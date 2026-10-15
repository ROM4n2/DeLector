# -*- coding: utf-8 -*-
"""`SEED_CASES` 种子集数据自检（判定量仪器 A 的质量闸）。

背景（逐字对齐计划 Task 1 与设计稿 §3 仪器 A；2026-10-15 修订后）
---------------------------------------------------------------
本种子集是 §4.3 第 8 条对照实验的**唯一判决量**（`R_uncovered`：held-out 种子错误的
确定性回收率）的载体。每篇种子的注入分两类（`Injection.kind`）：

- `kind="probe"`（**判决量分子**，每篇 ≥3 处）：五类**未被任何检测器覆盖**的错误 ——
  「未被覆盖错误」的语义靠 held-out 层钉死；
- `kind="signal"`（**不进判决量**，每篇恰好 1 处）：属**语法族**、会被生产分流
  （`routes.main.violations_for` + `_text_kind`）计数 ⇒ 该篇 `v_0 == 1`；否则 A3 臂
  首轮即收敛、`A2 vs A3` 的自变量（裁判信号）恒为零（实测倒逼，见设计稿仪器 A 修订段）。

因此质量闸分五层：

1. **接口层**：`ERROR_CLASSES` 恰好五类且名字逐字正确；`SEED_CASES` 恰好 20 篇
   （10 篇书信底本 + 10 篇非书信散文底本，各 ≥10）；每篇恰好 1 处 signal（语法族、
   `expected_count == 1`）+ ≥3 处 probe。
2. **字符串层**：每处注入 `wrong → right` 的计数可逐条复算 —— `wrong` 只在注入文本
   里、`right` 只在修复文本里（判决量就是「`right` 是否回到文本」）。
3. **区间层**：signal 与所有 probe 的文字区间**逐处不相交**（`text` 坐标查 wrong 对
   wrong、`clean_text` 坐标查 right 对 right）。
4. **held-out 层（命门）**：五类 probe 注入 MUST NOT 被 `analyze_a1_email` 抓到 ——
   否则判决量被裁判自身污染。用**真实 nlp** 逐篇跑 probe 口径三重差分：
   a. `text` 的 rule 计数多重集 == `clean_text` + 恰好 signal 那一条；
   b. 把 signal 回退后，裁判条目（rule/level/message 三元组）逐条不变、差分恰好 1 条
      （比 a 更细：条目级而非计数级；span 因句内相对坐标不参与）；
   c. **逐处回退**（只把一处 probe 修回）后 rule 计数仍与 `text` 相等（防「注入 A 掩盖
      了注入 B 触发的违规」）。
5. **生产分流层**：用真实 nlp + `routes.main` 的**生产分流**逐篇断言被计数违规
   `len(...) == 1` 且该条 `rule` 名 == signal 的 `error_class`；再把 signal 回退 ⇒
   计数归零；底本自身也归零 ⇒ 「1 来自信号」是差分事实而非猜测（`v_0` 是 A3 是否真
   迭代的物理前提）。

纪律：检测器 `error_type` 集合 MUST 从 `delector/services/writing.py` **现读**
（禁抄名字列表 —— 抄了检测器改名/新增类型时本文件不会红）；`nlp` fixture 沿用
`tests/test_writing_rules.py` 的惯例。
"""

import dataclasses
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import spacy

from delector.data import a1_writing_dict, corpus_dict
from delector.data.a1_seed_errors import ERROR_CLASSES, SEED_CASES, Injection, SeedCase
from delector.routes.main import _LETTER_FORMAT_RULE_PREFIX, _text_kind, violations_for
from delector.services import writing as writing_service
from delector.services.writing import analyze_a1_email

# 任务书逐字指定的五个类名（这是对**本模块产出**的命名契约，不是检测器名单 ——
# 检测器的名字集合一律现读，见 test_error_classes_disjoint_from_detector_error_types）。
_REQUIRED_CLASS_NAMES = frozenset(
    {
        "nebensatz_wortstellung",
        "artikel_genus",
        "verb_kongruenz",
        "praeposition_kollokation",
        "nomen_grossschreibung",
    }
)

