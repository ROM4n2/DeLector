# -*- coding: utf-8 -*-
"""从源码 AST 现读模块的「公开名清单」——切分安全网的基线生成器。

背景
----
`delector/core/database.py` 按职责切成包时，**公开面 MUST 零变化**（32 个 import 点
一行不改）。本工具从**源码 AST 现读**出模块顶层的公开名（函数 / 类 / 变量），输出
JSON（名字 → 类型）；调用方据此把「切分前公开名清单」**固化**进测试，断言 façade
导出集 ⊇ 基线 —— 任何一处「漏搬」都会让测试转红。基线 MUST 由本工具生成后粘进测试，
**不手抄**（手抄的清单不随功能增长）。

扫描口径（与计划 Task 1 Step 1 逐字对齐）
----------------------------------------
- 只扫**模块 body 顶层**的 ``FunctionDef`` / ``AsyncFunctionDef`` / ``ClassDef`` /
  ``Assign``（嵌套在函数/类内的定义不算公开面）；
- ``Assign`` **支持多目标**（``a = b = ...``）与元组/列表解包目标（``a, b = ...``，
  含 ``a, *b``）；
- **排除** ``_`` 前缀的私有名；
- **排除** ``if __name__ == "__main__":`` 块内的定义（那是脚本入口，不是公开面）；
- 输出 ``{"名字": "function|async_function|class|variable"}``（按键排序，稳定 diff）。

用法
----
    python tools/dump_module_public_names.py delector/core/database.py
    python tools/dump_module_public_names.py delector/core/database.py --pretty
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from typing import Dict, Iterator, List, Optional

# 名字类型 → 语义标签。刻意与「节点类型」区分：调用方关心的是「这是个函数还是常量」。
_FUNCTION: str = "function"
_ASYNC_FUNCTION: str = "async_function"
_CLASS: str = "class"
_VARIABLE: str = "variable"


def _is_dunder_main_guard(node: ast.stmt) -> bool:
    """判断是否 ``if __name__ == "__main__":``（只认这一种精确形态，不做模糊匹配）。"""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _iter_target_names(target: ast.expr) -> Iterator[str]:
    """展开赋值目标的 ``Name``：支持元组/列表解包与 ``*`` 展开；其余（下标/属性）忽略。"""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _iter_target_names(elt)
    elif isinstance(target, ast.Starred):
        yield from _iter_target_names(target.value)


def _record(result: Dict[str, str], name: str, kind: str) -> None:
    """登记一个公开名：``_`` 前缀是私有面，不进入清单。"""
    if name.startswith("_"):
        return
    result[name] = kind


def collect_public_names(source: str, filename: str = "<unknown>") -> Dict[str, str]:
    """返回 ``{公开名: 类型}``（按键排序）。纯函数：只读源码字符串，无副作用。"""
    tree = ast.parse(source, filename=filename)
    result: Dict[str, str] = {}
    for node in tree.body:
        # 只处理模块 body 顶层的 def/class/Assign；其余（含 if/for/try）一律不下探 ——
        # 这天然排除了 `if __name__ == "__main__":` 块内与函数/类内部的定义。
        if _is_dunder_main_guard(node):
            continue
        if isinstance(node, ast.AsyncFunctionDef):
            _record(result, node.name, _ASYNC_FUNCTION)
        elif isinstance(node, ast.FunctionDef):
            _record(result, node.name, _FUNCTION)
        elif isinstance(node, ast.ClassDef):
            _record(result, node.name, _CLASS)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _iter_target_names(target):
                    _record(result, name, _VARIABLE)
    return dict(sorted(result.items()))


def dump_path(path: str) -> Dict[str, str]:
    """读文件（保留行尾、按 UTF-8）并抽取公开名清单。"""
    with open(path, "r", encoding="utf-8") as handle:
        return collect_public_names(handle.read(), filename=path)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从源码 AST 现读模块的公开名清单（JSON）。")
    parser.add_argument("path", help="要扫描的 Python 源文件路径")
    parser.add_argument("--pretty", action="store_true", help="缩进输出（默认单行紧凑 JSON）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    names = dump_path(args.path)
    if args.pretty:
        print(json.dumps(names, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(names, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
