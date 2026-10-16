# -*- coding: utf-8 -*-
"""数据库连接、初始化、CRUD、配置存储、音频缓存管理与备份还原底层。"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Set

from fastapi import HTTPException, Request

# processor 的三个名字在这里**有意保留**（本文件已不再直接使用它们）：计划登记的
# `core ⇄ nlp_engine` 双向耦合（database.py 顶层 import processor）本计划**不解耦**，只登记。
# 它们同时登记进 `__all__`，pyflakes(F401) 据此认定其为有意导入（而非「导入未用」）。
from delector.nlp_engine.processor import PROCESSED_JSON_VERSION, _process_german_text_pure_python, process_german_text

# 本文件现在位于 delector/core/database.py（Phase 1 Task 6 搬入 core/）。DATA_DIR
# 必须指向**仓库根**（delector/ 的父目录），不能落到 delector/ 包目录。用「向上走到
# 不再是 Python 包目录（无 __init__.py）」的方式求仓库根，避免硬编码 dirname 层数 ——
# 下次再搬也不会静默指错。delector.db / progress.db 都挂在它下面，指错一级 = 换个地方
# 重建：桌面端没有 DELECTOR_DATA_DIR 兜底（Android 由 MainActivity 注入），用户看到
# "升级之后数据全没了"，本地测试照样全绿。这条语义由
# tests/test_backend_package_layout.py 钉住，别改回去。
_PKG_DIR = os.path.dirname(__file__)
_REPO_ROOT = _PKG_DIR
while os.path.exists(os.path.join(_REPO_ROOT, "__init__.py")):
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", _REPO_ROOT)
AUDIO_CACHE_DIR = os.path.join(DATA_DIR, ".cache", "audio")
try:
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
except Exception:
    pass

PROGRESS_DB_PATH = os.path.join(DATA_DIR, "progress.db")


def _norm_path(path: str) -> str:
    """把路径规范化到「可直接比较」的形态：abspath（消解相对段）+ normpath（消解分隔符差异）。

    桌面端 `DATA_DIR` 与 `_REPO_ROOT` 在同一进程里可能**字面不同但指向同地**（例如
    `DATA_DIR=/app` vs `_REPO_ROOT=/app/`、或一方带尾斜杠）。迁移闸的唯一依据是
    「两个路径是否真的不同」，故必须规范化后再比，绝不字符串直比。
    """
    return os.path.normpath(os.path.abspath(path))


def preflight_data_dir(data_dir: str, repo_root: str) -> None:
    """启动自检：数据还在旧位置 ⇒ 抛异常拒绝建空库（fail-loud）。纯函数、只读、不碰 DB。

    事故背景
    --------
    `docker-compose.yml` 早期把卷挂成**单文件** `./delector.db:/app/delector.db`，后改为
    **目录** `./data:/app/data` 并无条件设 `DELECTOR_DATA_DIR=/app/data`。而
    `get_db_path()` 优先读 `DATABASE_PATH`、其次 `DATA_DIR/delector.db` ⇒ 存量用户升级后
    旧库**不再被挂进容器**，`init_db()` 只会建一套**空 schema**。用户看到的是「功能全正常、
    数据全空」的应用，且全仓无任何探测/告警/迁移说明。

    为何抛异常而不「告警后继续」
    --------------------------
    静默空库比响亮崩溃危险得多：空库一旦建出，用户的诊断直觉是「数据丢了」，进而做
    「恢复出厂」这类**不可逆**操作；而审计已核实数据文件**根本没被删除**，只差一次 `cp`。
    宁可见的 crash-loop，也不要静默空库。

    判据（四者**同时**成立才抛）
    ----------------------------
    1. 新位置 `data_dir/delector.db` **不是**已存在的**非空**库文件（`os.path.isfile` 且
       `size > 0`）；
    2. 旧位置 `repo_root/delector.db` **是**已存在的库文件（`os.path.isfile`；size 判据见条件③）；
    3. 该旧文件 `size > 0`（size==0 是初始化残留的空壳，**不算数据** ⇒ 诚实留空，不拦启动）；
    4. 两个路径**规范化后不同**（桌面端 `DATA_DIR == _REPO_ROOT`，故**绝不误报**）。

    为何条件①也要求**非空**（size 对称化）
    --------------------------------------
    「0 字节是初始化残留的空壳，**不算数据**」这条标准在**两个位置**都成立，故必须**对称**：
    旧版只在旧位置（条件③）做 size 判断，条件① 只看 `isfile` ⇒ 一旦新位置落一个 0 字节
    `delector.db`（上一次启动在建表前被杀、或人为 `touch` 的残留），而旧位置恰有真实数据，
    条件① 就会提前 `return`，四条件**全不成立**、闸**静默放行** —— 程序随即在新位置重建
    空库，正是本闸要防的「静默空库」。条件① 与条件③ 用同一把尺（非空才算数据）后，
    「新位置空壳 + 旧位置有真实数据」这一组合会被正确地拦下。

    为何用 `isfile` 而非 `exists`（且 ①/② 对称）
    -------------------------------------------------
    旧版 compose 挂的是**单文件** `./delector.db:/app/delector.db`；宿主文件不存在时
    Docker 会**自动建一个同名目录** `./delector.db/`，它又被 `Dockerfile` 的 `COPY . .`
    带进镜像落在 `/app/delector.db`。Linux 下目录 `st_size == 4096 > 0`，于是
    `exists` + `getsize > 0` 的判据会**四条件全中**：目录里根本没有数据，用户却被拦死，
    而消息里的 `cp /app/delector.db /app/data/delector.db` 还会报 `omitting a directory`。
    `isfile` 对目录返回 `False`，让「有目录残留」与「有库数据」彻底分开。

    No-Silent-Write：本函数**只读不写**，修数据由用户照消息里的 `cp` 自己做——启动路径上
    不做用户没要求的写操作。Idempotent：正常路径零输出、零日志，重复启动不重复报警。
    """
    legacy_db = os.path.join(data_dir, "delector.db")
    if os.path.isfile(legacy_db) and os.path.getsize(legacy_db) > 0:
        return  # 新位置已有**非空**库：数据在位，闸无话可说（size 判据与条件③对称）
    old_db = os.path.join(repo_root, "delector.db")
    if not os.path.isfile(old_db):
        return  # 旧位置也没有库文件：全新安装（或只剩 Docker 建的同名目录），诚实留空
    if _norm_path(data_dir) == _norm_path(repo_root):
        # 条件④ 的**净结果**在当前守卫顺序下与条件③冗余，但它**不是**"永远到不了这一行"：
        # 两路径同地（`data_dir == repo_root`）时，①/② 看的是**同一个** `delector.db`，
        # 能否走到本行取决于该共享文件是否 0 字节 ——
        #   · 共享文件**非空** ⇒ ① 因 `size > 0` 提前 `return`，根本到不了这里；
        #   · 共享文件是 **0 字节** ⇒ ① 因 `size == 0` **不**返回，② 因文件存在也**不**返回，
        #     于是**真的到达**本行并由它 `return`（这正是条件① 加 `size > 0` 之前不存在的路径）。
        # 此时条件③ 同样会对 0 字节 `return` ⇒ 本守卫"净结果冗余"的结论仍成立（能到这行的
        # 场景，③ 本就会放行，两者结论一致）；但旧注释里"①（无库）与 ②（有库）互斥"的论断
        # 已被 `size > 0` **证伪**，故删除。
        # 判据明文要求四条件并列，故**保留**该守卫 —— 未来若重构调整守卫顺序（例如把
        # ② 挪到 ① 之前），它是防止闸在「两路径同地」时误报的唯一拦阻，不得删。
        return  # 桌面端默认：两路径同地，绝不误报
    if os.path.getsize(old_db) <= 0:
        return  # 0 字节空壳不算数据，不拦启动

    new_abs = os.path.abspath(legacy_db)
    old_abs = os.path.abspath(old_db)
    message = (
        "检测到数据目录迁移未完成：数据库文件仍留在旧位置，但程序已指向新位置。\n"
        "继续启动会在新位置重建一个**空库**（功能正常、数据全空），因此已拒绝启动。\n"
        "数据文件本身**没有被删除**，照下面这条命令复制过去再重启即可恢复：\n"
        f'  cp "{old_abs}" "{new_abs}"\n'
        f"  旧位置（数据在此）：{old_abs}\n"
        f"  新位置（程序要读）：{new_abs}\n"
        "注意：上面这条 cp 的两个路径是**容器内**的绝对路径，请在容器里执行（或用\n"
        "`docker compose cp`）；宿主机侧怎么搬见 README「数据目录与旧版迁移」一节。"
    )
    logging.getLogger("delector").error(message)
    raise RuntimeError(message)


def get_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("DATABASE_PATH", os.path.join(DATA_DIR, "delector.db"))


def get_progress_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("PROGRESS_DB_PATH", PROGRESS_DB_PATH)


def _configure_sqlite_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    try:
        # WAL：写不阻塞读、崩溃恢复更稳；与 synchronous=NORMAL 是官方推荐组合。
        # 注意：WAL 会在库文件旁生成 -wal/-shm；容器部署须挂**目录**而非单文件
        # （见 docker-compose.yml 的 ./data 挂载），否则尾写落在容器层。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(db_path))
    return _configure_sqlite_conn(conn)


_INITIALIZED_PROGRESS_DBS: Set[str] = set()


def get_progress_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = get_progress_db_path(db_path)
    if target_path not in _INITIALIZED_PROGRESS_DBS:
        init_progress_db(target_path)
    conn = sqlite3.connect(target_path)
    return _configure_sqlite_conn(conn)


# ── init_progress_db 已搬入 `delector/core/db/schema.py`（database-split / Task 3）。
#    本模块在该文件末尾逐名再导出，公开面零变化；`get_progress_db` 仍按名调用它。


def log_study_event(
    event_type: str,
    ref_id: Optional[int] = None,
    note: str = "",
    minutes: int = 0,
    db_path: Optional[str] = None,
) -> None:
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        with db_progress_conn(db_path) as conn:
            conn.execute(
                "INSERT INTO study_log (event_type, ref_id, note) VALUES (?, ?, ?)", (event_type, ref_id, note)
            )
            conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
            if event_type == "add_card":
                conn.execute(
                    "UPDATE daily_summary SET cards_added = cards_added + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(1, minutes), today),
                )
            elif event_type == "master_card":
                conn.execute(
                    "UPDATE daily_summary SET cards_mastered = cards_mastered + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(1, minutes), today),
                )
            elif event_type == "read_article":
                conn.execute(
                    "UPDATE daily_summary SET articles_read = articles_read + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(3, minutes), today),
                )
            elif event_type == "quiz_session":
                conn.execute(
                    "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(2, minutes), today),
                )
            elif event_type in ("a1_hoeren", "a1_lesen"):
                conn.execute(
                    "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, "
                    "study_minutes = study_minutes + ? WHERE date = ?",
                    (max(2, minutes), today),
                )
    except Exception as e:
        print(f"[Warn] Failed to log study event: {e}")


# ── init_db 已搬入 `delector/core/db/schema.py`（database-split / Task 3）：建表 +
#    索引 + 现有库的内联列迁移（ALTER TABLE）。本模块在该文件末尾逐名再导出。


# ── get_setting / set_setting 已搬入 `delector/core/db/settings.py`（database-split /
#    Task 3）。本模块在该文件末尾逐名再导出，公开面零变化。


def _close_db_conn(conn: sqlite3.Connection) -> None:
    """确定性关闭 get_db 打开的连接。

    裸 `with conn`（sqlite3.Connection 自带的上下文管理）只提交/回滚事务并不会
    close：sqlite3.Connection 会因内部 statement 缓存形成引用环，文件句柄要等
    循环 GC 才释放。Windows 上 clean_db 的 os.remove 靠 busy 重试可绕过，但正确
    做法是主动 close，不依赖 GC 时机——`db_conn`/`db_progress_conn` 已经做了。
    """
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def db_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """`with db_conn(...) as conn:` —— 语义与旧 `with get_db(...) as conn:` 等价
    （成功 commit / 异常 rollback），但 finally 确定性 close，不再依赖循环 GC。
    """
    conn = get_db(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _close_db_conn(conn)


@contextmanager
def db_progress_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """同 db_conn，面向 progress 库。注意 init_progress_db 内部不得使用本函数。"""
    conn = get_progress_db(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _close_db_conn(conn)


def get_wb_state(db_path: Optional[str] = None) -> Dict[str, Any]:
    """读 workbench 背词进度 server 镜像；无记录或解析失败一律返回 {}。"""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT payload FROM wb_state WHERE id = 1").fetchone()
    finally:
        _close_db_conn(conn)
    if not row:
        return {}
    try:
        data = json.loads(row["payload"])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_wb_state(payload: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """单行 upsert workbench 背词进度镜像（id 恒为 1），返回本次写入的 updated_at。

    ADR-0016 Phase 3 / Task 2：写镜像 blob 的同时把 wb 快照幂等投影进统一池
    ``vocab_cards``（``project_wb_deck``）。两者落在**同一个** ``with conn:`` 事务内：
    投影失败 ⇒ 整体回滚，blob 也不写（无「半写」，Migration-Idempotency §2）。
    投影异常**不被吞**，向上冒泡给调用方（让事务回滚并把错误暴露出来）。
    """
    updated_at = datetime.now().isoformat()
    text = json.dumps(payload, ensure_ascii=False)
    conn = get_db(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO wb_state (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
            """,
                (text, updated_at),
            )
            # 惰性导入（本仓约定：database 不顶层 import lexicon 主干）；投影不 commit，
            # 复用同一连接与事务。投影抛错 ⇒ with conn 回滚，blob 与投影一起回滚。
            from delector.core.vocab_pool import project_wb_deck

            project_wb_deck(conn, payload)
    finally:
        _close_db_conn(conn)
    return updated_at


