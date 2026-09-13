# -*- coding: utf-8 -*-
"""听写诊断引擎（听力微训工坊 Mode D）：词级 LCS 对齐 + 逐字分类归因。

纯标准库 + Pydantic v2，无 DB、无联网、无 spaCy——任意环境可本地运行。
词级 LCS 二维 DP 参照 static/js/writer.js 1040-1068 行；分类规则与
归因优先级见 docs/specs/2026-09-13-listening-micro-training-design.md §3。
"""

import itertools
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

TokenStatus = Literal["correct", "umlaut", "case", "inflection", "missing", "extra"]

# 首尾需要剥离的标点（比对用词干，原始词形保留在 token 字段）
_PUNCT_CHARS = ".,!?;:„“”\"'«»()[]{}—–-…·"

# 变音字符 → 基础形式（判定变音差；ß→ss 为长度变化的特例）
_UMLAUT_REPL = {"ü": "u", "ä": "a", "ö": "o", "é": "e", "ß": "ss"}
_UMLAUT_CHARS = frozenset(_UMLAUT_REPL)

# 常见屈折尾（-en/-e/-er/-es/-n/-s），用于词尾差判定
_INFLECTION_ENDINGS = ("en", "e", "er", "es", "n", "s")

# 功能词停用表（听力填空挖空时排除的候选；小写形式，可扩展）
_FUNCTION_WORDS = frozenset({
    # 冠词
    "der", "die", "das", "dem", "den", "des",
    "ein", "eine", "einen", "einem", "einer", "eines",
    # 代词
    "ich", "du", "er", "sie", "es", "wir", "ihr", "man",
    "mein", "dein", "sein", "mich", "dich", "mir", "dir", "uns", "euch",
    # 高频 be/have（功能化）
    "ist", "sind", "war", "waren", "bin", "bist", "hat", "haben", "hast",
    # 连词 / 疑问词
    "und", "oder", "aber", "wie", "was", "wann", "wo", "wer", "wen", "wem",
    "als", "dass", "denn",
    # 介词 / 副词 / 其它
    "zu", "zum", "zur", "mit", "auf", "an", "im", "in", "aus", "bei", "nach",
    "von", "vom", "für", "über", "um", "nicht", "ja", "nein", "so", "da",
    "hier", "sehr", "auch", "noch", "schon",
})


class TokenResult(BaseModel):
    """单个词的诊断结果：原始词形 + 归因状态 + 人话提示。"""

    token: str = Field(description="原始词形（含标点，未剥离）")
    status: TokenStatus
    hint: str = Field(default="", description="人话提示；correct 为空串")


class ListenDiagnosis(BaseModel):
    """整句听写诊断：对齐后的逐词结果 + 汇总计数与分数。"""

    expected: str
    actual: str
    tokens: list[TokenResult]
    correct: int
    total: int
    score: float


class ClozeItem(BaseModel):
    """听力填空挖空结果：挖空后的句子 + 答案 + 原文 + 被挖词位。"""

    text_with_blanks: str
    answer: str
    source: str
    blank_index: int


class _Word(NamedTuple):
    """切分后的词：raw 保留原始词形，core 为剥离首尾标点后的比对用形式。"""

    raw: str
    core: str


def _tokenize(text: str) -> list[_Word]:
    """按空白切词，并预计算每词剥离首尾标点后的比对形式。"""
    return [_Word(w, w.strip(_PUNCT_CHARS)) for w in text.split()]


def _umlaut_norm(s: str) -> str:
    """统一大小写并替换变音字符后的规范形，用于变音差判定。"""
    low = s.lower()
    return "".join(_UMLAUT_REPL.get(ch, ch) for ch in low)


def _is_umlaut(core_a: str, core_b: str) -> bool:
    """是否仅变音差：规范形一致、且至少一方含变音字符、且非纯大小写差。

    `core_a.lower() != core_b.lower()` 排除纯大小写差（如 Übung/ÜBUNG 应归 case，
    避免含变音字符的词被大小写差误归 umlaut）。
    """
    return (
        core_a.lower() != core_b.lower()
        and _umlaut_norm(core_a) == _umlaut_norm(core_b)
        and any(ch in core_a.lower() + core_b.lower() for ch in _UMLAUT_CHARS)
    )


def _umlaut_hint(core_a: str, core_b: str) -> str:
    """生成变音提示，如「变音：ä→a」；反向情况（如期望 ss、输入 ß）也支持。"""
    parts = [f"{ch}→{base}" for ch, base in _UMLAUT_REPL.items() if ch in core_a.lower()]
    if not parts:
        parts = [f"{base}→{ch}" for ch, base in _UMLAUT_REPL.items() if ch in core_b.lower()]
    return "变音：" + ", ".join(parts)


def _cut_ending(word: str, end: str) -> str | None:
    """去掉词尾 end 后的词干；不匹配或词太短返回 None。"""
    if len(word) <= len(end) or not word.endswith(end):
        return None
    return word[: -len(end)]


def _same_stem(core_a: str, core_b: str) -> bool:
    """词干相同判定：一方去掉一个常见屈折尾后与另一方（小写）一致。

    最短词长 <3 直接不判屈折（如 es/e、es/s 之类功能词短词，避免 -s/-e 尾误判）。
    """
    if min(len(core_a), len(core_b)) < 3:
        return False
    low_a = core_a.lower()
    low_b = core_b.lower()
    return any(
        low_b == _cut_ending(low_a, end) or low_a == _cut_ending(low_b, end)
        for end in _INFLECTION_ENDINGS
    )


