"""
DeLector - German Syntax Tree & Topological Field Engine (v3.5.0)
Topologisches Feldermodell (Vorfeld, Linke Satzklammer, Mittelfeld, Rechte Satzklammer, Nachfeld)
& Goethe/TestDaF Clause Classification Abstract Syntax Tree (AST).

100% Offline, Pure Python stdlib + spaCy NLP.
Zero external API dependencies.
"""
from typing import Dict, List, Any, Optional, Union, Tuple, Set
import spacy
from spacy.tokens import Doc, Span, Token

# Global cached spaCy German model instance
_nlp_instance = None


def get_spacy_nlp():
    """Load or return cached spaCy German model with robust fallback."""
    global _nlp_instance
    if _nlp_instance is None:
        try:
            _nlp_instance = spacy.load("de_core_news_md")
        except Exception:
            try:
                _nlp_instance = spacy.load("de_core_news_sm")
            except Exception:
                from spacy.cli import download
                download("de_core_news_sm")
                _nlp_instance = spacy.load("de_core_news_sm")
    return _nlp_instance


# ==============================================================================
# 1. Linguistic Classification Tables & Dictionaries
# ==============================================================================

# Subordinating Conjunctions (Subjunktoren / KOUS & KOUI)
SUBORDINATING_CONJUNCTIONS: Dict[str, Dict[str, str]] = {
    # ── Kausal (Cause & Reason) ───────────────────────────────────────────────
    "weil": {
        "subtype": "kausal",
        "label_de": "Kausalsatz (weil)",
        "label_zh": "原因状语从句 (weil)",
        "question": "Warum? Weshalb? Aus welchem Grund?"
    },
    "da": {
        "subtype": "kausal",
        "label_de": "Kausalsatz (da)",
        "label_zh": "原因状语从句 (da - 既成事实)",
        "question": "Da / Weil?"
    },
    # ── Konzessiv (Concession) ────────────────────────────────────────────────
    "obwohl": {
        "subtype": "konzessiv",
        "label_de": "Konzessivsatz (obwohl)",
        "label_zh": "让步状语从句 (obwohl)",
        "question": "Trotz welcher Umstände?"
    },
    "obgleich": {
        "subtype": "konzessiv",
        "label_de": "Konzessivsatz (obgleich)",
        "label_zh": "让步状语从句 (obgleich)",
        "question": "Trotz welcher Umstände?"
    },
    "obschon": {
        "subtype": "konzessiv",
        "label_de": "Konzessivsatz (obschon)",
        "label_zh": "让步状语从句 (obschon)",
        "question": "Trotz welcher Umstände?"
    },
    "wenngleich": {
        "subtype": "konzessiv",
        "label_de": "Konzessivsatz (wenngleich)",
        "label_zh": "让步状语从句 (wenngleich)",
        "question": "Trotz welcher Umstände?"
    },
    "obzwar": {
        "subtype": "konzessiv",
        "label_de": "Konzessivsatz (obzwar)",
        "label_zh": "让步状语从句 (obzwar)",
        "question": "Trotz welcher Umstände?"
    },
    # ── Konditional (Condition) ───────────────────────────────────────────────
    "wenn": {
        "subtype": "konditional",
        "label_de": "Konditionalsatz (wenn)",
        "label_zh": "条件状语从句 (wenn)",
        "question": "Unter welcher Bedingung? Wann?"
    },
    "falls": {
        "subtype": "konditional",
        "label_de": "Konditionalsatz (falls)",
        "label_zh": "条件状语从句 (falls - 假定)",
        "question": "Falls / Wenn?"
    },
    "sofern": {
        "subtype": "konditional",
        "label_de": "Konditionalsatz (sofern)",
        "label_zh": "条件状语从句 (sofern - 只要/倘若)",
        "question": "Inwiefern? Unter welcher Bedingung?"
    },
    # ── Temporal (Time) ───────────────────────────────────────────────────────
    "als": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (als - Vergangenheit)",
        "label_zh": "时间状语从句 (als - 过去单次)",
        "question": "Wann? Zu welchem Zeitpunkt?"
    },
    "während": {
        "subtype": "temporal",
        "label_de": "Temporalsatz / Adversativsatz (während)",
        "label_zh": "时间/对比状语从句 (während - 当...之时/而)",
        "question": "Wann? Während welchen Zeitraums?"
    },
    "nachdem": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (nachdem - Vorzeitigkeit)",
        "label_zh": "时间状语从句 (nachdem - 先时性)",
        "question": "Nach welchem Ereignis?"
    },
    "bevor": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (bevor - Nachzeitigkeit)",
        "label_zh": "时间状语从句 (bevor - 在...之前)",
        "question": "Vor welchem Ereignis?"
    },
    "ehe": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (ehe)",
        "label_zh": "时间状语从句 (ehe - 在...之前)",
        "question": "Ehe / Bevor?"
    },
    "seit": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (seit)",
        "label_zh": "时间状语从句 (seit - 自从)",
        "question": "Seit wann?"
    },
    "seitdem": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (seitdem)",
        "label_zh": "时间状语从句 (seitdem - 自从)",
        "question": "Seit wann?"
    },
    "bis": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (bis)",
        "label_zh": "时间状语从句 (bis - 直到)",
        "question": "Bis wann?"
    },
    "sobald": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (sobald)",
        "label_zh": "时间状语从句 (sobald - 一旦/一...就)",
        "question": "Ab wann?"
    },
    "solange": {
        "subtype": "temporal",
        "label_de": "Temporalsatz (solange)",
        "label_zh": "时间状语从句 (solange - 只要...一直)",
        "question": "Wie lange?"
    },
    # ── Final (Purpose) ───────────────────────────────────────────────────────
    "damit": {
        "subtype": "final",
        "label_de": "Finalsatz (damit)",
        "label_zh": "目的状语从句 (damit - 为了)",
        "question": "Wozu? Zu welchem Zweck?"
    },
    # ── Konsekutiv (Consecutive / Result) ─────────────────────────────────────
    "sodass": {
        "subtype": "konsekutiv",
        "label_de": "Konsekutivsatz (sodass)",
        "label_zh": "结果状语从句 (sodass - 以至于)",
        "question": "Mit welcher Folge?"
    },
    # ── Modal & Instrumental ──────────────────────────────────────────────────
    "indem": {
        "subtype": "modal",
        "label_de": "Modalsatz (indem - Instrumental)",
        "label_zh": "方式/手段状语从句 (indem - 通过/借由)",
        "question": "Wie? Auf welche Weise? Wodurch?"
    },
    # ── Adversativ ────────────────────────────────────────────────────────────
    "wohingegen": {
        "subtype": "adversativ",
        "label_de": "Adversativsatz (wohingegen)",
        "label_zh": "对立/对比从句 (wohingegen - 反之)",
        "question": "Im Gegensatz wozu?"
    },
    "wogegen": {
        "subtype": "adversativ",
        "label_de": "Adversativsatz (wogegen)",
        "label_zh": "对立从句 (wogegen - 而相比之下)",
        "question": "Wogegen?"
    },
    # ── Inhaltssätze (Noun Clauses) ───────────────────────────────────────────
    "dass": {
        "subtype": "inhalt_dass",
        "label_de": "Objekt-/Subjektsatz (dass)",
        "label_zh": "dass-名词从句 (宾语/主语从句)",
        "question": "Was?"
    },
    "ob": {
        "subtype": "inhalt_ob",
        "label_de": "Indirekter Fragesatz (ob)",
        "label_zh": "ob-间接是否疑问从句",
        "question": "Ob (Ja/Nein)?"
    },
    "wie": {
        "subtype": "modal",
        "label_de": "Modalsatz / Vergleichssatz (wie)",
        "label_zh": "方式/比较从句 (wie)",
        "question": "Wie?"
    }
}

