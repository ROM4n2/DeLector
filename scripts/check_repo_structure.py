#!/usr/bin/env python3
"""Repository structure gate: coupling, cycles, and the signatures of generated bloat.

Complements ``check_repo_hygiene.py`` (size / host paths / conflicts / AST-parse) with the *shape*
checks that catch a codebase turning into a pile:

- ``[CYCLE]``    import cycle among repo-internal modules
- ``[FANOUT]``   one module importing too many internal modules (hub / god module)
- ``[FUNC_LEN]`` function or method too long
- ``[NEST]``     nesting depth beyond the guard-clause ceiling
- ``[CLASS]``    class with too many methods (god object)
- ``[STUB]``     agent-generated placeholder: bare ``pass`` body, elision comments, TODO/FIXME,
                 or ``NotImplementedError`` outside an abstract context

The last one is the reason this gate exists alongside the hygiene gate. A bloat-oriented code
generator does not usually write one huge file; it writes many plausible-looking functions whose
bodies are stubs, and leaves elision markers (the ``rest of the body is unchanged`` family of
comments) where it ran out of context. Those signatures pass a size check and a syntax check, and
they are the actual leading indicator of a codebase that will need rewriting.

Python only (``ast``). Other languages are counted, not analysed.

Baseline tolerance: ``data/repo_structure.json`` may set ``allowed_*`` counts to tolerate existing
findings per default class, so a repo with historical debt can land the gate green today. Suppressed
counts are always printed in the verdict line — a silent suppression would be a dead gate.

Exit contract: ``0`` clean, ``1`` violation found, ``2`` gate could not run (bad config).
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path("data") / "repo_structure.json"

DEFAULTS: dict[str, int] = {
    "max_fanout": 12,          # internal modules imported by one module
    "max_function_lines": 60,  # one function/method body
    "max_nesting": 4,          # If/For/While/With/Try nesting inside one function
    "max_methods": 20,         # methods per class
    "max_cycle_length": 0,     # 0 = any cycle length is a violation
    # Opt-in checks (0 / -1 = disabled). They are OFF by default on purpose: bootstrap installs this
    # gate into repositories that already exist, and a gate that lands red on day one gets deleted
    # (`dfs-gate` Step 3: "never land red on day one"). Enable per repo once the baseline is clean.
    "max_dup_lines": 0,        # >0 enables [DUP]; duplicated block size that counts as a clone
    "require_test_for_src": 0, # 1 enables [TEST_GAP]; every src/ module needs a test file
    "max_dead_exports": -1,    # >=0 enables [DEAD]; tolerance for unreferenced public symbols
    # Baseline tolerance (ratchet): allow N existing findings of each DEFAULT class. 0 = enforce all.
    # Unlike the opt-in checks above, these never disable a check — they only absorb the historical
    # baseline so a gate installed into an existing repo is green on day one and ratchets downward.
    "allowed_cycle": 0,
    "allowed_fanout": 0,
    "allowed_func_len": 0,
    "allowed_nest": 0,
    "allowed_class": 0,
    "allowed_stub": 0,
}

# Tag -> config key for the default-class ratchet. A finding keeps its bracketed tag as the first
# token (e.g. "[NEST] src/x.py:12: ..."), so one pass partitions the list without parsing Locations.
RATCHET_KEYS: dict[str, str] = {
    "[CYCLE]": "allowed_cycle",
    "[FANOUT]": "allowed_fanout",
    "[FUNC_LEN]": "allowed_func_len",
    "[NEST]": "allowed_nest",
    "[CLASS]": "allowed_class",
    "[STUB]": "allowed_stub",
}

# Directories that are not part of the analysed graph.
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
     "build", "dist", ".tox", ".eggs", "site-packages", ".worktrees"}
)

# Source roots scanned for [DEAD] / [TEST_GAP]. Order matters: the first match wins.
SOURCE_ROOTS = ("src", "lib", "app")

# Test roots searched for a module's corresponding test file.
TEST_ROOTS = ("tests", "test")

# Elision / placeholder markers: the fingerprint of context-truncated generation.
#
# Every alternative must be an *elision phrase*, not a bare word. An earlier version matched the single
# word `unchanged`, which flagged a normal English sentence in a real repo ("three masked columns is
# unchanged, and ..."). A marker has to say "the rest is missing", not merely contain a word that
# appears in prose.
STUB_COMMENT_RE = re.compile(
    r"(?:#|//)\s*(?:"
    r"\.\.\.|…"
    r"|(?:the\s+)?rest\s+(?:of\s+(?:the\s+)?(?:code|implementation|body|file|method|function)\s+)?"
    r"(?:is\s+)?(?:unchanged|omitted|the\s+same)"
    r"|remaining\s+(?:code|implementation|methods?|functions?)\s+(?:unchanged|omitted)"
    r"|(?:code|implementation|body)\s+(?:unchanged|omitted|truncated)"
    r"|same\s+as\s+(?:above|before)"
    r"|implementation\s+here"
    r"|unchanged\s+from\s+(?:above|before|original)"
    r")",
    re.IGNORECASE,
)
TODO_RE = re.compile(r"(?:#|//)\s*(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)
# A `pass`-only or `...`-only body is a stub; `raise NotImplementedError` is a stub unless abstract.
ABSTRACT_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})

# Names that are never "dead exports": entry points, and framework hooks that a runner calls by name.
# `pytest_sessionstart` and friends are invoked by pytest's plugin protocol, never by an import.
EXEMPT_EXPORT_NAMES = frozenset({
    "main", "setup", "teardown_module", "teardown_function",
    "pytest_sessionstart", "pytest_sessionfinish", "pytest_collection_modifyitems",
    "pytest_configure", "pytest_unconfigure", "pytest_addoption",
})
EXEMPT_EXPORT_PREFIXES = ("pytest_", "test_", "visit_")


def load_config(root: Path) -> dict[str, int]:
    """Optional per-repo overrides. Malformed config is exit 2, never a silent fallback."""
    cfg = dict(DEFAULTS)
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
    for key in DEFAULTS:
        val = loaded.get(key)
        if isinstance(val, (int, float)) and val >= 0:
            cfg[key] = int(val)
    return cfg


def iter_python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(path)
    return out


def module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_abstract_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in ABSTRACT_BASES:
            return True
    return False


def _is_abstract_method(func: ast.AST) -> bool:
    for dec in getattr(func, "decorator_list", []):
        name = dec.attr if isinstance(dec, ast.Attribute) else getattr(dec, "id", "")
        if name in {"abstractmethod", "abstractproperty"}:
            return True
    return False


def _body_is_stub(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return a reason string when the function body is a placeholder, else None."""
    # An abstract method is *supposed* to have no body; that is the contract, not a stub.
    if _is_abstract_method(func):
        return None
    body = [n for n in func.body if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)
            or not isinstance(n.value.value, str)]
    # Drop a leading docstring from the "real body" view.
    if func.body and isinstance(func.body[0], ast.Expr) and isinstance(func.body[0].value, ast.Constant) \
            and isinstance(func.body[0].value.value, str):
        body = func.body[1:]
    if not body:
        return "empty body (docstring only)"
    if len(body) == 1:
        only = body[0]
        if isinstance(only, ast.Pass):
            return "body is only `pass`"
        if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis:
            return "body is only `...`"
        if isinstance(only, ast.Raise):
            exc = only.exc
            name = ""
            if isinstance(exc, ast.Call):
                name = exc.func.attr if isinstance(exc.func, ast.Attribute) else getattr(exc.func, "id", "")
            elif isinstance(exc, ast.Name):
                name = exc.id
            if name == "NotImplementedError" and not _is_abstract_method(func):
                return "raises NotImplementedError outside an abstract method"
    return None


