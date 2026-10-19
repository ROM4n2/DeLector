# -*- coding: utf-8 -*-
"""前端分层与模块图完整性机械闸 (Frontend Layer Invariants Gate)。

依据 `docs/plans/2026-10-19-writer-js-modularization.md` Task 4。本文件的判据经一轮
**独立对抗式复核**后整体重写（见文件末尾「复核驱动的重写」）—— 初版是**正则块表**，
被证明可被引号变化、别名、副作用型 import、正则字面量等多种方式绕过。现版本改为
**真词法分析（tokenize）** 驱动。

分层声明（`LAYER_SPEC`）
----------------------
  L1 `static/js/wr-format.js`  纯格式化 / 领域文案层
  L1 `static/js/rd-syntax.js`  纯格式化层（阅读器语法统计与渲染）
  L1 `static/js/wb-queue.js`   纯格式化层（复习队列构建 / 调度族）
  L1 `static/js/wb-scope.js`   纯格式化层（词表 scope / CEFR 等级判定）
  L2 `static/js/wr-api.js`     持久化访问层（写作台网络访问）
  L2 `static/js/rd-api.js`     持久化访问层（阅读器网络访问；模块由 Task 2 产出）

规则清单
--------
  ①② 分层硬禁令：按**标识符 token** 判（不是「函数调用形态」），故别名
      `const _net = fetch;`、可选链 `notify?.(x)`、下标取用 `g['setTimeout']`
      都逃不掉（后者落在字符串 token 里，另行扫描）。顶层 `let`/`var` 按
      **花括号净深度 0** 判，不依赖「列 0」。
  ③  反向依赖 + ③b import 白名单：token 级判，覆盖具名 / 默认 / 命名空间 /
      **副作用型** `import './x.js'` / `export … from` / 动态 `import('./x.js')`；
      比**整条相对路径**而非 basename（`./vendor/core.js` 不再冒充 `./core.js`）。
  ④  重复声明：导入绑定名（三种形态都算）MUST NOT 又在**顶层**声明。ES 对重复声明是
      **链接期 SyntaxError**，会让整张模块图一起挂（本仓 v4.7.0 同类事故）。只判顶层，
      因为函数内的同名声明是**合法遮蔽**，判它会造假红。
  ⑤  调用一致性：L2 模块（`wr-api.js`、`rd-api.js` 等）里每个 `api(...)` / `fetch(...)`
      的 (路径, 方法) MUST 命中后端注册表。**路径**维度另有闸（`check_frontend_api_contract.py`，
      用真实路由表），本闸只补**方法**维度；但**解析不出来就判失败**（fail-closed）：路径非字面量 ⇒
      `unverifiable-path`，`method:` 出现却取不到字面量值（双引号/反引号/取自变量/简写）
      ⇒ `unverifiable-method`。MUST NOT 猜一个 GET 蒙过去。
  ⑥  防假解耦：`writer.js` MUST NOT 在**顶层**重新定义已迁出到 L1/L2 的符号
      （含 `function*`；`export {…}` 再导出不算声明）。

判定纪律
--------
- **先词法分析再判**：注释、字符串、模板字面量、正则字面量各自成 token。这是必需而非
  洁癖 —— 初版用正则剥注释，遇到 `wr-format.js` 里那个含 `"` 与 `'` 的正则字面量
  `/(\\s+|[.,!?;:„"“'«»()—–-])/` 就误开「字符串」状态，导致其后**真实注释未被剥离**，
  并留下「正则字面量可掩蔽真实代码」的假绿通道。
- **块表是纵深防御，不是证明**：标识符块表永远不可能穷尽（真实保证来自「L1 只有一百来行
  且有人读」+ 参数保真探针）。本闸的目标是把**已知的**绕过通道逐条堵上，并在 docstring
  里如实标注「这是块表」。
- **失败要响**：解析不出来一律判失败（`unverifiable-*`），MUST NOT 用默认值蒙混。
- **行级归因**：违规报 `文件:行号:规则:原始行`，同一 (文件,行,规则) 只报一次。
- **退出码即结论**：0 = 全绿；1 = 有违规（逐条打印）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

# 直接 `python3 tools/check_frontend_layers.py` 时 sys.path[0] 是 tools/ 而非仓库根
# ⇒ `import delector` 会 ModuleNotFoundError。与 `check_frontend_api_contract.py:60` 同口径。
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ══ 词法分析 ══════════════════════════════════════════════════════════════════
class Tok(NamedTuple):
    kind: str  # 'id' | 'str' | 'tpl' | 'regex' | 'num' | 'punct'
    text: str  # id: 标识符；str/tpl/regex: **内容**（不含引号/斜杠）；num/punct: 原文
    line: int  # 1-based


# 这些标识符本身可作为「表达式结尾」⇒ 其后紧跟的 `/` 是**除号**
_EXPR_ENDING_KEYWORDS = frozenset({"this", "true", "false", "null", "undefined", "super"})
# 这些关键字之后出现的 `/` 一定是**正则起始**（`return /re/`、`typeof /re/` …）
_REGEX_PRECEDING_KEYWORDS = frozenset(
    {
        "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
        "case", "do", "else", "yield", "await", "throw",
    }
)
_PUNCT_OPERATORS = (
    "===", "!==", "**=", "=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.",
    "++", "--", "+=", "-=", "*=", "/=", "**",
)


def _prev_ends_expression(prev: Optional[Tok]) -> bool:
    """前一个有效 token 能否作为表达式结尾（决定 `/` 是除号还是正则起始）。"""
    if prev is None:
        return False
    if prev.kind in ("num", "str", "tpl", "regex"):
        return True
    if prev.kind == "punct":
        return prev.text in (")", "]", "}", "++", "--")
    if prev.kind == "id":
        return prev.text not in _REGEX_PRECEDING_KEYWORDS
    return False


def tokenize(text: str, base_line: int = 1) -> List[Tok]:
    """把 JS 源码切成 token。注释不产出 token（等价于被丢弃）。

    正则字面量 vs 除号歧义用标准启发式消解：**前一个有效 token 能否作为表达式结尾**。
    已知边界是 `}`：块结束（应为正则）与对象字面量结束（应为除号）在无解析器时无法区分 ——
    被纳管模块里不出现该形态；出现时按「正则」解释（保守：宁可把代码当正则吃掉，
    也不把正则当代码判）。
    """
    toks: List[Tok] = []
    i, n = 0, len(text)
    line = base_line
    prev: Optional[Tok] = None

    def push(kind: str, value: str, ln: int) -> None:
        nonlocal prev
        prev = Tok(kind, value, ln)
        toks.append(prev)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r\f\v":
            i += 1
            continue

        if ch == "/" and nxt == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue

        if ch in "'\"":
            start_line, quote = line, ch
            i += 1
            buf: List[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                if c == "\n":
                    line += 1
                buf.append(c)
                i += 1
            push("str", "".join(buf), start_line)
            continue

        if ch == "`":
            start_line = line
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == "`":
                    i += 1
                    break
                if c == "$" and i + 1 < n and text[i + 1] == "{":
                    push("tpl", "".join(buf), start_line)
                    buf = []
                    i += 2
                    depth = 1
                    inner_start = i
                    while i < n and depth:
                        cc = text[i]
                        if cc == "\n":
                            line += 1
                        elif cc == "{":
                            depth += 1
                        elif cc == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        i += 1
                    # 插值内部按普通 JS 递归切（可能含被禁标识符，如 `${document.title}`）
                    toks.extend(tokenize(text[inner_start:i], line))
                    prev = toks[-1] if toks else prev
                    i += 1  # 跳过 `}`
                    start_line = line
                    continue
                if c == "\n":
                    line += 1
                buf.append(c)
                i += 1
            push("tpl", "".join(buf), start_line)
            continue

        if ch.isdigit() or (ch == "." and nxt.isdigit()):
            start = i
            while i < n and (text[i].isalnum() or text[i] in "._"):
                i += 1
            push("num", text[start:i], line)
            continue

        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            push("id", text[i:j], line)
            i = j
            continue

        if ch == "/":
            if _prev_ends_expression(prev):
                push("punct", "/", line)
                i += 1
                continue
            start = i
            i += 1
            in_class = False
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == "\n":
                    break
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                i += 1
            content = text[start + 1 : i]
            i += 1  # 跳过结束斜杠
            while i < n and text[i].isalpha():  # regex flags
                i += 1
            push("regex", content, line)
            continue

        for op in _PUNCT_OPERATORS:
            if text.startswith(op, i):
                push("punct", op, line)
                i += len(op)
                break
        else:
            push("punct", ch, line)
            i += 1

    return toks


# ══ 分层声明 ══════════════════════════════════════════════════════════════════
class LayerSpec(NamedTuple):
    layer: str
    ban_rules: Tuple[str, ...]
    allowed_imports: Tuple[str, ...]


# 标识符块表（**块表，不可能是证明** —— 见模块 docstring）。
BAN_IDENTIFIERS: Dict[str, "frozenset[str]"] = {
    "dom": frozenset(
        {
            "document", "window", "navigator", "localStorage", "sessionStorage",
            "getElementById", "querySelector", "querySelectorAll", "getElementsByClassName",
            "getElementsByTagName", "innerHTML", "outerHTML", "innerText", "textContent",
            "addEventListener", "removeEventListener", "classList", "createElement",
            "createTextNode", "createDocumentFragment", "appendChild", "removeChild",
            "replaceChild", "insertBefore", "insertAdjacentHTML", "insertAdjacentElement",
            "insertAdjacentText", "setAttribute", "getAttribute", "removeAttribute",
            "dispatchEvent", "getBoundingClientRect", "scrollIntoView", "offsetWidth",
            "offsetHeight", "clientWidth", "clientHeight", "closest", "matches",
            "location", "history", "postMessage", "matchMedia", "requestFullscreen",
        }
    ),
    "network": frozenset(
        {"fetch", "api", "XMLHttpRequest", "EventSource", "WebSocket", "sendBeacon"}
    ),
    "toast": frozenset({"notify", "alert", "confirm", "prompt"}),
    "timer": frozenset({"setTimeout", "setInterval", "requestAnimationFrame", "requestIdleCallback"}),
    "dynamic-eval": frozenset({"eval", "Function", "importScripts"}),
}

LAYER_SPEC: Dict[str, LayerSpec] = {
    "wr-format.js": LayerSpec(
        layer="L1 纯格式化层",
        ban_rules=("dom", "network", "toast", "timer", "dynamic-eval"),
        allowed_imports=("./core.js",),
    ),
    "rd-syntax.js": LayerSpec(
        layer="L1 纯格式化层",
        ban_rules=("dom", "network", "toast", "timer", "dynamic-eval"),
        allowed_imports=("./core.js",),
    ),
    "wb-queue.js": LayerSpec(
        layer="L1 纯格式化层",
        ban_rules=("dom", "network", "toast", "timer", "dynamic-eval"),
        allowed_imports=(),
    ),
    "wb-scope.js": LayerSpec(
        layer="L1 纯格式化层",
        ban_rules=("dom", "network", "toast", "timer", "dynamic-eval"),
        allowed_imports=(),
    ),
    "wr-api.js": LayerSpec(
        layer="L2 持久化访问层",
        ban_rules=("dom", "toast", "timer", "dynamic-eval"),
        allowed_imports=("./core.js",),
    ),
    "rd-api.js": LayerSpec(
        layer="L2 持久化访问层",
        ban_rules=("dom", "toast", "timer", "dynamic-eval"),
        allowed_imports=("./core.js",),
    ),
}

# L1 纯层硬契约含「零顶层 let/var」⇒ 一并纳管（只收紧，不放松）。
MUTABLE_STATE_MODULES: Tuple[str, ...] = (
    "wr-format.js",
    "rd-syntax.js",
    "wb-queue.js",
    "wb-scope.js",
)
MUTABLE_KEYWORDS = frozenset({"let", "var"})

VIEW_MODULES: Tuple[str, ...] = ("writer.js",)
FALSE_DECOUPLING_HOST = "writer.js"

API_CALL_NAMES = ("api", "fetch")
DECL_KEYWORDS = frozenset({"function", "class", "const", "let", "var"})

_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
_TPL_INTERP_RE = re.compile(r"\$\{[^}]*\}")


class Violation(NamedTuple):
    rel_path: str
    lineno: int
    rule: str
    raw: str

    def render(self) -> str:
        return f"{self.rel_path}:{self.lineno}:{self.rule}:{self.raw.strip()}"


# ══ 读取与工具 ═══════════════════════════════════════════════════════════════
def read_js(path: Path) -> Tuple[str, List[Tok]]:
    raw = path.read_text(encoding="utf-8")
    return raw, tokenize(raw)


def raw_line_of(raw: str, lineno: int) -> str:
    lines = raw.splitlines()
    return lines[lineno - 1] if 0 < lineno <= len(lines) else ""


def strip_comments(text: str) -> str:
    """剥注释（字符串与正则**原样保留**），保留换行与长度，供诊断使用。

    判定本身走 token（`tokenize`），不依赖本函数 —— 它存在的意义是让「注释不参与判定」
    这件事可被单独断言。
    """
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            out.append("  ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append(c)
                i += 1
                if c == quote:
                    break
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _dedupe(violations: Sequence[Violation]) -> List[Violation]:
    seen: Set[Tuple[str, int, str]] = set()
    out: List[Violation] = []
    for v in violations:
        key = (v.rel_path, v.lineno, v.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


# ══ 规则①②：标识符 + 字符串内容 + 顶层可变状态 ═══════════════════════════════
def check_layer_bans(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name, spec in LAYER_SPEC.items():
        path = js_dir / name
        if not path.exists():
            out.append(
                Violation(f"static/js/{name}", 1, "missing-layer-module", "声明的分层模块不存在")
            )
            continue
        raw, toks = read_js(path)

        banned: Dict[str, str] = {}
        for rule in spec.ban_rules:
            for ident in BAN_IDENTIFIERS[rule]:
                banned[ident] = rule

        # ① 标识符 token：覆盖属性访问、别名、可选链、回调、未调用
        for t in toks:
            if t.kind == "id" and t.text in banned:
                out.append(
                    Violation(
                        f"static/js/{name}", t.line, f"{spec.layer}禁{banned[t.text]}",
                        raw_line_of(raw, t.line),
                    )
                )
        # ② 字符串/模板内容：挡住 `g['setTimeout']` 这类下标取用（名字落在字符串里）
        for t in toks:
            if t.kind not in ("str", "tpl"):
                continue
            for ident in _IDENT_RE.findall(t.text):
                if ident in banned:
                    out.append(
                        Violation(
                            f"static/js/{name}", t.line,
                            f"{spec.layer}禁{banned[ident]}(字符串内)",
                            raw_line_of(raw, t.line),
                        )
                    )
        # ③ 顶层可变状态：花括号**净深度 0** 处的 let/var
        if name in MUTABLE_STATE_MODULES:
            depth = 0
            for t in toks:
                if t.kind == "punct":
                    if t.text == "{":
                        depth += 1
                    elif t.text == "}":
                        depth = max(0, depth - 1)
                    continue
                if t.kind == "id" and depth == 0 and t.text in MUTABLE_KEYWORDS:
                    out.append(
                        Violation(
                            f"static/js/{name}", t.line, f"{spec.layer}禁mutable-state",
                            raw_line_of(raw, t.line),
                        )
                    )
    return out


# ══ 规则③/③b：import 目标 ════════════════════════════════════════════════════
def import_targets(toks: List[Tok]) -> List[Tuple[int, str, str]]:
    """产出 (行号, 模块说明符, 形态)。形态 ∈ {from-clause, bare}。

    不依赖 `^` 锚或空白：`import{b}from'./x.js'` 与 `import './x.js'` 同等对待；
    也覆盖 `export {a} from './x.js'` 与动态 `import('./x.js')`。
    """
    out: List[Tuple[int, str, str]] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "id":
            continue
        if t.text == "from" and i + 1 < n and toks[i + 1].kind in ("str", "tpl"):
            prev = toks[i - 1] if i > 0 else None
            # `from` 前必须是 `}`（具名/再导出）、`]`/`)` 少见形态、或标识符（命名空间 `* as ns`）
            if prev is not None and (
                prev.kind == "id" or (prev.kind == "punct" and prev.text in ("}", "]", ")"))
            ):
                out.append((t.line, toks[i + 1].text, "from-clause"))
        elif t.text == "import":
            j = i + 1
            if j < n and toks[j].kind == "punct" and toks[j].text == "(":
                j += 1  # 动态 import('./x.js')
            if j < n and toks[j].kind in ("str", "tpl"):
                out.append((t.line, toks[j].text, "bare"))
    return out


def _import_basename(spec_path: str) -> str:
    return spec_path.strip().lstrip("./").split("/")[-1].split("?")[0]


def check_reverse_deps(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name in LAYER_SPEC:
        path = js_dir / name
        if not path.exists():
            continue
        raw, toks = read_js(path)
        for lineno, spec_path, _form in import_targets(toks):
            if _import_basename(spec_path) in VIEW_MODULES:
                out.append(
                    Violation(
                        f"static/js/{name}", lineno, "reverse-dependency", raw_line_of(raw, lineno)
                    )
                )
    return out


def check_import_allowlist(js_dir: Path) -> List[Violation]:
    """比**整条相对路径**而非 basename —— `./vendor/core.js` MUST NOT 冒充 `./core.js`。"""
    out: List[Violation] = []
    for name, spec in LAYER_SPEC.items():
        path = js_dir / name
        if not path.exists():
            continue
        raw, toks = read_js(path)
        allowed = {a.lstrip("./") for a in spec.allowed_imports}
        for lineno, spec_path, _form in import_targets(toks):
            normalized = spec_path.strip().lstrip("./").split("?")[0]
            if normalized not in allowed:
                out.append(
                    Violation(
                        f"static/js/{name}", lineno,
                        f"{spec.layer}越界import({normalized})", raw_line_of(raw, lineno),
                    )
                )
    return out


# ══ 规则④/⑥：声明名采集（含三种导入绑定与逗号声明列表）═══════════════════════
def import_bindings(toks: List[Tok]) -> Set[str]:
    """导入引入的**本地绑定名**：具名 `{a, b as c}` / 命名空间 `* as ns` / 默认 `import X`。"""
    names: Set[str] = set()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "id" or t.text != "import":
            continue
        j = i + 1
        if j >= n:
            continue
        if toks[j].kind == "punct":
            if toks[j].text == "(":
                continue  # 动态 import，无绑定
            if toks[j].text == "*":
                if j + 2 < n and toks[j + 1].kind == "id" and toks[j + 1].text == "as":
                    names.add(toks[j + 2].text)
                continue
            if toks[j].text == "{":
                k, depth = j + 1, 1
                while k < n and depth:
                    tk = toks[k]
                    if tk.kind == "punct" and tk.text == "{":
                        depth += 1
                    elif tk.kind == "punct" and tk.text == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    elif depth == 1 and tk.kind == "id":
                        if k + 2 < n and toks[k + 1].kind == "id" and toks[k + 1].text == "as":
                            names.add(toks[k + 2].text)
                            k += 3
                            continue
                        names.add(tk.text)
                    k += 1
                continue
        if toks[j].kind == "id":
            names.add(toks[j].text)  # 默认导入
    return names


def local_declarations(toks: List[Tok], top_level_only: bool = True) -> Set[str]:
    """本模块声明的名字。含 `function*` 与逗号声明列表 `const a = 1, b = 2;`。

    `top_level_only=True` 时只收花括号净深度 0 的声明 —— 函数内的同名声明是**合法遮蔽**，
    收它会与规则④（重复声明 = 链接期 SyntaxError）的语义不符，造成假红。
    """
    names: Set[str] = set()
    n = len(toks)
    depth = 0
    i = 0
    while i < n:
        t = toks[i]
        if t.kind == "punct":
            if t.text == "{":
                depth += 1
            elif t.text == "}":
                depth = max(0, depth - 1)
            i += 1
            continue
        if t.kind != "id" or t.text not in DECL_KEYWORDS:
            i += 1
            continue
        if top_level_only and depth != 0:
            i += 1
            continue
        j = i + 1
        while j < n and toks[j].kind == "punct" and toks[j].text in ("*", ","):
            j += 1
        if j < n and toks[j].kind == "id":
            names.add(toks[j].text)
            # 逗号声明列表（深度与声明同级才继续收）
            k, d2 = j + 1, 0
            while k < n:
                tk = toks[k]
                if tk.kind == "punct":
                    if tk.text in ("(", "[", "{"):
                        d2 += 1
                    elif tk.text in (")", "]", "}"):
                        if d2 == 0:
                            break
                        d2 -= 1
                    elif tk.text == ";" and d2 == 0:
                        break
                    elif tk.text == "," and d2 == 0 and k + 1 < n and toks[k + 1].kind == "id":
                        names.add(toks[k + 1].text)
                k += 1
        i = j + 1
    return names


def check_duplicate_declarations(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name in sorted({*LAYER_SPEC, *VIEW_MODULES}):
        path = js_dir / name
        if not path.exists():
            continue
        raw, toks = read_js(path)
        dupes = import_bindings(toks) & local_declarations(toks, top_level_only=True)
        for dup in sorted(dupes):
            lineno = next((t.line for t in toks if t.kind == "id" and t.text == dup), 1)
            out.append(
                Violation(
                    f"static/js/{name}", lineno, f"duplicate-declaration({dup})",
                    raw_line_of(raw, lineno),
                )
            )
    return out


# ══ 规则⑤：调用一致性（方法维度；解析不出来即失败）══════════════════════════
class ApiCall(NamedTuple):
    lineno: int
    name: str
    path: Optional[str]
    method: Optional[str]
    method_seen: bool


def _tokens_in_parens(toks: List[Tok], open_idx: int) -> List[Tok]:
    """括号配平取出 open_idx（`(`）内的一级 token（不含该括号本身）。"""
    depth = 0
    out: List[Tok] = []
    for k in range(open_idx, len(toks)):
        t = toks[k]
        if t.kind == "punct" and t.text in ("(", "[", "{"):
            depth += 1
            if depth == 1:
                continue
        elif t.kind == "punct" and t.text in (")", "]", "}"):
            depth -= 1
            if depth == 0:
                return out
        if depth == 0 and t.kind == "punct" and t.text == ",":
            return out
        out.append(t)
    return out


def _split_top_level(toks: List[Tok]) -> List[List[Tok]]:
    """按**顶层逗号**把实参 token 切成各实参（括号/中括号/花括号内的逗号不算）。"""
    groups: List[List[Tok]] = []
    cur: List[Tok] = []
    depth = 0
    for t in toks:
        if t.kind == "punct":
            if t.text in ("(", "[", "{"):
                depth += 1
            elif t.text in (")", "]", "}"):
                depth -= 1
            elif t.text == "," and depth == 0:
                groups.append(cur)
                cur = []
                continue
        cur.append(t)
    groups.append(cur)
    return groups


def _first_arg_path(arg: List[Tok]) -> Optional[str]:
    """首个实参 → 归一化路径。字面量与变量 `+` 拼接按既有路由闸同口径折算 `{}`；
    首段不是 `/` 开头（纯变量、或模板以变量起头）⇒ None（fail-closed）。"""
    segs: List[str] = []
    for a in arg:
        if a.kind in ("str", "tpl"):
            segs.append(_TPL_INTERP_RE.sub("{}", a.text))
        elif a.kind == "punct" and a.text in ("+", "."):
            continue
        else:
            segs.append("{}")
    if not segs:
        return None
    joined = "".join(segs)
    return joined if joined.startswith("/") else None


def scan_api_calls(toks: List[Tok]) -> List[ApiCall]:
    """扫 `api(...)` / `fetch(...)`。路径与方法都必须能静态求值，否则记 None 判失败。"""
    calls: List[ApiCall] = []
    for i, t in enumerate(toks):
        if t.kind != "id" or t.text not in API_CALL_NAMES:
            continue
        if i + 1 >= len(toks) or toks[i + 1].kind != "punct" or toks[i + 1].text != "(":
            continue
        args = _split_top_level(_tokens_in_parens(toks, i + 1))
        method: Optional[str] = None
        seen, method = _scan_method_key(args[1:])
        calls.append(ApiCall(t.line, t.text, _first_arg_path(args[0]), method, seen))
    return calls


def _scan_method_key(groups: List[List[Tok]], _unused: object = None) -> Tuple[bool, Optional[str]]:
    """在选项对象**第一层**找 `method` 键：返回 (是否出现, 字面量方法或 None)。

    只认 depth==1（选项对象直接那一层），避免嵌套对象里的同名键误触发。
    简写 `{ method }`、变量值 `{ method: MUT }` ⇒ (True, None) ⇒ 上游判 `unverifiable-method`。
    """
    for group in groups:
        depth = 0
        for k, a in enumerate(group):
            if a.kind == "punct":
                if a.text in ("(", "[", "{"):
                    depth += 1
                elif a.text in (")", "]", "}"):
                    depth -= 1
                continue
            if a.kind != "id" or a.text != "method" or depth != 1:
                continue
            prev = group[k - 1] if k > 0 else None
            if prev is None or prev.kind != "punct" or prev.text not in ("{", ","):
                continue
            if k + 2 < len(group) and group[k + 1].kind == "punct" and group[k + 1].text == ":":
                m = group[k + 2]
                if m.kind in ("str", "tpl"):
                    return True, m.text.strip().upper()
            return True, None
    return False, None


def load_backend_route_patterns() -> Set[Tuple[str, str]]:
    from delector.server import app  # noqa: PLC0415  # 延迟导入：由调用方先隔离 env

    pairs: Set[Tuple[str, str]] = set()
    _walk(app.routes, pairs)
    return pairs


def _walk(routes: Sequence[object], out: Set[Tuple[str, str]]) -> None:
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            _walk(list(getattr(original, "routes", [])), out)
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is not None and methods:
            for meth in methods:
                out.add((_norm_path(str(path)), str(meth).upper()))
            continue
        sub = getattr(route, "routes", None)
        if sub:
            _walk(list(sub), out)


_ROUTE_PARAM_RE = re.compile(r"\{[^}]*\}")


def _norm_path(p: str) -> str:
    """路径参数占位归一：后端 `{essay_id}` 与前端模板 `${x}` 都折成 `{}`。"""
    return _ROUTE_PARAM_RE.sub("{}", _TPL_INTERP_RE.sub("{}", p))


def check_call_parity(js_dir: Path, route_pairs: Set[Tuple[str, str]]) -> List[Violation]:
    out: List[Violation] = []
    for name, spec in LAYER_SPEC.items():
        if not (spec.layer.startswith("L2") or spec.layer == "L2 持久化访问层"):
            continue
        path = js_dir / name
        if not path.exists():
            continue
        raw, toks = read_js(path)
        rel_path = f"static/js/{name}"
        for c in scan_api_calls(toks):
            if c.path is None:
                out.append(
                    Violation(rel_path, c.lineno, "unverifiable-path", raw_line_of(raw, c.lineno))
                )
                continue
            if c.method_seen and c.method is None:
                out.append(
                    Violation(rel_path, c.lineno, "unverifiable-method", raw_line_of(raw, c.lineno))
                )
                continue
            method = c.method or "GET"
            norm = _norm_path(c.path)
            if (norm, method) in route_pairs:
                continue
            same_path = sorted({m for p, m in route_pairs if p == norm})
            rule = (
                f"method-mismatch({method}!={'/'.join(same_path)})" if same_path else "route-path-unregistered"
            )
            out.append(Violation(rel_path, c.lineno, rule, raw_line_of(raw, c.lineno)))
    return out


check_api_call_consistency = check_call_parity


# ══ 规则⑥：防假解耦 ══════════════════════════════════════════════════════════
def check_false_decoupling(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    moved: Dict[str, str] = {}
    for name in LAYER_SPEC:
        path = js_dir / name
        if not path.exists():
            continue
        _raw, toks = read_js(path)
        moved.update({sym: name for sym in local_declarations(toks, top_level_only=False)})
    host = js_dir / FALSE_DECOUPLING_HOST
    if not host.exists():
        return out
    raw, toks = read_js(host)
    declared = local_declarations(toks, top_level_only=True)
    for sym in sorted(declared & set(moved)):
        lineno = next((t.line for t in toks if t.kind == "id" and t.text == sym), 1)
        out.append(
            Violation(
                f"static/js/{FALSE_DECOUPLING_HOST}", lineno,
                f"false-decoupling({sym} 仍在 {moved[sym]} 里存在)",
                raw_line_of(raw, lineno),
            )
        )
    return out


# ══ 主流程 ═══════════════════════════════════════════════════════════════════
def default_js_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "js"


def collect_violations(js_dir: Path, route_pairs: Optional[Set[Tuple[str, str]]] = None) -> List[Violation]:
    out: List[Violation] = []
    out += check_layer_bans(js_dir)
    out += check_reverse_deps(js_dir)
    out += check_import_allowlist(js_dir)
    out += check_duplicate_declarations(js_dir)
    out += check_false_decoupling(js_dir)
    if route_pairs is not None:
        out += check_call_parity(js_dir, route_pairs)
    return _dedupe(out)


def _bootstrap_env() -> None:
    """导入 delector 之前把库/缓存路径钉进临时目录，避免污染仓库根的真实 DB。

    （与 `tools/check_frontend_api_contract.py::_bootstrap_env` 同口径 —— 那边 import
    `delector.server` 会经 create_app() 建库/播种，不隔离就会往仓库根写 DB。）
    """
    import os
    import tempfile

    tmp = tempfile.mkdtemp(prefix="cpe_frontend_layers_")
    os.environ["DELECTOR_DATA_DIR"] = tmp
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "delector.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmp, "progress.db")


def _reconfigure_stdout() -> None:
    """尽力把 stdout 切到 utf-8：import delector 时会有中文提示行，GBK 控制台会崩。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        # silent-ok: 显示层兜底：reconfigure 失败只意味着「保持原流」，编码问题真影响输出会响亮暴露
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(description="前端分层与模块图完整性机械闸")
    parser.add_argument("--js-dir", default=None, help="static/js 目录（默认按脚本位置推导）")
    parser.add_argument(
        "--skip-route-parity",
        action="store_true",
        help="跳过规则⑤（调用一致性）；仅用于无 python 依赖环境的降级，CI 禁用",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    js_dir = Path(args.js_dir) if args.js_dir else default_js_dir()

    route_pairs: Optional[Set[Tuple[str, str]]] = None
    if not args.skip_route_parity:
        _bootstrap_env()
        route_pairs = load_backend_route_patterns()

    violations = collect_violations(js_dir, route_pairs)
    if violations:
        print(f"[check_frontend_layers] FAIL: {len(violations)} 处违规", file=sys.stderr)
        for v in violations:
            print("  - " + v.render(), file=sys.stderr)
        return 1
    print(
        "[check_frontend_layers] PASS: 分层契约与模块图完整性全绿"
        "（L1/L2 禁令 · 反向依赖 · 越界 import · 重复声明 · 调用一致 · 防假解耦）。"
    )
    return 0


# ══ 入口 ════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sys.exit(main())


# ══ 复核驱动的重写（2026-10-19）═══════════════════════════════════════════════
# 初版是正则块表，一轮独立对抗式复核证明它可被以下方式绕过。均已修复并各有回归用例：
#   F1  `method: "POST"`（双引号）/ 反引号 ⇒ 旧版只认单引号且静默按 GET 处理 ⇒ 假绿。
#       现：三种引号都认；`method:` 出现却取不到字面量 ⇒ `unverifiable-method`（fail-closed）。
#   F2  旧版按「首行及其后 4 行」取窗口 ⇒ 把邻近调用的方法串到本调用上（假红）。
#       现：括号配平取实参。
#   F3  旧版禁令要求「函数调用形态」⇒ `const _net = fetch;`、`notify?.(x)`、
#       `g['setTimeout']` 全部逃逸。现：按**标识符 token** 判 + 扫字符串内容。
#   F5  旧版 import 用单行 `^` 锚正则 ⇒ 多行具名 import、`import{b}from'./x'`（无空白）、
#       `export {x} from './x'`、动态 `import('./x')`、同行两个 import、以及
#       `./vendor/core.js`（basename 冒充）全部逃逸。现：token 级判 + 比整条相对路径。
#   F6  旧版漏命名空间/默认绑定、漏 `const a = 1, b = 2` 的第二个名字、漏 `function*`。
#       现：三种绑定形态 + 逗号声明列表 + 生成器都覆盖。
#   F7  旧版用正则剥注释，遇到正则字面量里的引号就误开字符串状态 ⇒ 真实注释未被剥离，
#       且存在「正则字面量掩蔽真实代码」的假绿通道。现：真词法分析。
#   F4  块表补了 DOM 汇点属性、`WebSocket`、`eval`/`Function`、`location`/`history`/
#       `postMessage` 等。**块表仍是块表**，不可能穷尽 —— 见模块 docstring。
#   F8  规则⑤ 现在同时覆盖 `fetch(...)`（`wr-api.js` 的另一条真实调用面）。
#   F9  路径非字面量 ⇒ `unverifiable-path`；方法统一 `.upper()`；拼接按既有闸同口径折算。
#   F10 顶层可变状态按花括号净深度 0 判，不再依赖列 0。
#   F11 同一 (文件,行,规则) 去重；`missing-layer-module` 报真实行号。