# -*- coding: utf-8 -*-
"""`tools/check_frontend_layers.py` 的验收测试（计划 `2026-10-19-writer-js-modularization.md` Task 4）。

三层证据，缺一不可：

  1. **纯函数单测**（`strip_comments` 等）—— 与仓库内容无关的判据本身。
  2. **合成夹具**（`tmp_path` 造模块）—— 证明每条规则**能变红**，而不是「跑当前树恰好绿」。
     这是「闸是规范，不是描述」的落地方式。
  3. **真树派生变异**（复制生产 `wr-format.js`/`wr-api.js`/`writer.js` 到 tmp 后注入缺陷）
     —— 证明规则作用在**真实文件**上仍能变红，且**不动生产文件**（复制而非就地改：
     就地改一旦断言抛出会把变异留在仓库里，那才是真事故）。

规则 → 变异（与计划 Task 3 变异自证表一一对应）：
  ① L1 禁令      <- M4 纯层注入 `fetch`        （现存门禁 UNCAUGHT）
  ② L2 禁令      <- M1 L2 注入 `document`      （现存门禁 UNCAUGHT）
  ③ 反向依赖     <- 低层 import `writer.js`    （分层倒置）
  ④ 重复声明     <- 导入名与本地声明同名        （`node --check` 才抓得到，CI 不跑它）
  ⑤ 方法一致     <- M2 `DELETE` -> `POST`      （现存门禁 UNCAUGHT）
  ⑥ 防假解耦     <- M5 `writer.js` 重定义已迁出符号
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_DIR = REPO_ROOT / "static" / "js"
GATE = REPO_ROOT / "tools" / "check_frontend_layers.py"

_LAYER_MODULES = ("wr-format.js", "wr-api.js", "writer.js")


def _load_gate() -> Any:
    """按路径加载被守卫脚本（`tools/` 不是 package，不能直接 import）。"""
    name = "check_frontend_layers_under_test"
    spec = importlib.util.spec_from_file_location(name, GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> Any:
    return _load_gate()


@pytest.fixture()
def js_dir(tmp_path: Path) -> Path:
    """把生产中三个被纳管模块**复制**到 tmp（真内容，不就地改）。"""
    d = tmp_path / "js"
    d.mkdir()
    for name in _LAYER_MODULES:
        shutil.copyfile(JS_DIR / name, d / name)
    return d


def run_gate(js_dir_arg: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), "--js-dir", str(js_dir_arg), "--skip-route-parity"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )


def rules_of(gate: Any, js_dir_arg: Path) -> list[str]:
    return [v.rule for v in gate.collect_violations(js_dir_arg, None)]


def inject(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{path.name}: 注入锚点命中 {text.count(old)} 次"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")


# ══ 1. 纯函数 ══════════════════════════════════════════════════════════════


def test_strip_comments_preserves_line_count_and_columns(gate: Any) -> None:
    src = "const a = 1;// document\n/* fetch( */\nconst b = 2;\n"
    out = gate.strip_comments(src)
    assert out.count("\n") == src.count("\n")
    assert "document" not in out and "fetch(" not in out
    assert out.splitlines()[0].startswith("const a = 1;")
    assert out.splitlines()[2] == "const b = 2;"


def test_strip_comments_does_not_swallow_string_literals(gate: Any) -> None:
    """字符串内容保留（口径：字符串不剥离；剥离会让字符串里的被禁词漏检）。"""
    src = "const p = '/api/essays';\n"
    assert "'/api/essays'" in gate.strip_comments(src)


def test_normalize_path_folds_both_placeholder_styles(gate: Any) -> None:
    assert gate._norm_path("/api/essays/${id}/versions/${vid}") == "/api/essays/{}/versions/{}"
    assert gate._norm_path("/api/essays/{essay_id}") == "/api/essays/{}"


# ══ 2. 合成夹具：每条规则都必须能变红 ═══════════════════════════════════════


def test_clean_copy_has_no_violations(gate: Any, js_dir: Path) -> None:
    """阴性对照：未注入缺陷的真实副本必须零违规（否则后面的红灯无法归因）。"""
    assert rules_of(gate, js_dir) == []


def test_rule1_l1_network_ban_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n  fetch('/x');")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("L1 纯格式化层禁network") for r in rules), rules


def test_rule1_l1_dom_ban_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n  document.getElementById('x');")
    assert any(r.startswith("L1 纯格式化层禁dom") for r in rules_of(gate, js_dir))


def test_rule1_l1_toast_and_timer_bans_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n  notify('x');\n  setTimeout(() => {}, 0);")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("L1 纯格式化层禁toast") for r in rules), rules
    assert any(r.startswith("L1 纯格式化层禁timer") for r in rules), rules


def test_rule1_l1_mutable_state_ban_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-format.js", "export const WRITER_TABS",
           "let scratch = 1;\nexport const WRITER_TABS")
    assert any(r.startswith("L1 纯格式化层禁mutable-state") for r in rules_of(gate, js_dir))


def test_rule2_l2_dom_ban_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-api.js", "export async function fetchWriterEssays() {",
           "export async function fetchWriterEssays() {\n  document.getElementById('x');")
    assert any(r.startswith("L2 持久化访问层禁dom") for r in rules_of(gate, js_dir))


def test_rule2_l2_network_is_allowed(gate: Any, js_dir: Path) -> None:
    """阴性对照：网络是 L2 的本职，注入 `fetch(` 不得变红（防闸过度收紧）。"""
    inject(js_dir / "wr-api.js", "export async function fetchWriterEssays() {",
           "export async function fetchWriterEssays() {\n  fetch('/x');")
    assert not any("禁network" in r for r in rules_of(gate, js_dir))


def test_rule3_reverse_dependency_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-api.js", "import { api } from './core.js';",
           "import { api } from './core.js';\nimport { renderEditor } from './writer.js';")
    rules = rules_of(gate, js_dir)
    assert "reverse-dependency" in rules, rules


def test_rule3b_import_allowlist_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-format.js", "import { esc } from './core.js';",
           "import { esc } from './core.js';\nimport { something } from './cards.js';")
    assert any("越界import" in r for r in rules_of(gate, js_dir))


def test_rule4_duplicate_declaration_red(gate: Any, js_dir: Path) -> None:
    """导入名同时被本地声明 ⇒ ES 链接期 SyntaxError（整张模块图一起挂）。"""
    inject(js_dir / "writer.js", "export { getErrorTypeLabel };",
           "export { getErrorTypeLabel };\nconst getErrorTypeLabel = (t) => t;")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("duplicate-declaration(getErrorTypeLabel)") for r in rules), rules


def test_rule6_false_decoupling_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "writer.js", "export { getErrorTypeLabel };",
           "export { getErrorTypeLabel };\nfunction renderWordDiff(a, b) { return { oldHtml: a, newHtml: b }; }")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("false-decoupling(renderWordDiff") for r in rules), rules


def test_rule5_method_mismatch_red(gate: Any, js_dir: Path) -> None:
    """路径注册了但方法不对（DELETE->POST）：现存路由闸只查路径，抓不到这个。"""
    inject(js_dir / "wr-api.js",
           "return api(`/api/essays/${essayId}/versions/${versionId}`, { method: 'DELETE' });",
           "return api(`/api/essays/${essayId}/versions/${versionId}`, { method: 'POST' });")
    pairs = {("/api/essays/{}/versions/{}", "GET"), ("/api/essays/{}/versions/{}", "DELETE")}
    rules = [v.rule for v in gate.collect_violations(js_dir, pairs)]
    assert any(r.startswith("method-mismatch(POST") for r in rules), rules


def test_rule5_unregistered_path_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / "wr-api.js", "return api('/api/essays');",
           "return api('/api/nope');")
    rules = [v.rule for v in gate.collect_violations(js_dir, {("/api/essays", "GET")})]
    assert "route-path-unregistered" in rules, rules


def test_missing_declared_module_red(gate: Any, tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    rules = rules_of(gate, d)
    assert rules.count("missing-layer-module") == 2, rules


def test_comment_mention_does_not_trip_the_gate(gate: Any, js_dir: Path) -> None:
    """**最关键的反假红用例**：L1/L2 的模块头注释逐字写着被禁词（那是在声明契约）。
    不剥注释 ⇒ 闸对自己的文档开火。"""
    head = "\n".join((js_dir / "wr-format.js").read_text(encoding="utf-8").splitlines()[:20])
    assert "MUST NOT 触碰 DOM" in head, "模块头注释应当声明契约（本用例的前提）"
    assert "getElementById" in head, "模块头注释应当逐字提到被禁词（本用例的前提）"
    assert "fetch" in head, "模块头注释应当逐字提到被禁词（本用例的前提）"
    assert rules_of(gate, js_dir) == []


# ══ 3. 真树集成 + 端到端退出码 ═══════════════════════════════════════════════


def test_gate_script_exits_zero_on_real_tree() -> None:
    """生产树必须 exit 0，且输出 PASS 字样（端到端，含规则⑤真实路由表）。"""
    res = subprocess.run(
        [sys.executable, str(GATE)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"闸报红:\n{res.stdout}\n{res.stderr}"
    assert "PASS" in res.stdout


def test_gate_cli_reports_file_line_rule_and_raw_line(js_dir: Path) -> None:
    """行级归因：违规必须报 `文件:行号:规则:原始行`，不许只报「共 N 处」。"""
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n  document.getElementById('x');")
    res = run_gate(js_dir)
    assert res.returncode == 1
    line = next(x for x in res.stderr.splitlines() if "wr-format.js" in x)
    assert line.strip().startswith("- static/js/wr-format.js:")
    assert ":L1 纯格式化层禁dom:" in line
    assert "document.getElementById" in line