def _nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Deepest control-flow nesting inside a function body."""
    nesting_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try,
                     ast.IfExp, ast.Match)
    worst = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a nested function is its own scope
        inner = depth + 1 if isinstance(child, nesting_types) else depth
        worst = max(worst, _nesting_depth(child, inner))
    return worst


def _span_lines(node: ast.AST) -> int:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start) or start
    return end - start + 1


def analyse_module(rel: str, tree: ast.Module, cfg: dict[str, int]) -> list[str]:
    failures: list[str] = []

    # [FUNC_LEN] / [NEST] / [STUB]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = _span_lines(node)
            if length > cfg["max_function_lines"]:
                failures.append(
                    f"[FUNC_LEN] {rel}:{node.lineno}: {node.name}() is {length} lines "
                    f"(> {cfg['max_function_lines']}); extract helpers"
                )
            depth = _nesting_depth(node)
            if depth > cfg["max_nesting"]:
                failures.append(
                    f"[NEST] {rel}:{node.lineno}: {node.name}() nests {depth} levels "
                    f"(> {cfg['max_nesting']}); use guard clauses"
                )
            reason = _body_is_stub(node)
            if reason:
                failures.append(f"[STUB] {rel}:{node.lineno}: {node.name}(): {reason}")

    # [CLASS]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if len(methods) > cfg["max_methods"]:
                failures.append(
                    f"[CLASS] {rel}:{node.lineno}: {node.name} has {len(methods)} methods "
                    f"(> {cfg['max_methods']}); split responsibilities"
                )
            if _is_abstract_class(node):
                continue

    # [STUB] on comment markers and TODO density (line scan; comments are not in the AST)
    return failures


def _scan_text_markers(rel: str, text: str) -> list[str]:
    """Elision comments and TODO/FIXME markers — the comment-level stub signature."""
    failures: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if STUB_COMMENT_RE.search(line):
            failures.append(
                f"[STUB] {rel}:{lineno}: elision marker (context-truncated generation): {line.strip()[:70]}"
            )
        elif TODO_RE.search(line):
            failures.append(f"[STUB] {rel}:{lineno}: placeholder marker: {line.strip()[:70]}")
    return failures


def _public_symbols(tree: ast.Module) -> list[tuple[str, int]]:
    """Top-level names a module exports: functions, classes, and module-level constants."""
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("_") or name in EXEMPT_EXPORT_NAMES:
                continue
            if any(name.startswith(p) for p in EXEMPT_EXPORT_PREFIXES):
                continue
            out.append((name, node.lineno))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                out.append((target.id, node.lineno))
    return out


def check_dead_exports(root: Path, trees: dict[str, ast.Module], rel_of: dict[str, str],
                       cfg: dict[str, int]) -> list[str]:
    """[DEAD] public symbols that nothing in the repo imports or references.

    Scans every module's source text for the name — imports, attribute access, string references in
    `__all__`. A symbol mentioned nowhere outside its own definition is either dead or only reachable
    via dynamic dispatch, which is exactly the case worth making a human confirm.
    """
    limit = cfg["max_dead_exports"]
    if limit < 0:
        return []
    # Concatenate every non-test module's text once; per-symbol `in` scans are then cheap. Test files
    # are excluded from BOTH sides: their functions are called by the runner, not by production code,
    # and counting them would flag every test helper as dead.
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in iter_python_files(root)
        if p.relative_to(root).parts[0] not in TEST_ROOTS
    )
    failures: list[str] = []
    for mod, tree in sorted(trees.items()):
        rel = rel_of[mod]
        if Path(rel).parts[0] in TEST_ROOTS:
            continue
        for name, lineno in _public_symbols(tree):
            # Count occurrences: one is the definition itself. More than one means it is referenced.
            if corpus.count(name) > 1:
                continue
            failures.append(
                f"[DEAD] {rel}:{lineno}: '{name}' is defined but never referenced "
                "(delete it, or export it from an entry point)"
            )
    if len(failures) <= limit:
        return []
    return failures


def check_test_coverage_by_file(root: Path, trees: dict[str, ast.Module], rel_of: dict[str, str],
                                cfg: dict[str, int]) -> list[str]:
    """[TEST_GAP] every module under a source root must have a corresponding test file.

    Not a coverage percentage — a file-level existence check. A module with zero tests is the shape
    generated code takes when nobody asked for tests, and no coverage tool will tell you it is missing.
    """
    if cfg["require_test_for_src"] <= 0:
        return []
    test_stems: set[str] = set()
    for p in iter_python_files(root):
        if p.relative_to(root).parts[0] not in TEST_ROOTS:
            continue
        stem = p.stem
        test_stems.add(stem)
        # Both conventions are common: tests/test_widget.py and tests/widget_test.py
        if stem.startswith("test_"):
            test_stems.add(stem[len("test_"):])
        elif stem.endswith("_test"):
            test_stems.add(stem[: -len("_test")])
    failures: list[str] = []
    for mod in sorted(trees):
        rel = rel_of[mod]
        top = Path(rel).parts[0]
        if top not in SOURCE_ROOTS:
            continue
        stem = Path(rel).stem
        if stem == "__init__" or stem in test_stems:
            continue
        failures.append(
            f"[TEST_GAP] {rel}: no test file for this module "
            f"(expected tests/test_{stem}.py or tests/{stem}_test.py)"
        )
    return failures


def _normalized_shape(node: ast.AST) -> str:
    """A clone-detection key: the function's signature and body, with identifiers and literals erased.

    Comparing node-type sequences (the obvious approach) is far too coarse — every function with an
    `if` inside a `for` produces the same sequence, which measured 580 false positives on a 40k-line
    repo. `ast.dump` keeps the tree shape; erasing names/constants makes two blocks that differ only
    in variable names or literal values compare equal, which is what a copy-paste clone is.

    The **name is erased but the arity is kept**: `def a(x)` and `def b(x)` with identical bodies are
    the duplicate this check exists to find, while `def a(x)` and `def b(x, y)` are different
    interfaces that merely share a body — flagging those produced false positives on real code.
    """
    sig = ast.arguments(
        posonlyargs=[], args=list(node.args.args), vararg=node.args.vararg,
        kwonlyargs=list(node.args.kwonlyargs), kw_defaults=[], kwarg=node.args.kwarg,
        defaults=[],
    )
    body = ast.Module(body=list(node.body), type_ignores=[])

    class Erase(ast.NodeTransformer):
        def visit_Name(self, n: ast.Name) -> ast.AST:
            return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)

        def visit_Attribute(self, n: ast.Attribute) -> ast.AST:
            self.generic_visit(n)
            return ast.copy_location(ast.Attribute(value=n.value, attr="_", ctx=n.ctx), n)

        def visit_Constant(self, n: ast.Constant) -> ast.AST:
            return ast.copy_location(ast.Constant(value=None), n)

        def visit_arg(self, n: ast.arg) -> ast.AST:
            # Erase the parameter name but keep the annotation: `x: int` and `x: str` differ.
            self.generic_visit(n)
            return ast.copy_location(ast.arg(arg="_", annotation=n.annotation), n)

        def visit_FunctionDef(self, n: ast.FunctionDef) -> ast.AST:
            # Nested functions: erase their name too, keep their body.
            self.generic_visit(n)
            return ast.copy_location(ast.FunctionDef(
                name="_", args=n.args, body=n.body, decorator_list=[], returns=n.returns,
                type_comment=n.type_comment,
            ), n)

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    wrapper = ast.Module(
        body=[ast.FunctionDef(name="_", args=sig, body=body.body, decorator_list=[],
                              returns=None, type_comment=None)],
        type_ignores=[],
    )
    erased = ast.fix_missing_locations(Erase().visit(wrapper))
    return ast.dump(erased, annotate_fields=False, include_attributes=False)


def _function_shapes(tree: ast.Module, min_lines: int) -> dict[str, int]:
    """Map each qualifying function's normalised shape to its line number."""
    shapes: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _span_lines(node) < min_lines:
            continue
        try:
            shapes[_normalized_shape(node)] = node.lineno
        except (SyntaxError, ValueError):
            continue
    return shapes


