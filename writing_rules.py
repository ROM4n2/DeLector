# -*- coding: utf-8 -*-
"""德语写作本地规则引擎：冠词/格位一致 + 介词支配格。

只报高置信错误（宁可漏报不可误报）。nlp=None 时优雅返回零错误 + CEFR。
spaCy 模型由调用方注入（server 传 Android 安全加载的 nlp；测试直传 spacy.load）。
"""
import re
from typing import Any, Dict, List, Optional, Tuple
from core_dict import lookup_core_vocab

# 双格介词整组跳过（静动态依语境决定，纯规则极易误报）
_TWO_WAY_PREPS = {
    "in", "an", "auf", "über", "unter", "vor", "hinter", "neben", "zwischen"
}

# 位置动词 + 双向介词时，习语搭配（如 stehen auf Akk=喜欢）易误伤真实位置 Dat/Akk
_LOC_VERBS_TWOWAY_COLLISION = {
    "stehen", "liegen", "sitzen", "hängen", "stellen", "legen", "setzen", "stecken", "bleiben"
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

# ── decline_determiner 查表（函数随句调用，常量一次性构造，避免每句重建 dict）──
_DEF_BY_GENDER = {
    "Masc": {"Nom": "der", "Akk": "den", "Dat": "dem", "Gen": "des"},
    "Fem":  {"Nom": "die", "Akk": "die", "Dat": "der", "Gen": "der"},
    "Neut": {"Nom": "das", "Akk": "das", "Dat": "dem", "Gen": "des"},
}
_INDEF_BY_GENDER = {
    "Masc": {"Nom": "ein", "Akk": "einen", "Dat": "einem", "Gen": "eines"},
    "Fem":  {"Nom": "eine", "Akk": "eine", "Dat": "einer", "Gen": "einer"},
    "Neut": {"Nom": "ein", "Akk": "ein", "Dat": "einem", "Gen": "eines"},
}
_OWNER_STEMS = {
    "kein": "kein", "mein": "mein", "dein": "dein",
    "sein": "sein", "ihr": "ihr", "unser": "unser", "euer": "euer", "eur": "euer"
}
_PLUR_ENDING_BY_CASE = {"Nom": "e", "Akk": "e", "Dat": "en", "Gen": "er"}
_SING_ENDING_BY_GENDER_CASE = {
    "Masc": {"Nom": "", "Akk": "en", "Dat": "em", "Gen": "es"},
    "Fem":  {"Nom": "e", "Akk": "e", "Dat": "er", "Gen": "er"},
    "Neut": {"Nom": "", "Akk": "", "Dat": "em", "Gen": "es"},
}

# ── A1 日期归一（表单判题）与书信词表（email 判题）—— 每判一次都重建的常量 ──
_A1_MONTH_MAP = {
    "01": ["januar", "jan"], "02": ["februar", "feb"], "03": ["märz", "maerz", "mar"],
    "04": ["april", "apr"], "05": ["mai"], "06": ["juni", "jun"],
    "07": ["juli", "jul"], "08": ["august", "aug"], "09": ["september", "sep"],
    "10": ["oktober", "okt"], "11": ["november", "nov"], "12": ["dezember", "dez"]
}
_A1_DATE_PAT = re.compile(r'^(\d{1,2})\s*[\.]?\s*([a-zA-Zäöüß0-9]+)')
_A1_FORMAL_GREETINGS = ["sehr geehrte damen und herren", "sehr geehrte frau", "sehr geehrter herr"]
_A1_INFORMAL_GREETINGS = ["liebe", "lieber", "hallo", "guten tag", "hi"]
_A1_VALEDICTIONS = [
    "viele grüße", "herzliche grüße", "liebe grüße", "beste grüße", "schöne grüße",
    "mit freundlichen grüßen", "mit besten grüßen", "bis bald", "auf wiedersehen",
    "alles gute", "alles liebe", "herzlichen dank", "dein", "deine", "tschüss"
]
_A1_POLITE_PRONOUNS = {"Sie", "Ihr", "Ihre", "Ihren", "Ihrem", "Ihrer"}
_A1_PROPER_NOUNS = {
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
    "berlin", "münchen", "hamburg", "köln", "frankfurt", "deutschland", "österreich", "schweiz",
    "januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"
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
    # 位置动词 + 双向介词时，习语搭配易误伤真实位置 → 优先按双向处理（只给 warning，不报 error）
    if verb_head and verb_head.lemma_ in _LOC_VERBS_TWOWAY_COLLISION and prep in _TWO_WAY_PREPS:
        return "Dat/Akk", "twoway"

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
            spans.append({
                "severity": "error",
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
        if obj is None and prep == "entlang":
            if verb_head and verb_head.pos_ in ("VERB", "AUX"):
                obj = next((c for c in verb_head.children if c.pos_ == "NOUN" and c.i < tok.i), None)
            if obj is None:
                for prev in reversed(tokens[:tok.i]):
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
                "severity": "error",
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


def _collect_prep_warnings(tokens: List[Any], base: int) -> List[Dict[str, Any]]:
    """收集双格介词提醒（warning 级：方向不确定，Dat/Akk 皆可）。"""
    warnings = []
    for tok in tokens:
        if tok.pos_ != "ADP":
            continue
        expected, source = _prep_expected_case(tok)
        if source == "twoway":
            start, end = _tok_off(tok, base)
            warnings.append({
                "severity": "warning",
                "error_type": "twoway",
                "label": f"注意：{tok.text} [Dat/Akk]",
                "explanation_zh": f"「{tok.text}」是静动态双格介词：这里 Dat/Akk 皆可，请根据动作方向判断（静态用三格 Dativ，动态用四格 Akkusativ）。",
                "start": start,
                "end": end,
            })
    return warnings


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
    warning_count = 0

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
            warnings = _collect_prep_warnings(toks, base)
            sentences.append({
                "text": sent.text,
                "spans": spans,
                "hints": hints,
                "warnings": warnings,
            })
            error_count += len(spans)
            warning_count += len(warnings)

    cefr = _cefr_basic(text)
    return {
        "version": "4.3.0",
        "cefr": cefr,
        "error_count": error_count,
        "warning_count": warning_count,
        "problem_count": error_count + warning_count,
        "sentences": sentences
    }


# ── Goethe-Zertifikat A1: Schreiben Evaluator & Diagnostician ───────────────

def check_a1_formular_answer(user_val: str, expected_val: str, aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Evaluates a user answer in Goethe A1 Teil 1 (Formular ausfuellen).
    Case-insensitive, normalizes punctuation, whitespace, and German date formats (e.g. 15.08 vs 15. August).
    """
    def _normalize(s: str) -> str:
        s = s.strip().lower()
        s = re.sub(r'[,;.!?/\\-]+', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
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


def analyze_a1_email(text: str, leitpunkte: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Automated evaluation and diagnostics for Goethe A1 Teil 2 (ca. 30 Woerter E-Mail/Brief).
    Checks:
    1. Anrede (Greeting) - presence, capitalization, comma rule.
    2. Lowercase start of main text after comma greeting.
    3. Grussformel (Valediction) - presence, comma prohibition (NO comma after Viele Gruesse!).
    4. Word count recommendation (25-35 words).
    5. Leitpunkte coverage hints.
    """
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    words = [w for w in re.findall(r'[a-zA-ZäöüÄÖÜß]+', text)]
    word_count = len(words)

    suggestions = []

    # 1. Word count rule
    if word_count < 20:
        suggestions.append({
            "rule": "a1_word_count",
            "level": "warning",
            "message": f"字数偏短（当前 {word_count} 词）。歌德 A1 考纲要求约 30 词（建议 25~35 词）。"
        })
    elif word_count > 45:
        suggestions.append({
            "rule": "a1_word_count",
            "level": "warning",
            "message": f"字数偏多（当前 {word_count} 词）。A1 简短便条尽量控制在 25~35 词，避免过度拓展产生额外语法错误。"
        })

    # 2. Greeting check
    greeting_line = lines[0] if lines else ""
    norm_greeting = re.sub(r'[,.!?]', '', greeting_line).strip().lower()

    is_formal = any(norm_greeting.startswith(fg) for fg in _A1_FORMAL_GREETINGS)
    is_informal = any(norm_greeting.startswith(ig) for ig in _A1_INFORMAL_GREETINGS)
    has_valid_greeting = is_formal or is_informal

    has_greeting_comma = greeting_line.endswith(",")

    if not has_valid_greeting:
        suggestions.append({
            "rule": "a1_greeting_missing",
            "level": "error",
            "message": "缺少德语书信称呼语。非正式信件建议使用 'Liebe/Lieber [名字],' 或 'Hallo [名字],'"
        })
    elif not has_greeting_comma:
        suggestions.append({
            "rule": "a1_greeting_comma",
            "level": "warning",
            "message": "德语称呼语末尾建议加逗号（如 'Liebe Maria,'），以便下一行正文首词小写。"
        })

    # 3. First word lowercase check after comma greeting
    first_body_word_case_error = False
    if has_greeting_comma and len(lines) > 1:
        first_body_line = lines[1]
        body_words = re.findall(r'[a-zA-ZäöüÄÖÜß]+', first_body_line)
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
                suggestions.append({
                    "rule": "a1_greeting_body_lowercase",
                    "level": "error",
                    "message": f"称呼语后加了逗号，正文首词 '{first_w}' 必须小写（应为 '{first_w[0].lower() + first_w[1:]}'）。"
                })

    # 4. Valediction & Comma prohibition check
    valediction_found = False
    valediction_line = ""
    has_valediction_comma_error = False

    for l in reversed(lines):
        norm_l = re.sub(r'[,.!?]', '', l).strip().lower()
        if any(norm_l.startswith(v) for v in _A1_VALEDICTIONS):
            valediction_found = True
            valediction_line = l
            if l.endswith(","):
                has_valediction_comma_error = True
                suggestions.append({
                    "rule": "a1_valediction_comma",
                    "level": "error",
                    "message": "德语书信结语后【严禁】加逗号（如 'Viele Grüße'，后面不可加逗号，与英语不同）。"
                })
            break

    if not valediction_found:
        suggestions.append({
            "rule": "a1_valediction_missing",
            "level": "warning",
            "message": "缺少德语结语（如 'Viele Grüße' 或 'Mit freundlichen Grüßen'）。"
        })

    # 5. Leitpunkte keyword presence check
    leitpunkte_results = []
    if leitpunkte:
        lower_text = text.lower()
        for lp in leitpunkte:
            tokens = [t.lower() for t in re.findall(r'[a-zA-ZäöüÄÖÜß]{3,}', lp)]
            matched = any(t in lower_text for t in tokens) if tokens else True
            leitpunkte_results.append({
                "leitpunkt": lp,
                "matched": matched
            })

    if word_count < 20:
        word_count_status = "too_short"
    elif word_count <= 40:
        word_count_status = "optimal"
    else:
        word_count_status = "too_long"

    leitpunkte_matches = sum(1 for r in leitpunkte_results if r["matched"])

    return {
        "word_count": word_count,
        "word_count_status": word_count_status,
        "greeting": {
            "valid": has_valid_greeting,
            "type": "formal" if is_formal else ("informal" if is_informal else "unknown"),
            "has_comma": has_greeting_comma
        },
        "has_lowercase_start_error": first_body_word_case_error,
        "valediction": {
            "valid": valediction_found,
            "text": valediction_line
        },
        "has_valediction_comma_error": has_valediction_comma_error,
        "leitpunkte_matches": leitpunkte_matches,
        "leitpunkte_results": leitpunkte_results,
        "suggestions": suggestions
    }
