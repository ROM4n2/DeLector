# -*- coding: utf-8 -*-
"""背词工作台（wb）快照 → 统一词池 ``vocab_cards`` 的幂等投影（ADR-0016 Phase 3 / Task 1）。

职责：把 ``PUT /api/wb/state`` 的 wb 快照（``{words, cards, log, wrong, settings}``）
里的词条**幂等投影**进服务端统一池 ``vocab_cards``。本模块只读 payload、只写
``vocab_cards``，**不 commit**（事务交调用方），便于与镜像 blob 写入同事务原子提交
（Migration-Idempotency §2）。

注入不变量（Vault 规则；违反即驳回）
====================================
1. **按内容去重（禁计数对账）**：去重键 = ``lemma``（``lemma_key(str(hw))`` 归一）。
   MUST NOT 用「计数相等 / 大于」判迁移完成（Migration-Idempotency §1）。
2. **只增 + 只补空 + 幂等**：已存在的行**不得被覆盖** —— 仅当目标字段为空 / NULL 时写入；
   同一 payload 二次运行 ``inserted==0, updated==0, unchanged==N``（不写盘）。
3. **绝不触碰用户数据**：不写 ``correct_count`` / ``wrong_count`` / ``mastered`` /
   ``mastered_at`` / ``due_date`` / ``interval_days`` / ``ease_factor`` /
   ``repetition_count``，也不覆盖用户手编的 ``definition_zh`` / ``sentence_context``。
4. **不跨语义来源混用**：wb 的 ``reps`` 是 **FSRS** 语义 ⇒ 只写 ``fsrs_s`` / ``fsrs_d`` /
   ``fsrs_lapses``，MUST NOT 写 ``repetition_count``（DSR）。``gloss`` / ``ex[].de`` 是
   工作台语义（**语境原句**）⇒ 写 ``definition_zh`` / ``sentence_context``，仅在为空时补；
   MUST NOT 顶替官方「词典例句」槽。
5. **来源**：``source = primary_source(str(hw))``（Phase 2）；仅在该行 ``source`` 为空时补。
6. **诚实留空**：查不到 / 缺失的字段留空，不编造兜底（Backfill §6）。
7. **不抛**：payload 缺键 / words 非数组 / cards 非 dict → 安全降级（返回全 0，不抛）。
8. **范围闸（只收「用户自己的词」）**：仅当词条 ``custom is True``（自建，**严格** ``is True``，非
   truthy）或其 ``cards[str(id)].reps > 0``（已学）时才投影；自动加载的 A1/A2/B1 种子词
   （非自建且未学）MUST NOT 入池 —— 跳过（不查库、不写库）并计入返回值的 ``skipped``。
   判定在**归一键之后、查库之前**。

读取期派生（Backfill §2）：``pos`` / ``gender`` / ``plural`` / ``cefr_level`` 等富元数据
**不由本投影写入**（workbench 的 ``pos`` 标签是 view-owned 展示层，与池内约定不同，写入即
跨语义），由读取期从主干 ``lexicon`` 派生，避免写入期一次性填充与主干漂移。
"""

import sqlite3
from typing import Any, Dict, Optional, Set

# 主干单入口（ADR-0012 §5-1）：lemma 归一键与来源判定唯一实现，禁止在本模块复制一份。
from delector.core.lexicon import lemma_key, primary_source

# ``vocab_cards`` 中本投影可读 / 可写的列（SELECT 顺序即下列顺序，用整数下标读取，
# 不依赖调用方连接的 row_factory）。
_READ_COLUMNS = (
    "id",
    "definition_zh",
    "sentence_context",
    "source",
    "fsrs_s",
    "fsrs_d",
    "fsrs_lapses",
)