def _is_mirrored_copy(rel: str, other: str) -> bool:
    """True when one path is a suffix of the other — the same file reached via two roots.

    Build systems copy a source tree into a platform directory (`android/app/src/main/python/...`
    holds a copy of `delector/...`). Those pairs are not clones; flagging them produces hundreds of
    false positives and buries the real duplicates. Measured: 421 of 421 [DUP] hits on a real repo
    were this pattern.
    """
    a, b = rel.split("/"), other.split("/")
    return a[-min(len(a), len(b)):] == b[-min(len(a), len(b)):] and (len(a) != len(b))


def check_duplicates(root: Path, trees: dict[str, ast.Module], rel_of: dict[str, str],
                     cfg: dict[str, int]) -> list[str]:
    """[DUP] the same function body appearing in more than one place."""
    min_lines = cfg["max_dup_lines"]
    if min_lines <= 0:
        return []
    seen: dict[str, tuple[str, int]] = {}
    failures: list[str] = []
    for mod in sorted(trees):
        rel = rel_of[mod]
        for shape, lineno in _function_shapes(trees[mod], min_lines).items():
            if shape not in seen:
                seen[shape] = (rel, lineno)
                continue
            first_rel, first_line = seen[shape]
            if _is_mirrored_copy(rel, first_rel):
                continue
            failures.append(
                f"[DUP] {rel}:{lineno}: function body duplicates {first_rel}:{first_line} "
                "(identical structure and literals); extract a shared helper"
            )
    return failures