# ── get_wb_sync_key / regenerate_wb_sync_key / verify_wb_key / get_effective_api_* 已搬入
#    `delector/core/db/settings.py`（database-split / Task 3）。本模块在文件末尾再导出。
# ── 备份/还原切片显式 re-export（database-split / Task 2）──────────────────────────
# 备份 / 还原 / 白名单整组已搬入 `delector/core/db/backup.py`（纯移动）。此处**逐名**再导出，
# 保持公开面零变化 —— 既有 `from delector.core.database import <名字>` 的调用点一行不改。
# 用逐名的 `from ... import (...)`（**不用 `import *`**，不吞名字）；再导出的名字同时登记进
# 本模块的 `__all__`，pyflakes(F401) 据此把它们认定为有意再导出（而非「导入未用」）。
#
# 位置说明：`db/backup.py` 需要 `get_db` / `get_progress_db` / `get_db_path` /
# `get_progress_db_path`（仍在本模块，Task 3 才搬走），故本 import MUST 排在它们的定义
# （上方）之后，循环导入才成立 —— 与 `delector/server.py` 的分节 import 同理。
from delector.core.db.backup import (  # noqa: E402  # 需排在连接访问器定义之后，见上
    _BACKUP_TABLES,
    _PROGRESS_TABLES,
    _SRS_COLUMNS,
    _SRS_DEFAULTS,
    BACKUP_FORMAT_VERSION,
    BACKUP_SETTINGS_EXPORT_WHITELIST,
    BACKUP_SETTINGS_IMPORT_WHITELIST,
    BACKUP_SETTINGS_WHITELIST,
    BACKUP_TOKEN_TTL_SEC,
    _backup_db_file,
    _db_snapshot_guard,
    _issue_pending,
    _pending_backup,
    _pending_wb,
    _replace_tables,
    _restore_db_file,
    _rows_to_tuples,
    _take_pending,
    build_backup_payload,
)

