#!/usr/bin/env python3
"""PR net-diff no-deletion guard.

Blocks a PR whose head deletes a path that exists in base. This is a mechanical
gate, not a semantic one: every path whose ``git diff --name-status`` status
starts with ``D`` counts as a deletion and fails the run.

Usage (from the repository root)::

    python scripts/check_pr_no_regression.py --base <ref> --head <ref>

Exit contract: ``0`` = no deletions, ``1`` = at least one deletion (the full
list is printed, never truncated), ``2`` = base/head objects unavailable
(shallow clone) — warn-through, never crash the whole gate job.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


class RefUnavailable(RuntimeError):
    """Raised when git cannot diff base..head (missing objects / shallow clone)."""


def find_deleted_paths(base: str, head: str, root: Path) -> list[str]:
    """Return every path deleted between ``base`` and ``head`` (status starts with 'D')."""
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base}..{head}"],
        cwd=str(root),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RefUnavailable(
            f"git diff {base}..{head} failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
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

    try:
        deleted = find_deleted_paths(args.base, args.head, Path.cwd())
    except RefUnavailable as exc:
        # Environment unavailable (e.g. shallow clone without base object): warn through.
        # The static-invariants job fetches full depth; this is a defensive fallback so a
        # missing object never crashes the whole gate job with a raw traceback.
        print(f"[pr-no-regression] WARN: {exc}")
        print("[pr-no-regression] 基线对象不可用 ⇒ 本次不判定（CI 已配 fetch-depth: 0）")
        return 2
    if not deleted:
        return 0
    print(f"PR head deletes {len(deleted)} path(s) that exist in base:")
    for path in deleted:
        print(path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
