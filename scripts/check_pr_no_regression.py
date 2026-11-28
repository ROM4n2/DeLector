#!/usr/bin/env python3
"""PR net-diff no-deletion guard.

Blocks a PR whose head deletes a path that exists in base. This is a mechanical
gate, not a semantic one: every path whose ``git diff --name-status`` status
starts with ``D`` counts as a deletion unless it is explicitly registered in
``scripts/pr_no_regression_allowlist.json`` with a reason.

The allowlist is an intentional-deletion registry, not a bypass switch: entries
are path + reason pairs, malformed entries are a config error, and every other
deletion still fails the run.

Usage (from the repository root)::

    python scripts/check_pr_no_regression.py --base <ref> --head <ref>

Exit contract: ``0`` = no undocumented deletions, ``1`` = at least one
undocumented deletion (the full list is printed, never truncated), ``2`` =
base/head objects unavailable (shallow clone) or malformed allowlist —
warn-through/fail-loud, never crash the whole gate job with a traceback.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ALLOWLIST_REL = Path("scripts") / "pr_no_regression_allowlist.json"


class RefUnavailable(RuntimeError):
    """Raised when git cannot diff base..head (missing objects / shallow clone)."""


class AllowlistError(RuntimeError):
    """Raised when the intentional-deletion registry is malformed."""


def load_allowlist(root: Path) -> dict[str, str]:
    """Return ``path -> reason`` from the intentional-deletion registry.

    Missing file means "no exemptions" (strict default); a present but malformed
    file is a config error so a broken registry can never silently widen the gate.
    """
    path = root / ALLOWLIST_REL
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistError(f"无法读取删除白名单 {ALLOWLIST_REL}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("version") != "1.0.0"
        or not isinstance(data.get("entries"), list)
    ):
        raise AllowlistError(f"{ALLOWLIST_REL} 必须是 version=1.0.0 且含 entries 数组")
    result: dict[str, str] = {}
    for index, entry in enumerate(data["entries"]):
        if not isinstance(entry, dict):
            raise AllowlistError(f"{ALLOWLIST_REL} entries[{index}] 必须是对象")
        deleted_path = entry.get("path")
        reason = entry.get("reason")
        if not isinstance(deleted_path, str) or not deleted_path.strip():
            raise AllowlistError(f"{ALLOWLIST_REL} entries[{index}].path 缺失或为空")
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistError(f"{ALLOWLIST_REL} entries[{index}].reason 缺失或为空")
        result[deleted_path] = reason
    return result


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

    root = Path.cwd()
    try:
        allowlist = load_allowlist(root)
    except AllowlistError as exc:
        print(f"[pr-no-regression] CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        deleted = find_deleted_paths(args.base, args.head, root)
    except RefUnavailable as exc:
        # Environment unavailable (e.g. shallow clone without base object): warn through.
        # The static-invariants job fetches full depth; this is a defensive fallback so a
        # missing object never crashes the whole gate job with a raw traceback.
        print(f"[pr-no-regression] WARN: {exc}")
        print("[pr-no-regression] 基线对象不可用 ⇒ 本次不判定（CI 已配 fetch-depth: 0）")
        return 2
    allowed = [(path, allowlist[path]) for path in deleted if path in allowlist]
    unexpected = [path for path in deleted if path not in allowlist]
    if allowed:
        print(f"PR head deletes {len(allowed)} documented path(s) (allowed):")
        for path, reason in allowed:
            print(f"{path} :: {reason}")
    if not unexpected:
        return 0
    print(f"PR head deletes {len(unexpected)} undocumented path(s) that exist in base:")
    for path in unexpected:
        print(path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
