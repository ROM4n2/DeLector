# -*- coding: utf-8 -*-
"""rd-api.js（L2 持久化访问层）独立可用性验收与变异自证。

依据 docs/plans/2026-10-19-reader-api-layer-split.md Task 4：
  1. test_rd_api_is_an_independent_module:
     - 独立通过 node --check（隔离临时目录内改名为 .mjs）。
     - import 白名单严格等于 {"./core.js"}。
  2. test_rd_api_does_not_reference_reader_js:
     - token 级断言：rd-api.js 不引用 reader.js 独有的任何顶层符号。
  3. test_rd_api_export_surface_is_exactly_the_endpoints:
     - 导出面严格等于 14 个端点函数（回归守卫：Task 3 曾产出 28 个导出，
       其中 14 个是零引用的 `*Remote` 别名）。
  4. test_rd_api_has_no_dead_exports:
     - 每一个导出符号都必须被 static/js 下至少一个模块真实 import。
       （这是上面那条缺陷的**机制级**守卫：别名不是兼容层，是债。）
  5. test_rd_api_has_no_mutable_module_state:
     - 顶层（花括号净深度 0 处）let / var 计数为 0。
  6. test_reader_js_does_not_redeclare_rd_api_symbols:
     - 防假解耦 + ESM 链接期重复声明守卫。
  7. 变异自证套件：
     - DOM 注入 -> 禁dom
     - 弹窗注入 -> 禁toast
     - 顶层 let -> 禁mutable-state
     - 未注册路由 -> route-path-unregistered
     - 方法不匹配 -> method-mismatch
     - 语法损坏 -> node --check exit 1
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.check_frontend_layers import (  # noqa: E402
    collect_violations,
    import_bindings,
    import_targets,
    load_backend_route_patterns,
    local_declarations,
    read_js,
    tokenize,
)

RD_API_REL = "static/js/rd-api.js"
READER_REL = "static/js/reader.js"

#: 计划规格：恰好 14 个端点函数，一个不多一个不少。
EXPECTED_ENDPOINTS = frozenset({
    "removeArticle",
    "fetchArticles",
    "fetchArticle",
    "lookupVocab",
    "lookupGrammar",
    "saveVocabCard",
    "saveGrammarCard",
    "fetchCardCounts",
    "fetchArticleNotes",
    "saveArticleNote",
    "removeNote",
    "fetchNoteAssist",
    "saveSyntaxStats",
    "fetchSyntaxStats",
})


def _rd_api_tokens():
    path = REPO_ROOT / RD_API_REL
    assert path.exists(), f"{RD_API_REL} must exist"
    return read_js(path)


def _exported_names(toks) -> set[str]:
    """token 级导出面（导出名，不是本地名）。

    为什么不能用 `^export` 正则：`export { a as b }` 块里的名字对列 0 正则是
    **隐形**的，而块内 `as` 右边才是真正的导出名。rd-api.js 那 14 个 `*Remote`
    别名当初就是这种形态，用正则守卫等于没守 —— 把整块别名加回来照样全绿。

    覆盖：`export [async] function|const|let|var|class X`、`export { a, b as c }`、
    `export * from '…'`（返回哨兵 `*`，调用方应判红）。
    """
    names: set[str] = set()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "id" or t.text != "export":
            continue
        j = i + 1
        if j >= n:
            continue
        # export [async] function|const|let|var|class NAME
        k = j
        if toks[k].kind == "id" and toks[k].text == "async":
            k += 1
        if k < n and toks[k].kind == "id" and toks[k].text in ("function", "const", "let", "var", "class"):
            k += 1
            while k < n and toks[k].kind == "punct" and toks[k].text == "*":
                k += 1
            if k < n and toks[k].kind == "id":
                names.add(toks[k].text)
            continue
        # export { a, b as c }
        if toks[j].kind == "punct" and toks[j].text == "{":
            depth = 0
            item: list[tuple[str, str]] = []
            items: list[list[tuple[str, str]]] = []
            k = j
            while k < n:
                tk = toks[k]
                if tk.kind == "punct" and tk.text == "{":
                    depth += 1
                    if depth == 1:
                        k += 1
                        continue
                elif tk.kind == "punct" and tk.text == "}":
                    depth -= 1
                    if depth == 0:
                        items.append(item)
                        break
                if depth == 1:
                    if tk.kind == "punct" and tk.text == ",":
                        items.append(item)
                        item = []
                    elif tk.kind in ("id", "str"):
                        item.append((tk.kind, tk.text))
                k += 1
            for it in items:
                ids = [x[1] for x in it if x[0] == "id"]
                strs = [x[1] for x in it if x[0] == "str"]
                if ids:
                    # a as b -> 导出名是 b
                    names.add(ids[2] if len(ids) >= 3 and ids[1] == "as" else ids[0])
                elif strs:
                    # export { "x" as y } 里的字符串名不是合法标识符，按原样记
                    names.add(strs[0])
            continue
        # export * from '…'
        if toks[j].kind == "punct" and toks[j].text == "*":
            names.add("*")
    return names


def _imported_names_from(toks, target: str) -> set[str]:
    """该模块从 `target` 模块 import 进来的**源名**集合（`a as b` 取 a）。

    必须按 import 语句逐条匹配 specifier：把「任何 import 了 rd-api.js 的模块
    的全部绑定名」并进来，会让 `import { esc } from './core.js'` 里的 `esc`
    也被算成「有人用了」—— 死导出守卫就被自己的宽松算法废掉了。
    """
    names: set[str] = set()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "id" or t.text != "import":
            continue
        j = i + 1
        spec = None
        braces: list[tuple[str, str]] = []
        depth = 0
        while j < n:
            tk = toks[j]
            if tk.kind == "punct" and tk.text == ";":
                break
            if tk.kind == "punct" and tk.text == "{":
                depth += 1
                j += 1
                continue
            if tk.kind == "punct" and tk.text == "}":
                depth -= 1
                j += 1
                continue
            if depth > 0 and tk.kind in ("id", "str"):
                braces.append((tk.kind, tk.text))
            elif tk.kind == "id" and tk.text == "from":
                if j + 1 < n and toks[j + 1].kind == "str":
                    spec = toks[j + 1].text
                break
            elif tk.kind == "str" and depth == 0:
                spec = tk.text  # 副作用型 import './x.js'
                j += 1
                continue
            j += 1
        if spec is None:
            continue
        if spec.strip().lstrip("./").split("?")[0] != target:
            continue
        # 逐个 item：a / a as b ── 取源名 a
        item: list[str] = []
        for kind, text in braces:
            if kind != "id":
                continue
            if text == "as":
                continue
            item.append(text)
            # 遇到下一个名字前，item 形如 [a] 或 [a, b]（as 被跳过、b 是本地名）
        # 重新按顺序解析，避免把本地名当源名
        ids = [text for kind, text in braces if kind == "id"]
        idx = 0
        while idx < len(ids):
            src = ids[idx]
            if idx + 2 < len(ids) and ids[idx + 1] == "as":
                names.add(src)
                idx += 3
            else:
                names.add(src)
                idx += 1
    return names


def _copy_js_tree(tmp_path: Path) -> Path:
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    shutil.copytree(REPO_ROOT / "static" / "js", js_dir, dirs_exist_ok=True)
    return js_dir


def _violations_for_rd_api(js_dir: Path, rule_fragment: str) -> list[str]:
    """收集 rd-api.js 的违规。

    规则⑤（调用一致性）只在传入真实后端路由表时才执行 —— 传 None 会整条跳过，
    那会让 route-path-unregistered / method-mismatch 两条变异自证**永远是空的绿**。
    故这里显式加载真实路由表。
    """
    violations = collect_violations(js_dir, load_backend_route_patterns())
    return [
        v.rule
        for v in violations
        if v.rel_path == RD_API_REL and rule_fragment in v.rule
    ]


# ══ 1. 独立可用性 ═══════════════════════════════════════════════════════════


def test_rd_api_is_an_independent_module(tmp_path: Path) -> None:
    """rd-api.js 必须能独立通过 node --check，且 import 仅限 ./core.js。"""
    raw, toks = _rd_api_tokens()

    temp_mjs = tmp_path / "rd-api.mjs"
    temp_mjs.write_text(raw, encoding="utf-8")
    proc = subprocess.run(
        ["node", "--check", str(temp_mjs)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        f"node --check failed independently on rd-api.js:\n{proc.stderr}"
    )

    targets = import_targets(toks)
    imported_specs = {spec for _lineno, spec, _form in targets}
    assert imported_specs == {"./core.js"}, (
        f"rd-api.js imports must strictly equal {{'./core.js'}}, got: {imported_specs}"
    )


# ══ 2. 不引用视图层符号 ═════════════════════════════════════════════════════


def test_rd_api_does_not_reference_reader_js() -> None:
    """token 级断言：rd-api.js 不引用 reader.js 独有的任何顶层符号。"""
    _raw_rd, toks_rd = _rd_api_tokens()
    _raw_reader, toks_reader = read_js(REPO_ROOT / READER_REL)

    reader_top = local_declarations(toks_reader, top_level_only=True) | import_bindings(
        toks_reader
    )
    rd_declared = local_declarations(toks_rd, top_level_only=False)
    rd_imports = import_bindings(toks_rd)
    reader_exclusive = reader_top - (rd_declared | rd_imports)

    rd_id_tokens = {t.text for t in toks_rd if t.kind == "id"}
    forbidden = rd_id_tokens & reader_exclusive
    assert forbidden == set(), (
        f"rd-api.js must not reference symbols exclusive to reader.js, found: {forbidden}"
    )


# ══ 3/4. 导出面：恰好 14 个，且零死导出 ═════════════════════════════════════


def test_rd_api_export_surface_is_exactly_the_endpoints() -> None:
    """导出面必须严格等于 14 个端点函数，不允许任何别名/包装膨胀。

    回归背景：Task 3 首版产出 28 个导出（14 个真函数 + 14 个零引用的
    `*Remote` 别名），违反计划的「14 个端点函数」规格。这条用例把规格
    钉成断言，别名再回来就红。
    """
    _raw, toks = _rd_api_tokens()
    declared = local_declarations(toks, top_level_only=True)

    # token 级解析：`export { a as b }` 的导出名是 b，列 0 正则对它完全隐形。
    exported = _exported_names(toks)

    assert exported == EXPECTED_ENDPOINTS, (
        f"rd-api.js export surface drifted.\n"
        f"  missing: {sorted(EXPECTED_ENDPOINTS - exported)}\n"
        f"  extra:   {sorted(exported - EXPECTED_ENDPOINTS)}"
    )
    # 交叉校验：正则解析与词法解析必须一致（防一边漂移掩盖另一边）
    assert exported <= declared, (
        f"regex-exported names not found by the tokenizer: {sorted(exported - declared)}"
    )


def test_rd_api_has_no_dead_exports() -> None:
    """机制级守卫：rd-api.js 的每个导出都必须被 static/js 下至少一个模块真实 import。

    比「导出名白名单」更强的地方 —— 它不针对某一次事故的具体名字，而是
    针对「留下没人用的出口」这个**形态**。别名、兼容层、遗留包装都逃不掉。
    """
    js_dir = REPO_ROOT / "static" / "js"
    _raw_api, toks_api = _rd_api_tokens()
    exported = _exported_names(toks_api)

    imported_anywhere: set[str] = set()
    for js_file in js_dir.glob("*.js"):
        if js_file.name == "rd-api.js":
            continue
        _raw, toks = read_js(js_file)
        # 按 specifier 逐条匹配：只要「这个文件 import 了 rd-api.js」就算，
        # 但只计**来自 rd-api.js 的那条语句**的源名（见函数 docstring）。
        imported_anywhere |= _imported_names_from(toks, "rd-api.js")

    dead = exported - imported_anywhere
    assert dead == set(), (
        f"rd-api.js has dead exports (nobody imports them): {sorted(dead)}"
    )


# ══ 5. 零顶层可变状态 ═══════════════════════════════════════════════════════


def test_rd_api_has_no_mutable_module_state() -> None:
    """顶层（花括号净深度 0 处）let / var 计数必须严格为 0。"""
    _raw, toks = _rd_api_tokens()

    depth = 0
    top_level_mutables: list[str] = []
    for t in toks:
        if t.kind == "punct":
            if t.text == "{":
                depth += 1
            elif t.text == "}":
                depth = max(0, depth - 1)
            continue
        if t.kind == "id" and depth == 0 and t.text in ("let", "var"):
            top_level_mutables.append(f"{t.text} (line {t.line})")

    assert top_level_mutables == [], (
        f"rd-api.js must have 0 top-level mutable state declarations, found: {top_level_mutables}"
    )


# ══ 6. 防假解耦 / 链接期重复声明 ════════════════════════════════════════════


def test_reader_js_does_not_redeclare_rd_api_symbols() -> None:
    """reader.js 顶层不得重新定义 rd-api.js 导出的符号（假解耦 + SyntaxError）。"""
    _raw_rd, toks_rd = _rd_api_tokens()
    _raw_reader, toks_reader = read_js(REPO_ROOT / READER_REL)

    rd_exported = local_declarations(toks_rd, top_level_only=True)
    reader_declared = local_declarations(toks_reader, top_level_only=True)

    redefined = rd_exported & reader_declared
    assert redefined == set(), (
        f"reader.js must not redefine symbols exported by rd-api.js, found: {redefined}"
    )

    dupes = import_bindings(toks_reader) & reader_declared
    assert dupes == set(), f"reader.js duplicate declarations found: {dupes}"


# ══ 7. 变异自证套件 ═════════════════════════════════════════════════════════

_MUTATION_ANCHOR = "export async function removeArticle(id) {"


def _inject(tmp_path: Path, snippet: str) -> Path:
    js_dir = _copy_js_tree(tmp_path)
    target = js_dir / "rd-api.js"
    content = target.read_text(encoding="utf-8")
    assert content.count(_MUTATION_ANCHOR) == 1, (
        f"注入锚点命中 {content.count(_MUTATION_ANCHOR)} 次（符号若改名，锚点必须同步）"
    )
    target.write_text(
        content.replace(_MUTATION_ANCHOR, snippet + "\n" + _MUTATION_ANCHOR, 1),
        encoding="utf-8",
    )
    return js_dir


def test_mutation_proof_dom_injection_trips_l2_ban(tmp_path: Path) -> None:
    """变异 1: 注入 document. → L2 必须报禁dom。"""
    js_dir = _inject(tmp_path, "document.getElementById('probe');")
    assert _violations_for_rd_api(js_dir, "禁dom"), "expected a 禁dom violation"


def test_mutation_proof_toast_injection_trips_l2_ban(tmp_path: Path) -> None:
    """变异 2: 注入 notify( → L2 必须报禁toast。"""
    js_dir = _inject(tmp_path, "notify('probe');")
    assert _violations_for_rd_api(js_dir, "禁toast"), "expected a 禁toast violation"


def test_mutation_proof_top_level_let_trips_state_ban(tmp_path: Path) -> None:
    """变异 3: 注入顶层 let → L2 必须报禁mutable-state。"""
    js_dir = _inject(tmp_path, "let injectedState = 42;")
    assert _violations_for_rd_api(js_dir, "禁mutable-state"), (
        "expected a 禁mutable-state violation"
    )


def test_mutation_proof_unregistered_route_trips_rule5(tmp_path: Path) -> None:
    """变异 4: 注入未注册路由 → 规则⑤ 必须报 route-path-unregistered。"""
    js_dir = _inject(
        tmp_path,
        "export async function _probeUnregistered() {\n"
        "  return api('/api/definitely-not-a-route', { method: 'GET' });\n"
        "}",
    )
    assert _violations_for_rd_api(js_dir, "route-path-unregistered"), (
        "expected a route-path-unregistered violation"
    )


def test_mutation_proof_method_mismatch_trips_rule5(tmp_path: Path) -> None:
    """变异 5: 方法不匹配（POST 打只注册了 GET 的路径）→ method-mismatch。"""
    js_dir = _inject(
        tmp_path,
        "export async function _probeWrongMethod() {\n"
        "  return api('/api/articles', { method: 'POST' });\n"
        "}",
    )
    assert _violations_for_rd_api(js_dir, "method-mismatch"), (
        "expected a method-mismatch violation"
    )


def test_regression_reexport_alias_block_is_detected() -> None:
    """回归：整块 `export { a as b }` 别名必须被导出面守卫看见。

    这是一条**由独立评审打出来的真实绕过**：两条守卫最初用 `^export` 列 0 正则
    抽导出名，于是把下面这 14 个别名整块加回 `rd-api.js`，守卫、`node --check`
    与分层闸**全部保持绿色** —— 而块内名字对正则是隐形的，`as` 右边才是导出名。

    该形态必须红。用 token 级解析后，别名会进 `exported` 集合，于是
    「恰好 14 个端点」与「零死导出」两条同时抓住它。
    """
    raw = (REPO_ROOT / RD_API_REL).read_text(encoding="utf-8")
    NL = chr(10)
    alias_block = (
        NL
        + "export {" + NL
        + "  removeArticle as deleteArticleRemote," + NL
        + "  fetchArticles as fetchArticlesRemote," + NL
        + "  fetchArticle as fetchArticleRemote," + NL
        + "  fetchSyntaxStats as fetchSyntaxStatsRemote" + NL
        + "};" + NL
    )
    mutated = raw + alias_block
    toks = tokenize(mutated)

    exported = _exported_names(toks)
    extra = exported - EXPECTED_ENDPOINTS
    assert extra == {
        "deleteArticleRemote",
        "fetchArticlesRemote",
        "fetchArticleRemote",
        "fetchSyntaxStatsRemote",
    }, f"token-level export parsing must see the `as` right-hand names, got extras: {sorted(extra)}"

    # 这些别名无人 import ⇒ 零死导出守卫同样必须看见它们
    imported = _imported_names_from(tokenize((REPO_ROOT / READER_REL).read_text(encoding="utf-8")), "rd-api.js")
    assert extra - imported == extra, "aliases are not imported anywhere, so they must be dead"


def test_regression_indented_export_const_is_detected() -> None:
    """回归：行首带缩进的 `  export const x = ...` 也必须被看见（列 0 正则的另一漏洞）。"""
    raw = (REPO_ROOT / RD_API_REL).read_text(encoding="utf-8")
    NL = chr(10)
    mutated = raw + NL + "  export const fetchArticlesRemote = fetchArticles;" + NL
    exported = _exported_names(tokenize(mutated))
    assert "fetchArticlesRemote" in exported, (
        "an indented export must not escape the export-surface guard"
    )


def test_mutation_proof_syntax_error_trips_node_check(tmp_path: Path) -> None:
    """变异 6: 语法损坏 → 独立 node --check 必须失败。"""
    _raw, _toks = _rd_api_tokens()
    broken = (REPO_ROOT / RD_API_REL).read_text(encoding="utf-8").replace(
        _MUTATION_ANCHOR, "export async function removeArticle(id) { const a = ; }", 1
    )
    temp_mjs = tmp_path / "broken.mjs"
    temp_mjs.write_text(broken, encoding="utf-8")
    proc = subprocess.run(
        ["node", "--check", str(temp_mjs)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode != 0, "node --check must reject a syntactically broken module"
