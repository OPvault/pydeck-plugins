#!/usr/bin/env python3
"""Promote canary → stable and restore the canary label.

Steps
-----
1. Verify the working tree is clean and we are on canary.
2. Regenerate manifest.json with label "Official · Stable".
3. Commit that change on canary.
4. Merge canary into stable (fast-forward).
5. Push stable.
6. Switch back to canary.
7. Regenerate manifest.json with label "Official · Canary".
8. Commit and push canary.

Usage
-----
    python release_stable.py [--stable-label TEXT] [--canary-label TEXT] [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent
GENERATOR     = REPO_ROOT / "generate_manifest.py"
DEFAULT_STABLE = "Official · Stable"
DEFAULT_CANARY = "Official · Canary"


def run(cmd: list[str], dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        print(f"\nERROR: command failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result


def current_branch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return r.stdout.strip()


def working_tree_clean() -> bool:
    """True when there are no staged or unstaged changes to tracked files."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        if not line.startswith("??"):   # ignore untracked files
            return False
    return True


def generate(label: str, dry_run: bool) -> None:
    run(["python3", str(GENERATOR), "--label", label], dry_run=dry_run)


def release(stable_label: str, canary_label: str, dry_run: bool) -> None:
    # ── Pre-flight checks ──────────────────────────────────────────────────────
    branch = current_branch()
    if branch != "canary":
        print(f"ERROR: must be on 'canary' branch (currently on '{branch}')", file=sys.stderr)
        sys.exit(1)

    if not working_tree_clean():
        print("ERROR: working tree has uncommitted changes — commit or stash them first.", file=sys.stderr)
        sys.exit(1)

    print(f"\n── Step 1: set manifest label → \"{stable_label}\"")
    generate(stable_label, dry_run)

    print(f"\n── Step 2: commit on canary")
    run(["git", "add", "manifest.json"], dry_run=dry_run)
    run(["git", "commit", "-m", f"chore: set manifest label to {stable_label}"], dry_run=dry_run)

    print(f"\n── Step 3: merge canary → stable")
    run(["git", "checkout", "stable"], dry_run=dry_run)
    run(["git", "merge", "canary", "--ff-only"], dry_run=dry_run)

    print(f"\n── Step 4: push stable")
    run(["git", "push", "origin", "stable"], dry_run=dry_run)

    print(f"\n── Step 5: switch back to canary")
    run(["git", "checkout", "canary"], dry_run=dry_run)

    print(f"\n── Step 6: restore manifest label → \"{canary_label}\"")
    generate(canary_label, dry_run)

    print(f"\n── Step 7: commit and push canary")
    run(["git", "add", "manifest.json"], dry_run=dry_run)
    run(["git", "commit", "-m", f"chore: restore manifest label to {canary_label}"], dry_run=dry_run)
    run(["git", "push", "origin", "canary"], dry_run=dry_run)

    print(f"\n{'[dry-run] ' if dry_run else ''}Done — stable is up to date, canary label restored.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote canary → stable and restore the canary label.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stable-label", default=DEFAULT_STABLE,
                        help=f'Label to write before merging (default: "{DEFAULT_STABLE}")')
    parser.add_argument("--canary-label", default=DEFAULT_CANARY,
                        help=f'Label to restore on canary after merge (default: "{DEFAULT_CANARY}")')
    parser.add_argument("--dry-run", action="store_true",
                        help="Print all steps without executing any git commands or file writes")
    args = parser.parse_args()
    release(args.stable_label, args.canary_label, args.dry_run)


if __name__ == "__main__":
    main()
