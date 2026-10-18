# -*- coding: utf-8 -*-
"""A1 工作台词库双向构建工具（ADR-0011 / Task 1）。

单一真相与投影结构
------------------
``delector/data/a1_workbench_dict.py`` 是 A1 工作台词库 membership 的**投影入口**（ADR-0015 T2）；
其词条内容/身份真源在 ``a1_sidecar``（id·letter·hw·ipa·ex）与 ``a1_fragments``（lemma 富字段）。
``static/js/wb-seed-data.js`` 里声明的四个常量是该 Python 投影模块的**构建产物**（C7 Task 4 起，
这四个常量从 ``static/german/workbench.html`` 抽到该数据模块）。

构建模式
--------
默认（无参）      Python 数据模块 → JS 数据模块注入：以模块为准重写四个 JS 声明（正常维护流）。
``--extract``    JS 数据模块 → Python 数据模块（bootstrap 专用）：把 ``static/js/wb-seed-data.js``
                 里的常量抽成纯字面量 Python 模块。
                 ⚠️ 危险操作：该操作会将 a1_workbench_dict.py 的 45 行 membership 投影入口覆盖为
                 760+ 行扁平字面量，故受 `--i-know-this-overwrites` 护栏保护，默认拒绝执行。

零漂移与幂等
------------
注入是**定点替换**：只重写 JS 数据模块里的 ``const <name> = <字面量>;`` 这一段，该文件
其余字节一字不动（含文件头注释、其余三个声明、EMBEDDED_AUDIO）。渲染完全由数据决定
（无时间戳、无随机化、无 map 迭代序漂移），故：

- 当前 JS 数据模块与模块同源时，注入一遍即**字节一致**（零漂移）；
- 连跑两次结果**字节一致**（幂等）。

这两条由 ``tests/test_a1_workbench_source.py`` 的
``test_injection_into_data_module_is_byte_identical`` /
``test_injection_is_idempotent`` 钉住 —— 「内联 const 是构建产物」这条契约因此仍
约束**真实产物字节**，而不是退化成「文件存在」。

本仓库行尾契约是 CRLF（``.gitattributes`` 的 ``* text=auto eol=crlf``），故注入一律
从目标文件自身探测行尾并保行尾写回（``newline=""``），绝不把整文件行尾改掉制造假 diff。

命令
----
    export PYTHONIOENCODING=utf-8
    python tools/build_workbench_seed.py                                    # 正常：Python 模块 → JS 模块注入（幂等）
    python tools/build_workbench_seed.py --extract --i-know-this-overwrites # bootstrap 专用：带护栏覆写
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
# JS 侧构建产物（C7 Task 4 起：四个数据常量在这里，不在 workbench.html 里）。
DEFAULT_JS = _REPO_ROOT / "static" / "js" / "wb-seed-data.js"
DEFAULT_MODULE = _REPO_ROOT / "delector" / "data" / "a1_workbench_dict.py"

# 四个 JS 声明：(解析键, const 名, 字面量左括号, 右括号)。
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


def parse_source(js_text: str) -> Dict[str, Any]:
    """把 static/js/wb-seed-data.js 里的四个常量解析成 {seed, core_ids, custom, aliases}。

    解析口径与搬迁前逐字一致（同一个 ``const <name> = <字面量>;`` 定位 + 括号配平），
    只是目标文件从 workbench.html 换成 JS 数据模块。
    """
    parsed: Dict[str, Any] = {}
    for key, name, open_ch, close_ch in _DECLARATIONS:
        start = js_text.index("const " + name)
        parsed[key] = json.loads(slice_balanced(js_text, start, open_ch, close_ch))
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
"""A1 工作台词库（workbench 静态种子）—— 由工具生成，仅供 bootstrap/恢复参考。

注意：生产环境当前采用 ADR-0015 T2 的 membership 动态投影入口形态（import 自 a1_sidecar）。
本扁平字面量形态由 tools/build_workbench_seed.py --extract --i-know-this-overwrites 生成。
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


def _js_values(
    seed: Sequence[Dict[str, Any]],
    core_ids: Iterable[str],
    custom: Sequence[Dict[str, Any]],
    aliases: Dict[str, str],
    newline: str,
) -> Dict[str, str]:
    """渲染四个常量的 JS 字面量（排版与既有内联块一致，注入即零漂移）。"""
    # JS 侧用 2 空格缩进（Python 模块文件用 4 空格），此处必须与既有排版一致。
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


def render_source(
    js_text: str,
    seed: Sequence[Dict[str, Any]],
    core_ids: Iterable[str],
    custom: Sequence[Dict[str, Any]],
    aliases: Dict[str, str],
) -> str:
    """以模块为准重写 JS 数据模块的四个声明，该文件其余字节一字不动。"""
    values = _js_values(seed, core_ids, custom, aliases, _detect_newline(js_text))
    out = js_text
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


def _run_extract(js_path: Path, module_path: Path) -> int:
    parsed = parse_source(_read_raw_text(js_path))
    module_path.parent.mkdir(parents=True, exist_ok=True)
    source = render_module(parsed["seed"], parsed["core_ids"], parsed["custom"], parsed["aliases"])
    _write_raw_text(module_path, source)
    print(
        "[build_workbench_seed] extract: seed=%d core_ids=%d custom=%d aliases=%d -> %s"
        % (len(parsed["seed"]), len(parsed["core_ids"]), len(parsed["custom"]), len(parsed["aliases"]), module_path)
    )
    return 0


def _run_inject(js_path: Path, module_path: Path) -> int:
    module = load_module(module_path)
    source = _read_raw_text(js_path)
    injected = render_source(
        source,
        seed=module.A1_WORKBENCH_SEED,
        core_ids=module.A1_WORKBENCH_CORE_IDS,
        custom=module.A1_WORKBENCH_CUSTOM,
        aliases=module.A1_WORKBENCH_ID_ALIASES,
    )
    changed = injected != source
    if changed:
        _write_raw_text(js_path, injected)
    print("[build_workbench_seed] inject: %s (changed=%s)" % (js_path, changed))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A1 工作台词库双向构建工具（JS 数据模块 <-> Python 数据模块）。")
    parser.add_argument(
        "--extract",
        action="store_true",
        help="JS 数据模块 -> Python 数据模块（bootstrap 专用；覆写危险，默认拒绝）",
    )
    parser.add_argument(
        "--i-know-this-overwrites",
        action="store_true",
        help="确认覆写 Python 数据模块（解除 --extract 的安全护栏）",
    )
    parser.add_argument("--js", default=str(DEFAULT_JS), help="JS 数据模块路径（static/js/wb-seed-data.js）")
    parser.add_argument("--module", default=str(DEFAULT_MODULE), help="Python 数据模块路径")
    args = parser.parse_args(argv)

    js_path = Path(args.js)
    module_path = Path(args.module)
    if args.extract:
        if module_path.exists() and not args.i_know_this_overwrites:
            sys.stderr.write(
                "[build_workbench_seed] 拒绝执行：目标 Python 模块 %s 已存在！\n"
                "该文件实际是手工维护的 membership 投影入口（ADR-0015 T2，import 自 a1_sidecar），\n"
                "直接 --extract 会将其覆写为 760+ 行字面量生成物，破坏原有投影结构。\n"
                "若仅为初次 bootstrap 或确需覆写，必须显式附加 --i-know-this-overwrites 护栏参数。\n"
                % module_path
            )
            return 2
        return _run_extract(js_path, module_path)
    return _run_inject(js_path, module_path)


if __name__ == "__main__":
    raise SystemExit(main())
