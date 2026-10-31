# -*- coding: utf-8 -*-
r"""设置持久化与鉴权（`app_settings` 读写、API 生效值、workbench 同步密钥）。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 3）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.settings import X as X` 再导出，公开面零变化。

本片承载的整组职责：
- 设置读写：`get_setting` / `set_setting`（`app_settings` 表 + env 兜底）
- workbench 同步鉴权：`get_wb_sync_key` / `regenerate_wb_sync_key` / `verify_wb_key`
  （`delector/core/wb_auth.py` 依赖后两者）
- API 生效值（库值优先、env 兜底走 `get_setting`）：`get_effective_api_key` /
  `get_effective_api_base_url` / `get_effective_api_model`

本片**无模块级可变状态**（不缓存任何设置值）。
"""

import logging
import os
import secrets
import sqlite3
from typing import Optional

from delector.core.db.connection import db_conn


def get_setting(key: str, default: str = "", db_path: Optional[str] = None) -> str:
    # P0-2：曾经 `except Exception: pass` 无日志——库锁/损坏时**已配置的 API key 被静默忽略**
    # （get_effective_api_key 走这里 ⇒ main.py 误走 stub，报"用户没配 key"）。收窄到
    # sqlite3.Error 并落 WARNING（带 exc_info），回落不再是静默的。
    try:
        with db_conn(db_path) as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if row and row["value"] is not None and row["value"] != "":
                return row["value"]  # type: ignore[no-any-return]  # sqlite3.Row 索引为 Any，此处运行时恒为 str
    except sqlite3.Error:
        logging.getLogger("delector").warning(
            "get_setting(%s) 读取失败，回落到默认值/环境变量", key, exc_info=True
        )
    # env 兜底**保留**（依赖调查结论）：delector/server.py 的 load_env() 会把 .env 的
    # DEEPSEEK_API_KEY 等灌进 os.environ，Docker（WORKDIR=/app）与 .env 用户会真实走
    # 这条路（tests/test_ci_hardening.py 的 .dockerignore 守卫注释亦证实）；删掉 = 静默
    # 破坏既有部署。保留但加可见日志——回落不许再是无声的。
    env_val = os.environ.get(key)
    if env_val:
        logging.getLogger("delector").info(
            "设置 %s 库内未取到，回落到环境变量", key
        )
        return env_val
    return default


def set_setting(key: str, value: str, db_path: Optional[str] = None) -> None:
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
            (key, value),
        )


def get_wb_sync_key(db_path: Optional[str] = None) -> str:
    """workbench server 同步密钥：读 app_settings，缺则生成 32 位 hex 并持久化。

    独立于 DEEPSEEK_API_KEY；单用户自用，明文 header 传输即够。
    幂等：同一库重复调用返回同一把 key（手机从电脑拿一次就能长期用）。
    """
    key = get_setting("wb_sync_key", "", db_path=db_path)
    if not key:
        key = secrets.token_hex(16)
        set_setting("wb_sync_key", key, db_path=db_path)
    return key


def regenerate_wb_sync_key(db_path: Optional[str] = None) -> str:
    """作废旧同步密钥并生成新的一把（= 撤销配对）：旧 key 立即失效。

    持久凭证敢长期有效的前提是「随时能一键作废」：泄露或换设备时重新生成，
    所有仍持旧 key 的端立即 403，必须重新配对。
    """
    key = secrets.token_hex(16)
    set_setting("wb_sync_key", key, db_path=db_path)
    return key


def verify_wb_key(provided: Optional[str], expected: Optional[str]) -> bool:
    """X-WB-Key 恒定时间校验统一入口。

    `secrets.compare_digest` 是恒定时间比较（长度与内容不产生可观测时序差），
    直接 `!=` 会让 key 校验成为时序侧信道。所有使用 X-WB-Key 鉴权的位置
    （wb state PUT / sync 信令 / rtc 信令）都必须走这里，禁止再写裸 `!=`。
    """
    return secrets.compare_digest(str(provided or ""), str(expected or ""))


def get_effective_api_key(db_path: Optional[str] = None) -> str:
    return get_setting("DEEPSEEK_API_KEY", "", db_path=db_path)


def get_effective_api_base_url(db_path: Optional[str] = None) -> str:
    return get_setting("API_BASE_URL", "https://api.deepseek.com", db_path=db_path)


def get_effective_api_model(db_path: Optional[str] = None) -> str:
    return get_setting("API_MODEL", "deepseek-v4-flash", db_path=db_path)


def get_effective_reasoning_effort(db_path: Optional[str] = None) -> str:
    return get_setting("REASONING_EFFORT", "medium", db_path=db_path)