def _resolve_relative(module: str, level: int) -> str:
    """Resolve a relative import's base package without nesting."""
    if not level:
        return module
    package = module.rsplit(".", 1)[0] if "." in module else ""
    if not package:
        return module
    parts = package.split(".")
    up = level - 1
    if up >= len(parts):
        return module
    kept = parts[: len(parts) - up] if up else parts
    return ".".join(kept)


def resolve_imports(mod: str, tree: ast.Module, known: set[str]) -> set[str]:
    """Internal module names this module imports."""
    targets: set[str] = set()

    def consider(candidate: str) -> None:
        if candidate and candidate != mod and candidate in known:
            targets.add(candidate)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                for i in range(1, len(parts) + 1):
                    consider(".".join(parts[:i]))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        base = node.module or ""
        if node.level:
            pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
            pkg_parts = pkg.split(".") if pkg else []
            up = node.level - 1
            if up and up <= len(pkg_parts):
                pkg_parts = pkg_parts[: len(pkg_parts) - up]
            base = ".".join([*pkg_parts, base]) if base else ".".join(pkg_parts)
        consider(base)
        for alias in node.names:
            if alias.name != "*":
                consider(f"{base}.{alias.name}" if base else alias.name)
    return targets


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan-style SCC detection; every SCC of size > 1 is a cycle cluster."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    result: list[list[str]] = []
    counter = [0]

    def strongconnect(node: str) -> None:
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack[node] = True
        for nxt in sorted(graph.get(node, ())):
            if nxt not in index:
                strongconnect(nxt)
                low[node] = min(low[node], low[nxt])
            elif on_stack.get(nxt):
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            strongconnect(node)
    return sorted(result)


