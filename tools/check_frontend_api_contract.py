# -*- coding: utf-8 -*-
"""前端 ↔ 后端路由契约检查（ADR-0021「替代投资#3」，改口径版）。

为什么有这个脚本（**实测结论**，不是偏好）
------------------------------------------
ADR-0021 §6.1 第 3 项原计划是「给 static/（33k 行前端）加类型检查」，理由是
「JS↔Python 才是真正的跨边界误用来源」。但实测（typescript@5.6.3 对全部
23 个 static/js/*.js 跑 `tsc --noEmit --allowJs --checkJs`）共 219 条存量错误，
其中 **199 条**是 TS2339（Property 'X' does not exist on HTMLElement/Window）——
那是**噪音**：只是缺 DOM/全局声明，不是 bug。把全量 checkJs 接进 CI 会立刻变成
「永远红的噪音源」（本仓刚有过「门禁恒真/恒红」的教训）。

改口径：**抓真正的跨边界缺陷**（前端调了后端没注册的端点），而不是 DOM 注解缺失。
本脚本就是那把尺子 —— 用**真实路由表**（`delector.server.app.routes`）校验前端
`static/js` 里真实存在的 HTTP 调用；调用了未注册端点 ⇒ 非零退出。

判定与排除（**显式写清，带理由**）
----------------------------------
- 权威来源：`from delector.server import app` 后**递归**遍历 `app.routes` 取
  `path`/`methods`。新版 FastAPI 的 `include_router` 会在 `app.routes` 留一层
  `_IncludedRouter` 中间对象（实测 fastapi 0.141.1），故须下钻其 `original_router.routes`；
  **不**用正则去猜 `delector/routes/*.py`（那正是本脚要取代的脆弱做法）。
- 被检查面：`static/js/**/*.js` 里真实存在的 HTTP 调用。实测写法（grep 确认，非假设）：
  * 自建包装 `api(...)`（core.js 定义，全仓主用）；
  * 原生 `fetch(...)`；
  * 注入式包装 `doFetch(...)`（update.js：`doFetch = options.fetchImpl || globalThis.fetch`）；
  * 导航式 `window.location.href = ...`（真发 HTTP GET）。
  `EventSource` / `XMLHttpRequest` 实测 **0 处**，仍保留识别以防回潮。
- 归一化：模板字面量插值 `` `/api/x/${id}` `` ⇒ `/api/x/{}`；`+` 拼接中的变量段同样
  折叠为 `{}`（如 `"/api/articles/" + id` ⇒ `/api/articles/{}`）。匹配前剥离查询串与 hash。
- 排除项（命中即跳过，**不**判失败）：
  * **外部绝对 URL**（`http://`/`https://`/`//`/`data:`/`mailto:` 等带 scheme）：不是本机路由；
  * **静态资源**（`/static/…` 或以 `.js/.css/.png` 等资源扩展名结尾）：不是 API；
  * **非 `/api/` 的根路径**（如 `/sw.js`）：不是 API 路由；
  * **无法静态求值的动态首参**（纯变量、含顶层三元表达式）：记 INFO，**不**判失败 ——
    强行判定会产出假阳性（如 encounter.js 的 `endpoint` 在 `http://<host>/…` 与
    `/api/wb/state` 间三元切换）。
- 反向信息：已注册但前端从未调用的 `/api/…` 路由列为 **INFO**（**不**导致失败 ——
  它们可能供 Android/其它客户端使用）。

控制台纪律：本脚本只用 ASCII 标记输出，避免中文 Windows 的 GBK 控制台在 print 时抛
UnicodeEncodeError（import delector 时会有中文提示行，故 main() 先把 stdout 切到 utf-8）。
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(REPO_ROOT, "static")
STATIC_JS_DIR = os.path.join(STATIC_DIR, "js")

# 允许从任意 CWD 直接 `python tools/check_frontend_api_contract.py` 运行：脚本方式下
# sys.path[0] 是 tools/ 而非仓库根，`import delector` 会 ModuleNotFoundError。
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# 实测存在的请求函数（首参即 URL）。EventSource 实测 0 处，保留以防回潮。
_CALL_FUNCS: tuple[str, ...] = ("api", "fetch", "doFetch", "EventSource")

# 静态资源扩展名（命中即排除，**不是** API）。
STATIC_EXTENSIONS: tuple[str, ...] = (
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".html",
    ".htm",
    ".wasm",
)

# 站点类型（供报表与单测断言）。CHECKABLE 才进入路由匹配。
KIND_CHECKABLE = "checkable"
KIND_EXTERNAL = "external"
KIND_STATIC = "static"
KIND_NON_API = "non_api"
KIND_DYNAMIC = "dynamic"

_CALL_RE = re.compile(r"(?<![\w$.])(?P<name>" + "|".join(_CALL_FUNCS) + r")\s*\(")
# 导航式 HTTP 调用：window.location.href = <url>
_HREF_RE = re.compile(r"(?:window\s*\.\s*)?location\s*\.\s*href\s*=\s*")
# XMLHttpRequest：xhr.open(<method>, <url>) —— 取第 2 个实参为 URL。
# 不加 `(?<![\w$])` 前置断言：`.` 前必然是宿主对象标识符（如 `xhr`），断言会把它挡掉。
_OPEN_RE = re.compile(r"\.open\s*\(")
# 形如 /api/…，或 {name}/{name:converter} 路径参数占位。
_ROUTE_PARAM_RE = re.compile(r"\{[^}]*\}")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


@dataclass(frozen=True)
class HttpCall:
    """一条前端 HTTP 调用站点。`url` 为归一化后的路径（含 `{}` 占位）；`None` 表动态。"""

    file: str
    lineno: int
    callee: str
    raw_expr: str
    kind: str
    url: Optional[str]


# ── 表达式读取（尊重字符串/模板/括号深度）────────────────────────────────────
def _skip_quoted(text: str, i: int) -> int:
    """i 指向起始引号，返回其配对闭合引号之后的下标（未闭合则到末尾）。"""
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return i


def _read_expression(text: str, start: int, stops: frozenset[str]) -> str:
    """从 start 读一段表达式，遇到顶层 stop 字符或闭合括号即停。"""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            i = _skip_quoted(text, i)
            continue
        if c in "([{":
            depth += 1
            i += 1
            continue
        if c in ")]}" and depth == 0:
            break
        if c in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and c in stops:
            break
        i += 1
    return text[start:i]


def _skip_to_next_arg(text: str, start: int) -> int:
    """跳过一段表达式（含其后的逗号），返回下一个实参的起点；无逗号则返回 len。"""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            i = _skip_quoted(text, i)
            continue
        if c in "([{":
            depth += 1
            i += 1
            continue
        if c in ")]}" and depth == 0:
            return n
        if c in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and c == ",":
            return i + 1
        i += 1
    return n


# ── URL 表达式归一化 ─────────────────────────────────────────────────────────
def _has_top_level(expr: str, target: str) -> bool:
    """expr 中是否存在**顶层**（非字符串、非括号内）的 target 字符。"""
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c in "\"'`":
            i = _skip_quoted(expr, i)
            continue
        if c in "([{":
            depth += 1
            i += 1
            continue
        if c in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and c == target:
            return True
        i += 1
    return False


def _split_top_level(expr: str, sep: str) -> list[str]:
    """按顶层 sep 切分 expr（跳过字符串与括号内的 sep）。"""
    parts: list[str] = []
    depth = 0
    i = 0
    start = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c in "\"'`":
            i = _skip_quoted(expr, i)
            continue
        if c in "([{":
            depth += 1
            i += 1
            continue
        if c in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and c == sep:
            parts.append(expr[start:i])
            start = i + 1
        i += 1
    parts.append(expr[start:])
    return parts


def _unescape_string(raw: str) -> str:
    """反义普通字符串里 URL 相关的转义（`\\/` ⇒ `/` 等）。"""
    return raw.replace("\\/", "/").replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def _find_template_expr_end(inner: str, brace_open: int) -> int:
    """brace_open 指向插值的 `{`，返回其配对 `}` 的下标（未闭合则到末尾）。

    只数花括号深度（URL 插值里不出现字符串字面量里的花括号），够用且无嵌套。
    """
    depth = 1
    i = brace_open + 1
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "{":
            depth += 1
        if ch == "}":
            depth -= 1
        if depth == 0 and ch == "}":
            return i
        i += 1
    return n - 1


def _template_pieces(inner: str) -> list[Optional[str]]:
    """把模板字面量内容切成 [文本段 | None(插值)] 序列。"""
    pieces: list[Optional[str]] = []
    buf: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        if not (inner[i] == "$" and i + 1 < n and inner[i + 1] == "{"):
            buf.append(inner[i])
            i += 1
            continue
        if buf:
            pieces.append("".join(buf))
            buf = []
        end = _find_template_expr_end(inner, i + 1)
        pieces.append(None)
        i = end + 1
    if buf:
        pieces.append("".join(buf))
    return pieces


def _expr_pieces(expr: str) -> Optional[list[Optional[str]]]:
    """把表达式拆成 [文本段 | None(动态)] 序列；顶层三元无法静态求值 ⇒ None。"""
    if _has_top_level(expr, "?"):
        return None
    pieces: list[Optional[str]] = []
    for part in _split_top_level(expr, "+"):
        p = part.strip()
        if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
            pieces.append(_unescape_string(p[1:-1]))
        elif len(p) >= 2 and p[0] == "`" and p[-1] == "`":
            pieces.extend(_template_pieces(p[1:-1]))
        else:
            pieces.append(None)
    return pieces


def _collapse(pieces: Sequence[Optional[str]]) -> Optional[str]:
    """把 piece 序列折叠成路径模板。

    动态段（None）只在**路径段位置**（前文为空或以 `/` 结尾）折叠为 `{}`；若它**紧贴**
    在路径字面量之后（前一个字符不是 `/`），则按查询串/后缀尾部处理 —— 从该处**截断**。
    理由（实测）：listen-lab.js 的 `` `/api/listen/materials${levelParam}` `` 里
    `levelParam` 是 `""` 或 `"?level=…"` 的**查询串构造器**，粘在路径后；若强折叠为
    `{}` 会得到 `/api/listen/materials{}` 而误判为未知端点（假阳性）。
    """
    out = ""
    saw_literal = False
    for piece in pieces:
        if piece is None and (out == "" or out.endswith("/")):
            out += "{}"
            continue
        if piece is None:
            break
        saw_literal = True
        out += piece
    if not saw_literal:
        return None
    return out


def normalize_url_expr(expr: str) -> Optional[str]:
    """把首参表达式归一化为路径模板；无法静态求值（纯动态/三元）时返回 None。

    - 单字面量：`` `/api/x/${id}` `` ⇒ `/api/x/{}`；
    - `+` 拼接：`"/api/articles/" + id` ⇒ `/api/articles/{}`；
    - 紧贴的插值/拼接（非路径段位置）：按查询/后缀尾部截断
      （`` `/api/listen/materials${levelParam}` `` ⇒ `/api/listen/materials`）；
    - 顶层三元（`a ? b : c`）⇒ None（左右分支可能指向不同主机，硬判会假阳性）；
    - 纯变量/成员/调用（无任何字面量）⇒ None（无从静态求值）。
    """
    expr = expr.strip()
    if not expr:
        return None
    pieces = _expr_pieces(expr)
    if pieces is None:
        return None
    return _collapse(pieces)


def classify_url(url: str) -> tuple[str, Optional[str]]:
    """把归一化后的 URL 分类为 (kind, checkable_path)。

    checkable_path 仅当 kind == KIND_CHECKABLE 时非 None，且已剥离查询串/hash。
    """
    stripped = url.split("#", 1)[0].split("?", 1)[0].strip()
    if not stripped:
        return (KIND_NON_API, None)
    if stripped.startswith("//") or _SCHEME_RE.match(stripped):
        return (KIND_EXTERNAL, None)
    if stripped == "/static" or stripped.startswith("/static/"):
        return (KIND_STATIC, None)
    low = stripped.lower()
    if any(low.endswith(ext) for ext in STATIC_EXTENSIONS):
        return (KIND_STATIC, None)
    if stripped == "/api" or stripped.startswith("/api/"):
        return (KIND_CHECKABLE, stripped)
    return (KIND_NON_API, None)


# ── 站点扫描 ─────────────────────────────────────────────────────────────────
def _iter_sites(source: str) -> Iterator[tuple[int, str, str]]:
    """产出 (lineno, callee, url_expr) —— 空实参的站点直接丢弃（降噪）。"""
    found: list[tuple[int, str, str]] = []
    for m in _CALL_RE.finditer(source):
        expr = _read_expression(source, m.end(), frozenset({","})).strip()
        if expr:
            found.append((m.start(), m.group("name"), expr))
    for m in _HREF_RE.finditer(source):
        expr = _read_expression(source, m.end(), frozenset({";"})).strip()
        if expr:
            found.append((m.start(), "location.href", expr))
    for m in _OPEN_RE.finditer(source):
        # xhr.open(method, url)：跳过第 1 个实参，取第 2 个为 URL。
        second = _skip_to_next_arg(source, m.end())
        expr = _read_expression(source, second, frozenset({","})).strip()
        if expr:
            found.append((m.start(), ".open", expr))
    for pos, callee, expr in sorted(found, key=lambda t: t[0]):
        lineno = source.count("\n", 0, pos) + 1
        yield (lineno, callee, expr)


def scan_source(source: str, filename: str) -> list[HttpCall]:
    """扫描单个 JS 源文本，返回其 HTTP 调用站点清单。"""
    calls: list[HttpCall] = []
    for lineno, callee, expr in _iter_sites(source):
        url = normalize_url_expr(expr)
        if url is None:
            calls.append(HttpCall(filename, lineno, callee, expr, KIND_DYNAMIC, None))
            continue
        kind, path = classify_url(url)
        calls.append(HttpCall(filename, lineno, callee, expr, kind, path))
    return calls


def _read_text(path: str) -> str:
    """读 UTF-8 文本（独立函数：把 `with` 从扫描循环里挪出，保持循环扁平）。"""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _iter_js_files(static_js_dir: str) -> list[str]:
    """递归收集 .js 文件绝对路径（排序，保证输出确定）。"""
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(static_js_dir):
        found.extend(os.path.join(dirpath, name) for name in filenames if name.endswith(".js"))
    return sorted(found)


def scan_frontend(static_js_dir: str = STATIC_JS_DIR) -> list[HttpCall]:
    """递归扫描 static/js 下全部 .js（按路径排序，保证输出确定性）。"""
    calls: list[HttpCall] = []
    for full in _iter_js_files(static_js_dir):
        rel = os.path.relpath(full, REPO_ROOT).replace(os.sep, "/")
        calls.extend(scan_source(_read_text(full), rel))
    calls.sort(key=lambda c: (c.file, c.lineno, c.callee))
    return calls


# ── 真实路由表 ───────────────────────────────────────────────────────────────
def _walk_routes(routes: Sequence[object], out: list[str]) -> None:
    """递归收集 app.routes 里的真实路径。

    新版 FastAPI 的 include_router 会留 `_IncludedRouter` 中间对象（无 .path），
    需下钻其 `original_router.routes`；普通 Mount/Route 直接取 .path。
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            _walk_routes(list(getattr(original, "routes", [])), out)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            out.append(str(path))
            continue
        subroutes = getattr(route, "routes", None)
        if subroutes:
            _walk_routes(list(subroutes), out)


