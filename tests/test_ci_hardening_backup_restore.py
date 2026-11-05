# -*- coding: utf-8 -*-
"""备份 / 还原一致性守卫：清单 ↔ 模型、事务与 trial 表往返。"""

from pathlib import Path
from typing import Any

import pytest

# ── 备份/还原「清单 ↔ 模型」一致性守卫（2026-10-16 A1 / P0-1：还原静默清空训练记录）──
# 事故链（已用真实 _replace_tables 在临时库复现）：`_BACKUP_TABLES` 现读 **10 张表**，
# 而还原请求模型 `RestoreReq` 只声明 **8 张主库表**字段；pydantic v2 默认
# `extra=ignore` ⇒ 前端整份 POST 里 listen_trials / hard_sentence_trials 两键被**静默
# 丢弃**；`_replace_tables` 又对清单里**每张表无条件 DELETE** ⇒ 删光零回灌，而接口仍
# 返回 ok（用户零提示地丢掉全部听力微训 / 长难句精读记录）。
#
# 三处同批修，缺一处仍会静默丢数据：
#   ① `RestoreReq` 补 listen_trials / hard_sentence_trials 两字段；
#   ② `_replace_tables` 加前向兼容闸「键不在 payload ⇒ continue（原样保留）」——它把
#      「日后新增备份表忘了补字段」的代价从**不可逆丢数据**降到**该表没被覆盖**；
#   ③ 本节守卫把「清单 ↔ 字段集」钉成集合关系，让下一次「入清单忘改模型」立刻红。
#
# 为什么这三条落在本文件：本文件是「清单 ↔ 实现一致性」守卫的既有落点
# （CI_REQUIRED_RUNTIMES ↔ conftest 实查项、PACKAGING_SURFACE_PATHS ↔ paths 过滤…），
# 且计划允许「test_ci_hardening_backup_restore.py 或 test_server.py 择一」；test_server.py 同期另有
# 改动面（P1-1 的 local_storage 契约），同文件并行编辑必冲突。
#
# 断言纪律：两份清单**现读**（import 真对象），不手抄表名 —— 手抄的清单不随功能增长，
# 而「新表入清单、模型没跟上」正是本次事故溜到线上的原因。

_TRIAL_TABLES: tuple[str, ...] = ("listen_trials", "hard_sentence_trials")


def _fresh_db_pair(tmp_path: Path, stem: str) -> tuple[str, str]:
    """在 tmp_path 下建一对空 schema（主库 + progress 库），返回两个**绝对**路径。

    显式传 db_path ⇒ `init_db` 不跑数据目录闸（那条闸判的是仓库根 / 数据目录），
    也不碰开发者真实库：用例只在临时目录里真跑 SQL（审计复现用的也是这条路径）。
    """
    from delector.core.database import init_db, init_progress_db

    db_path = str(tmp_path / f"{stem}.db")
    progress_path = str(tmp_path / f"{stem}-progress.db")
    init_db(db_path=db_path)
    init_progress_db(progress_path)
    return db_path, progress_path


def _insert_trial_rows(db_path: str) -> None:
    """写入 2 条听力微训 + 1 条长难句精读（字段取非默认值，往返比对才有区分度）。"""
    from delector.core.database import record_hard_sentence_trial, record_listen_trial

    record_listen_trial("dictation", "article", 7, "A2", 10, 8, 0.8, 95, db_path=db_path)
    record_listen_trial("choice", "encounter", 3, "B1", 12, 5, 0.4167, 120, db_path=db_path)
    record_hard_sentence_trial("article", 7, 2, "B1", 0.75, 1, 64, db_path=db_path)