# ── 文章 / 遇见 / Anki / 音频缓存切片显式 re-export（database-split / Task 4）──────────
# 文章与遇见区短文（`articles` / `encounter_texts`）读写、预置文章与遇见区种子、Anki 牌组
# 导出、音频缓存信息与清理整组已搬入 `delector/core/db/content.py`（纯移动）。此处**逐名**
# 再导出，保持公开面零变化 —— 既有 `from delector.core.database import <名字>` 的调用点一行
# 不改；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
#
# 位置说明：`db/schema.py` 需要本片的 `seed_preset_articles`（`init_db` 末尾调用），而 schema
# 的 re-export 在下方，故本 import MUST 排在它之前；本片自身只依赖 `db_conn` / `get_db_path` /
# `AUDIO_CACHE_DIR` / `_PKG_DIR`（均已在上方定义）、`db/settings.py` 的 `set_setting` 与
# `nlp_engine.processor` 的分析函数。
from delector.core.db.content import (  # noqa: E402  # 需排在 schema re-export 之前，见上
    _ENCOUNTER_SEED_VERSION_KEY,
    _PRESET_PROCESSED_FILENAME,
    A1_VOCAB_MODEL,
    GRAMMAR_MODEL,
    PRESET_ARTICLES,
    PRESET_PROCESSED_SCHEMA,
    PRESET_SEED_VERSION,
    VOCAB_MODEL,
    _anki_esc,
    _backfill_pack_lemma_seq,
    _grammar_anki_note,
    _load_preset_processed,
    _preset_processed_entries,
    _preset_processed_json_lite,
    _preset_processed_loaded,
    _read_preset_seed_version,
    _reset_preset_processed_cache,
    _seed_or_backfill_preset_pack,
    _try_seed_or_backfill_preset_pack,
    _vocab_anki_note,
    _warn_preset_processed,
    create_encounter_text,
    export_a1_anki_deck,
    export_anki_deck,
    get_cache_info,
    get_encounter_text,
    import_encounter_pack,
    ingest_article,
    list_encounter_texts,
    preset_processed_data_path,
    preset_processed_json,
    preset_text_hash,
    prune_audio_cache,
    seed_preset_articles,
    seed_preset_encounter_texts,
)

