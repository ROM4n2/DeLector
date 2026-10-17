# -*- coding: utf-8 -*-
"""``tools/check_mock_drift.py`` 的单元测试（C9 Task 3：mock 漂移机械闸）。

覆盖任务书 Step 4 的四件：
1. 判据的**阳性**样本：patch 目标符号在目标生产模块内已无引用/调用点 ⇒ 候选
   （``file:line | symbol | 目标模块``），含本次事故的真形状（``<模块>.httpx`` + ``"stream"``）；
2. **阴性**样本：符号仍被调用/引用、或属**自供出口**（顶层 def/class/赋值 + ``__all__``
   声明；包 ``__init__`` + 直属子模块 + ``__all__``）⇒ MUST NOT 命中（另覆盖：非生产模块
   目标、无法静态解析的目标）；
3. 空理由抑制 = 违规（``mock-drift-ok:`` 后不写 REASON 不算豁免；字符串里的标记不算注释）；
4. 退出码语义：0=通过 / 1=有未豁免候选 / 2=环境不可用（run_scan 与 CLI 两层）。
5. **判据细化（2026-10）**：``__all__`` **自供**出口计为引用；plain import 绑定 / re-export
   一律不计 —— 真遗留 ``tests/test_server.py:2501``（patch ``server.nlp``）的形状 MUST
   照常命中（见口径测试）。
另锁两条「极限」负样本：符号名非字符串字面量、字符串寻址形态 —— 都已登记为静态不可达
（见闸模块头「极限」#1/#3），MUST NOT 在闸里变成命中（那是假精度）。

纪律：全部用 ``tmp_path`` 造合成树，**绝不**让被测模块扫描真仓库
（本文件唯一读真仓库的地方是末尾的 CI 接线守卫：读 ``.github/workflows/ci.yml``）。
"""

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "check_mock_drift.py"


def _load_module() -> Any:
    """按文件路径加载判定器模块（用真对象，避免 import 期污染 sys.modules）。"""
    if not _SCRIPT.exists():
        pytest.fail(f"判定器脚本不存在：{_SCRIPT}（mock 漂移机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_mock_drift", _SCRIPT)
    assert spec is not None and spec.loader is not None, f"无法加载判定器脚本：{_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tree(
    tmp_path: Path,
    files: dict[str, str],
    *,
    dirs: tuple[str, ...] = ("tests",),
) -> Path:
    """造一个最小扫描树：``root/<dirs…>`` + 指定相对路径的文件（LF 写入）。"""
    root = tmp_path / "repo"
    for sub in dirs:
        (root / sub).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return root


# ── 样本：本次事故的真形状（tests patch <encounter 模块>.httpx 的 "stream"）────────────
#
# 生产模块（合成）：只用 httpx.get —— 即本次 C8 事故「符号 get→stream 换向」的另一侧。
# 测试补丁钉在 "stream" 上 ⇒ stream 在该模块内已无引用/调用点 ⇒ 必须命中。

_MODULE_USES_GET = (
    "import httpx\n"  # 1
    "\n"  # 2
    "\n"  # 3
    "def _shelf_get(url: str) -> object:\n"  # 4
    "    return httpx.get(url)\n"  # 5
)

_MODULE_USES_STREAM = (
    "import httpx\n"  # 1
    "\n"  # 2
    "\n"  # 3
    "def _shelf_get(url: str) -> object:\n"  # 4
    '    with httpx.stream("GET", url) as resp:\n'  # 5
    "        return resp\n"  # 6
)

# 测试文件：第 6 行是 monkeypatch.setattr 调用行（多行调用形态的行号口径也由此钉住）。
_TEST_PATCHES_ATTRIBUTE = (
    "from delector.routes import encounter as encounter_mod\n"  # 1
    "\n"  # 2
    "\n"  # 3
    "def test_pull(monkeypatch):\n"  # 4
    "    fake = object()\n"  # 5
    '    monkeypatch.setattr(encounter_mod.httpx, "stream", fake)\n'  # 6  ← 调用行
)

_INCIDENT_TREE = {
    "tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE,
    "delector/routes/encounter.py": _MODULE_USES_GET,
}


def _scan_sites(module: Any, root: Path) -> list[tuple[int, str, str, str]]:
    """走引用判定层（``collect_sites``）取候选：行号 / 符号 / 目标模块 / obj 四元组。"""
    return [(site.line, site.symbol, site.module, site.obj) for site in module.collect_sites(root).sites]