# Infinitive Connectors (KOUI)
INFINITIVE_CONNECTORS: Dict[str, Dict[str, str]] = {
    "um": {
        "subtype": "infinitiv_um_zu",
        "label_de": "Infinitivgruppe (um...zu)",
        "label_zh": "um...zu 目的不定式从属短语 (Final)",
        "formula": "[LK: um] + [MF: ...] + [RK: zu + Infinitiv]"
    },
    "ohne": {
        "subtype": "infinitiv_ohne_zu",
        "label_de": "Infinitivgruppe (ohne...zu)",
        "label_zh": "ohne...zu 否定方式不定式从属短语 (Modal)",
        "formula": "[LK: ohne] + [MF: ...] + [RK: zu + Infinitiv]"
    },
    "anstatt": {
        "subtype": "infinitiv_anstatt_zu",
        "label_de": "Infinitivgruppe (anstatt...zu)",
        "label_zh": "anstatt...zu 替代对立不定式从属短语 (Adversativ)",
        "formula": "[LK: anstatt] + [MF: ...] + [RK: zu + Infinitiv]"
    },
    "statt": {
        "subtype": "infinitiv_anstatt_zu",
        "label_de": "Infinitivgruppe (statt...zu)",
        "label_zh": "statt...zu 替代不定式从属短语 (Adversativ)",
        "formula": "[LK: statt] + [MF: ...] + [RK: zu + Infinitiv]"
    }
}

# Relative Pronouns & Relative Adverbs
RELATIVE_PRONOUNS: Set[str] = {
    "der", "die", "das", "dem", "den", "des",
    "dessen", "deren", "derer", "denen",
    "welcher", "welche", "welches", "welchem", "welchen",
    "wer", "was",
    "woran", "worauf", "wovon", "womit", "worüber", "wodurch",
    "wobei", "wozu", "wofür", "wohin", "woher", "wo"
}

# Interrogative Words (W-Fragewörter für indirekte Fragesätze)
INTERROGATIVE_WORDS: Set[str] = {
    "wer", "wen", "wem", "wessen", "was",
    "wo", "wohin", "woher", "wann", "warum",
    "weshalb", "wieso", "weswegen", "wie",
    "welcher", "welche", "welches", "welchem", "welchen"
}

# Coordinating Conjunctions (KON / Position 0)
COORDINATING_CONJUNCTIONS: Set[str] = {
    "und", "aber", "oder", "denn", "sondern", "doch", "allein"
}

# Common German Finite Modal & Auxiliary Verb Forms
FINITE_MODAL_AND_AUX_FORMS: Set[str] = {
    # Modal verbs
    "muss", "musst", "müssen", "müsst", "musste", "musstest", "mussten", "musstet",
    "kann", "kannst", "können", "könnt", "konnte", "konntest", "konnten", "konntet",
    "will", "willst", "wollen", "wollt", "wollte", "wolltest", "wollten", "wolltet",
    "soll", "sollst", "sollen", "sollt", "sollte", "solltest", "sollten", "solltet",
    "darf", "darfst", "dürfen", "dürft", "durfte", "durftest", "durften", "durftet",
    "mag", "magst", "mögen", "mögt", "mochte", "mochtest", "mochten", "mochtet",
    "möchte", "möchtest", "möchten", "möchtet",
    # Auxiliaries
    "hat", "habe", "hast", "haben", "habt", "hatte", "hattest", "hatten", "hattet",
    "ist", "bin", "bist", "sind", "seid", "war", "warst", "waren", "wart",
    "wird", "werde", "wirst", "werden", "werdet", "wurde", "wurdest", "wurden", "wurdet"
}

# Subjunctive Verb Stems & Auxiliary Forms (Konjunktiv II / I)
SUBJUNCTIVE_FORMS: Set[str] = {
    # Konjunktiv II Hilfsverben & Modalverben
    "hätte", "hättest", "hätten", "hättet",
    "wäre", "wärest", "wären", "wäret",
    "würde", "würdest", "würden", "würdet",
    "könnte", "könntest", "könnten", "könntet",
    "müsste", "müsstest", "müssten", "müsstet",
    "sollte", "solltest", "sollten", "solltet",
    "dürfte", "dürftest", "dürften", "dürftet",
    "wollte", "wolltest", "wollten", "wolltet",
    "möchte", "möchtest", "möchten", "möchtet",
    # Strong Verbs Konjunktiv II
    "käme", "kämen", "ginge", "gingen", "wüsste", "wüssten",
    "fände", "fänden", "bliebe", "blieben", "gäbe", "gäben",
    "ließe", "ließen", "schriebe", "schrieben", "nähme", "nähmen",
    "sähe", "sähen", "stände", "stünde", "ständen", "stünden",
    "täte", "täten", "brächte", "brächten", "dächte", "dächten",
    # Konjunktiv I
    "sei", "seien", "seiet", "habe", "haben", "werde", "werden",
    "könne", "können", "müsse", "müssen", "wisse", "wissen",
    "gehe", "gehen", "komme", "kommen", "bleibe", "bleiben"
}


