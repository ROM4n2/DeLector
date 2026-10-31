# -*- coding: utf-8 -*-
r"""`delector/core/database.py` 的**纯 façade**（database-split / Task 5 收口）。

本模块已**不再含任何数据层实现**：切分出的六个切片 + 本轮收口的连接/路径片全部住
`delector/core/db/*`，此处只做**逐名显式再导出**（**不用 `import *`**，不吞名字），
使既有 `import delector.core.database as database` 与
`from delector.core.database import <名字>` 的调用点**一行不改**（公开面零变化）。

切片去向：
- `delector.core.db.connection` ← 连接访问器 / 库文件·数据目录路径 / preflight 迁移闸 /
  库级基础读写（进度事件、workbench 镜像、搭配已入卡、句法雷达统计）（Task 5）
- `delector.core.db.backup`     ← 备份 / 还原 / 白名单（含两份 pending 暂存槽）（Task 2）
- `delector.core.db.settings`   ← 设置持久化与鉴权（Task 3）
- `delector.core.db.schema`     ← 建表 / 索引 / 内联列迁移（Task 3）
- `delector.core.db.content`    ← 文章 / 遇见区种子 / Anki 导出 / 音频缓存（Task 4）
- `delector.core.db.records`    ← 考试 / 训练记录读写（Task 4）
- `delector.core.db.vocab`      ← 词汇契约与富字段（含词库缓存）（Task 4）

**唯一仍住本模块的实现**：`_require_localhost` —— 它是 **HTTP 关注点**，塞进持久层包
（`delector/core/db/`）会制造错误的语义分层，故**保持原位**；登记为「将来可搬去
`delector/core/net_guard.py` 的候选」（本轮 out of scope，属命名 / 分层整理）。
"""

from fastapi import HTTPException, Request

# ── 连接 / 路径切片显式 re-export（database-split / Task 5）──────────────────────────
# 连接访问器、库文件 / 数据目录路径常量、preflight 迁移闸与库级基础读写整组已搬入
# `delector/core/db/connection.py`（纯移动）。此处**逐名**再导出；再导出的名字同时登记进
# 本模块 `__all__`，pyflakes(F401) 据此认定为有意再导出（而非「导入未用」）。
#
# 位置说明：本 import MUST 排在**所有切片 re-export 之前** —— 各切片（backup / content /
# schema / settings / records / vocab）都经 `from delector.core.database import db_conn ...`
# 取用连接访问器，只有本片先把这些名字绑进 database 命名空间，切片 import 才成立
# （循环导入纪律，与 `db/backup.py` 的注释同款）。
from delector.core.db.connection import (
    _INITIALIZED_PROGRESS_DBS,
    _PKG_DIR,
    _REPO_ROOT,
    AUDIO_CACHE_DIR,
    DATA_DIR,
    PROGRESS_DB_PATH,
    _close_db_conn,
    _configure_sqlite_conn,
    _norm_path,
    add_prep_saved,
    db_conn,
    db_progress_conn,
    get_all_corpus_syntax_stats,
    get_db,
    get_db_path,
    get_prep_saved,
    get_progress_db,
    get_progress_db_path,
    get_wb_state,
    log_study_event,
    preflight_data_dir,
    save_wb_state,
    upsert_corpus_syntax_stats,
)


def _require_localhost(request: Request) -> None:
    """敏感接口仅允许本机访问。

    桌面端有意绑 0.0.0.0（start.py 的 get_bind_host，同 Wi-Fi 的手机/平板可读文章），
    但「导出整个数据库」「清空数据库再灌」和「改写 API Key / base_url」从来不该被局域网触达 ——
    后者在改成真覆盖语义后等于「局域网内一个 POST 清空你的数据」或「悄悄改写你的模型网关」。
    读文章期望被共享，备份与设置不期望，所以闸下在端点粒度而不是改绑定地址。

    接受 127.0.0.1、::1、localhost 与等价的 IPv4-mapped 回环 ::ffff:127.0.0.1；
    无法确认来源（client 为 None 或 host 缺失/空）时拒绝，不默认放行。

    ⚠️ 本函数**刻意留在 façade**：它是 HTTP 关注点，不属于持久层。将来整体搬去
    `delector/core/net_guard.py` 是命名 / 分层整理（本轮 out of scope）。
    """
    host = ""
    if request.client is not None:
        host = getattr(request.client, "host", None) or ""
    if host not in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        raise HTTPException(403, "该接口仅允许本机访问")


