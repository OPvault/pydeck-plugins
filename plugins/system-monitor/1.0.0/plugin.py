"""System Monitor plugin for PyDeck.

No third-party Python packages required. Data is read from kernel interfaces
and common system tools using the following fallback chains:

CPU usage  : /proc/stat (delta) → vmstat → mpstat → top  (selectable per button)
CPU temp   : /sys/class/hwmon   → /sys/class/thermal → sensors
RAM        : /proc/meminfo       → free                → top  (selectable per button)
Disk       : os.statvfs (kernel syscall) → df             (selectable per button)
GPU        : nvidia-smi (NVIDIA proprietary) → rocm-smi (AMD) → /sys/class/drm sysfs
             (NVIDIA nouveau · AMD · Intel — the same interface nvtop uses)

Color coding applied to the button background:
  blue   (#4f9cf9) — load < 60 % / temp < 65 °C  (healthy)
  orange (#f97316) — load 60–85 % / temp 65–85 °C (warm)
  red    (#ef4444) — load > 85 %  / temp > 85 °C  (critical)
  dark   (#0f172a) — data unavailable
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Colour / size constants ────────────────────────────────────────────────────

_COLOR_OK   = "#4f9cf9"
_COLOR_WARN = "#f97316"
_COLOR_CRIT = "#ef4444"
_COLOR_NONE = "#0f172a"

_TEXT_SIZE      = 16
_TEXT_SIZE_RAM  = 13
_TEXT_SIZE_DISK = 12


def _usage_color(pct: float) -> str:
    if pct >= 85:
        return _COLOR_CRIT
    if pct >= 60:
        return _COLOR_WARN
    return _COLOR_OK


def _temp_color(temp_c: float) -> str:
    if temp_c >= 85:
        return _COLOR_CRIT
    if temp_c >= 65:
        return _COLOR_WARN
    return _COLOR_OK


def _to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def _display(text: str, color: str, size: int = _TEXT_SIZE) -> Dict[str, Any]:
    return {"text": text, "color": color, "text_size": size}


def _run(cmd: List[str], timeout: int = 4) -> Tuple[bool, str]:
    """Run *cmd* and return (success, stdout). Never raises."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout,
        )
        return proc.returncode == 0, proc.stdout
    except Exception:
        return False, ""


# ══ CPU USAGE ══════════════════════════════════════════════════════════════════
#
# Chain: /proc/stat → vmstat → mpstat → top

_CPU_CHIPS = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal", "k8temp")

# State for /proc/stat delta calculation
_proc_stat_prev: Dict[str, Tuple[int, int]] = {}  # "cpu" → (total, idle)


def _cpu_via_proc_stat() -> Optional[float]:
    """/proc/stat: compute usage from idle-delta between consecutive polls.

    cpu  user nice system idle iowait irq softirq steal guest guest_nice
    usage = 1 - (Δidle / Δtotal)
    Returns None on the very first call (no previous sample yet).
    """
    try:
        text = Path("/proc/stat").read_text()
    except OSError:
        return None

    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        try:
            vals  = [int(x) for x in line.split()[1:]]
            idle  = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
            total = sum(vals)
        except (IndexError, ValueError):
            return None

        prev = _proc_stat_prev.get("cpu")
        _proc_stat_prev["cpu"] = (total, idle)

        if prev is None:
            return None  # first call — no delta yet; caller falls through

        d_total = total - prev[0]
        d_idle  = idle  - prev[1]
        if d_total <= 0:
            return None

        return round((1.0 - d_idle / d_total) * 100.0, 1)

    return None


def _cpu_via_vmstat() -> Optional[float]:
    """vmstat 1 2: take the second sample's idle column."""
    if not shutil.which("vmstat"):
        return None
    ok, out = _run(["vmstat", "1", "2"])
    if not ok:
        return None
    # Last non-empty line contains the second sample
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith(("procs", "r ", " r"))]
    if not lines:
        return None
    try:
        # Columns: r b swpd free buff cache si so bi bo in cs us sy id wa st
        parts = lines[-1].split()
        idle  = float(parts[14])   # %id column
        return round(100.0 - idle, 1)
    except (IndexError, ValueError):
        return None


