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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 测试默认库：保证「任何测试模块 import server 之前 env 已有值」，使 server 模块顶层的
# init_db() 落到测试库而非仓库根的真实 delector.db；同时给各模块 fixture 的 env 还原
# 提供稳定目标（契约见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1 C2）。
# 用 setdefault：尊重外部（CI）已显式指定的库。
os.environ.setdefault("DATABASE_PATH", "test_conftest_default.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_conftest_default_progress.db")