def load_route_patterns() -> list[str]:
    """取真实路由表并归一化路径参数占位（`{id}` / `{id:int}` ⇒ `{}`）。

    import 期会经 create_app() 建库/播种 —— 由调用方在导入前把 DATABASE_PATH /
    PROGRESS_DB_PATH / DELECTOR_DATA_DIR 指到临时目录（main() 已做，避免污染仓库根）。
    """
    from delector.server import app  # noqa: PLC0415  # 延迟导入：先隔离 env 再导入

    raw: list[str] = []
    _walk_routes(list(app.routes), raw)
    patterns = [normalize_route_pattern(p) for p in raw]
    # 去重并排序，保证 INFO/PASS 输出确定
    return sorted(set(patterns))


def normalize_route_pattern(path: str) -> str:
    """把路由路径参数占位归一化为 `{}`（`/api/x/{id:int}` ⇒ `/api/x/{}`）。"""
    return _ROUTE_PARAM_RE.sub("{}", path)


def paths_match(call_path: str, route_pattern: str) -> bool:
    """两段式匹配：段数相同，且每段相等或任一方为 `{}` 通配。"""
    a = call_path.split("/")
    b = route_pattern.split("/")
    if len(a) != len(b):
        return False
    return all(x == y or x == "{}" or y == "{}" for x, y in zip(a, b))


