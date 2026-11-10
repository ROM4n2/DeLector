# -*- coding: utf-8 -*-
"""发布文档守卫：真实树基线 + 逐类违规的变异自证。

为什么有这组用例
----------------
``tools/check_release_docs.py`` 把「CHANGELOG 必须降序且结构完整 / README 版本表 ≤3 行 /
发布面文档无 emoji」变成机械检查。用例 MUST 同时钉住两件事：

1. 真实仓库当前**绿**（闸一上线就是红的话没人会信它）；
2. 每一类违规**真能红**（只证明能绿等于没证明闸存在）。

判据全部走真实判定器（非字符串在场）；夹具用 ``tmp_path`` 构造最小仓库，
不依赖真实仓库的历史豁免。
"""

import importlib.util
from pathlib import Path
from typing import Any, Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "check_release_docs.py"


def _load_tool() -> Any:
    """按文件路径加载判定器（tools 不是包，避免依赖 sys.path 形状）。"""
    if not TOOL.exists():
        pytest.fail(f"判定器脚本不存在：{TOOL}（发布文档机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_release_docs", TOOL)
    assert spec is not None and spec.loader is not None, f"无法加载判定器：{TOOL}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD_CHANGELOG = """# 更新日志 (Changelog)

## v5.22.1 - 2026-11-09

### 修复

- 修了 A。

### 已知限制（Known Limitations）

- B 未验证。

### 回滚（Rollback）

- 产物可回退。

---

## v5.22.0 - 2026-11-08

### 修复

- 修了 C。

### 已知限制（Known Limitations）

- 无。

### 回滚（Rollback）

- 产物可回退。
"""

GOOD_README = """# DeLector

## 版本历史

| 版本 | 发布日期 | 里程碑概要 |
| :--- | :--- | :--- |
| **v5.22.1** | 2026-11-09 | A |
| **v5.22.0** | 2026-11-08 | B |
| **v5.21.1** | 2026-11-03 | C |

> 更早的版本已迁入 CHANGELOG.md。
"""

GOOD_TEMPLATE = "# 模板\n\n不使用 emoji。\n"

GOOD_WORKFLOW = "body: |\n  跨版本稳定内容。\n"


def _make_repo(tmp_path: Path, files: Mapping[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _good_files() -> dict[str, str]:
    return {
        "CHANGELOG.md": GOOD_CHANGELOG,
        "README.md": GOOD_README,
        ".github/release-notes-template.md": GOOD_TEMPLATE,
        ".github/workflows/build-release.yml": GOOD_WORKFLOW,
    }


def _messages(rules: list[Any]) -> str:
    return " | ".join(f"{v.where}: {v.message}" for v in rules)


def test_real_repository_passes() -> None:
    """真实仓库当前必须绿，否则闸一上线就是红的。"""
    module = _load_tool()
    assert module.check(REPO_ROOT) == [], _messages(module.check(REPO_ROOT))


def test_fixture_baseline_is_green(tmp_path: Path) -> None:
    module = _load_tool()
    root = _make_repo(tmp_path, _good_files())
    assert module.check(root) == [], _messages(module.check(root))


def test_ascending_versions_are_rejected(tmp_path: Path) -> None:
    """顺序颠倒（旧版在上）必须红 —— 这是「每次发版插错位置」的直接判别式。"""
    module = _load_tool()
    broken = GOOD_CHANGELOG.replace("## v5.22.1 - 2026-11-09", "## v5.22.1 - 2026-11-09").replace(
        "## v5.22.0 - 2026-11-08", "## v5.22.2 - 2026-11-10"
    )
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": broken})
    assert "严格降序" in _messages(module.check(root))


def test_date_regression_is_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_CHANGELOG.replace("## v5.22.0 - 2026-11-08", "## v5.22.0 - 2026-11-20")
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": broken})
    assert "日期不是单调不增" in _messages(module.check(root))


def test_missing_separator_is_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_CHANGELOG.replace("\n---\n\n## v5.22.0", "\n## v5.22.0")
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": broken})
    assert "缺少一行 `---` 分隔" in _messages(module.check(root))


def test_latest_block_missing_sections_is_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_CHANGELOG.replace("### 已知限制（Known Limitations）", "### 已知边界").replace(
        "### 回滚（Rollback）", "### 退路"
    )
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": broken})
    text = _messages(module.check(root))
    assert "缺少 `### 已知限制（Known Limitations）`" in text
    assert "缺少 `### 回滚（Rollback）`" in text


def test_readme_four_rows_are_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_README.replace(
        "| **v5.21.1** | 2026-11-03 | C |",
        "| **v5.21.1** | 2026-11-03 | C |\n| **v5.21.0** | 2026-11-03 | D |",
    )
    root = _make_repo(tmp_path, {**_good_files(), "README.md": broken})
    assert "超过 3 行上限" in _messages(module.check(root))


def test_emoji_in_changelog_is_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_CHANGELOG.replace("- 修了 A。", "- 修了 A 🎉")
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": broken})
    assert "包含 emoji" in _messages(module.check(root))


def test_emoji_in_release_template_is_rejected(tmp_path: Path) -> None:
    module = _load_tool()
    broken = GOOD_TEMPLATE + "\n## 本版重点 ⚠\n"
    root = _make_repo(tmp_path, {**_good_files(), ".github/release-notes-template.md": broken})
    assert "包含 emoji" in _messages(module.check(root))


def test_arrow_and_middot_are_not_emoji(tmp_path: Path) -> None:
    """正文常用排版符号（箭头 / 中点 / 破折号）不得被误判成 emoji。"""
    module = _load_tool()
    ok = GOOD_CHANGELOG.replace("- 修了 A。", "- 修了 A → B，附带 · 说明 —— 就这样。")
    root = _make_repo(tmp_path, {**_good_files(), "CHANGELOG.md": ok})
    assert module.check(root) == [], _messages(module.check(root))