# ── 建表/迁移切片显式 re-export（database-split / Task 3）────────────────────────
# 建表 / 索引 / 内联列迁移整组已搬入 `delector/core/db/schema.py`（纯移动），含
# `migrate_a1_records_to_exam_trials`（与建表函数同模块，见 schema.py 模块 docstring）。
# 同样逐名再导出，公开面零变化。
#
# 位置说明：`db/schema.py` 需要 `db_conn` / `_close_db_conn` / `_configure_sqlite_conn` /
# `_INITIALIZED_PROGRESS_DBS` / `DATA_DIR` / `_REPO_ROOT` / `get_db_path` /
# `get_progress_db_path` / `preflight_data_dir` 与**预置种子** `seed_preset_articles`
# （Task 4 已随 `db/content.py` 搬走，此处经上方 re-export 得名），故本 import MUST 排在它们全部定义之后。
from delector.core.db.schema import (  # noqa: E402  # 需排在上述依赖定义之后，见上
    init_db,
    init_progress_db,
    migrate_a1_records_to_exam_trials,
)

# ── 设置/鉴权切片显式 re-export（database-split / Task 3）──────────────────────────
# 设置持久化与鉴权整组已搬入 `delector/core/db/settings.py`（纯移动）。此处**逐名**再导出，
# 保持公开面零变化 —— 既有 `from delector.core.database import <名字>` 的调用点一行不改。
# 与 backup 同规矩：用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）；再导出
# 的名字已在 `__all__` 登记，pyflakes(F401) 据此认定为有意再导出（而非「导入未用」）。
#
# 位置说明：`db/settings.py` 需要 `db_conn`（仍在本模块），故本 import MUST 排在其定义之后，
# 循环导入才成立。
from delector.core.db.settings import (  # noqa: E402  # 需排在连接访问器定义之后，见上
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    get_setting,
    get_wb_sync_key,
    regenerate_wb_sync_key,
    set_setting,
    verify_wb_key,
)


