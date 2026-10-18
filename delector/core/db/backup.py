# -*- coding: utf-8 -*-
"""备份 / 还原（清单、白名单、暂存槽与落盘回灌）。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 2）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.backup import X as X` 再导出，公开面零变化。

本片承载的整组职责：
- 清单与默认值：`_BACKUP_TABLES` / `_PROGRESS_TABLES` / `_SRS_COLUMNS` / `_SRS_DEFAULTS`
- 设置白名单：`BACKUP_SETTINGS_WHITELIST` / `..._EXPORT_...` / `..._IMPORT_...`
- 导出组装：`build_backup_payload`
- 暂存槽与 token：`_pending_backup` / `_pending_wb` / `BACKUP_TOKEN_TTL_SEC` /
  `_issue_pending` / `_take_pending`
- 落盘/回灌：`_rows_to_tuples` / `_replace_tables` / `_backup_db_file` /
  `_restore_db_file` / `_db_snapshot_guard`

模块级状态（两份 pending 暂存槽）**随函数同迁**，全仓仅此一份（不分裂成两份副本）。
"""

import logging
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Tuple

from fastapi import HTTPException

from delector.core.db.connection import (
    get_db,
    get_db_path,
    get_progress_db,
    get_progress_db_path,
)

BACKUP_FORMAT_VERSION = 2

# app_settings 的**正向**白名单。用白名单而非黑名单：将来新增敏感设置项时，
# 黑名单会默认泄露，白名单会默认安全。DEEPSEEK_API_KEY 绝不在列 ——
# 备份 JSON 是用户会分享、上传、丢进网盘的文件。
#
# 导出/还原白名单刻意**拆成两份**：
# - 导出（BACKUP_SETTINGS_WHITELIST / BACKUP_SETTINGS_EXPORT_WHITELIST）保留
#   API_BASE_URL/API_MODEL —— 它们不是机密，导出带上是正常的设备间配置迁移。
# - 还原（BACKUP_SETTINGS_IMPORT_WHITELIST）**只允许 TTS_***：API_BASE_URL 若从
#   恶意备份导入，会把库里真实 DEEPSEEK_API_KEY 的下一次 AI 调用（带 Bearer 头）
#   指向攻击者服务器 → 密钥外泄。还原时这两项一律保留本机现值。
BACKUP_SETTINGS_WHITELIST = ("TTS_VOICE", "TTS_RATE", "API_BASE_URL", "API_MODEL")
BACKUP_SETTINGS_EXPORT_WHITELIST = BACKUP_SETTINGS_WHITELIST
BACKUP_SETTINGS_IMPORT_WHITELIST = ("TTS_VOICE", "TTS_RATE")

_SRS_COLUMNS = (
    "mastered",
    "mastered_at",
    "correct_count",
    "wrong_count",
    "due_date",
    "interval_days",
    "ease_factor",
    "repetition_count",
)

# 缺列时回落到与建表 DDL 一致的默认值，这样 v1 备份（或手工编辑过的文件）
# 也能被读进来而不是炸掉。
_SRS_DEFAULTS = {
    "mastered": 0,
    "mastered_at": None,
    "correct_count": 0,
    "wrong_count": 0,
    "due_date": None,
    "interval_days": 1,
    "ease_factor": 2.5,
    "repetition_count": 0,
}

