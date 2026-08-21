# -*- coding: utf-8 -*-
"""德语写作本地规则引擎：冠词/格位一致 + 介词支配格。

只报高置信错误（宁可漏报不可误报）。nlp=None 时优雅返回零错误 + CEFR。
spaCy 模型由调用方注入（server 传 Android 安全加载的 nlp；测试直传 spacy.load）。
"""
from typing import Any, Dict, List, Optional, Tuple
from core_dict import lookup_core_vocab

# 双格介词整组跳过（静动态依语境决定，纯规则极易误报）
_TWO_WAY_PREPS = {
    "in", "an", "auf", "über", "unter", "vor", "hinter", "neben", "zwischen"
}

# 固定单格介词 → 支配格（事实数据，参考 LanguageTool PrepositionToCases）
_PREP_CASE = {
    "mit": "Dat", "bei": "Dat", "nach": "Dat", "seit": "Dat",
    "aus": "Dat", "von": "Dat", "zu": "Dat", "gegenüber": "Dat", "entlang": "Akk",
    "ohne": "Akk", "für": "Akk", "gegen": "Akk", "durch": "Akk", "um": "Akk",
    "wegen": "Gen", "trotz": "Gen", "während": "Gen",
}

_CASE_NORM = {
    "nom": "Nom", "akk": "Akk", "acc": "Akk", "dat": "Dat", "gen": "Gen"
}

_GENDER_NORM = {
    "masc": "Masc", "fem": "Fem", "neut": "Neut"
}


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
        table = {
            "Masc": {"Nom": "der", "Akk": "den", "Dat": "dem", "Gen": "des"},
            "Fem":  {"Nom": "die", "Akk": "die", "Dat": "der", "Gen": "der"},
            "Neut": {"Nom": "das", "Akk": "das", "Dat": "dem", "Gen": "des"},
        }
        return table[g][c]

    # 不定冠词（无复数）
    if lem in ("ein", "eine", "einen", "einem", "einer", "eines"):
        if num == "Plur" or not g:
            return None
        table = {
            "Masc": {"Nom": "ein", "Akk": "einen", "Dat": "einem", "Gen": "eines"},
            "Fem":  {"Nom": "eine", "Akk": "eine", "Dat": "einer", "Gen": "einer"},
            "Neut": {"Nom": "ein", "Akk": "ein", "Dat": "einem", "Gen": "eines"},
        }
        return table[g][c]

    # kein 与物主代词
    stems = {
        "kein": "kein", "mein": "mein", "dein": "dein",
        "sein": "sein", "ihr": "ihr", "unser": "unser", "euer": "euer"
    }
    base_stem = None
    for k, v in stems.items():
        if lem == k or lem.startswith(k):
            base_stem = v
            break
    if base_stem:
        if num == "Plur":
            endings = {"Nom": "e", "Akk": "e", "Dat": "en", "Gen": "er"}
            return base_stem + endings[c]
        if not g:
            return None
        endings = {
            "Masc": {"Nom": "", "Akk": "en", "Dat": "em", "Gen": "es"},
            "Fem":  {"Nom": "e", "Akk": "e", "Dat": "er", "Gen": "er"},
            "Neut": {"Nom": "", "Akk": "", "Dat": "em", "Gen": "es"},
        }
        return base_stem + endings[g][c]

    return None


def _tok_off(tok: Any, base: int) -> Tuple[int, int]:
    """句内相对字符 offset。tok.idx 是文档级，需减去句首偏移。"""
    return tok.idx - base, tok.idx + len(tok.text) - base