# ── 判据：阳性 / 阴性 ─────────────────────────────────────────────────────────────


def test_criterion_flags_patch_to_symbol_without_call_site(tmp_path: Path) -> None:
    """阳性（事故真形状）：模块只用 `httpx.get`，测试补丁钉 `"stream"` ⇒ 命中。"""
    module = _load_module()
    root = _make_tree(tmp_path, _INCIDENT_TREE)
    assert _scan_sites(module, root) == [
        (6, "stream", "delector.routes.encounter", "encounter_mod.httpx")
    ]


def test_criterion_passes_when_symbol_is_still_called_as_attribute(tmp_path: Path) -> None:
    """阴性：模块内有 `httpx.stream(...)` 调用点 ⇒ MUST NOT 命中（符号仍在被调用）。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        {
            "tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE,
            "delector/routes/encounter.py": _MODULE_USES_STREAM,
        },
    )
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "候选 0 个" in out.getvalue()


_DEAD_NAME_MODULE = (
    "def _helper() -> int:\n"  # 1
    "    return 1\n"  # 2
)

_CALLED_NAME_MODULE = (
    "def _helper() -> int:\n"  # 1
    "    return 1\n"  # 2
    "\n"  # 3
    "\n"  # 4
    "def use() -> int:\n"  # 5
    "    return _helper()\n"  # 6
)

_TEST_PATCHES_NAME = (
    "from delector import helper_mod\n"  # 1
    "\n"  # 2
    "\n"  # 3
    "def test_x(monkeypatch):\n"  # 4
    '    monkeypatch.setattr(helper_mod, "_helper", lambda: 2)\n'  # 5  ← 调用行
)


def test_criterion_flags_dead_name_patch(tmp_path: Path) -> None:
    """阳性（名字形态）：模块只定义、从不调用 `_helper` ⇒ 命中（死测/假绿形状）。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_NAME, "delector/helper_mod.py": _DEAD_NAME_MODULE},
    )
    assert _scan_sites(module, root) == [
        (5, "_helper", "delector.helper_mod", "helper_mod")
    ]


