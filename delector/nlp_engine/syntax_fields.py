# -*- coding: utf-8 -*-
"""
DeLector - German Syntax Field Helpers.

自 ``delector/nlp_engine/syntax_tree.py`` 原样搬移（P1 纯搬移，零逻辑变更）：
只读/写局部变量、不 import ``syntax_tree``（单向依赖 ``syntax_tables``）。
"""

from typing import Any, List, Optional, Tuple

from .syntax_tables import (
    FINITE_MODAL_AND_AUX_FORMS,
    INFINITIVE_CONNECTORS,
    INTERROGATIVE_WORDS,
    RELATIVE_PRONOUNS,
    SUBORDINATING_CONJUNCTIONS,
)

# 与 syntax_tree 的 spaCy 降级占位同义：仅用于类型注解层，运行时不作断言（红线 1）。
Token = Any


def filter_non_punct_tokens(tokens: List[Token]) -> List[Token]:
    non_punct_tokens = [t for t in tokens if not t.is_punct and not t.is_space]
    if not non_punct_tokens:
        non_punct_tokens = tokens
    return non_punct_tokens


def find_main_finite_verb(tokens: List[Token]) -> Tuple[bool, Optional[Token]]:
    # Check if there is a main clause finite verb (e.g. following a comma in a preposed subclause)
    has_main_finite_verb = False
    main_fin_candidate: Optional[Token] = None

    # Look for a finite verb after a comma (V2 main clause after preposed subclause)
    for idx, t in enumerate(tokens):
        if t.text == "," and idx + 1 < len(tokens):
            next_tok = tokens[idx + 1]
            if (
                next_tok.pos_ in ("VERB", "AUX")
                or next_tok.tag_ in ("VVFIN", "VAFIN", "VMFIN")
                or next_tok.text.lower() in FINITE_MODAL_AND_AUX_FORMS
            ):
                has_main_finite_verb = True
                main_fin_candidate = next_tok
                break

    return has_main_finite_verb, main_fin_candidate


def detect_clause_type(
    tokens: List[Token], non_punct_tokens: List[Token], clause_type: str, has_main_finite_verb: bool
) -> Tuple[bool, bool, List[Token]]:
    # Determine Clause Verb Order & Type
    is_infinitiv = False
    is_subordinate = False
    connector_tokens: List[Token] = []

    # Check for infinitive with zu
    zu_tokens = [t for t in tokens if t.tag_ == "PTKZU" or t.dep_ == "pm" or t.text.lower() == "zu"]
    inf_verbs = [
        t
        for t in tokens
        if t.tag_ in ("VVINF", "VAINF", "VMINF") or (t.pos_ in ("VERB", "AUX") and "Inf" in t.morph.get("VerbForm", []))
    ]
    has_finite_verb = any(
        t.tag_ in ("VVFIN", "VAFIN", "VMFIN") or (t.pos_ in ("VERB", "AUX") and "Fin" in t.morph.get("VerbForm", []))
        for t in tokens
    )

    if (zu_tokens and inf_verbs) or any(t.tag_ == "VVIZU" for t in tokens):
        # Only set is_infinitiv if explicit or if the span has no finite verbs
        if clause_type in ("infinitivgruppe", "infinitiv") or not has_finite_verb:
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

    return is_infinitiv, is_subordinate, connector_tokens