def _np_det(noun_tok: Any) -> Optional[Any]:
    """返回名词的限定词子节点（dep 为 det/nk/pnc），没有返回 None。"""
    known_det_lemmas = {"der", "die", "das", "ein", "kein", "mein", "dein", "sein", "ihr", "unser", "euer"}
    known_det_texts = {
        "der", "die", "das", "den", "dem", "des",
        "ein", "eine", "einen", "einem", "einer", "eines",
        "kein", "keine", "keinen", "keinem", "keiner", "keines"
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
    # 1. 动词/形容词固定搭配优先
    if verb_head and verb_head.pos_ in ("VERB", "AUX", "ADJ"):
        from linguistics import lookup_prep_collocations
        rows = lookup_prep_collocations(verb_head.lemma_) or lookup_prep_collocations(verb_head.text.lower())
        match = next((r for r in rows if r.get("praeposition", "").lower() == prep), None)
        if match:
            c = _CASE_NORM.get(match.get("kasus", "").lower())
            if c:
                return c, "collocation"

    # 2. 双格介词判定
    if prep in _TWO_WAY_PREPS:
        return "Dat/Akk", "twoway"

    # 3. 固定单格介词判定
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
            spans.append({
                "error_type": "artikel",
                "corrected_form": f"{correct_det} {head.text}",
                "explanation_zh": f"「{head.text}」是{real_gender}性{expected_case}格，冠词应为「{correct_det}」而非「{tok.text}」。",
                "start": start,
                "end": end,
            })
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
        if obj is None:
            continue
        det = _np_det(obj)
        if det is None:
            # FP 守卫：无冠词的名词跳过（零冠词常见且通常正确）
            continue

        dict_info = lookup_core_vocab(obj.lemma_) or lookup_core_vocab(obj.text)
        real_gender = (dict_info.get("gender") if dict_info else None) or _first_morph(obj.morph.get("Gender")) or _first_morph(det.morph.get("Gender"))
        if not real_gender:
            continue

        form = decline_determiner(
            det.lemma_, real_gender, _first_morph(obj.morph.get("Number"), "Sing"), expected
        )
        if form is None:
            continue

        if det.text.lower() != form.lower():
            start = min(det.idx, obj.idx) - base
            end = max(det.idx + len(det.text), obj.idx + len(obj.text)) - base
            if error_type == "praeposition" and verb_head:
                expl = f"固定搭配「{verb_head.lemma_} {prep}」要求{expected}格，名词「{obj.text}」前应为「{form}」而非「{det.text}」。"
            else:
                expl = f"介宾「{prep}」要求{expected}格，名词「{obj.text}」前应为「{form}」而非「{det.text}」。"
            spans.append({
                "error_type": error_type,
                "corrected_form": f"{form} {obj.text}",
                "explanation_zh": expl,
                "start": start,
                "end": end,
            })
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
        hints.append({
            "type": "prep_case",
            "label": label,
            "start": start,
            "end": end
        })
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
        g_raw = (dict_info.get("gender") if dict_info else None) or _first_morph(tok.morph.get("Gender")) or (det and _first_morph(det.morph.get("Gender")))
        g = _GENDER_NORM.get(g_raw.lower()) if g_raw else None

        if g:
            label = f"[{g}·{c}]"
        else:
            label = f"[{c}]"

        start, end = _tok_off(tok, base)
        hints.append({
            "type": "np_case",
            "label": label,
            "start": start,
            "end": end
        })
    return hints


def _cefr_basic(text: str) -> Dict[str, Any]:
    """词汇频率估测（MVP 简化：词数 + 基础说明）。"""
    words = [w for w in (text or "").split() if any(ch.isalpha() for ch in w)]
    return {
        "word_count": len(words),
        "recommended_level": "A1",
        "note_zh": "词汇频率估测，非写作能力分"
    }


def analyze_essay_text(text: str, nlp: Optional[Any] = None) -> Dict[str, Any]:
    """写作润色主分析入口。nlp=None 时优雅降级为零错误 + CEFR 估测。"""
    sentences: List[Dict[str, Any]] = []
    error_count = 0

    if nlp is not None and text and text.strip():
        doc = nlp(text)
        for sent in doc.sents:
            toks = list(sent)
            if not toks:
                continue
            base = toks[0].idx
            spans = (
                detect_determiner_noun_agreement(toks, base)
                + detect_preposition_case(toks, base)
            )
            hints = (
                _collect_prep_hints(toks, base)
                + _collect_np_hints(toks, base)
            )
            sentences.append({
                "text": sent.text,
                "spans": spans,
                "hints": hints
            })
            error_count += len(spans)

    cefr = _cefr_basic(text)
    return {
        "version": "4.1.1",
        "cefr": cefr,
        "error_count": error_count,
        "sentences": sentences
    }