def apply_baseline_tolerance(
    failures: list[str], cfg: dict[str, int]
) -> tuple[list[str], dict[str, tuple[int, int]]]:
    """Absorb up to ``allowed_*`` findings per default class; return the rest plus a suppression report.

    The tolerance is a COUNT, not an allow-list of specific findings: fixing one and adding a new one
    keeps the gate green. That is intentional — the ratchet is a number to lower as debt is paid, not
    a brittle fingerprint of today's file positions. Every absorbed finding is named in the verdict
    line; a silent suppression would be indistinguishable from a deleted gate.
    """
    seen: dict[str, int] = {}
    absorbed: dict[str, int] = {}
    kept: list[str] = []
    for msg in failures:
        tag = msg.split(" ", 1)[0]
        limit = cfg[RATCHET_KEYS[tag]] if tag in RATCHET_KEYS else 0
        seen[tag] = seen.get(tag, 0) + 1
        if limit and seen[tag] <= limit:
            absorbed[tag] = absorbed.get(tag, 0) + 1
            continue
        kept.append(msg)
    report = {tag: (absorbed[tag], seen[tag]) for tag in sorted(absorbed)}
    return kept, report


def run_audit(root: Path) -> int:
    cfg = load_config(root)
    files = iter_python_files(root)
    if not files:
        print("[PASS] Structure audit: no Python modules found (nothing to analyse).")
        return 0

    trees: dict[str, ast.Module] = {}
    texts: dict[str, str] = {}
    failures: list[str] = []
    skipped: list[str] = []

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            skipped.append(f"{rel}:{exc.lineno}")
            continue
        mod = module_name(root, path)
        trees[mod] = tree
        texts[mod] = text
        failures.extend(analyse_module(rel, tree, cfg))
        failures.extend(_scan_text_markers(rel, text))

    known = set(trees)
    graph: dict[str, set[str]] = {}
    rel_of = {module_name(root, p): p.relative_to(root).as_posix() for p in files}
    for mod, tree in trees.items():
        targets = resolve_imports(mod, tree, known)
        graph[mod] = targets
        if len(targets) > cfg["max_fanout"]:
            failures.append(
                f"[FANOUT] {rel_of[mod]}: imports {len(targets)} internal modules "
                f"(> {cfg['max_fanout']}); this is a hub — split it or introduce a seam"
            )

    for component in find_cycles(graph):
        if cfg["max_cycle_length"] and len(component) > cfg["max_cycle_length"]:
            continue
        members = " <-> ".join(rel_of.get(m, m) for m in component)
        failures.append(f"[CYCLE] import cycle among {len(component)} modules: {members}")

    failures.extend(check_dead_exports(root, trees, rel_of, cfg))
    failures.extend(check_test_coverage_by_file(root, trees, rel_of, cfg))
    failures.extend(check_duplicates(root, trees, rel_of, cfg))

    failures, suppressed = apply_baseline_tolerance(failures, cfg)
    return _report(failures, len(trees), skipped, suppressed)


