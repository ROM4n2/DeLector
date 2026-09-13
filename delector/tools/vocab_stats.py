# -*- coding: utf-8 -*-
"""B1：vocab_stats —— 第 6 个 Python leaf tool（词表覆盖统计）。

语义：按 payload 的 tokens，统计「已知 = lemma ∈ (A1∪A2 考纲词 lemma 集)
∪ known_extra」的覆盖率，并给出未知词频降序排名（封顶 60）与 level_hint 启发式。

**词集来源（口径纪律）**：考纲词 lemma 集取自既有
`delector.services.exam_catalog` 口径所引用的数据源，**不内嵌新词表**——
- A1 考纲词 = `delector.data.a1_dict.GOETHE_A1_VOCAB` 各条目 `lemma` 字段
  （与 exam_catalog 的 A1 vocab count_fn 同源；已确认该词典条目携带小写 lemma）。
- A2 考纲词 = `delector.data.core_dict.CORE_VOCAB_DB` 中 CEFR=A2 条目的 lemma
  key（即 `get_vocab_by_cefr("A2")` 读取的同源常量；A2 词条对外只暴露带定冠词
  装饰的 hw 与 `a2-{lemma}` id，**无独立 lemma 字段**，故直接从底层常量取原始
  小写 lemma）。

纯函数、无 DB（ADR-0009 纪律）。已知 lemma 集做模块级惰性缓存。

level_hint 启发式（契约）：unknown_rate = 未知 token / tokens_total，
≤0.15 → "A1"，≤0.35 → "A2"，否则 "B1"。
空 tokens 边界：tokens_total=0 时 unknown_rate 定义作 0.0 → level_hint "A1"
（无信息输入按最乐观定级，避免除零）。
"""

from typing import Any, Dict, List

# 允许作为 known 基准的考纲等级（与 exam_catalog 实存词表对应）。
_ALLOWED_LEVELS = frozenset({"A1", "A2"})
# 未知词排名封顶条数（契约）。
_UNKNOWN_CAP = 60
# known_rate 舍入小数位（对齐契约示例 0.667）。
_RATE_ROUND = 3


def _load_a1_lemmas() -> frozenset:
    """A1 考纲词 lemma 集（惰性）。源 = GOETHE_A1_VOCAB 条目 lemma 字段。"""
    from delector.data.a1_dict import GOETHE_A1_VOCAB

    lemmas = {str(entry.get("lemma", "")).strip().lower() for entry in GOETHE_A1_VOCAB.values()}
    lemmas.discard("")
    return frozenset(lemmas)


def _load_a2_lemmas() -> frozenset:
    """A2 考纲词 lemma 集（惰性）。源 = core_dict CEFR=A2 条目 lemma key。

    词条对外只暴露装饰过的 hw / `a2-{lemma}` id、无独立 lemma 字段，故直接从
    与 get_vocab_by_cefr("A2") 同源的 CORE_VOCAB_DB 常量取原始小写 lemma。
    """
    from delector.data.core_dict import CORE_VOCAB_DB

    lemmas = {lemma.strip().lower() for lemma, val in CORE_VOCAB_DB.items() if str(val[0]).upper() == "A2"}
    return frozenset(lemmas)


# 模块级惰性缓存：首次访问才解析 210KB+ 数据模块，避免 import 期冷启动。
_LEVEL_CACHE: Dict[str, frozenset] = {}


def _level_lemmas(level: str) -> frozenset:
    cached = _LEVEL_CACHE.get(level)
    if cached is None:
        cached = _load_a1_lemmas() if level == "A1" else _load_a2_lemmas()
        _LEVEL_CACHE[level] = cached
    return cached


async def run(payload: dict) -> dict:
    """纯函数词表覆盖统计。

    payload:
        tokens: [{text, lemma, pos}, ...]（必填，list）
        known_extra: [hw, ...] 可选调用方补充已知词，hw 小写比对
        levels: ["A1","A2"]（可选，默认 A1∪A2）——参与 known 基准的考纲等级
    return:
        {tokens_total, known_count, known_rate, unknown_ranked, level_hint}
    """
    # --- Guard Clauses：畸形 payload 快速失败（ADR-0009 纯函数纪律） ---
    raw_tokens = payload.get("tokens")
    if raw_tokens is None:
        raw_tokens = []
    if not isinstance(raw_tokens, list):
        raise ValueError("payload['tokens'] must be a list")

    tokens: List[Dict[str, Any]] = []
    for tok in raw_tokens:
        if not isinstance(tok, dict):
            raise ValueError("each token must be an object with a 'lemma' string")
        lemma = tok.get("lemma")
        if not isinstance(lemma, str):
            raise ValueError("each token must carry a string 'lemma'")
        tokens.append(tok)

    raw_levels = payload.get("levels")
    if raw_levels is None:
        levels = ["A1", "A2"]
    elif not isinstance(raw_levels, list):
        raise ValueError("payload['levels'] must be a list of exam levels")
    else:
        bad = [lv for lv in raw_levels if lv not in _ALLOWED_LEVELS]
        if bad:
            raise ValueError(f"unsupported exam level(s): {bad}; allowed {sorted(_ALLOWED_LEVELS)}")
        levels = raw_levels

    known_extra = payload.get("known_extra")
    if known_extra is None:
        known_extra = []
    if not isinstance(known_extra, list):
        raise ValueError("payload['known_extra'] must be a list")

    # --- 已知 lemma 集 = ∪(levels 考纲词 lemma) ∪ known_extra（小写） ---
    known_lemmas: set = set()
    for level in levels:
        known_lemmas |= _level_lemmas(level)
    for hw in known_extra:
        if isinstance(hw, str) and hw.strip():
            known_lemmas.add(hw.strip().lower())

    # --- 逐 token 判定 known / 未知词频统计 ---
    tokens_total = len(tokens)
    known_count = 0
    unknown_freq: Dict[str, int] = {}
    for tok in tokens:
        lemma = str(tok.get("lemma", "")).strip().lower()
        if lemma in known_lemmas:
            known_count += 1
        else:
            # 空 lemma 无法作为词项入排名，但计入未知（拉低覆盖率）。
            if lemma:
                unknown_freq[lemma] = unknown_freq.get(lemma, 0) + 1

    known_rate = round(known_count / tokens_total, _RATE_ROUND) if tokens_total else 0.0
    unknown_count = tokens_total - known_count

    # 频降序 + lemma 升序（稳定），封顶 _UNKNOWN_CAP。
    unknown_ranked = sorted(unknown_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:_UNKNOWN_CAP]
    unknown_ranked = [{"lemma": lemma, "count": cnt} for lemma, cnt in unknown_ranked]

    # --- level_hint 启发式 ---
    if tokens_total == 0:
        level_hint = "A1"  # 文档化：空输入 unknown_rate 定义作 0.0
    else:
        unknown_rate = unknown_count / tokens_total
        if unknown_rate <= 0.15:
            level_hint = "A1"
        elif unknown_rate <= 0.35:
            level_hint = "A2"
        else:
            level_hint = "B1"

    return {
        "tokens_total": tokens_total,
        "known_count": known_count,
        "known_rate": known_rate,
        "unknown_ranked": unknown_ranked,
        "level_hint": level_hint,
    }
