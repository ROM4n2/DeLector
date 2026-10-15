# -*- coding: utf-8 -*-
"""德语写作本地规则引擎：冠词/格位一致 + 介词支配格。

只报高置信错误（宁可漏报不可误报）。nlp=None 时优雅返回零错误 + CEFR。
spaCy 模型由调用方注入（server 传 Android 安全加载的 nlp；测试直传 spacy.load）。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from delector.core.lexicon import lookup_core_vocab
from delector.data.a1_verb_case import A1_VERB_CASES

# 双格介词整组跳过（静动态依语境决定，纯规则极易误报）
_TWO_WAY_PREPS = {"in", "an", "auf", "über", "unter", "vor", "hinter", "neben", "zwischen"}

# 位置动词 + 双向介词时，习语搭配（如 stehen auf Akk=喜欢）易误伤真实位置 Dat/Akk
_LOC_VERBS_TWOWAY_COLLISION = {
    "stehen",
    "liegen",
    "sitzen",
    "hängen",
    "stellen",
    "legen",
    "setzen",
    "stecken",
    "bleiben",
}

# 固定单格介词 → 支配格（事实数据，参考 LanguageTool PrepositionToCases）
_PREP_CASE = {
    "mit": "Dat",
    "bei": "Dat",
    "nach": "Dat",
    "seit": "Dat",
    "aus": "Dat",
    "von": "Dat",
    "zu": "Dat",
    "gegenüber": "Dat",
    "entlang": "Akk",
    "ohne": "Akk",
    "für": "Akk",
    "gegen": "Akk",
    "durch": "Akk",
    "um": "Akk",
    "wegen": "Gen",
    "trotz": "Gen",
    "während": "Gen",
}

_CASE_NORM = {"nom": "Nom", "akk": "Akk", "acc": "Akk", "dat": "Dat", "gen": "Gen"}

# ── decline_determiner 查表（函数随句调用，常量一次性构造，避免每句重建 dict）──
_DEF_BY_GENDER = {
    "Masc": {"Nom": "der", "Akk": "den", "Dat": "dem", "Gen": "des"},
    "Fem": {"Nom": "die", "Akk": "die", "Dat": "der", "Gen": "der"},
    "Neut": {"Nom": "das", "Akk": "das", "Dat": "dem", "Gen": "des"},
}
_INDEF_BY_GENDER = {
    "Masc": {"Nom": "ein", "Akk": "einen", "Dat": "einem", "Gen": "eines"},
    "Fem": {"Nom": "eine", "Akk": "eine", "Dat": "einer", "Gen": "einer"},
    "Neut": {"Nom": "ein", "Akk": "ein", "Dat": "einem", "Gen": "eines"},
}
_OWNER_STEMS = {
    "kein": "kein",
    "mein": "mein",
    "dein": "dein",
    "sein": "sein",
    "ihr": "ihr",
    "unser": "unser",
    "euer": "euer",
    "eur": "euer",
}
_PLUR_ENDING_BY_CASE = {"Nom": "e", "Akk": "e", "Dat": "en", "Gen": "er"}
_SING_ENDING_BY_GENDER_CASE = {
    "Masc": {"Nom": "", "Akk": "en", "Dat": "em", "Gen": "es"},
    "Fem": {"Nom": "e", "Akk": "e", "Dat": "er", "Gen": "er"},
    "Neut": {"Nom": "", "Akk": "", "Dat": "em", "Gen": "es"},
}

# ── A1 日期归一（表单判题）与书信词表（email 判题）—— 每判一次都重建的常量 ──
_A1_MONTH_MAP = {
    "01": ["januar", "jan"],
    "02": ["februar", "feb"],
    "03": ["märz", "maerz", "mar"],
    "04": ["april", "apr"],
    "05": ["mai"],
    "06": ["juni", "jun"],
    "07": ["juli", "jul"],
    "08": ["august", "aug"],
    "09": ["september", "sep"],
    "10": ["oktober", "okt"],
    "11": ["november", "nov"],
    "12": ["dezember", "dez"],
}
_A1_DATE_PAT = re.compile(r"^(\d{1,2})\s*[\.]?\s*([a-zA-Zäöüß0-9]+)")
_A1_FORMAL_GREETINGS = ["sehr geehrte damen und herren", "sehr geehrte frau", "sehr geehrter herr"]
_A1_INFORMAL_GREETINGS = ["liebe", "lieber", "hallo", "guten tag", "hi"]
_A1_VALEDICTIONS = [
    "viele grüße",
    "herzliche grüße",
    "liebe grüße",
    "beste grüße",
    "schöne grüße",
    "mit freundlichen grüßen",
    "mit besten grüßen",
    "bis bald",
    "auf wiedersehen",
    "alles gute",
    "alles liebe",
    "herzlichen dank",
    "dein",
    "deine",
    "tschüss",
]
_A1_POLITE_PRONOUNS = {"Sie", "Ihr", "Ihre", "Ihren", "Ihrem", "Ihrer"}
_A1_PROPER_NOUNS = {
    "montag",
    "dienstag",
    "mittwoch",
    "donnerstag",
    "freitag",
    "samstag",
    "sonntag",
    "berlin",
    "münchen",
    "hamburg",
    "köln",
    "frankfurt",
    "deutschland",
    "österreich",
    "schweiz",
    "januar",
    "februar",
    "märz",
    "april",
    "mai",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "dezember",
}

_GENDER_NORM = {"masc": "Masc", "fem": "Fem", "neut": "Neut"}


def _first_morph(val: Any, default: Optional[str] = None) -> Optional[str]:
    """安全解包 spaCy morph 属性（list/tuple 或单个值）。"""
    if not val:
        return default
    if isinstance(val, (list, tuple)):
        return str(val[0]) if val else default
    return str(val)


def decline_determiner(lemma: str, gender: Optional[str], number: Optional[str], case: str) -> Optional[str]:
    """返回冠词/物主代词在 (gender, number, case) 下应取的表面形式；算不出返回 None。"""
    c = _CASE_NORM.get((case or "").lower())
    if not c:
        return None

    num_str = _first_morph(number, "Sing")
    num = "Plur" if (num_str or "").lower() in ("plur", "plural") else "Sing"
    gen_str = _first_morph(gender)
    g = _GENDER_NORM.get((gen_str or "").lower())
    lem = (lemma or "").lower().strip()

    # 定冠词
    if lem in ("der", "die", "das", "den", "dem", "des"):
        if num == "Plur":
            return {"Nom": "die", "Akk": "die", "Dat": "den", "Gen": "der"}[c]
        if not g:
            return None
        return _DEF_BY_GENDER[g][c]

    # 不定冠词（无复数）
    if lem in ("ein", "eine", "einen", "einem", "einer", "eines"):
        if num == "Plur" or not g:
            return None
        return _INDEF_BY_GENDER[g][c]

    # kein 与物主代词
    base_stem = None
    for k, v in _OWNER_STEMS.items():
        if lem == k or lem.startswith(k):
            base_stem = v
            break
    if base_stem:
        if num == "Plur":
            end = _PLUR_ENDING_BY_CASE[c]
            if base_stem == "euer":
                return "eur" + end if end else "euer"
            return base_stem + end
        if not g:
            return None
        end = _SING_ENDING_BY_GENDER_CASE[g][c]
        if base_stem == "euer":
            return "eur" + end if end else "euer"
        return base_stem + end

    return None


def _tok_off(tok: Any, base: int) -> Tuple[int, int]:
    """句内相对字符 offset。tok.idx 是文档级，需减去句首偏移。"""
    return tok.idx - base, tok.idx + len(tok.text) - base


def _np_det(noun_tok: Any) -> Optional[Any]:
    """返回名词的限定词子节点（dep 为 det/nk/pnc），没有返回 None。"""
    known_det_lemmas = {"der", "die", "das", "ein", "kein", "mein", "dein", "sein", "ihr", "unser", "euer", "eur"}
    known_det_texts = {
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "einer",
        "eines",
        "kein",
        "keine",
        "keinen",
        "keinem",
        "keiner",
        "keines",
    }
    for c in noun_tok.children:
        if c.pos_ in ("DET", "PRON") and c.dep_ in ("nk", "det", "pnc"):
            if c.lemma_.lower() in known_det_lemmas or c.text.lower() in known_det_texts:
                return c
    return None


def _prep_expected_case(tok: Any) -> Tuple[Optional[str], str]:
    """统一判定介词的预期支配格。
    返回 (expected_case_norm, source)，source 取值：
    - "collocation": 动词/形容词固定搭配
    - "twoway": 静动态双格介词 (in, auf...)
    - "fixed": 固有单格介词 (mit, ohne...)
    - "none": 未知/无法裁定
    """
    prep = tok.text.lower()
    verb_head = tok.head
    # 位置动词 + 双向介词时，习语搭配易误伤真实位置 → 优先按双向处理（只给 warning，不报 error）
    if verb_head and verb_head.lemma_ in _LOC_VERBS_TWOWAY_COLLISION and prep in _TWO_WAY_PREPS:
        return "Dat/Akk", "twoway"

    # 1. 动词/形容词固定搭配优先
    if verb_head and verb_head.pos_ in ("VERB", "AUX", "ADJ"):
        from delector.nlp_engine.linguistics import lookup_prep_collocations

        rows = lookup_prep_collocations(verb_head.lemma_) or lookup_prep_collocations(verb_head.text.lower())
        match = next((r for r in rows if r.get("praeposition", "").lower() == prep), None)
        if match:
            c = _CASE_NORM.get(match.get("kasus", "").lower())
            if c:
                return c, "collocation"

    # 2. 双格介词判定
    if prep in _TWO_WAY_PREPS:
        return "Dat/Akk", "twoway"

    # 3. entlang: 依位置决定支配格（前置=Genitiv，后置=Akkusativ）
    if prep == "entlang":
        obj = next((c for c in tok.children if c.dep_ in ("pobj", "op", "nk") and c.pos_ == "NOUN"), None)
        if obj:
            return ("Gen", "fixed") if tok.i < obj.i else ("Akk", "fixed")
        if verb_head and verb_head.pos_ in ("VERB", "AUX"):
            if any(c.pos_ == "NOUN" and c.i < tok.i for c in verb_head.children):
                return "Akk", "fixed"
        return "Akk", "fixed"

    # 4. 固定单格介词判定
    fixed = _PREP_CASE.get(prep)
    if fixed:
        return fixed, "fixed"

    return None, "none"


def detect_determiner_noun_agreement(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """规则 A：DET 与 head NOUN 的 case/gender 一致。"""
    spans = []
    dep_case_map = {"oa": "Akk", "da": "Dat", "sb": "Nom", "og": "Gen"}

    for tok in tokens:
        if tok.pos_ not in ("DET", "PRON") or tok.dep_ not in ("det", "nk", "pnc"):
            continue
        head = tok.head
        if head.pos_ != "NOUN":
            continue
        # 如果 head 直接受介词支配（如介词短语），交由 detect_preposition_case 统一裁定
        if head.head and head.head.pos_ == "ADP" and head.dep_ in ("nk", "pobj", "op"):
            continue

        # FP 守卫：属格定语间隔（des Mannes Haus）— DET 与 head 间夹有名词时，DET 实际归属中间名词而非 head
        if abs(tok.i - head.i) > 1:
            lo = min(tok.i, head.i)
            hi = max(tok.i, head.i)
            has_intervening_noun = False
            for mid in tokens:
                if lo < mid.i < hi:
                    # POS 直判 + 词典兜底（Mannes 被误标为 ADJ 但 lemma Mann 仍是 NOUN）
                    if mid.pos_ in ("NOUN", "PROPN"):
                        has_intervening_noun = True
                        break
                    di = lookup_core_vocab(mid.lemma_) or lookup_core_vocab(mid.text)
                    if di and di.get("pos") == "NOUN":
                        has_intervening_noun = True
                        break
                    # ADJ 误标但实为名词屈折（如 Mannes）
                    if mid.pos_ == "ADJ":
                        di2 = lookup_core_vocab(mid.text)
                        if di2 and di2.get("pos") == "NOUN":
                            has_intervening_noun = True
                            break
            if has_intervening_noun:
                continue

        dc_raw = _first_morph(tok.morph.get("Case"))
        dg_raw = _first_morph(tok.morph.get("Gender"))
        nc_raw = _first_morph(head.morph.get("Case"))
        ng_raw = _first_morph(head.morph.get("Gender"))

        dc = _CASE_NORM.get(dc_raw.lower()) if dc_raw else None
        dg = _GENDER_NORM.get(dg_raw.lower()) if dg_raw else None
        nc = _CASE_NORM.get(nc_raw.lower()) if nc_raw else None
        ng = _GENDER_NORM.get(ng_raw.lower()) if ng_raw else None

        # 优先查核心词典获取名词权威词性
        dict_info = lookup_core_vocab(head.lemma_) or lookup_core_vocab(head.text)
        real_gender = (dict_info.get("gender") if dict_info else None) or ng or dg

        slot_case = dep_case_map.get(head.dep_)
        expected_case = slot_case or nc

        # FP 守卫：双侧格信息与词性必须齐全
        if not dc or not expected_case or not real_gender:
            continue

        correct_det = decline_determiner(
            tok.lemma_, real_gender, _first_morph(head.morph.get("Number"), "Sing"), expected_case
        )
        if not correct_det:
            continue

        # 只有在表面形式确实不匹配时才报错
        if tok.text.lower() != correct_det.lower():
            start = min(tok.idx, head.idx) - base
            end = max(tok.idx + len(tok.text), head.idx + len(head.text)) - base
            spans.append(
                {
                    "severity": "error",
                    "error_type": "artikel",
                    "corrected_form": f"{correct_det} {head.text}",
                    "explanation_zh": (
                        f"「{head.text}」是{real_gender}性{expected_case}格，冠词应为"
                        f"「{correct_det}」而非「{tok.text}」。"
                    ),
                    "start": start,
                    "end": end,
                }
            )
    return spans


def detect_preposition_case(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """规则 B：固定单格介词 / 动词固定介词搭配 vs 介宾名词短语的实际格。"""
    spans = []
    for tok in tokens:
        if tok.pos_ != "ADP":
            continue
        prep = tok.text.lower()
        expected, source = _prep_expected_case(tok)
        if source in ("twoway", "none") or expected is None:
            continue

        error_type = "praeposition" if source == "collocation" else "kasus"
        verb_head = tok.head

        # 取介宾名词：ADP 的子节点里 dep 是 pobj/op/nk 的 NOUN
        obj = next((c for c in tok.children if c.dep_ in ("pobj", "op", "nk") and c.pos_ == "NOUN"), None)
        if obj is None and prep == "entlang":
            if verb_head and verb_head.pos_ in ("VERB", "AUX"):
                obj = next((c for c in verb_head.children if c.pos_ == "NOUN" and c.i < tok.i), None)
            if obj is None:
                for prev in reversed(tokens[: tok.i]):
                    if prev.pos_ == "NOUN":
                        obj = prev
                        break
        if obj is None:
            continue
        det = _np_det(obj)
        if det is None:
            # FP 守卫：无冠词的名词跳过（零冠词常见且通常正确）
            continue

        dict_info = lookup_core_vocab(obj.lemma_) or lookup_core_vocab(obj.text)
        real_gender = (
            (dict_info.get("gender") if dict_info else None)
            or _first_morph(obj.morph.get("Gender"))
            or _first_morph(det.morph.get("Gender"))
        )
        if not real_gender:
            continue

        form = decline_determiner(det.lemma_, real_gender, _first_morph(obj.morph.get("Number"), "Sing"), expected)
        if form is None:
            continue

        if det.text.lower() != form.lower():
            start = min(det.idx, obj.idx) - base
            end = max(det.idx + len(det.text), obj.idx + len(obj.text)) - base
            if error_type == "praeposition" and verb_head:
                expl = (
                    f"固定搭配「{verb_head.lemma_} {prep}」要求{expected}格，名词「{obj.text}」前应为"
                    f"「{form}」而非「{det.text}」。"
                )
            else:
                expl = f"介宾「{prep}」要求{expected}格，名词「{obj.text}」前应为「{form}」而非「{det.text}」。"
            spans.append(
                {
                    "severity": "error",
                    "error_type": error_type,
                    "corrected_form": f"{form} {obj.text}",
                    "explanation_zh": expl,
                    "start": start,
                    "end": end,
                }
            )
    return spans


# ── 规则 C：主谓一致（Number 一致）────────────────────────────────────────────
# FP 守卫③清单：Number 语义不可靠的形式/不定/指示代词作主语（spaCy 实测：
# 「Das sind meine Eltern.」里 das=Sing 而 sind=Plur —— 这是合法句 ⇒ 一律不判）。
_NUMBER_UNRELIABLE_SUBJECTS = {
    "man",
    "es",
    "das",
    "dies",
    "jemand",
    "niemand",
    "irgendwer",
    "wer",
    "was",
    "etwas",
    "nichts",
    "alles",
    "alle",
    "jeder",
    "manche",
    "mehrere",
    "viele",
    "einige",
}

# FP 守卫②清单：集合名词（语法格为单数，但常见误标/语义漂移风险）⇒ 不判。
_COLLECTIVE_NOUNS = {
    "familie",
    "gruppe",
    "team",
    "klasse",
    "mannschaft",
    "gesellschaft",
    "publikum",
    "polizei",
    "verein",
    "firma",
}

# 现在时第三人称复数与不定式同形（通则），唯一例外：
_IRREG_PLURAL_VERB_FORMS = {"sein": "sind"}


def _is_plural(num: Optional[str]) -> bool:
    return (num or "").lower() in ("plur", "plural")


def _subject_is_coordinated(subj: Any, verb: Any) -> bool:
    """FP 守卫①：主语含并列（sb 只代表第一个并列项，Number 属整个并列短语 ⇒ 不判）。

    实测结构：`Anna und Tom spielen` ⇒ sb=Anna(Sing)，`und`(CCONJ) 是 Anna 的孩子。
    """
    if subj.dep_ in ("cj", "cd"):
        return True
    if any(c.pos_ == "CCONJ" for c in subj.children):
        return True
    return any(c.dep_ in ("cj", "cd") and c.pos_ in ("NOUN", "PROPN", "PRON") for c in verb.children)


def _plural_verb_form(tok: Any) -> Optional[str]:
    """生成现在时第三人称复数形式；不确定 ⇒ None（调用方跳过 —— 宁漏不误）。"""
    if _first_morph(tok.morph.get("Tense")) != "Pres":
        return None
    lemma = (tok.lemma_ or "").lower().strip()
    if not lemma:
        return None
    return _IRREG_PLURAL_VERB_FORMS.get(lemma, lemma)


def detect_subject_verb_agreement(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """规则 C：主语（`dep=="sb"`）的 Number 与定式动词的 Number 不一致。

    只报「复数主语 + 单数定式动词」这一个方向（实测锚点：`Die Kinder spielt im Garten.`）；
    反向（单数主语 + 复数动词）不判 —— 单数第三人称形式不规则面大（hilft/liest/isst…），
    生成 `corrected_form` 不可靠 ⇒ 宁漏不误。

    FP 守卫（逐条实测标定；②—⑦ 缺一条就会在真实文本上大批误报，唯 ① 例外 —— 当前单向
    判据下它不可达/防御性、只会造成漏报、勿当有效拦截器）：
    ① 并列主语（`Anna und Tom spielen` —— sb 只挂第一个并列项；「复数主语＋单数动词」单向
    判定下此类句子的动词天然是复数、根本不进判定 ⇒ 该守卫当前不可达）；
    ② 集合名词（`die Familie`）；
    ③ `man` / 不定代词 / 形式主语（`Das sind meine Eltern.` 实测是合法句）；
    ④ 复合时态（`hat ... gemacht`：句含过去分词 ⇒ 整句不判，Number 落在助动词上）；
    ⑤ 数量词主语（`Zwei Stunden ist genug.` 实测是合法句 ⇒ 不判）；
    ⑥ 不定式/动词短语主语（`Bücher lesen ist schön.` ⇒ Number 不适用）；
    ⑦ 主语缺失（祈使句 / `es gibt` / 无 `sb` 的句子 ⇒ 天然零输出）。
    """
    spans: List[Dict[str, Any]] = []
    # FP 守卫④：句内存在过去分词（复合时态/被动）⇒ 整句不判。
    if any(_first_morph(t.morph.get("VerbForm")) == "Part" for t in tokens):
        return spans

    for subj in tokens:
        if subj.dep_ != "sb":
            continue
        verb = subj.head
        if verb is None or verb.pos_ not in ("VERB", "AUX"):
            continue
        if _first_morph(verb.morph.get("VerbForm")) != "Fin":
            continue
        # FP 守卫③：形式/不定代词主语
        if subj.text.lower() in _NUMBER_UNRELIABLE_SUBJECTS:
            continue
        if subj.lemma_ and subj.lemma_.lower() in _NUMBER_UNRELIABLE_SUBJECTS:
            continue
        # FP 守卫②：集合名词主语
        if subj.pos_ in ("NOUN", "PROPN") and subj.lemma_.lower() in _COLLECTIVE_NOUNS:
            continue
        # FP 守卫⑤：主语是数量词短语（实测 `Zwei Stunden ist genug.` 是合法句 ——
        # sb=Stunden(Plur) + ist(Sing)，德语里量词主语接单数动词是常见合法用法）。
        if any(c.pos_ == "NUM" for c in subj.children):
            continue
        # FP 守卫⑥：主语为不定式/动词短语（`Bücher lesen ist schön.`）⇒ Number 不适用。
        if subj.pos_ in ("VERB", "AUX") or _first_morph(subj.morph.get("VerbForm")) == "Inf":
            continue
        # FP 守卫①：并列主语
        if _subject_is_coordinated(subj, verb):
            continue

        s_num = _first_morph(subj.morph.get("Number"))
        if not s_num and subj.pos_ == "NOUN":
            det = _np_det(subj)
            s_num = _first_morph(det.morph.get("Number")) if det is not None else None
        v_num = _first_morph(verb.morph.get("Number"))
        if not s_num or not v_num:
            continue
        # 只报「复数主语 + 单数动词」方向（宁漏不误，见 docstring）。
        if not _is_plural(s_num) or _is_plural(v_num):
            continue

        correct = _plural_verb_form(verb)
        if not correct or correct.lower() == verb.text.lower():
            continue
        start, end = _tok_off(verb, base)
        spans.append(
            {
                "severity": "error",
                "error_type": "numerus",
                "corrected_form": correct,
                "explanation_zh": (
                    f"主语「{subj.text}」是复数，定式动词「{verb.text}」却是单数形式，应为「{correct}」。"
                ),
                "start": start,
                "end": end,
            }
        )
    return spans


# ── 规则 D：动词支配格（Rektion）──────────────────────────────────────────────
# 词表是人工登记的事实数据（逐条来源注释见 delector/data/a1_verb_case.py）。
_CASE_LABEL_ZH = {"Dat": "三格（Dativ）", "Acc": "四格（Akkusativ）"}


def detect_verb_case_government(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """规则 D：词表动词的支配格 vs 其宾语 NP 的实际格。

    实测锚点：`Ich helfe meinen Bruder.`（helfen 支配三格）⇒ 报 `meinem Bruder`；
    `Ich helfe meinem Bruder.` ⇒ 0 条。

    实现要点（FP 是敌人 ⇒ 宁漏不误）：
    - 只报**有冠词且单数**的宾语 NP：零冠词（`Ich danke dir.`）与复数宾语（Dat Plur 名词
      还需 -n 词尾，只换冠词会给出半对纠正）一律跳过；
    - 比对**表面形式 vs 目标格形式**（`decline_determiner`），不直判 `morph.Case` —— 实测
      `Ich helfe meiner Schwester.` 里 spaCy 把 Fem Dat 的 `meiner` 标成 `Gen`（同形歧义），
      直判 morph 会误报合法句；
    - 词表内标 `Dat+Acc` 的双宾动词（geben 等）不判；
    - **只比对「占用被支配格位」的宾语**（如实跑标定，见守卫⑧）：目标格 = `Acc` 时，动词四格位
      （`oa` 孩子）**已被占用**的情况下，`da` 宾语是**自由第三格**（`jdm. etw.` 构造，与
      `Ich öffne jdm. die Tür.` 同类）⇒ MUST 不判。

    FP 守卫：① 动词不在词表；② 反身（宾语是反身代词）；③ 可分前缀（`svp` 分裂前缀）；
    ④ 名词化（动词 token 带限定词孩子 / pos 非 VERB）；⑤ `Dat+Acc`；⑥ 代词/零冠词宾语；
    ⑦ 复数宾语；⑧ **自由第三格**（严格 `Acc` 动词 + 已有 `oa` 宾语时的 `da` 宾语）。

    守卫⑧ 的实跑锚点与取舍：`Ich lese meinem Bruder das Buch.` / `Ich suche meinem Bruder
    die Schuhe.` 里 spaCy 给 `Bruder` 打 `da`、给 `Buch`/`Schuhe` 打 `oa` —— 旧实现把所有
    `oa`/`da` 宾语都拿去比对 Acc 目标格 ⇒ 合法句被报 `meinen Bruder`。自由第三格是 A1 教材级
    普遍构造（`Ich öffne / wasche / lese / suche jdm. etw.`），故判据取「四格位已被 `oa` 占用时
    `da` 不判」；**代价（明知而接受）**：漏掉「本该 Dat 却写成 Acc 的双宾句」（人三物四里把三格
    写成 `meinen Bruder`）—— 宁漏不误。反证据 `Ich verstehe der Frage.`（`da` 宾语、无 `oa`
    兄弟 = 真实格错）MUST 仍报，用例见 tests/test_writing_rules.py。
    """
    spans: List[Dict[str, Any]] = []
    for tok in tokens:
        if tok.pos_ not in ("VERB", "AUX"):
            continue
        target = A1_VERB_CASES.get(tok.lemma_.lower())
        if target is None or target == "Dat+Acc":
            continue
        # 守卫③：可分前缀动词（`Ich rufe meine Mutter an.` —— an 的 dep=svp 且 head 是动词）
        if any(c.dep_ == "svp" for c in tok.children):
            continue
        # 守卫②：反身（`Ich freue mich ...` —— mich 的 pos=PRF / Reflex=Yes）
        if any(c.pos_ == "PRF" or _first_morph(c.morph.get("Reflex")) == "Yes" for c in tok.children):
            continue
        # 守卫④：名词化（`Das Lesen ...` —— 动词 token 带限定词孩子）
        if any(c.pos_ == "DET" for c in tok.children):
            continue

        # 守卫⑧（结构性 FP，实跑标定）：`oa` 孩子 = 该动词四格位已被占用的信号 ——
        # 严格 Acc 动词只有在四格位**空着**时，`da` 宾语才可能是「四格被写成三格」的错句
        # （`Ich verstehe der Frage.` ⇒ 实测 `da`、无 `oa` ⇒ 仍报）；四格位被占用时，`da` 宾语
        # 是自由第三格（`Ich lese/suche jdm. etw.`）⇒ MUST 不判。取舍见 docstring（宁漏不误）。
        has_accusative_object = any(c.dep_ == "oa" for c in tok.children)
        for obj in tok.children:
            if obj.pos_ != "NOUN" or obj.dep_ not in ("oa", "da"):
                continue
            if target == "Acc" and obj.dep_ == "da" and has_accusative_object:
                continue
            det = _np_det(obj)
            if det is None:
                continue  # 守卫⑥：零冠词 / 代词宾语
            number = _first_morph(obj.morph.get("Number")) or _first_morph(det.morph.get("Number"))
            if not number or _is_plural(number):
                continue  # 守卫⑦：复数宾语
            dict_info = lookup_core_vocab(obj.lemma_) or lookup_core_vocab(obj.text)
            real_gender = (
                (dict_info.get("gender") if dict_info else None)
                or _first_morph(obj.morph.get("Gender"))
                or _first_morph(det.morph.get("Gender"))
            )
            form = decline_determiner(det.lemma_, real_gender, number, target)
            if form is None or form.lower() == det.text.lower():
                continue  # 表面形式已是目标格 ⇒ 判定通过
            start = min(det.idx, obj.idx) - base
            end = max(det.idx + len(det.text), obj.idx + len(obj.text)) - base
            spans.append(
                {
                    "severity": "error",
                    "error_type": "rektion",
                    "corrected_form": f"{form} {obj.text}",
                    "explanation_zh": (
                        f"动词「{tok.lemma_}」支配{_CASE_LABEL_ZH.get(target, target)}，"
                        f"「{obj.text}」前应为「{form}」而非「{det.text}」。"
                    ),
                    "start": start,
                    "end": end,
                }
            )
    return spans


# ── 规则 E：主句动词位置（V2）────────────────────────────────────────────────
_FINITE_MOODS = {"Ind", "Imp", "Sub"}
# 非主句分句标记（德语 TIGER 依存标签，全部实测）：mo=从句谓词（`weil ich krank bin` 的 bin）
# · oc=宾语从句/引语内（`"Ich komme morgen."` 的 komme）· cp=从属连词提升 · cs=从属连词
# · cj/cd/cc=并列分句（`... und mein Bruder isst.` 的 isst）· rc/re=关系从句 · mnr/par=附加语。
_SUBORDINATE_DEPS = {"mo", "oc", "cp", "cs", "rc", "re", "mnr", "par", "cj", "cd", "cc"}
# 主语同一 NP 内部的依存标记（不算"额外前置成分"）。
_NP_INTERNAL_DEPS = {"det", "nk", "pnc", "ag", "app", "pn", "cc", "cd", "cj"}
_QUOTE_CHARS = {'"', "„", "“", "”", "«", "»", "‚", "‘", "’"}


def _is_finite_verb(tok: Any) -> bool:
    if tok.pos_ not in ("VERB", "AUX"):
        return False
    if _first_morph(tok.morph.get("VerbForm")) == "Fin":
        return True
    return _first_morph(tok.morph.get("Mood")) in _FINITE_MOODS


def _np_family_text(subj: Any, tokens: List[Any]) -> str:
    """主语 NP 的完整文本（含限定词/定语/并列项；用于生成 corrected_form）。"""
    members: Dict[int, Any] = {subj.i: subj}
    for _ in range(4):
        grew = False
        for t in tokens:
            if t.i in members or t.dep_ not in _NP_INTERNAL_DEPS:
                continue
            if t.head is not None and t.head.i in members:
                members[t.i] = t
                grew = True
        if not grew:
            break
    return " ".join(members[k].text for k in sorted(members))


# 焦点小词（Fokuspartikeln）—— **封闭词表**，只收「焦点标记」用法：语义上依附其后的成分
# （`Auch meine Familie ...` / `Nur mein Bruder ...`），A1 教材级普遍构造。
# MUST NOT 收：时间/频率/程度副词（`gestern / heute / morgen / jetzt / dann / sehr / oft` …）——
# 实测两者在 spaCy 里**同形**（dep=`mo`、head 直挂主语），一旦混入就会让错误语序负样本
# `Gestern ich habe gearbeitet.` 被豁免（V2 规则对 A1 最高频语序错永久失明，见用例
# `test_v2_focus_particles_closed_list_excludes_time_adverbs`）。
# 同理 MUST NOT 收 `erst / schon`：其主导用法是时间性状语（Vorfeld 位 ⇒ 正常 V2），
# 与焦点用法不可区分 ⇒ 宁漏不误。
_FOCUS_PARTICLES = frozenset(
    {
        "auch",
        "nur",
        "sogar",
        "eben",
        "genau",
        "gerade",
        "bloß",
        "allein",
        "insbesondere",
        "wenigstens",
        "zumindest",
        "ausgerechnet",
        "besonders",
        "lediglich",
        "speziell",
        "mindestens",
        "hauptsächlich",
    }
)


def _is_focus_particle_in_subject_np(tok: Any, subj: Any) -> bool:
    """tok 是否为**落在主语 NP 内部**的焦点小词（1~2 步进入主语名词或其限定词）。

    实测锚点（第三类 FP）：`Auch meine Familie wohnt in Berlin.` 的链 `Auch → Familie(sb)`（1 步）、
    `Nur mein Bruder kommt heute.` 的链 `Nur → mein(DET/`nk`) → Bruder(sb)`（2 步）—— 两条链上
    **都没有 ADJ**，故只靠「经过 ADJ」的判据整类漏掉 ⇒ 合法句被报 `Auch wohnt meine Familie`。
    中间节点 MUST 是主语 NP 内部成分（`_NP_INTERNAL_DEPS`：det/nk/…），否则不算 NP 内部。
    """
    if tok.text.lower() not in _FOCUS_PARTICLES:
        return False
    node = tok
    for _ in range(2):
        parent = node.head
        if parent is None or parent.i == node.i:
            return False
        if parent.i == subj.i:
            return True
        node = parent
        if node.dep_ not in _NP_INTERNAL_DEPS:
            return False
    return False


def _is_inside_subject_np(tok: Any, subj: Any) -> bool:
    """沿 head 链判定 tok 是否落在主语 NP 内部（主语 NP 的修饰链 / 焦点小词）。

    判据（逐条实测标定）：
    ① **焦点小词**（封闭词表 `_FOCUS_PARTICLES`）：head 链 1~2 步进入主语 NP ⇒ 参与构成主语 NP
       （`Auch meine Familie ...` / `Nur mein Bruder ...`，实测链上没有 ADJ ⇒ ② 覆盖不到）；
    ② 其余词：head 链回溯可达主语，**且路径上经过形容词（ADJ）**。
    - 实测锚点（B 类 FP）：`Meine sehr große Familie wohnt in Berlin.` 里 `sehr` 的链
      `sehr(ADV, mo) → große(ADJ, nk) → Familie(sb)` 经过 ADJ ⇒ 是主语 NP 内部修饰语、豁免；
    - 反例（MUST 继续报）：错误语序 `Gestern ich habe gearbeitet.` 里 spaCy 把状语
      `Gestern` 直接挂到主语 `ich` 上（`Gestern(ADV, mo) → ich(sb)`，实测），链上无 ADJ
      ⇒ 不算 NP 内部成分 —— 「链可达主语」单独使用会漏报该负样本（实测踩坑后收紧）；该反例也是
      ① 只能用**封闭词表**而不能用「形态相同即豁免」的原因（`Gestern` 与 `Auch` 的解析形态一致）。
    限步回溯，防解析异常成环。
    """
    if _is_focus_particle_in_subject_np(tok, subj):
        return True
    saw_adj = False
    node = tok
    for _ in range(8):
        parent = node.head
        if parent is None or parent.i == node.i:
            return False  # 抵达 ROOT（自环）仍未经过主语 ⇒ 不在主语 NP 内
        if node.pos_ == "ADJ":
            saw_adj = True
        if parent.i == subj.i:
            return saw_adj
        node = parent
    return False


def detect_verb_second_position(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """规则 E：主句定式动词 MUST 落在第二位置（V2）。

    实测锚点：`Gestern habe ich gearbeitet.` ⇒ 0 条；`Gestern ich habe gearbeitet.` ⇒ 报 1 条。

    主句判定**优先用 dep 而不是标点**：候选定式动词的 head 链上出现从句/并列标记
    （`mo`/`oc`/`cp`/`cj`/`cd`…）即非主句 ⇒ 不判 —— 实测 `weil ich krank bin` 里 `bin` 的
    dep=`mo`、引语内 `komme` 的 dep=`oc`、并列分句 `isst` 的 dep=`cj`。

    豁免面（逐条用例见 tests/test_writing_rules.py）：
    ① 从句 / ② 疑问句（含 `?` 或句首动词 V1）/ ③ 祈使句（Mood=Imp 或句首动词）/
    ④ 并列句第二分句 / ⑤ 直接引语（引号奇偶） / ⑥ 标题式片段（无主语 / 多主语 ⇒ 天然零输出）/
    ⑦ 主语与动词之间有逗号（称呼语 `Sehr geehrter Herr ...`、插入语）⇒ 宁漏不误；
    ⑧ 动词前出现换行（称呼语/行边界被并进同一句）⇒ Vorfeld 不跨行 ⇒ 宁漏不误。

    判据本体：主语在定式动词**之后**（Vorfeld 是别的成分）⇒ 天然合法，不判；主语在动词之前时，
    仅当主语左侧还有**独立于该主语 NP 的成分**才报 —— 故「Vorfeld = 多 token 短语」
    （`Gestern Abend habe ich gearbeitet.` / `Am Montag habe ich Zeit.`）不会误报。

    「独立于主语 NP」MUST 沿 head 链判定（判据本体见 `_is_inside_subject_np`，实测锚点
    `Meine sehr große Familie wohnt in Berlin.`：`sehr` 的 dep=`mo`、head 链
    `sehr → große(ADJ) → Familie（主语）` —— 只按 dep 白名单会把 `sehr` 当独立 Vorfeld 成分
    ⇒ 误报；豁免仅当链可达主语**且经过 ADJ** —— 否则错误语序句 `Gestern ich habe gearbeitet.`
    会被漏报，此为收紧后的实测行为）。

    第三类实跑 FP 与补丁：**焦点小词**（`Auch meine Familie wohnt in Berlin.` / `Nur mein Bruder
    kommt heute.`）的 head 链同样直挂主语 NP，但链上**没有 ADJ** ⇒ 上面那条判据整类漏掉、合法句被
    报。故豁免面增补：词 ∈ **封闭**焦点小词表 `_FOCUS_PARTICLES` 且 head 链 1~2 步进入主语 NP。
    时间/频率副词 MUST NOT 进表（`Gestern` 与 `Auch` 的解析形态实测一致，只能靠封闭词表区分）。
    """
    spans: List[Dict[str, Any]] = []
    if any(t.text == "?" for t in tokens):
        return spans  # 豁免②：疑问句（标点信号）
    for v in tokens:
        if not _is_finite_verb(v):
            continue
        if _first_morph(v.morph.get("Mood")) == "Imp":
            continue  # 豁免③：祈使句（形态信号）
        if v.i == 0:
            continue  # 豁免②③：句首动词（V1 疑问 / 祈使 / 片段）
        # 主句判定：head 链上出现从句/并列标记 ⇒ 该候选是子句谓词（豁免①④）。
        in_main = True
        node = v
        for _ in range(6):
            if node.dep_ in _SUBORDINATE_DEPS or node.pos_ == "SCONJ":
                in_main = False
                break
            parent = node.head
            if parent is None or parent.i == node.i:
                break  # 到达 ROOT 且链上无从句标记
            node = parent
        if not in_main:
            continue
        # 豁免⑤：直接引语（动词落在奇数个引号之后 ⇒ 处于引号对内）。
        if sum(1 for t in tokens if t.i < v.i and t.text in _QUOTE_CHARS) % 2 == 1:
            continue
        # 豁免⑥：无主语 / 多主语（含无人称被动、标题式片段）⇒ 天然零输出。
        # 多 sb 是解析不确定的信号：实测书信称呼语 `Sehr geehrter Herr Becker, ich interessiere ...`
        # 会给动词挂上两个 sb（`Herr` 与 `ich`）⇒ 必须跳过，否则官方范文被误报。
        subj_children = [c for c in v.children if c.dep_ == "sb"]
        if len(subj_children) != 1:
            continue
        subj = subj_children[0]
        # 豁免⑦：主语与动词之间有逗号（称呼语 / 插入语 `Ich, ehrlich gesagt, habe ...`）⇒ 宁漏不误。
        if any(t.pos_ == "PUNCT" and subj.i < t.i < v.i for t in tokens):
            continue
        # 主语在动词之后 ⇒ Vorfeld 已被别的成分占据，语序合法。
        if subj.i > v.i:
            continue
        # 豁免⑧：Vorfeld 不跨行 —— 定式动词之前出现换行（称呼语/行边界吸收进同一句）⇒ 该
        # "前置成分"只是上一行残留（实测官方范文 `Liebe Sarah,\n\nes tut mir leid ...` 被并句）。
        if any("\n" in t.text for t in tokens if t.i < v.i):
            continue
        # 主语左侧的 token（排除标点与空白）：只有“独立于主语 NP 的成分”才算额外前置成分。
        left = [t for t in tokens if t.i < v.i and t.i < subj.i and t.pos_ not in ("PUNCT", "SPACE")]
        if any(t.pos_ == "CCONJ" for t in left):
            continue  # 并列结构（解析复杂）⇒ 宁漏不误
        indep = [t for t in left if t.dep_ not in _NP_INTERNAL_DEPS and not _is_inside_subject_np(t, subj)]
        if not indep:
            continue  # 主语左侧只有它自己的 NP 内部成分（`Meine Eltern ...`）⇒ 合法 V2
        vorfeld = " ".join(t.text for t in sorted(indep, key=lambda x: x.i))
        corrected = f"{vorfeld} {v.text} {_np_family_text(subj, tokens)}"
        start, end = _tok_off(v, base)
        spans.append(
            {
                "severity": "error",
                "error_type": "wortstellung",
                "corrected_form": corrected,
                "explanation_zh": (
                    f"德语主句定式动词必须占第二位（V2）：动词「{v.text}」之前已有前置成分「{vorfeld}」，"
                    f"主语「{subj.text}」不应再插在动词前（应为「{corrected}」）。"
                ),
                "start": start,
                "end": end,
            }
        )
    return spans


def _collect_prep_hints(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """收集介词支配格内联提示。"""
    hints = []
    for tok in tokens:
        if tok.pos_ != "ADP":
            continue
        expected, source = _prep_expected_case(tok)
        if source == "twoway":
            label = f"{tok.text} [Dat/Akk]"
        elif expected:
            label = f"{tok.text} [{expected}]"
        else:
            continue
        start, end = _tok_off(tok, base)
        hints.append({"type": "prep_case", "label": label, "start": start, "end": end})
    return hints


def _collect_np_hints(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """收集名词短语实际格与性数内联提示。"""
    hints = []
    for tok in tokens:
        if tok.pos_ != "NOUN":
            continue
        det = _np_det(tok)

        # 格判断：名词 morph 优先，det morph 兜底
        c_raw = _first_morph(tok.morph.get("Case")) or (det and _first_morph(det.morph.get("Case")))
        c = _CASE_NORM.get(c_raw.lower()) if c_raw else None
        if not c:
            continue

        # 性判断：核心词典权威优先 -> 名词 morph -> 冠词 morph
        dict_info = lookup_core_vocab(tok.lemma_) or lookup_core_vocab(tok.text)
        g_raw = (
            (dict_info.get("gender") if dict_info else None)
            or _first_morph(tok.morph.get("Gender"))
            or (det and _first_morph(det.morph.get("Gender")))
        )
        g = _GENDER_NORM.get(g_raw.lower()) if g_raw else None

        if g:
            label = f"[{g}·{c}]"
        else:
            label = f"[{c}]"

        start, end = _tok_off(tok, base)
        hints.append({"type": "np_case", "label": label, "start": start, "end": end})
    return hints


def _collect_prep_warnings(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """收集双格介词提醒（warning 级：方向不确定，Dat/Akk 皆可）。"""
    warnings = []
    for tok in tokens:
        if tok.pos_ != "ADP":
            continue
        expected, source = _prep_expected_case(tok)
        if source == "twoway":
            start, end = _tok_off(tok, base)
            warnings.append(
                {
                    "severity": "warning",
                    "error_type": "twoway",
                    "label": f"注意：{tok.text} [Dat/Akk]",
                    "explanation_zh": (
                        f"「{tok.text}」是静动态双格介词：这里 Dat/Akk 皆可，请根据动作方向判断"
                        f"（静态用三格 Dativ，动态用四格 Akkusativ）。"
                    ),
                    "start": start,
                    "end": end,
                }
            )
    return warnings


def _cefr_basic(text: str) -> Dict[str, Any]:
    """词汇频率估测（MVP 简化：词数 + 基础说明）。"""
    words = [w for w in (text or "").split() if any(ch.isalpha() for ch in w)]
    return {"word_count": len(words), "recommended_level": "A1", "note_zh": "词汇频率估测，非写作能力分"}


def analyze_essay_text(text: str, nlp: Optional[Any] = None) -> Dict[str, Any]:
    """写作润色主分析入口。nlp=None 时优雅降级为零错误 + CEFR 估测。"""
    sentences: List[Dict[str, Any]] = []
    error_count = 0
    warning_count = 0

    if nlp is not None and text and text.strip():
        doc = nlp(text)
        for sent in doc.sents:
            toks = list(sent)
            if not toks:
                continue
            base = toks[0].idx
            spans = detect_determiner_noun_agreement(toks, base) + detect_preposition_case(toks, base)
            hints = _collect_prep_hints(toks, base) + _collect_np_hints(toks, base)
            warnings = _collect_prep_warnings(toks, base)
            sentences.append(
                {
                    "text": sent.text,
                    "spans": spans,
                    "hints": hints,
                    "warnings": warnings,
                }
            )
            error_count += len(spans)
            warning_count += len(warnings)

    cefr = _cefr_basic(text)
    return {
        "version": "4.3.0",
        "cefr": cefr,
        "error_count": error_count,
        "warning_count": warning_count,
        "problem_count": error_count + warning_count,
        "sentences": sentences,
    }


# ── Goethe-Zertifikat A1: Schreiben Evaluator & Diagnostician ───────────────


def check_a1_formular_answer(user_val: str, expected_val: str, aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Evaluates a user answer in Goethe A1 Teil 1 (Formular ausfuellen).
    Case-insensitive, normalizes punctuation, whitespace, and German date formats (e.g. 15.08 vs 15. August).
    """

    def _normalize(s: str) -> str:
        s = s.strip().lower()
        s = re.sub(r"[,;.!?/\\-]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    norm_user = _normalize(user_val)
    norm_exp = _normalize(expected_val)

    if not norm_user:
        return {"correct": False, "expected": expected_val, "user_answer": user_val}

    if norm_user == norm_exp:
        return {"correct": True, "expected": expected_val, "user_answer": user_val}

    # Check aliases
    if aliases:
        for alias in aliases:
            if norm_user == _normalize(alias):
                return {"correct": True, "expected": expected_val, "user_answer": user_val}

    # Date normalization: e.g. 15.08. vs 15. August
    m_user = _A1_DATE_PAT.match(norm_user)
    m_exp = _A1_DATE_PAT.match(norm_exp)
    if m_user and m_exp:
        day_u, mon_u = m_user.group(1).lstrip("0"), m_user.group(2).lower()
        day_e, mon_e = m_exp.group(1).lstrip("0"), m_exp.group(2).lower()
        if day_u == day_e:
            # Check month equivalence
            for num, names in _A1_MONTH_MAP.items():
                all_names = [num, num.lstrip("0")] + names
                if (mon_u in all_names) and (mon_e in all_names):
                    return {"correct": True, "expected": expected_val, "user_answer": user_val}

    return {"correct": False, "expected": expected_val, "user_answer": user_val}


def collect_violations(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把一次裁判输出规整为**统一违规形状**，且只保留 `level == "error"`（阻止收敛的那一类）。

    统一形状：`{"rule": str, "level": "error"|"warning", "message": str, "span": tuple[int, int] | None}`。

    抽取顺序（Task 1 新增，`只增不改` 的落地）：
    - **新键 `violations` 优先** —— `analyze_a1_email` 扩后的并列字段（格式族与语法族已按统一
      形状并列其中）；
    - 缺新键时回退 **legacy `suggestions`**（Task 4 起的旧形状），回退路径同样只取
      `level == "error"`。

    只取 error 的理由与 `polish_loop.default_violations_of` 一致：warning 是建议（字数偏短/
    偏多、称呼语缺逗号…），不构成"不达标"；把 warning 也算违规 ⇒ 几乎所有 A1 短文永远
    `v > 0` ⇒ 循环永不收敛，那才是真正的静默失败。
    """
    if not isinstance(analysis, dict):
        return []
    raw = analysis.get("violations")
    if isinstance(raw, list):
        source: List[Any] = raw
    else:
        legacy = analysis.get("suggestions")
        source = legacy if isinstance(legacy, list) else []
    out: List[Dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict) or item.get("level") != "error":
            continue
        span = item.get("span")
        span_t: Optional[Tuple[int, int]] = None
        if isinstance(span, (list, tuple)) and len(span) == 2:
            span_t = (int(span[0]), int(span[1]))
        out.append(
            {
                "rule": str(item.get("rule", "")),
                "level": "error",
                "message": str(item.get("message", "")),
                "span": span_t,
            }
        )
    return out


def analyze_a1_email(text: str, leitpunkte: Optional[List[str]] = None, nlp: Optional[Any] = None) -> Dict[str, Any]:
    """
    Automated evaluation and diagnostics for Goethe A1 Teil 2 (ca. 30 Woerter E-Mail/Brief).
    Checks:
    1. Anrede (Greeting) - presence, capitalization, comma rule.
    2. Lowercase start of main text after comma greeting.
    3. Grussformel (Valediction) - presence, comma prohibition (NO comma after Viele Gruesse!).
    4. Word count recommendation (25-35 words).
    5. Leitpunkte coverage hints.

    追加并列字段（Task 1/2，只增不改；既有键逐字不动）：
    - `violations`：统一形状 `{rule, level, message, span}`（格式族 + 语法族并列）；
    - `judge_engine`：`"rules+spacy"`（nlp 可用且语法族至少跑过一个检测器）/ `"rules_only"`（否则）。

    **降级运行时 `converged` 的语义边界**（评审 RED#2 的诚实性，勿删）：`judge_engine == "rules_only"`
    时语法族**根本未检查**，此时「零违规 ⇒ 收敛」只代表**格式族**无阻塞性违规，**不等于**语法正确；
    任何人（判据表/发行说明/宣传文案）MUST NOT 把该次 `converged` 当作「全引擎零违规」的证据
    （运行期 fail-open，声明 / 门禁层 fail-closed）。
    """
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    words = [w for w in re.findall(r"[a-zA-ZäöüÄÖÜß]+", text)]
    word_count = len(words)

    suggestions = []

    # 1. Word count rule
    if word_count < 20:
        suggestions.append(
            {
                "rule": "a1_word_count",
                "level": "warning",
                "message": f"字数偏短（当前 {word_count} 词）。歌德 A1 考纲要求约 30 词（建议 25~35 词）。",
            }
        )
    elif word_count > 45:
        suggestions.append(
            {
                "rule": "a1_word_count",
                "level": "warning",
                "message": (
                    f"字数偏多（当前 {word_count} 词）。A1 简短便条尽量控制在 25~35 词，避免过度拓展产生额外语法错误。"
                ),
            }
        )

    # 2. Greeting check
    greeting_line = lines[0] if lines else ""
    norm_greeting = re.sub(r"[,.!?]", "", greeting_line).strip().lower()

    is_formal = any(norm_greeting.startswith(fg) for fg in _A1_FORMAL_GREETINGS)
    is_informal = any(norm_greeting.startswith(ig) for ig in _A1_INFORMAL_GREETINGS)
    has_valid_greeting = is_formal or is_informal

    has_greeting_comma = greeting_line.endswith(",")

    if not has_valid_greeting:
        suggestions.append(
            {
                "rule": "a1_greeting_missing",
                "level": "error",
                "message": "缺少德语书信称呼语。非正式信件建议使用 'Liebe/Lieber [名字],' 或 'Hallo [名字],'",
            }
        )
    elif not has_greeting_comma:
        suggestions.append(
            {
                "rule": "a1_greeting_comma",
                "level": "warning",
                "message": "德语称呼语末尾建议加逗号（如 'Liebe Maria,'），以便下一行正文首词小写。",
            }
        )

    # 3. First word lowercase check after comma greeting
    first_body_word_case_error = False
    if has_greeting_comma and len(lines) > 1:
        first_body_line = lines[1]
        body_words = re.findall(r"[a-zA-ZäöüÄÖÜß]+", first_body_line)
        if body_words:
            first_w = body_words[0]
            # In German, if greeting ends with comma, body starts with lowercase ('ich lade dich ein...')
            # Exempt: polite pronouns (Sie, Ihr), capitalized nouns, proper nouns (Montag, Berlin...)
            is_polite = first_w in _A1_POLITE_PRONOUNS
            vocab_info = lookup_core_vocab(first_w) or lookup_core_vocab(first_w.lower())
            is_noun = bool(vocab_info and vocab_info.get("pos") in ("NOUN", "PROPN"))
            if first_w.lower() in _A1_PROPER_NOUNS:
                is_noun = True

            if first_w[0].isupper() and not is_polite and not is_noun:
                first_body_word_case_error = True
                suggestions.append(
                    {
                        "rule": "a1_greeting_body_lowercase",
                        "level": "error",
                        "message": (
                            f"称呼语后加了逗号，正文首词 '{first_w}' 必须小写"
                            f"（应为 '{first_w[0].lower() + first_w[1:]}'）。"
                        ),
                    }
                )

    # 4. Valediction & Comma prohibition check
    valediction_found = False
    valediction_line = ""
    has_valediction_comma_error = False

    for ln in reversed(lines):
        norm_ln = re.sub(r"[,.!?]", "", ln).strip().lower()
        if any(norm_ln.startswith(v) for v in _A1_VALEDICTIONS):
            valediction_found = True
            valediction_line = ln
            if ln.endswith(","):
                has_valediction_comma_error = True
                suggestions.append(
                    {
                        "rule": "a1_valediction_comma",
                        "level": "error",
                        "message": "德语书信结语后【严禁】加逗号（如 'Viele Grüße'，后面不可加逗号，与英语不同）。",
                    }
                )
            break

    if not valediction_found:
        suggestions.append(
            {
                "rule": "a1_valediction_missing",
                "level": "warning",
                "message": "缺少德语结语（如 'Viele Grüße' 或 'Mit freundlichen Grüßen'）。",
            }
        )

    # 5. Leitpunkte keyword presence check
    leitpunkte_results = []
    if leitpunkte:
        lower_text = text.lower()
        for lp in leitpunkte:
            tokens = [t.lower() for t in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", lp)]
            matched = any(t in lower_text for t in tokens) if tokens else True
            leitpunkte_results.append({"leitpunkt": lp, "matched": matched})

    if word_count < 20:
        word_count_status = "too_short"
    elif word_count <= 40:
        word_count_status = "optimal"
    else:
        word_count_status = "too_long"

    leitpunkte_matches = sum(1 for r in leitpunkte_results if r["matched"])

    # ── 统一违规形状（Task 1 并列字段，只增不改）：格式族 + 语法族 ─────────────
    # 既有 `suggestions` 逐字不动；这里只把它与语法族的 span 一并搬进统一的
    # {rule, level, message, span} 形状，供 `collect_violations` 与端点层同口径消费。
    violations: List[Dict[str, Any]] = [
        {"rule": s["rule"], "level": s["level"], "message": s["message"], "span": None} for s in suggestions
    ]
    judge_engine = "rules_only"
    if nlp is not None and text and text.strip():
        # 沿用 `analyze_essay_text(text, nlp)` 的「显式传 nlp」惯例：不在模块内自读全局 nlp。
        doc = nlp(text)
        for sent in doc.sents:
            toks = list(sent)
            if not toks:
                continue
            base = toks[0].idx
            spans = (
                detect_determiner_noun_agreement(toks, base)
                + detect_preposition_case(toks, base)
                + detect_subject_verb_agreement(toks, base)
                + detect_verb_case_government(toks, base)
                + detect_verb_second_position(toks, base)
            )
            # 语法族至少跑过一个检测器（哪怕零违规）⇒ 引擎标记为 rules+spacy。
            judge_engine = "rules+spacy"
            for sp in spans:
                violations.append(
                    {
                        "rule": str(sp.get("error_type", "")),
                        "level": "error" if sp.get("severity") == "error" else "warning",
                        "message": str(sp.get("explanation_zh", "")),
                        "span": (int(sp["start"]), int(sp["end"])) if ("start" in sp and "end" in sp) else None,
                    }
                )

    return {
        "word_count": word_count,
        "word_count_status": word_count_status,
        "greeting": {
            "valid": has_valid_greeting,
            "type": "formal" if is_formal else ("informal" if is_informal else "unknown"),
            "has_comma": has_greeting_comma,
        },
        "has_lowercase_start_error": first_body_word_case_error,
        "valediction": {"valid": valediction_found, "text": valediction_line},
        "has_valediction_comma_error": has_valediction_comma_error,
        "leitpunkte_matches": leitpunkte_matches,
        "leitpunkte_results": leitpunkte_results,
        "suggestions": suggestions,
        "violations": violations,
        "judge_engine": judge_engine,
    }
