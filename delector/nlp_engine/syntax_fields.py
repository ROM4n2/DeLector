# -*- coding: utf-8 -*-
"""
DeLector - German Syntax Field Helpers.

自 ``delector/nlp_engine/syntax_tree.py`` 原样搬移（P1 纯搬移，零逻辑变更）：
只读/写局部变量、不 import ``syntax_tree``（单向依赖 ``syntax_tables``）。
"""

from typing import Any, List, Optional, Tuple

from .syntax_tables import FINITE_MODAL_AND_AUX_FORMS

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
