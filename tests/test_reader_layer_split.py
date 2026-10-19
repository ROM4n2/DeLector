# -*- coding: utf-8 -*-
"""reader.js 分层解耦独立可用性验收与探针契约测试。

依据 docs/plans/2026-10-19-reader-js-layer-split.md Task 4：
  1. test_rd_syntax_is_an_independent_module:
     - 独立通过 node --check 语法验证（在隔离临时目录中）。
     - import 白名单仅限 ./core.js。
  2. test_rd_syntax_does_not_reference_reader_js:
     - token 级断言：rd-syntax.js 不引用 reader.js 独有的任何顶层符号。
  3. test_rd_syntax_candidate_set_is_closed:
     - 符号闭包：自由标识符与全仓静态 JS 顶层符号的交集严格等于 {"esc", "jsAttr", "normalizeCefrPct"}。
  4. test_rd_syntax_has_no_mutable_module_state:
     - 模块花括号净深度 0 处的 let / var 声明计数为 0。
  5. 变异自证套件：
     - DOM 注入 -> 报 L1 纯格式化层禁dom
     - 顶层 let 注入 -> 报 L1 纯格式化层禁mutable-state 与零状态断言失败
     - reader.js 重新声明迁出符号 -> 报 false-decoupling(renderMiniBar...)
     - 外部符号泄漏 -> 报闭包失败
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
    local_declarations,
    read_js,
)

RD_SYNTAX_REL = "static/js/rd-syntax.js"
READER_REL = "static/js/reader.js"


def test_rd_syntax_is_an_independent_module(tmp_path: Path) -> None:
    """rd-syntax.js 必须具备独立可用性：独立通过 node --check，且 import 仅限 ./core.js。"""
    rd_syntax_path = REPO_ROOT / RD_SYNTAX_REL
    assert rd_syntax_path.exists(), f"{RD_SYNTAX_REL} must exist"
    raw, toks = read_js(rd_syntax_path)

    # 1. 独立通过 node --check（在完全隔离的临时目录下重命名为 .mjs 执行）
    temp_mjs = tmp_path / "rd-syntax.mjs"
    temp_mjs.write_text(raw, encoding="utf-8")
    proc = subprocess.run(
        ["node", "--check", str(temp_mjs)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"node --check failed independently on rd-syntax.js:\n{proc.stderr}"

    # 2. import 模块目标严格仅限 ./core.js
    targets = import_targets(toks)
    assert len(targets) > 0, "rd-syntax.js must import its shared dependencies"
    imported_specs = {spec for _lineno, spec, _form in targets}
    assert imported_specs == {"./core.js"}, (
        f"rd-syntax.js imports must strictly equal {{'./core.js'}}, got: {imported_specs}"
    )


def test_rd_syntax_does_not_reference_reader_js() -> None:
    """token 级断言：rd-syntax.js 不引用 reader.js 独有的任何顶层符号。"""
    rd_syntax_path = REPO_ROOT / RD_SYNTAX_REL
    reader_path = REPO_ROOT / READER_REL

    raw_rd, toks_rd = read_js(rd_syntax_path)
    raw_reader, toks_reader = read_js(reader_path)

    # 收集 reader.js 顶层声明及导入绑定
    reader_top_symbols = local_declarations(toks_reader, top_level_only=True) | import_bindings(toks_reader)

    # 排除 rd-syntax.js 自身合法声明或自 core.js 导入的符号
    rd_declared = local_declarations(toks_rd, top_level_only=False)
    rd_imports = import_bindings(toks_rd)
    reader_exclusive = reader_top_symbols - (rd_declared | rd_imports)

    # rd-syntax.js 中出现的标识符 token
    rd_id_tokens = {t.text for t in toks_rd if t.kind == "id"}
    forbidden_references = rd_id_tokens & reader_exclusive

    assert forbidden_references == set(), (
        f"rd-syntax.js must not reference symbols exclusive to reader.js, found: {forbidden_references}"
    )


def test_rd_syntax_candidate_set_is_closed() -> None:
    """闭包断言：rd-syntax.js 自由标识符与全仓静态 JS 顶层符号的交集严格等于 core.js 授权集。"""
    js_dir = REPO_ROOT / "static" / "js"
    rd_syntax_path = js_dir / "rd-syntax.js"
    raw_rd, toks_rd = read_js(rd_syntax_path)

    # 汇总除 rd-syntax.js 外全仓 static/js/ 顶层声明与导入绑定
    project_symbols: set[str] = set()
    for js_file in js_dir.glob("*.js"):
        if js_file.name == "rd-syntax.js":
            continue
        _raw, toks = read_js(js_file)
        project_symbols.update(local_declarations(toks, top_level_only=True))
        project_symbols.update(import_bindings(toks))

    rd_declared = local_declarations(toks_rd, top_level_only=False)
    rd_id_tokens = {t.text for t in toks_rd if t.kind == "id"}

    # 自由标识符与全仓顶层符号的交集
    free_project_symbols = (rd_id_tokens - rd_declared) & project_symbols

    expected = {"esc", "jsAttr", "normalizeCefrPct"}
    assert free_project_symbols == expected, (
        f"rd-syntax.js candidate set closure failure: expected {expected}, got {free_project_symbols}"
    )


def test_rd_syntax_has_no_mutable_module_state() -> None:
    """rd-syntax.js 顶层（花括号净深度 0 处）let / var 声明计数必须严格为 0。"""
    rd_syntax_path = REPO_ROOT / RD_SYNTAX_REL
    raw, toks = read_js(rd_syntax_path)

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

    assert len(top_level_mutables) == 0, (
        f"rd-syntax.js must have 0 top-level mutable state declarations (let/var), found: {top_level_mutables}"
    )


def test_reader_js_does_not_redefine_rd_syntax_symbols() -> None:
    """防假解耦断言：reader.js 顶层不得重新定义已迁出至 rd-syntax.js 的符号。"""
    rd_syntax_path = REPO_ROOT / RD_SYNTAX_REL
    reader_path = REPO_ROOT / READER_REL

    _raw_rd, toks_rd = read_js(rd_syntax_path)
    _raw_reader, toks_reader = read_js(reader_path)

    rd_exported = local_declarations(toks_rd, top_level_only=True)
    reader_declared = local_declarations(toks_reader, top_level_only=True)
    redefined = rd_exported & reader_declared

    assert redefined == set(), (
        f"reader.js must not redefine symbols exported by rd-syntax.js (false-decoupling), found: {redefined}"
    )

    # 同时断言 reader.js 不存在导入名与顶层本地声明同名（ES 链接期 SyntaxError）
    dupes = import_bindings(toks_reader) & reader_declared
    assert dupes == set(), f"reader.js duplicate declarations found: {dupes}"


# ══ 变异自证套件 (Mutation Self-Proof Suite) ══════════════════════════════════


def test_mutation_proof_dom_injection_trips_gate(tmp_path: Path) -> None:
    """变异自证 1: 在 rd-syntax.js 注入 document.，必须触发 L1 纯格式化层禁dom 门禁规则。"""
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    shutil.copytree(REPO_ROOT / "static" / "js", js_dir, dirs_exist_ok=True)

    target = js_dir / "rd-syntax.js"
    anchor = "export function renderMiniBar(stats) {"
    injected = "document.getElementById('probe');\n" + anchor
    content = target.read_text(encoding="utf-8")
    assert content.count(anchor) == 1
    target.write_text(content.replace(anchor, injected, 1), encoding="utf-8")

    violations = collect_violations(js_dir, None)
    rd_violations = [v for v in violations if v.rel_path == "static/js/rd-syntax.js"]
    rules = [v.rule for v in rd_violations]
    assert any("禁dom" in r for r in rules), f"Expected '禁dom' rule violation, got: {rules}"


def test_mutation_proof_top_level_let_trips_gate_and_state_check(tmp_path: Path) -> None:
    """变异自证 2: 在 rd-syntax.js 注入顶层 let，必须触发禁mutable-state与零可变状态断言。"""
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    shutil.copytree(REPO_ROOT / "static" / "js", js_dir, dirs_exist_ok=True)

    target = js_dir / "rd-syntax.js"
    anchor = "export function renderMiniBar(stats) {"
    injected = "let injectedState = 42;\n" + anchor
    content = target.read_text(encoding="utf-8")
    assert content.count(anchor) == 1
    target.write_text(content.replace(anchor, injected, 1), encoding="utf-8")

    violations = collect_violations(js_dir, None)
    rd_violations = [v for v in violations if v.rel_path == "static/js/rd-syntax.js"]
    rules = [v.rule for v in rd_violations]
    assert any("禁mutable-state" in r for r in rules), f"Expected '禁mutable-state', got: {rules}"

    # 同时断言零状态检查本地捕获到顶层 let
    _raw, toks = read_js(target)
    depth = 0
    muts: list[str] = []
    for t in toks:
        if t.kind == "punct":
            if t.text == "{":
                depth += 1
            elif t.text == "}":
                depth = max(0, depth - 1)
        elif t.kind == "id" and depth == 0 and t.text in ("let", "var"):
            muts.append(t.text)
    assert len(muts) == 1 and muts[0] == "let"


def test_mutation_proof_redefinition_in_reader_trips_false_decoupling(tmp_path: Path) -> None:
    """变异自证 3: 在 reader.js 重新定义已迁出符号 renderMiniBar，必须被防假解耦断言拦截。"""
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    shutil.copytree(REPO_ROOT / "static" / "js", js_dir, dirs_exist_ok=True)

    target = js_dir / "reader.js"
    injected = "\nfunction renderMiniBar() { return ''; }\n"
    content = target.read_text(encoding="utf-8")
    target.write_text(content + injected, encoding="utf-8")

    _raw_rd, toks_rd = read_js(js_dir / "rd-syntax.js")
    _raw_reader, toks_reader = read_js(target)

    rd_exported = local_declarations(toks_rd, top_level_only=True)
    reader_declared = local_declarations(toks_reader, top_level_only=True)
    redefined = rd_exported & reader_declared

    assert "renderMiniBar" in redefined, (
        f"Expected 'renderMiniBar' in redefined symbols, got: {redefined}"
    )


def test_mutation_proof_foreign_symbol_trips_candidate_closure(tmp_path: Path) -> None:
    """变异自证 4: 在 rd-syntax.js 引入未授权外部符号 notify，必须被闭包断言检测并拒绝。"""
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    shutil.copytree(REPO_ROOT / "static" / "js", js_dir, dirs_exist_ok=True)

    target = js_dir / "rd-syntax.js"
    anchor = "import { esc, jsAttr, normalizeCefrPct } from './core.js';"
    injected = "import { esc, jsAttr, normalizeCefrPct, notify } from './core.js';\nnotify('leak');"
    content = target.read_text(encoding="utf-8")
    assert content.count(anchor) == 1
    target.write_text(content.replace(anchor, injected, 1), encoding="utf-8")

    _raw, toks = read_js(target)
    rd_declared = local_declarations(toks, top_level_only=False)
    rd_id_tokens = {t.text for t in toks if t.kind == "id"}

    project_symbols: set[str] = set()
    for js_file in js_dir.glob("*.js"):
        if js_file.name == "rd-syntax.js":
            continue
        _r, tks = read_js(js_file)
        project_symbols.update(local_declarations(tks, top_level_only=True))
        project_symbols.update(import_bindings(tks))

    free_symbols = (rd_id_tokens - rd_declared) & project_symbols
    assert "notify" in free_symbols, "Injected foreign symbol 'notify' must be detected in free symbols"
    assert free_symbols != {"esc", "jsAttr", "normalizeCefrPct"}


def test_mutation_proof_syntax_error_trips_node_check(tmp_path: Path) -> None:
    """变异自证 5: 语法损坏的 rd-syntax.js 必须让 node --check 报非零退出码。"""
    temp_mjs = tmp_path / "broken.mjs"
    temp_mjs.write_text("export function broken() { const a = ; }", encoding="utf-8")
    proc = subprocess.run(
        ["node", "--check", str(temp_mjs)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode != 0