def _cpu_via_mpstat() -> Optional[float]:
    """mpstat 1 1: parse %idle from the summary line."""
    if not shutil.which("mpstat"):
        return None
    ok, out = _run(["mpstat", "1", "1"])
    if not ok:
        return None
    for line in reversed(out.splitlines()):
        if "all" in line or re.search(r"\d+\.\d+", line):
            parts = line.split()
            # Last column is %idle
            try:
                idle = float(parts[-1])
                return round(100.0 - idle, 1)
            except (IndexError, ValueError):
                continue
    return None


def _cpu_via_top() -> Optional[float]:
    """top -bn1: parse %idle from the Cpu(s) summary line."""
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if re.search(r"%?Cpu", line, re.IGNORECASE):
            m = re.search(r"([\d.]+)\s+id", line)
            if m:
                return round(100.0 - float(m.group(1)), 1)
    return None


def _cpu_pct(backend: str = "auto") -> Optional[float]:
    """Return CPU usage % using the selected or best available source.

    htop has no batch/non-interactive output mode, so selecting "htop" routes
    to /proc/stat — the exact same kernel interface htop reads internally.
    """
    if backend in ("procstat", "htop"):
        return _cpu_via_proc_stat()
    if backend == "vmstat":
        return _cpu_via_vmstat()
    if backend == "mpstat":
        return _cpu_via_mpstat()
    if backend == "top":
        return _cpu_via_top()
    # auto: try all in order
    return (
        _cpu_via_proc_stat()
        or _cpu_via_vmstat()
        or _cpu_via_mpstat()
        or _cpu_via_top()
    )


# ══ CPU TEMPERATURE ════════════════════════════════════════════════════════════
#
# Chain: /sys/class/hwmon → /sys/class/thermal → sensors


def _temp_via_hwmon() -> Optional[float]:
    """/sys/class/hwmon: read temp*_input files, prefer known CPU chip names."""
    base = Path("/sys/class/hwmon")
    if not base.exists():
        return None

    cpu_temps: List[float] = []
    all_temps: List[float] = []

    for hwmon in sorted(base.iterdir()):
        try:
            name = (hwmon / "name").read_text().strip().lower()
        except OSError:
            name = ""
        is_cpu = any(name.startswith(k) for k in _CPU_CHIPS)

        for f in sorted(hwmon.glob("temp*_input")):
            try:
                val = int(f.read_text().strip()) / 1000.0
                all_temps.append(val)
                if is_cpu:
                    cpu_temps.append(val)
            except (OSError, ValueError):
                pass

    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _temp_via_thermal_zone() -> Optional[float]:
    """/sys/class/thermal/thermal_zone*: prefer zones typed as CPU/SoC."""
    base = Path("/sys/class/thermal")
    if not base.exists():
        return None

    cpu_temps: List[float] = []
    all_temps: List[float] = []

    for zone in sorted(base.glob("thermal_zone*")):
        try:
            zone_type = (zone / "type").read_text().strip().lower()
            raw       = int((zone / "temp").read_text().strip())
            val       = raw / 1000.0
            all_temps.append(val)
            if any(k in zone_type for k in ("cpu", "pkg", "soc", "core", "x86")):
                cpu_temps.append(val)
        except (OSError, ValueError):
            pass

    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _temp_via_sensors() -> Optional[float]:
    """sensors -j: parse *_input fields, prefer known CPU chip names."""
    if not shutil.which("sensors"):
        return None
    ok, out = _run(["sensors", "-j"])
    if not ok or not out.strip():
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None

    cpu_temps: List[float] = []
    all_temps: List[float] = []

    for chip_name, chip in data.items():
        if not isinstance(chip, dict):
            continue
        is_cpu = any(chip_name.lower().startswith(k) for k in _CPU_CHIPS)
        for feat_name, feat in chip.items():
            if feat_name == "Adapter" or not isinstance(feat, dict):
                continue
            for sub_key, val in feat.items():
                if sub_key.endswith("_input") and isinstance(val, (int, float)):
                    temp = float(val)
                    all_temps.append(temp)
                    if is_cpu:
                        cpu_temps.append(temp)

    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _cpu_temp_c() -> Optional[float]:
    """Return the highest CPU temperature in °C using the best available source."""
    return (
        _temp_via_hwmon()
        or _temp_via_thermal_zone()
        or _temp_via_sensors()
    )


