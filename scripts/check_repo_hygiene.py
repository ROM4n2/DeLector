#!/usr/bin/env python3
# dfs-bootstrap-gate-version: 3
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

Scope-granular ratchet (``--emit-baseline`` / ``--ratchet-guard``): a repo with legacy debt sets a
``ratchet`` map in the config, keyed ``"CATEGORY|scope"`` where scope is the first path segment
(e.g. ``"ABS_PATH|docs"``) or ``"<root>"`` for top-level files. A finding is absorbed only if its
bucket's count stays at or under that bucket's allowance; an unlisted bucket allows ZERO. That last
rule is the point: a single global count would let a new host path in production code hide under
hundreds of historical docs paths, whereas a bucketed baseline holds production scopes at zero and
ratchets only the scopes that carry real debt.
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
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

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

# Ratchet-bucket categories. These are the "debt" classes a repo may legitimately carry legacy
# findings in. Correctness classes (CONFLICT/SYMLINK/SYNTAX/EOL_PIN) are deliberately excluded:
# a merge marker or a broken symlink is never tolerable debt, so they always fail regardless of
# what a config tries to allow. A malicious/incompetent config cannot ratchet them away.
RATCHET_CATEGORIES = frozenset({"ABS_PATH", "BLOAT", "LARGE", "BUDGET"})
ROOT_SCOPE = "<root>"


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


def load_ratchet(cfg: dict[str, object]) -> dict[str, int]:
    """Read the ``ratchet`` map; malformed values are ignored (never silently widen a bucket)."""
    raw = cfg.get("ratchet")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, (int, float)) and value >= 0:
            out[key] = int(value)
    return out


def _bucket_key(msg: str) -> str | None:
    """Map a finding to its ``CATEGORY|scope`` bucket, or None if not ratchetable.

    Message shape is ``[TAG] path:line: detail`` (or ``[TAG] path: detail``). ``EOL_PIN`` findings
    carry no file path and are not ratchetable, so they never reach the pathless branch here.
    """
    if not msg.startswith("["):
        return None
    tag, sep, rest = msg[1:].partition("]")
    if not sep or tag not in RATCHET_CATEGORIES:
        return None
    path = rest.strip().split(":", 1)[0].replace("\\", "/")
    scope = path.split("/", 1)[0] if "/" in path else ROOT_SCOPE
    return f"{tag}|{scope}"


def apply_baseline_tolerance(
    findings: list[str], ratchet: dict[str, int]
) -> tuple[list[str], dict[str, tuple[int, int]]]:
    """Absorb up to each bucket's allowance; keep the rest plus an auditable suppression report.

    The allowance is a COUNT per ``(category, scope)``, not an allow-list of findings — mirroring
    the structure gate. Unlisted buckets default to zero, which is what keeps new debt in a clean
    production scope from hiding under historical debt in another scope. Every absorbed bucket is
    named in the verdict line: silent suppression is indistinguishable from a deleted gate.
    """
    seen: dict[str, int] = {}
    absorbed: dict[str, int] = {}
    kept: list[str] = []
    for msg in findings:
        key = _bucket_key(msg)
        if key is None:
            kept.append(msg)
            continue
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= ratchet.get(key, 0):
            absorbed[key] = absorbed.get(key, 0) + 1
            continue
        kept.append(msg)
    report = {key: (absorbed[key], seen[key]) for key in sorted(absorbed)}
    return kept, report


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
        capture_output=True, check=False,
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


def collect_findings(root: Path, *, staged: bool = False) -> tuple[list[str], int]:
    """Run the full audit and return (raw findings, file count).

    Factored out so ``--emit-baseline`` measures the SAME findings the audit sees — reimplementing
    the scan in the baseline writer would let the two drift apart and baseline a phantom debt.
    """
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
    return failures, len(paths)


