# -*- coding: utf-8 -*-
"""NLP 引擎子包：spaCy 德语处理流水线、句法树分析与语言学业余资料。

原扁平模块 nlp.py / syntax_tree.py / linguistics.py 收进本子包
（nlp.py 因与子包职责重复改名 processor.py）。对外稳定接口在此 re-export，
Go Agent 工具层与外部消费者一律从 deletor.nlp_engine 取，不直接依赖子模块名。
"""
from .processor import (  # noqa: F401
    process_german_text,
    calculate_cefr_stats,
    get_cefr_level,
)
from .syntax_tree import (  # noqa: F401
    analyze_syntax_tree,
    analyze_sentence_topology,
    build_clause_tree,
    split_sentences_pure_python,
)
from .linguistics import (  # noqa: F401
    lookup_irregular_verb,
    is_irregular_verb,
    get_verb_stammformen,
    lookup_linguistics_ext,
    split_komposita,
    lookup_prep_collocations,
    build_prep_matrix_core,
    build_prep_matrix,
)

__all__ = [
    "process_german_text",
    "calculate_cefr_stats",
    "get_cefr_level",
    "analyze_syntax_tree",
    "analyze_sentence_topology",
    "build_clause_tree",
    "split_sentences_pure_python",
    "lookup_irregular_verb",
    "is_irregular_verb",
    "get_verb_stammformen",
    "lookup_linguistics_ext",
    "split_komposita",
    "lookup_prep_collocations",
    "build_prep_matrix_core",
    "build_prep_matrix",
]
