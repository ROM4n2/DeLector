# -*- coding: utf-8 -*-
"""纯数据字典子包（ADR-0008 Phase 1 Task 2）。

8 个只含常量/查表的纯数据模块从包根收进 `data/`：
互不依赖、零业务 import、import 期零副作用（红线 #9）。

保持原文件名（只加 `data/` 层级不改名），消费方统一改指
`from .data.<name> import …` 或 `from .data import <name>`（属性访问不变）。
"""

__all__ = [
    "a1_dict",
    "a1_hoeren_dict",
    "a1_lesen_dict",
    "a1_writing_dict",
    "core_dict",
    "core_dict_ext",
    "corpus_dict",
    "prep_dict",
]
