# -*- coding: utf-8 -*-
r"""processed_json 版本迁移的共享实现（单篇惰性迁移与维护 CLI 共用）。

背景
====
``articles.processed_json`` 是**派生数据**（由 ``raw_text`` 经 NLP 生成），版本号
``PROCESSED_JSON_VERSION`` 是「是否需要重算」的唯一判据。版本号升级后，存量行靠**打开文章时**
的惰性迁移按需重算 —— 不在启动路径扫描全表，也不新增启动期批量重算。

三条硬约束
==========
1. **重算失败保留旧结果**：本模块只在成功产出新 payload **之后**才写库；处理函数抛错时由
   调用方捕获、继续使用旧数据。写库过程中任何异常都 MUST 回滚本次事务，绝不留下
   「备份写了、正文没更新」的半成品。
2. **旧结果可回退**：覆盖前把上一版 ``processed_json`` / ``stats_json`` 快照进
   ``processed_json_backup``（与 UPDATE 同一事务）。回退见
   ``tools/recompute_processed.py --restore``。
3. **幂等 / 可中断**：每次只处理一篇文章、单事务提交；已迁移行按版本号跳过，中途退出后
   重跑即可续上。

分层纪律：本模块**不** import ``delector.nlp_engine.processor``（db 层不反向依赖 NLP）。
当前版本号与处理函数由调用方传入，便于测试注入。
"""

import json
from typing import Any, Dict, Optional

_BACKUP_TABLE = "processed_json_backup"


def needs_migration(processed: Any, current_version: str) -> bool:
    """惰性迁移判据：非 dict / 缺 stats / 版本落后 ⇒ 需迁移。

    与写入端共用 ``PROCESSED_JSON_VERSION``（由调用方传入），MUST NOT 在本模块再写版本字面量。
    """
    return not (
        isinstance(processed, dict) and "stats" in processed and processed.get("version") == current_version
    )


def _version_of(processed_json: Optional[str]) -> str:
    """从旧 payload 文本里取版本号（损坏 / 非对象一律空串，绝不抛）。"""
    try:
        parsed = json.loads(processed_json or "")
    except (TypeError, ValueError):
        return ""
    if isinstance(parsed, dict):
        version = parsed.get("version")
        if isinstance(version, str):
            return version
    return ""


def write_migrated(
    conn: Any,
    article_id: int,
    old_processed_json: Optional[str],
    old_stats_json: Optional[str],
    payload: Dict[str, Any],
) -> None:
    """快照旧结果 + 写入新结果（同一事务；调用方负责 commit/rollback）。

    备份是 ``ON CONFLICT DO UPDATE``：始终保留「本次覆盖前的上一版」，重复升级时回退目标
    是紧邻的前一版而不是最早版本。
    """
    conn.execute(
        f"INSERT INTO {_BACKUP_TABLE} "
        "(article_id, processed_version, processed_json, stats_json, backed_up_at) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(article_id) DO UPDATE SET "
        "processed_version = excluded.processed_version, "
        "processed_json = excluded.processed_json, "
        "stats_json = excluded.stats_json, "
        "backed_up_at = CURRENT_TIMESTAMP",
        (
            article_id,
            _version_of(old_processed_json),
            old_processed_json if old_processed_json is not None else "",
            old_stats_json,
        ),
    )
    conn.execute(
        "UPDATE articles SET processed_json = ?, stats_json = ? WHERE id = ?",
        (
            json.dumps(payload, ensure_ascii=False),
            json.dumps(payload.get("stats") or {}, ensure_ascii=False),
            article_id,
        ),
    )


def restore_article(conn: Any, article_id: int) -> bool:
    """把某篇的备份写回 articles；有备份返回 True。commit 由调用方负责。

    写回的是**逐字原始文本**（含损坏 JSON 的原始字节形态），不做任何再生成。
    注意：回退后该行版本号仍是旧值 ⇒ 若当前代码仍是升级后的版本号，下次打开会再次
    惰性迁移并覆盖。维护者回退的完整步骤见 ``tools/recompute_processed.py`` 的模块文档。
    """
    row = conn.execute(
        f"SELECT processed_json, stats_json FROM {_BACKUP_TABLE} WHERE article_id = ?", (article_id,)
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE articles SET processed_json = ?, stats_json = ? WHERE id = ?",
        (row["processed_json"], row["stats_json"], article_id),
    )
    conn.execute(f"DELETE FROM {_BACKUP_TABLE} WHERE article_id = ?", (article_id,))
    return True