def _require_localhost(request: Request) -> None:
    """敏感接口仅允许本机访问。

    桌面端有意绑 0.0.0.0（start.py 的 get_bind_host，同 Wi-Fi 的手机/平板可读文章），
    但「导出整个数据库」「清空数据库再灌」和「改写 API Key / base_url」从来不该被局域网触达 ——
    后者在改成真覆盖语义后等于「局域网内一个 POST 清空你的数据」或「悄悄改写你的模型网关」。
    读文章期望被共享，备份与设置不期望，所以闸下在端点粒度而不是改绑定地址。

    接受 127.0.0.1、::1、localhost 与等价的 IPv4-mapped 回环 ::ffff:127.0.0.1；
    无法确认来源（client 为 None 或 host 缺失/空）时拒绝，不默认放行。
    """
    host = ""
    if request.client is not None:
        host = getattr(request.client, "host", None) or ""
    if host not in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        raise HTTPException(403, "该接口仅允许本机访问")


def get_prep_saved(db_path: Optional[str] = None) -> Set[str]:
    """返回所有已入卡的 (lemma, praep, kasus) 三元组 key 集合。"""
    with db_conn(db_path) as conn:
        rows = conn.execute("SELECT lemma, praep, kasus FROM prep_saved").fetchall()
        return {f"{r['lemma']}|{r['praep']}|{r['kasus']}" for r in rows}


