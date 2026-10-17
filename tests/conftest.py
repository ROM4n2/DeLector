# -*- coding: utf-8 -*-
r"""tests/ 侧 conftest：会话级「仓库根数据目录」守卫。

为什么它住在这里，而不是根 `conftest.py`
------------------------------------------
根 `conftest.py` 在 CI 的**入口面 strict mypy 门禁**里：
`mypy --platform win32 --strict --follow-imports=skip desktop.py package_windows.py conftest.py start.py`。
该门禁带 `--follow-imports=skip` ⇒ `pytest` 是**不可解析导入**（视作 Any）⇒ 里面任何
`@pytest.fixture` 都会被判 `untyped-decorator`（strict 专属检查）。而 `tests/` 那档门禁
（`mypy --follow-imports=skip tests`）**不是 strict** ⇒ 夹具放测试侧两档门禁都干净，
**不需要任何 `# type: ignore`**。夹具本来也该住在测试侧。

为什么需要这个守卫
------------------
`database.DATA_DIR` 在 `DELECTOR_DATA_DIR` 缺席时**兜底到仓库根**（`delector/core/database.py:36`），
而 `delector/server.py` 在**模块顶层**就调 `init_db()` ⇒ 任何"没先钉落点就 import server"
的路径（诊断 import / 忘钉 env 的脚本 / 别的会话）都会在**仓库根**建一套库。后果不只是脏：
根目录一有库，`tests/test_save_wb_state_cost.py` 的迁移闸（`preflight_data_dir`）就拒绝运行
⇒ **本地红、CI 绿**（CI 是干净克隆），最耗人的那类分歧。

为什么比对**快照差值**而不是"断言根目录没有库"
----------------------------------------------
便携模式（`DELECTOR_PORTABLE=1`）下仓库根**本来**就是合法落点，开发者手上可能先就有库 ——
那种情况不该判红。只有"**本次测试运行期间**新出现 / 被改动"才是泄漏。
helper（`root_db_snapshot` / `describe_root_db_diff`）落在 `db_cleanup.py`：那是测试侧
数据库文件关注点的既有唯一实现，本文件只负责把它接成会话守卫。
"""

from pathlib import Path
from typing import Iterator

import pytest
from db_cleanup import describe_root_db_diff, root_db_snapshot
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _guard_repo_root_data_dirs() -> Iterator[None]:
    """本次测试运行期间仓库根**不得**新增 / 改动 `delector.db` / `progress.db` / `test_*.db`（含侧文件）。

    注（2026-10-16 审计 P1-1）：视野随 `db_cleanup.ROOT_DB_NAMES` 扩含 `test_*.db` ——
    测试自己的库（如根 `conftest.py` 默认的 `test_conftest_default.db`）此前全在守卫
    视野之外，而 `*.db` 被 `.gitignore` 挡住 ⇒ 这类泄漏可以无限期无人发现。

    失败时给出**根因与三步修法**（不甩锅给读者）。
    """
    before = root_db_snapshot(str(ROOT))
    yield
    after = root_db_snapshot(str(ROOT))
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


@pytest.fixture
def client():
    # 显式给出本机来源地址：备份端点有「仅 127.0.0.1」闸，
    # TestClient 默认把 client.host 报成 "testclient"，会被闸拒掉。
    #
    # C6 Task 1：自 tests/test_server.py 下沉至此（分域切分的前置）。`app` 的 import
    # 刻意留在夹具体内：conftest 顶层 import delector.server 会让任何 tests/ 会话在
    # 收集期触发 server 模块顶层的 init_db()；惰性导入把时机保持为「用例真正请求
    # client 时」，与下沉前的暴露面一致。语义与默认作用域逐字保持。
    from delector.server import app

    return TestClient(app, client=("127.0.0.1", 54321))
