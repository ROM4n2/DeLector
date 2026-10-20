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

import re
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

    # 只统计 export 出来的：函数声明 + export const 别名都算「导出面」
    raw = (REPO_ROOT / RD_API_REL).read_text(encoding="utf-8")
    exported = set(re.findall(r"^export\s+(?:async\s+)?function\s+(\w+)", raw, re.M))
    exported |= set(re.findall(r"^export\s+const\s+(\w+)", raw, re.M))

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
    raw_api = (REPO_ROOT / RD_API_REL).read_text(encoding="utf-8")
    exported = set(re.findall(r"^export\s+(?:async\s+)?function\s+(\w+)", raw_api, re.M))
    exported |= set(re.findall(r"^export\s+const\s+(\w+)", raw_api, re.M))

    imported_anywhere: set[str] = set()
    for js_file in js_dir.glob("*.js"):
        if js_file.name == "rd-api.js":
            continue
        _raw, toks = read_js(js_file)
        for _lineno, spec_path, _form in import_targets(toks):
            if spec_path.strip().lstrip("./").split("?")[0] != "rd-api.js":
                continue
            imported_anywhere |= import_bindings(toks)

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
