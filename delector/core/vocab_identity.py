"""词卡同一性：唯一归一入口（读 / 写共用，禁第二份实现）。

身份 = ``(lemma_key(lemma), word_key(word))``：

- ``lemma`` 侧复用 :func:`delector.data.lexicon_merge.lemma_key`（去冠词、去 ``(sich)``、
  空白/连字符折叠）；
- ``word`` 侧复用 :func:`delector.data.lexicon_merge.word_key`（只 trim + 空白折叠 + 小写，
  **不**去冠词）。

为什么不是 ``lemma`` 单列：介词搭配 ``bestehen auf/aus/in`` 同 lemma 不同 word，
听力 ``die Wohnung`` 与正文 ``Wohnung`` 也同 lemma 不同 word —— 单列会把合法多卡判成重复。

空值回退：``vocab_identity`` 在参数侧把空 ``lemma`` / 空 ``word`` 回退到另一列（兼容老
前端传空串与旧备份还原出的 ``lemma=''`` 行）。SQL 侧**不**再对单列直接套归一函数，而是
注册 ``card_identity(lemma, word)`` / ``card_lemma_key(lemma, word)`` 两个行级 UDF ——
它们内部调用同一个 :func:`vocab_identity`，让「参数侧回退」与「存储列回退」完全同源。
零 DDL、不回填存量行；若只在 Python 侧回退，存储列为空的旧行会永远查不中，每次提交
都长一张新卡。

为什么 Step 1 不建 UNIQUE：存量重复规模未知，``CREATE UNIQUE INDEX`` 会失败或要求先删
用户数据。本模块只提供「先查后写」；并发窗口靠 ``BEGIN IMMEDIATE`` 收窄，**不等价于唯一
索引**：绕过本模块的写入（旧客户端、直接 SQL、备份还原）仍可产生重复。
"""

import sqlite3
from typing import Any, Mapping, Optional, Tuple

from delector.data.lexicon_merge import lemma_key, word_key

# upsert 时允许「只补空、不覆盖」的列（用户已填的内容一律保留）。
FILLABLE_COLUMNS = ("pos", "gender", "plural", "cefr_level", "definition_zh", "sentence_context")

# 身份键里两列的分隔符：归一后的 lemma/word 不会含控制字符。
_IDENTITY_SEP = "\x1f"


def vocab_identity(lemma: str, word: str) -> Tuple[str, str]:
    """返回 ``(lemma_key, word_key)``；lemma 为空时回退到 word（兼容老前端传空串）。"""
    lem = (lemma or "").strip() or (word or "").strip()
    return lemma_key(lem), word_key(word or lem)


def identity_key(lemma: str, word: str) -> str:
    """把一行的 ``(lemma, word)`` 折成与 :func:`vocab_identity` 同源的可比较字符串键。"""
    lk, wk = vocab_identity(lemma, word)
    return f"{lk}{_IDENTITY_SEP}{wk}"


def identity_lemma_key(lemma: str, word: str) -> str:
    """台账按 ``lemma_key`` 聚合时用：同样复用 :func:`vocab_identity` 的空值回退。"""
    return vocab_identity(lemma, word)[0]


def register_identity_functions(conn: sqlite3.Connection) -> None:
    """把行级归一 UDF 注册进 SQLite 连接（零 DDL；读侧 SQL 复用同一实现）。"""
    conn.create_function("card_identity", 2, identity_key, deterministic=True)
    conn.create_function("card_lemma_key", 2, identity_lemma_key, deterministic=True)


def find_card_id(conn: sqlite3.Connection, lemma: str, word: str) -> Optional[int]:
    """按身份查既有卡；多行时取最小 id（确定性）。无命中返回 ``None``。"""
    lk, wk = vocab_identity(lemma, word)
    if not lk and not wk:
        return None
    register_identity_functions(conn)
    row = conn.execute(
        "SELECT id FROM vocab_cards WHERE card_identity(lemma, word) = ? ORDER BY id LIMIT 1",
        (identity_key(lemma, word),),
    ).fetchone()
    return int(row[0]) if row else None


def fill_empty_columns(conn: sqlite3.Connection, card_id: int, values: Mapping[str, Any]) -> None:
    """对既有卡「只补空」：NULL / 空白串才写入，绝不覆盖用户已有内容。"""
    sets = []
    params: list[Any] = []
    for col in FILLABLE_COLUMNS:
        val = values.get(col)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        sets.append(f"{col} = CASE WHEN {col} IS NULL OR TRIM({col}) = '' THEN ? ELSE {col} END")
        params.append(val)
    if not sets:
        return
    params.append(card_id)
    conn.execute(f"UPDATE vocab_cards SET {', '.join(sets)} WHERE id = ?", tuple(params))
