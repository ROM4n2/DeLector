"""C7 · 探针读取公共层（计划 `2026-10-18-c7-workbench-html-split.md` Task 1）。

为什么要有这一层：`static/german/workbench.html`（4730 行单文件 PWA）即将拆分为多
模块，而 140 个耦合探针里有 **91 个 A 类**（相对位置序 / 标记切片）与 **4 个 B 类**
（行号钉）把当前单文件的内部结构钉成了契约。逐个硬改既容易退化成 C 类存在性断言
（`assert "x" in src` —— 本仓记过在案的死测形态，红线 11），又无法在拆分后跨文件
锚定。故先立一层公共读法：**按段读（segment）/ 按声明读（decl_body）/ 按行读
（line_of、same_line）**，后续迁移只换「文件清单」，不换断言语义。

三条硬纪律：

  1. **Fail-Loud**：找不到标记一律抛 `AssertionError`，并把所查标记原文打进消息。
     任何情况下都不返回空串 —— 空串会让下游的 `in` 断言静默通过（假绿）。
  2. **判别力只许升不许降**：`depth_at` / `occurs_before` 用来把「与某行同一物理行」
     这类一格式化就红的钉，升级为「在声明体内 + 位于顶层 + 早于 IO」的契约断言。
  3. **不改写行尾**：`read_source` 走 `Path.read_text`（universal newlines，内存里
     CRLF → LF）。行号与切片不受影响；**要逐字节比对（D 类）请自行 `read_bytes()`**，
     本层不做字节等价断言。

已知限制：花括号配平不识别**正则字面量**里的未转义花括号（JS 的 `/` 歧义在没有
解析器的前提下无法可靠消除）；本仓探针目标声明体里没有这种形态，遇到时再补。
"""

from collections.abc import Iterator
from pathlib import Path

# tests/ 的上一级 = 仓库根（工作区副本 / worktree 都成立，不依赖 CWD）
REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve(rel_path: str) -> Path:
    """解析源路径：绝对路径原样返回；相对路径先按 CWD 找，再回落到仓库根。"""
    p = Path(rel_path)
    if p.is_absolute():
        return p
    tried = [Path.cwd() / p, REPO_ROOT / p]
    for cand in tried:
        if cand.exists():
            return cand
    raise FileNotFoundError(
        f"探针源文件缺失：{rel_path!r}（已尝试：{'、'.join(str(t) for t in tried)}）"
    )


def read_source(*rel_paths: str) -> str:
    """按仓库相对路径（或绝对路径）读源文本；多路径按**给定顺序**用换行拼接。

    拆分后跨文件锚定就靠这个顺序契约：**实参顺序 = 拼接顺序**，之后 segment /
    decl_body / line_of 全都作用在这份拼出来的「虚拟单文件」上 —— 断言写法不用动，
    只需把文件清单从 1 个换成 N 个。各文件自带的尾随换行被保留，故相接处会出现一个
    空行（这正是我们想要的：声明不会被粘到上一个文件的最后一行）。
    """
    return "\n".join(_resolve(rel).read_text(encoding="utf-8") for rel in rel_paths)


def segment(text: str, start_marker: str, end_marker: str) -> str:
    """返回 start_marker 之后、end_marker 之前的片段（**不含**两端标记）。

    缺任一标记即抛 `AssertionError` 并把所查标记原文打进消息；结束标记出现在起始
    标记之前也一样抛 —— 绝不返回空串（空串 = 下游存在性断言的静默假绿）。
    """
    start = text.find(start_marker)
    if start < 0:
        raise AssertionError(f"segment: 找不到起始标记 {start_marker!r}")
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise AssertionError(
            f"segment: 找到起始标记 {start_marker!r}，但其后找不到结束标记 {end_marker!r}"
        )
    return text[start + len(start_marker) : end]


def decl_body(text: str, decl: str) -> str:
    """按大括号配平取出 decl 的声明体 —— **不含** decl 自身，也**不含**外层花括号。

    例：`decl_body(src, "function saveWords()")` ⇒ 返回 `{` 与配对 `}` 之间的全部文本，
    因此「函数体顶层语句」= `depth_at(body, pos) == 0`。替代 `_top_fn_segment` /
    `_slice_balanced` 这类「切到下一个声明为止」的写法（后者在声明顺序漂移时会切歪）。

    配平跳过行注释 / 块注释 / 单双引号字符串 / 模板字面量；模板插值 `${…}` 的花括号
    计入配平。decl 取**首次**出现；decl 缺失、其后没有 `{`、或花括号未配平 ⇒ 抛。
    """
    at = text.find(decl)
    if at < 0:
        raise AssertionError(f"decl_body: 找不到声明 {decl!r}")
    # decl 允许自带花括号（`function f() {`）：从「去掉尾部 { 与空格」处起找，
    # 否则会跳过自己的花括号去匹配下一个 —— 那是静默错位，最难查的一种。
    open_at = text.find("{", at + len(decl.rstrip("{ ")))
    if open_at < 0:
        raise AssertionError(f"decl_body: 声明 {decl!r} 之后找不到 '{{'")
    return text[open_at + 1 : _matching_brace(text, open_at, decl)]


