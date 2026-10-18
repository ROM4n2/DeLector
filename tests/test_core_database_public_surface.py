# -*- coding: utf-8 -*-
r"""`delector/core/database.py` 切分安全网：公开面**逐名对账**（双向差集为空的机械闸）。

背景（为什么先有这张网，再动切分）
----------------------------------
`core/database.py`（切分前 2809 行 / 86 顶层 def / 32 处被 import）要按职责切成包，硬约束是
**公开面零变化**：32 个 `import delector.core.database as database` 的调用点一行不改。
切分最危险的失败不是「报错」而是「静默漏搬」——某个名字没被 façade re-export，调用方
在运行时 AttributeError，而本地可能因为没走到那条路径而全绿。

本文件把「切分前公开名清单」**固化**成基线（`BASELINE_PUBLIC_NAMES`），并对 façade 模块
`delector.core.database` 做**双向**对账（Task 5 由「⊇ 基线」升级）：
- `基线 − façade` 为空 —— 不许**漏搬**（切分时漏了 re-export ⇒ 调用方运行时崩）；
- `façade 公开面 − 基线`（再去掉显式 allowlist）为空 —— 不许**夹带未登记的新公开名**。
两个方向任一非空 ⇒ 测试红，并打印一份「名字 → 归属切片模块 → 是否在基线」的对账表。

基线怎么来的（**不手抄**）
--------------------------
- 生成命令：``python tools/dump_module_public_names.py delector/core/database.py --pretty``
- 生成时间：2026-10-16（database-split / Task 1 Step 1，对**切分前**源码现读后粘入）
- 生成口径：AST 扫顶层 ``def``/``AsyncFunctionDef``/``ClassDef``/``Assign``（含多目标），
  排除 ``_`` 前缀与 ``if __name__ == "__main__":`` 块；规模 65（13 变量 + 52 函数）。
- **口径边界补记（Task 5）**：顶层 ``AnnAssign``（``NAME: T = ...``）不在工具扫描范围内，
  故两个 AnnAssign 公开常量 ``PRESET_SEED_VERSION`` / ``GENDER_ARTICLE_MAP`` 此前**未**进
  基线。它们确实出现在 façade 上 ⇒ 按「**补进基线**（而非塞进 allowlist）」处置：它们是
  真实的再导出公开名（属性可经 `database.X` 取用），不是导入产物。补入后规模 67。

为什么断言 façade 的 ``dir()`` 而不是 ``__all__``
-------------------------------------------------
基线含 ``BACKUP_SETTINGS_EXPORT_WHITELIST`` / ``BACKUP_SETTINGS_IMPORT_WHITELIST`` 等
**公开但刻意不在 `__all__` 里**的名字（它们由具体调用方按名 import）。用 ``__all__``
当 façade 导出集会把这几个判成「漏搬」——那是假红。故 façade 导出集取 ``dir(module)``
（真实可访问的模块属性），与「调用方能否 `database.X` 拿到」逐字同义。

反方向为何需要 allowlist（而非放宽断言）
----------------------------------------
``dir(module)`` 会把**模块级 import 绑定的名字**也算进「公开面」——它们不是「漏搬」、
也不是「新公开名」，只是 import 产物（`_` 前缀者已被过滤，无前缀者如实列出）。故反方向
断言为 ``façade − 基线 − _FACADE_ALLOWLIST == ∅``；allowlist **逐条带理由**，且**不放宽
任何方向**：漏一个基线名 ⇒ 红；夹带一个未登记名 ⇒ 红。
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Dict, List, Set, Tuple

import delector.core.database as database

# 由 tools/dump_module_public_names.py 对切分前源码现读生成后粘入（勿手改，重生成即可）。
# Task 5 补入两个 AnnAssign 常量（判断依据见模块 docstring「口径边界补记」）。
BASELINE_PUBLIC_NAMES: Dict[str, str] = {
    "A1_VOCAB_MODEL": "variable",
    "AUDIO_CACHE_DIR": "variable",
    "BACKUP_FORMAT_VERSION": "variable",
    "BACKUP_SETTINGS_EXPORT_WHITELIST": "variable",
    "BACKUP_SETTINGS_IMPORT_WHITELIST": "variable",
    "BACKUP_SETTINGS_WHITELIST": "variable",
    "BACKUP_TOKEN_TTL_SEC": "variable",
    "DATA_DIR": "variable",
    "GENDER_ARTICLE_MAP": "variable",
    "GRAMMAR_MODEL": "variable",
    "PRESET_ARTICLES": "variable",
    "PRESET_PROCESSED_SCHEMA": "variable",
    "PRESET_SEED_VERSION": "variable",
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

# 反方向（façade − 基线）的**显式 allowlist**：每个名字都是 `dir()` 会列出的「模块级 import
# 绑定」，既非漏搬、也非新公开名。逐条理由如下；**只在反方向生效**，正方向（基线 − façade）
# 一律不允许豁免（放宽方向 = 安全网失效）。
_FACADE_ALLOWLIST: Dict[str, str] = {
    "HTTPException": (
        "fastapi 导入产物：留在 façade 的 `_require_localhost`（HTTP 关注点，按计划刻意不搬进 "
        "持久层包）所需，非 DB 公开面；登记以免对账表把这层导入误当『夹带新公开名』。"
    ),
    "Request": (
        "同上：`_require_localhost` 的入参类型注解所需，fastapi 导入产物。"
    ),
}

# 防呆：基线一旦被误清空（或生成命令写错路径产出空表），「⊇」断言会**恒真**而失去意义。
# 67 是补入两个 AnnAssign 常量后的真实规模；60 留出余量但不允许退化成个位数。
_MIN_BASELINE_SIZE = 60

# 对账表里「名字归属哪一片」的候选模块（顺序即优先级）。落在这些模块以外的名字，是
# façade 本体（`_require_localhost`）所需的导入产物。
_OWNER_CANDIDATES: Tuple[str, ...] = (
    "delector.core.db.connection",
    "delector.core.db.backup",
    "delector.core.db.settings",
    "delector.core.db.schema",
    "delector.core.db.content",
    "delector.core.db.records",
    "delector.core.db.vocab",
)


def _facade_public_names() -> Set[str]:
    """façade 模块当前可访问的公开名（``dir()`` 去掉 ``_`` 前缀）。

    用 ``dir()`` 而非 ``__all__``：见模块 docstring「为什么断言 dir()」。
    """
    return {name for name in dir(database) if not name.startswith("_")}


def _defined_top_level_names(module: ModuleType) -> Set[str]:
    """模块**顶层定义**的名字（def/class/Assign/AnnAssign）—— 不含 `import` 绑定的名字。

    只看「定义」而非 `vars()`：多个切片都会 `import HTTPException` / `PROCESSED_JSON_VERSION`，
    用 `vars()` 会把偶尔先导入它的切片误报成「归属」。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