def test_criterion_passes_when_name_is_called_in_module(tmp_path: Path) -> None:
    """阴性（名字形态）：模块内 `_helper()` 被调用 ⇒ MUST NOT 命中。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_NAME, "delector/helper_mod.py": _CALLED_NAME_MODULE},
    )
    assert _scan_sites(module, root) == [], (
        "模块内已有 `_helper()` 调用点 ⇒ 不得进入候选（假阳性 = 闸被稀释）"
    )


def test_criterion_passes_when_symbol_is_own_export_via_all(tmp_path: Path) -> None:
    """细化口径 (a)：**自供出口**（顶层 def + ``__all__`` 声明）⇒ MUST NOT 命中。

    出口符号没有模块内调用点正是**预期形状**：消费方在别的模块经出口引用，实现之家
    不调用自己导出的符号 —— 属设计，不是漂移（precision fix，非便利豁免）。
    """
    module = _load_module()
    module_source = (
        '__all__ = ["stream"]\n'  # 1
        "\n"  # 2
        "\n"  # 3
        "def stream(x: object) -> object:\n"  # 4
        "    return x\n"  # 5
    )
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE, "delector/routes/encounter.py": module_source},
    )
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "候选 0 个" in out.getvalue()


def test_criterion_tags_bare_reexport_without_all(tmp_path: Path) -> None:
    """细化口径 (b)：re-export **未**列入 ``__all__`` ⇒ MUST 命中（无出口声明可依）。"""
    module = _load_module()
    module_source = "from elsewhere.api import stream\n"  # 1 裸 import 绑定，无 __all__
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE, "delector/routes/encounter.py": module_source},
    )
    assert _scan_sites(module, root) == [
        (6, "stream", "delector.routes.encounter", "encounter_mod.httpx")
    ]


def test_criterion_tags_bare_reexport_listed_in_all(tmp_path: Path) -> None:
    """细化口径 (c)：**裸 re-export 即使列入 ``__all__``** 也 MUST 命中 —— 真遗留形状。

    ``tests/test_server.py:2501``（patch ``server.nlp``）正是该形状：import 绑定他处
    符号 + ``__all__`` 兼容条目，模块内零取值点 ⇒ 补丁空转。把 import 绑定计入引用会
    静默洗白这条真遗留，故此边界 MUST 锁死。
    """
    module = _load_module()
    module_source = (
        '__all__ = ["stream"]\n'  # 1
        "from elsewhere.api import stream  # 裸 re-export：模块内无取值点\n"  # 2
    )
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE, "delector/routes/encounter.py": module_source},
    )
    assert _scan_sites(module, root) == [
        (6, "stream", "delector.routes.encounter", "encounter_mod.httpx")
    ]


def test_criterion_passes_when_package_init_exports_submodule_via_all(tmp_path: Path) -> None:
    """细化口径 (b)：包 ``__init__`` 经 ``__all__`` 声明**直属子模块**为公开出口 ⇒ MUST NOT 命中。

    形状即 ``delector.services.tts``：补丁替换的是包属性（= 子模块对象本身），消费方在
    调用期 ``from <pkg> import <sub>`` 取值 —— 属设计，不是漂移。
    """
    module = _load_module()
    init_source = (
        "from delector.pkg import helper\n"  # 1
        "\n"  # 2
        "\n"  # 3
        '__all__ = ["helper"]\n'  # 4
    )
    test_source = (
        "import delector.pkg as pkg\n"  # 1
        "\n"  # 2
        "\n"  # 3
        "def test_x(monkeypatch):\n"  # 4
        '    monkeypatch.setattr(pkg, "helper", object())\n'  # 5
    )
    root = _make_tree(
        tmp_path,
        {
            "tests/test_sample.py": test_source,
            "delector/pkg/__init__.py": init_source,
            "delector/pkg/helper.py": "x = 1\n",
        },
    )
    assert _scan_sites(module, root) == []


def test_multiline_patch_reports_call_line(tmp_path: Path) -> None:
    """多行 `monkeypatch.setattr(` 形态：命中行号 = 调用行（左括号所在行）。"""
    module = _load_module()
    source = (
        "from delector.routes import encounter as encounter_mod\n"  # 1
        "\n"  # 2
        "\n"  # 3
        "def test_pull(monkeypatch):\n"  # 4
        "    fake = object()\n"  # 5
        "    monkeypatch.setattr(\n"  # 6  ← 调用行
        "        encounter_mod.httpx,\n"  # 7
        '        "stream",\n'  # 8
        "        fake,\n"  # 9
        "    )\n"  # 10
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    assert _scan_sites(module, root) == [
        (6, "stream", "delector.routes.encounter", "encounter_mod.httpx")
    ]


# ── 阴性：非生产目标 / 无法解析 / 已登记的极限（MUST NOT 命中）─────────────────────


def test_criterion_ignores_non_production_target(tmp_path: Path) -> None:
    """阴性：目标为 stdlib 模块（`os.path`）⇒ 不在判据范围（只判 delector.* / tools.*）。"""
    module = _load_module()
    source = (
        "import os.path\n"  # 1
        "\n"  # 2
        "\n"  # 3
        "def test_x(monkeypatch):\n"  # 4
        '    monkeypatch.setattr(os.path, "exists", lambda p: True)\n'  # 5
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source})
    assert _scan_sites(module, root) == []


def test_criterion_ignores_unresolvable_target(tmp_path: Path) -> None:
    """阴性：`<obj>` 根部不是 import 别名（本地变量 / fixture）⇒ 静态不可解析，跳过。"""
    module = _load_module()
    source = (
        "def test_x(monkeypatch):\n"  # 1
        "    target = object()\n"  # 2
        '    monkeypatch.setattr(target, "anything", lambda: None)\n'  # 3
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source})
    assert _scan_sites(module, root) == []


def test_criterion_ignores_non_string_symbol(tmp_path: Path) -> None:
    """极限 #1 负样本：符号名非字符串字面量（`setattr(obj, name_var, …)`）⇒ 跳过，不判。"""
    module = _load_module()
    source = (
        "from delector.routes import encounter as encounter_mod\n"  # 1
        "\n"  # 2
        "\n"  # 3
        "def test_x(monkeypatch):\n"  # 4
        '    name = "stream"\n'  # 5
        "    monkeypatch.setattr(encounter_mod.httpx, name, lambda *a, **k: None)\n"  # 6
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    assert _scan_sites(module, root) == []


def test_criterion_ignores_string_addressed_setattr(tmp_path: Path) -> None:
    """极限 #3 负样本：字符串寻址形态（首参为点分字符串）不在判据口径内 ⇒ 跳过，不判。"""
    module = _load_module()
    source = (
        "def test_x(monkeypatch):\n"  # 1
        '    monkeypatch.setattr("delector.routes.encounter.httpx.stream", lambda *a, **k: None)\n'  # 2
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    assert _scan_sites(module, root) == []


def test_criterion_ignores_other_setattr_receivers(tmp_path: Path) -> None:
    """阴性：接收者不是 `monkeypatch`（其他替身对象的 setattr）不在扫描面。"""
    module = _load_module()
    source = (
        "from delector.routes import encounter as encounter_mod\n"  # 1
        "\n"  # 2
        "\n"  # 3
        "def test_x(patcher):\n"  # 4
        '    patcher.setattr(encounter_mod.httpx, "stream", lambda *a, **k: None)\n'  # 5
    )
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    assert _scan_sites(module, root) == []


# ── 豁免层：mock-drift-ok 只在注释里生效；空理由 = 违规 ────────────────────────────


def _sample_with_marker(marker_line: str, *, above: bool) -> str:
    """构造带标记的测试样本（`above=True` 时标记独立成行写在第 5 行）。"""
    lines = [
        "from delector.routes import encounter as encounter_mod",  # 1
        "",  # 2
        "",  # 3
        "def test_pull(monkeypatch):",  # 4
    ]
    if above:
        lines.append(f"    # {marker_line}")  # 5
        lines.append('    monkeypatch.setattr(encounter_mod.httpx, "stream", object())')  # 6 ← 调用行
    else:
        lines.append(f'    monkeypatch.setattr(encounter_mod.httpx, "stream", object())  # {marker_line}')  # 5
    return "\n".join(lines) + "\n"


def test_suppression_same_line_exempts_and_records_reason(tmp_path: Path) -> None:
    """同行注释 `mock-drift-ok: REASON` ⇒ 豁免，理由被完整记录、逐行打印。"""
    module = _load_module()
    source = _sample_with_marker("mock-drift-ok: 符号经调用期导入消费，补丁即时生效", above=False)
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "[exempt] mock-drift-ok: 符号经调用期导入消费，补丁即时生效" in out.getvalue()


def test_suppression_line_above_exempts(tmp_path: Path) -> None:
    """上一行注释 `mock-drift-ok: REASON` ⇒ 豁免。"""
    module = _load_module()
    source = _sample_with_marker("mock-drift-ok: 注释在调用行的上一行", above=True)
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "[exempt] mock-drift-ok: 注释在调用行的上一行" in out.getvalue()


def test_suppression_empty_reason_is_rejected(tmp_path: Path) -> None:
    """空理由（`mock-drift-ok:` 后什么都不写）⇒ 不豁免，判 1 并标注「REASON 为空」。"""
    module = _load_module()
    source = _sample_with_marker("mock-drift-ok:", above=False)
    root = _make_tree(tmp_path, {"tests/test_sample.py": source, "delector/routes/encounter.py": _MODULE_USES_GET})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 1
    assert "REASON 为空" in out.getvalue()


def test_suppression_marker_in_string_literal_is_not_a_comment() -> None:
    """标记出现在字符串字面量里 ⇒ 不算豁免（豁免只认注释，tokenize 口径）。"""
    module = _load_module()
    source = (
        "def test_pull() -> None:\n"  # 1
        '    note = "mock-drift-ok: 假豁免"\n'  # 2  ← 字符串，不是注释
        "    fake = object()\n"  # 3
    )
    comments = module.comments_by_line(source)
    exempt, _reason, empty_reason = module.suppression_state(comments, 3)
    assert exempt is False
    assert empty_reason is False


# ── 退出码语义：0 / 1 / 2（run_scan 与 CLI 两层）────────────────────────────────────


def test_run_scan_returns_zero_on_clean_tree(tmp_path: Path) -> None:
    """0 = 通过：符号仍在模块内被引用（无候选）。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        {"tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE, "delector/routes/encounter.py": _MODULE_USES_STREAM},
    )
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "通过" in out.getvalue()


def test_run_scan_returns_one_on_violation_and_prints_hit_line(tmp_path: Path) -> None:
    """1 = 违规：输出 MUST 含 ``file:line | symbol | 目标模块`` 逐行清单。"""
    module = _load_module()
    root = _make_tree(tmp_path, _INCIDENT_TREE)
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 1
    assert "tests/test_sample.py:6 | stream | delector.routes.encounter" in out.getvalue()
    assert "违规" in err.getvalue()


def test_run_scan_report_only_still_returns_zero(tmp_path: Path) -> None:
    """--report-only：候选照打（含计数），但退出码恒 0（只报告不判红）。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        dict(_INCIDENT_TREE, **{"tests/other.py": _TEST_PATCHES_ATTRIBUTE}),
    )
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, report_only=True, out=out, err=err) == 0
    assert "tests/test_sample.py:6 | stream | delector.routes.encounter" in out.getvalue()
    assert "候选 2 个" in out.getvalue()
    assert "report-only" in out.getvalue()