# ══ RAM ════════════════════════════════════════════════════════════════════════
#
# Chain: /proc/meminfo → free → top
#
# All return (used_gib, total_gib, pct) or None.

def _ram_via_proc_meminfo() -> Optional[Tuple[float, float, float]]:
    """/proc/meminfo: always available on Linux.

    Uses MemAvailable for "free" (accounts for reclaimable caches) so the
    reading matches what htop and free show.
    """
    try:
        kv: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                kv[parts[0].rstrip(":")] = int(parts[1])  # kB

        total_kb = kv["MemTotal"]
        avail_kb = kv.get("MemAvailable", kv.get("MemFree", 0))
        used_kb  = total_kb - avail_kb
        pct      = round(used_kb / total_kb * 100.0, 1)
        factor   = 1024 ** 2  # kB → GiB
        return (used_kb / factor, total_kb / factor, pct)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def _ram_via_free() -> Optional[Tuple[float, float, float]]:
    """free -b: parse the Mem: row (total and available columns)."""
    if not shutil.which("free"):
        return None
    ok, out = _run(["free", "-b"])
    if not ok:
        return None
    for line in out.splitlines():
        if not line.startswith("Mem:"):
            continue
        try:
            parts = line.split()
            total = float(parts[1])
            avail = float(parts[6]) if len(parts) > 6 else float(parts[3])
            used  = total - avail
            pct   = round(used / total * 100.0, 1)
            gib   = 1024 ** 3
            return (used / gib, total / gib, pct)
        except (IndexError, ValueError, ZeroDivisionError):
            return None
    return None


