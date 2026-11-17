#!/usr/bin/env python3
"""Repository hygiene gate: large files, module bloat, host paths, conflicts, and AST.

Thresholds align with upstream community standards:
- 500 KB default file size cap (``pre-commit/pre-commit-hooks`` ``check-added-large-files``)
- 1,000 lines max per source module (``pylint`` ``C0302 / max-module-lines``)
- Merge conflict markers & broken symlinks (``pre-commit/pre-commit-hooks``)
- Hardcoded machine-local absolute paths (repo portability)
- Context / hot-memory file budgets (``AGENTS.md`` <= 80 lines / 8 KB, ``WORKMEMORY/work.log``
  <= 150 lines / 24 KB)

Configuration is optional and additive. If ``data/repo_hygiene.json`` exists, its keys override the
defaults::

    {
      "max_bytes": 524288,
      "large_file_patterns": {"data/raw/**": 5242880, "docs/problem/**": 5242880},
      "max_source_lines": 1000,
      "context_budgets": {"AGENTS.md": [80, 8192], "WORKMEMORY/work.log": [150, 24576]}
    }

Everything here is stdlib-only on purpose: this file runs from a pre-commit hook in projects that
may not have any virtualenv yet, so it must never import a third-party package.

Escape hatches are line-scoped pragmas, not global switches:
    git:allow-large-file / git:allow-bloat / git:allow-abs-path / git:allow-conflict-marker
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MAX_BYTES = 500 * 1024  # 500 KB (pre-commit-hooks standard)
DEFAULT_MAX_SOURCE_LINES = 1000  # pylint C0302 max-module-lines default
SOURCE_SUFFIXES = frozenset({".py", ".typ", ".sh", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"})

DEFAULT_CONTEXT_BUDGETS: dict[str, tuple[int, int]] = {
    "AGENTS.md": (80, 8 * 1024),
    "WORKMEMORY/work.log": (150, 24 * 1024),
}

# `.gitattributes` rules whose absence silently un-pins the hook. Checked against the file's text
# because git normalizes eol=lf files on `add`, so a staged-blob CRLF scan can never fire for them —
# the pin itself is the invariant that can be verified, and the one whose loss causes the failure.
REQUIRED_GITATTRIBUTES_PINS: tuple[str, ...] = (
    ".githooks/** text eol=lf",
    "WORKMEMORY/** text eol=lf",
)

CONFIG_PATH = Path("data") / "repo_hygiene.json"

# Machine-local absolute paths. Deliberately narrow: it targets the well-known user/workspace
# roots, not every drive-letter string, so version numbers and URLs do not trip it. `$WIKI_PATH`,
# `~` and `%LOCALAPPDATA%` forms are portable and therefore NOT matched.
HOST_PATH_RE = re.compile(
    "(?:"
    r"(?<![A-Za-z0-9_])[A-Za-z]:(?:/|\\{1,2})(?:Users|Code|WorkSpace|Obsidian|Desktop|Documents"
    r"|Downloads|AppData|ProgramData|Program Files|Java|Android)(?:/|\\{1,2}|$)"
    "|"
    r"""(?:^|[\s"'`(])(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|/[cde]/(?:Users|Code|WorkSpace)/)"""
    "|"
    r"file:///(?:[A-Za-z]:|Users/|home/)"
    ")"
)  # git:allow-abs-path

CONFLICT_RE = re.compile(r"^(?:<{7} |>{7} |={7}$)")


def load_config(root: Path) -> dict[str, object]:
    """Read optional per-repo overrides; a malformed config is a hard error, never a silent skip."""
    cfg: dict[str, object] = {}
    path = root / CONFIG_PATH
    if not path.is_file():
        return cfg
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[FAIL] {CONFIG_PATH.as_posix()} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(loaded, dict):
        print(f"[FAIL] {CONFIG_PATH.as_posix()} must contain a JSON object", file=sys.stderr)
        raise SystemExit(2)
    cfg.update(loaded)
    return cfg


def _patterns_from(cfg: dict[str, object]) -> dict[str, int]:
    raw = cfg.get("large_file_patterns")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for pattern, limit in raw.items():
        if isinstance(pattern, str) and isinstance(limit, (int, float)) and limit > 0:
            out[pattern] = int(limit)
    return out


def _budgets_from(cfg: dict[str, object]) -> dict[str, tuple[int, int]]:
    raw = cfg.get("context_budgets")
    if not isinstance(raw, dict):
        return dict(DEFAULT_CONTEXT_BUDGETS)
    budgets = dict(DEFAULT_CONTEXT_BUDGETS)
    for name, pair in raw.items():
        if not isinstance(name, str) or not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        lines, size = pair
        if isinstance(lines, (int, float)) and isinstance(size, (int, float)):
            budgets[name] = (int(lines), int(size))
    return budgets


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _size_limit(norm_rel: str, max_bytes: int, patterns: dict[str, int]) -> int:
    """Per-path size cap: a matching pattern can only raise the default, never lower it."""
    limit = max_bytes
    posix = PurePosixPath(norm_rel)
    for pattern, pattern_limit in patterns.items():
        if posix.match(pattern):
            limit = max(limit, pattern_limit)
    return limit


def _check_line_rules(norm_rel: str, lines: list[str]) -> list[str]:
    """Conflict markers and hardcoded host paths, line by line."""
    failures: list[str] = []
    for lineno, line in enumerate(lines, 1):
        if "git:allow-conflict-marker" not in line and CONFLICT_RE.match(line):
            failures.append(f"[CONFLICT] {norm_rel}:{lineno}: unresolved merge conflict marker")
        if "git:allow-abs-path" not in line and HOST_PATH_RE.search(line):
            failures.append(
                f"[ABS_PATH] {norm_rel}:{lineno}: hardcoded machine-local absolute path "
                "(use relative path or add 'git:allow-abs-path')"
            )
    return failures


def check_blob(
    rel: str,
    data: bytes,
    *,
    disk_path: Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    large_file_patterns: dict[str, int] | None = None,
    max_source_lines: int = DEFAULT_MAX_SOURCE_LINES,
    context_budgets: dict[str, tuple[int, int]] | None = None,
) -> list[str]:
    """Audit one tracked/staged file's bytes and return violation messages."""
    failures: list[str] = []
    norm_rel = rel.replace("\\", "/")
    patterns = large_file_patterns or {}
    budgets = context_budgets if context_budgets is not None else DEFAULT_CONTEXT_BUDGETS

    if disk_path is not None and disk_path.is_symlink() and not disk_path.exists():
        failures.append(f"[SYMLINK] {norm_rel}: broken symbolic link")

    binary = _is_binary(data)
    text = "" if binary else data.decode("utf-8", errors="replace")

    limit = _size_limit(norm_rel, max_bytes, patterns)
    if len(data) > limit and "git:allow-large-file" not in text:
        size_kb = (len(data) + 1023) // 1024
        failures.append(
            f"[LARGE] {norm_rel}: {size_kb} KB exceeds {limit // 1024} KB cap "
            "(split/ignore or add 'git:allow-large-file')"
        )

    if binary:
        return failures

    lines = text.splitlines()
    nlines = len(lines)
    suffix = Path(norm_rel).suffix.lower()

    if suffix in SOURCE_SUFFIXES and nlines > max_source_lines and "git:allow-bloat" not in text:
        failures.append(
            f"[BLOAT] {norm_rel}: {nlines} lines exceeds {max_source_lines}-line limit "
            "(split module or add 'git:allow-bloat')"
        )

    if norm_rel in budgets:
        max_lines, max_ctx_bytes = budgets[norm_rel]
        if nlines > max_lines or len(data) > max_ctx_bytes:
            failures.append(
                f"[BUDGET] {norm_rel}: {nlines} lines / {len(data)} bytes exceeds "
                f"{max_lines} lines / {max_ctx_bytes} bytes context budget"
            )

    failures.extend(_check_line_rules(norm_rel, lines))

    if suffix == ".py":
        try:
            ast.parse(text, filename=norm_rel)
        except SyntaxError as exc:
            failures.append(f"[SYNTAX] {norm_rel}:{exc.lineno}: {exc.msg}")

    return failures


def check_gitattributes_pins(root: Path) -> list[str]:
    """Fail when no attributes source carries the pins the hook's executability depends on.

    Two valid sources, checked in precedence order:

    * ``.gitattributes`` — tracked; the normal case when you own the repository.
    * ``.git/info/attributes`` — local-only, highest precedence; used by ``--mode overlay`` so a
      fork's tracked files stay byte-identical to upstream.

    Accepting only the tracked file makes overlay mode fail its own gate on every commit — the
    self-rejection trap. Accepting either keeps the invariant ("the pins exist and git honours them")
    while leaving the *location* to the mode.
    """
    pins = REQUIRED_GITATTRIBUTES_PINS
    sources = [root / ".gitattributes", root / ".git" / "info" / "attributes"]
    present: set[str] = set()
    for path in sources:
        if path.is_file():
            present.update(
                line.strip()
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            )
    if not present:
        return ["[EOL_PIN] no attributes source found: " + ", ".join(pins)]
    return [f"[EOL_PIN] no attributes source carries pin: {pin}" for pin in pins if pin not in present]


def _git_paths(root: Path, staged: bool) -> list[str]:
    cmd = (
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]
        if staged
        else ["git", "ls-files", "-z"]
    )
    try:
        out = subprocess.check_output(cmd, cwd=root, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Exit 2, not 1: the gate could not run. Reporting a violation here would be a lie, and
        # reporting 0 would silently pass a repo that was never audited.
        detail = getattr(exc, "stderr", b"") or b""
        print(
            f"[FAIL] hygiene gate cannot run: `{' '.join(cmd)}` failed in {root} "
            f"({detail.decode('utf-8', 'replace').strip() or 'git unavailable or not a repository'})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return [raw.decode("utf-8") for raw in out.split(b"\x00") if raw]


def _read_staged_blobs(root: Path, paths: list[str]) -> dict[str, bytes]:
    """Read every staged blob in ONE `git cat-file --batch` process.

    The obvious implementation — `git show :path` per file — costs ~32 ms per file because each call
    spawns a process: measured 25.5 s extrapolated for 801 files, which is longer than the timeout a
    pre-commit hook survives. `--batch` speaks a length-prefixed stream over one process instead.
    """
    if not paths:
        return {}
    request = "\n".join(f":{p}" for p in paths) + "\n"
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root, input=request.encode("utf-8"),
        capture_output=True,
    )
    if proc.returncode != 0:
        print(
            f"[FAIL] hygiene gate cannot read staged blobs: git cat-file exited {proc.returncode}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    out = proc.stdout
    blobs: dict[str, bytes] = {}
    pos = 0
    for rel in paths:
        nl = out.find(b"\n", pos)
        if nl < 0:
            break
        header = out[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        # "<oid> missing" for a path not in the index.
        if len(header) < 3:
            continue
        size = int(header[2])
        blobs[rel] = out[pos:pos + size]
        pos += size + 1  # trailing newline after the payload
    return blobs


def run_audit(root: Path, *, staged: bool = False) -> int:
    cfg = load_config(root)
    max_bytes = cfg.get("max_bytes")
    max_bytes = int(max_bytes) if isinstance(max_bytes, (int, float)) else DEFAULT_MAX_BYTES
    max_source_lines = cfg.get("max_source_lines")
    max_source_lines = (
        int(max_source_lines) if isinstance(max_source_lines, (int, float)) else DEFAULT_MAX_SOURCE_LINES
    )
    large_patterns = _patterns_from(cfg)
    budgets = _budgets_from(cfg)

    failures: list[str] = []
    failures.extend(check_gitattributes_pins(root))
    paths = _git_paths(root, staged=staged)
    staged_blobs = _read_staged_blobs(root, paths) if staged else {}
    for rel in paths:
        if staged:
            data = staged_blobs.get(rel)
            if data is None:
                continue
        else:
            p = root / rel
            if not p.exists() and not p.is_symlink():
                continue
            data = b"" if (p.is_symlink() and not p.exists()) else p.read_bytes()
        failures.extend(
            check_blob(
                rel,
                data,
                disk_path=root / rel,
                max_bytes=max_bytes,
                large_file_patterns=large_patterns,
                max_source_lines=max_source_lines,
                context_budgets=budgets,
            )
        )

    if failures:
        print(f"[FAIL] Repo hygiene check failed ({len(failures)} issue(s)):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    scope = "staged" if staged else "tracked"
    print(f"[PASS] Repo hygiene verified {len(paths)} {scope} file(s) (size/lines/paths/conflicts/AST).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Inspect staged blobs in git index (for pre-commit)")
    mode.add_argument("--all", action="store_true", help="Inspect all tracked files (default, for CI)")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    args = ap.parse_args(argv)
    return run_audit(args.root, staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