def _report(failures: list[str], path_count: int, staged: bool,
            suppressed: dict[str, tuple[int, int]]) -> int:
    """Print the verdict with an auditable suppression tail and return the exit code."""
    tail = ""
    if suppressed:
        detail = ", ".join(f"{key} {n}/{total}" for key, (n, total) in suppressed.items())
        tail = f" (baseline tolerated: {detail})"
    if failures:
        print(f"[FAIL] Repo hygiene check failed ({len(failures)} issue(s)):{tail}", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1
    scope = "staged" if staged else "tracked"
    print(f"[PASS] Repo hygiene verified {path_count} {scope} file(s) (size/lines/paths/conflicts/AST).{tail}")
    return 0


def run_audit(root: Path, *, staged: bool = False) -> int:
    cfg = load_config(root)
    findings, path_count = collect_findings(root, staged=staged)
    kept, suppressed = apply_baseline_tolerance(findings, load_ratchet(cfg))
    return _report(kept, path_count, staged, suppressed)


def _git_head_sha(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except FileNotFoundError:
        return "unknown"


def _baseline_counts(findings: list[str]) -> dict[str, int]:
    """Self-measure raw debt per bucket — the SAME findings the audit sees, tolerance disabled."""
    counts: dict[str, int] = {}
    for msg in findings:
        key = _bucket_key(msg)
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def emit_baseline(root: Path) -> int:
    """Write self-measured per-bucket counts into the config (human reviews the diff)."""
    findings, _ = collect_findings(root, staged=False)
    buckets = _baseline_counts(findings)
    existing = load_config(root)
    payload: dict[str, object] = {
        key: value for key, value in existing.items()
        if key not in ("ratchet", "_provenance")
    }
    payload["ratchet"] = buckets
    payload["_provenance"] = {
        "measured_at_commit": _git_head_sha(root),
        "note": "Self-measured by --emit-baseline; each CATEGORY|scope bucket may only decrease "
                "(see --ratchet-guard). Unlisted buckets allow zero findings.",
    }
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"[BASELINE] wrote {CONFIG_PATH.as_posix()} at commit {payload['_provenance']['measured_at_commit']}:")
    for key, value in buckets.items():
        print(f"  {key} = {value}")
    return 0


def ratchet_guard(root: Path) -> int:
    """CI mode: fail if any ratchet bucket rose above the value committed at HEAD.

    Unlike the structure gate's fixed keys, buckets are dynamic: a newly added bucket with a
    positive allowance is itself a tolerance increase (from implicit zero) and must be caught.
    """
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{CONFIG_PATH.as_posix()}"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
    except FileNotFoundError:
        print("[FAIL] ratchet-guard needs git to read the committed baseline", file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(f"[FAIL] ratchet-guard: {CONFIG_PATH.as_posix()} not present at HEAD; commit a baseline first",
              file=sys.stderr)
        return 2
    try:
        committed_raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] committed baseline is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(committed_raw, dict):
        print("[FAIL] committed baseline must be a JSON object", file=sys.stderr)
        return 2
    committed = load_ratchet(committed_raw)
    current = load_ratchet(load_config(root))
    raised = [
        f"{key}: {committed.get(key, 0)} -> {current[key]}"
        for key in current
        if current[key] > committed.get(key, 0)
    ]
    if raised:
        print("[FAIL] hygiene ratchet violated — bucket allowances may only decrease:", file=sys.stderr)
        for item in raised:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"[PASS] hygiene ratchet intact ({len(current)} buckets, no tolerance increase vs HEAD)")
    return 0


def audit_json(root: Path) -> int:
    """Emit machine-readable hygiene findings on stdout — no human text, for trend aggregation."""
    findings, path_count = collect_findings(root, staged=False)
    ratchet = load_ratchet(load_config(root))
    kept, suppressed = apply_baseline_tolerance(findings, ratchet)
    by_class: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    for msg in findings:
        tag = msg[1:].partition("]")[0] if msg.startswith("[") else "UNKNOWN"
        by_class[tag] = by_class.get(tag, 0) + 1
        key = _bucket_key(msg)
        if key is not None:
            by_bucket[key] = by_bucket.get(key, 0) + 1
    payload = {
        "files_checked": path_count,
        "verdict": "pass" if not kept else "fail",
        "findings_total": len(findings),
        "findings_reported": len(kept),
        "findings_tolerated": len(findings) - len(kept),
        "by_class": dict(sorted(by_class.items())),
        "by_bucket": dict(sorted(by_bucket.items())),
        "tolerated_by_bucket": {
            key: {"absorbed": n, "total": total} for key, (n, total) in suppressed.items()
        },
        "reported_findings": kept,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not kept else 1


def explain_config(root: Path) -> int:
    """Print effective thresholds, ratchet buckets and provenance (auditability)."""
    cfg = load_config(root)
    path = root / CONFIG_PATH
    print(f"config source: {path.as_posix()} ({'present' if path.is_file() else 'absent — using defaults'})")
    print("effective settings:")
    for key in sorted(key for key in cfg if key not in ("ratchet", "_provenance")):
        print(f"  {key} = {cfg[key]}")
    ratchet = load_ratchet(cfg)
    print(f"ratchet buckets ({len(ratchet)}; unlisted buckets allow zero):")
    for key in sorted(ratchet):
        print(f"  {key} = {ratchet[key]}")
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("  (config file is not valid JSON; values above are defaults)")
        else:
            prov = raw.get("_provenance") if isinstance(raw, dict) else None
            if isinstance(prov, dict):
                print(f"provenance: measured_at_commit={prov.get('measured_at_commit', 'unknown')}")
                print(f"            note={prov.get('note', '')}")
    print(f"ratchet categories: {', '.join(sorted(RATCHET_CATEGORIES))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Inspect staged blobs in git index (for pre-commit)")
    mode.add_argument("--all", action="store_true", help="Inspect all tracked files (default, for CI)")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    ap.add_argument("--emit-baseline", action="store_true",
                    help="Measure current per-bucket counts into the config (self-measured)")
    ap.add_argument("--ratchet-guard", action="store_true",
                    help="CI mode: fail if any bucket allowance rose above the value at HEAD")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable findings on stdout (for trend aggregation)")
    ap.add_argument("--explain", action="store_true",
                    help="print effective config, ratchet buckets and provenance")
    args = ap.parse_args(argv)
    modes = (args.emit_baseline, args.ratchet_guard, args.json, args.explain)
    if sum(bool(m) for m in modes) > 1:
        ap.error("--emit-baseline, --ratchet-guard, --json and --explain are mutually exclusive")
    if args.emit_baseline:
        return emit_baseline(args.root)
    if args.ratchet_guard:
        return ratchet_guard(args.root)
    if args.json:
        return audit_json(args.root)
    if args.explain:
        return explain_config(args.root)
    return run_audit(args.root, staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