def _ram_via_top() -> Optional[Tuple[float, float, float]]:
    """top -bn1: parse the MiB/KiB Mem summary line."""
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if "Mem" not in line or "total" not in line:
            continue
        m_total = re.search(r"([\d.]+)\s+total", line)
        m_used  = re.search(r"([\d.]+)\s+used",  line)
        if not (m_total and m_used):
            continue
        try:
            factor      = 1024 ** 3 if "GiB" in line else (1024 if "KiB" in line else 1024 ** 2)
            total_bytes = float(m_total.group(1)) * factor
            used_bytes  = float(m_used.group(1))  * factor
            pct         = round(used_bytes / total_bytes * 100.0, 1)
            gib         = 1024 ** 3
            return (used_bytes / gib, total_bytes / gib, pct)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _ram_stats(backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) using the selected or best available source.

    htop has no batch/non-interactive output mode, so selecting "htop" routes
    to /proc/meminfo — the exact same kernel interface htop reads internally.
    """
    if backend in ("procmeminfo", "htop"):
        return _ram_via_proc_meminfo()
    if backend == "free":
        return _ram_via_free()
    if backend == "top":
        return _ram_via_top()
    # auto: try all in order
    return (
        _ram_via_proc_meminfo()
        or _ram_via_free()
        or _ram_via_top()
    )


# ══ GPU ════════════════════════════════════════════════════════════════════════
#
# Chain: nvidia-smi → rocm-smi → /sys/class/drm (nvtop / AMD / Intel)

def _nvidia_info() -> Optional[Tuple[float, float]]:
    """nvidia-smi: temperature and utilisation for NVIDIA GPUs."""
    if not shutil.which("nvidia-smi"):
        return None
    ok, out = _run(["nvidia-smi",
                    "--query-gpu=temperature.gpu,utilization.gpu",
                    "--format=csv,noheader,nounits"])
    if not ok or not out.strip():
        return None
    try:
        parts = out.strip().splitlines()[0].split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    except (IndexError, ValueError):
        return None


def _amd_info() -> Optional[Tuple[float, float]]:
    """rocm-smi: temperature and utilisation for AMD GPUs."""
    if not shutil.which("rocm-smi"):
        return None
    ok, out = _run(["rocm-smi", "--showtemp", "--showuse", "--csv"])
    if not ok or not out.strip():
        return None
    try:
        lines = [l for l in out.strip().splitlines()
                 if l and not l.startswith("#")]
        for row in lines[1:]:
            parts = row.split(",")
            if len(parts) >= 3:
                return float(parts[1].strip()), float(parts[2].strip())
    except (IndexError, ValueError):
        pass
    return None


def _sysfs_gpu_info() -> Optional[Tuple[float, float]]:
    """/sys/class/drm sysfs: temperature + utilisation for NVIDIA/AMD/Intel GPUs.

    This is the same kernel interface nvtop reads internally, so it works
    without any vendor tool installed.

    Supported drivers:
      NVIDIA  — nouveau (open-source) exposes hwmon + gpu_busy_percent
      AMD     — amdgpu exposes hwmon + gpu_busy_percent
      Intel   — i915/xe exposes hwmon + gpu_busy_percent

    Note: the proprietary NVIDIA driver does not expose sysfs; use nvidia-smi
    (already tried first in the auto chain) for that case.

    temp:    card/device/hwmon/hwmonN/temp1_input  (millidegrees → °C)
    util %:  card/device/gpu_busy_percent
    """
    drm = Path("/sys/class/drm")
    if not drm.exists():
        return None

    for card in sorted(drm.glob("card[0-9]*")):
        device = card / "device"
        if not device.is_dir():
            continue

        temp_c: Optional[float] = None
        for hwmon in sorted(device.glob("hwmon/hwmon*")):
            f = hwmon / "temp1_input"
            if f.exists():
                try:
                    temp_c = int(f.read_text().strip()) / 1000.0
                    break
                except (OSError, ValueError):
                    pass

        if temp_c is None:
            continue

        util_pct = 0.0
        bp = device / "gpu_busy_percent"
        if bp.exists():
            try:
                util_pct = float(bp.read_text().strip())
            except (OSError, ValueError):
                pass

        return temp_c, util_pct

    return None


# ══ DISK ═══════════════════════════════════════════════════════════════════════

def _disk_via_statvfs(path: str) -> Optional[Tuple[float, float, float]]:
    """os.statvfs: direct kernel syscall — no subprocess, always available."""
    try:
        st         = os.statvfs(path)
        total_bytes = st.f_frsize * st.f_blocks
        free_bytes  = st.f_frsize * st.f_bavail   # available to non-root
        used_bytes  = total_bytes - free_bytes
        pct         = round(used_bytes / total_bytes * 100.0, 1)
        gib         = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (OSError, ZeroDivisionError):
        return None


def _disk_via_df(path: str) -> Optional[Tuple[float, float, float]]:
    """df -B1: return (used_gib, total_gib, pct) for *path*."""
    ok, out = _run(["df", "-B1", path])
    if not ok or not out.strip():
        return None
    try:
        lines     = out.strip().splitlines()
        data_line = " ".join(lines[1:])   # handles long filesystem names
        parts     = data_line.split()
        # Columns: Filesystem 1B-blocks Used Available Use% Mounted
        total_bytes = float(parts[1])
        used_bytes  = float(parts[2])
        pct         = float(parts[4].rstrip("%"))
        gib         = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (IndexError, ValueError):
        return None


def _disk_stats(path: str, backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) using the selected or best available source."""
    if backend == "statvfs":
        return _disk_via_statvfs(path)
    if backend == "df":
        return _disk_via_df(path)
    # auto: prefer the zero-subprocess statvfs, fall back to df
    return _disk_via_statvfs(path) or _disk_via_df(path)


# ══ BUTTON HANDLERS ════════════════════════════════════════════════════════════

# ── CPU Monitor ────────────────────────────────────────────────────────────────