def _relation(core_a: str, core_b: str) -> str:
    """两词比较关系：correct / umlaut / case / inflection / other（按优先级）。"""
    if core_a == core_b:
        return "correct"
    if _is_umlaut(core_a, core_b):
        return "umlaut"
    if core_a.lower() == core_b.lower():
        return "case"
    if _same_stem(core_a, core_b):
        return "inflection"
    return "other"


def _alignable(core_a: str, core_b: str) -> bool:
    """两词能否对齐：任一归因（正确/变音/大小写/屈折）成立即可。"""
    return _relation(core_a, core_b) != "other"


def _pair_result(core_a: str, core_b: str) -> tuple[TokenStatus, str]:
    """对齐对归因（调用方保证 _alignable 成立，rel 不会是 other）。"""
    rel = _relation(core_a, core_b)
    if rel == "correct":
        return "correct", ""
    if rel == "umlaut":
        return "umlaut", _umlaut_hint(core_a, core_b)
    if rel == "case":
        return "case", "大小写"
    return "inflection", "词尾"


def _lcs_table(exp_words: list[_Word], act_words: list[_Word]) -> list[list[int]]:
    """词级 LCS 二维 DP（参照 writer.js 的 Uint16 二维 DP 思路）。"""
    n, m = len(exp_words), len(act_words)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i, j in itertools.product(range(n), range(m)):
        if _alignable(exp_words[i].core, act_words[j].core):
            dp[i + 1][j + 1] = dp[i][j] + 1
        else:
            dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    return dp


def diagnose_diktat(expected: str, actual: str) -> ListenDiagnosis:
    """词级 LCS 对齐 + 逐字分类归因的听写诊断（纯函数）。

    - 按空白分词、剥离首尾标点后比对，token 保留原始词形
    - 对齐对按 完全匹配 > 变音 > 大小写 > 屈折 归因；未对齐的期望词=missing、输入词=extra
    - correct 为 correct 词数，total 为期望词数，score = correct/total（total 为 0 时取 0）
    """
    exp_words = _tokenize(expected)
    act_words = _tokenize(actual)
    dp = _lcs_table(exp_words, act_words)
    n, m = len(exp_words), len(act_words)

    # 回溯恢复对齐决策（逆序收集后反转；并列时优先判 extra，对齐 writer.js）
    decisions: list[tuple[str, TokenStatus, str]] = []
    i, j = n, m
    while i > 0 and j > 0:
        if _alignable(exp_words[i - 1].core, act_words[j - 1].core):
            status, hint = _pair_result(exp_words[i - 1].core, act_words[j - 1].core)
            decisions.append((exp_words[i - 1].raw, status, hint))
            i -= 1
            j -= 1
        elif dp[i][j - 1] >= dp[i - 1][j]:
            decisions.append((act_words[j - 1].raw, "extra", "多余"))
            j -= 1
        else:
            decisions.append((exp_words[i - 1].raw, "missing", "缺少"))
            i -= 1
    while i > 0:
        decisions.append((exp_words[i - 1].raw, "missing", "缺少"))
        i -= 1
    while j > 0:
        decisions.append((act_words[j - 1].raw, "extra", "多余"))
        j -= 1

    tokens = [TokenResult(token=raw, status=status, hint=hint) for raw, status, hint in reversed(decisions)]
    total = len(exp_words)
    correct = sum(1 for t in tokens if t.status == "correct")
    score = correct / total if total else 0.0
    return ListenDiagnosis(
        expected=expected,
        actual=actual,
        tokens=tokens,
        correct=correct,
        total=total,
        score=score,
    )


def _is_noun_candidate(words: list[_Word], idx: int) -> bool:
    """名词候选：非句首、首字符大写、且非功能词（德语名词首字母大写）。"""
    if idx == 0:
        return False
    core = words[idx].core
    return core[:1].isupper() and core.lower() not in _FUNCTION_WORDS


def _is_verb_candidate(words: list[_Word], idx: int) -> bool:
    """动词候选：词长 ≥3、常见动词词尾 -en/-n/-e、且非功能词（启发式，无 POS 依赖）。"""
    core = words[idx].core.lower()
    return len(core) >= 3 and core.endswith(("en", "n", "e")) and core not in _FUNCTION_WORDS


def make_cloze(sentence: str, level: str) -> ClozeItem | None:
    """听力填空挖空：名词优先、动词次之的启发式，每次只挖 1 个空。

    - 句子按空白分词后 <5 词，或无可挖候选（全功能词/全句首大写词）→ None
    - text_with_blanks 以 ___ 占位（前后保持单空格），answer 保留原词大小写/变音，
      blank_index 为被挖词在原句的词位（0 起），source 为原句原文
    - level 预留参数：当前 A1/A2 同策略，仅留扩展口
    """
    words = _tokenize(sentence)
    if len(words) < 5:
        return None
    pick = next((i for i, _ in enumerate(words) if _is_noun_candidate(words, i)), None)
    if pick is None:
        pick = next((i for i, _ in enumerate(words) if _is_verb_candidate(words, i)), None)
    if pick is None:
        return None
    blanks = ["___" if i == pick else w.raw for i, w in enumerate(words)]
    return ClozeItem(
        text_with_blanks=" ".join(blanks),
        answer=words[pick].core,
        source=sentence,
        blank_index=pick,
    )
