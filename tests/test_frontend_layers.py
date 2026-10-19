# -*- coding: utf-8 -*-
"""`tools/check_frontend_layers.py` 的验收测试（计划 `2026-10-19-writer-js-modularization.md` Task 4）。

三层证据，缺一不可：

  1. **纯函数单测**（`strip_comments` 等）—— 与仓库内容无关的判据本身。
  2. **合成夹具**（`tmp_path` 造模块）—— 证明每条规则**能变红**，而不是「跑当前树恰好绿」。
     这是「闸是规范，不是描述」的落地方式。
  3. **真树派生变异**（复制生产 `wr-format.js`/`wr-api.js`/`writer.js`/`rd-syntax.js` 到 tmp 后注入缺陷）
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

_LAYER_MODULES = (
    "wr-format.js",
    "wr-api.js",
    "writer.js",
    "rd-syntax.js",
    "wb-queue.js",
    "wb-scope.js",
    "rd-api.js",
)


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
    """把生产中已被纳管的模块**复制**到 tmp（真内容，不就地改）。

    `rd-syntax.js` 是「先注册、后落盘」（计划 Task 1/Task 2）⇒ 只复制**存在**的模块，
    缺文件时跳过；「声明的模块不存在」另由 `missing-layer-module` 用例专门覆盖。
    """
    d = tmp_path / "js"
    d.mkdir()
    for name in _LAYER_MODULES:
        src = JS_DIR / name
        if src.exists():
            shutil.copyfile(src, d / name)
    return d


def _write_module(path: Path, text: str) -> None:
    """写模块夹具：统一 CRLF（仓库契约），并避免 `newline=''` 把整文件转成 LF。"""
    cr, lf = chr(13), chr(10)
    path.write_text(text.replace(cr + lf, lf).replace(lf, cr + lf), encoding="utf-8", newline="")


@pytest.fixture()
def rule5_dir(tmp_path: Path) -> Path:
    """规则⑤ 专用最小树：`wr-api.js` 里**只有一个**受测调用。

    为什么不用真文件：真文件有 14 个调用，配一个最小路由集会让**别的**调用如实报
    `route-path-unregistered`，把断言面搅浑（曾据此写出过假失败的断言）。要测的是
    「这一个调用怎么判」，就该只放这一个。
    """
    d = tmp_path / "js"
    d.mkdir()
    _write_module(d / "wr-format.js", "import { esc } from './core.js';\nexport const WRITER_TABS = ['a'];\n")
    # 同理：`LAYER_SPEC` 里声明的模块都必须在树里存在，否则每条断言都会被
    # `missing-layer-module` 搅浑（本树只测规则⑤）。
    _write_module(d / "rd-syntax.js", "import { esc } from './core.js';\nexport const CEFR_LEVELS = ['A1'];\n")
    _write_module(d / "wb-queue.js", "export {};\n")
    _write_module(d / "wb-scope.js", "export {};\n")
    _write_module(d / "writer.js", "export {};\n")
    _write_module(
        d / "wr-api.js",
        "import { api } from './core.js';\n"
        "export async function probe() {\n"
        "  return api('/api/essays');\n"
        "}\n",
    )
    _write_module(d / "rd-api.js", "import { api } from './core.js';\nexport async function dummy() {}\n")
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
    assert rules.count("missing-layer-module") == len(gate.LAYER_SPEC), rules


def test_comment_mention_does_not_trip_the_gate(gate: Any, js_dir: Path) -> None:
    """**最关键的反假红用例**：L1/L2 的模块头注释逐字写着被禁词（那是在声明契约）。
    不剥注释 ⇒ 闸对自己的文档开火。"""
    head = "\n".join((js_dir / "wr-format.js").read_text(encoding="utf-8").splitlines()[:20])
    assert "MUST NOT 触碰 DOM" in head, "模块头注释应当声明契约（本用例的前提）"
    assert "getElementById" in head, "模块头注释应当逐字提到被禁词（本用例的前提）"
    assert "fetch" in head, "模块头注释应当逐字提到被禁词（本用例的前提）"
    assert rules_of(gate, js_dir) == []


@pytest.mark.parametrize(
    "import_line",
    [
        "import { renderEditor } from './writer.js';",
        "import writer from './writer.js';",
        "import * as w from './writer.js';",
        "import './writer.js';",
    ],
    ids=["named", "default", "namespace", "side-effect"],
)
def test_rule3_catches_every_import_form(gate: Any, js_dir: Path, import_line: str) -> None:
    """单向层序 MUST 对**所有** import 形态成立。

    副作用型 `import './writer.js'` 没有任何绑定名 —— 早先的解析只认带 `from` 的三种形态，
    等于给「低层偷偷 import 视图层」留了后门（本用例即该洞的回归钉子）。
    """
    inject(js_dir / "wr-api.js", "import { api } from './core.js';",
           "import { api } from './core.js';\n" + import_line)
    rules = rules_of(gate, js_dir)
    assert "reverse-dependency" in rules, (import_line, rules)


@pytest.mark.parametrize(
    "import_line",
    [
        "import { something } from './cards.js';",
        "import cards from './cards.js';",
        "import * as cards from './cards.js';",
        "import './cards.js';",
    ],
    ids=["named", "default", "namespace", "side-effect"],
)
def test_rule3b_allowlist_catches_every_import_form(gate: Any, js_dir: Path, import_line: str) -> None:
    inject(js_dir / "wr-format.js", "import { esc } from './core.js';",
           "import { esc } from './core.js';\n" + import_line)
    assert any("越界import" in r for r in rules_of(gate, js_dir)), import_line


# ══ 2b. 复核驱动的绕过通道回归钉子（F1~F11）══════════════════════════════════
# 下列每条都对应一轮独立对抗式复核里**当时真的绕过了**闸的输入；不是假想用例。
# 规则⑤ 的用例一律用 `rule5_dir`（最小受测树）—— 拿真文件配最小路由集会让**别的**
# 调用如实报红，把断言面搅浑。


def test_rule5_method_quote_forms_all_red(gate: Any, rule5_dir: Path) -> None:
    """F1：`method:` 写双引号/反引号时旧版静默按 GET 处理 ⇒ 假绿。三种引号都必须判红。"""
    pairs = {("/api/essays/{}/versions/{}", "GET"), ("/api/essays/{}/versions/{}", "DELETE")}
    for quote in ('"', "'", "`"):
        _write_module(
            rule5_dir / "wr-api.js",
            "import { api } from './core.js';\n"
            "export async function probe() {\n"
            "  return api(`/api/essays/${essayId}/versions/${versionId}`, "
            "{ method: " + quote + "POST" + quote + " });\n"
            "}\n",
        )
        rules = [v.rule for v in gate.collect_violations(rule5_dir, pairs)]
        assert any(r.startswith("method-mismatch(POST") for r in rules), (quote, rules)


@pytest.mark.parametrize(
    "opts",
    ["{ method: MUT }", "{ method }"],
    ids=["variable", "shorthand"],
)
def test_rule5_unparsable_method_fails_closed(gate: Any, rule5_dir: Path, opts: str) -> None:
    """F1：取不到字面量方法值 MUST 判失败（`unverifiable-method`），不许猜一个 GET 蒙过去。

    简写 `{ method }` 同样是「写了 method 却没有值」，MUST 一并 fail-closed。
    """
    inject(rule5_dir / "wr-api.js", "  return api('/api/essays');",
           "  return api('/api/essays', " + opts + ");")
    rules = [v.rule for v in gate.collect_violations(rule5_dir, {("/api/essays", "GET")})]
    assert "unverifiable-method" in rules, rules


def test_rule5_no_line_window_bleed(gate: Any, rule5_dir: Path) -> None:
    """F2：旧版按「首行 + 后 4 行」取窗口 ⇒ 会把邻近调用的方法串到本调用上（假红）。

    这里让一个 GET-only 调用紧邻一个无关的 POST 调用：前者 MUST NOT 被判红。
    """
    _write_module(
        rule5_dir / "wr-api.js",
        "import { api } from './core.js';\n"
        "export async function probe() {\n"
        "  const other = api('/api/essays', { method: 'POST' });\n"
        "  const v = await api('/api/essays/1/versions/2');\n"
        "  return other && v;\n"
        "}\n",
    )
    pairs = {("/api/essays", "GET"), ("/api/essays", "POST"), ("/api/essays/{}/versions/{}", "GET")}
    rules = [v.rule for v in gate.collect_violations(rule5_dir, pairs)]
    assert not any(r.startswith("method-mismatch") for r in rules), rules


@pytest.mark.parametrize(
    "snippet,rule_part",
    [
        ("  const _net = fetch;", "禁network"),
        ("  notify?.('x');", "禁toast"),
        ("  g['setTimeout'](fn, 0);", "禁timer"),
        ("  const g2 = globalThis;", None),  # 阴性对照：globalThis 自身不在块表里
    ],
    ids=["alias", "optional-chain", "subscript-string", "negative-control"],
)
def test_rule1_alias_optional_chain_and_subscript(
    gate: Any, js_dir: Path, snippet: str, rule_part: Any
) -> None:
    """F3：旧版禁令要求「函数调用形态」⇒ 别名 / 可选链 / 下标取用全部逃逸。"""
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n" + snippet)
    rules = rules_of(gate, js_dir)
    if rule_part is None:
        assert not any("禁" in r for r in rules), (snippet, rules)
    else:
        assert any(rule_part in r for r in rules), (snippet, rules)


@pytest.mark.parametrize(
    "snippet",
    [
        # 以下都是**被扫描的 JS 代码字符串**（夹具数据），不是 Python 的 eval 调用 ——
        # 它们只会被喂给闸的词法分析器，绝不执行。
        "  el.appendChild(document.body);",
        "  new WebSocket('ws://x');",
        "  eval('1+1');",
        "  top.location.href = '/';",
        "  parent.postMessage('x', '*');",
    ],
    ids=["appendChild", "WebSocket", "eval", "location", "postMessage"],
)
def test_rule1_dom_and_dynamic_sinks_red(gate: Any, js_dir: Path, snippet: str) -> None:
    """F4：块表补的 DOM 汇点 / 动态求值 / 跨窗通信 —— 每条都必须能红。"""
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n" + snippet)
    assert any("禁" in r for r in rules_of(gate, js_dir)), snippet


@pytest.mark.parametrize(
    "import_line",
    [
        "import{b2}from'./writer.js';",
        "export {renderEditor} from './writer.js';",
        "import('./writer.js');",
        "import './writer.js'; import './writer.js';",
    ],
    ids=["no-whitespace", "export-from", "dynamic-import", "two-on-one-line"],
)
def test_rule3_import_forms_that_old_regex_missed(gate: Any, js_dir: Path, import_line: str) -> None:
    """F5：旧版单行 `^` 锚正则漏掉的无空白 / export-from / 动态 import / 同行两个。"""
    inject(js_dir / "wr-api.js", "import { api } from './core.js';",
           "import { api } from './core.js';\n" + import_line)
    assert "reverse-dependency" in rules_of(gate, js_dir), import_line


def test_rule3b_vendor_path_is_not_a_disguise(gate: Any, js_dir: Path) -> None:
    """F5：旧版只比 basename ⇒ `./vendor/core.js` 冒充 `./core.js`。现必须判红。"""
    inject(js_dir / "wr-format.js", "import { esc } from './core.js';",
           "import { esc } from './vendor/core.js';")
    assert any("越界import(vendor/core.js)" in r for r in rules_of(gate, js_dir))


@pytest.mark.parametrize(
    "import_line,decl_line",
    [
        ("import * as A1Writer from './core.js';", "const A1Writer = 1;"),
        ("import writerMod from './core.js';", "function writerMod() {}"),
    ],
    ids=["namespace", "default"],
)
def test_rule4_namespace_and_default_bindings_are_tracked(
    gate: Any, js_dir: Path, import_line: str, decl_line: str
) -> None:
    """F6：旧版只收具名 `{…}` 绑定 ⇒ 命名空间/默认导入重名逃逸（正是会挂整图的那类）。"""
    inject(js_dir / "wr-format.js", "import { esc } from './core.js';",
           "import { esc } from './core.js';\n" + import_line)
    inject(js_dir / "wr-format.js", "export const WRITER_TABS",
           decl_line + "\nexport const WRITER_TABS")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("duplicate-declaration(") for r in rules), rules


def test_rule4_comma_declarator_list_is_tracked(gate: Any, js_dir: Path) -> None:
    """F6：`const other = 1, esc = 2;` 的第二个名字旧版收不到（esc 是导入名 ⇒ 链接期报错）。"""
    inject(js_dir / "wr-format.js", "export const WRITER_TABS",
           "const other = 1, esc = 2;\nexport const WRITER_TABS")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("duplicate-declaration(esc)") for r in rules), rules


def test_rule6_generator_redefinition_red(gate: Any, js_dir: Path) -> None:
    """F6：`export function* name(){}` 旧版漏判。"""
    inject(js_dir / "writer.js", "export { getErrorTypeLabel };",
           "export { getErrorTypeLabel };\nexport function* renderWordDiff(a, b) { yield a; }")
    rules = rules_of(gate, js_dir)
    assert any(r.startswith("false-decoupling(renderWordDiff") for r in rules), rules


def test_rule5_fetch_calls_are_checked(gate: Any, rule5_dir: Path) -> None:
    """F8：`wr-api.js` 的另一条真实调用面 `fetch(` 旧版完全没查。"""
    _write_module(
        rule5_dir / "wr-api.js",
        "export async function probe() {\n"
        "  return fetch('/api/nope', { method: 'DELETE' });\n"
        "}\n",
    )
    rules = [v.rule for v in gate.collect_violations(rule5_dir, {("/api/essays", "GET")})]
    assert "route-path-unregistered" in rules, rules


@pytest.mark.parametrize(
    "inject_line,expected_rule",
    [
        ("  return api(endpoint);", "unverifiable-path"),
        ("  return api('/api/essays/' + id);", None),
        ("  return api('/api/essays', { method: 'delete' });", None),
    ],
    ids=["variable-path", "concatenated-literal", "lowercase-method"],
)
def test_rule5_path_and_method_normalization(
    gate: Any, rule5_dir: Path, inject_line: str, expected_rule: Any
) -> None:
    """F9：路径非字面量 ⇒ fail-closed；`+` 拼接按既有闸口径折算 `{}`；方法统一 upper。"""
    inject(rule5_dir / "wr-api.js", "  return api('/api/essays');", inject_line)
    pairs = {("/api/essays", "GET"), ("/api/essays", "DELETE"), ("/api/essays/{}", "GET")}
    rules = [v.rule for v in gate.collect_violations(rule5_dir, pairs)]
    if expected_rule is None:
        assert not rules, rules
    else:
        assert expected_rule in rules, rules


def test_rule1_mid_line_top_level_let_red(gate: Any, js_dir: Path) -> None:
    """F10：旧版 `mutable-state` 只在列 0 生效 ⇒ `const A = 1; let x = 2;` 逃逸。"""
    inject(js_dir / "wr-format.js", "export const WRITER_TABS",
           "const A = 1; let scratch = 2;\nexport const WRITER_TABS")
    assert any("禁mutable-state" in r for r in rules_of(gate, js_dir))


def test_regex_literal_does_not_mask_real_code(gate: Any, js_dir: Path) -> None:
    """F7：旧版用正则剥注释 ⇒ 正则字面量里的 `/*` 会被当成块注释起始，把真实代码吃掉。"""
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n"
           "  const STAR = /a\\/*b/;\n"
           "  document.getElementById('smuggled');")
    assert any("禁dom" in r for r in rules_of(gate, js_dir))


def test_real_file_comment_and_regex_handling(gate: Any) -> None:
    """F7 的回归钉子：真文件里那个含引号的正则字面量 MUST NOT 让真实注释逃过剥离。

    双侧断言：① 块注释正文在剥注释结果里消失；② 正则字面量原文被原样保留。
    """
    src = (JS_DIR / "wr-format.js").read_text(encoding="utf-8")
    stripped = gate.strip_comments(src)
    assert stripped.count("\n") == src.count("\n"), "行数必须不变（行号才可信）"
    assert "MUST NOT 触碰 DOM" in src and "MUST NOT 触碰 DOM" not in stripped
    assert "分层契约" in src and "分层契约" not in stripped
    regex_line = next(x for x in src.splitlines() if "oldSent.split(" in x)
    assert regex_line in stripped, "正则字面量所在行被误剥"


def test_violations_are_deduped_per_file_line_rule(gate: Any, js_dir: Path) -> None:
    """F11：同一 (文件,行,规则) 只报一次，不因多模式命中而重复刷屏。"""
    inject(js_dir / "wr-format.js", "export function getErrorTypeLabel(type) {",
           "export function getErrorTypeLabel(type) {\n  document.getElementById('x');")
    rules = rules_of(gate, js_dir)
    assert len(rules) == len(set(rules)), rules

# ══ 2c. rd-syntax.js：Task 1 先注册、Task 2 才落盘的 L1 模块 ══════════════════
# 计划 `2026-10-19-reader-js-layer-split.md` Task 1（Gate-Before-Code）：闸先声明目标形态，
# 模块后建。下列注入用例在 `rd-syntax.js` 落盘前必然失败 —— 夹具复制的真实文件还不存在
# （`_inject_into_rd_syntax` 找不到锚点），那正是「声明先于代码」要的红灯；Task 2 产出该
# 文件后自动转绿，无需改动本文件。

_RD_SYNTAX = "rd-syntax.js"
# 锚点取自计划 Task 2 的 Produces（与 `reader.js:89` 现状逐字相同，落盘后必然命中一次）
_RD_SYNTAX_ANCHOR = "export function renderMiniBar(stats) {"


def _rd_syntax_rules(gate: Any, js_dir_arg: Path) -> list[str]:
    """只取归到 `static/js/rd-syntax.js` 名下的规则 —— 光比规则名无法排除「红的是别人」。"""
    return [
        v.rule
        for v in gate.collect_violations(js_dir_arg, None)
        if v.rel_path == f"static/js/{_RD_SYNTAX}"
    ]


def _inject_into_rd_syntax(js_dir_arg: Path, snippet: str) -> None:
    """把片段插到**顶层**锚点之前（顶层 `let` 才落在花括号净深度 0）。"""
    inject(js_dir_arg / _RD_SYNTAX, _RD_SYNTAX_ANCHOR, snippet + "\n" + _RD_SYNTAX_ANCHOR)


def test_rd_syntax_declaration_equals_wr_format(gate: Any) -> None:
    """No-Narrowing：新 L1 模块与 `wr-format.js` 是**同一个** L1 定义（逐字相同）。

    该断言不依赖模块是否落盘，故 Task 1 当场即绿 —— 它是「MUST NOT 为了绿灯放宽任何
    一条规则」的机械钉子。
    """
    new, baseline = gate.LAYER_SPEC[_RD_SYNTAX], gate.LAYER_SPEC["wr-format.js"]
    assert new.layer == baseline.layer
    assert new.ban_rules == baseline.ban_rules
    assert new.allowed_imports == baseline.allowed_imports == ("./core.js",)
    assert _RD_SYNTAX in gate.MUTABLE_STATE_MODULES


@pytest.mark.parametrize(
    "snippet,rule_part",
    [
        ("document.getElementById('x');", "禁dom"),
        ("fetch('/x');", "禁network"),
        ("setTimeout(() => {}, 0);", "禁timer"),
    ],
    ids=["dom", "network", "timer"],
)
def test_rd_syntax_l1_bans_red(gate: Any, js_dir: Path, snippet: str, rule_part: str) -> None:
    """注入 DOM 标识符 / 网络调用 / 计时器 ⇒ 归到 `rd-syntax.js` 名下的 L1 禁令必须变红。"""
    _inject_into_rd_syntax(js_dir, snippet)
    hits = _rd_syntax_rules(gate, js_dir)
    assert any(rule_part in r for r in hits), (snippet, hits)


def test_rd_syntax_l1_top_level_let_red(gate: Any, js_dir: Path) -> None:
    """L1 MUST NOT 有顶层可变状态：模块级 `let` 与 `wr-format.js` 同口径判红。"""
    _inject_into_rd_syntax(js_dir, "let scratch = 1;")
    hits = _rd_syntax_rules(gate, js_dir)
    assert any("禁mutable-state" in r for r in hits), hits


# ══ 2d. rd-api.js：Task 1 先注册、Task 2 才落盘的 L2 持久化层 ══════════════════
# 计划 `2026-10-19-reader-api-layer-split.md` Task 1（Gate-Before-Code）：闸先声明目标形态，
# 模块后建。下列注入用例在 `rd-api.js` 落盘前必然失败 —— 夹具复制的真实文件还不存在
# （`_inject_into_rd_api` 找不到锚点），那正是「声明先于代码」要的红灯；Task 2 产出该
# 文件后自动转绿，无需改动本文件。

_RD_API = "rd-api.js"
# 锚点取自计划 Task 2 的 Produces（落盘后首个具名远程导出）
_RD_API_ANCHOR = "export async function deleteArticleRemote(id) {"


def _rd_api_rules(gate: Any, js_dir_arg: Path) -> list[str]:
    """只取归到 `static/js/rd-api.js` 名下的规则。"""
    return [
        v.rule
        for v in gate.collect_violations(js_dir_arg, None)
        if v.rel_path == f"static/js/{_RD_API}"
    ]


def _inject_into_rd_api(js_dir_arg: Path, snippet: str) -> None:
    """把片段插到锚点之前。"""
    inject(js_dir_arg / _RD_API, _RD_API_ANCHOR, snippet + "\n" + _RD_API_ANCHOR)


def test_rd_api_declaration_equals_wr_api(gate: Any) -> None:
    """No-Narrowing: 新 L2 模块与 `wr-api.js` 是同一个 L2 定义（逐字相同）。

    该断言不依赖模块是否落盘，故 Task 1 当场即绿。
    """
    new, baseline = gate.LAYER_SPEC[_RD_API], gate.LAYER_SPEC["wr-api.js"]
    assert new.layer == baseline.layer
    assert new.ban_rules == baseline.ban_rules
    assert new.allowed_imports == baseline.allowed_imports == ("./core.js",)


@pytest.mark.parametrize(
    "snippet,rule_part",
    [
        ("document.getElementById('x');", "禁dom"),
        ("notify('x');", "禁toast"),
        ("setTimeout(() => {}, 0);", "禁timer"),
    ],
    ids=["dom", "toast", "timer"],
)
def test_rd_api_l2_bans_red(gate: Any, js_dir: Path, snippet: str, rule_part: str) -> None:
    """L2 禁令：DOM / 提示 / 计时器必须判红。"""
    _inject_into_rd_api(js_dir, snippet)
    hits = _rd_api_rules(gate, js_dir)
    assert any(rule_part in r for r in hits), (snippet, hits)


def test_rd_api_l2_network_is_allowed(gate: Any, js_dir: Path) -> None:
    """阴性对照：网络是 L2 的本职，注入 `fetch(` 不得变红。"""
    _inject_into_rd_api(js_dir, "fetch('/api/articles');")
    hits = _rd_api_rules(gate, js_dir)
    assert not any("禁network" in r for r in hits), hits


def test_rd_api_reverse_dependency_red(gate: Any, js_dir: Path) -> None:
    """反向依赖：L2 不得 import 视图层。"""
    _inject_into_rd_api(js_dir, "import { renderEditor } from './writer.js';")
    hits = _rd_api_rules(gate, js_dir)
    assert "reverse-dependency" in hits, hits


def test_rd_api_import_allowlist_red(gate: Any, js_dir: Path) -> None:
    """import 白名单：L2 仅允许 ./core.js，引入其他模块必须判红。"""
    _inject_into_rd_api(js_dir, "import { something } from './cards.js';")
    hits = _rd_api_rules(gate, js_dir)
    assert any("越界import" in r for r in hits), hits


# ══ 2e. wb-queue.js 与 wb-scope.js：已存在的 L1 纯层模块 ═══════════════════════

_WB_QUEUE = "wb-queue.js"
_WB_SCOPE = "wb-scope.js"
_WB_QUEUE_ANCHOR = "const manualExtraIds = new Set();"
_WB_SCOPE_ANCHOR = "const CEFR_BY_PREFIX = ["


def _wb_module_rules(gate: Any, js_dir_arg: Path, mod_name: str) -> list[str]:
    return [
        v.rule
        for v in gate.collect_violations(js_dir_arg, None)
        if v.rel_path == f"static/js/{mod_name}"
    ]


def test_wb_queue_and_scope_declarations(gate: Any) -> None:
    """wb-queue.js 与 wb-scope.js 的分层定义：L1 纯层，零外部 import，禁止顶层可变状态。"""
    for mod in (_WB_QUEUE, _WB_SCOPE):
        spec = gate.LAYER_SPEC[mod]
        assert spec.layer == "L1 纯格式化层"
        assert spec.ban_rules == ("dom", "network", "toast", "timer", "dynamic-eval")
        assert spec.allowed_imports == ()
        assert mod in gate.MUTABLE_STATE_MODULES


@pytest.mark.parametrize(
    "snippet,rule_part",
    [
        ("document.getElementById('x');", "禁dom"),
        ("fetch('/x');", "禁network"),
        ("notify('x');", "禁toast"),
        ("setTimeout(() => {}, 0);", "禁timer"),
    ],
    ids=["dom", "network", "toast", "timer"],
)
def test_wb_queue_l1_bans_red(gate: Any, js_dir: Path, snippet: str, rule_part: str) -> None:
    inject(js_dir / _WB_QUEUE, _WB_QUEUE_ANCHOR, snippet + "\n" + _WB_QUEUE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_QUEUE)
    assert any(rule_part in r for r in hits), (snippet, hits)


def test_wb_queue_top_level_let_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / _WB_QUEUE, _WB_QUEUE_ANCHOR, "let scratch = 1;\n" + _WB_QUEUE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_QUEUE)
    assert any("禁mutable-state" in r for r in hits), hits


def test_wb_queue_disallows_all_imports_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / _WB_QUEUE, _WB_QUEUE_ANCHOR, "import { esc } from './core.js';\n" + _WB_QUEUE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_QUEUE)
    assert any("越界import" in r for r in hits), hits


@pytest.mark.parametrize(
    "snippet,rule_part",
    [
        ("document.getElementById('x');", "禁dom"),
        ("fetch('/x');", "禁network"),
        ("notify('x');", "禁toast"),
        ("setTimeout(() => {}, 0);", "禁timer"),
    ],
    ids=["dom", "network", "toast", "timer"],
)
def test_wb_scope_l1_bans_red(gate: Any, js_dir: Path, snippet: str, rule_part: str) -> None:
    inject(js_dir / _WB_SCOPE, _WB_SCOPE_ANCHOR, snippet + "\n" + _WB_SCOPE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_SCOPE)
    assert any(rule_part in r for r in hits), (snippet, hits)


def test_wb_scope_top_level_let_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / _WB_SCOPE, _WB_SCOPE_ANCHOR, "let scratch = 1;\n" + _WB_SCOPE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_SCOPE)
    assert any("禁mutable-state" in r for r in hits), hits


def test_wb_scope_disallows_all_imports_red(gate: Any, js_dir: Path) -> None:
    inject(js_dir / _WB_SCOPE, _WB_SCOPE_ANCHOR, "import { esc } from './core.js';\n" + _WB_SCOPE_ANCHOR)
    hits = _wb_module_rules(gate, js_dir, _WB_SCOPE)
    assert any("越界import" in r for r in hits), hits


# ══ 2f. 规则⑤ 泛化到所有 L2 模块 ═══════════════════════════════════════════════


def test_rule5_generalized_checks_rd_api_unregistered_path(gate: Any, rule5_dir: Path) -> None:
    """规则⑤ 泛化：rd-api.js 中调用未注册路径被识别并归因到 rd-api.js。"""
    _write_module(
        rule5_dir / "rd-api.js",
        "import { api } from './core.js';\n"
        "export async function probe() {\n"
        "  return api('/api/articles/unregistered', { method: 'DELETE' });\n"
        "}\n",
    )
    violations = [
        v for v in gate.collect_violations(rule5_dir, {("/api/essays", "GET")})
        if v.rel_path == "static/js/rd-api.js"
    ]
    assert len(violations) == 1
    assert violations[0].rule == "route-path-unregistered"


def test_rule5_generalized_checks_rd_api_method_mismatch(gate: Any, rule5_dir: Path) -> None:
    """规则⑤ 泛化：rd-api.js 中方法不匹配被识别并归因到 rd-api.js。"""
    _write_module(
        rule5_dir / "rd-api.js",
        "import { api } from './core.js';\n"
        "export async function probe() {\n"
        "  return api(`/api/articles/${id}`, { method: 'POST' });\n"
        "}\n",
    )
    pairs = {("/api/essays", "GET"), ("/api/articles/{}", "DELETE")}
    violations = [
        v for v in gate.collect_violations(rule5_dir, pairs)
        if v.rel_path == "static/js/rd-api.js"
    ]
    assert any(v.rule.startswith("method-mismatch(POST!=DELETE)") for v in violations), violations


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