# ==============================================================================
# 2. Token Formatting Helper
# ==============================================================================

def format_token_dict(tok: Token) -> Dict[str, Any]:
    """Convert a spaCy Token into a clean, serializable dictionary."""
    morph_dict = tok.morph.to_dict()
    return {
        "id": tok.i,
        "text": tok.text,
        "lemma": tok.lemma_,
        "pos": tok.pos_,
        "tag": tok.tag_,
        "dep": tok.dep_,
        "head_id": tok.head.i,
        "head_text": tok.head.text,
        "gender": morph_dict.get("Gender", ""),
        "case": morph_dict.get("Case", ""),
        "number": morph_dict.get("Number", ""),
        "person": morph_dict.get("Person", ""),
        "tense": morph_dict.get("Tense", ""),
        "mood": morph_dict.get("Mood", ""),
        "verb_form": morph_dict.get("VerbForm", ""),
        "is_punct": tok.is_punct,
        "is_space": tok.is_space
    }


def _empty_topology() -> Dict[str, Any]:
    return {
        "vorfeld": [],
        "linke_klammer": [],
        "mittelfeld": [],
        "rechte_klammer": [],
        "nachfeld": [],
        "field_texts": {"vorfeld": "", "linke_klammer": "", "mittelfeld": "", "rechte_klammer": "", "nachfeld": ""},
        "sentence_type": "unknown",
        "bracket_structure": "keine",
        "clause_type": "unknown"
    }


# ==============================================================================
# 3. Topological Five Fields Algorithm (Das topologische Feldermodell)
# ==============================================================================