_OWNER_NAMES_CACHE: Dict[str, Set[str]] = {}


def _owner_module(name: str) -> str:
    """名字归属的模块（按**顶层定义**判定）；不属于任何切片/处理器时回退为 façade 本体。"""
    for module_path in _OWNER_CANDIDATES:
        if module_path not in _OWNER_NAMES_CACHE:
            _OWNER_NAMES_CACHE[module_path] = _defined_top_level_names(importlib.import_module(module_path))
        if name in _OWNER_NAMES_CACHE[module_path]:
            return module_path
    return "delector.core.database(façade 本体 / 其它导入)"


def _reconciliation_rows() -> List[Tuple[str, str, bool]]:
    """(名字, 归属切片模块, 是否在基线) —— 按名字排序，供对账表打印。"""
    baseline = set(BASELINE_PUBLIC_NAMES)
    return [(name, _owner_module(name), name in baseline) for name in sorted(_facade_public_names())]


def _format_reconciliation_table() -> str:
    rows = _reconciliation_rows()
    width = max((len(name) for name, _, _ in rows), default=8)
    lines = [
        "",
        "── façade 公开面对账表（名字 → 归属切片模块 → 是否在基线）──",
    ]
    for name, owner, in_baseline in rows:
        mark = "基线" if in_baseline else ("allowlist" if name in _FACADE_ALLOWLIST else "!! 未登记 !!")
        lines.append(f"  {name:<{width}}  {owner:<32}  {mark}")
    lines.append(f"  合计 {len(rows)} 个公开名 · 基线 {len(BASELINE_PUBLIC_NAMES)} 个")
    return "\n".join(lines)


