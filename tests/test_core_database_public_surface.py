# -*- coding: utf-8 -*-
r"""`delector/core/database.py` 切分安全网：公开面「⊇ 基线」对账。

背景（为什么先有这张网，再动切分）
----------------------------------
`core/database.py`（2819 行 / 86 顶层 def / 32 处被 import）要按职责切成包，硬约束是
**公开面零变化**：32 个 `import delector.core.database as database` 的调用点一行不改。
切分最危险的失败不是「报错」而是「静默漏搬」——某个名字没被 façade re-export，调用方
在运行时 AttributeError，而本地可能因为没走到那条路径而全绿。

本文件把「切分前公开名清单」**固化**成基线（`BASELINE_PUBLIC_NAMES`），断言 façade
模块 `delector.core.database` 的属性集 ⊇ 基线。任何一处漏搬 ⇒ 差集非空 ⇒ 测试红。

基线怎么来的（**不手抄**）
--------------------------
- 生成命令：``python tools/dump_module_public_names.py delector/core/database.py --pretty``
- 生成时间：2026-10-16（database-split / Task 1 Step 1，对**切分前**源码现读后粘入）
- 生成口径：AST 扫顶层 ``def``/``AsyncFunctionDef``/``ClassDef``/``Assign``（含多目标），
  排除 ``_`` 前缀与 ``if __name__ == "__main__":`` 块；规模 65（13 变量 + 52 函数）。
- 已知口径边界：顶层 ``AnnAssign``（``NAME: T = ...``）不在本基线内（当前有
  ``PRESET_SEED_VERSION`` / ``GENDER_ARTICLE_MAP`` 两个公开名未被覆盖）。这是 Task 1
  Step 1 计划「只扫 Assign」的既定范围；如需覆盖可另立一轮把 AnnAssign 纳入。

为什么断言 façade 的 ``dir()`` 而不是 ``__all__``
-------------------------------------------------
基线含 ``BACKUP_SETTINGS_EXPORT_WHITELIST`` / ``BACKUP_SETTINGS_IMPORT_WHITELIST`` 等
**公开但刻意不在 `__all__` 里**的名字（它们由具体调用方按名 import）。用 ``__all__``
当 façade 导出集会把这几个判成「漏搬」——那是假红。故 façade 导出集取 ``dir(module)``
（真实可访问的模块属性），与「调用方能否 `database.X` 拿到」逐字同义。
"""

from __future__ import annotations

from typing import Dict, Set

import delector.core.database as database

# 由 tools/dump_module_public_names.py 对切分前源码现读生成后粘入（勿手改，重生成即可）。
BASELINE_PUBLIC_NAMES: Dict[str, str] = {
    "A1_VOCAB_MODEL": "variable",
    "AUDIO_CACHE_DIR": "variable",
    "BACKUP_FORMAT_VERSION": "variable",
    "BACKUP_SETTINGS_EXPORT_WHITELIST": "variable",
    "BACKUP_SETTINGS_IMPORT_WHITELIST": "variable",
    "BACKUP_SETTINGS_WHITELIST": "variable",
    "BACKUP_TOKEN_TTL_SEC": "variable",
    "DATA_DIR": "variable",
    "GRAMMAR_MODEL": "variable",
    "PRESET_ARTICLES": "variable",
    "PRESET_PROCESSED_SCHEMA": "variable",
    "PROGRESS_DB_PATH": "variable",
    "VOCAB_MODEL": "variable",
    "add_prep_saved": "function",
    "build_backup_payload": "function",
    "create_encounter_text": "function",
    "db_conn": "function",
    "db_progress_conn": "function",
    "export_a1_anki_deck": "function",
    "export_anki_deck": "function",
    "format_vocab_headword": "function",
    "get_a1_hoeren_history": "function",
    "get_a1_lesen_history": "function",
    "get_all_corpus_syntax_stats": "function",
    "get_cache_info": "function",
    "get_db": "function",
    "get_db_path": "function",
    "get_effective_api_base_url": "function",
    "get_effective_api_key": "function",
    "get_effective_api_model": "function",
    "get_encounter_text": "function",
    "get_exam_history": "function",
    "get_prep_saved": "function",
    "get_progress_db": "function",
    "get_progress_db_path": "function",
    "get_setting": "function",
    "get_vocab_by_cefr": "function",
    "get_wb_state": "function",
    "get_wb_sync_key": "function",
    "import_encounter_pack": "function",
    "ingest_article": "function",
    "init_db": "function",
    "init_progress_db": "function",
    "list_encounter_texts": "function",
    "list_hard_sentence_trials": "function",
    "list_listen_trials": "function",
    "log_study_event": "function",
    "migrate_a1_records_to_exam_trials": "function",
    "preflight_data_dir": "function",
    "preset_processed_data_path": "function",
    "preset_processed_json": "function",
    "preset_text_hash": "function",
    "prune_audio_cache": "function",
    "record_a1_hoeren_trial": "function",
    "record_a1_lesen_trial": "function",
    "record_exam_trial": "function",
    "record_hard_sentence_trial": "function",
    "record_listen_trial": "function",
    "regenerate_wb_sync_key": "function",
    "save_wb_state": "function",
    "seed_preset_articles": "function",
    "seed_preset_encounter_texts": "function",
    "set_setting": "function",
    "upsert_corpus_syntax_stats": "function",
    "verify_wb_key": "function",
}

# 防呆：基线一旦被误清空（或生成命令写错路径产出空表），「⊇」断言会**恒真**而失去意义。
# 65 是切分前的真实规模；60 留出余量但不允许退化成个位数。
_MIN_BASELINE_SIZE = 60


def _facade_public_names() -> Set[str]:
    """façade 模块当前可访问的公开名（``dir()`` 去掉 ``_`` 前缀）。

    用 ``dir()`` 而非 ``__all__``：见模块 docstring「为什么断言 dir()」。
    """
    return {name for name in dir(database) if not name.startswith("_")}


def test_baseline_is_non_vacuous() -> None:
    """基线非空且数量级合理 —— 否则「⊇」断言退化成永真、安全网形同虚设。"""
    assert len(BASELINE_PUBLIC_NAMES) >= _MIN_BASELINE_SIZE, (
        f"公开面基线只有 {len(BASELINE_PUBLIC_NAMES)} 个名字（期望 ≥{_MIN_BASELINE_SIZE}）："
        "要么被误清空、要么生成命令扫错文件 —— 这会让「⊇ 基线」断言恒真而不再能拦漏搬。"
    )


def test_facade_exports_superset_of_baseline() -> None:
    """切分后 façade MUST 仍导出切分前的全部公开名（漏一个即红）。"""
    facade = _facade_public_names()
    missing = sorted(set(BASELINE_PUBLIC_NAMES) - facade)
    assert missing == [], (
        f"façade 缺少这些切分前就存在的公开名：{missing}\n"
        "切分（database.py → core/db/*）时任一名字漏搬 / 漏 re-export，"
        "都会让既有 `from delector.core.database import <名字>` 调用点在运行时崩。\n"
        "修法：在 `delector/core/database.py` 的显式 re-export 里补回该名字（不要改基线）。"
    )