def test_run_scan_returns_two_on_missing_root(tmp_path: Path) -> None:
    """2 = 环境不可用：扫描根不存在。"""
    module = _load_module()
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(tmp_path / "absent", out=out, err=err) == 2
    assert "环境不可用" in err.getvalue()


def test_run_scan_returns_two_on_missing_scan_dir(tmp_path: Path) -> None:
    """2 = 环境不可用：缺 tests/ 扫描面（闸空转 MUST NOT 静默放行）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": "x = 1\n"}, dirs=("delector",))
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "扫描面缺失" in err.getvalue()


def test_run_scan_returns_two_on_empty_scan_surface(tmp_path: Path) -> None:
    """2 = 环境不可用：tests/ 存在但一个 .py 都没有（空转）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "扫描面为空" in err.getvalue()


def test_run_scan_returns_two_on_unparseable_test_file(tmp_path: Path) -> None:
    """2 = 环境不可用：测试文件无法解析 ⇒ 无法判定 ⇒ 拒绝放行（不是判 0）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"tests/test_broken.py": "def broken(:\n"})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "无法解析" in err.getvalue()


def test_run_scan_returns_two_on_unparseable_target_module(tmp_path: Path) -> None:
    """2 = 环境不可用：目标生产模块自身无法解析 ⇒ 无法判定 ⇒ 拒绝放行。"""
    module = _load_module()
    root = _make_tree(
        tmp_path,
        {
            "tests/test_sample.py": _TEST_PATCHES_ATTRIBUTE,
            "delector/routes/encounter.py": "def broken(:\n",
        },
    )
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "目标模块无法解析" in err.getvalue()


def test_main_cli_violation_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：不带 --report-only 时候选 ⇒ 退出码 1。"""
    module = _load_module()
    root = _make_tree(tmp_path, _INCIDENT_TREE)
    assert module.main(["--root", str(root)]) == 1
    assert "tests/test_sample.py:6 | stream | delector.routes.encounter" in capsys.readouterr().out


