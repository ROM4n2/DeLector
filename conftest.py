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

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 测试默认库：保证「任何测试模块 import server 之前 env 已有值」，使 server 模块顶层的
# init_db() 落到测试库而非仓库根的真实 delector.db；同时给各模块 fixture 的 env 还原
# 提供稳定目标（契约见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1 C2）。
#
# 默认值 MUST 是**绝对路径**（审计 P1-1）：`setdefault` 的值只在「没人显式钉过」时生效，
# 而那正是裸文件名会出事的地方 —— 裸名由 sqlite 按进程 CWD 解析，「从仓库根跑 pytest」
# 就把库写进仓库根（`*.db` 被 .gitignore 挡住 ⇒ 泄漏可无限期无人发现）。
# 所以默认值钉到一个**临时目录的绝对路径**：与 CWD 无关，且不污染工作区。
# 目录在导入期（模块级）就建，因为 pytest 夹具的 tmp_path/tmp_path_factory 此时尚不可用，
# 而 `delector/server.py` 是**模块顶层**就 init_db() ⇒ env 必须在那之前已经有值。
_TMP_DB_DIR = tempfile.mkdtemp(prefix="delector_pytest_db_")
# 尽力清理（Windows 上句柄未释放会删不掉，ignore_errors 免得清理失败反把退出搞挂）。
atexit.register(shutil.rmtree, _TMP_DB_DIR, ignore_errors=True)

# 用 setdefault：尊重外部（CI）已显式指定的库值 —— 这是设计，不是疏漏。
os.environ.setdefault("DATABASE_PATH", os.path.join(_TMP_DB_DIR, "test_conftest_default.db"))
os.environ.setdefault(
    "PROGRESS_DB_PATH", os.path.join(_TMP_DB_DIR, "test_conftest_default_progress.db")
)


def pytest_sessionstart(session: pytest.Session) -> None:
    """CI 缺少必需的 Node 运行时时立即失败；本地仍由各 wrapper 决定是否 skip。"""
    if os.environ.get("CI") and not shutil.which("node"):
        pytest.exit(
            "CI 环境缺少必需的 node 运行时；.mjs 探针不能以 skip 静默跳过",
            returncode=1,
        )