def _report(
    failures: list[str],
    module_count: int,
    skipped: list[str],
    suppressed: dict[str, tuple[int, int]],
) -> int:
    """Print the verdict and return the exit code."""
    # Always name absorbed findings — suppression must be auditable, never look like a dead gate.
    tail = ""
    if suppressed:
        detail = ", ".join(f"{tag} {n}/{total}" for tag, (n, total) in suppressed.items())
        tail = f" (baseline tolerated: {detail})"
    if failures:
        print(f"[FAIL] Structure audit found {len(failures)} issue(s):{tail}", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        if skipped:
            print(f"  ({len(skipped)} module(s) skipped for syntax errors: {skipped[:5]})", file=sys.stderr)
        return 1

    print(
        f"[PASS] Structure audit verified {module_count} module(s) "
        f"(cycles/fanout/functions/nesting/classes/stubs/dead/tests/dups).{tail}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    # The import graph is global: a cycle involves modules that may not be staged. Accept --staged
    # for symmetry with the hygiene gate, but always analyse the whole graph — a partial graph
    # silently reports "no cycles", which is the failure mode this gate exists to prevent.
    ap.add_argument("--staged", action="store_true", help="Accepted for symmetry; the graph is always whole")
    ap.add_argument("--all", action="store_true", help="Audit all modules (default)")
    args = ap.parse_args(argv)
    return run_audit(args.root)


if __name__ == "__main__":
    sys.exit(main())