def _read_cpu(config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        pct = _cpu_pct(str(config.get("cpu_backend", "auto")))
        if pct is None:
            return {"success": False, "error": "All CPU sources failed",
                    "display_update": _display("CPU\nERR", _COLOR_NONE)}

        show_temp = bool(config.get("show_temp", True))
        use_f     = config.get("temp_unit", "C") == "F"
        lines     = ["CPU", f"{pct:.0f}%"]

        if show_temp:
            temp_c = _cpu_temp_c()
            if temp_c is not None:
                temp_str = (f"{_to_f(temp_c):.0f}°F" if use_f
                            else f"{temp_c:.0f}°C")
                lines.append(temp_str)
                color = _temp_color(temp_c)
            else:
                color = _usage_color(pct)
        else:
            color = _usage_color(pct)

        return {"success": True,
                "display_update": _display("\n".join(lines), color)}
    except Exception as exc:
        return {"success": False, "error": str(exc),
                "display_update": _display("CPU\nERR", _COLOR_NONE)}


def cpu_monitor(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the CPU button."""
    return _read_cpu(config)


def poll_cpu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update CPU button every 2 s."""
    return _read_cpu(config)


# ── RAM Monitor ────────────────────────────────────────────────────────────────

def _read_ram(config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ram = _ram_stats(str(config.get("ram_backend", "auto")))
        if ram is None:
            return {"success": False, "error": "All RAM sources failed",
                    "display_update": _display("RAM\nERR", _COLOR_NONE, _TEXT_SIZE_RAM)}

        used_gib, total_gib, pct = ram
        show_used = bool(config.get("show_used", True))

        if show_used:
            lines = ["RAM", f"{used_gib:.1f}/{total_gib:.0f}G", f"{pct:.0f}%"]
        else:
            lines = ["RAM", f"{pct:.0f}%"]

        return {"success": True,
                "display_update": _display("\n".join(lines), _usage_color(pct), _TEXT_SIZE_RAM)}
    except Exception as exc:
        return {"success": False, "error": str(exc),
                "display_update": _display("RAM\nERR", _COLOR_NONE, _TEXT_SIZE_RAM)}


def ram_monitor(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the RAM button."""
    return _read_ram(config)


def poll_ram(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update RAM button every 2 s."""
    return _read_ram(config)


# ── GPU Monitor ────────────────────────────────────────────────────────────────

def _read_gpu(config: Dict[str, Any]) -> Dict[str, Any]:
    backend    = str(config.get("gpu_backend", "auto"))
    use_f      = config.get("temp_unit", "C") == "F"
    show_usage = bool(config.get("show_usage", True))

    info: Optional[Tuple[float, float]] = None
    if backend in ("auto", "nvidia"):
        info = _nvidia_info()
    if info is None and backend in ("auto", "amd"):
        info = _amd_info()
    if info is None and backend in ("auto", "nvtop"):
        info = _sysfs_gpu_info()

    if info is None:
        return {"success": False,
                "error": "No GPU data source found (nvidia-smi / rocm-smi / sysfs — see backend option)",
                "display_update": _display("GPU\nN/A", _COLOR_NONE)}

    temp_c, util_pct = info
    temp_str = (f"{_to_f(temp_c):.0f}°F" if use_f else f"{temp_c:.0f}°C")
    lines = ["GPU", temp_str]
    if show_usage:
        lines.append(f"{util_pct:.0f}%")

    return {"success": True,
            "display_update": _display("\n".join(lines), _temp_color(temp_c))}


def gpu_monitor(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the GPU button."""
    return _read_gpu(config)


def poll_gpu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update GPU button every 3 s."""
    return _read_gpu(config)


# ── Disk Monitor ───────────────────────────────────────────────────────────────

def _read_disk(config: Dict[str, Any]) -> Dict[str, Any]:
    path = str(config.get("path") or "/")
    try:
        stats = _disk_stats(path, str(config.get("disk_backend", "auto")))
        if stats is None:
            return {"success": False, "error": f"df failed for {path!r}",
                    "display_update": _display("Disk\nERR", _COLOR_NONE, _TEXT_SIZE_DISK)}

        used_gib, total_gib, pct = stats
        if total_gib >= 1024:
            size_str = f"{used_gib/1024:.1f}/{total_gib/1024:.1f}T"
        else:
            size_str = f"{used_gib:.0f}/{total_gib:.0f}G"
        lines = ["Disk", size_str, f"{pct:.0f}%"]

        return {"success": True,
                "display_update": _display("\n".join(lines), _usage_color(pct), _TEXT_SIZE_DISK)}
    except Exception as exc:
        return {"success": False, "error": str(exc),
                "display_update": _display("Disk\nERR", _COLOR_NONE, _TEXT_SIZE_DISK)}


def disk_monitor(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the Disk button."""
    return _read_disk(config)


def poll_disk(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update Disk button every 10 s."""
    return _read_disk(config)