def nearest_routes(call_path: str, patterns: Sequence[str], limit: int = 3) -> list[str]:
    """给出与 call_path 最相近的已注册路由（供失败信息定位）。"""
    return difflib.get_close_matches(call_path, list(patterns), n=limit, cutoff=0.0)


def _checkable_paths(calls: Sequence[HttpCall]) -> set[str]:
    """取出所有可判定调用的归一化路径（供反向 INFO 用）。"""
    return {c.url for c in calls if c.kind == KIND_CHECKABLE and c.url is not None}


def find_unknown(
    calls: Sequence[HttpCall], patterns: Sequence[str]
) -> list[tuple[HttpCall, list[str]]]:
    """返回「调用了未注册端点」的站点清单（每项附最近似的已知路由）。

    纯函数、可单测：唯一会判失败的判据就是这里 —— 可判定路径不匹配任何已注册路由。
    """
    known = list(patterns)
    unknown: list[tuple[HttpCall, list[str]]] = []
    for call in calls:
        if call.kind != KIND_CHECKABLE or call.url is None:
            continue
        if not any(paths_match(call.url, pat) for pat in known):
            unknown.append((call, nearest_routes(call.url, known)))
    return unknown


# ── 主流程 ───────────────────────────────────────────────────────────────────
def _bootstrap_env() -> None:
    """导入 delector 之前把库/缓存路径钉进临时目录，避免污染仓库根的真实 DB。"""
    import tempfile  # noqa: PLC0415

    tmp = tempfile.mkdtemp(prefix="cpe_frontend_contract_")
    os.environ["DELECTOR_DATA_DIR"] = tmp
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "delector.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmp, "progress.db")


