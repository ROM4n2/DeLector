# -*- coding: utf-8 -*-
"""A1 工作台词库双向构建工具（ADR-0011 / Task 1）。

单一真相
--------
``delector/data/a1_workbench_dict.py`` 是 A1 工作台词库的**唯一真相**；
``static/german/workbench.html`` 内联的四个常量是它的**构建产物**。

两种模式
--------
``--extract``    HTML → 数据模块（bootstrap）：把 HTML 里内联的 ``SEED_WORDS`` /
                 ``CORE_WORD_SEED_IDS`` / ``CORE_CUSTOM_WORDS`` / ``SEED_ID_ALIASES``
                 抽成模块常量。字段、id、顺序一律不改（逐字等价）。
默认（无参）      数据模块 → HTML 注入：以模块为准重写四个内联块。

零漂移与幂等
------------
注入是**定点替换**：只重写 ``const <name> = <字面量>;`` 这一段，HTML 其余字节一字
不动。渲染完全由数据决定（无时间戳、无随机化、无 map 迭代序漂移），故：

- 当前 HTML 与模块同源时，注入一遍即**字节一致**（零漂移）；
- 连跑两次结果**字节一致**（幂等）。

本仓库 ``core.autocrlf=true``：workbench.html 工作区是 CRLF、blob 是 LF，
故读写一律显式保行尾（``newline=""``），绝不把整文件行尾改掉制造假 diff。

命令
----
    export PYTHONIOENCODING=utf-8
    python tools/build_workbench_seed.py --extract   # HTML → 模块
    python tools/build_workbench_seed.py             # 模块 → HTML（幂等）

禁止手工改 ``delector/data/a1_workbench_dict.py`` —— 要改就重跑本脚本。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HTML = _REPO_ROOT / "static" / "german" / "workbench.html"
DEFAULT_MODULE = _REPO_ROOT / "delector" / "data" / "a1_workbench_dict.py"

# 四个内联声明：(解析键, const 名, 字面量左括号, 右括号)。
# 顺序即注入顺序：先声明的先写（CORE_* 必须排在 SEED_WORDS 之前，见既有权重测试）。
_DECLARATIONS = (
    ("seed", "SEED_WORDS", "[", "]"),
    ("core_ids", "CORE_WORD_SEED_IDS", "[", "]"),
    ("custom", "CORE_CUSTOM_WORDS", "[", "]"),
    ("aliases", "SEED_ID_ALIASES", "{", "}"),
)

# 核心词 id 每行写几个（与既有 HTML 排版一致，保证注入零漂移）。
_IDS_PER_LINE = 8


def slice_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str:
    """从 start 起找第一个 open_ch，返回到其配对 close_ch 的闭合切片。

    只做括号计数（与 tests/test_german_workbench.py 同口径）：四个常量里没有
    含括号的字符串字面量，故无需词法级扫描。
    """
    begin = text.index(open_ch, start)
    depth = 0
    for i in range(begin, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
            continue
        if ch != close_ch:
            continue
        depth -= 1
        if depth == 0:
            return text[begin : i + 1]
    raise ValueError("括号未闭合：%s ... %s" % (open_ch, close_ch))


def _decl_stmt_span(text: str, name: str, open_ch: str, close_ch: str) -> tuple[int, int]:
    """定位 ``const <name> = <字面量>;`` 的 [start, end) —— end 落在 `;` 之后。"""
    decl = "const " + name
    start = text.index(decl)
    literal = slice_balanced(text, start, open_ch, close_ch)
    lit_end = text.index(open_ch, start) + len(literal)
    return start, text.index(";", lit_end) + 1


def parse_html(html_text: str) -> Dict[str, Any]:
    """把 workbench.html 内联的四个常量解析成 {seed, core_ids, custom, aliases}。"""
    parsed: Dict[str, Any] = {}
    for key, name, open_ch, close_ch in _DECLARATIONS:
        start = html_text.index("const " + name)
        parsed[key] = json.loads(slice_balanced(html_text, start, open_ch, close_ch))
    return parsed


def _json_compact(value: Any) -> str:
    """紧凑 JSON（无空白），与 HTML 内联 SEED_WORDS 的既有排版一致。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _py_literal(value: Any) -> str:
    """把 JSON 值渲染成**单行 Python 字面量**（true/false/null → True/False/None）。

    不能直接 json.dumps：CORE_CUSTOM_WORDS 带 ``custom: true``，而 ``true`` 不是
    合法 Python 字面量。
    """
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, list):
        return "[" + ", ".join(_py_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ("%s: %s" % (json.dumps(k, ensure_ascii=False), _py_literal(v)) for k, v in value.items())
        return "{" + ", ".join(pairs) + "}"
    return json.dumps(value, ensure_ascii=False)


def _chunk_id_lines(ids: Sequence[str], indent: str = "    ") -> List[str]:
    """把 id 列表按每行 _IDS_PER_LINE 个渲染（末行不加尾逗号，与既有排版一致）。"""
    lines: List[str] = []
    for i in range(0, len(ids), _IDS_PER_LINE):
        chunk = ids[i : i + _IDS_PER_LINE]
        tail = "," if i + _IDS_PER_LINE < len(ids) else ""
        lines.append(indent + ", ".join('"%s"' % item for item in chunk) + tail)
    return lines


_MODULE_HEADER = '''# -*- coding: utf-8 -*-
"""A1 工作台词库（workbench 静态种子）—— 由工具生成，请勿手工编辑。

单一真相（Single Source of Truth）
    本模块即 A1 工作台词库的真源头。static/german/workbench.html 内联的
    const SEED_WORDS / CORE_WORD_SEED_IDS / CORE_CUSTOM_WORDS / SEED_ID_ALIASES
    是本模块的**构建产物**（由 tools/build_workbench_seed.py 注入）。

生成命令（Reproducible Command）
    export PYTHONIOENCODING=utf-8
    python tools/build_workbench_seed.py --extract   # HTML -> 本模块
    python tools/build_workbench_seed.py             # 本模块 -> HTML（幂等）

幂等与确定性（Determinism & Immutability）
    纯数据模块：导入期零副作用、零网络、零文件 IO（项目红线 9）。
    内容由 --extract 从 workbench.html 一次性抽出，字段/id/顺序逐字保留；
    **禁止手工改内容** —— 改则重跑 --extract，再跑默认模式把 HTML 重新注入。
"""
from typing import Any, Dict, FrozenSet, List
'''


def render_module(
    seed: Sequence[Dict[str, Any]],
    core_ids: Iterable[str],
    custom: Sequence[Dict[str, Any]],
    aliases: Dict[str, str],
) -> str:
    """渲染完整的数据模块源码（四个常量，每条数据一行）。"""
    parts: List[str] = [_MODULE_HEADER]
    parts.append("A1_WORKBENCH_SEED: List[Dict[str, Any]] = [")
    parts.extend("    %s," % _py_literal(word) for word in seed)
    parts.append("]")
    parts.append("")
    parts.append("A1_WORKBENCH_CORE_IDS: FrozenSet[str] = frozenset([")
    parts.extend(_chunk_id_lines(sorted(core_ids)))
    parts.append("])")
    parts.append("")
    parts.append("A1_WORKBENCH_CUSTOM: List[Dict[str, Any]] = [")
    parts.extend("    %s," % _py_literal(word) for word in custom)
    parts.append("]")
    parts.append("")
    parts.append("A1_WORKBENCH_ID_ALIASES: Dict[str, str] = {")
    parts.extend(
        "    %s: %s," % (json.dumps(k, ensure_ascii=False), json.dumps(v, ensure_ascii=False))
        for k, v in aliases.items()
    )
    parts.append("}")
    parts.append("")
    return "\n".join(parts)


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _html_values(
    seed: Sequence[Dict[str, Any]],
    core_ids: Iterable[str],
    custom: Sequence[Dict[str, Any]],
    aliases: Dict[str, str],
    newline: str,
) -> Dict[str, str]:
    """渲染四个常量的 JS 字面量（排版与既有 HTML 一致，注入即零漂移）。"""
    # HTML 内联块用 2 空格缩进（模块文件用 4 空格），此处必须与既有排版一致。
    core_lines = _chunk_id_lines(sorted(core_ids), indent="  ")
    custom_lines = [
        "  %s%s" % (json.dumps(word, ensure_ascii=False), "," if i < len(custom) - 1 else "")
        for i, word in enumerate(custom)
    ]
    alias_pairs = ", ".join(
        "%s: %s" % (json.dumps(k, ensure_ascii=False), json.dumps(v, ensure_ascii=False)) for k, v in aliases.items()
    )
    values = {
        "seed": _json_compact(seed),
        "core_ids": "new Set([\n" + "\n".join(core_lines) + "\n])",
        "custom": "[\n" + "\n".join(custom_lines) + "\n]",
        "aliases": "{ " + alias_pairs + " }",
    }
    if newline != "\n":
        values = {key: value.replace("\n", newline) for key, value in values.items()}
    return values


def render_html(
    html_text: str,
    seed: Sequence[Dict[str, Any]],
    core_ids: Iterable[str],
    custom: Sequence[Dict[str, Any]],
    aliases: Dict[str, str],
) -> str:
    """以模块为准重写 HTML 的四个内联块，其余字节一字不动。"""
    values = _html_values(seed, core_ids, custom, aliases, _detect_newline(html_text))
    out = html_text
    for key, name, open_ch, close_ch in _DECLARATIONS:
        start, end = _decl_stmt_span(out, name, open_ch, close_ch)
        out = out[:start] + "const %s = %s;" % (name, values[key]) + out[end:]
    return out


def _read_raw_text(path: Path) -> str:
    """读文本且**不做行尾翻译**（newline="" 保留 CRLF）。"""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_raw_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def load_module(module_path: Path) -> ModuleType:
    """加载数据模块（ADR-0015：模块已投影依赖 package，须保证 repo root 在 sys.path）。"""
    repo_root = str(_REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    spec = importlib.util.spec_from_file_location("a1_workbench_dict_source", str(module_path))
    if spec is None or spec.loader is None:  # pragma: no cover - 路径不可用时
        raise SystemExit("[build_workbench_seed] 无法加载数据模块：%s" % module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_extract(html_path: Path, module_path: Path) -> int:
    parsed = parse_html(_read_raw_text(html_path))
    module_path.parent.mkdir(parents=True, exist_ok=True)
    source = render_module(parsed["seed"], parsed["core_ids"], parsed["custom"], parsed["aliases"])
    with open(module_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source)
    print(
        "[build_workbench_seed] extract: seed=%d core_ids=%d custom=%d aliases=%d -> %s"
        % (len(parsed["seed"]), len(parsed["core_ids"]), len(parsed["custom"]), len(parsed["aliases"]), module_path)
    )
    return 0


def _run_inject(html_path: Path, module_path: Path) -> int:
    module = load_module(module_path)
    html = _read_raw_text(html_path)
    injected = render_html(
        html,
        seed=module.A1_WORKBENCH_SEED,
        core_ids=module.A1_WORKBENCH_CORE_IDS,
        custom=module.A1_WORKBENCH_CUSTOM,
        aliases=module.A1_WORKBENCH_ID_ALIASES,
    )
    changed = injected != html
    if changed:
        _write_raw_text(html_path, injected)
    print("[build_workbench_seed] inject: %s (changed=%s)" % (html_path, changed))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A1 工作台词库双向构建工具（HTML <-> 数据模块）。")
    parser.add_argument("--extract", action="store_true", help="HTML -> 数据模块（bootstrap；逐字等价）")
    parser.add_argument("--html", default=str(DEFAULT_HTML), help="workbench.html 路径")
    parser.add_argument("--module", default=str(DEFAULT_MODULE), help="数据模块路径")
    args = parser.parse_args(argv)

    html_path = Path(args.html)
    module_path = Path(args.module)
    if args.extract:
        return _run_extract(html_path, module_path)
    return _run_inject(html_path, module_path)


if __name__ == "__main__":
    raise SystemExit(main())