def analyze_sentence_topology(
    doc_or_sent: Union[Doc, Span, str],
    clause_tokens: Optional[List[Token]] = None,
    clause_type: str = "auto"
) -> Dict[str, Any]:
    """
    Accurately segment a German sentence or clause into the 5 classic topological fields:
      - Vorfeld (VF / 前场): constituent before the left bracket (main clause only)
      - Linke Satzklammer (LK / 左框): finite verb (V2/V1) or subordinator (VL)
      - Mittelfeld (MF / 中场): core nominal arguments, adverbials, objects between brackets
      - Rechte Satzklammer (RK / 右框): non-finite verbs, prefixes, or clause-final verb complex
      - Nachfeld (NF / 后场): extraposed subordinate clauses, comparative phrases, supplements

    Returns:
      {
        "vorfeld": [...],
        "linke_klammer": [...],
        "mittelfeld": [...],
        "rechte_klammer": [...],
        "nachfeld": [...],
        "field_texts": {"vorfeld": "...", ...},
        "sentence_type": "V2" | "V1" | "VL" | "Infinitiv",
        "bracket_structure": str,
        "clause_type": str
      }
    """
    if isinstance(doc_or_sent, str):
        if not doc_or_sent.strip():
            return _empty_topology()
        nlp = get_spacy_nlp()
        doc = nlp(doc_or_sent)
        sents = list(doc.sents)
        tokens = list(sents[0]) if sents else list(doc)
    elif isinstance(doc_or_sent, Doc):
        sents = list(doc_or_sent.sents)
        tokens = list(sents[0]) if sents else list(doc_or_sent)
    elif isinstance(doc_or_sent, Span):
        tokens = list(doc_or_sent)
    elif isinstance(doc_or_sent, list):
        tokens = doc_or_sent
    else:
        tokens = []

    if clause_tokens is not None:
        tokens = clause_tokens

    if not tokens:
        return _empty_topology()

    non_punct_tokens = [t for t in tokens if not t.is_punct and not t.is_space]
    if not non_punct_tokens:
        non_punct_tokens = tokens

    # Check if there is a main clause finite verb (e.g. following a comma in a preposed subclause)
    has_main_finite_verb = False
    main_fin_candidate: Optional[Token] = None

    # Look for a finite verb after a comma (V2 main clause after preposed subclause)
    for idx, t in enumerate(tokens):
        if t.text == "," and idx + 1 < len(tokens):
            next_tok = tokens[idx + 1]
            if next_tok.pos_ in ("VERB", "AUX") or next_tok.tag_ in ("VVFIN", "VAFIN", "VMFIN") or next_tok.text.lower() in FINITE_MODAL_AND_AUX_FORMS:
                has_main_finite_verb = True
                main_fin_candidate = next_tok
                break

    # Determine Clause Verb Order & Type
    is_infinitiv = False
    is_subordinate = False
    connector_tokens: List[Token] = []

    # Check for infinitive with zu
    zu_tokens = [t for t in tokens if t.tag_ == "PTKZU" or t.dep_ == "pm" or t.text.lower() == "zu"]
    inf_verbs = [t for t in tokens if t.tag_ in ("VVINF", "VAINF", "VMINF") or (t.pos_ in ("VERB", "AUX") and "Inf" in t.morph.get("VerbForm", []))]
    
    if (zu_tokens and inf_verbs) or any(t.tag_ == "VVIZU" for t in tokens):
        # Only set is_infinitiv if the entire span is the infinitive clause
        if clause_type in ("infinitivgruppe", "infinitiv") or not has_main_finite_verb:
            is_infinitiv = True
            first_word = non_punct_tokens[0].text.lower() if non_punct_tokens else ""
            if first_word in INFINITIVE_CONNECTORS:
                connector_tokens = [non_punct_tokens[0]]

    # Check for subordinate conjunction / relative pronoun / question word at the beginning
    if not is_infinitiv and not has_main_finite_verb:
        for idx, t in enumerate(non_punct_tokens[:3]):
            w_lower = t.text.lower()
            if t.tag_ in ("KOUS", "KOUI") or w_lower in SUBORDINATING_CONJUNCTIONS:
                is_subordinate = True
                connector_tokens = [t]
                break
            elif t.tag_ in ("PRELS", "PRELAT") or (t.dep_ in ("rc", "re") and idx == 0):
                is_subordinate = True
                connector_tokens = [t]
                break
            elif t.pos_ == "ADP" and idx == 0 and len(non_punct_tokens) > 1:
                next_tok = non_punct_tokens[1]
                if next_tok.tag_ in ("PRELS", "PRELAT") or next_tok.text.lower() in RELATIVE_PRONOUNS:
                    is_subordinate = True
                    connector_tokens = [t, next_tok]
                    break
            elif t.tag_ in ("PWAV", "PWS") or (w_lower in INTERROGATIVE_WORDS and t.dep_ != "ROOT"):
                fin_verbs = [v for v in tokens if v.tag_ in ("VVFIN", "VAFIN", "VMFIN")]
                if fin_verbs and fin_verbs[-1].i > t.i:
                    is_subordinate = True
                    connector_tokens = [t]
                    break

    # If explicit clause_type override provided
    if clause_type in ("konjunktionalsatz", "relativsatz", "nebensatz", "subordinate"):
        is_subordinate = True
        is_infinitiv = False
    elif clause_type in ("infinitivgruppe", "infinitiv"):
        is_infinitiv = True
        is_subordinate = False
    elif clause_type in ("hauptsatz", "main"):
        is_subordinate = False
        is_infinitiv = False

    # --------------------------------------------------------------------------
    # ALLOCATE FIELDS
    # --------------------------------------------------------------------------
    vf_tokens: List[Token] = []
    lk_tokens: List[Token] = []
    mf_tokens: List[Token] = []
    rk_tokens: List[Token] = []
    nf_tokens: List[Token] = []

    sentence_type = "V2"
    bracket_desc = "Einfacher Satz"

    if is_infinitiv:
        # === 1. INFINITIVGRUPPE ===
        sentence_type = "Infinitiv"
        vf_tokens = []
        lk_tokens = connector_tokens

        rk_candidates = [
            t for t in tokens
            if t.tag_ in ("PTKZU", "VVINF", "VAINF", "VMINF", "VVIZU") or t.dep_ == "pm" or t.text.lower() == "zu"
        ]
        rk_candidates = sorted(rk_candidates, key=lambda x: x.i)
        
        if rk_candidates:
            rk_first_id = rk_candidates[0].i
            rk_last_id = rk_candidates[-1].i
            rk_tokens = [t for t in tokens if rk_first_id <= t.i <= rk_last_id and (t in rk_candidates or t.pos_ in ("VERB", "AUX", "PART"))]
        else:
            rk_tokens = []

        lk_ids = {t.i for t in lk_tokens}
        rk_ids = {t.i for t in rk_tokens}
        min_rk_id = min(rk_ids) if rk_ids else len(tokens)
        max_rk_id = max(rk_ids) if rk_ids else -1

        for t in tokens:
            if t.i in lk_ids or t.i in rk_ids:
                continue
            if t.i < min_rk_id:
                if t.i not in lk_ids:
                    mf_tokens.append(t)
            elif t.i > max_rk_id:
                nf_tokens.append(t)

        bracket_desc = "Infinitiv-Klammer (zu + Infinitiv)"

    elif is_subordinate:
        # === 2. SUBORDINATE CLAUSE (VL / Verbletzt) ===
        sentence_type = "VL"
        vf_tokens = []

        if connector_tokens:
            lk_tokens = connector_tokens
        else:
            lk_tokens = [non_punct_tokens[0]] if non_punct_tokens else []

        all_verbs_in_clause = [
            t for t in tokens
            if t.pos_ in ("VERB", "AUX") or t.tag_ in ("PTKVZ", "PTKZU") or t.dep_ in ("svp", "pm")
        ]
        if all_verbs_in_clause:
            last_verb = all_verbs_in_clause[-1]
            cluster = [last_verb]
            for v in reversed(all_verbs_in_clause[:-1]):
                if abs(v.i - cluster[-1].i) <= 2:
                    cluster.append(v)
                else:
                    break
            cluster = sorted(cluster, key=lambda x: x.i)
            rk_first_id = cluster[0].i
            rk_last_id = cluster[-1].i
            rk_tokens = [t for t in tokens if rk_first_id <= t.i <= rk_last_id]
        else:
            rk_tokens = []

        lk_ids = {t.i for t in lk_tokens}
        rk_ids = {t.i for t in rk_tokens}
        min_rk_id = min(rk_ids) if rk_ids else len(tokens)
        max_rk_id = max(rk_ids) if rk_ids else -1

        for t in tokens:
            if t.i in lk_ids or t.i in rk_ids:
                continue
            if t.i < min_rk_id:
                if t.i not in lk_ids:
                    mf_tokens.append(t)
            elif t.i > max_rk_id:
                nf_tokens.append(t)

        bracket_desc = "Nebensatz-Klammer (Subjunktor ... Verbkomplex)"

    else:
        # === 3. MAIN CLAUSE (V2 / V1) ===
        fin_verb = main_fin_candidate

        # Priority 1: Check finite modal/auxiliary verbs at pos 1-3
        if fin_verb is None:
            for t in non_punct_tokens[:4]:
                if t.text.lower() in FINITE_MODAL_AND_AUX_FORMS and t.tag_ not in ("VAINF", "VMINF", "VVINF"):
                    fin_verb = t
                    break

        # Priority 2: ROOT token if finite verb
        if fin_verb is None:
            for t in tokens:
                if t.dep_ == "ROOT" and t.tag_ in ("VVFIN", "VAFIN", "VMFIN"):
                    fin_verb = t
                    break

        # Priority 3: First finite verb not in a subordinate clause
        if fin_verb is None:
            for t in tokens:
                if t.tag_ in ("VVFIN", "VAFIN", "VMFIN") and t.dep_ not in ("rc", "re", "cp"):
                    fin_verb = t
                    break

        # Priority 4: ROOT token if pos is VERB/AUX
        if fin_verb is None:
            for t in tokens:
                if t.dep_ == "ROOT" and t.pos_ in ("VERB", "AUX"):
                    fin_verb = t
                    break

        # Priority 5: First verb or initial verb (V1)
        if fin_verb is None:
            for t in non_punct_tokens:
                if t.pos_ in ("VERB", "AUX") or t.text.lower() in FINITE_MODAL_AND_AUX_FORMS:
                    fin_verb = t
                    break

        if fin_verb is None and tokens:
            fin_verb = non_punct_tokens[0] if non_punct_tokens else tokens[0]

        # Determine if V1 or V2
        if fin_verb and non_punct_tokens and fin_verb.i == non_punct_tokens[0].i:
            sentence_type = "V1"
            vf_tokens = []
            lk_tokens = [fin_verb]
        else:
            sentence_type = "V2"
            lk_tokens = [fin_verb] if fin_verb else []
            if fin_verb:
                vf_tokens = [t for t in tokens if t.i < fin_verb.i]
            else:
                vf_tokens = []

        # Identify boundary of any following extraposed subordinate clause
        extraposed_start_id = len(tokens)
        for idx, t in enumerate(tokens):
            if fin_verb and t.i <= fin_verb.i:
                continue
            if t.text == "," and idx + 1 < len(tokens):
                next_tok = tokens[idx + 1]
                if next_tok.tag_ in ("KOUS", "KOUI", "PRELS", "PRELAT") or next_tok.text.lower() in SUBORDINATING_CONJUNCTIONS or next_tok.text.lower() in RELATIVE_PRONOUNS or next_tok.text.lower() == "um":
                    extraposed_start_id = t.i
                    break

        # Identify Rechte Satzklammer (RK):
        # Non-finite verbs, separable prefixes (PTKVZ) belonging to main clause predicate
        # (Strictly BEFORE any following extraposed subordinate clause)
        rk_elements: List[Token] = []
        if fin_verb:
            for t in tokens:
                if t.i <= fin_verb.i or t.i >= extraposed_start_id:
                    continue
                if t.tag_ == "PTKVZ" or t.dep_ in ("svp", "compound:prt"):
                    rk_elements.append(t)
                elif t.tag_ in ("VVPP", "VAPP", "VVINF", "VAINF", "VMINF") or (t.pos_ in ("VERB", "AUX") and t.i > fin_verb.i):
                    if t.dep_ in ("oc", "ROOT", "mo") or t.head == fin_verb or t.head.head == fin_verb or t == fin_verb.head:
                        rk_elements.append(t)

        rk_tokens = sorted(rk_elements, key=lambda x: x.i)

        lk_ids = {t.i for t in lk_tokens}
        rk_ids = {t.i for t in rk_tokens}

        if rk_tokens:
            min_rk_id = min(rk_ids)
            max_rk_id = max(rk_ids)
            for t in tokens:
                if t.i in lk_ids or t.i in rk_ids or t.i < (fin_verb.i if fin_verb else 0):
                    continue
                if t.i < min_rk_id:
                    mf_tokens.append(t)
                elif t.i > max_rk_id:
                    nf_tokens.append(t)
        else:
            for t in tokens:
                if t.i in lk_ids or t.i < (fin_verb.i if fin_verb else 0):
                    continue
                if t.i < extraposed_start_id:
                    mf_tokens.append(t)
                else:
                    nf_tokens.append(t)

    # --------------------------------------------------------------------------
    # Format Text Strings & Bracket Detection
    # --------------------------------------------------------------------------
    def to_text(toks: List[Token]) -> str:
        if not toks:
            return ""
        res = []
        for t in toks:
            if t.is_punct and t.text in (",", ".", "!", "?", ";", ":") and res:
                res[-1] = res[-1] + t.text
            else:
                res.append(t.text)
        return " ".join(res).strip()

    field_texts = {
        "vorfeld": to_text(vf_tokens),
        "linke_klammer": to_text(lk_tokens),
        "mittelfeld": to_text(mf_tokens),
        "rechte_klammer": to_text(rk_tokens),
        "nachfeld": to_text(nf_tokens)
    }

    has_participle = any(t.tag_ in ("VVPP", "VAPP") for t in (lk_tokens + rk_tokens + mf_tokens))
    has_werden = any(t.lemma_.lower() in ("werden", "wurde") or t.text.lower() in ("wurde", "wurden", "wird", "werden") for t in (lk_tokens + rk_tokens))
    has_sein = any(t.lemma_.lower() in ("sein", "war") or t.text.lower() in ("ist", "sind", "war", "waren") for t in (lk_tokens + rk_tokens))
    has_modal = any(t.tag_ in ("VMFIN", "VMINF") or t.text.lower() in FINITE_MODAL_AND_AUX_FORMS for t in (lk_tokens + rk_tokens))
    has_sep_pfx = any(t.tag_ == "PTKVZ" for t in rk_tokens)
    has_subjunctive = any(t.text.lower() in SUBJUNCTIVE_FORMS or "Sub" in t.morph.get("Mood", []) for t in (lk_tokens + rk_tokens))

    if has_werden and has_participle:
        bracket_desc = "Passiv-Klammer (Vorgangspassiv)"
    elif has_modal and has_participle and has_werden:
        bracket_desc = "Passiv-Klammer mit Modalverb"
    elif has_sein and has_participle:
        bracket_desc = "Passiv-Klammer (Zustandspassiv / Perfekt)"
    elif has_subjunctive:
        bracket_desc = "Konjunktiv-Klammer (Irrealis / Höflichkeit)"
    elif has_modal and (has_participle or any(t.tag_ in ("VVINF", "VAINF") or t.text.lower() in ("werden", "sein", "haben") for t in rk_tokens)):
        bracket_desc = "Modalverb-Klammer"
    elif has_sep_pfx:
        bracket_desc = "Trennbare-Verb-Klammer (Präfix im RK)"
    elif has_participle:
        bracket_desc = "Perfekt/Plusquamperfekt-Klammer"
    elif is_infinitiv:
        bracket_desc = "Infinitiv-Klammer (zu + Inf.)"
    elif is_subordinate:
        bracket_desc = "Nebensatz-Klammer (Verbletzt)"
    elif rk_tokens:
        bracket_desc = "Zweiteilige Verbklammer"
    else:
        bracket_desc = "Einfache Verbklammer"

    return {
        "vorfeld": [format_token_dict(t) for t in vf_tokens],
        "linke_klammer": [format_token_dict(t) for t in lk_tokens],
        "mittelfeld": [format_token_dict(t) for t in mf_tokens],
        "rechte_klammer": [format_token_dict(t) for t in rk_tokens],
        "nachfeld": [format_token_dict(t) for t in nf_tokens],
        "field_texts": field_texts,
        "sentence_type": sentence_type,
        "bracket_structure": bracket_desc,
        "clause_type": clause_type
    }