def _reconfigure_stdout() -> None:
    """尽力把 stdout 切到 utf-8：import delector 时会有中文提示行，GBK 控制台会崩。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _reconfigure_stdout()
    _bootstrap_env()
    patterns = load_route_patterns()
    calls = scan_frontend()

    checkable = [c for c in calls if c.kind == KIND_CHECKABLE]
    unknown = find_unknown(calls, patterns)
    called_paths = _checkable_paths(calls)
    dynamic_calls = [c for c in calls if c.kind == KIND_DYNAMIC]
    _print_report(calls, checkable, dynamic_calls, unknown, patterns, called_paths)

    return 1 if unknown else 0


def _print_report(
    calls: Sequence[HttpCall],
    checkable: Sequence[HttpCall],
    dynamic_calls: Sequence[HttpCall],
    unknown: Sequence[tuple[HttpCall, Sequence[str]]],
    patterns: Sequence[str],
    called_paths: set[str],
) -> None:
    lines: list[str] = []
    lines.append("[frontend-api-contract] scanned static/js: %d HTTP call sites" % len(calls))
    lines.append(
        "[frontend-api-contract]   checkable /api/ calls: %d | dynamic (skipped): %d"
        % (len(checkable), len(dynamic_calls))
    )

    if dynamic_calls:
        lines.append("[frontend-api-contract] INFO dynamic call sites (not statically resolvable):")
        for call in dynamic_calls:
            lines.append("  - %s:%d %s(%s)" % (call.file, call.lineno, call.callee, call.raw_expr))

    uncalled = [
        pat
        for pat in patterns
        if pat.startswith("/api/") and not any(paths_match(path, pat) for path in called_paths)
    ]
    lines.append(
        "[frontend-api-contract] INFO registered /api/ routes not matched by any statically-resolved "
        "frontend call: %d (may be called dynamically or serve Android/other clients; NOT a failure)"
        % len(uncalled)
    )
    for pat in uncalled:
        lines.append("  - %s" % pat)

    if unknown:
        lines.append("")
        lines.append("[frontend-api-contract] FAIL: frontend calls unknown endpoints:")
        for call, nearest in unknown:
            lines.append("  - %s:%d %s(%s) -> %s" % (call.file, call.lineno, call.callee, call.raw_expr, call.url))
            lines.append("      nearest registered routes: %s" % (", ".join(nearest) or "(none)"))
        lines.append("")
        lines.append("FAIL")
    else:
        lines.append("[frontend-api-contract] all checkable calls match registered routes.")
        lines.append("PASS")

    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