def add_prep_saved(lemma: str, praep: str, kasus: str, db_path: Optional[str] = None) -> None:
    """记录一条搭配已入卡。幂等：重复插入被主键忽略。"""
    with db_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO prep_saved (lemma, praep, kasus) VALUES (?, ?, ?)",
            (lemma, praep, kasus),
        )


# ── 考试 / 训练记录切片显式 re-export（database-split / Task 4）────────────────────────
# 泛化模考（exam_trials）、A1 双模块透传、听力微训（listen_trials）、长难句精读
# （hard_sentence_trials）整组已搬入 `delector/core/db/records.py`（纯移动）。此处**逐名**
# 再导出，保持公开面零变化；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
from delector.core.db.records import (  # noqa: E402  # 需排在连接访问器 / log_study_event 定义之后
    get_a1_hoeren_history,
    get_a1_lesen_history,
    get_exam_history,
    list_hard_sentence_trials,
    list_listen_trials,
    record_a1_hoeren_trial,
    record_a1_lesen_trial,
    record_exam_trial,
    record_hard_sentence_trial,
    record_listen_trial,
)

# ── 词汇契约 / 富字段切片显式 re-export（database-split / Task 4）──────────────────────
# A1 工作台词库加载与缓存、12 字段词对象契约、reader 生词富字段回填与对外取词入口
# （`get_vocab_by_cefr`）整组已搬入 `delector/core/db/vocab.py`（纯移动）。此处**逐名**
# 再导出，保持公开面零变化；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
#
# 词库缓存 `_A1_WORKBENCH_WORDS_CACHE` / `_A2_VOCAB_CACHE` 随本片同迁、全仓仅此一份：
# 这里只再导出**同名绑定**（同一对象），**不在本模块另建缓存**。
from delector.core.db.vocab import (  # noqa: E402  # 需排在连接访问器定义之后
    _A1_ARTICLE_PREFIXES,
    _A1_WORKBENCH_WORDS_CACHE,
    _A2_VOCAB_CACHE,
    _READER_ARTICLE_RE,
    GENDER_ARTICLE_MAP,
    _a1_noun_meta,
    _a1_workbench_row,
    _contract_from_a1_row,
    _contract_from_core_entry,
    _contract_item,
    _load_a1_workbench_dict_module,
    _load_a1_workbench_words,
    _load_a2_vocab_words,
    _normalize_a1_headword,
    _reader_lemma_key,
    _reader_rich_fields,
    _reset_a1_workbench_cache,
    format_vocab_headword,
    get_vocab_by_cefr,
)