def test_main_cli_report_only_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：--report-only ⇒ 退出码 0。"""
    module = _load_module()
    root = _make_tree(tmp_path, _INCIDENT_TREE)
    assert module.main(["--root", str(root), "--report-only"]) == 0
    assert "tests/test_sample.py:6 | stream | delector.routes.encounter" in capsys.readouterr().out


def test_main_cli_missing_root_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：环境不可用 ⇒ 退出码 2。"""
    module = _load_module()
    assert module.main(["--root", str(tmp_path / "absent")]) == 2
    assert "环境不可用" in capsys.readouterr().err


# ── CI 接线守卫（这份闸的 fail-loud 接线本身就是契约）──────────────────────────


def test_ci_workflow_wires_the_gate_fail_loud() -> None:
    """ci.yml 必须有 `mock-drift` job 真跑判定器，且 job / 步骤均无容错键。"""
    yaml_module = pytest.importorskip("yaml")
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    doc = yaml_module.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert "mock-drift" in jobs, "ci.yml 缺少 mock-drift job（闸没接线）"
    job = jobs["mock-drift"]
    assert "continue-on-error" not in job, "job 级容错键会让闸变摆设（fail-loud 违约）"
    runs = [str(step.get("run", "")) for step in job["steps"]]
    assert any("tools/check_mock_drift.py" in run for run in runs), "job 未接线判定器脚本"
    assert all("continue-on-error" not in step for step in job["steps"]), "步骤级容错键会让闸变摆设"