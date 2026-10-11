# -*- coding: utf-8 -*-
"""根 conftest：把仓库根目录插进 sys.path，让 tests/ 下的测试能 import `delector` 包。

为什么必须有这个文件：CI 与本地都跑 `pytest -v`，而 `pytest` 不像
`python -m pytest` 那样把当前工作目录加进 sys.path。测试在 `tests/` 里，
后端已收进 `delector/` 包 —— 但 pytest 只把 `tests/` 自身插进 sys.path，
仓库根不在其中，`from delector import server` 一样 ModuleNotFoundError。

Phase 1 的注释说过"Phase 2 收包后这里就该删掉"，那是错的：收包并不改变
pytest 不注入 CWD 的事实，`import delector` 依然需要根在 sys.path。
这个文件是长期需要的，别删。
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterator, Mapping, Tuple

import pytest

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 测试默认库：保证「任何测试模块 import server 之前 env 已有值」，使 server 模块顶层的
# init_db() 落到测试库而非仓库根的真实 delector.db；同时给各模块 fixture 的 env 还原
# 提供稳定目标（契约见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1 C2）。
# 用 setdefault：尊重外部（CI）已显式指定的库。
os.environ.setdefault("DATABASE_PATH", "test_conftest_default.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_conftest_default_progress.db")


def pytest_sessionstart(session: pytest.Session) -> None:
    """CI 缺少必需的 Node 运行时时立即失败；本地仍由各 wrapper 决定是否 skip。"""
    if os.environ.get("CI") and not shutil.which("node"):
        pytest.exit(
            "CI 环境缺少必需的 node 运行时；.mjs 探针不能以 skip 静默跳过",
            returncode=1,
        )


# ── 仓库根「数据目录」守卫（2026-10-11）──────────────────────────────────────────
# 为什么需要它：`database.DATA_DIR` 在 `DELECTOR_DATA_DIR` 缺席时**兜底到仓库根**
# （`delector/core/database.py:36`），而 `delector/server.py` 在**模块顶层**就调 `init_db()`
# ⇒ 任何"没先钉落点就 import server"的路径（诊断 import / 忘钉 env 的脚本 / 别的会话）
# 都会在**仓库根**建一套库。后果不只是脏：根目录一有库，`tests/test_save_wb_state_cost.py`
# 的迁移闸（`preflight_data_dir`）就拒绝运行 ⇒ **本地红、CI 绿**（CI 是干净克隆）。
# 为什么比对**快照差值**而不是"断言根目录没有库"：便携模式（`DELECTOR_PORTABLE=1`）下
# 仓库根**本来**就是合法落点，开发者手上可能先就有库 —— 那种情况不该判红；只有
# "**本次测试运行期间**新出现 / 被改动"才是泄漏。
_ROOT_DB_NAMES: Tuple[str, ...] = ("delector.db", "progress.db")


def root_db_snapshot(root: Path) -> Dict[str, int]:
    """仓库根那两套库（含 `-wal` / `-shm` 侧文件）的快照：文件名 → 字节数。"""
    snapshot: Dict[str, int] = {}
    for name in _ROOT_DB_NAMES:
        for suffix in ("", "-wal", "-shm"):
            path = root / f"{name}{suffix}"
            if path.is_file():
                snapshot[path.name] = path.stat().st_size
    return snapshot


def describe_root_db_diff(before: Mapping[str, int], after: Mapping[str, int]) -> str:
    """把两次快照的差异说成人话（新出现 / 被改动 / 消失），供守卫报错用。"""
    added = sorted(set(after) - set(before))
    changed = sorted(name for name in set(after) & set(before) if after[name] != before[name])
    removed = sorted(set(before) - set(after))
    parts = []
    if added:
        parts.append(f"新出现：{', '.join(added)}")
    if changed:
        parts.append(f"被改动：{', '.join(changed)}")
    if removed:
        parts.append(f"消失：{', '.join(removed)}")
    return "；".join(parts) if parts else "无差异"


@pytest.fixture(scope="session", autouse=True)
def _guard_repo_root_data_dirs() -> Iterator[None]:
    """会话级守卫：本次测试运行期间仓库根**不得**新增 / 改动 `delector.db` / `progress.db`。

    失败时给出**根因与修法**（不是"你自己去看"）：见下方断言消息里的三步。
    """
    before = root_db_snapshot(ROOT)
    yield
    after = root_db_snapshot(ROOT)
    if after != before:
        raise AssertionError(
            f"测试运行期间仓库根的数据文件被动了：{describe_root_db_diff(before, after)}。\n"
            "根因通常是：某条路径在 `DELECTOR_DATA_DIR` 缺席时用了 `database.DATA_DIR` 的"
            "仓库根兜底（`delector/core/database.py:36`），而 `delector/server.py` 在**模块顶层**"
            "就 `init_db()` ⇒ import 即建库。\n"
            "修法：给那条路径显式钉 `DELECTOR_DATA_DIR`（或 `DATABASE_PATH` / `PROGRESS_DB_PATH`）；"
            "已经产生的文件请**移走**——它们会毒化 `tests/test_save_wb_state_cost.py` 的迁移闸，"
            "造成「本地红 / CI 绿」。冒烟纪律见 `delector/core/data_dir_bootstrap.py` 的模块 docstring。"
        )
