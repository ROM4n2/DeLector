# -*- coding: utf-8 -*-
"""前端分层与模块图完整性机械闸 (Frontend Layer Invariants Gate)。

依据 `docs/plans/2026-10-19-writer-js-modularization.md` Task 4（其规则来自 Task 3
变异自证实测出的 3 条 UNCAUGHT + 1 条 CI 外判别力）。

分层声明（`LAYER_SPEC`）
----------------------
  L1 `static/js/wr-format.js`  纯格式化 / 领域文案层
      MUST NOT: DOM 全家 / 网络 / 用户提示 / 计时器 / 顶层 `let`
      只允许 import `./core.js`
  L2 `static/js/wr-api.js`     持久化访问层
      MUST NOT: DOM 全家 / 用户提示 / 计时器
      只允许 import `./core.js`（网络是它的本职）

规则清单
--------
  ① L1 硬禁令                 —— 变异实测 M4（纯层注入 `fetch`）现存门禁 UNCAUGHT
  ② L2 硬禁令                 —— 变异实测 M1（L2 注入 `document`）现存门禁 UNCAUGHT
  ③ 反向依赖：L1/L2 MUST NOT import `writer.js`（分层倒置 + 与 main.js 成环）
  ④ 重复声明：模块**导入的名字** MUST NOT 同时被本模块**本地声明**
                               —— ES 链接期 SyntaxError，整张模块图一起挂（v4.7.0 同类事故）。
                                  现状唯一捕获者是 `node --check`，而**本仓 CI 不跑它**。
  ⑤ 方法一致性：`wr-api.js` 每个 `api()` 的 (路径, 方法) MUST 命中后端注册表
                               —— 变异实测 M2（`DELETE`→`POST`）现存门禁 UNCAUGHT。
                                  **路径**维度已由 `tools/check_frontend_api_contract.py` 覆盖
                                  （它用真实路由表），本闸**刻意不重复**，只补**方法**维度。
  ⑥ 防假解耦：`writer.js` MUST NOT 重新定义已迁出到 L1/L2 的符号名
                               —— 判别力等价于 `node --check` 的重复定义（见 ④ 的说明）。

判定纪律
--------
- **注释先剥离**：L1/L2 的模块头注释**逐字写着** `document` / `fetch` / `notify` 等被禁词
  （那是在声明契约）。不剥注释 ⇒ 闸对自己的文档开火（假红）。故扫描前先剥 `//` 与 `/* */`。
- **字符串不剥离（已知口径）**：代价是把「字符串里出现的被禁词」判为违规——这是**保守**方向
  （假红可改，假绿是漏洞）。当前两模块的字符串里没有被禁词（实测闸绿）；若将来出现，先在
  这里登记口径再放行，MUST NOT 靠删断言绕过。
- **行级归因**：违规一律报 `文件:行号:规则:原始行`，不报「共 N 处」——否则下一个人不知道该改哪一行。
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

# ── 被禁词表（正则，按「规则名 -> 模式串」组织）────────────────────────────────
BAN_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "dom": (
        r"\bdocument\b",
        r"\bwindow\b",
        r"\bnavigator\b",
        r"\blocalStorage\b",
        r"\bsessionStorage\b",
        r"\bgetElementById\b",
        r"\bquerySelector(?:All)?\b",
        r"\binnerHTML\b",
        r"\bouterHTML\b",
        r"\baddEventListener\b",
        r"\bclassList\b",
        r"\bcreateElement\b",
    ),
    "network": (
        r"\bfetch\s*\(",
        r"(?<![\w.$])api\s*\(",
        r"\bXMLHttpRequest\b",
        r"\bEventSource\b",
    ),
    "toast": (
        r"\bnotify\s*\(",
        r"\balert\s*\(",
        r"\bconfirm\s*\(",
    ),
    "timer": (
        r"\bsetTimeout\s*\(",
        r"\bsetInterval\s*\(",
        r"\brequestAnimationFrame\s*\(",
    ),
}

# 顶层可变模块状态（只禁 `let`/`var`；`const` 允许——它是不可重绑定的纯数据）
MUTABLE_STATE_PATTERN = r"^(?:export\s+)?(?:let|var)\s"

# 后端路由：@router.<method>("<path>")
BACKEND_ROUTE_RE = re.compile(r'@router\.(get|post|put|delete|patch)\("(/api/[^"]+)"\)')
# 前端 src 里的 import：import [* as X | {…}] from '<mod>'
JS_IMPORT_RE = re.compile(r"^import\s+(?:\*\s+as\s+\w+|\{[^}]*\}|[\w$]+)\s+from\s+['\"]([^'\"]+)['\"]", re.M)
JS_IMPORTED_NAMES_RE = re.compile(r"^import\s+\{([^}]*)\}\s+from\s+['\"]([^'\"]+)['\"]", re.M | re.S)
JS_DECL_BODY = r"(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+"
JS_DECL_HEAD = r"^(?:export\s+)?" + JS_DECL_BODY
JS_DECL_RE = re.compile(JS_DECL_HEAD + r"([A-Za-z_$][\w$]*)", re.M)
JS_EXPORTED_RE = re.compile(r"^export\s+" + JS_DECL_BODY + r"([A-Za-z_$][\w$]*)", re.M)


class LayerSpec(NamedTuple):
    layer: str
    forbid: Tuple[str, ...]
    allowed_imports: Tuple[str, ...]


# ── 分层声明（分层的唯一事实来源）────────────────────────────────────────────
LAYER_SPEC: Dict[str, LayerSpec] = {
    "wr-format.js": LayerSpec(
        layer="L1 纯格式化层",
        forbid=("dom", "network", "toast", "timer"),
        allowed_imports=("core.js",),
    ),
    "wr-api.js": LayerSpec(
        layer="L2 持久化访问层",
        forbid=("dom", "toast", "timer"),
        allowed_imports=("core.js",),
    ),
}

# L1 额外禁令：顶层可变状态
MUTABLE_STATE_MODULES: Tuple[str, ...] = ("wr-format.js",)

# 分层倒置：低层 MUST NOT import 这些视图/编排模块
VIEW_MODULES: Tuple[str, ...] = ("writer.js",)

# 防假解耦的宿主（它 MUST NOT 再定义 L1/L2 已迁出的符号）
FALSE_DECOUPLING_HOST = "writer.js"


class Violation(NamedTuple):
    rel_path: str
    lineno: int
    rule: str
    raw: str

    def render(self) -> str:
        return f"{self.rel_path}:{self.lineno}:{self.rule}:{self.raw.strip()}"


# ── 源码读取与注释剥离 ───────────────────────────────────────────────────────
def strip_comments(text: str) -> str:
    """剥 `//` 与 `/* */` 注释，**保留换行与列位**（行号、列位都对得上原始文件）。

    不剥字符串字面量（口径见模块 docstring「字符串不剥离」一节）。
    """
    out: List[str] = []
    i = 0
    n = len(text)
    state = "code"
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if c in "\"'`":
                # 跳过整段字符串/模板字面量内容（只用于定位，不改变外层的注释判定）
                quote = c
                out.append(c)
                i += 1
                while i < n:
                    ch = text[i]
                    if ch == "\\" and i + 1 < n:
                        out.append("  ")
                        i += 2
                        continue
                    if ch == quote:
                        out.append(ch)
                        i += 1
                        break
                    out.append("\n" if ch == "\n" else ch)
                    i += 1
                continue
            out.append(c)
            i += 1
            continue
        if state == "line":
            if c == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        # block
        if c == "*" and nxt == "/":
            state = "code"
            out.append("  ")
            i += 2
            continue
        out.append("\n" if c == "\n" else " ")
        i += 1
    return "".join(out)


def read_js(path: Path) -> Tuple[str, str]:
    """返回 (原始文本, 剥注释文本)；两者行号一一对应。"""
    raw = path.read_text(encoding="utf-8")
    return raw, strip_comments(raw)


# ── 规则 ①②：分层硬禁令 ─────────────────────────────────────────────────────
def check_layer_bans(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name, spec in LAYER_SPEC.items():
        path = js_dir / name
        if not path.exists():
            out.append(Violation(f"static/js/{name}", 0, "missing-layer-module", "声明的分层模块不存在"))
            continue
        raw, code = read_js(path)
        raw_lines = raw.splitlines()
        code_lines = code.splitlines()
        patterns = [(rule, re.compile(p)) for rule in spec.forbid for p in BAN_PATTERNS[rule]]
        if name in MUTABLE_STATE_MODULES:
            patterns.append(("mutable-state", re.compile(MUTABLE_STATE_PATTERN)))
        for idx, line in enumerate(code_lines):
            for rule, pat in patterns:
                if pat.search(line):
                    out.append(
                        Violation(f"static/js/{name}", idx + 1, f"{spec.layer}禁{rule}", raw_lines[idx])
                    )
    return out


# ── 规则 ③：反向依赖 ─────────────────────────────────────────────────────────
def check_reverse_deps(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name in LAYER_SPEC:
        path = js_dir / name
        if not path.exists():
            continue
        raw, code = read_js(path)
        raw_lines = raw.splitlines()
        for idx, line in enumerate(code.splitlines()):
            m = JS_IMPORT_RE.search(line)
            if not m:
                continue
            target = m.group(1).lstrip("./").split("/")[-1]
            if target in VIEW_MODULES:
                out.append(
                    Violation(f"static/js/{name}", idx + 1, "reverse-dependency", raw_lines[idx])
                )
    return out


# ── 规则 ③b：白名单外的 import ───────────────────────────────────────────────
def check_import_allowlist(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    for name, spec in LAYER_SPEC.items():
        path = js_dir / name
        if not path.exists():
            continue
        raw, code = read_js(path)
        raw_lines = raw.splitlines()
        for idx, line in enumerate(code.splitlines()):
            m = JS_IMPORT_RE.search(line)
            if not m:
                continue
            target = m.group(1).lstrip("./").split("/")[-1]
            if target not in spec.allowed_imports:
                out.append(
                    Violation(
                        f"static/js/{name}",
                        idx + 1,
                        f"{spec.layer}越界import({target})",
                        raw_lines[idx],
                    )
                )
    return out


# ── 规则 ④：重复声明（导入名 vs 本地声明）────────────────────────────────────
def check_duplicate_declarations(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    targets = sorted({*LAYER_SPEC, *VIEW_MODULES})
    for name in targets:
        path = js_dir / name
        if not path.exists():
            continue
        raw, code = read_js(path)
        raw_lines = raw.splitlines()
        imported: Set[str] = set()
        for m in JS_IMPORTED_NAMES_RE.finditer(code):
            for item in m.group(1).split(","):
                item = item.strip()
                if not item:
                    continue
                imported.add(item.split(" as ")[-1].strip())
        declared: Set[str] = set(JS_DECL_RE.findall(code))
        for dup in sorted(imported & declared):
            for idx, line in enumerate(code.splitlines()):
                if re.match(JS_DECL_HEAD + re.escape(dup) + r"\b", line):
                    out.append(
                        Violation(
                            f"static/js/{name}",
                            idx + 1,
                            f"duplicate-declaration({dup})",
                            raw_lines[idx],
                        )
                    )
                    break
    return out


# ── 规则 ⑤：方法一致性（路径维度由既有闸负责，这里只补方法）──────────────────
def load_backend_route_patterns() -> Set[Tuple[str, str]]:
    """(归一化路径, 方法) 集合；路径参数占位归一化为 `{}`。"""
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
_TPL_PARAM_RE = re.compile(r"\$\{[^}]*\}")


def _norm_path(p: str) -> str:
    return _ROUTE_PARAM_RE.sub("{}", _TPL_PARAM_RE.sub("{}", p))


def scan_api_calls(js_dir: Path, name: str = "wr-api.js") -> List[Tuple[int, str, str, str]]:
    """返回 [(行号, 方法, 路径, 原始行)]，只看**代码**里的 `api(...)` 调用。"""
    path = js_dir / name
    if not path.exists():
        return []
    raw, code = read_js(path)
    raw_lines = raw.splitlines()
    calls: List[Tuple[int, str, str, str]] = []
    for idx, line in enumerate(code.splitlines()):
        if not re.search(r"(?<![\w.$])api\s*\(", line):
            continue
        # 路径取该行或其后续 4 行内的第一个引号字面量
        window_code = "\n".join(code.splitlines()[idx : idx + 5])
        pm = re.search(r"api\s*\(\s*([`'])([^`'\n]+)\1", window_code)
        if not pm:
            continue
        method_m = re.search(r"method:\s*'(\w+)'", window_code)
        calls.append(
            (idx + 1, method_m.group(1) if method_m else "GET", pm.group(2), raw_lines[idx])
        )
    return calls


def check_method_parity(js_dir: Path, route_pairs: Set[Tuple[str, str]]) -> List[Violation]:
    out: List[Violation] = []
    for lineno, method, path, raw_line in scan_api_calls(js_dir):
        if (_norm_path(path), method) in route_pairs:
            continue
        # 路径存在但方法不对 —— 这是我们真正要抓的（路径维度另有闸）
        same_path = sorted({m for p, m in route_pairs if p == _norm_path(path)})
        rule = (
            f"method-mismatch({method}!={'/'.join(same_path) if same_path else '未注册'})"
            if same_path
            else "route-path-unregistered"
        )
        out.append(Violation("static/js/wr-api.js", lineno, rule, raw_line))
    return out


# ── 规则 ⑥：防假解耦 ─────────────────────────────────────────────────────────
def check_false_decoupling(js_dir: Path) -> List[Violation]:
    out: List[Violation] = []
    moved: Dict[str, str] = {}
    for name in LAYER_SPEC:
        path = js_dir / name
        if not path.exists():
            continue
        _raw, code = read_js(path)
        for sym in JS_EXPORTED_RE.findall(code):
            moved.setdefault(sym, name)
    host = js_dir / FALSE_DECOUPLING_HOST
    if not host.exists():
        return out
    raw, code = read_js(host)
    raw_lines = raw.splitlines()
    declared = set(JS_DECL_RE.findall(code))
    for sym in sorted(declared & set(moved)):
        for idx, line in enumerate(code.splitlines()):
            if re.match(
                JS_DECL_HEAD + re.escape(sym) + r"\b",
                line,
            ):
                out.append(
                    Violation(
                        f"static/js/{FALSE_DECOUPLING_HOST}",
                        idx + 1,
                        f"false-decoupling({sym} 仍在 {moved[sym]} 里导出)",
                        raw_lines[idx],
                    )
                )
                break
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────
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
        out += check_method_parity(js_dir, route_pairs)
    return out


def _bootstrap_env() -> None:
    """导入 delector 之前把库/缓存路径钉进临时目录，避免污染仓库根的真实 DB。

    （与 `tools/check_frontend_api_contract.py::_bootstrap_env` 同口径——那边 import
    `delector.server` 会经 create_app() 建库/播种，不隔离就会往仓库根写 DB。）
    """
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

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
        help="跳过规则⑤（方法一致性）；仅用于无 python 依赖环境的降级，CI 禁用",
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
        "（L1/L2 禁令 · 反向依赖 · 越界 import · 重复声明 · 方法一致 · 防假解耦）。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())