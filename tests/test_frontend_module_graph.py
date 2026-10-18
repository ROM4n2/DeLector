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

import wb_source

JS_DIR = Path("static/js")


def _norm(module_ref):
    """Normalize a module reference ('./core.js' / 'core.js') to a bare filename."""
    return module_ref.lstrip("./").split("/")[-1]


# ── Parsers (tuned to this codebase's syntax; see git history for forms) ─────


def _parse_own_exports(src):
    """Names directly exported by the module itself."""
    names = set()
    names.update(re.findall(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", src))
    names.update(re.findall(r"\bexport\s+(?:let|const|var|class)\s+([A-Za-z_$][\w$]*)", src))
    # export { a, b, c }  WITHOUT `from` → module's own exported bindings
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}\s*(?!from\b)", src, re.S):
        for item in m.group(1).split(","):
            item = item.strip()
            if item:
                names.add(item.split(" as ")[0].strip())
    return names


def _parse_named_reexports(src):
    """{exported_name: (source_module, original_name)} for `export {…} from`."""
    result = {}
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", src, re.S):
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
    """[(imported_name, source_module)] for `import {…} from`."""
    result = []
    for m in re.finditer(r"\bimport\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", src, re.S):
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
                violations.append(f"{name} imports '{imported}' from {src_mod}, which does not export it")
        for mod in _parse_star_imports(info["src"]):
            mod = _norm(mod)
            if mod not in modules:
                violations.append(f"{name} does `import *` from missing file {mod}")
        for alias, (src_mod, orig) in info["named_reexports"].items():
            src_mod = _norm(src_mod)
            if src_mod not in modules:
                violations.append(f"{name} re-exports {alias} from missing file {src_mod}")
            elif not _exports_name(modules, src_mod, orig):
                violations.append(f"{name} re-exports {alias} (as {orig}) from {src_mod}, which does not export it")
        for mod in info["star"]:
            mod = _norm(mod)
            if mod not in modules:
                violations.append(f"{name} does `export *` from missing file {mod}")
    return violations


def test_every_named_import_resolves_to_a_real_export():
    violations = _graph_violations()
    assert not violations, (
        "Frontend ES module graph has unresolved imports (link-time SyntaxError "
        "that would kill the whole module graph on Android WebView):\n" + "\n".join("  - " + v for v in violations)
    )


def test_a1_modules_are_not_empty():
    """The exact v4.7.0 regression: 0-byte modules with exports expected."""
    for name in ("a1_cards.js", "a1_writer.js", "a1_hoeren.js", "a1_lesen.js"):
        path = JS_DIR / name
        assert path.exists(), f"{name} is missing"
        src = path.read_text(encoding="utf-8")
        assert len(src.strip()) > 0, f"{name} is empty"
        assert _parse_own_exports(src) or _parse_named_reexports(src), f"{name} exports nothing"


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
    bound: set[str] = set()
    # named imports: `import { a, b as c } from …`
    bound.update(_parse_named_imports(src) and [item[0] for item in _parse_named_imports(src)])
    # star-namespace imports: `import * as NS from …` → binds NS
    bound.update(_parse_star_namespace_imports(src).keys())
    # default import
    bound.update(re.findall(r"\bimport\s+([A-Za-z_$][\w$]*)\s*,?[^;]*\bfrom\b", src))
    # own top-level declarations
    bound.update(re.findall(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", src))
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
    used.update(re.findall(r"^\s*([A-Za-z_$][\w$]*)\s*,\s*$", src, re.M))
    # Property `alias: name` → resolve `name` (the value side).
    used.update(re.findall(r"^\s*[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*)\s*,?\s*$", src, re.M))
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
        exported_names = modules.get(js.name, {}).get("own", set()) | set(
            modules.get(js.name, {}).get("named_reexports", {}).keys()
        )
        for block in blocks:
            for ident in _exposer_block_identifiers(block):
                if ident in bound or ident in exported_names:
                    continue
                # allowance: namespaced/global `window.X`, `Companion`, `ShadowPlayer`
                if ident in {
                    "window",
                    "document",
                    "console",
                    "navigator",
                    "localStorage",
                    "fetch",
                    "alert",
                    "confirm",
                    "setTimeout",
                    "clearTimeout",
                    "setInterval",
                    "clearInterval",
                    "encodeURIComponent",
                    "decodeURIComponent",
                    "JSON",
                    "Math",
                    "Date",
                    "Promise",
                    "Object",
                    "Array",
                    "String",
                    "Number",
                    "Boolean",
                    "Error",
                    "URL",
                    "FileReader",
                    "WebSocket",
                    "Image",
                    "Audio",
                    "Blob",
                    "File",
                    "TextEncoder",
                    "TextDecoder",
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
        "selectA1Formular",
        "checkA1Formular",
        "resetA1Formular",
        "selectA1Email",
        "onA1EmailInput",
        "diagnoseA1Email",
        "applyA1EmailTemplate",
        "clearA1Email",
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


# ── Workbench 进度 server 镜像同步（wbsync）─────────────────────────────────
# 契约（docs/plans/archive/workbench-progress-server-sync.md Task 3）：
#  1. 5 个 saveXxx() 定义行都挂 `wbsync.push()` —— 本地一落盘就往 server 推；
#  2. `wbsync.init()` 只在启动块 async IIFE（IDB hydrate 完成）之后才被调用；
#  3. 有 轮询(pull/setInterval) / 切走(pushNow) / visibilitychange 三条路径；
#  4. 用到 X-WB-Key + /api/wb/state，且 __wb 调试出口暴露 wbsync。
# 读法（C7 Task 1）：全部经 `tests/wb_source.py` 按**声明体**读，不再用 `splitlines()`
# 下标钉物理行。拆分 / 格式化造成的位置漂移不再产生假红；每条断言只钉契约，判别力
# 严格强于原「同一物理行」钉（逐条对比见 WORKMEMORY/handoff 与本次提交的说明）：
# 原钉是**格式事实**（一换行就红、被塞进回调却照样绿），新钉是**行为事实**。


def _workbench_src() -> str:
    """workbench 源文本。拆分后只需在这里补文件路径（实参顺序 = 拼接顺序）。

    C7 Task 5 块 2（seed-persist）起 `saveWords` / `loadAll` / 整套 IDB 声明住在
    `static/js/wb-idb.js`（入口页用普通 <script src> 在主内联脚本之前加载）。
    C7 Task 5 块 4（wbsync）起 `const wbsync` IIFE（含 push/pushNow/pull/init）住在
    `static/js/wb-sync.js` —— Pin1 的「落盘后推一次」与 Pin2 的「hydrate 后初始化」
    都跨了文件（写调用在 wb-idb.js / HTML，被调方在 wb-sync.js）。
    故这里读**三个文件**：声明所在模块在前、使用它的 HTML 在后 —— `decl_body` /
    `line_of` / `occurs_before` 全都作用在这份拼出来的「虚拟单文件」上，断言写法与
    判别力不变，且两条钉子各自**新增**一条跨文件断言（wbsync 必须真的提供 push / init：
    否则 saveXxx 末尾那行与启动块里的 init() 是 TypeError，不是「存了就推」/「hydrate
    完就同步」）。Pin1 的四条、Pin2 的包含关系与 depth==0 一条未减。
    """
    return wb_source.read_source(
        "static/js/wb-sync.js", "static/js/wb-idb.js", "static/german/workbench.html"
    )


def test_workbench_wbsync_save_hooks_on_each_store():
    """每个 saveXxx() 都必须：落盘**之后**、任何 await **之前**、无条件推一次。

    四条同时成立才算过（任一被破坏即红）：
      ① push 在该函数**大括号配平体**内 —— 被移出函数体即红（原断言也抓得到）；
      ② push 是函数体**顶层**语句 —— 被塞进 if 块 / 回调即红（原断言抓不到）；
      ③ push 早于任一 await —— 等 IO 才推、关页即丢（原断言抓不到）；
      ④ push 晚于 localStorage.setItem —— 先推后落盘、崩溃即失（原断言抓不到）。
    """
    src = _workbench_src()
    for fn in ("saveWords", "saveCards", "saveLog", "saveWrong", "saveSettings"):
        body = wb_source.decl_body(src, f"function {fn}()")
        assert "wbsync.push()" in body, f"{fn}() 函数体内没有 wbsync.push()（保存后不推 server）"
        push_at = body.index("wbsync.push()")
        assert wb_source.depth_at(body, push_at) == 0, (
            f"{fn}() 的 wbsync.push() 不在函数体顶层"
            f"（嵌进块 / 带花括号的子函数或回调 ⇒ 不是保存即推；"
            f"无花括号的表达式体回调不产生花括号，本钉抓不到）"
        )
        assert wb_source.occurs_before(body, "wbsync.push()", "await"), (
            f"{fn}() 的 wbsync.push() 排在 await 之后（等 IO 才推 ⇒ 关页就丢）"
        )
        assert wb_source.occurs_before(body, "localStorage.setItem", "wbsync.push()"), (
            f"{fn}() 的 wbsync.push() 排在 localStorage.setItem 之前（先推后落盘 ⇒ 崩溃即失）"
        )
    # 跨文件（C7 Task 5 块 4）：调用点写在这里、被调方住在 static/js/wb-sync.js。
    # 只有对端**真的把 push 暴露出来**，上面那四条的「推一次」才成立 —— 名字被改名或从
    # 返回对象里删掉时，运行期是 TypeError（存了也不推），静态四条却照样绿。
    # 锚点带前导换行：`const wbsync = ` 也出现在本模块**文件头注释**里（说明它是什么），
    # 裸串会切到注释内部的 `{ … }` 占位上，断言就变成对文档撒谎。行首形式只命中真声明。
    wbsync_body = wb_source.decl_body(src, "\nconst wbsync = ")
    assert re.search(r"\bpush:\s*push\b", wbsync_body), (
        "static/js/wb-sync.js 的 wbsync 返回对象里没有 push —— saveXxx() 末尾的 "
        "wbsync.push() 会是 TypeError（保存后根本不推 server）"
    )


def test_workbench_wbsync_init_after_idb_hydrate_block():
    """wbsync.init() 必须在启动 async IIFE **体内**、hydrate 之后、且无条件执行。

    原写法只比三个行号下标（loadAll(); < (async () => { < wbsync.init();）：那是行序
    事实，IIFE 体被改写（如 init 被移进 try）时不必然成立。新写法升为**包含关系**。
    """
    src = _workbench_src()
    assert wb_source.line_of(src, "loadAll();") < wb_source.line_of(src, "(async () => {"), (
        "启动块必须是 loadAll() → async IIFE 的顺序"
    )
    startup = wb_source.decl_body(src, "(async () => {")
    assert "wbsync.init()" in startup, (
        "wbsync.init() 不在启动 async IIFE 体内（早于 IDB hydrate ⇒ 推的是被覆盖前的旧 S）"
    )
    assert wb_source.occurs_before(startup, "idbHydrate()", "wbsync.init()"), (
        "wbsync.init() 早于 idbHydrate()（hydrate 还没覆盖 S 就推 ⇒ server 镜像被旧值覆盖）"
    )
    init_at = startup.index("wbsync.init()")
    assert wb_source.depth_at(startup, init_at) == 0, (
        "wbsync.init() 不在启动 IIFE 的顶层"
        "（嵌进带花括号的 try / 块 / 子函数或回调 ⇒ hydrate 抛错被 catch 吞掉后就永不初始化；"
        "无花括号的表达式体回调不产生花括号，本钉抓不到）"
    )
    # 跨文件（C7 Task 5 块 4）：init 必须由 wb-sync.js 的 wbsync 返回对象暴露，
    # 且 init 本体真的把同步启动起来（调 boot()）—— 只暴露一个空壳 init 同样是死同步。
    # 同上：锚点带前导换行，避开文件头注释里对 `const wbsync = (() => { … })();` 的引用。
    wbsync_body = wb_source.decl_body(src, "\nconst wbsync = ")
    assert re.search(r"\binit:\s*init\b", wbsync_body), (
        "static/js/wb-sync.js 的 wbsync 返回对象里没有 init —— 启动块里的 wbsync.init() "
        "会是 TypeError（IDB hydrate 完成后同步永不启动）"
    )
    init_body = wb_source.decl_body(wbsync_body, "function init()")
    assert "boot()" in init_body, (
        "wbsync 的 init() 没有调 boot() —— 空壳 init 会让 wbsync.init() 变成无操作"
        "（拉取/轮询/推送三条路径都不起来）"
    )


def test_workbench_wbsync_trigger_paths_present():
    src = _workbench_src()
    # 模块头、端点与鉴权头
    assert "const wbsync = " in src
    assert "X-WB-Key" in src
    assert '"/api/wb/state"' in src or "'/api/wb/state'" in src
    # visibilitychange：回前台拉 / 离开前推，且监听必须挂在 wbsync 模块**体内**
    vis = wb_source.line_of(src, "visibilitychange")
    assert vis > wb_source.line_of(src, "const wbsync = "), (
        "visibilitychange 监听不在 wbsync 模块内（漂到模块外 ⇒ 拿不到 pushNow/pull 闭包）"
    )
    handler = wb_source.decl_body(src, 'document.addEventListener("visibilitychange"')
    else_at = re.search(r"\belse\b", handler)
    assert else_at, "visibilitychange 处理体没有 else 分支（必须「切走推 / 回前台拉」两条路径）"
    hidden_branch = handler[: else_at.start()]
    visible_branch = handler[else_at.end() :]
    assert wb_source.occurs_before(hidden_branch, "document.hidden", "pushNow()"), (
        "pushNow() 没有被 document.hidden 守着（每次可见性变化都推 ⇒ 无谓的写放大）"
    )
    assert "pull()" in visible_branch and "pushNow()" not in visible_branch, (
        "回前台分支必须只 pull()（混进 pushNow() ⇒ 回前台反把本地值推上去覆盖远端）"
    )
    # 轮询路径
    assert "setInterval" in src
    # __wb 调试出口暴露 wbsync（对象字面量跨多行 ⇒ 按大括号配平取整块，不再扫到 "};"）
    debug_obj = wb_source.decl_body(src, "window.__wb")
    expose = re.search(r"\bwbsync\s*:\s*wbsync\b", debug_obj)
    assert expose, "__wb 调试出口未暴露 wbsync"
    assert wb_source.depth_at(debug_obj, expose.start()) == 0, (
        "wbsync 不是 __wb 的顶层键（嵌进子对象 ⇒ 控制台 __wb.wbsync 取不到）"
    )


# ── 听力微训工坊（listen-lab.js）：非孤岛、无循环依赖、导出齐全 ────────────────
# Task 5（红线 11 契约探针配套）：listen-lab.js 由 main.js `import * as ListenLab`
# 命名空间接线（main.js:162）。若它变成孤岛（没人 import）、或与其它模块成环
# （求值序不确定 → 断裂传播到整个 ES 模块图），模块图守卫必须红。
# 注意：listen-lab 的 named import（core.js 的 api/esc/notify、player.js 的
# playGermanAudio）已由上方 test_every_named_import_resolves_to_a_real_export
# 自动覆盖（_load_modules 全量扫 static/js/*.js）。

# main.js 通过 `import * as ListenLab` 消费的全部导出名（也是行为探针的驱动面）
LISTEN_LAB_EXPORTS = (
    "enterListenLab",
    "stopListenLab",
    "setListenLevel",
    "selectListenMaterial",
    "setListenMode",
    "listenPlayToggle",
    "listenNext",
    "listenPrev",
    "listenReplay",
    "listenJump",
    "listenSetSpeed",
    "listenSetFlow",
    "listenSkip",
    "listenSubmitDictation",
    "listenSubmitCloze",
    "listenRestart",
    "listenExit",
)


def _import_edges(modules):
    """{module: {站内被 import 的模块}} —— named import + star import 的边。"""
    edges = {}
    for name, info in modules.items():
        targets = set()
        for _, src_mod in _parse_named_imports(info["src"]):
            t = _norm(src_mod)
            if t in modules:
                targets.add(t)
        for mod in _parse_star_imports(info["src"]):
            t = _norm(mod)
            if t in modules:
                targets.add(t)
        edges[name] = targets
    return edges


def _cycles_through(modules, target):
    """DFS：找所有从 target 出发能回到 target 的环（target 必在环上）。"""
    edges = _import_edges(modules)
    found: list[list[str]] = []

    def dfs(node: str, path: list[str], seen: set[str]) -> None:
        if found:
            return
        for nxt in edges.get(node, ()):
            if nxt == target:
                found.append(path + [nxt])
                return
            if nxt in seen:
                continue
            dfs(nxt, path + [nxt], seen | {nxt})

    dfs(target, [target], {target})
    return found


def test_listen_lab_not_an_island():
    """listen-lab.js 必须存在、非空、且被 main.js import（孤岛 = 前端接线静默失效）。"""
    path = JS_DIR / "listen-lab.js"
    assert path.exists(), "listen-lab.js 缺失"
    src = path.read_text(encoding="utf-8")
    assert len(src.strip()) > 0, "listen-lab.js 为空（同 v4.7.0 a1_cards 空文件回归）"
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    assert "listen-lab.js" in main_src, "listen-lab.js 是孤岛：main.js 未 import 它"


def test_listen_lab_exports_complete():
    """main.js `import * as ListenLab` 依赖的全部导出名必须在 listen-lab.js 里。"""
    modules = _load_modules()
    own = modules["listen-lab.js"]["own"]
    for name in LISTEN_LAB_EXPORTS:
        assert name in own, f"listen-lab.js 缺导出 {name}"


def test_listen_lab_no_circular_dependency():
    """listen-lab.js 不得出现在任何 import 环上（环破坏 ES 模块求值序）。"""
    cycles = _cycles_through(_load_modules(), "listen-lab.js")
    assert not cycles, f"listen-lab.js 存在循环依赖：{cycles}"


# ── 长难句精读工坊（hard-sentences.js）：非孤岛、无循环依赖、导出齐全 ────────
# Task 5（红线 11 契约探针配套）：hard-sentences.js 由 main.js `import * as
# HardSentences` 命名空间接线（main.js:163，window 挂载于 :1096）。若它变成孤岛
# （没人 import）、或与其它模块成环（求值序不确定 → 断裂传播到整个 ES 模块图），
# 模块图守卫必须红。注意：其 named import（core.js 的 api/esc/notify）已由上方
# test_every_named_import_resolves_to_a_real_export 自动覆盖。

# main.js 通过 `import * as HardSentences` 消费 / 模块内 `HardSentences.xxx`
# onclick 直调的全部导出名（也是行为探针的驱动面）
HARD_SENT_EXPORTS = (
    "enterHardSentences",
    "stopHardSentences",
    "setHardSource",
    "setHardLevel",
    "pickHardMaterial",
    "revealTree",
    "lookupWord",
    "addCard",
    "nextCard",
    "prevCard",
    "restart",
    "exit",
)


def test_hard_sentences_not_an_island():
    """hard-sentences.js 必须存在、非空、且被 main.js import（孤岛 = 前端接线静默失效）。"""
    path = JS_DIR / "hard-sentences.js"
    assert path.exists(), "hard-sentences.js 缺失"
    src = path.read_text(encoding="utf-8")
    assert len(src.strip()) > 0, "hard-sentences.js 为空（同 v4.7.0 a1_cards 空文件回归）"
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    assert "hard-sentences.js" in main_src, "hard-sentences.js 是孤岛：main.js 未 import 它"


def test_hard_sentences_exports_complete():
    """main.js `import * as HardSentences` 依赖的全部导出名必须在 hard-sentences.js 里。"""
    modules = _load_modules()
    own = modules["hard-sentences.js"]["own"]
    for name in HARD_SENT_EXPORTS:
        assert name in own, f"hard-sentences.js 缺导出 {name}"


def test_hard_sentences_no_circular_dependency():
    """hard-sentences.js 不得出现在任何 import 环上（环破坏 ES 模块求值序）。"""
    cycles = _cycles_through(_load_modules(), "hard-sentences.js")
    assert not cycles, f"hard-sentences.js 存在循环依赖：{cycles}"