def test_baseline_is_non_vacuous() -> None:
    """基线非空且数量级合理 —— 否则「⊇」断言退化成永真、安全网形同虚设。"""
    assert len(BASELINE_PUBLIC_NAMES) >= _MIN_BASELINE_SIZE, (
        f"公开面基线只有 {len(BASELINE_PUBLIC_NAMES)} 个名字（期望 ≥{_MIN_BASELINE_SIZE}）："
        "要么被误清空、要么生成命令扫错文件 —— 这会让「⊇ 基线」断言恒真而不再能拦漏搬。"
    )


def test_reconciliation_table_is_printable() -> None:
    """打印逐名对账表（`pytest -s` 可见）—— 便于人工核对每名归属与基线状态。"""
    print(_format_reconciliation_table())


def test_facade_exports_superset_of_baseline() -> None:
    """方向一：`基线 − façade` 必须为空 —— 切分后 façade 仍导出切分前的全部公开名（漏一个即红）。"""
    facade = _facade_public_names()
    missing = sorted(set(BASELINE_PUBLIC_NAMES) - facade)
    assert missing == [], (
        f"façade 缺少这些切分前就存在的公开名：{missing}\n"
        "切分（database.py → core/db/*）时任一名字漏搬 / 漏 re-export，"
        "都会让既有 `from delector.core.database import <名字>` 调用点在运行时崩。\n"
        "修法：在 `delector/core/database.py` 的显式 re-export 里补回该名字（不要改基线）。"
    )


def test_facade_has_no_unregistered_extra_names() -> None:
    """方向二：`façade − 基线 − allowlist` 必须为空 —— 不许夹带未登记的新公开名（Task 5 新增）。"""
    facade = _facade_public_names()
    extra = sorted(facade - set(BASELINE_PUBLIC_NAMES) - set(_FACADE_ALLOWLIST))
    assert extra == [], (
        f"façade 上出现了基线之外、且未登记进 allowlist 的公开名：{extra}\n"
        "这多半意味着往 façade 里夹带了未登记的新公开名（re-export 别名 / 误绑变量）。\n"
        "修法二选一（**不许放宽断言方向**）：\n"
        "  · 若是真实的新公开面 ⇒ 补进 `BASELINE_PUBLIC_NAMES`（并同步 tools 生成口径）；\n"
        "  · 若是 import 产物 / 导入型再导出 ⇒ 登记进 `_FACADE_ALLOWLIST` 并写清理由。"\
    )


def test_core_db_has_no_top_level_nlp_engine_imports() -> None:
    """Layer 1 [core.db] 顶层严禁导入 Layer 2 [nlp_engine]（C5 分层依赖守卫）。"""
    import ast
    from pathlib import Path

    db_dir = Path(__file__).resolve().parent.parent / "delector" / "core" / "db"
    violations: List[str] = []

    for py_file in db_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    if alias.name.startswith("delector.nlp_engine"):
                        violations.append(f"{py_file.name}: import {alias.name}")
            elif isinstance(stmt, ast.ImportFrom):
                mod = stmt.module or ""
                if mod.startswith("delector.nlp_engine"):
                    violations.append(f"{py_file.name}: from {mod} import ...")

    assert violations == [], f"core/db/ 发现顶层逆向导入 nlp_engine: {violations}"