def line_of(text: str, needle: str, start: int = 0) -> int:
    """返回 needle 首次出现处的**行下标（0 基）**；`start` 为起查行下标。

    B 类「`splitlines()` 下标」钉的结构化替代：返回值仍是行下标（所以相对位置序的
    比较照旧），但**缺失时抛**并在消息里打印 needle —— 旧写法找不到就返回 -1 / None，
    会让 `assert i > 0` 之类的比较在标记被改名后静默假绿。
    """
    lines = text.splitlines()
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    raise AssertionError(f"line_of: 自第 {start} 行起找不到含 {needle!r} 的行")


def same_line(text: str, a: str, b: str) -> bool:
    """a 首次出现所在的那一行是否也含 b。a 缺失 ⇒ 抛（不静默返回 False）。

    静默 False 的害处：`assert not same_line(...)` 这种反向断言会在 a 被删掉后照样绿。
    """
    return b in text.splitlines()[line_of(text, a)]


def depth_at(text: str, pos: int) -> int:
    """text[pos] 处的花括号**净深度**。text 应是**单个声明体**（`decl_body` 的返回值）。

    0 = 声明体的顶层语句；1 = 嵌在一层块 / 子函数 / 回调里。它把「必须无条件执行」
    写成结构断言 —— 比「与声明同一物理行」强得多，且不依赖换行与缩进。

    边界：**无花括号的表达式体回调**（如 `setTimeout(() => wbsync.push(), 0)`）不产生
    任何花括号 ⇒ 深度仍是 0 ⇒ **本函数抓不到**这种「被塞进回调」。引用它的断言消息
    MUST 只承诺「嵌进块 / 带花括号的子函数或回调」，不得泛称「嵌进块/回调」。
    """
    depth = 0
    for idx, _ch, before, after in _iter_braces(text, 0):
        if idx >= pos:
            return before
        depth = after
    return depth


def occurs_before(text: str, needle: str, marker: str) -> bool:
    """needle 的首次出现是否**早于** marker 的首次出现；marker 不存在 ⇒ True。

    needle 缺失 ⇒ 抛（禁止静默 False ⇒ 假绿）。这是 A 类「`index(a) < index(b)`」
    相对位置序断言的结构化写法。
    """
    at = text.find(needle)
    if at < 0:
        raise AssertionError(f"occurs_before: 找不到 {needle!r}")
    marker_at = text.find(marker)
    return marker_at < 0 or at < marker_at


# ── 花括号扫描器（decl_body / depth_at 共用一台状态机，避免两份实现漂移）──────


def _iter_braces(text: str, start: int) -> Iterator[tuple[int, str, int, int]]:
    """产出 `(下标, 字符, 扫描前深度, 扫描后深度)`，字符只取 `{` 与 `}`。

    状态机跳过行注释 / 块注释 / 单双引号字符串 / 模板字面量；模板插值 `${…}` 的花括号
    计入配平（其 `{` 使深度 +1，配对的 `}` 退回模板模式）。
    """
    depth = 0
    modes = ["code"]  # 栈顶 = 当前解析模式
    interp_depths: list[int] = []  # 各层模板插值 `${` 处的深度
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        mode = modes[-1]
        if mode == "code":
            if ch == "/" and nxt == "/":
                modes.append("line")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                modes.append("block")
                i += 2
                continue
            if ch in ("'", '"'):
                modes.append("str" + ch)
                i += 1
                continue
            if ch == "`":
                modes.append("tpl")
                i += 1
                continue
            if ch == "{":
                yield i, ch, depth, depth + 1
                depth += 1
            elif ch == "}":
                yield i, ch, depth, depth - 1
                depth -= 1
                if interp_depths and depth == interp_depths[-1]:
                    interp_depths.pop()
                    modes.pop()  # 插值结束，退回模板模式
            i += 1
            continue
        if mode == "line":
            if ch == "\n":
                modes.pop()
            i += 1
            continue
        if mode == "block":
            if ch == "*" and nxt == "/":
                modes.pop()
                i += 2
                continue
            i += 1
            continue
        if mode == "tpl":
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                modes.pop()
                i += 1
                continue
            if ch == "$" and nxt == "{":
                interp_depths.append(depth)
                depth += 1
                modes.append("code")
                i += 2
                continue
            i += 1
            continue
        # modes[-1] == "str'" / 'str"'：只认反斜杠转义与同种引号
        if ch == "\\":
            i += 2
            continue
        if ch == mode[-1]:
            modes.pop()
        i += 1


def _matching_brace(text: str, open_at: int, label: str) -> int:
    """从 open_at（必须是 `{`）配平到右花括号，返回其下标；扫到尾仍未配平 ⇒ 抛。"""
    if text[open_at] != "{":
        raise AssertionError(f"decl_body 内部错误：下标 {open_at} 处不是 '{{'（声明 {label!r}）")
    for idx, ch, _before, after in _iter_braces(text, open_at):
        if ch == "}" and after == 0:
            return idx
    raise AssertionError(
        f"decl_body: 声明 {label!r} 的花括号未配平（自下标 {open_at} 起扫到文本尾）"
    )
