# -*- coding: utf-8 -*-
"""A1 裁判候选维度的 FP 标定实验（Task 6 的 AFK 半：**只标定，不接线**）。

为什么存在
----------
计划 docs/plans/2026-10-15-a1-judge-expansion.md 的 Task 6 要在两条候选维度
（情态动词框架语序 / 过去时间锚与时态一致性）上回答一个问题：**把它们接进
A1 裁判的误报代价有多大**。误报比漏报危险（模型会去"修"一个不存在的错误），
所以裁决（接线为 error / 降级 warning / 不做）是 HITL，由人拿本脚本产出的
原始数据拍板 —— **本脚本不下这个结论**。

探测实现只住在本脚本里（计划原文：可不进 writing.py），**不得**接进
`analyze_a1_email`；它们是"探针"而不是"规则"。

为什么两条探测都刻意绕开 spaCy 的依存连接（实测，2026-10-15，de_core_news_sm）
------------------------------------------------------------------------------
错误句 `Ich muss gehen heute nach Hause.`：
    spaCy: muss=AUX/dep=nk、gehen=VERB/ROOT 且被误标 VerbForm=Fin（本应为 Inf）；
    正确句 `Ich muss heute nach Hause gehen.` 下同一对词是 muss=ROOT、gehen=oc/Inf。
错误句 `Sie muss machen die Hausaufgaben heute.`：
    spaCy: muss=ADV/dep=mo（连动词词性都错了）、machen=VERB/ROOT。
错误句 `Du kannst helfen mir bei der Hausaufgabe.`：
    spaCy: kannst=VERB/dep=sb（荒谬）、helfen=VERB/ROOT/Inf。
范文 email_05 里 `kannst` 的 lemma 是垃圾值 "kannstn"；范文 email_06 里
`muss` 被标 Tense=Past。且整篇解析与单句解析不一致（"Kannst du ... mitbringen?"
整篇=VERB/ROOT、单句=PROPN/ROOT）。

⇒ A 维探测用「情态动词表面形式表 + 位置 + 实词 POS 检查」、B 维用「时间锚词表 +
morph 时态」——都不依赖 dep 边的正确性。这不改变一个事实：探测在真实文本上的
FP 率由本脚本的样本集来量化。

样本集
------
- 正样本：`delector/data/a1_writing_dict.py` 的 `A1_SCHREIBEN_TEIL2` 全部 10 篇
  官方 sample_email（期望误报 = 0）。
- 负样本：每维 ≥5 句手工定向错误句 + 正确对照组（逐句标注期望；对照组期望
  "不报" —— 没有对照组，FP/FN 无法分开）。
- 切句为确定性标点规则 `(?<=\\D[.!?])\\s+`（数字缩写如 "15." 不切）：与 spaCy
  senter 的实测差异仅 1 处（email_06 落款 "Liebe Grüße\\nJulia" 多切一段
  无动词碎片，不影响这两维的判定），换来"切句零模型依赖 + 口径固定为单句解析"。

计数口径与裁决
--------------
per_candidate[i] = ``{name, fp, fn, fp_samples, fn_samples}``：
- ``fp`` = 正样本句误报数 + 对照组句误报数（两类都进 fp_samples，带来源前缀）；
- ``fn`` = 定向错误句漏报数（进 fn_samples，带来源前缀）。
``verdict`` 只给"实测值与建议阈值的对照"（error 档 / warning 档的条件是否
成立），**不写"建议做/不做"** —— 裁决归 HITL。
另：A 维附**样本外追补**（OUT_OF_SAMPLE_A，3 句逗号并列正确句；2026-10-15 评审
追补实测 3/3 被 A 维误报）——**不入任何计数**：原文与 live 结果打印在 CLI
「样本外追补（不入计数）」区块，结论（含 warning 档翻档影响）并入 A 维
``verdict``。防止产物读者以冻结表的 0 误报外推出"A 维真实文本 FP≈0"。

退出码
------
0 = 标定完成；1 = 样本集自身无效（空样本 / 标注缺失 / JSON 结构错误）；
2 = 环境不可用（spaCy 未安装 / 德语模型加载失败；**绝不**触发 ``spacy.cli.download`` ——
与 ``processor.try_load_nlp_no_download`` 同纪律）。

可复跑：同输入同输出（无随机、无时间、无网络；切句为确定性正则）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, TypedDict

# 允许从任意 CWD 直接 `python tools/bench_judge_fp.py` 运行（同 tools/ 其余脚本约定）。
# 注意：这里**只**注入路径、不 import 仓库模块 —— 仓库 import 全部延迟到函数内
# （import 期零重依赖、零副作用；E402 也无从触发）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# --------------------------------------------------------------------------- #
# 类型与常量
# --------------------------------------------------------------------------- #

#: 四分类标签：TP=期望报且报；FN=期望报却漏；FP=期望不报却报；TN=期望不报且没报。
OutcomeLabel = Literal["TP", "TN", "FP", "FN"]

#: 模型候选顺序**复制自** processor.SPACY_MODEL_CANDIDATES（不 import：本脚本
#: 不应拉起 delector 的依赖链；顺序不一致会让标定口径和产品漂移，改这里时必须
#: 同步 `delector/nlp_engine/processor.py:23`）。
MODEL_CANDIDATES: Tuple[str, ...] = ("de_core_news_md", "de_core_news_sm")

#: verdict 的建议阈值（**脚本算"条件是否成立"，不替人裁决**）：
#: error 档 = 零误报（正样本句 + 对照组句）且零漏报；warning 档 = 各容忍少量。
ERROR_POS_FP_MAX = 0
ERROR_CTRL_FP_MAX = 0
ERROR_FN_MAX = 0
WARN_POS_FP_MAX = 1
WARN_CTRL_FP_MAX = 1
WARN_FN_MAX = 2

#: 确定性切句：句末标点后跟空白才切；`\\D` 防 "vom 15. bis 18. August" 这类
#: 数字缩写被切碎（实测：不加它会切出 "vom 15." / "bis 18." 碎片）。
_SENT_BOUNDARY = re.compile(r"(?<=\D[.!?])\s+")


@dataclass(frozen=True)
class LabeledSentence:
    """负样本条目：逐句标注期望（``expected=None`` = 标注缺失 ⇒ 样本集无效）。"""

    text: str
    expected: Optional[bool]
    note: str = ""


@dataclass(frozen=True)
class Candidate:
    """一条候选维度：名字 + 描述 + 句级探测（True = 报违规）。"""

    name: str
    description: str
    detect: Callable[[str], bool]


@dataclass(frozen=True)
class SentenceOutcome:
    """一个句子的评估结果（明细，供 CLI 打印与 fold 折叠）。"""

    label: OutcomeLabel
    kind: Literal["positive", "negative"]
    source: str
    expected: bool
    reported: bool
    text: str


class CandidateResult(TypedDict):
    """单条候选的标定计数（计划 Task 6 固定的 Report 形状）。"""

    name: str
    fp: int
    fn: int
    fp_samples: List[str]
    fn_samples: List[str]


class Report(TypedDict):
    """标定报告：per_candidate 计数 + verdict（只含量与阈值对照，不含裁决）。"""

    per_candidate: List[CandidateResult]
    verdict: Dict[str, str]


# --------------------------------------------------------------------------- #
# 探测实现（候选维度 A/B —— 只住脚本里，不接线）
# --------------------------------------------------------------------------- #

# 维度 A：情态动词表面形式表。为什么用"表面形式"而不是 lemma：
#   spaCy 的德语 lemma 实测会产出垃圾（kannst→kannstn、muss→Muss），不可依赖。
# 覆盖六大情态动词的现在时/过去时/第二虚拟式全部常见变位（60+ 形式）。
_MODAL_SURFACE_FORMS = frozenset({
    # können
    "kann", "kannst", "könnt", "können", "konnte", "konntest", "konnten", "konntet",
    "könnte", "könntest", "könnten", "könntet",
    # müssen
    "muss", "musst", "müsst", "müssen", "musste", "musstest", "mussten", "musstet",
    "müsste", "müsstest", "müssten", "müsstet",
    # wollen
    "will", "willst", "wollt", "wollen", "wollte", "wolltest", "wollten", "wolltet",
    # dürfen
    "darf", "darfst", "dürft", "dürfen", "durfte", "durftest", "durften", "durftet",
    "dürfte", "dürftest", "dürften", "dürftet",
    # sollen
    "soll", "sollst", "sollt", "sollen", "sollte", "solltest", "sollten", "solltet",
    # mögen（含 möchte 全系列；mochte 系列兼收无变音符号的 möchte 误拼）
    "mag", "magst", "mögt", "mögen", "mochte", "mochtest", "mochten", "mochtet",
    "möchte", "möchtest", "möchten", "möchtet",
})

# 维度 A：触发"框架被拆开"的实词 POS（功能词/标点/动词本身都不算）。
_CONTENT_POS = frozenset({"NOUN", "PROPN", "PRON", "ADJ", "ADV", "NUM"})

# 维度 B：过去时间锚（决定性锚定过去的副词；含无变音符号转写）。
_PAST_ANCHOR_ADVERBS = frozenset({
    "gestern", "vorgestern", "damals", "früher", "frueher",
    "neulich", "kürzlich", "kuerzlich", "ehemals",
})
# 维度 B：letzte/letzten/... + 时间名词 才是锚（单独 "letzte" 可能是"末班车"）。
_LETZTE_FORMS = frozenset({"letzte", "letzten", "letzter", "letztes"})
_TIME_NOUNS = frozenset({
    "woche", "wochen", "monat", "monaten", "jahr", "jahren",
    "wochenende", "mal", "sommer", "winter", "tag", "tagen",
})
# 维度 B：现在时形式的完成时助动词（haben/sein）——句中存在 Partizip II 时豁免。
# 例：`Gestern habe ich eine Suppe gekocht.` 的 habe 是现在时形态但整体是过去语义。
_PERFECT_AUX_PRES = frozenset({"habe", "hast", "hat", "haben", "habt", "bin", "bist", "ist", "sind", "seid"})

# spaCy 惰性加载的进程内缓存（import 期不加载、不联网；加载失败不写缓存）。
_NLP: Any = None
_NLP_MODEL_NAME: str = ""


def _load_nlp() -> Any:
    """惰性加载德语模型（缓存）。spaCy 缺失 / 全部候选失败一律抛 RuntimeError；**绝不下载**。"""
    global _NLP, _NLP_MODEL_NAME
    if _NLP is not None:
        return _NLP
    try:
        import spacy  # 惰性：import 期不引入 spacy（本脚本直接运行时的启动成本也在意）
    except ImportError as exc:  # 裸外泄会拿到未捕获异常的 rc=1，与"样本集无效"撞语义 ⇒ 归一为 RuntimeError
        raise RuntimeError(f"spaCy 未安装（本脚本不自动安装、不触发下载）：{exc}") from exc

    errors: List[str] = []
    for name in MODEL_CANDIDATES:
        try:
            _NLP = spacy.load(name)
            _NLP_MODEL_NAME = name
            return _NLP
        except Exception as exc:  # 该候选加载失败 ⇒ 继续试下一个；全部失败才抛 RuntimeError
            errors.append(f"{name}: {exc}")
    raise RuntimeError("德语模型加载失败（不自动下载；请先安装 de_core_news_sm）：" + " | ".join(errors))


def get_loaded_model_name() -> str:
    """返回实际生效的模型名（未加载时为空串）。"""
    return _NLP_MODEL_NAME


def probe_environment(load_nlp: Optional[Callable[[], Any]] = None) -> Optional[str]:
    """环境探测（"退出码 2 = 环境不可用"的单一归口）：可用返回 None，不可用返回原因文本。

    ``load_nlp`` 仅供测试注入（默认 ``_load_nlp``）；同时兜住两类环境故障：
    spaCy 未安装（ImportError，原始形态）与德语模型加载失败（RuntimeError，
    见 ``_load_nlp`` 的归一化）。**绝不**触发 ``spacy.cli.download`` —— 与
    ``processor.try_load_nlp_no_download`` 同纪律。
    """
    loader = _load_nlp if load_nlp is None else load_nlp
    try:
        loader()
    except (RuntimeError, ImportError) as exc:
        return str(exc)
    return None


def _is_zu_infinitive(tokens: Sequence[Any], index: int) -> bool:
    """判断 index 处的不定式是否属于 zu-Infinitiv（如 `etwas zu trinken`）。

    zu-Inf 不是情态框架的一部分：`Kannst du ... etwas zu trinken mitbringen?`
    里的 trinken 若被误当框架动词，正确范文会被误报 —— 排除它是保 FP=0 的关键。
    """
    return index > 0 and tokens[index - 1].pos_ == "PART" and tokens[index - 1].lower_ == "zu"


def _detect_modal_frame_order(sentence: str) -> bool:
    """候选维度 A：主句情态框架（情态动词 + 句末不定式）疑似被拆开 ⇒ True。

    判据（表面形式 + 位置 + 实词 POS 检查，**刻意不用 dep 连接与 morph**，理由见模块 docstring）：
      1. 找句中第一个情态动词表面形式 W；
      2. 找 W 之后第一个动词 V（跳过 zu-不定式）；
      3. 若 V 之后（在遇到下一个从句/并列引导词 SCONJ/CCONJ 之前）还有实词
         （名词/代词/形容词/副词/数词）⇒ 框架动词不在末尾 ⇒ 报。

    已知边界（未覆盖，如实登记；2026-10-15 实测）：
      - 机制：探测**仅按 SCONJ/CCONJ 断句，不识别从句/并列结构** —— 从句内框架被不被
        报，只看实词落在末位动词之后（`..., dass ich muss gehen heute.` 会报）还是夹在
        情态动词与末位动词之间（`..., dass ich muss heute arbeiten.` 不报；负样本 err7
        即此族，**整族不可见**）；
      - 逗号并列主句（`Ich kann nicht kommen, ich muss arbeiten.`）**会误报**（FP 方向；
        第二分句主语 PRON 触发实词检查）。样本外追补原文见 ``OUT_OF_SAMPLE_A``（不入计数）。
    """
    doc = _load_nlp()(sentence)
    tokens = [t for t in doc if not t.is_space]
    w_index: Optional[int] = None
    for i, token in enumerate(tokens):
        if token.lower_ in _MODAL_SURFACE_FORMS:
            w_index = i
            break
    if w_index is None:
        return False
    v_index: Optional[int] = None
    for i in range(w_index + 1, len(tokens)):
        if tokens[i].pos_ == "VERB" and not _is_zu_infinitive(tokens, i):
            v_index = i
            break
    if v_index is None:
        return False
    for token in tokens[v_index + 1:]:
        if token.pos_ in ("SCONJ", "CCONJ"):
            break  # 从句/并列分句从引导词开始 ≠ 主句 Mittelfeld（`..., weil ...` / `und ...`）
        if token.pos_ in _CONTENT_POS:
            return True
    return False


def _has_past_anchor(tokens: Sequence[Any]) -> bool:
    """句中是否含过去时间锚（副词表 或 letzte-系 + 时间名词）。"""
    for i, token in enumerate(tokens):
        if token.lower_ in _PAST_ANCHOR_ADVERBS:
            return True
        if token.lower_ in _LETZTE_FORMS and i + 1 < len(tokens) and tokens[i + 1].lower_ in _TIME_NOUNS:
            return True
    return False


def _detect_past_anchor_tense_conflict(sentence: str) -> bool:
    """候选维度 B：过去时间锚 + 现在时限定动词（非完成时结构）⇒ True。

    判据（词表 + morph）：
      1. 句中含过去时间锚（gestern / letzte Woche / damals ...）；
      2. 存在 morph VerbForm=Fin 且 Tense=Pres 的动词；
      3. 豁免完成时结构：句中存在 Partizip II（VerbForm=Part 的 VERB）时，
         haben/sein 的现在时形式不触发（`Gestern habe ich ... gekocht.` 是正确句）。

    已知边界（未覆盖，如实登记）：`Gestern muss ich müde gewesen sein.` 这类
    "情态词 + 完成时不定式"的正确推测句会被误报；`Morgen`/`am Samstag` 等
    中性/未来时间表达不在锚表内（`Morgen fahre ich ...` 正确不报）。
    """
    doc = _load_nlp()(sentence)
    tokens = [t for t in doc if not t.is_space]
    if not _has_past_anchor(tokens):
        return False
    has_partizip = any(t.pos_ == "VERB" and "Part" in t.morph.get("VerbForm") for t in tokens)
    for token in tokens:
        if "Fin" in token.morph.get("VerbForm") and "Pres" in token.morph.get("Tense"):
            if has_partizip and token.lower_ in _PERFECT_AUX_PRES:
                continue
            return True
    return False


# --------------------------------------------------------------------------- #
# 样本集：正样本装载 + 负样本（逐句标注期望；错句与正确对照组配对）
# --------------------------------------------------------------------------- #


def load_positives() -> List[Tuple[str, str]]:
    """装载正样本：A1_SCHREIBEN_TEIL2 全部 10 篇官方 sample_email。

    返回 ``[(email_id, sample_email), ...]``（顺序 = 数据文件顺序，deterministic）。
    """
    from delector.data.a1_writing_dict import A1_SCHREIBEN_TEIL2  # 延迟 import（见模块头）

    return [(str(entry["id"]), str(entry["sample_email"])) for entry in A1_SCHREIBEN_TEIL2]


# 负样本集（内置；`--negatives` 可覆盖）。每维 = 定向错误句（expected=True）
# + 正确对照组（expected=False）。构造依据如下：错误句取"情态框架拆裂"
# 与"过去锚+现在时"两个高频学生错误族；对照组是修正版 + 边界守卫
# （从句框架 / 完成时 / 未来现在时）。
NEGATIVES: Dict[str, Tuple[LabeledSentence, ...]] = {
    "a_modal_frame_order": (
        LabeledSentence("Ich muss gehen heute nach Hause.", True, "err1_verb_vorgezogen"),
        LabeledSentence("Ich kann besuchen dich morgen.", True, "err2_verb_vorgezogen"),
        LabeledSentence("Wir wollen fahren am Wochenende nach Berlin.", True, "err3_verb_vorgezogen"),
        LabeledSentence("Er will kaufen ein neues Auto.", True, "err4_verb_vorgezogen"),
        LabeledSentence("Sie muss machen die Hausaufgaben heute.", True, "err5_verb_vorgezogen"),
        LabeledSentence("Du kannst helfen mir bei der Hausaufgabe.", True, "err6_verb_vorgezogen"),
        LabeledSentence("Ich weiß, dass ich muss heute arbeiten.", True, "err7_nebensatz_klammer"),
        LabeledSentence("Ich muss heute nach Hause gehen.", False, "ctrl1_klammer_korrekt"),
        LabeledSentence("Ich kann dich morgen besuchen.", False, "ctrl2_klammer_korrekt"),
        LabeledSentence("Wir wollen am Wochenende nach Berlin fahren.", False, "ctrl3_klammer_korrekt"),
        LabeledSentence("Er will ein neues Auto kaufen.", False, "ctrl4_klammer_korrekt"),
        LabeledSentence("Sie muss die Hausaufgaben heute machen.", False, "ctrl5_klammer_korrekt"),
        LabeledSentence("Du kannst mir bei der Hausaufgabe helfen.", False, "ctrl6_klammer_korrekt"),
        LabeledSentence("Ich weiß, dass ich heute arbeiten muss.", False, "ctrl7_nebensatz_korrekt"),
    ),
    "b_past_anchor_tense_conflict": (
        LabeledSentence("Gestern gehe ich zur Schule.", True, "err1_praesens_statt_praeteritum"),
        LabeledSentence("Vorgestern koche ich eine Suppe.", True, "err2_praesens_statt_praeteritum"),
        LabeledSentence("Letzte Woche fahre ich nach Berlin.", True, "err3_praesens_statt_praeteritum"),
        LabeledSentence("Gestern kaufe ich ein Buch im Supermarkt.", True, "err4_praesens_statt_praeteritum"),
        LabeledSentence("Damals wohne ich in Hamburg.", True, "err5_praesens_statt_praeteritum"),
        LabeledSentence("Letztes Jahr arbeite ich in einer Firma.", True, "err6_praesens_statt_praeteritum"),
        LabeledSentence("Gestern habe ich eine Suppe koche.", True, "err7_kein_partizip"),
        LabeledSentence("Gestern ging ich zur Schule.", False, "ctrl1_praeteritum"),
        LabeledSentence("Gestern habe ich eine Suppe gekocht.", False, "ctrl2_perfekt"),
        LabeledSentence("Letzte Woche bin ich nach Berlin gefahren.", False, "ctrl3_perfekt"),
        LabeledSentence("Gestern kaufte ich ein Buch im Supermarkt.", False, "ctrl4_praeteritum"),
        LabeledSentence("Damals wohnte ich in Hamburg.", False, "ctrl5_praeteritum"),
        LabeledSentence("Morgen fahre ich nach Berlin.", False, "ctrl6_futur_praesens"),
    ),
}

#: A 维候选名（verdict 的样本外追补句与 CLI 追补区块按此名挂钩；同名键出现在
#: NEGATIVES / CANDIDATES 里，改名时三处必须同步）。
_A_MODAL_FRAME_NAME = "a_modal_frame_order"

#: A 维**样本外追补集**（**不入冻结集、不入任何计数**）。2026-10-15 评审追补实测：
#: 逗号并列的两个正确主句被误报 —— 第一分句情态框架的末位动词之后，"第二分句主语
#: PRON"命中实词检查（机制边界见 _detect_modal_frame_order docstring）。第 1 句为
#: 评审原记录句；本机 de_core_news_sm 复测 3 句均报 True —— 结果不硬编码，由
#: _out_of_sample_a_results() 现场实测（CLI 区块与 verdict 追补句同源）。
#: 此前这些实测量只住 docstring ⇒ 产物无痕迹、读者会误得"A 维真实文本 FP≈0"：
#: 产物必须自带反例（评审 RED 修复）。
OUT_OF_SAMPLE_A: Tuple[str, ...] = (
    "Ich kann nicht kommen, ich muss arbeiten.",
    "Er kann nicht kommen, er muss noch arbeiten.",
    "Wir können nicht kommen, wir müssen am Wochenende arbeiten.",
)


def _out_of_sample_a_results() -> List[Tuple[str, bool]]:
    """对 ``OUT_OF_SAMPLE_A`` 跑 A 维探测（live 实测；verdict 追补句与 CLI 区块共用）。"""
    return [(text, bool(_detect_modal_frame_order(text))) for text in OUT_OF_SAMPLE_A]


#: 内置候选（探测实现见上方；接线与否由 HITL 拍板，这里只定义"候选"）。
CANDIDATES: Tuple[Candidate, ...] = (
    Candidate(
        name="a_modal_frame_order",
        description="维度A：主句情态动词框架（情态动词 + 不定式末位）被拆开",
        detect=_detect_modal_frame_order,
    ),
    Candidate(
        name="b_past_anchor_tense_conflict",
        description="维度B：过去时间锚 + 现在时限定动词（非完成时结构）冲突",
        detect=_detect_past_anchor_tense_conflict,
    ),
)


def load_negatives_from_json(path: str) -> Dict[str, List[LabeledSentence]]:
    """从 JSON 装载负样本覆盖集（格式：``{维度名: [{text, expected, note?}, ...]}``）。

    结构错误抛 ValueError（CLI 转退出码 1）。条目缺 expected / 非 bool 一律
    记 expected=None ⇒ 由 validate_samples 报"标注缺失"（这正是退出码 1 的
    可测路径，见 tests/test_judge_fp_bench.py）。
    """
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("负样本 JSON 顶层必须是对象（{维度名: [条目, ...]}）")
    result: Dict[str, List[LabeledSentence]] = {}
    for dim, items in raw.items():
        if not isinstance(items, list):
            raise ValueError(f"负样本维度 {dim} 的值必须是列表")
        loaded: List[LabeledSentence] = []
        for j, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"负样本维度 {dim} 第 {j + 1} 条必须是对象")
            text = item.get("text")
            if not isinstance(text, str):
                raise ValueError(f"负样本维度 {dim} 第 {j + 1} 条缺 text（或非字符串）")
            expected_raw = item.get("expected")
            expected: Optional[bool] = expected_raw if isinstance(expected_raw, bool) else None
            note = item.get("note")
            loaded.append(LabeledSentence(text, expected, note if isinstance(note, str) else ""))
        result[dim] = loaded
    return result


# --------------------------------------------------------------------------- #
# 校验与评估引擎
# --------------------------------------------------------------------------- #


def _split_sentences(text: str) -> List[str]:
    """确定性标点切句（不依赖模型；实测与 spaCy senter 的差异见模块 docstring）。"""
    flat = " ".join(text.split())
    return [part.strip() for part in _SENT_BOUNDARY.split(flat) if part.strip()]


def validate_samples(
    candidates: Sequence[Candidate],
    positives: Sequence[str],
    negatives: Mapping[str, Sequence[LabeledSentence]],
) -> List[str]:
    """校验样本集；返回问题列表（空列表 = 有效）。

    退出码语义：本函数非空 ⇔ CLI 退出码 1（"样本集自身无效"），覆盖两类
    致命情况：空样本（正样本空 / 某维负样本空）与标注缺失（expected=None）。
    """
    errors: List[str] = []
    if not candidates:
        errors.append("候选集为空：没有可标定的维度")
    if not positives:
        errors.append("正样本为空：无法标定误报（FP）")
    else:
        for i, text in enumerate(positives):
            if not text.strip():
                errors.append(f"正样本第 {i + 1} 篇为空文本")
    if not negatives:
        errors.append("负样本集为空：无法标定漏报（FN）")
    for candidate in candidates:
        items = negatives.get(candidate.name)
        if items is None:
            errors.append(f"候选 {candidate.name} 缺负样本集（键缺失）")
            continue
        if not items:
            errors.append(f"候选 {candidate.name} 的负样本集为空")
            continue
        for j, item in enumerate(items):
            if not item.text.strip():
                errors.append(f"{candidate.name} 第 {j + 1} 条负样本为空文本")
            if item.expected is None:
                errors.append(f"{candidate.name} 第 {j + 1} 条缺标注（expected 缺失）")
    return errors


def _classify(kind: Literal["positive", "negative"], expected: bool, reported: bool) -> OutcomeLabel:
    """四分类。正样本句 = 期望不报的 negative 同口径（expected=False）。"""
    if expected and reported:
        return "TP"
    if expected and not reported:
        return "FN"
    if (not expected) and reported:
        return "FP"
    return "TN"


def evaluate_candidate(
    candidate: Candidate,
    positives: Sequence[str],
    negatives: Sequence[LabeledSentence],
    positive_labels: Optional[Sequence[str]] = None,
) -> List[SentenceOutcome]:
    """逐句评估一条候选维度，返回明细（顺序确定：正样本在前、负样本在后）。

    ``positive_labels`` 仅影响明细/样例里的来源标识（CLI 传 email id；
    库调用默认 ``positive#N``）。
    """
    outcomes: List[SentenceOutcome] = []
    for i, text in enumerate(positives):
        source = positive_labels[i] if positive_labels is not None and i < len(positive_labels) else f"positive#{i + 1}"
        for sentence in _split_sentences(text):
            reported = bool(candidate.detect(sentence))
            outcomes.append(
                SentenceOutcome(_classify("positive", False, reported), "positive", source, False, reported, sentence)
            )
    for j, item in enumerate(negatives):
        if item.expected is None:
            raise ValueError(f"负样本第 {j + 1} 条缺标注（expected=None）：{item.text!r}（先跑 validate_samples）")
        source = item.note or f"negative#{j + 1}"
        reported = bool(candidate.detect(item.text))
        outcomes.append(
            SentenceOutcome(
                _classify("negative", item.expected, reported), "negative", source, item.expected, reported, item.text
            )
        )
    return outcomes


def _fold(name: str, outcomes: Sequence[SentenceOutcome]) -> CandidateResult:
    """把明细折叠成 per_candidate 计数（fp/fn + 样例全文）。"""
    fp_samples = [f"[{o.source}] {o.text}" for o in outcomes if o.label == "FP"]
    fn_samples = [f"[{o.source}] {o.text}" for o in outcomes if o.label == "FN"]
    return CandidateResult(
        name=name, fp=len(fp_samples), fn=len(fn_samples), fp_samples=fp_samples, fn_samples=fn_samples
    )


def _verdict_text(
    outcomes: Sequence[SentenceOutcome],
    out_of_sample: Optional[Sequence[Tuple[str, bool]]] = None,
) -> str:
    """生成 verdict 文本：只报"实测值 + 建议阈值对照"，裁决归 HITL。

    ``out_of_sample``（仅 A 维传入，见 ``OUT_OF_SAMPLE_A``）：**不入任何计数**的样本外
    live 实测；追补句必须同时出现在 text 与 ``--json`` 的 verdict（同一份 Report ⇒ 同源），
    防止产物读者以冻结表的 0 误报外推"A 维真实文本 FP≈0"。
    """
    pos = [o for o in outcomes if o.kind == "positive"]
    neg = [o for o in outcomes if o.kind == "negative"]
    pos_fp = [o for o in pos if o.label == "FP"]
    neg_err = [o for o in neg if o.expected]
    neg_ctrl = [o for o in neg if not o.expected]
    fn = [o for o in neg_err if o.label == "FN"]
    ctrl_fp = [o for o in neg_ctrl if o.label == "FP"]
    error_ok = len(pos_fp) <= ERROR_POS_FP_MAX and len(ctrl_fp) <= ERROR_CTRL_FP_MAX and len(fn) <= ERROR_FN_MAX
    warn_ok = len(pos_fp) <= WARN_POS_FP_MAX and len(ctrl_fp) <= WARN_CTRL_FP_MAX and len(fn) <= WARN_FN_MAX
    text = (
        f"实测：正样本误报 {len(pos_fp)}/{len(pos)} 句；负样本定向错误句漏报 {len(fn)}/{len(neg_err)} 句；"
        f"正确对照组误报 {len(ctrl_fp)}/{len(neg_ctrl)} 句。"
        f"建议阈值对照：error 档「正样本 FP<={ERROR_POS_FP_MAX} 且 对照组 FP<={ERROR_CTRL_FP_MAX} "
        f"且 FN<={ERROR_FN_MAX}」⇒ 条件{'成立' if error_ok else '不成立'}；"
        f"warning 档「正样本 FP<={WARN_POS_FP_MAX} 且 对照组 FP<={WARN_CTRL_FP_MAX} 且 FN<={WARN_FN_MAX}」"
        f"⇒ 条件{'成立' if warn_ok else '不成立'}。"
        f"裁决（接线为 error / 降级 warning / 不做）归 HITL，本脚本只报量与阈值对照，不下结论。"
    )
    if out_of_sample:
        hits = sum(1 for _text, reported in out_of_sample if reported)
        table_fp = len(pos_fp) + len(ctrl_fp)
        text += (
            f"样本外追补实测（**未入本冻结集**，不计入上面任何计数）：逗号并列正确句"
            f"「{out_of_sample[0][0]}」等 {len(out_of_sample)} 个变体中 {hits} 个报 True"
            f" ⇒ **真实文本 FP 不得以本表 {table_fp} 外推**"
        )
        if len(ctrl_fp) + hits > WARN_CTRL_FP_MAX:
            text += (
                f"；若将其计入对照组（对照组 FP={len(ctrl_fp)}+{hits}={len(ctrl_fp) + hits}"
                f" > WARN_CTRL_FP_MAX={WARN_CTRL_FP_MAX}）则 warning 档条件亦不成立"
            )
        text += "。"
    return text


def _evaluate_all(
    candidates: Sequence[Candidate],
    positives: Sequence[str],
    negatives: Mapping[str, Sequence[LabeledSentence]],
    positive_labels: Optional[Sequence[str]] = None,
) -> Tuple[Report, Dict[str, List[SentenceOutcome]]]:
    """评估全部候选：返回 (Report, 逐句明细)。CLI 用同一份明细打印原始结果（不二次计算）。

    A 维额外跑一次样本外追补 live 实测（``_out_of_sample_a_results``，**不入计数**）
    并把它并入该维 verdict（text 与 --json 同源）。
    """
    per_candidate: List[CandidateResult] = []
    details: Dict[str, List[SentenceOutcome]] = {}
    for candidate in candidates:
        outcomes = evaluate_candidate(candidate, positives, negatives[candidate.name], positive_labels)
        details[candidate.name] = outcomes
        per_candidate.append(_fold(candidate.name, outcomes))
    verdict: Dict[str, str] = {}
    for entry in per_candidate:
        out_of_sample = _out_of_sample_a_results() if entry["name"] == _A_MODAL_FRAME_NAME else None
        verdict[entry["name"]] = _verdict_text(details[entry["name"]], out_of_sample)
    report = Report(per_candidate=per_candidate, verdict=verdict)
    return report, details


def measure_candidates(
    candidates: Sequence[Candidate],
    positives: Sequence[str],
    negatives: Mapping[str, Sequence[LabeledSentence]],
) -> Report:
    """标定入口（可证伪签名，计划 Task 6）：样本集无效时抛 ValueError。

    返回 ``{per_candidate: [{name, fp, fn, fp_samples, fn_samples}, ...], verdict: {name: str}}``。
    环境不可用（spaCy 缺失 / 模型加载失败，见 ``_load_nlp``）由 detect 抛 RuntimeError；
    CLI 层用 ``probe_environment`` 预加载并把任何环境故障转成退出码 2。
    """
    errors = validate_samples(candidates, positives, negatives)
    if errors:
        raise ValueError("样本集无效：" + "；".join(errors))
    report, _details = _evaluate_all(candidates, positives, negatives)
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _print_out_of_sample_block() -> None:
    """CLI 独立区块：A 维样本外追补（**不入计数**）——3 句原文 + live 结果 + err7 族边界。

    评审 RED 修复：这些实测误报此前只住 docstring ⇒ 以产物为据的读者会误得
    "A 维真实文本 FP≈0"。结果与 verdict 追补句同源（``_out_of_sample_a_results``）。
    """
    results = _out_of_sample_a_results()
    print()
    print("--- 样本外追补（不入计数）---")
    print("逗号并列正确句（**不在**冻结样本集内、**不计入**任何 fp/fn；原文见模块常量 OUT_OF_SAMPLE_A）：")
    for text, reported in results:
        print(f"  [报={'True' if reported else 'False'}] {text}")
    print("结构性边界（漏报方向，2026-10-15 实测）：err7 族（实词夹在情态动词与末位动词之间，")
    print("如 `Ich weiß, dass ich muss heute arbeiten.`）**整族不可见** —— 探测只扫描末位动词")
    print("之后的实词；该边界与上列误报同为 HITL 判据的一部分，不允许只住 docstring。")


def _print_text_report(
    report: Report,
    details: Dict[str, List[SentenceOutcome]],
    candidates: Sequence[Candidate],
    positive_docs: int,
    positive_sentences: int,
) -> None:
    """文本模式：逐句原始结果 + 计数 + 样例全文（只报比例无法证伪判据，故必须打全文）。"""
    descriptions = {candidate.name: candidate.description for candidate in candidates}
    print("=== bench_judge_fp（A1 裁判候选维度 FP 标定实验；只标定不接线）===")
    print(f"model={get_loaded_model_name()}")
    print("positive_source=A1_SCHREIBEN_TEIL2（官方 sample_email，逐句评估）")
    print(f"positive_docs={positive_docs} positive_sentences={positive_sentences}")
    for entry in report["per_candidate"]:
        name = entry["name"]
        print()
        print(f"--- candidate: {name} ---")
        print(f"描述：{descriptions.get(name, '')}")
        print("逐句结果（TP=期望报且报；FN=期望报却漏；FP=期望不报却报；TN=期望不报且没报）：")
        for outcome in details[name]:
            print(f"  [{outcome.label}] [{outcome.source}] {outcome.text}")
        print(f"fp={entry['fp']} fn={entry['fn']}")
        print("误报样例（全文）：")
        if entry["fp_samples"]:
            for sample in entry["fp_samples"]:
                print(f"  - {sample}")
        else:
            print("  （无）")
        print("漏报样例（全文）：")
        if entry["fn_samples"]:
            for sample in entry["fn_samples"]:
                print(f"  - {sample}")
        else:
            print("  （无）")
        if name == _A_MODAL_FRAME_NAME:
            _print_out_of_sample_block()
    print()
    print("--- verdict（量与建议阈值对照；裁决归 HITL）---")
    for name, text in report["verdict"].items():
        print(f"verdict[{name}]={text}")
    print()
    print("退出码：0=标定完成；1=样本集自身无效（空样本/标注缺失）；2=环境不可用（spaCy 缺失/模型加载失败）")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。退出码：0=标定完成；1=样本集无效；2=环境不可用。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：德语字符需 UTF-8
        except Exception:  # 已关闭/不可重配置的流（如 pytest capture）⇒ 保持原状
            pass

    parser = argparse.ArgumentParser(description="A1 裁判候选维度 FP 标定实验（Task 6 AFK 半：只标定、不接线）。")
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出 Report（stdout；含 fp_samples/fn_samples 全文）",
    )
    parser.add_argument(
        "--negatives",
        metavar="PATH",
        default=None,
        help="覆盖内置负样本集（JSON：{维度名: [{text, expected, note?}, ...]}；缺标注 ⇒ 退出码 1）",
    )
    args = parser.parse_args(argv)

    try:
        if args.negatives is not None:
            negatives: Dict[str, List[LabeledSentence]] = load_negatives_from_json(args.negatives)
        else:
            negatives = {dim: list(items) for dim, items in NEGATIVES.items()}
    except (ValueError, OSError) as exc:
        print(f"[样本集无效] 负样本装载失败：{exc}", file=sys.stderr)
        return 1

    pairs = load_positives()
    positive_labels = [entry_id for entry_id, _ in pairs]
    positive_texts = [text for _, text in pairs]

    errors = validate_samples(CANDIDATES, positive_texts, negatives)
    if errors:
        print(f"[样本集无效] 共 {len(errors)} 个问题（退出码 1）：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    env_error = probe_environment()
    if env_error is not None:
        print(f"[环境不可用] {env_error}", file=sys.stderr)
        return 2

    report, details = _evaluate_all(CANDIDATES, positive_texts, negatives, positive_labels)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        positive_sentences = sum(len(_split_sentences(text)) for text in positive_texts)
        _print_text_report(report, details, CANDIDATES, len(positive_texts), positive_sentences)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
