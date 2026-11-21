#!/usr/bin/env python3
"""PR net-diff no-deletion guard.

Blocks a PR whose head deletes a path that exists in base. This is a mechanical
gate, not a semantic one: every path whose ``git diff --name-status`` status
starts with ``D`` counts as a deletion and fails the run.

Usage (from the repository root)::

    python scripts/check_pr_no_regression.py --base <ref> --head <ref>

Exit contract: ``0`` = no deletions, ``1`` = at least one deletion (the full
list is printed, never truncated).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_deleted_paths(base: str, head: str, root: Path) -> list[str]:
    """Return every path deleted between ``base`` and ``head`` (status starts with 'D')."""
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base}..{head}"],
        cwd=str(root),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    deleted: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[0].startswith("D"):
            continue
        deleted.append(parts[1])
    return deleted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", required=True, help="Base ref (PR base SHA)")
    ap.add_argument("--head", required=True, help="Head ref (PR head SHA)")
    args = ap.parse_args(argv)

    deleted = find_deleted_paths(args.base, args.head, Path.cwd())
    if not deleted:
        return 0
    print(f"PR head deletes {len(deleted)} path(s) that exist in base:")
    for path in deleted:
        print(path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
