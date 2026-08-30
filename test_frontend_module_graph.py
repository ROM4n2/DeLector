"""Frontend ES module graph integrity test.

Guard against the v4.7.0 regression: a1_cards.js / a1_writer.js were committed
as EMPTY files while cards.js / writer.js named-imported from them. An empty
module "does not provide an export named X" — that is a link-time SyntaxError
which kills the ENTIRE ES module graph (main.js never evaluates, so every
interaction reduces to bare CSS click effects; the Android APK shipped like
this).

The old contract test asserted `"setA1Mode" in cards_js` — a string-substring
check. It stayed green even with the empty module, because the import/export
scaffolding itself contains those identifiers. This test resolves the graph
structurally instead: every named import and every `export {...} from` must
actually resolve to a real export in the target module (transitively through
`export *`).
"""

import re
from pathlib import Path

JS_DIR = Path("static/js")


def _norm(module_ref):
    """Normalize a module reference ('./core.js' / 'core.js') to a bare filename."""
    return module_ref.lstrip("./").split("/")[-1]

# ── Parsers (tuned to this codebase's syntax; see git history for forms) ─────

def _parse_own_exports(src):
    """Names directly exported by the module itself."""
    names = set()
    names.update(
        re.findall(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", src)
    )
    names.update(
        re.findall(r"\bexport\s+(?:let|const|var|class)\s+([A-Za-z_$][\w$]*)", src)
    )
    # export { a, b, c }  WITHOUT `from` → module's own exported bindings
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}\s*(?!from\b)", src, re.S):
        for item in m.group(1).split(","):
            item = item.strip()
            if item:
                names.add(item.split(" as ")[0].strip())
    return names


def _parse_named_reexports(src):
    """{exported_name: (source_module, original_name)} for `export {…} from`. """
    result = {}
    for m in re.finditer(
        r"\bexport\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", src, re.S
    ):
        mod = m.group(2)
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            if " as " in item:
                orig, alias = item.split(" as ", 1)
                orig, alias = orig.strip(), alias.strip()
            else:
                orig = alias = item
            result[alias] = (mod, orig)
    return result


def _parse_star_reexports(src):
    return re.findall(r"\bexport\s*\*\s*from\s*['\"]([^'\"]+)['\"]", src)


def _parse_named_imports(src):
    """[(imported_name, source_module)] for `import {…} from`. """
    result = []
    for m in re.finditer(
        r"\bimport\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", src, re.S
    ):
        mod = m.group(2)
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            orig = item.split(" as ")[0].strip()
            result.append((orig, mod))
    return result


def _parse_star_imports(src):
    return re.findall(r"\bimport\s*\*\s*as\s+\w+\s*from\s*['\"]([^'\"]+)['\"]", src)


# ── Module index & export resolution ─────────────────────────────────────────

def _load_modules():
    modules = {}
    for js in sorted(JS_DIR.glob("*.js")):
        src = js.read_text(encoding="utf-8")
        modules[js.name] = {
            "src": src,
            "own": _parse_own_exports(src),
            "named_reexports": _parse_named_reexports(src),
            "star": _parse_star_reexports(src),
        }
    return modules


def _exports_name(modules, module, name, seen=None):
    """Does `module` export `name`, following `export *` chains transitively?"""
    module = _norm(module)
    if module not in modules:
        return False
    if seen is None:
        seen = set()
    if module in seen:
        return False
    seen = seen | {module}
    info = modules[module]
    if name in info["own"]:
        return True
    # export { a } from './y.js'  →  module exports `a`, but y must export it too
    if name in info["named_reexports"]:
        target, orig = info["named_reexports"][name]
        return _exports_name(modules, target, orig, seen)
    # export * from './y.js'
    return any(_exports_name(modules, target, name, seen) for target in info["star"])


# ── Tests ────────────────────────────────────────────────────────────────────

def _graph_violations():
    modules = _load_modules()
    violations = []
    for name, info in modules.items():
        for imported, src_mod in _parse_named_imports(info["src"]):
            src_mod = _norm(src_mod)
            if src_mod not in modules:
                violations.append(f"{name} imports {imported} from missing file {src_mod}")
            elif not _exports_name(modules, src_mod, imported):
                violations.append(
                    f"{name} imports '{imported}' from {src_mod}, which does not export it"
                )
        for mod in _parse_star_imports(info["src"]):
            mod = _norm(mod)
            if mod not in modules:
                violations.append(f"{name} does `import *` from missing file {mod}")
        for alias, (src_mod, orig) in info["named_reexports"].items():
            src_mod = _norm(src_mod)
            if src_mod not in modules:
                violations.append(
                    f"{name} re-exports {alias} from missing file {src_mod}"
                )
            elif not _exports_name(modules, src_mod, orig):
                violations.append(
                    f"{name} re-exports {alias} (as {orig}) from {src_mod}, "
                    f"which does not export it"
                )
        for mod in info["star"]:
            mod = _norm(mod)
            if mod not in modules:
                violations.append(f"{name} does `export *` from missing file {mod}")
    return violations


def test_every_named_import_resolves_to_a_real_export():
    violations = _graph_violations()
    assert not violations, (
        "Frontend ES module graph has unresolved imports (link-time SyntaxError "
        "that would kill the whole module graph on Android WebView):\n"
        + "\n".join("  - " + v for v in violations)
    )


def test_a1_modules_are_not_empty():
    """The exact v4.7.0 regression: 0-byte modules with exports expected."""
    for name in ("a1_cards.js", "a1_writer.js"):
        path = JS_DIR / name
        assert path.exists(), f"{name} is missing"
        src = path.read_text(encoding="utf-8")
        assert len(src.strip()) > 0, f"{name} is empty — cards.js/writer.js import from it"
        assert _parse_own_exports(src) or _parse_named_reexports(src), (
            f"{name} exports nothing, yet cards.js/writer.js named-import from it"
        )
