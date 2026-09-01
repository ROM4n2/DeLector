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
    for name in ("a1_cards.js", "a1_writer.js", "a1_hoeren.js", "a1_lesen.js"):
        path = JS_DIR / name
        assert path.exists(), f"{name} is missing"
        src = path.read_text(encoding="utf-8")
        assert len(src.strip()) > 0, f"{name} is empty"
        assert _parse_own_exports(src) or _parse_named_reexports(src), (
            f"{name} exports nothing"
        )


# ── v4.8.2 guard: dangling bare identifier in a hook-exposer block ────────────
# The import/export resolver above catches *unresolved imports* (link-time
# SyntaxError). It cannot catch a name that is USED in a module body but was
# silently DROPPED from the import list — e.g. v4.8.2's `clearA1Email` at the
# bottom of main.js's `Object.assign(window, {...})`. At runtime that throws
# ReferenceError, which aborts the assignment and un-wires EVERY handler: the
# page still paints (CSS-only) but all JS interaction is dead on Android
# WebView — the exact "前端显示正常 / 交互全死" symptom. This test statically
# resolves each bare identifier used in any `Object.assign(window, {…})`
# exposer block against the bindings the module actually has.


def _parse_star_namespace_imports(src):
    """{namespace_name: source_module} for `import * as NS from …`."""
    return dict(
        re.findall(
            r"\bimport\s+\*\s*as\s+([A-Za-z_$][\w$]*)\s*from\s*['\"]([^'\"]+)['\"]",
            src,
        )
    )


def _module_local_bindings(src):
    """Names bound at top level of `src` (imports + own declarations)."""
    bound = set()
    # named imports: `import { a, b as c } from …`
    bound.update(_parse_named_imports(src) and [
        item[0] for item in _parse_named_imports(src)
    ])
    # star-namespace imports: `import * as NS from …` → binds NS
    bound.update(_parse_star_namespace_imports(src).keys())
    # default import
    bound.update(
        re.findall(r"\bimport\s+([A-Za-z_$][\w$]*)\s*,?[^;]*\bfrom\b", src)
    )
    # own top-level declarations
    bound.update(
        re.findall(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", src)
    )
    return bound


def _exposer_block_identifiers(src):
    """Bare identifiers inside `Object.assign(window, { … })` blocks.

    Finds every `Object.assign(window, {` … matching one of these blocks and
    yields the identifier at the start of each property shorthand (the `name,`
    / `name: xxx` entries that reference a binding defined elsewhere). Keep it
    conservative: we only flag identifiers that appear as a lone property value
    (shorthand `name`) at one nesting level below the block, since that is the
    pattern this codebase uses. Aliased keys like `saveVocabCard: saveVocab`
    resolve to their value side, handled by resolving the *value* identifier.
    """
    used = set()
    # Shorthand property `name,` — the value is an unqualified identifier.
    used.update(
        re.findall(r"^\s*([A-Za-z_$][\w$]*)\s*,\s*$", src, re.M)
    )
    # Property `alias: name` → resolve `name` (the value side).
    used.update(
        re.findall(r"^\s*[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*)\s*,?\s*$", src, re.M)
    )
    return used


def _exposer_blocks(src):
    """Yield the text of each `Object.assign(window, {` block body."""
    blocks = []
    marker = re.compile(r"\bObject\.assign\(window,\s*\{", re.S)
    start = 0
    while True:
        m = marker.search(src, start)
        if not m:
            break
        open_brace = m.end() - 1  # index of '{'
        # scan for the matching closing brace
        depth = 1
        i = open_brace + 1
        in_str = None
        while i < len(src) and depth:
            ch = src[i]
            if in_str:
                if ch == in_str and src[i - 1] != "\\":
                    in_str = None
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        blocks.append(src[open_brace + 1 : i - 1])
        start = i
    return blocks


def _dangling_exposer_violations():
    violations = []
    modules = _load_modules()
    jsdir = Path("static/js")
    for js in sorted(jsdir.glob("*.js")):
        src = js.read_text(encoding="utf-8")
        blocks = _exposer_blocks(src)
        if not blocks:
            continue
        bound = _module_local_bindings(src)
        # also bind the module's own exported names (function decls are already
        # in `bound`; exported consts are too) — add re-exported aliases resolved
        # through the graph, so re-exported calls still resolve.
        exported_names = modules.get(js.name, {}).get(
            "own", set()
        ) | set(modules.get(js.name, {}).get("named_reexports", {}).keys())
        for block in blocks:
            for ident in _exposer_block_identifiers(block):
                if ident in bound or ident in exported_names:
                    continue
                # allowance: namespaced/global `window.X`, `Companion`, `ShadowPlayer`
                if ident in {
                    "window", "document", "console", "navigator", "localStorage",
                    "fetch", "alert", "confirm", "setTimeout", "clearTimeout",
                    "setInterval", "clearInterval", "encodeURIComponent",
                    "decodeURIComponent", "JSON", "Math", "Date", "Promise",
                    "Object", "Array", "String", "Number", "Boolean", "Error",
                    "URL", "FileReader", "WebSocket", "Image", "Audio",
                    "Blob", "File", "TextEncoder", "TextDecoder",
                }:
                    continue
                violations.append(
                    f"{js.name} uses bare identifier '{ident}' in a window "
                    f"hook-exposer block, but it is neither imported nor "
                    f"declared in the module (runtime ReferenceError → dead UI)"
                )
    return violations


def test_window_hook_exposer_identifiers_are_bound():
    """No dangling bare identifier in an Object.assign(window,{…}) block.

    Regression for v4.8.2-adjacent 'Android 交互全死 / 前端显示正常': a name
    dropped from the import list but still referenced in the window-exposer
    block throws ReferenceError at module evaluation, aborts the assignment,
    and un-wires every handler. (Bare inside these blocks must resolve to an
    import, a local declaration, or a tabu-global; never a phantom.)
    """
    violations = _dangling_exposer_violations()
    assert not violations, (
        "Frontend exposer block references an unbound identifier (runtime "
        "ReferenceError that kills all JS interaction on Android WebView):\n"
        + "\n".join("  - " + v for v in violations)
    )


def test_writer_a1_email_functions_present_in_main_imports():
    """main.js must import every A1 email/Formular helper it re-exposes.

    Guards the concrete v4.8.2 regression: clearA1Email is re-exported by
    writer.js but was dropped from main.js's `from './writer.js'` import and
    only survived in the window exposer → ReferenceError.
    """
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    imported = {i[0] for i in _parse_named_imports(main_src)}
    for name in (
        "selectA1Formular", "checkA1Formular", "resetA1Formular",
        "selectA1Email", "onA1EmailInput", "diagnoseA1Email",
        "applyA1EmailTemplate", "clearA1Email",
    ):
        assert name in imported, (
            f"main.js uses '{name}' but does not import it from './writer.js'; "
            f"this caused the v4.8.2 ReferenceError → dead Android UI"
        )


def test_a1_engines_present_in_main_window_exposer():
    """main.js must explicitly attach A1Hoeren and A1Lesen to window."""
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    star_imports = _parse_star_namespace_imports(main_src)
    assert "A1Hoeren" in star_imports
    assert "A1Lesen" in star_imports
    blocks = _exposer_blocks(main_src)
    assert blocks, "main.js has no window hook-exposer block"
    exposer_idents = set()
    for block in blocks:
        exposer_idents.update(_exposer_block_identifiers(block))
    assert "A1Hoeren" in exposer_idents
    assert "A1Lesen" in exposer_idents
