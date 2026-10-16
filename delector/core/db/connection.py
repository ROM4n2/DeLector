# -*- coding: utf-8 -*-
r"""连接访问器、库文件 / 数据目录路径与库级基础读写（database-split / Task 5）。

本模块由 `delector/core/database.py` 按职责切分搬出（纯移动）。`database.py` 逐名
`from delector.core.db.connection import X` 再导出，公开面零变化。

本片承载的整组职责：
- 数据目录 / 路径常量：`_PKG_DIR` / `_REPO_ROOT` / `DATA_DIR` / `AUDIO_CACHE_DIR` /
  `PROGRESS_DB_PATH`；路径解析：`_norm_path` / `get_db_path` / `get_progress_db_path`
- 启动迁移闸：`preflight_data_dir`（纯只读自检，不做任何写操作）
- 连接访问器：`_configure_sqlite_conn` / `get_db` / `get_progress_db` /
  `_close_db_conn` / `db_conn` / `db_progress_conn`
- 库级基础读写（进度事件 / workbench 镜像 / 搭配已入卡 / 句法雷达统计）：
  `log_study_event` / `get_wb_state` / `save_wb_state` / `get_prep_saved` /
  `add_prep_saved` / `upsert_corpus_syntax_stats` / `get_all_corpus_syntax_stats`

模块级可变状态（`_INITIALIZED_PROGRESS_DBS`：progress 库「已建表」去重集合）随
`get_progress_db` 同迁，全仓**仅此一份**（不分裂成两份副本）。

循环导入纪律：本模块是 `delector/core/db/` 里最底层的一片，**顶层只依赖标准库**，
不 import `database` 也不 import 任何兄弟切片；`database.py` 在 re-export 其它切片**之前**
先 re-export 本片，各切片才能经 `database` 拿到连接访问器。
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Set

# 本文件现在位于 delector/core/db/connection.py（database-split / Task 5 搬入 db/）。
# DATA_DIR 必须指向**仓库根**（delector/ 的父目录），不能落到 delector/ 包目录。用
# 「向上走到不再是 Python 包目录（无 __init__.py）」的方式求仓库根，避免硬编码
# dirname 层数 —— 下次再搬（含本轮搬进 db/）也**不会静默指错**。delector.db /
# progress.db 都挂在它下面，指错一级 = 换个地方重建：桌面端没有 DELECTOR_DATA_DIR 兜底
# （Android 由 MainActivity 注入），用户看到 "升级之后数据全没了"，本地测试照样全绿。
# 这条语义由 tests/test_backend_package_layout.py 钉住，别改回去。
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
        # 惰性导入（循环导入纪律）：`init_progress_db` 住 Task-3 切出的 `db/schema.py`，
        # 而 schema 顶层 import `database`（再导出）；本模块是最底层的 connection 片，
        # 顶层 import schema 会成环 ⇒ 仅在真正需要建库时按名取用（与 `save_wb_state`
        # 惰性取 `vocab_pool.project_wb_deck` 同款）。行为不变：原实现在 `database.py`
        # 内也是「运行时按名解析到 schema 的 `init_progress_db`」。
        from delector.core.db.schema import init_progress_db

        init_progress_db(target_path)
    conn = sqlite3.connect(target_path)
    return _configure_sqlite_conn(conn)


# ── init_progress_db 已搬入 `delector/core/db/schema.py`（database-split / Task 3）。
#    本片只经上面的惰性导入按名调用它，公开面不变。


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
#    索引 + 现有库的内联列迁移（ALTER TABLE）。本模块不含该职责。


# ── get_setting / set_setting 已搬入 `delector/core/db/settings.py`（database-split /
#    Task 3）。本模块不含该职责。


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
#    `delector/core/db/settings.py`（database-split / Task 3）。


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
