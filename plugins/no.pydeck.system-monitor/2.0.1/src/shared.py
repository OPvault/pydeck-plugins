"""Shared utilities for PDK System Monitor.

Data backends for CPU, RAM, GPU, and Disk — no third-party packages.

CPU usage  : /proc/stat (delta) → vmstat → mpstat → top
CPU temp   : /sys/class/hwmon → /sys/class/thermal → sensors
RAM        : /proc/meminfo → free → top
Disk       : os.statvfs → df
GPU        : nvidia-smi → rocm-smi → /sys/class/drm sysfs
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Colour constants ─────────────────────────────────────────────────────────

COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_CRIT = "#f85149"


def usage_color(pct: float) -> str:
    if pct >= 85:
        return COLOR_CRIT
    if pct >= 60:
        return COLOR_WARN
    return COLOR_OK


def temp_color(temp_c: float) -> str:
    if temp_c >= 85:
        return COLOR_CRIT
    if temp_c >= 65:
        return COLOR_WARN
    return COLOR_OK


def val_class(color: str) -> str:
    if color == COLOR_CRIT:
        return "value-crit"
    if color == COLOR_WARN:
        return "value-warn"
    return "value-ok"


def sub_class(color: str) -> str:
    if color == COLOR_CRIT:
        return "sub-crit"
    if color == COLOR_WARN:
        return "sub-warn"
    return "sub-ok"


def to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def _run(cmd: List[str], timeout: int = 4) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout,
        )
        return proc.returncode == 0, proc.stdout
    except Exception:
        return False, ""


# ══ CPU USAGE ═════════════════════════════════════════════════════════════════

_CPU_CHIPS = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal", "k8temp")
_proc_stat_prev: Dict[str, Tuple[int, int]] = {}


def _cpu_via_proc_stat() -> Optional[float]:
    try:
        text = Path("/proc/stat").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        try:
            vals = [int(x) for x in line.split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
        except (IndexError, ValueError):
            return None
        prev = _proc_stat_prev.get("cpu")
        _proc_stat_prev["cpu"] = (total, idle)
        if prev is None:
            return None
        d_total = total - prev[0]
        d_idle = idle - prev[1]
        if d_total <= 0:
            return None
        return round((1.0 - d_idle / d_total) * 100.0, 1)
    return None


def _cpu_via_vmstat() -> Optional[float]:
    if not shutil.which("vmstat"):
        return None
    ok, out = _run(["vmstat", "1", "2"])
    if not ok:
        return None
    lines = [l for l in out.splitlines()
             if l.strip() and not l.startswith(("procs", "r ", " r"))]
    if not lines:
        return None
    try:
        parts = lines[-1].split()
        idle = float(parts[14])
        return round(100.0 - idle, 1)
    except (IndexError, ValueError):
        return None


def _cpu_via_mpstat() -> Optional[float]:
    if not shutil.which("mpstat"):
        return None
    ok, out = _run(["mpstat", "1", "1"])
    if not ok:
        return None
    for line in reversed(out.splitlines()):
        if "all" in line or re.search(r"\d+\.\d+", line):
            parts = line.split()
            try:
                idle = float(parts[-1])
                return round(100.0 - idle, 1)
            except (IndexError, ValueError):
                continue
    return None


def _cpu_via_top() -> Optional[float]:
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if re.search(r"%?Cpu", line, re.IGNORECASE):
            m = re.search(r"([\d.]+)\s+id", line)
            if m:
                return round(100.0 - float(m.group(1)), 1)
    return None


def cpu_pct(backend: str = "auto") -> Optional[float]:
    """Return CPU usage % using the selected or best available source."""
    if backend in ("procstat", "htop"):
        return _cpu_via_proc_stat()
    if backend == "vmstat":
        return _cpu_via_vmstat()
    if backend == "mpstat":
        return _cpu_via_mpstat()
    if backend == "top":
        return _cpu_via_top()
    return (
        _cpu_via_proc_stat()
        or _cpu_via_vmstat()
        or _cpu_via_mpstat()
        or _cpu_via_top()
    )


# ══ CPU TEMPERATURE ══════════════════════════════════════════════════════════

def _temp_via_hwmon() -> Optional[float]:
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
    base = Path("/sys/class/thermal")
    if not base.exists():
        return None
    cpu_temps: List[float] = []
    all_temps: List[float] = []
    for zone in sorted(base.glob("thermal_zone*")):
        try:
            zone_type = (zone / "type").read_text().strip().lower()
            raw = int((zone / "temp").read_text().strip())
            val = raw / 1000.0
            all_temps.append(val)
            if any(k in zone_type for k in ("cpu", "pkg", "soc", "core", "x86")):
                cpu_temps.append(val)
        except (OSError, ValueError):
            pass
    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _temp_via_sensors() -> Optional[float]:
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


def cpu_temp_c() -> Optional[float]:
    """Return the highest CPU temperature in °C."""
    return (
        _temp_via_hwmon()
        or _temp_via_thermal_zone()
        or _temp_via_sensors()
    )


# ══ RAM ══════════════════════════════════════════════════════════════════════

def _ram_via_proc_meminfo() -> Optional[Tuple[float, float, float]]:
    try:
        kv: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                kv[parts[0].rstrip(":")] = int(parts[1])
        total_kb = kv["MemTotal"]
        avail_kb = kv.get("MemAvailable", kv.get("MemFree", 0))
        used_kb = total_kb - avail_kb
        pct = round(used_kb / total_kb * 100.0, 1)
        factor = 1024 ** 2
        return (used_kb / factor, total_kb / factor, pct)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def _ram_via_free() -> Optional[Tuple[float, float, float]]:
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
            used = total - avail
            pct = round(used / total * 100.0, 1)
            gib = 1024 ** 3
            return (used / gib, total / gib, pct)
        except (IndexError, ValueError, ZeroDivisionError):
            return None
    return None


def _ram_via_top() -> Optional[Tuple[float, float, float]]:
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if "Mem" not in line or "total" not in line:
            continue
        m_total = re.search(r"([\d.]+)\s+total", line)
        m_used = re.search(r"([\d.]+)\s+used", line)
        if not (m_total and m_used):
            continue
        try:
            factor = 1024 ** 3 if "GiB" in line else (1024 if "KiB" in line else 1024 ** 2)
            total_bytes = float(m_total.group(1)) * factor
            used_bytes = float(m_used.group(1)) * factor
            pct = round(used_bytes / total_bytes * 100.0, 1)
            gib = 1024 ** 3
            return (used_bytes / gib, total_bytes / gib, pct)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def ram_stats(backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) using the best available source."""
    if backend in ("procmeminfo", "htop"):
        return _ram_via_proc_meminfo()
    if backend == "free":
        return _ram_via_free()
    if backend == "top":
        return _ram_via_top()
    return (
        _ram_via_proc_meminfo()
        or _ram_via_free()
        or _ram_via_top()
    )