# 上游素材里那篇「散文集 MUST NOT 含」的书信体课文（a2_alltag_03 是 'Liebe Freunde...' 邀请信）。
_LETTER_LIKE_CORPUS_ID = "goethe_a2_alltag_03"


@pytest.fixture(scope="module")
def nlp():
    try:
        return spacy.load("de_core_news_sm")
    except OSError:
        pytest.skip("de_core_news_sm not installed")


def _rule_counts(analysis: dict[str, Any]) -> Counter:
    """违规 rule 计数多重集（violations + advisories 并集 —— held-out 判据的观察量）。"""
    return Counter(str(v["rule"]) for v in analysis["violations"] + analysis["advisories"])


def _entries(analysis: dict[str, Any]) -> Counter:
    """违规条目的**逐条身份**多重集（rule/level/message 三元组）。

    span 不进键：它是**句内相对坐标**（检测器以句首 base 折算，见 `_tok_off`），跨句
    比较会退化成数字巧合 —— 条目级差分用三元组即可逐条钉死「信号之外零变化」。
    """
    return Counter(
        (str(v["rule"]), str(v["level"]), str(v["message"])) for v in analysis["violations"] + analysis["advisories"]
    )


def _occurrences(haystack: str, needle: str) -> list[tuple[int, int]]:
    """needle 在 haystack 中的所有出现区间（needle 为空 ⇒ 空集，防无界循环）。"""
    if not needle:
        return []
    out: list[tuple[int, int]] = []
    start = haystack.find(needle)
    while start != -1:
        out.append((start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    return out


def _single_signal(case: SeedCase) -> Injection:
    """该篇唯一的 signal 注入（数量不为 1 直接红 —— 供各用例复用）。"""
    signals = [inj for inj in case.injections if inj.kind == "signal"]
    assert len(signals) == 1, f"{case.id}: 应有恰好 1 处 signal，实际 {len(signals)}"
    return signals[0]


def _probes(case: SeedCase) -> list[Injection]:
    """该篇全部 probe 注入（判决量分子）。"""
    return [inj for inj in case.injections if inj.kind == "probe"]


# ── 接口层 ────────────────────────────────────────────────────────────────────


def test_error_classes_exactly_five_required_names():
    """`ERROR_CLASSES` 恰好五类，名字逐字等于任务书的五个（顺序不约束）。"""
    assert len(ERROR_CLASSES) == 5
    assert set(ERROR_CLASSES) == _REQUIRED_CLASS_NAMES
    assert all(isinstance(name, str) and name for name in ERROR_CLASSES)


def test_error_classes_disjoint_from_detector_error_types():
    """五类 MUST 与 `writing.py` 现读的检测器 `error_type` 零交集（**禁抄名单**）。

    现读方式：逐行扫 `delector/services/writing.py`，凡含 `error_type` 的行，取其行内
    全部字母/下划线引号字面量（覆盖 `"error_type": "artikel"` 与
    `error_type = "praeposition" if ... else "kasus"` 两种形态）。下限断言（≥6）防
    「正则失效 ⇒ 抽出空集 ⇒ 零交集假绿」。附：格式族 `a1_*` 规则名一并纳入禁区。
    """
    src = Path(str(writing_service.__file__)).read_text(encoding="utf-8")
    literal = re.compile(r'"([A-Za-z_]+)"')
    detector_types: set[str] = set()
    for line in src.splitlines():
        if "error_type" in line:
            detector_types.update(literal.findall(line))
    assert len(detector_types) >= 6, f"现读 error_type 少于 6 个（正则失效？）：{sorted(detector_types)}"
    assert set(ERROR_CLASSES) & detector_types == set(), (
        f"ERROR_CLASSES 与检测器 error_type 有交集：{sorted(set(ERROR_CLASSES) & detector_types)}"
    )
    a1_rules = set(re.findall(r'"(a1_[a-z_]+)"', src))
    assert a1_rules, "格式族规则名现读为空（正则失效？）"
    assert set(ERROR_CLASSES) & a1_rules == set(), (
        f"ERROR_CLASSES 与格式族规则名有交集：{sorted(set(ERROR_CLASSES) & a1_rules)}"
    )


def test_seed_cases_total_and_families():
    """恰好 20 篇 / id 唯一 / 两类底本（`letter_` / `prose_` 前缀）各 ≥10 篇。"""
    ids = [case.id for case in SEED_CASES]
    assert len(ids) == 20, f"SEED_CASES 恰好 20 篇（冻结样本集），实际 {len(ids)}"
    assert len(set(ids)) == len(ids), f"id 必须唯一：{sorted(i for i in ids if ids.count(i) > 1)}"
    letters = [i for i in ids if i.startswith("letter_")]
    prose = [i for i in ids if i.startswith("prose_")]
    assert len(letters) >= 10, f"书信底本 ≥10 篇，实际 {len(letters)}"
    assert len(prose) >= 10, f"非书信散文底本 ≥10 篇，实际 {len(prose)}"
    assert len(letters) + len(prose) == len(ids), "存在既非 letter_ 也非 prose_ 前缀的 id"


def test_seed_cases_are_frozen_slots_dataclasses():
    """接口形状逐字：字段名/顺序 + frozen + slots + `kind` 取值域（防类型与序列化漂移）。"""
    assert [f.name for f in dataclasses.fields(SeedCase)] == ["id", "text", "clean_text", "injections"]
    assert [f.name for f in dataclasses.fields(Injection)] == [
        "error_class",
        "kind",
        "wrong",
        "right",
        "expected_count",
    ]
    for case in SEED_CASES:
        assert isinstance(case, SeedCase)
        assert not hasattr(case, "__dict__"), f"{case.id}: slots=True 的实例不应有 __dict__"
        assert isinstance(case.injections, list)
        with pytest.raises(dataclasses.FrozenInstanceError):
            case.text = "mutated"
        for inj in case.injections:
            assert isinstance(inj, Injection)
            assert inj.kind in ("signal", "probe"), f"{case.id}: kind 取值仅 signal/probe，实际 {inj.kind!r}"
            with pytest.raises(dataclasses.FrozenInstanceError):
                inj.wrong = "mutated"


def test_every_case_has_at_least_three_probes():
    """每篇 probe ≥3 处（判决量分子下界；signal 不顶替 probe 数）。"""
    for case in SEED_CASES:
        probes = _probes(case)
        assert len(probes) >= 3, f"{case.id} probe 数 {len(probes)} < 3"


def test_every_case_has_exactly_one_signal():
    """每篇恰好 1 处 signal：语法族（非 `a1_*` 格式族、非 held-out 类名）、count 恰 1。"""
    for case in SEED_CASES:
        signals = [inj for inj in case.injections if inj.kind == "signal"]
        assert len(signals) == 1, f"{case.id} signal 数 {len(signals)} != 1"
        sig = signals[0]
        assert sig.error_class not in ERROR_CLASSES, (
            f"{case.id}: signal 的 error_class 不得取 held-out 类名（{sig.error_class!r}）"
        )
        assert not sig.error_class.startswith(_LETTER_FORMAT_RULE_PREFIX), (
            f"{case.id}: signal MUST 属语法族（现读生产前缀 {_LETTER_FORMAT_RULE_PREFIX!r}），"
            f"不得用格式族名 {sig.error_class!r}"
        )
        assert sig.expected_count == 1, f"{case.id}: signal 的 expected_count 应恰为 1，实际 {sig.expected_count}"


def test_all_five_classes_actually_used_in_probes():
    """五类 held-out 都必须真的出现在 **probe** 里（signal 的语法族名不参与本集合）。"""
    used = {inj.error_class for case in SEED_CASES for inj in _probes(case)}
    assert used == set(ERROR_CLASSES), (
        f"probe 类名集合与 ERROR_CLASSES 不等：missing={sorted(set(ERROR_CLASSES) - used)} "
        f"unknown={sorted(used - set(ERROR_CLASSES))}"
    )


def test_clean_texts_anchor_to_in_repo_sources():
    """底本 MUST 取自仓内既有真实素材（不许自造）：clean_text 与上游逐字一致且互不相同。

    - 书信篇：`clean_text` ∈ `A1_SCHREIBEN_TEIL2[*].sample_email`（官方范文，修复目标）；
    - 散文篇：`clean_text` ∈ `OFFICIAL_CORPUS[*].content` 且 MUST NOT 是那篇书信体课文；
    - 20 篇底本互不相同（10 篇书信互异 ∈ 10 篇范文 ⇒ 恰好覆盖全部；散文同理）。
    """
    sample_emails = {ex["sample_email"] for ex in a1_writing_dict.A1_SCHREIBEN_TEIL2}
    corpus_texts = {item["content"] for item in corpus_dict.OFFICIAL_CORPUS}
    letter_like = {
        item["content"] for item in corpus_dict.OFFICIAL_CORPUS if item["id"] == _LETTER_LIKE_CORPUS_ID
    }
    assert len(sample_emails) == 10 and len(letter_like) == 1
    cleans = [case.clean_text for case in SEED_CASES]
    assert len(set(cleans)) == len(cleans), "底本不得重复（每篇应来自不同素材）"
    for case in SEED_CASES:
        if case.id.startswith("letter_"):
            assert case.clean_text in sample_emails, f"{case.id}: clean_text 不是官方 sample_email 的逐字复制"
        else:
            assert case.clean_text in corpus_texts, f"{case.id}: clean_text 不是 OFFICIAL_CORPUS 课文的逐字复制"
            assert case.clean_text not in letter_like, f"{case.id}: 散文集 MUST NOT 使用书信体课文"


# ── 字符串层（逐篇参数化）─────────────────────────────────────────────────────


@pytest.mark.parametrize("case", SEED_CASES, ids=lambda c: c.id)
def test_string_level_consistency(case):
    """每处注入（signal 与 probe 同口径）的 `wrong → right` 计数可逐条复算。"""
    assert case.text != case.clean_text, f"{case.id}: text 不得等于 clean_text"
    for inj in case.injections:
        assert isinstance(inj.expected_count, int) and inj.expected_count >= 1
        assert inj.wrong and inj.right, f"{case.id}/{inj.error_class}: wrong/right 不得为空"
        assert inj.wrong != inj.right, f"{case.id}/{inj.error_class}: wrong 不得等于 right"
        assert case.text.count(inj.wrong) == inj.expected_count, (
            f"{case.id}/{inj.error_class}: text 中 wrong 计数 {case.text.count(inj.wrong)} != {inj.expected_count}；"
            f"wrong={inj.wrong!r}"
        )
        assert case.clean_text.count(inj.wrong) == 0, (
            f"{case.id}/{inj.error_class}: clean_text 中 wrong 应 0 次；wrong={inj.wrong!r}"
        )
        assert case.clean_text.count(inj.right) == inj.expected_count, (
            f"{case.id}/{inj.error_class}: clean_text 中 right 计数 {case.clean_text.count(inj.right)} "
            f"!= {inj.expected_count}；right={inj.right!r}"
        )
    # 双向回放：两文本的差异 MUST 恰好是注入本身（防「text 手改」式的与注入无关的偏差）。
    replayed = case.clean_text
    for inj in case.injections:
        replayed = replayed.replace(inj.right, inj.wrong)
    assert replayed == case.text, f"{case.id}: text 必须恰好等于对 clean_text 回放全部注入的结果"
    repaired = case.text
    for inj in case.injections:
        repaired = repaired.replace(inj.wrong, inj.right)
    assert repaired == case.clean_text, f"{case.id}: 回放全部修复必须恰好还原 clean_text"


# ── 区间层（逐篇参数化）───────────────────────────────────────────────────────


@pytest.mark.parametrize("case", SEED_CASES, ids=lambda c: c.id)
def test_signal_and_probe_ranges_are_pairwise_disjoint(case):
    """signal 的文字区间 MUST NOT 与任何 probe 的区间相交（两坐标系逐处断言）。

    - `text` 坐标：signal.wrong 的每次出现 vs 每个 probe.wrong 的每次出现；
    - `clean_text` 坐标：signal.right 的每次出现 vs 每个 probe.right 的每次出现。
    这就是「信号不得落在探针区里（反之亦然）」的机械可判定形式。
    """
    signal = _single_signal(case)
    for text, sig_key, probe_key in (
        (case.text, signal.wrong, "wrong"),
        (case.clean_text, signal.right, "right"),
    ):
        sig_areas = _occurrences(text, sig_key)
        assert sig_areas, f"{case.id}: signal.{probe_key} 在对应文本中 0 次出现"
        for probe in _probes(case):
            p_key = probe.wrong if probe_key == "wrong" else probe.right
            for p_start, p_end in _occurrences(text, p_key):
                for s_start, s_end in sig_areas:
                    assert not (s_start < p_end and p_start < s_end), (
                        f"{case.id}: signal.{probe_key}={sig_key!r} 区间 {(s_start, s_end)} 与 probe"
                        f"（{probe.error_class}）.{probe_key}={p_key!r} 区间 {(p_start, p_end)} 相交"
                    )


# ── held-out 层（真实 nlp，逐篇参数化；probe 口径三重差分）────────────────────


@pytest.mark.parametrize("case", SEED_CASES, ids=lambda c: c.id)
def test_probe_injections_are_held_out_from_detectors(case, nlp):
    """probe 注入 MUST NOT 被 `analyze_a1_email` 抓到（violations + advisories 两键）。

    signal 是**唯一**允许改变裁判输出的注入（且只允许 +1 条自己的规则）——
    把 signal 回退后的「纯 probe 文本」裁判输出 MUST 与底本逐条相等。
    """
    signal = _single_signal(case)
    clean_analysis = analyze_a1_email(case.clean_text, nlp=nlp)
    text_analysis = analyze_a1_email(case.text, nlp=nlp)
    clean_counts = _rule_counts(clean_analysis)

    # a. 整体差分：text 计数 == clean 计数 + 恰好 signal 那一条（probe 对裁判零可见）。
    text_counts = _rule_counts(text_analysis)
    assert text_counts == clean_counts + Counter({signal.error_class: 1}), (
        f"{case.id}: text 计数 != clean + signal 一条（text={dict(text_counts)} clean={dict(clean_counts)}）"
    )

    # a2. 回退 signal ⇒ 纯 probe 文本的计数 MUST 与底本完全相等。
    assert case.text.count(signal.wrong) == 1, f"{case.id}: signal.wrong 在 text 中应恰 1 次"
    probe_only_text = case.text.replace(signal.wrong, signal.right, 1)
    probe_only_analysis = analyze_a1_email(probe_only_text, nlp=nlp)
    probe_only_counts = _rule_counts(probe_only_analysis)
    assert probe_only_counts == clean_counts, (
        f"{case.id}: 纯 probe 文本的裁判计数 != 底本（{dict(probe_only_counts)} vs {dict(clean_counts)}）"
    )

    # b. 条目级差分：删掉 signal 的 entry 后，裁判输出逐条（rule/level/message）不变。
    entries_text = _entries(text_analysis)
    entries_probe_only = _entries(probe_only_analysis)
    only_text = entries_text - entries_probe_only
    only_probe_only = entries_probe_only - entries_text
    assert not only_probe_only, f"{case.id}: 信号回退引入了新裁判条目：{dict(only_probe_only)}"
    assert sum(only_text.values()) == 1, f"{case.id}: 信号必须恰好带来 1 条裁判条目，实际 {dict(only_text)}"
    assert next(iter(only_text))[0] == signal.error_class, (
        f"{case.id}: 信号带来的条目 rule 应为 {signal.error_class!r}，实际 {next(iter(only_text))[0]!r}"
    )

    # c. 逐处回退（只修一处 probe）后计数仍等于 text（防「注入 A 掩盖注入 B 的违规」）。
    for inj in _probes(case):
        patched = case.text.replace(inj.wrong, inj.right, 1)
        patched_counts = _rule_counts(analyze_a1_email(patched, nlp=nlp))
        assert patched_counts == text_counts, (
            f"{case.id}/{inj.error_class}: 只回退该处后裁判计数 != text（{dict(patched_counts)} vs "
            f"{dict(text_counts)}）—— 该 probe 与其它注入/底本有隐藏交互"
        )

    print(
        f"[held-out ok] {case.id}: family={'letter' if case.id.startswith('letter_') else 'prose'} "
        f"probes={len(_probes(case))} signal_rule={signal.error_class} rules={dict(text_counts)}"
    )


# ── 生产分流层（真实 nlp；v_0 == 1 的物理事实）───────────────────────────────


@pytest.mark.parametrize("case", SEED_CASES, ids=lambda c: c.id)
def test_signal_is_counted_as_exactly_one_violation_under_production_routing(case, nlp):
    """生产分流下每篇恰 1 条被计数违规，且就是 signal 那条（`v_0 == 1`，A3 才会真迭代）。

    - `len(violations_for(_text_kind(verdict), verdict)) == 1`；
    - 该条 `rule` == signal 的 `error_class`（证明它来自信号而非别的）；
    - 回退 signal ⇒ 计数归零；底本文本自身也归零 ⇒ 归因是**差分事实**而非猜测。
    """
    signal = _single_signal(case)
    expected_kind = "letter" if case.id.startswith("letter_") else "prose"
    verdict = analyze_a1_email(case.text, nlp=nlp)
    kind = _text_kind(verdict)
    assert kind == expected_kind, f"{case.id}: 文本族判定 {kind!r} != 期望 {expected_kind!r}"
    counted = violations_for(kind, verdict)
    counted_rules = [str(v["rule"]) for v in counted]
    assert len(counted) == 1, f"{case.id}: v_0 应为 1，实际 {len(counted)}（rules={counted_rules}）"
    assert str(counted[0]["rule"]) == signal.error_class, (
        f"{case.id}: 被计数条 rule 应为 signal 的 {signal.error_class!r}，实际 {counted_rules!r}"
    )

    no_signal = case.text.replace(signal.wrong, signal.right, 1)
    verdict_no_signal = analyze_a1_email(no_signal, nlp=nlp)
    counted_no_signal = violations_for(_text_kind(verdict_no_signal), verdict_no_signal)
    assert counted_no_signal == [], (
        f"{case.id}: 回退 signal 后仍有被计数违规：{[str(v['rule']) for v in counted_no_signal]}"
    )
    verdict_clean = analyze_a1_email(case.clean_text, nlp=nlp)
    counted_clean = violations_for(_text_kind(verdict_clean), verdict_clean)
    assert counted_clean == [], (
        f"{case.id}: 底本自身有被计数违规：{[str(v['rule']) for v in counted_clean]}"
    )

    print(
        f"[v0] {case.id}: family={kind} probes={len(_probes(case))} "
        f"signal={signal.error_class!r} counted_rule={counted_rules[0]!r} v0={len(counted)}"
    )
