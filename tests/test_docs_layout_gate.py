# -*- coding: utf-8 -*-
"""docs/ 目录归置机械闸：真实树基线 + 逐类违规的变异自证。

为什么有这组用例
----------------
``tools/check_docs_layout.py`` 把 docs 各目录 README 的归置约定变成机械检查。
用例 MUST 同时钉住两件事：
1. 真实仓库当前**绿**（否则闸一上线就是红的，没人会信它）；
2. 每一类违规**真能红**（只证明能绿等于没证明闸存在）。

判据全部走真实判定器（非字符串在场）；夹具用 tmp_path 构造最小 docs 树，
白名单在夹具里显式传入，不依赖真实仓库的历史豁免。
"""

import importlib.util
from pathlib import Path
from typing import Any, Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "check_docs_layout.py"


def _load_tool() -> Any:
    """按文件路径加载判定器（tools 不是包，避免依赖 sys.path 形状）。"""
    if not TOOL.exists():
        pytest.fail(f"判定器脚本不存在：{TOOL}（docs 归置机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_docs_layout", TOOL)
    assert spec is not None and spec.loader is not None, f"无法加载判定器：{TOOL}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_docs(tmp_path: Path, files: Mapping[str, str]) -> Path:
    """构造最小 docs 树；键为相对 docs 根的 POSIX 路径。"""
    root = tmp_path / "docs"
    root.mkdir()
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _run(tmp_path: Path, files: Mapping[str, str], whitelist: Any = ()) -> int:
    root = _make_docs(tmp_path, files)
    return int(_load_tool().main(["--docs-root", str(root)], whitelist=whitelist))


def _base() -> dict[str, str]:
    return {
        "README.md": "# docs/ 目录约定\n",
        "plans/2026-11-09-sample.md": "# plan\n",
    }


# ── 真实仓库基线 ────────────────────────────────────────────────────────────
def test_real_docs_tree_passes() -> None:
    """真实 docs/ 树必须绿；任何未登记/错位文件都会让本用例红。"""
    tool = _load_tool()
    assert tool.main(["--docs-root", str(REPO_ROOT / "docs")]) == 0


# ── 索引登记类 ──────────────────────────────────────────────────────────────
def test_unregistered_review_is_red(tmp_path: Path) -> None:
    """reviews/ 新增报告未写进 reviews/README.md ⇒ 红（本次事故的直接形态）。"""
    files = _base() | {
        "reviews/README.md": "# 评审索引\n",
        "reviews/2026-11-09-unregistered-research.md": "# 调研\n",
    }
    assert _run(tmp_path, files) == 1


def test_registered_review_passes(tmp_path: Path) -> None:
    """登记后即绿（证明红线是「未登记」，不是「禁止新增」）。"""
    files = _base() | {
        "reviews/README.md": "# 评审索引\n\n- [报告](2026-11-09-registered.md)\n",
        "reviews/2026-11-09-registered.md": "# 报告\n",
    }
    assert _run(tmp_path, files) == 0


def test_unregistered_research_is_red(tmp_path: Path) -> None:
    """research/ 新增文件未写进 research/README.md ⇒ 红。"""
    files = _base() | {
        "research/README.md": "# 调研索引\n",
        "research/2026-11-09-unregistered.md": "# 调研\n",
    }
    assert _run(tmp_path, files) == 1


def test_unregistered_adr_is_red(tmp_path: Path) -> None:
    """ADR 副本未写进 adr/INDEX.md ⇒ 红（INDEX 顶部有此硬要求）。"""
    files = _base() | {
        "adr/INDEX.md": "# ADR 状态索引\n",
        "adr/2026-11-09-adr-0031-unregistered.md": "# ADR\n",
    }
    assert _run(tmp_path, files) == 1


# ── 目录/命名类 ─────────────────────────────────────────────────────────────
def test_unknown_parallel_dir_is_red(tmp_path: Path) -> None:
    """docs/ 下新开 README 未列出的平行目录 ⇒ 红。"""
    files = _base() | {"superpowers/plan.md": "# old\n"}
    assert _run(tmp_path, files) == 1


def test_unknown_top_level_file_is_red(tmp_path: Path) -> None:
    """docs/ 顶层放 README 未列出的 *.md ⇒ 红。"""
    files = _base() | {"misc.md": "# misc\n"}
    assert _run(tmp_path, files) == 1


def test_spec_naming_is_red(tmp_path: Path) -> None:
    """设计稿不按 <日期>-<主题>-design.md 命名 ⇒ 红。"""
    files = _base() | {"specs/2026-11-09-bad-name.md": "# spec\n"}
    assert _run(tmp_path, files) == 1


def test_plan_naming_is_red(tmp_path: Path) -> None:
    """计划不带 <日期>- 前缀且不在白名单 ⇒ 红。"""
    files = _base() | {"plans/archive/no-date-plan.md": "# plan\n"}
    assert _run(tmp_path, files) == 1


# ── 白名单纪律 ──────────────────────────────────────────────────────────────
def test_whitelist_empty_reason_is_config_error(tmp_path: Path) -> None:
    """白名单条目无理由 ⇒ 退出码 2（配置错误，不是静默放行）。"""
    tool = _load_tool()
    exemption = tool.Exemption("plans/archive/no-date-plan.md", "  ")
    files = _base() | {"plans/archive/no-date-plan.md": "# plan\n"}
    root = _make_docs(tmp_path, files)
    assert tool.main(["--docs-root", str(root)], whitelist=(exemption,)) == 2


def test_stale_whitelist_entry_is_red(tmp_path: Path) -> None:
    """白名单指向的文件已不存在 ⇒ 红，防止白名单腐烂后继续放行。"""
    tool = _load_tool()
    exemption = tool.Exemption("plans/archive/gone.md", "历史豁免，理由示例")
    files = _base()
    root = _make_docs(tmp_path, files)
    assert tool.main(["--docs-root", str(root)], whitelist=(exemption,)) == 1


def test_whitelisted_file_passes_and_prints_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """白名单豁免 MUST 大声打印理由（fail-loud），不得静默跳过。"""
    tool = _load_tool()
    exemption = tool.Exemption("plans/archive/no-date-plan.md", "历史既成事实，改名会打断引用")
    files = _base() | {"plans/archive/no-date-plan.md": "# plan\n"}
    root = _make_docs(tmp_path, files)
    assert tool.main(["--docs-root", str(root)], whitelist=(exemption,)) == 0
    err = capsys.readouterr().err
    assert "whitelist" in err and "历史既成事实" in err