def upsert_corpus_syntax_stats(article_id: int, stats: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """插入或更新单篇文献的 24 维句法雷达聚合统计数据。"""
    try:
        sent_count = int(stats.get("sent_count", 0))
        avg_clause_depth = float(stats.get("avg_clause_depth", 0.0))
        passive_rate = float(stats.get("passive_rate", 0.0))
        konjunktiv_rate = float(stats.get("konjunktiv_rate", 0.0))
        vl_rate = float(stats.get("vl_rate", 0.0))
        with db_progress_conn(db_path) as conn:
            conn.execute(
                """
                INSERT INTO corpus_syntax_stats (
                    article_id, sent_count, avg_clause_depth, passive_rate, konjunktiv_rate, vl_rate, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(article_id) DO UPDATE SET
                    sent_count=excluded.sent_count,
                    avg_clause_depth=excluded.avg_clause_depth,
                    passive_rate=excluded.passive_rate,
                    konjunktiv_rate=excluded.konjunktiv_rate,
                    vl_rate=excluded.vl_rate,
                    analyzed_at=CURRENT_TIMESTAMP
                """,
                (article_id, sent_count, avg_clause_depth, passive_rate, konjunktiv_rate, vl_rate),
            )
        return True
    except Exception as e:
        print(f"[Warn] Failed to upsert corpus syntax stats: {e}")
        return False


def get_all_corpus_syntax_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """查询全量文献的句法雷达统计均值。"""
    try:
        with db_progress_conn(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), AVG(sent_count), AVG(avg_clause_depth), AVG(passive_rate), "
                "AVG(konjunktiv_rate), AVG(vl_rate) FROM corpus_syntax_stats"
            ).fetchone()
            if row:
                count, avg_sc, avg_cd, avg_pr, avg_kr, avg_vr = row
                return {
                    "total_articles": count or 0,
                    "avg_sent_count": round(float(avg_sc or 0.0), 2),
                    "avg_clause_depth": round(float(avg_cd or 0.0), 2),
                    "avg_passive_rate": round(float(avg_pr or 0.0), 4),
                    "avg_konjunktiv_rate": round(float(avg_kr or 0.0), 4),
                    "avg_vl_rate": round(float(avg_vr or 0.0), 4),
                }
    except Exception as e:
        print(f"[Warn] Failed to get all corpus syntax stats: {e}")
    return {
        "total_articles": 0,
        "avg_sent_count": 0.0,
        "avg_clause_depth": 0.0,
        "avg_passive_rate": 0.0,
        "avg_konjunktiv_rate": 0.0,
        "avg_vl_rate": 0.0,
    }