_BACKUP_TABLES: Dict[str, Tuple[Tuple[str, ...], Dict[str, Any]]] = {
    "articles": (
        ("id", "title", "source_url", "raw_text", "processed_json", "created_at"),
        {"title": "Untitled", "source_url": "", "raw_text": "", "processed_json": "{}"},
    ),
    "vocab_cards": (
        (
            "id",
            "article_id",
            "word",
            "lemma",
            "pos",
            "gender",
            "plural",
            "cefr_level",
            "definition_zh",
            "sentence_context",
            "created_at",
        )
        + _SRS_COLUMNS
        # ADR-0016 Phase 3 / Task 5：统一池语义列（Phase 1 新增）。此前漏在清单外 ⇒
        # _replace_tables 不写它们，备份→还原往返把 source 静默打回默认 'user'、
        # fsrs_* 清空（数据丢失）。旧备份（无这些键）经 _rows_to_tuples 的
        # ``r.get(c, defaults.get(c))`` 自动落到与建表 DDL 一致的默认值——刻意的向后兼容。
        + ("source", "fsrs_s", "fsrs_d", "fsrs_lapses"),
        dict(
            _SRS_DEFAULTS,
            word="",
            lemma="",
            pos="",
            gender="",
            plural="",
            cefr_level="A1",
            definition_zh="",
            sentence_context="",
            source="user",
            fsrs_s=None,
            fsrs_d=None,
            fsrs_lapses=0,
        ),
    ),
    "grammar_cards": (
        (
            "id",
            "article_id",
            "sentence_context",
            "grammar_name",
            "cefr_level",
            "explanation_zh",
            "rule_formula",
            "examples_zh",
            "corrected_form",
            "error_type",
            "created_at",
        )
        + _SRS_COLUMNS,
        dict(
            _SRS_DEFAULTS,
            sentence_context="",
            grammar_name="",
            cefr_level="A1",
            explanation_zh="",
            rule_formula="",
            examples_zh="",
            corrected_form="",
            error_type="",
        ),
    ),
    "reading_notes": (
        ("id", "article_id", "sentence_id", "selected_text", "color", "note_content", "created_at"),
        {"selected_text": "", "color": "yellow", "note_content": ""},
    ),
    "prep_saved": (
        ("lemma", "praep", "kasus", "saved_at"),
        {"lemma": "", "praep": "", "kasus": "", "saved_at": None},
    ),
    "essays": (
        (
            "id",
            "title",
            "content",
            "analysis_json",
            "cefr_level",
            "error_count",
            "sentence_count",
            "created_at",
            "updated_at",
        ),
        {"title": "", "content": "", "analysis_json": "{}", "cefr_level": "A1", "error_count": 0, "sentence_count": 0},
    ),
    "essay_versions": (
        ("id", "essay_id", "content", "analysis_json", "message", "created_at"),
        {"essay_id": 0, "content": "", "analysis_json": "{}", "message": ""},
    ),
    # 遇见区短文（Task A1 起入同库）；pack_json 存整份 encounter-pack/v1 元数据。
    # 备份/还原缺失该表会让换机还原后遇见区全丢（vault-team 评审 ②）。
    "encounter_texts": (
        ("id", "pack_id", "title", "level", "source", "content", "pack_json", "created_at"),
        {"pack_id": None, "title": "", "level": "A2", "source": "", "content": "", "pack_json": None},
    ),
    # 听力微训成绩（Task 3）：备份/还原缺失该表会让换机还原后听力记录全丢。
    "listen_trials": (
        (
            "id",
            "mode",
            "source_type",
            "source_id",
            "level",
            "total",
            "correct",
            "score",
            "duration_sec",
            "created_at",
        ),
        {
            "mode": "",
            "source_type": "",
            "source_id": 0,
            "level": "",
            "total": 0,
            "correct": 0,
            "score": 0.0,
            "duration_sec": 0,
        },
    ),
    # 长难句精读训练记录（Task 3）：备份/还原缺失该表会让换机还原后训练记录全丢。
    "hard_sentence_trials": (
        (
            "id",
            "source",
            "source_id",
            "sentence_index",
            "level",
            "score",
            "revealed",
            "duration_sec",
            "created_at",
        ),
        {
            "source": "",
            "source_id": 0,
            "sentence_index": 0,
            "level": "",
            "score": 0.0,
            "revealed": 0,
            "duration_sec": 0,
        },
    ),
}

