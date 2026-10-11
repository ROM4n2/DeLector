# -*- coding: utf-8 -*-
r"""P0-2 回归锁：`get_setting` 不得静默吞异常（已配置的 API key 曾被静默失效）。

已证实的缺陷
------------
`database.get_setting` 曾是 `except Exception: pass` 无日志：库锁/损坏时已配置的
key 被静默忽略 ⇒ `get_effective_api_key` 返回空 ⇒ `main.py` 走 stub 200，误报
"用户没配置 key"。

修法契约
--------
- 收窄到 `sqlite3.Error`，回落前必须 `logging.getLogger("delector").warning(...)`
  且带 `exc_info=True`（否则排查时零线索）；
- `os.environ` 兜底**保留**（依赖调查见测试 docstring 与修复报告）：
  `delector/server.py:load_env()` 会把 `.env` 的 `DEEPSEEK_API_KEY` 等灌进
  `os.environ`，Docker（WORKDIR=/app）与 `.env` 用户是**真实依赖路径**；
  保留时加可见日志（"设置 X 回落到环境变量"）。

**变异自证**：把 `except sqlite3.Error` 改回 `except Exception: pass`（无日志）
⇒ `test_get_setting_logs_warning_on_db_error` 立即转红（warning 记录消失）。
"""

import logging
import sqlite3
from typing import Any

import pytest

from delector.core import database


def test_get_setting_logs_warning_and_returns_env_value_on_db_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """库抛 `sqlite3.OperationalError` ⇒ 落 WARNING（带 exc_info）+ 仍返回 env 兜底值。

    这条同时钉住两件事：① key 不再被静默忽略（有日志留痕）；② 语义不变
    （env 兜底值照常返回，Docker/.env 场景不被破坏）。
    """
    def broken_conn(db_path: Any = None) -> Any:
        raise sqlite3.OperationalError("模拟：库被锁 / 损坏")

    monkeypatch.setattr(database, "db_conn", broken_conn)
    monkeypatch.setenv("DELECTOR_GUARD_TEST_KEY", "env-key-value")
    caplog.set_level(logging.DEBUG)

    value = database.get_setting("DELECTOR_GUARD_TEST_KEY", "dflt")

    assert value == "env-key-value", "库读失败 ⇒ 必须仍回落到 env 兜底（语义不变）"

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "库读失败必须落 WARNING 日志（except: pass 静默吞 = 本 P0 的根因）"
    assert any(
        "DELECTOR_GUARD_TEST_KEY" in r.getMessage() for r in warnings
    ), "WARNING 必须点名是哪个 key 读失败"
    assert any(r.exc_info for r in warnings), "WARNING 必须携带 exc_info（否则排查零线索）"


def test_get_setting_logs_when_falling_back_to_env(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """env 兜底保留（真实依赖：load_env() 把 .env 灌进 os.environ），
    但回落时必须有可见日志——"设置 X 回落到环境变量"。"""

    class FakeConn:
        """库里没有该 key（row 为 None）⇒ 走 env 兜底的正常路径。"""

        def __enter__(self) -> "FakeConn":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            class _Cursor:
                def fetchone(self) -> None:
                    return None

            return _Cursor()

    monkeypatch.setattr(database, "db_conn", lambda db_path=None: FakeConn())
    monkeypatch.setenv("DELECTOR_GUARD_ENV_FALLBACK", "from-env")
    caplog.set_level(logging.DEBUG)

    value = database.get_setting("DELECTOR_GUARD_ENV_FALLBACK", "dflt")

    assert value == "from-env", "库内没有 ⇒ env 兜底值照常返回（保留语义）"
    assert any(
        "DELECTOR_GUARD_ENV_FALLBACK" in r.getMessage() and "环境变量" in r.getMessage()
        for r in caplog.records
    ), "回落到环境变量时必须留下可见日志（不许悄悄用 env 值）"


def test_get_setting_returns_db_row_without_env_fallback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """库正常且行存在 ⇒ 返回库值（本 P0 的主语义不得被改动）。"""

    class FakeConn:
        def __enter__(self) -> "FakeConn":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            class _Cursor:
                def fetchone(self) -> dict:
                    return {"value": "db-value"}

            return _Cursor()

    monkeypatch.setattr(database, "db_conn", lambda db_path=None: FakeConn())
    monkeypatch.setenv("DELECTOR_GUARD_DB_ROW_KEY", "should-not-be-used")
    caplog.set_level(logging.DEBUG)

    value = database.get_setting("DELECTOR_GUARD_DB_ROW_KEY", "dflt")

    assert value == "db-value", "库正常 ⇒ 必须用库值（不得被 env 值冒充）"
    assert not any("DELECTOR_GUARD_DB_ROW_KEY" in r.getMessage() for r in caplog.records), (
        "库值命中时不得出现 env 回落日志（正常路径零噪音）"
    )