# ══ GPU ══════════════════════════════════════════════════════════════════════

def nvidia_info() -> Optional[Tuple[float, float]]:
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


def amd_info() -> Optional[Tuple[float, float]]:
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


def sysfs_gpu_info() -> Optional[Tuple[float, float]]:
    """/sys/class/drm sysfs: temp + utilisation (nouveau/AMD/Intel)."""
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


# ══ DISK ═════════════════════════════════════════════════════════════════════

def _disk_via_statvfs(path: str) -> Optional[Tuple[float, float, float]]:
    try:
        st = os.statvfs(path)
        total_bytes = st.f_frsize * st.f_blocks
        free_bytes = st.f_frsize * st.f_bavail
        used_bytes = total_bytes - free_bytes
        pct = round(used_bytes / total_bytes * 100.0, 1)
        gib = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (OSError, ZeroDivisionError):
        return None


def _disk_via_df(path: str) -> Optional[Tuple[float, float, float]]:
    ok, out = _run(["df", "-B1", path])
    if not ok or not out.strip():
        return None
    try:
        lines = out.strip().splitlines()
        data_line = " ".join(lines[1:])
        parts = data_line.split()
        total_bytes = float(parts[1])
        used_bytes = float(parts[2])
        pct = float(parts[4].rstrip("%"))
        gib = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (IndexError, ValueError):
        return None


def disk_stats(path: str, backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) for the given mount point."""
    if backend == "statvfs":
        return _disk_via_statvfs(path)
    if backend == "df":
        return _disk_via_df(path)
    return _disk_via_statvfs(path) or _disk_via_df(path)