# ── 备份/还原切片显式 re-export（database-split / Task 2）──────────────────────────
# 备份 / 还原 / 白名单整组已搬入 `delector/core/db/backup.py`（纯移动）。此处**逐名**再导出，
# 保持公开面零变化 —— 既有 `from delector.core.database import <名字>` 的调用点一行不改。
# 用逐名的 `from ... import (...)`（**不用 `import *`**，不吞名字）。
from delector.core.db.backup import (  # noqa: E402, I001  # 需排在连接访问器 re-export 之后
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
# 再导出，保持公开面零变化；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
#
# 位置说明：`db/schema.py` 需要本片的 `seed_preset_articles`（`init_db` 末尾调用），故本片
# MUST 排在 schema re-export 之前。
from delector.core.db.content import (  # noqa: E402, I001  # 需排在 schema re-export 之前，见上
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
#
# 位置说明：`db/schema.py` 需要连接访问器（已在上方绑定）与**预置种子**
# `seed_preset_articles`（Task 4 已随 `db/content.py` 搬走、此处经上方 content re-export 得名），
# 故本 import MUST 排在 content re-export 之后。
from delector.core.db.schema import (  # noqa: E402, I001  # 需排在 content re-export 之后，见上
    init_db,
    init_progress_db,
    migrate_a1_records_to_exam_trials,
)

# ── 设置/鉴权切片显式 re-export（database-split / Task 3）──────────────────────────
# 设置持久化与鉴权整组已搬入 `delector/core/db/settings.py`（纯移动）。此处**逐名**再导出，
# 保持公开面零变化；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
from delector.core.db.settings import (  # noqa: E402, I001  # 需排在连接访问器 re-export 之后
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    get_effective_reasoning_effort,
    get_setting,
    get_wb_sync_key,
    regenerate_wb_sync_key,
    set_setting,
    verify_wb_key,
)

# ── 考试 / 训练记录切片显式 re-export（database-split / Task 4）────────────────────────
# 泛化模考（exam_trials）、A1 双模块透传、听力微训（listen_trials）、长难句精读
# （hard_sentence_trials）整组已搬入 `delector/core/db/records.py`（纯移动）。此处**逐名**
# 再导出，保持公开面零变化；用逐名 `from ... import (...)`（**不用 `import *`**，不吞名字）。
from delector.core.db.records import (  # noqa: E402, I001  # 需排在连接访问器 re-export 之后
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
from delector.core.db.vocab import (  # noqa: E402, I001  # 需排在连接访问器 re-export 之后
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

# ── 伴学会话持久化切片显式 re-export ────────────────────────────────────────────────
from delector.core.db.companion import (  # noqa: E402, I001
    init_companion_tables,
    create_session,
    get_session,
    list_sessions,
    append_message,
    get_messages,
    create_proposal,
    get_proposals,
    update_proposal_status,
)


__all__ = [
    "DATA_DIR",
    "AUDIO_CACHE_DIR",
    "PROGRESS_DB_PATH",
    # ├─ 连接 / 路径片（Task 5）：非 `__all__` 名（下划线前缀 / 内部访问器）在此显式登记，
    #    使 pyflakes 认定它们是**有意再导出**而非「导入未用」。
    "_PKG_DIR",
    "_REPO_ROOT",
    "_norm_path",
    "_INITIALIZED_PROGRESS_DBS",
    "_configure_sqlite_conn",
    "_close_db_conn",
    "db_conn",
    "db_progress_conn",
    "preflight_data_dir",
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
    "get_effective_reasoning_effort",
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
]