__all__ = [
    "DATA_DIR",
    "AUDIO_CACHE_DIR",
    "PROGRESS_DB_PATH",
    "get_db_path",
    "get_progress_db_path",
    "get_db",
    "get_progress_db",
    "init_progress_db",
    "log_study_event",
    "init_db",
    "get_setting",
    "set_setting",
    "get_wb_state",
    "save_wb_state",
    "get_wb_sync_key",
    "regenerate_wb_sync_key",
    "verify_wb_key",
    "list_encounter_texts",
    "get_encounter_text",
    "create_encounter_text",
    "import_encounter_pack",
    "get_effective_api_key",
    "get_effective_api_base_url",
    "get_effective_api_model",
    "PRESET_ARTICLES",
    "ingest_article",
    "seed_preset_articles",
    "seed_preset_encounter_texts",
    "VOCAB_MODEL",
    "GRAMMAR_MODEL",
    "A1_VOCAB_MODEL",
    "export_anki_deck",
    "export_a1_anki_deck",
    "get_cache_info",
    "prune_audio_cache",
    "BACKUP_FORMAT_VERSION",
    "BACKUP_SETTINGS_WHITELIST",
    "BACKUP_SETTINGS_EXPORT_WHITELIST",
    "BACKUP_SETTINGS_IMPORT_WHITELIST",
    "_BACKUP_TABLES",
    "_PROGRESS_TABLES",
    "_SRS_COLUMNS",
    "_SRS_DEFAULTS",
    "_require_localhost",
    "_rows_to_tuples",
    "build_backup_payload",
    "_pending_backup",
    "_pending_wb",
    "BACKUP_TOKEN_TTL_SEC",
    "_issue_pending",
    "_take_pending",
    "_backup_db_file",
    "_restore_db_file",
    "_db_snapshot_guard",
    "_replace_tables",
    "get_prep_saved",
    "add_prep_saved",
    "record_a1_hoeren_trial",
    "get_a1_hoeren_history",
    "record_a1_lesen_trial",
    "get_a1_lesen_history",
    "record_exam_trial",
    "get_exam_history",
    "migrate_a1_records_to_exam_trials",
    "record_listen_trial",
    "list_listen_trials",
    "record_hard_sentence_trial",
    "list_hard_sentence_trials",
    "get_vocab_by_cefr",
    "upsert_corpus_syntax_stats",
    "get_all_corpus_syntax_stats",
    "_ENCOUNTER_SEED_VERSION_KEY",
    "_PRESET_PROCESSED_FILENAME",
    "PRESET_PROCESSED_SCHEMA",
    "PRESET_SEED_VERSION",
    "_anki_esc",
    "_backfill_pack_lemma_seq",
    "_grammar_anki_note",
    "_load_preset_processed",
    "_preset_processed_entries",
    "_preset_processed_json_lite",
    "_preset_processed_loaded",
    "_read_preset_seed_version",
    "_reset_preset_processed_cache",
    "_seed_or_backfill_preset_pack",
    "_try_seed_or_backfill_preset_pack",
    "_vocab_anki_note",
    "_warn_preset_processed",
    "preset_processed_data_path",
    "preset_processed_json",
    "preset_text_hash",
    "_A1_ARTICLE_PREFIXES",
    "_A1_WORKBENCH_WORDS_CACHE",
    "_A2_VOCAB_CACHE",
    "_READER_ARTICLE_RE",
    "GENDER_ARTICLE_MAP",
    "_a1_noun_meta",
    "_a1_workbench_row",
    "_contract_from_a1_row",
    "_contract_from_core_entry",
    "_contract_item",
    "_load_a1_workbench_dict_module",
    "_load_a1_workbench_words",
    "_load_a2_vocab_words",
    "_normalize_a1_headword",
    "_reader_lemma_key",
    "_reader_rich_fields",
    "_reset_a1_workbench_cache",
    "format_vocab_headword",
    # 登记的双向耦合：database 顶层仍 import processor（本计划不解耦，见文件头注释），
    # 这三个名字保持可经 `database.X` 取用。
    "PROCESSED_JSON_VERSION",
    "_process_german_text_pure_python",
    "process_german_text",
]