_PROGRESS_TABLES: Dict[str, Tuple[Tuple[str, ...], Dict[str, Any]]] = {
    "study_log": (
        ("id", "event_type", "ref_id", "note", "logged_at"),
        {"event_type": "", "note": ""},
    ),
    "quiz_log": (
        ("id", "card_id", "card_type", "mode", "correct", "attempted_at"),
        {"card_type": "vocab", "mode": "", "correct": 0},
    ),
    "daily_summary": (
        ("date", "cards_added", "cards_mastered", "articles_read", "quiz_sessions", "study_minutes"),
        {"cards_added": 0, "cards_mastered": 0, "articles_read": 0, "quiz_sessions": 0, "study_minutes": 0},
    ),
    "a1_hoeren_records": (
        (
            "id",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
    ),
    "a1_lesen_records": (
        (
            "id",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
    ),
    "exam_trials": (
        (
            "id",
            "level",
            "module",
            "set_id",
            "score_raw",
            "score_official",
            "total_questions",
            "duration_seconds",
            "answers_json",
            "wrong_questions_json",
            "created_at",
        ),
        {
            "level": "A1",
            "module": "hoeren",
            "set_id": 1,
            "score_raw": 0,
            "score_official": 0.0,
            "total_questions": 15,
            "duration_seconds": 0,
            "answers_json": "{}",
            "wrong_questions_json": "[]",
        },
    ),
}


def _rows_to_tuples(
    rows: List[Dict[str, Any]],
    columns: Tuple[str, ...],
    defaults: Dict[str, Any],
) -> List[Tuple[Any, ...]]:
    return [tuple(r.get(c, defaults.get(c)) for c in columns) for r in rows]


def build_backup_payload() -> Dict[str, Any]:
    """组装 v2 备份。local_storage 由前端在 /prepare 时填入——后端读不到浏览器存储。

    P1-2 快照一致性保证：
    在 WAL 模式下，裸 SELECT 循环可能读到跨表时间不一致的混合提交。
    此处对主库与 progress 库分别以 BEGIN DEFERRED 显式包裹读操作并 COMMIT，
    确保单库内部所有表读自同一一致性只读快照。
    （注：SQLite 两独立连接之间物理上无法保证跨库原子性，单库内一致性已极大收敛窗口。）
    """
    conn = get_db()
    try:
        conn.execute("BEGIN DEFERRED")
        try:
            tables = {
                name: [dict(r) for r in conn.execute(f"SELECT * FROM {name}").fetchall()]
                for name in _BACKUP_TABLES
            }
            placeholders = ",".join("?" for _ in BACKUP_SETTINGS_WHITELIST)
            settings = [
                dict(r)
                for r in conn.execute(
                    f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                    BACKUP_SETTINGS_WHITELIST,
                ).fetchall()
            ]
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    pconn = get_progress_db()
    try:
        pconn.execute("BEGIN DEFERRED")
        try:
            progress = {
                name: [dict(r) for r in pconn.execute(f"SELECT * FROM {name}").fetchall()] for name in _PROGRESS_TABLES
            }
            pconn.commit()
        except Exception:
            pconn.rollback()
            raise
    finally:
        pconn.close()

    return {
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "app_settings": settings,
        "local_storage": {},
        **tables,
        **progress,
    }


# prepare→download 之间的暂存槽。单用户本地服务，一份就够。
# 不落盘：避免在磁盘留下用户全库的明文副本，也免去一套失效时会静默的清理逻辑。
# 可接受的失效模式——用户始终不点下载时，一份 JSON 占内存到进程重启。
_pending_backup: Dict[str, Any] = {"token": None, "payload": None, "filename": None, "expires_at": 0.0}

# ── Workbench backup (同理，Android WebView 对 blob: URL 静默失败) ────────
_pending_wb: Dict[str, Any] = {"token": None, "payload": None, "filename": None, "expires_at": 0.0}

# token 有效期。原来是「单次有效」——端点返回前就把槽位清空，这与 WebView 的
# 真实行为冲突：WebView 为了嗅探 Content-Disposition 会先发一次 GET（这一次就把
# token 烧掉），App 侧再发第二次必然 404，落盘的是一个
# {"detail": "备份链接已失效"} 的错误 JSON。用户拿到一份假备份且全程无报错，
# 比直接报错更糟（v4.7.3 修）。改成 TTL 内可重复取后，两次 GET 都拿到真备份。
BACKUP_TOKEN_TTL_SEC = 600


def _issue_pending(pending: Dict[str, Any], payload: Any, filename: str) -> str:
    """装填暂存槽并返回新 token。同一槽位重复调用会让上一个 token 立即作废。"""
    pending.update(
        token=secrets.token_urlsafe(16),
        payload=payload,
        filename=filename,
        expires_at=time.time() + BACKUP_TOKEN_TTL_SEC,
    )
    return pending["token"]  # type: ignore[no-any-return]  # Dict[str, Any] 取值，运行时恒 str


def _take_pending(pending: Dict[str, Any], token: str) -> Tuple[Any, str]:
    """TTL 内可重复取，取用后**不**清除槽位。

    安全性没有因此下降：端点仍受 _require_localhost 保护（只放行 127.0.0.1/::1），
    token 是 128 位随机值，窗口只有 10 分钟。换来的收益是「同一个 URL 被取两次」
    这种完全正常的行为不再把导出变成一份假备份。
    """
    if not pending["token"] or not secrets.compare_digest(str(token), pending["token"]):
        raise HTTPException(404, "备份链接无效，请重新导出")
    if time.time() > pending.get("expires_at", 0.0):
        pending.update(token=None, payload=None, filename=None, expires_at=0.0)
        raise HTTPException(410, f"备份链接已过期（{BACKUP_TOKEN_TTL_SEC // 60} 分钟），请重新导出")
    return pending["payload"], pending["filename"]


def _backup_db_file(src_path: str, dst_path: str) -> None:
    """用 SQLite backup API 把 src_path 导出一致性快照文件 dst_path。

    为什么不用 `shutil.copy2`：WAL 模式下最新提交可能只落在 -wal 里，且本项目
    的 `get_db()` **只结束事务、不 close**（句柄靠循环 GC 释放），库里可能随时挂着
    未关闭的连接。此时直接拷文件会拿到不一致快照；回滚时把主库/-wal 换回去，又会
    让仍在映射旧 WAL 的连接把库读成 `disk I/O error`。backup API 由 SQLite 按页读
    出一个**一致视图**，天然绕开这两点。
    """
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _restore_db_file(snapshot_path: str, dst_path: str) -> None:
    """用 backup API 把快照文件写回活库 dst_path。

    写回走 SQLite 自身的页复制：落在活库当前的日志模式（WAL）里、沿用既有连接，
    因此**不需要**搬/删 -wal/-shm 旁文件，也不会在别处持有连接时把库改成
    `disk I/O error`。busy_timeout 兜住与在途写事务的短暂争用。
    """
    snap = sqlite3.connect(snapshot_path)
    live = sqlite3.connect(dst_path)
    try:
        live.execute("PRAGMA busy_timeout=5000")
        snap.backup(live)
    finally:
        live.close()
        snap.close()


@contextmanager
def _db_snapshot_guard() -> Iterator[None]:
    """还原前给两个库做快照，任一步失败就整体写回。

    delector.db 与 progress.db 是两个**独立** SQLite 文件，无法共处一个事务。
    还原已改成「清库再灌」，所以清空之后、灌完之前若失败（JSON 损坏、磁盘满、
    进程被杀），数据就「已删而备份没进去」——把丢复习进度的 bug 换成丢全部数据的 bug。
    单库事务保护不了跨文件操作，只能在库外再兜一层（两个库各自留一份 backup API 快照）。

    快照/写回均走 SQLite **backup API**（而非文件拷贝）：WAL 模式下文件拷贝既会
    拿到可能陈旧/不一致的快照，也会在库仍挂有连接时把库搞成 `disk I/O error`
    —— 见 `_backup_db_file` / `_restore_db_file` 的说明。

    回滚失败（P0）**不静默**：写回失败意味着库可能停在「已清空、未灌回」的半还原态。
    此时 `finally` 的 rmtree 会把快照目录删掉，之后既无凭据也无退路，故 MUST 在此刻
    打出「哪张库 / 快照在哪 / 为什么失败」，运维据此手工把库捞回来。回滚是**尽力而为**：
    逐个库独立记录，一处失败不阻断其余；但原始异常始终上抛（回滚失败只是附加信息，
    替换主异常会掩盖真正的故障原因）。
    """
    paths = [p for p in (get_db_path(), get_progress_db_path()) if os.path.exists(p)]
    tmpdir = tempfile.mkdtemp(prefix="delector_restore_")
    snapshots: Dict[str, str] = {}
    try:
        for p in paths:
            dst = os.path.join(tmpdir, os.path.basename(p))
            _backup_db_file(p, dst)
            snapshots[p] = dst
        yield
    except BaseException:
        # 连 KeyboardInterrupt 也要回滚——半个还原比不还原更糟；
        # 但回滚不了也必须「如实」留痕，否则这条理由就自己破了。
        for original, snapshot in snapshots.items():
            try:
                _restore_db_file(snapshot, original)
            except Exception as exc:
                logging.getLogger("delector").error(
                    "还原回滚失败：数据库 %s 可能已损坏（已清空但未灌回），"
                    "请用同目录快照 %s 手工恢复后再启动。快照目录 %s 将在本次调用结束后"
                    "被删除，务必先复制出来。回滚错误：%r",
                    original,
                    snapshot,
                    tmpdir,
                    exc,
                    exc_info=True,
                )
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _replace_tables(
    conn: sqlite3.Connection,
    spec: Dict[str, Tuple[Tuple[str, ...], Dict[str, Any]]],
    payload: Dict[str, List[Dict[str, Any]]],
) -> None:
    for name, (columns, defaults) in spec.items():
        # 前向兼容闸（2026-10-15 swarm 审计 P0-1）：payload 里**没有**这张表的键 ⇒
        # 原样保留，而不是「先 DELETE、再零行可灌」。
        # 为什么必须有：调用方各自声明自己认识的键（RestoreReq 是 pydantic 模型，v2 默认
        # extra=ignore ⇒ 前端整份 POST 里**模型没声明的表**会被静默丢弃），而清单
        # （_BACKUP_TABLES/_PROGRESS_TABLES）会随功能增长 ⇒ 没有这道闸时「新表入清单、
        # 请求模型没跟上」的代价是**用户数据被删光且零提示**；有了它退化成「这次没覆盖」。
        # 判据是**键的存在性**而不是 `not rows`：键在场但为空仍是有意覆盖（备份里这张表
        # 就是空的），否则用户删干净的成绩会在还原后复活。
        if name not in payload:
            continue
        conn.execute(f"DELETE FROM {name}")
        rows = payload.get(name) or []
        if not rows:
            continue
        placeholders = ",".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO {name} ({','.join(columns)}) VALUES ({placeholders})",
            _rows_to_tuples(rows, columns, defaults),
        )