# ==============================================================================
# 4. Clause Classifier & Abstract Syntax Tree (AST) Engine
# ==============================================================================

class ClauseNode:
    """Represents a single clause node in the syntactic AST."""
    def __init__(
        self,
        node_id: str,
        clause_type: str,
        label: str,
        subtype: str,
        connector: str,
        finite_verb: str,
        formula: str,
        bracket_structure: str,
        features: Dict[str, Any],
        token_ids: List[int],
        tokens: List[Token],
        head_token: Optional[Token] = None
    ):
        self.id = node_id
        self.type = clause_type
        self.label = label
        self.subtype = subtype
        self.connector = connector
        self.finite_verb = finite_verb
        self.formula = formula
        self.bracket_structure = bracket_structure
        self.features = features
        self.token_ids = token_ids
        self.tokens = tokens
        self.head_token = head_token
        self.children: List[ClauseNode] = []
        self.topology: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert AST node to a clean JSON-serializable structure."""
        tok_texts = [t.text for t in self.tokens]
        clause_text = " ".join(tok_texts).replace(" ,", ",").replace(" .", ".").replace(" !", "!").replace(" ?", "?")
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "subtype": self.subtype,
            "connector": self.connector,
            "finite_verb": self.finite_verb,
            "formula": self.formula,
            "bracket_structure": self.bracket_structure,
            "features": self.features,
            "token_ids": self.token_ids,
            "text": clause_text,
            "topology": self.topology,
            "children": [child.to_dict() for child in self.children]
        }


def _classify_single_clause(
    tokens: List[Token],
    head: Token,
    node_id: str,
    is_root: bool = False
) -> ClauseNode:
    """Classify a set of tokens and its verbal head into one of the 5 Goethe/TestDaF clause types."""
    non_punct = [t for t in tokens if not t.is_punct and not t.is_space]
    first_tok = non_punct[0] if non_punct else (tokens[0] if tokens else None)
    first_word_lower = first_tok.text.lower() if first_tok else ""

    # Check for infinitive particles and verbs
    has_zu = any(t.tag_ == "PTKZU" or t.dep_ == "pm" or t.text.lower() == "zu" for t in tokens)
    is_inf_verb = head.tag_ in ("VVINF", "VAINF", "VMINF") or "Inf" in head.morph.get("VerbForm", [])

    # Check passive / subjunctive / tense / mood
    has_participle = any(t.tag_ in ("VVPP", "VAPP") for t in tokens)
    has_werden = any(t.lemma_.lower() in ("werden", "wurde") or t.text.lower() in ("wurde", "wurden", "wird", "werden") for t in tokens)
    has_sein = any(t.lemma_.lower() in ("sein", "war") or t.text.lower() in ("ist", "sind", "war", "waren") for t in tokens)
    has_modal = any(t.tag_ in ("VMFIN", "VMINF") or t.text.lower() in FINITE_MODAL_AND_AUX_FORMS for t in tokens)
    
    subj_tokens = [t for t in tokens if t.text.lower() in SUBJUNCTIVE_FORMS or "Sub" in t.morph.get("Mood", [])]
    is_subjunctive = len(subj_tokens) > 0
    
    is_passive = (has_werden and has_participle) or (has_modal and has_participle and has_werden)
    is_zustandspassiv = has_sein and has_participle and not is_passive

    voice = "Aktiv"
    if is_passive:
        voice = "Vorgangspassiv"
    elif is_zustandspassiv:
        voice = "Zustandspassiv"

    mood = "Indikativ"
    if is_subjunctive:
        if any(t.text.lower() in ("sei", "seien", "habe", "könne", "müsse", "werde") for t in subj_tokens):
            mood = "Konjunktiv I"
        else:
            mood = "Konjunktiv II"

    tense = head.morph.get("Tense", ["Präsens"])[0] if head.morph.get("Tense") else "Präsens"
    if tense == "Pres":
        tense = "Präsens"
    elif tense == "Past":
        tense = "Präteritum"

    features = {
        "is_passive": is_passive or is_zustandspassiv,
        "is_subjunctive": is_subjunctive,
        "voice": voice,
        "mood": mood,
        "tense": tense,
        "has_modal": has_modal
    }

    # --------------------------------------------------------------------------
    # 1. INFINITIVGRUPPE
    # --------------------------------------------------------------------------
    if not is_root and ((has_zu and is_inf_verb) or first_word_lower in INFINITIVE_CONNECTORS):
        connector_str = first_word_lower if first_word_lower in INFINITIVE_CONNECTORS else ""
        meta = INFINITIVE_CONNECTORS.get(connector_str, {
            "subtype": "infinitiv_zu",
            "label_de": "Infinitivgruppe (zu + Inf.)",
            "label_zh": "zu-不定式从属短语",
            "formula": "[MF] + [RK: zu + Infinitiv]"
        })
        bracket_str = f"Infinitiv-Klammer ({connector_str + '...zu' if connector_str else 'zu + Inf.'})"
        return ClauseNode(
            node_id=node_id,
            clause_type="infinitivgruppe",
            label=meta["label_de"],
            subtype=meta["subtype"],
            connector=connector_str,
            finite_verb=head.text,
            formula=meta["formula"],
            bracket_structure=bracket_str,
            features=features,
            token_ids=[t.i for t in tokens],
            tokens=tokens,
            head_token=head
        )

    # --------------------------------------------------------------------------
    # 2. RELATIVSATZ
    # --------------------------------------------------------------------------
    # Note: Check if connector is an indirect question word first
    is_question_word = first_word_lower in INTERROGATIVE_WORDS and first_word_lower not in ("der", "die", "das", "welcher", "welche", "welches")
    rel_pron_toks = [t for t in tokens if t.tag_ in ("PRELS", "PRELAT") or (t.text.lower() in RELATIVE_PRONOUNS and t.dep_ in ("sb", "oa", "da", "og", "nk", "rc", "ag"))]
    is_relativsatz = not is_root and not is_question_word and (head.dep_ in ("rc", "re") or len(rel_pron_toks) > 0)

    if is_relativsatz and not (first_word_lower in SUBORDINATING_CONJUNCTIONS and first_word_lower not in ("das", "die", "der")):
        connector_str = ""
        if rel_pron_toks:
            rel_t = rel_pron_toks[0]
            if rel_t.head and rel_t.head.pos_ == "ADP" and rel_t.head.i < rel_t.i:
                connector_str = f"{rel_t.head.text} {rel_t.text}"
            else:
                connector_str = rel_t.text
        else:
            connector_str = first_tok.text if first_tok else ""

        formula = f"[LK: {connector_str or 'Relativpronomen'}] + [MF] + [RK: Verb_fin]"
        bracket_str = "Relativsatz-Klammer (Relativpronomen ... Verbletzt)"
        if is_passive:
            bracket_str = "Relativsatz + Passiv-Klammer"
        elif is_subjunctive:
            bracket_str = "Relativsatz + Konjunktiv-Klammer"

        return ClauseNode(
            node_id=node_id,
            clause_type="relativsatz",
            label="Relativsatz",
            subtype="relativ",
            connector=connector_str,
            finite_verb=head.text,
            formula=formula,
            bracket_structure=bracket_str,
            features=features,
            token_ids=[t.i for t in tokens],
            tokens=tokens,
            head_token=head
        )

    # --------------------------------------------------------------------------
    # 3. KONJUNKTIONALSATZ / ADVERBIALSATZ / DASS-OB SATZ / INDIREKTER FRAGESATZ
    # --------------------------------------------------------------------------
    conj_toks = [t for t in non_punct[:3] if t.text.lower() in SUBORDINATING_CONJUNCTIONS or t.tag_ in ("KOUS", "KOUI")]
    is_interrogative_sub = (first_word_lower in INTERROGATIVE_WORDS and not is_root)

    if not is_root and (conj_toks or is_interrogative_sub or (head.dep_ in ("mo", "oc", "cp", "rc") and first_word_lower in SUBORDINATING_CONJUNCTIONS)):
        if conj_toks:
            conj_word = conj_toks[0].text.lower()
            meta = SUBORDINATING_CONJUNCTIONS.get(conj_word, {
                "subtype": "konjunktional",
                "label_de": f"Konjunktionalsatz ({conj_word})",
                "label_zh": "从属连词从句",
                "question": ""
            })
            connector_str = conj_toks[0].text
        else:
            conj_word = first_word_lower
            meta = {
                "subtype": "indirekter_fragesatz",
                "label_de": f"Indirekter Fragesatz ({conj_word})",
                "label_zh": "间接疑问从句",
                "question": "W-Frage"
            }
            connector_str = first_tok.text if first_tok else ""

        formula = f"[LK: {connector_str}] + [MF] + [RK: Verb_fin]"
        bracket_str = f"Nebensatz-Klammer ({connector_str} ... {head.text})"
        if is_passive:
            bracket_str = f"Nebensatz ({connector_str}) + Passiv-Klammer"
        elif is_subjunctive:
            bracket_str = f"Nebensatz ({connector_str}) + Konjunktiv-Klammer"

        return ClauseNode(
            node_id=node_id,
            clause_type="konjunktionalsatz",
            label=meta["label_de"],
            subtype=meta["subtype"],
            connector=connector_str,
            finite_verb=head.text,
            formula=formula,
            bracket_structure=bracket_str,
            features=features,
            token_ids=[t.i for t in tokens],
            tokens=tokens,
            head_token=head
        )

    # --------------------------------------------------------------------------
    # 4. HAUPTSATZ (Main Clause)
    # --------------------------------------------------------------------------
    is_v1 = (head.i == (first_tok.i if first_tok else -1)) or (first_tok and first_tok.text.endswith("?"))
    is_coord = first_word_lower in COORDINATING_CONJUNCTIONS

    if is_v1:
        subtype = "stirnsatz_v1"
        label = "Hauptsatz (V1 - Frage/Imperativ)"
        formula = "[LK: Verb_fin] + [MF] + [RK: Verb_nonfin/Pfx] + [NF]"
    elif is_coord:
        subtype = "koordinierter_hauptsatz"
        label = f"Koordinierter Hauptsatz ({first_tok.text if first_tok else ''})"
        formula = f"[Koordinator: {first_tok.text if first_tok else ''}] + [VF] + [LK: Verb_fin] + [MF] + [RK] + [NF]"
    else:
        subtype = "kernsatz_v2"
        label = "Hauptsatz (V2)"
        formula = "[VF] + [LK: Verb_fin] + [MF] + [RK: Verb_nonfin/Pfx] + [NF]"

    bracket_str = "Hauptsatz-Klammer (V2)"
    if is_passive:
        bracket_str = "Hauptsatz + Passiv-Klammer (werden + Partizip II)"
    elif is_zustandspassiv:
        bracket_str = "Hauptsatz + Zustandspassiv (sein + Partizip II)"
    elif is_subjunctive:
        bracket_str = "Hauptsatz + Konjunktiv II Klammer"
    elif has_modal:
        bracket_str = "Hauptsatz + Modalverb-Klammer"

    return ClauseNode(
        node_id=node_id,
        clause_type="hauptsatz",
        label=label,
        subtype=subtype,
        connector=first_tok.text if is_coord else "",
        finite_verb=head.text,
        formula=formula,
        bracket_structure=bracket_str,
        features=features,
        token_ids=[t.i for t in tokens],
        tokens=tokens,
        head_token=head
    )


def build_clause_tree(doc_or_sent: Union[Doc, Span, str]) -> Dict[str, Any]:
    """
    Build a multi-level recursive Abstract Syntax Tree (AST) of German clauses:
      - Hauptsatz (Main Clause / V2 / V1 / Satzreihe)
      - Konjunktionalsatz (Adverbial / dass / ob / Kausal / Konzessiv / etc.)
      - Relativsatz (Relative clause with der/die/das/dessen/prep+rel)
      - Infinitivgruppe (um...zu, ohne...zu, anstatt...zu, zu+Infinitiv)
      - Passiv- & Konjunktiv-Klammer bracket recognition

    Each node in the tree contains:
      {
        "id": str,
        "type": "hauptsatz" | "konjunktionalsatz" | "relativsatz" | "infinitivgruppe",
        "label": str,
        "subtype": str,
        "connector": str,
        "finite_verb": str,
        "formula": str,
        "bracket_structure": str,
        "features": {...},
        "token_ids": [...],
        "text": str,
        "topology": {...},
        "children": [...]
      }
    """
    if isinstance(doc_or_sent, str):
        if not doc_or_sent.strip():
            return {}
        nlp = get_spacy_nlp()
        doc = nlp(doc_or_sent)
        sents = list(doc.sents)
        sent = sents[0] if sents else doc[:]
    elif isinstance(doc_or_sent, Doc):
        sents = list(doc_or_sent.sents)
        sent = sents[0] if sents else doc_or_sent[:]
    elif isinstance(doc_or_sent, Span):
        sent = doc_or_sent
    else:
        sent = doc_or_sent

    sent_tokens = list(sent)
    if not sent_tokens:
        return {}

    # 1. Identify all clause verbal heads
    clause_heads: List[Tuple[Token, str]] = []

    # Find root head(s)
    roots = [t for t in sent_tokens if t.dep_ == "ROOT"]
    if not roots:
        roots = [sent_tokens[0]]

    primary_root = roots[0]
    clause_heads.append((primary_root, "root"))

    # Find subordinate and infinitive clause heads
    for t in sent_tokens:
        if t == primary_root:
            continue

        # 1. Infinitivgruppe (Infinitive WITH zu / KOUI)
        has_zu_child = any(c.tag_ == "PTKZU" or c.dep_ == "pm" or c.text.lower() == "zu" for c in t.children)
        is_inf = t.tag_ in ("VVINF", "VAINF", "VMINF") or t.tag_ == "VVIZU" or "Inf" in t.morph.get("VerbForm", [])
        is_koui = any(c.tag_ == "KOUI" or c.text.lower() in INFINITIVE_CONNECTORS for c in t.children)
        if (has_zu_child or is_koui) and is_inf:
            clause_heads.append((t, "infinitiv"))
            continue

        # 2. Finite Relative Clause
        is_finite = t.tag_ in ("VVFIN", "VAFIN", "VMFIN") or "Fin" in t.morph.get("VerbForm", [])
        if t.dep_ in ("rc", "re") and (is_finite or t.pos_ in ("VERB", "AUX")):
            clause_heads.append((t, "relativ"))
            continue

        # 3. Finite Subordinate Conjunctional / Adverbial Clause
        has_conj_child = any(c.tag_ in ("KOUS", "KOUI") or c.dep_ == "cp" or c.text.lower() in SUBORDINATING_CONJUNCTIONS for c in t.children)
        if is_finite and (t.dep_ in ("mo", "oc", "oa", "sb", "cp") or has_conj_child):
            clause_heads.append((t, "subordinate"))
            continue

        # 4. Coordinated Main Clause (finite verb attached to root via cj)
        if is_finite and t.dep_ == "cj" and t.head == primary_root:
            clause_heads.append((t, "coord_root"))
            continue

    # 2. Compute token spans and subtrees for each clause head
    clause_spans: List[Tuple[Token, str, List[Token]]] = []
    
    for head, ctype in clause_heads:
        subtree_tokens = sorted(list(head.subtree), key=lambda x: x.i)
        min_i = subtree_tokens[0].i
        max_i = subtree_tokens[-1].i
        # Include preceding comma if immediately before subclause (within current sentence)
        sent_start_id = sent_tokens[0].i
        if min_i > sent_start_id and head.doc[min_i - 1].text == ",":
            if ctype != "root":
                min_i = min_i - 1

        span_tokens = [t for t in sent_tokens if min_i <= t.i <= max_i]
        clause_spans.append((head, ctype, span_tokens))

    # 3. Create ClauseNode instances
    clause_nodes: List[ClauseNode] = []
    for idx, (head, ctype, tokens) in enumerate(clause_spans):
        is_root = (ctype in ("root", "coord_root"))
        node = _classify_single_clause(tokens, head, f"clause_{idx}", is_root=is_root)
        node.topology = analyze_sentence_topology(sent, clause_tokens=tokens, clause_type=node.type)
        clause_nodes.append(node)

    # 4. Build Parent-Child Hierarchy (Nesting Tree)
    root_node = clause_nodes[0]
    child_candidates = clause_nodes[1:]

    def attach_to_tree(parent: ClauseNode, candidate: ClauseNode) -> bool:
        cand_ids = set(candidate.token_ids)
        for child in parent.children:
            child_ids = set(child.token_ids)
            if cand_ids.issubset(child_ids):
                return attach_to_tree(child, candidate)
        
        parent_ids = set(parent.token_ids)
        if cand_ids.issubset(parent_ids) or candidate.head_token in parent.tokens:
            parent.children.append(candidate)
            return True
        return False

    for cand in child_candidates:
        attached = attach_to_tree(root_node, cand)
        if not attached:
            root_node.children.append(cand)

    return root_node.to_dict()


# ==============================================================================
# 5. High-Level Convenience API for Full Sentences & Text
# ==============================================================================

def analyze_syntax_tree(text_or_doc: Union[str, Doc]) -> Dict[str, Any]:
    """
    High-level entrypoint: Analyze all sentences in a text, returning for each sentence:
      - sentence_id
      - text
      - clause_tree (AST)
      - topology (5 fields: VF, LK, MF, RK, NF)
    """
    if isinstance(text_or_doc, str):
        if not text_or_doc.strip():
            return {"version": "3.5.0", "sentence_count": 0, "sentences": []}
        nlp = get_spacy_nlp()
        doc = nlp(text_or_doc)
    else:
        doc = text_or_doc

    results = []
    for s_idx, sent in enumerate(doc.sents):
        tree = build_clause_tree(sent)
        topology = analyze_sentence_topology(sent)
        results.append({
            "sentence_id": s_idx,
            "text": sent.text,
            "clause_tree": tree,
            "topology": topology
        })

    return {
        "version": "3.5.0",
        "sentence_count": len(results),
        "sentences": results
    }