def _trial_rows(db_path: str) -> dict[str, list[dict[str, Any]]]:
    """读回两张训练表的**全列**（按 id 排序，便于整行逐字段比对内容）。"""
    from delector.core.database import get_db

    conn = get_db(db_path)
    try:
        return {
            name: [dict(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()]
            for name in _TRIAL_TABLES
        }
    finally:
        conn.close()


def _pin_db_env(monkeypatch: pytest.MonkeyPatch, db_path: str, progress_path: str) -> None:
    """把 env 钉到这对临时库：`build_backup_payload()` / `get_db()` 都按 env 解析落点。"""
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("PROGRESS_DB_PATH", progress_path)


def test_restore_payload_missing_table_key_preserves_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """payload **缺**表键 ⇒ 该表 MUST 原样保留（前向兼容闸），MUST NOT 被清空。

    这是真实事故链的最后一步：pydantic 丢键后的 payload 里没有 listen_trials，而
    `_replace_tables` 对清单里每张表**无条件 DELETE**，随后 `payload.get(name) or []`
    为空 ⇒ continue ⇒ **删光零回灌**。用临时库真跑，不 mock。
    """
    from delector.core.database import _BACKUP_TABLES, _replace_tables, build_backup_payload, get_db

    src, progress_src = _fresh_db_pair(tmp_path, "src")
    _pin_db_env(monkeypatch, src, progress_src)
    _insert_trial_rows(src)
    before = _trial_rows(src)
    assert len(before["listen_trials"]) == 2, "前置：种子数据没落库，本用例守的对象不对"

    payload = build_backup_payload()
    assert "listen_trials" in payload, "导出侧缺该键：本用例守的对象不对，请先修导出"
    payload.pop("listen_trials")

    conn = get_db(src)
    try:
        with conn:
            _replace_tables(conn, _BACKUP_TABLES, payload)
    finally:
        conn.close()

    after = _trial_rows(src)
    assert after["listen_trials"] == before["listen_trials"], (
        "payload 缺 listen_trials 键时该表被清空了 —— 这正是 P0-1：还原静默删光零回灌"
        "（接口仍返回 ok，用户零提示地丢掉全部听力微训记录）。\n"
        "修法：`_replace_tables` 加前向兼容闸 —— 键不在 payload 就 continue（**原样保留**），"
        "而不是清空。"
    )
    assert after["hard_sentence_trials"] == before["hard_sentence_trials"], (
        "键在场且非空的表往返后不一致：DELETE + 回灌这条路径本身坏了"
    )

    # 反向语义（闸 MUST NOT 退化成「空列表也跳过」）：键**在场但为空**仍是有意覆盖 ——
    # 「备份里这张表就是空的」必须把目标库清空，否则用户删干净的成绩会在还原后复活。
    payload_empty = build_backup_payload()
    payload_empty["listen_trials"] = []
    conn = get_db(src)
    try:
        with conn:
            _replace_tables(conn, _BACKUP_TABLES, payload_empty)
    finally:
        conn.close()
    assert _trial_rows(src)["listen_trials"] == [], (
        "键在场但为空时该表没被清空：闸被写成了 `if not rows: continue` 这类把空列表也当缺键的"
        "形态，会让「备份里的空表」永远无法覆盖目标库"
    )


def test_backup_restore_roundtrip_keeps_trial_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """导出 →（经 RestoreReq 过滤）→ 还原进**空库**（换机/重装）⇒ 两表行数与内容一致。

    为什么不只测 `_replace_tables`：真实链路上多了一道 **pydantic 过滤**，
    字段没声明 ⇒ 键被 `extra=ignore` 丢掉 ⇒ 还原删光零回灌。本用例把这道过滤接进来，
    让"模型漏字段"这一类缺陷在测试里就能红。
    """
    from delector.core.database import _BACKUP_TABLES, _replace_tables, build_backup_payload, get_db
    from delector.routes.main import RestoreReq

    src, progress_src = _fresh_db_pair(tmp_path, "src")
    _pin_db_env(monkeypatch, src, progress_src)
    _insert_trial_rows(src)
    before = _trial_rows(src)
    assert before["listen_trials"] and before["hard_sentence_trials"], "前置：种子数据没落库"

    exported = build_backup_payload()

    # 换机/重装：目标库是全新的空库（还原语义是「真覆盖」，不是 merge）
    dst, progress_dst = _fresh_db_pair(tmp_path, "dst")
    _pin_db_env(monkeypatch, dst, progress_dst)

    # 走真实请求模型：这正是「前端整份 POST 被 pydantic 过滤」的那一步
    req = RestoreReq(**exported)
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    for name in _TRIAL_TABLES:
        assert payload.get(name), (
            f"RestoreReq 过滤后 payload 里没有 {name}：前端整份 POST 的该键被模型丢弃，"
            "还原会「删光零回灌」（P0-1）。修法：给 RestoreReq 补该字段。"
        )

    conn = get_db(dst)
    try:
        with conn:
            _replace_tables(conn, _BACKUP_TABLES, payload)
    finally:
        conn.close()

    after = _trial_rows(dst)
    for name in _TRIAL_TABLES:
        assert after[name] == before[name], (
            f"{name} 备份往返后不一致：\n  导出前 {before[name]!r}\n  还原后 {after[name]!r}"
        )


def test_build_backup_payload_uses_deferred_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-2: build_backup_payload MUST wrap table queries in BEGIN DEFERRED ... COMMIT for read snapshot consistency."""
    import sqlite3

    from delector.core.database import build_backup_payload, get_db, get_progress_db

    src, progress_src = _fresh_db_pair(tmp_path, "backup_tx")
    _pin_db_env(monkeypatch, src, progress_src)

    history: list[str] = []
    orig_get_db = get_db
    orig_get_progress_db = get_progress_db

    class SpyingConn:
        def __init__(self, conn: sqlite3.Connection, prefix: str) -> None:
            self._conn = conn
            self._prefix = prefix

        def execute(self, sql: str, *params: Any) -> Any:
            history.append(f"{self._prefix}:{sql.strip()}")
            return self._conn.execute(sql, *params)

        def commit(self) -> None:
            history.append(f"{self._prefix}:COMMIT")
            self._conn.commit()

        def rollback(self) -> None:
            history.append(f"{self._prefix}:ROLLBACK")
            self._conn.rollback()

        def close(self) -> None:
            self._conn.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._conn, name)

    monkeypatch.setattr(
        "delector.core.db.backup.get_db",
        lambda *a, **kw: SpyingConn(orig_get_db(*a, **kw), "main"),
    )
    monkeypatch.setattr(
        "delector.core.db.backup.get_progress_db",
        lambda *a, **kw: SpyingConn(orig_get_progress_db(*a, **kw), "progress"),
    )

    exported = build_backup_payload()
    assert exported["version"] == 2

    main_begins = [i for i, s in enumerate(history) if s == "main:BEGIN DEFERRED"]
    main_commits = [i for i, s in enumerate(history) if s == "main:COMMIT"]
    prog_begins = [i for i, s in enumerate(history) if s == "progress:BEGIN DEFERRED"]
    prog_commits = [i for i, s in enumerate(history) if s == "progress:COMMIT"]

    assert main_begins and main_commits, (
        f"main connection queries not wrapped in BEGIN DEFERRED / COMMIT: {history}"
    )
    assert prog_begins and prog_commits, (
        f"progress connection queries not wrapped in BEGIN DEFERRED / COMMIT: {history}"
    )
    assert main_begins[0] < main_commits[0], "main COMMIT occurred before BEGIN DEFERRED"
    assert prog_begins[0] < prog_commits[0], "progress COMMIT occurred before BEGIN DEFERRED"


def test_restore_req_declares_every_backup_table() -> None:
    """备份清单里的每张表 MUST 在 `RestoreReq` 上有同名字段（现读两份清单，不手抄）。

    判据是**集合差**而非逐表列举：清单随功能增长（listen_trials / hard_sentence_trials /
    encounter_texts 都是后加的），逐表列举永远滞后一步；而漏一处的代价就是
    「还原静默清空该表」——同类缺陷本仓已发生两次（vocab_cards 漏列 / 本次两表漏字段）。
    """
    from delector.core.database import _BACKUP_TABLES, _PROGRESS_TABLES
    from delector.routes.main import RestoreReq

    fields = getattr(RestoreReq, "model_fields", None)
    if fields is None:  # pragma: no cover - pydantic v1 面（Android 运行时）字段集在 __fields__
        fields = getattr(RestoreReq, "__fields__", {})
    provided = set(fields)

    missing = sorted(set(_BACKUP_TABLES) - provided)
    assert missing == [], (
        f"RestoreReq 未声明备份清单里的表：{missing}\n"
        "pydantic v2 默认 extra=ignore ⇒ 前端整份 POST 里的同名键会被**静默丢弃**，"
        "而还原会对这些表 DELETE 后零回灌（用户零提示地丢数据）。\n"
        "修法：在 RestoreReq 上补 `字段名: List[Dict[str, Any]] = []`（缺省空以兼容旧备份），"
        "而不是删掉本守卫。"
    )

    # 同理守 progress 库清单：还原对 _PROGRESS_TABLES 走同一套 _replace_tables，
    # 漏键的失败形态与危害相同（只是数据面在另一个库）。
    missing_progress = sorted(set(_PROGRESS_TABLES) - provided)
    assert missing_progress == [], (
        f"RestoreReq 未声明 progress 备份清单里的表：{missing_progress}\n"
        "还原对 _PROGRESS_TABLES 走同一套 _replace_tables，漏键 ⇒ 该表被 DELETE 后零回灌。"
    )


def test_backup_column_lists_cover_schema_columns(tmp_path: Path) -> None:
    """列级守卫：备份列清单 MUST 覆盖**建表 DDL 的每一列**（主库 + progress 库）。

    上一节只比对**表集合**——表在清单里、列漏了照样全绿。articles.stats_json
    （P1-6 列表投影列，schema.py 建表 DDL 内）就是这样漏出清单的：
    `_replace_tables` 按清单 DELETE + INSERT ⇒ 还原后该列**永久 NULL**，
    列表接口的 COALESCE 只是把 NULL 读成默认值，掩盖了性能回退（数据是真丢）。

    判据现读 `PRAGMA table_info`（不手抄列名），与既有守卫同一纪律：清单随功能增长，
    手抄的列集合永远滞后一步。反向也守（清单独有、DDL 没有的列会在还原时 INSERT 报错）。
    """
    import sqlite3

    from delector.core.database import _BACKUP_TABLES, _PROGRESS_TABLES

    db_path, progress_path = _fresh_db_pair(tmp_path, "cols")
    problems: list[str] = []
    for label, path, spec in (
        ("main", db_path, _BACKUP_TABLES),
        ("progress", progress_path, _PROGRESS_TABLES),
    ):
        conn = sqlite3.connect(path)
        try:
            for name, (cols, _defaults) in spec.items():
                actual = [r[1] for r in conn.execute(f"PRAGMA table_info({name})").fetchall()]
                missing = sorted(set(actual) - set(cols))
                unknown = sorted(set(cols) - set(actual))
                if missing:
                    problems.append(f"{label}/{name} 备份列清单漏列：{missing}")
                if unknown:
                    problems.append(f"{label}/{name} 备份列清单含建表 DDL 中不存在的列：{unknown}")
        finally:
            conn.close()

    assert problems == [], (
        "备份列清单与建表 DDL 不一致（还原按清单 DELETE + INSERT ⇒ 漏列的值会永久变 NULL/默认值，"
        "接口仍返回 ok，用户零提示）：\n  " + "\n  ".join(problems) + "\n"
        "修法：把缺的列补进 _BACKUP_TABLES / _PROGRESS_TABLES 的列元组与 defaults，"
        "而不是删掉本守卫。"
    )


def test_backup_restore_roundtrip_keeps_articles_stats_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """articles.stats_json 必须逐字度过「导出 →（RestoreReq 过滤）→ 还原」往返。

    导出侧用 `SELECT *`，所以 stats_json 会进 payload；坏在还原侧按固定列清单
    DELETE + INSERT ⇒ 不在清单里的列被丢弃、还原后为 NULL。本用例走真实链路
    （build_backup_payload + RestoreReq + _replace_tables），在临时库里真跑。
    """
    from delector.core.database import _BACKUP_TABLES, _replace_tables, build_backup_payload, get_db
    from delector.routes.main import RestoreReq

    stats_value = '{"words": 3, "sentences": 1}'

    src, progress_src = _fresh_db_pair(tmp_path, "src")
    _pin_db_env(monkeypatch, src, progress_src)
    conn = get_db(src)
    try:
        with conn:
            conn.execute(
                "INSERT INTO articles (title, raw_text, processed_json, stats_json, source_url) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Stats 往返", "Ein kurzer Satz.", '{"stats": {"words": 3}}', stats_value, ""),
            )
    finally:
        conn.close()

    exported = build_backup_payload()
    exported_row = next(r for r in exported["articles"] if r["title"] == "Stats 往返")
    assert exported_row["stats_json"] == stats_value, (
        "前置：导出侧没带 stats_json，本用例守的对象不对（先修 build_backup_payload 的读取列）"
    )

    # 换机/重装：还原进全新的空库
    dst, progress_dst = _fresh_db_pair(tmp_path, "dst")
    _pin_db_env(monkeypatch, dst, progress_dst)
    req = RestoreReq(**exported)
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()

    conn = get_db(dst)
    try:
        with conn:
            _replace_tables(conn, _BACKUP_TABLES, payload)
    finally:
        conn.close()

    conn = get_db(dst)
    try:
        after = dict(conn.execute("SELECT * FROM articles WHERE title = 'Stats 往返'").fetchone())
    finally:
        conn.close()
    assert after["stats_json"] == stats_value, (
        f"articles.stats_json 往返后被丢弃：还原前 {stats_value!r}，还原后 {after['stats_json']!r}\n"
        "这是 _BACKUP_TABLES['articles'] 的列清单缺 stats_json ⇒ _replace_tables 不写该列。\n"
        "修法：把 stats_json 补进列清单（defaults 置 None 以兼容旧备份）。"
    )