# 已存在行的「只补空」目标列（不覆盖非空值）：工作台语义槽 + 来源 + FSRS-6 参数。
# 注意：**不含** word / lemma（身份列）、**不含**任何 DSR / 用户进度列。
_FILLABLE_COLUMNS = (
    "definition_zh",
    "sentence_context",
    "source",
    "fsrs_s",
    "fsrs_d",
    "fsrs_lapses",
)


def _empty_result() -> Dict[str, int]:
    """安全降级返回值（不抛、零副作用）。"""
    return {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}


def _is_empty(value: Any) -> bool:
    """目标槽「可补」判定：``None`` / 纯空白串视为空；``0`` / 其它值视为有值。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _as_text(value: Any) -> str:
    """取字符串值：``None`` → ``""``；否则去首尾空白（保证幂等：非空值二次运行不再被判空）。"""
    if value is None:
        return ""
    return str(value).strip()


def _as_float(value: Any) -> Optional[float]:
    """宽松转 ``float``：``None`` / 布尔 / 不可转 → ``None``（诚实留空，不编造）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    """宽松转 ``int``：``None`` / 布尔 / 不可转 → ``default``。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_example_de(ex: Any) -> str:
    """取 ``ex[0].de``（工作台语境原句）；形状不符 → ``""``（诚实留空）。"""
    if not isinstance(ex, list) or not ex:
        return ""
    first = ex[0]
    if not isinstance(first, dict):
        return ""
    return _as_text(first.get("de"))


def _desired_fields(entry: Dict[str, Any], cards: Dict[str, Any]) -> Dict[str, Any]:
    """把一条 wb 词条 + 其 FSRS 卡映射为本投影的目标字段值（未读到的留空 / ``None``）。

    映射（不跨语义）：
    - ``definition_zh`` ← ``gloss``（工作台语义，中文释义）；
    - ``sentence_context`` ← ``ex[0].de``（工作台语境原句）；
    - ``source`` ← ``primary_source(str(hw))``；
    - ``fsrs_s`` / ``fsrs_d`` / ``fsrs_lapses`` ← 卡的 ``s`` / ``d`` / ``lapses``（FSRS-6）。
    卡键 = ``str(word.id)``（wb 快照约定）。
    """
    hw = entry.get("hw")
    word_id = entry.get("id")
    card: Any = cards.get(str(word_id)) if word_id is not None else None
    if not isinstance(card, dict):
        card = {}
    return {
        "definition_zh": _as_text(entry.get("gloss")),
        "sentence_context": _first_example_de(entry.get("ex")),
        "source": primary_source(str(hw)) if hw is not None else "user",
        "fsrs_s": _as_float(card.get("s")),
        "fsrs_d": _as_float(card.get("d")),
        "fsrs_lapses": _as_int(card.get("lapses")),
    }


def _insert_row(conn: sqlite3.Connection, word: str, lemma: str, desired: Dict[str, Any]) -> None:
    """只增：插入一行统一池词条（仅本投影关心的列；其余列走 schema 默认值）。"""
    conn.execute(
        "INSERT INTO vocab_cards "
        "(word, lemma, definition_zh, sentence_context, source, fsrs_s, fsrs_d, fsrs_lapses) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            word,
            lemma,
            desired["definition_zh"] or "",
            desired["sentence_context"] or "",
            desired["source"] or "user",
            desired["fsrs_s"],
            desired["fsrs_d"],
            desired["fsrs_lapses"],
        ),
    )


def _fill_updates(existing: Any, desired: Dict[str, Any]) -> Dict[str, Any]:
    """只补空：返回「当前为空 / NULL 且有值可补」的列 → 值；无则空 dict（据此判 unchanged）。"""
    current = {
        "definition_zh": existing[1],
        "sentence_context": existing[2],
        "source": existing[3],
        "fsrs_s": existing[4],
        "fsrs_d": existing[5],
        "fsrs_lapses": existing[6],
    }
    updates: Dict[str, Any] = {}
    for column in _FILLABLE_COLUMNS:
        desired_value = desired.get(column)
        if _is_empty(desired_value):
            continue
        if _is_empty(current[column]):
            updates[column] = desired_value
    return updates


def _entry_lemma(entry: Any) -> str:
    """取 wb 词条的归一键 lemma（唯一归一口径，投影 / 对账共用）。

    非 dict 或无 ``hw`` → ``""``（无法按内容去重，调用方据此跳过，与 ``_project_word`` 同口径）。
    """
    if not isinstance(entry, dict):
        return ""
    hw = entry.get("hw")
    return lemma_key(str(hw)) if hw is not None else ""


def _is_projectable(entry: Dict[str, Any], cards: Dict[str, Any]) -> bool:
    """范围闸（不变量 8）：只收「用户自己的词」——自建（``custom is True``）或已学（``reps > 0``）。

    - ``custom`` 取 ``entry.get("custom") is True``（**严格** ``is True``，非 truthy）；
    - ``reps`` 取 ``cards[str(entry["id"])]["reps"]``，卡不存在 / ``reps`` 非数 / ``<= 0`` ⇒ 未学。
    自动加载的 A1/A2/B1 种子词（既非自建又未学）⇒ ``False``（MUST NOT 入池）。
    """
    if entry.get("custom") is True:
        return True
    word_id = entry.get("id")
    if word_id is None:
        return False
    card = cards.get(str(word_id))
    if not isinstance(card, dict):
        return False
    reps = _as_float(card.get("reps"))
    return reps is not None and reps > 0


def _project_word(conn: sqlite3.Connection, entry: Any, cards: Dict[str, Any]) -> Optional[str]:
    """投影单条 wb 词条；返回 ``"inserted"`` / ``"updated"`` / ``"unchanged"`` / ``"skipped"``，
    无法作键（非 dict / 无归一键）→ ``None``（不计入任何桶）。"""
    lemma = _entry_lemma(entry)
    if not lemma:
        return None  # 非 dict / 无归一键 ⇒ 无法按内容去重，跳过（不编造占位）
    hw = entry.get("hw")

    # 范围闸（不变量 8）：归一键判定之后、查库之前短路 —— 种子词不查库、不写库，仅计入 skipped。
    if not _is_projectable(entry, cards):
        return "skipped"

    desired = _desired_fields(entry, cards)
    existing = conn.execute(
        "SELECT " + ", ".join(_READ_COLUMNS) + " FROM vocab_cards WHERE lemma = ? LIMIT 1",
        (lemma,),
    ).fetchone()

    if existing is None:
        _insert_row(conn, str(hw), lemma, desired)
        return "inserted"

    updates = _fill_updates(existing, desired)
    if not updates:
        return "unchanged"
    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE vocab_cards SET {assignments} WHERE id = ?",
        (*updates.values(), existing[0]),
    )
    return "updated"


def project_wb_deck(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, int]:
    """把 wb 快照的 ``words`` / ``cards`` 幂等投影进 ``vocab_cards``。

    返回 ``{"inserted": int, "updated": int, "unchanged": int, "skipped": int}``；``skipped`` =
    被范围闸挡下（非自建且未学）的词条数；**不 commit**（事务交调用方）。
    坏 payload（缺键 / ``words`` 非数组 / ``cards`` 非 dict）安全降级为全 0、不抛。
    """
    if not isinstance(payload, dict):
        return _empty_result()
    words = payload.get("words")
    cards = payload.get("cards")
    if not isinstance(words, list) or not isinstance(cards, dict):
        return _empty_result()

    counts: Dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for entry in words:
        outcome = _project_word(conn, entry, cards)
        if outcome is not None:
            counts[outcome] += 1
    return counts


# ── ADR-0016 Phase 3 / Task 4：只读对账（绝不写盘）────────────────────────────


def _pool_total(conn: sqlite3.Connection) -> int:
    """如实取 ``vocab_cards`` 现有**总行数**（规模量，仅供参考）；查库失败 → 0（不抛）。"""
    try:
        row = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    return int(row[0])


def _pool_lemmas(conn: sqlite3.Connection) -> Set[str]:
    """池侧归一键集合（只读 ``lemma`` 列）；查库失败 → 空集（不抛）。"""
    try:
        rows = conn.execute("SELECT lemma FROM vocab_cards").fetchall()
    except sqlite3.Error:
        return set()
    return {str(r[0]) for r in rows if r[0] is not None}


def _empty_reconcile(pool_total: int) -> Dict[str, Any]:
    """坏 payload / 降级返回值（不抛）：deck 侧全 0，``pool_total`` 仍如实给出。"""
    return {"deck_projectable": 0, "deck_in_pool": 0, "missing": [], "pool_total": pool_total}


def reconcile_report(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    """只读对账：应入池的 deck 词条 vs 池中实际存在的行。**绝不写盘。**

    返回**恰好** 4 个键：
    - ``deck_projectable``：deck 中「可投影」（过范围闸 ``_is_projectable``）的词条数（按 lemma 去重）；
    - ``deck_in_pool``：其上已在 ``vocab_cards`` 命中（按 ``lemma`` 去重后）的条数；
    - ``missing``：应入池但缺失的 lemma（**已排序**，便于断言 / 日志）；
    - ``pool_total``：``vocab_cards`` 现有总行数（仅供参考的规模量）。

    不变量
    ======
    - **按内容去重（禁计数对账）**：deck 侧按 ``lemma_key(str(hw))`` 归一成 lemma **集合**，
      池侧同样用 ``lemma`` 列；MUST NOT 以计数相等 / 大小判「是否一致」（Migration-Idempotency §1）。
      同一 lemma 在 deck 出现多次只算一次。
    - **只读**：函数内**只允许** ``SELECT``；MUST NOT 有任何 ``INSERT/UPDATE/DELETE/REPLACE``，
      也 MUST NOT 调 ``project_wb_deck``。不 commit / rollback；返回后库状态不变
      （同一 payload 连调两次结果一致）。
    - **诚实留空**：deck 侧无 ``hw`` / 非 dict 的词条不计入 ``deck_projectable``
      （与 ``project_wb_deck`` 口径一致——它们连 bucket 都不进）。
    - **刻意不产出 ``extra``（池里多出来的行）**：``vocab_cards`` 里还有主阅读流「存词」写入的
      用户卡（``POST /api/cards/vocab``），当前 schema **不记录行的来源是 deck 还是阅读**，
      因此任何 ``extra`` 都必然把用户卡误报成异常 ⇒ 按诚实原则**不产出该字段**。
    - **不抛**：``payload`` 缺 ``words`` / ``words`` 非数组 / ``cards`` 非 dict / 库为空 →
      ``deck`` 侧全 0、``missing==[]``（``pool_total`` 仍如实查库给出真实值；查库本身失败则给 0）。
    """
    pool_total = _pool_total(conn)
    if not isinstance(payload, dict):
        return _empty_reconcile(pool_total)
    words = payload.get("words")
    cards = payload.get("cards")
    if not isinstance(words, list) or not isinstance(cards, dict):
        return _empty_reconcile(pool_total)

    deck_lemmas: Set[str] = set()
    for entry in words:
        lemma = _entry_lemma(entry)
        if not lemma:
            continue  # 非 dict / 无归一键：与 project_wb_deck 口径一致，不计入
        if not _is_projectable(entry, cards):
            continue  # 范围闸：非自建且未学 → 不入池（与 skipped 口径一致）
        deck_lemmas.add(lemma)  # 集合天然对同一 lemma 去重

    in_pool = deck_lemmas & _pool_lemmas(conn)
    return {
        "deck_projectable": len(deck_lemmas),
        "deck_in_pool": len(in_pool),
        "missing": sorted(deck_lemmas - in_pool),
        "pool_total": pool_total,
    }
