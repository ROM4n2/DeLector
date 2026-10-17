# -*- coding: utf-8 -*-
"""无静默降级机械闸（C2/C8 缺陷族的**类级**固化；Task 8）。

为什么要这道闸
--------------
C2/C8 缺陷族共享同一形态：**错误 / 降级路径不可见** —— 异常被吞（``except: pass``）、
异常类型被裸 ``except:`` 抹平、证书校验被悄悄关掉而零痕迹。这些站点已被逐个人工修复，
但**类**此前没有机械闸 ⇒ 可以无声回长。本脚本把三条窄判据做成可测判定器：
CI job ``silent-degradation`` 按 fail-loud 口径执行它（退出码 1 = 有未豁免站点 ⇒ job 红），
本地可用 ``--report-only`` 只看清单不判红。结构照 ``tools/check_master_commit_scope.py``
（纯 stdlib、argv 友好、0/1/2 退出码）。

三条判据（窄口径；MUST NOT 扩成泛化的异常处理风格审查）
--------------------------------------------------------
C1  静默吞错：``except ...:`` 子句体**只**由 ``pass`` / ``continue`` 组成；体内出现任何
    log / warn / raise / 带值 return ⇒ 不算（那是有痕迹的处理）。
C2  裸 ``except:``：无异常类型（连 KeyboardInterrupt / SystemExit 一并吞掉的形态）。
C3  证书校验静默关闭：``ssl._create_unverified_context(`` / ``ssl.CERT_NONE`` / ``verify=False``，
    且**最近的封闭函数**（无函数包裹时按模块体）内没有任何 logging / warnings 调用。

豁免约定（**绝不静默**：豁免站点也逐行打印并在行尾标注）
--------------------------------------------------------
命中行的**同一行**或**上一行**的**注释**里出现 ``silent-ok: REASON`` ⇒ 豁免该站点。
REASON 留空（``silent-ok:`` 后什么都不写）= 抑制无效：站点照常判红，并在输出中标注。
REASON MUST 具体到「为什么此站点安全」；占位式 ``ok`` / ``intentional`` 属废话、不算数
（本闸只能机械判定空 / 非空，具体性由评审把关 —— 故豁免行一律打印、可被审阅）。
多行 ``except`` 的标记请写在 ``except`` 那一行（行尾）或其上一行 —— 判定只看这两行。

退出码
------
0 = 通过（含 ``--report-only``；该模式扫描完成即 0，命中不影响退出码）
1 = 有**未豁免**的站点
2 = 环境不可用（扫描面缺失 / 为空 / 文件不可读 / 无法解析 / 参数错误）

只读：仅读 ``<root>/delector/**/*.py`` 与 ``<root>/tools/**/*.py``；零子进程、零网络。
"""

# ── 缺陷族档案（决定这道闸的去留时读这里，不要读 PR 描述）────────────────────────────
# 缺陷形态（一句话）：错误 / 降级路径执行了，但**观测不到**（异常被吞、无日志、无边界），
#   调用方据此把「降级了」读成「一切正常」。
#
# 同形态的具体事故（本仓实测）：
#   1) `clear_audio_cache`（delector/routes/main.py）：`except Exception: pass` 吞掉删除失败，
#      且 freed_mb 返回的是**清理前**的总量 ⇒ 在「什么都没删掉」时响应依然报告清理成功，
#      前端拿到一个静默说谎的数字（修法：pre/post 差值口径 + 失败计数上报）。
#   2) `delector/services/tts.py` 的 `ssl._create_unverified_context()` 回退：证书校验被关掉
#      而**零日志** ⇒ Android 端静默降级到不校验的连接，无人知晓（并行批次在补可观测性）。
#   （同族还包括 encounter 抓取无大小闸、settings 非回环来源不脱敏等 —— 均已逐项修复，
#    本闸的职责是让**类**不再无声回长，而不是逐项复刻它们。）
#
# 为什么更便宜的层不够（CI 才是权威层）：
#   `.githooks/pre-commit` 只做**暂存区密钥扫描**（另一个形态），对静默降级零覆盖；
#   且任何本地 hook 都可被 `--no-verify` 绕过、fresh clone 上根本没有 hook。
#   只有 CI 侧的机械闸不可绕过 —— 这就是本闸挂在 CI（job `silent-degradation`）的原因。
#
# 判据的固有边界（MUST 明说）：每条判据检测的是**形态（shape）**，不是某个具体 one-off；
#   形态合规 ≠ 站点正确（一个吞错却写足日志的站点仍可能错）。发现新形态时应当**另立判据
#   并以建议形式报告**，MUST NOT 顺手扩大现有判据（多一条模式 = 多一片假阳性面）。

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple, Optional, Sequence, TextIO

#: 扫描面（相对根目录）：与任务书逐字一致，MUST NOT 顺手扩大。
SCAN_DIRS: tuple[str, ...] = ("delector", "tools")

#: 判据编号（输出里的 criterion-number 字段）。
CRITERION_SILENT_SWALLOW = "C1"
CRITERION_BARE_EXCEPT = "C2"
CRITERION_UNVERIFIED_TLS = "C3"
CRITERIA: tuple[str, ...] = (CRITERION_SILENT_SWALLOW, CRITERION_BARE_EXCEPT, CRITERION_UNVERIFIED_TLS)

#: 豁免标记。形式：``silent-ok: REASON``（REASON 非空才生效）。
SUPPRESSION_MARKER = "silent-ok:"

#: 输出片段的长度上限（超出截断加省略号），防止超长行刷屏。
MAX_SNIPPET_CHARS = 120

#: C3 的「有观测」判定：属性链最左端名字（去下划线、小写化后）落在该集合。
_LOG_ROOT_NAMES: frozenset[str] = frozenset({"logging", "warnings", "log", "logger", "lg"})
#: C3 的「有观测」判定：方法名落在该集合（logging.warning / logger.error / warnings.warn …）。
_LOG_METHOD_NAMES: frozenset[str] = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception", "fatal", "log"}
)

_SUPPRESSION_RE = re.compile(r"silent-ok:(?P<reason>.*)")


class ScanEnvironmentError(RuntimeError):
    """扫描环境不可用（扫描面缺失 / 为空、文件不可读 / 无法解析）⇒ CLI 退出码 2。"""


class RawHit(NamedTuple):
    """AST 层的一条原始命中（尚未做豁免判定）。"""

    line: int
    criterion: str
    snippet: str


class Site(NamedTuple):
    """最终站点：原始命中 + 豁免判定结果（输出与退出码都看这一层）。"""

    path: str  # 仓库相对路径（posix 分隔）
    line: int
    criterion: str
    snippet: str
    exempt: bool
    reason: str
    empty_reason: bool

    def render(self) -> str:
        """渲染单行输出：``file:line | criterion | 'snippet'``（豁免/空理由加尾注）。"""
        head = f"{self.path}:{self.line} | {self.criterion} | {self.snippet!r}"
        if self.exempt:
            return f"{head} | [exempt] silent-ok: {self.reason}"
        if self.empty_reason:
            return f"{head} | [违规] silent-ok 的 REASON 为空：抑制无效，站点照常判红"
        return head


# ── 文本工具 ─────────────────────────────────────────────────────────────────────


def _collapse_whitespace(text: str) -> str:
    """把任意空白折叠为单个空格并去首尾（多行片段压成一行，便于逐行输出）。"""
    return re.sub(r"\s+", " ", text).strip()


def _clip(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    """超长截断（保留 limit 个字符 + 省略号）。"""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ── C1 / C3 的纯判定件 ─────────────────────────────────────────────────────────


def _is_silent_body(body: Sequence[ast.stmt]) -> bool:
    """C1 判定：体非空且**每条**语句都是 pass / continue（注释不算语句）。"""
    return bool(body) and all(isinstance(stmt, (ast.Pass, ast.Continue)) for stmt in body)


def _root_name(expr: ast.expr) -> str:
    """沿属性 / 调用链取最左端名字：``logging.getLogger(x).warning`` → ``logging``。"""
    node: ast.AST = expr
    while True:
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Name):
            return node.id
        else:
            return ""


def _is_logging_call(node: ast.Call) -> bool:
    """C3 的「有观测」判定：是否为 logging / warnings 调用（见 _LOG_ROOT_NAMES 注释）。"""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _LOG_METHOD_NAMES:
        return False
    root = _root_name(func.value).lower().lstrip("_")
    return root in _LOG_ROOT_NAMES


def _is_unverified_context_call(node: ast.Call) -> bool:
    """C3 判定①：``ssl._create_unverified_context(...)``（属性形式或直接导入的名字）。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "_create_unverified_context"
    if isinstance(func, ast.Name):
        return func.id == "_create_unverified_context"
    return False


class _ScopeInfo:
    """一个「封闭函数」的探测上下文（模块体也算一个作用域，见访问器类注释）。"""

    __slots__ = ("has_log_call", "ssl_sites")

    def __init__(self) -> None:
        self.has_log_call: bool = False
        #: (行号, 用于截片段的节点)
        self.ssl_sites: list[tuple[int, ast.AST]] = []


class _SilentDegradationVisitor(ast.NodeVisitor):
    """收集 C1 / C2 / C3 三类原始命中（不含豁免判定 —— 那一步在文本层做）。

    C3 的口径是「最近的封闭函数内无 logging / warnings 调用」：本访问器按
    FunctionDef / AsyncFunctionDef / Lambda / Module 压栈，退出时结算该作用域内的
    ssl 站点 —— 嵌套函数各自独立判定（内层有日志不清洗外层）。
    """

    def __init__(self, source: str) -> None:
        self.hits: list[RawHit] = []
        self._source = source
        self._lines = source.splitlines()
        self._scopes: list[_ScopeInfo] = []

    # -- 作用域 ---------------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:
        self._scoped(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scoped(node)

    def _scoped(self, node: ast.AST) -> None:
        scope = _ScopeInfo()
        self._scopes.append(scope)
        self.generic_visit(node)
        self._scopes.pop()
        if scope.has_log_call:
            return
        for line, site_node in scope.ssl_sites:
            self.hits.append(
                RawHit(line=line, criterion=CRITERION_UNVERIFIED_TLS, snippet=self._snippet_for(site_node))
            )

    # -- C1 / C2：异常处理 ----------------------------------------------------

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            header = self._snippet_for(node, header_only=True)
            self.hits.append(RawHit(line=node.lineno, criterion=CRITERION_BARE_EXCEPT, snippet=header))
        if _is_silent_body(node.body):
            body = self._snippet_for(node)
            self.hits.append(RawHit(line=node.lineno, criterion=CRITERION_SILENT_SWALLOW, snippet=body))
        self.generic_visit(node)

    # -- C3：证书校验静默关闭 --------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if self._scopes and _is_logging_call(node):
            self._scopes[-1].has_log_call = True
        if _is_unverified_context_call(node):
            self._record_ssl_site(node.lineno, node)
        for keyword in node.keywords:
            if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
                self._record_ssl_site(keyword.value.lineno, node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "CERT_NONE":
            self._record_ssl_site(node.lineno, node)
        self.generic_visit(node)

    def _record_ssl_site(self, line: int, node: ast.AST) -> None:
        if self._scopes:
            self._scopes[-1].ssl_sites.append((line, node))
            return
        # 理论不可达：入口恒为 visit(Module)，作用域栈至少含模块体。保险起见仍上报
        # （宁可多报也不丢站点），而不是静默丢弃。
        self.hits.append(RawHit(line=line, criterion=CRITERION_UNVERIFIED_TLS, snippet=self._snippet_for(node)))

    # -- 片段提取 -------------------------------------------------------------

    def _snippet_for(self, node: ast.AST, *, header_only: bool = False) -> str:
        """节点的源码片段：折叠空白、裁剪长度；取不到时退回物理行文本。"""
        segment = ast.get_source_segment(self._source, node)
        if segment is None:
            lineno = getattr(node, "lineno", 0)
            text = self._lines[lineno - 1] if 1 <= lineno <= len(self._lines) else ""
        else:
            lines = segment.splitlines()
            text = lines[0] if header_only and lines else segment
        return _clip(_collapse_whitespace(text))


def scan_source(source: str) -> list[RawHit]:
    """扫描一段 Python 源码，返回去重、按（行号, 判据）排序的原始命中。"""
    tree = ast.parse(source)
    visitor = _SilentDegradationVisitor(source)
    visitor.visit(tree)
    unique: list[RawHit] = []
    seen: set[tuple[int, str, str]] = set()
    for hit in visitor.hits:
        key = (hit.line, hit.criterion, hit.snippet)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    unique.sort(key=lambda hit: (hit.line, hit.criterion))
    return unique


# ── 豁免层（只认**注释**里的标记；字符串字面量里的不算）──────────────────────────


def comments_by_line(source: str) -> dict[int, list[str]]:
    """按行号收集注释文本（tokenize 口径 —— 字符串里的 ``silent-ok:`` 不算注释）。"""
    comments: dict[int, list[str]] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments.setdefault(token.start[0], []).append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # tokenize 失败（ast 已解析通过时理论上不可能）⇒ 返回空表：不做任何豁免。
        # 失败方向是**更严**（把带注释的站点照常判红），不是静默放行 —— 见模块头纪律。
        return {}
    return comments


def suppression_state(comments: dict[int, list[str]], line: int) -> tuple[bool, str, bool]:
    """判定某行是否被豁免；返回（是否豁免, 理由, 是否存在空理由的抑制标记）。

    查命中行与其上一行（任务书口径：same line or the line above）；取第一条非空理由。
    空理由 = 抑制无效：调用方按违规处理，并在输出中标注。
    """
    exempt = False
    reason = ""
    empty_reason = False
    for probe in (line, line - 1):
        if probe < 1:
            continue
        for comment in comments.get(probe, []):
            for match in _SUPPRESSION_RE.finditer(comment):
                tail = match.group("reason").strip()
                if tail:
                    if not exempt:
                        exempt = True
                        reason = tail
                else:
                    empty_reason = True
    return exempt, reason, empty_reason


# ── 扫描与运行 ──────────────────────────────────────────────────────────────────


def collect_sites(root: Path) -> tuple[int, list[Site]]:
    """扫描 root 下 delector/ 与 tools/ 的全部 .py；返回（扫描文件数, 站点列表）。

    环境问题（扫描面缺失 / 为空、文件不可读 / 无法解析）一律抛 ScanEnvironmentError：
    闸 MUST NOT 在「看不全」的情况下静默放行（这正是它要防的失败形态的镜像）。
    """
    if not root.is_dir():
        raise ScanEnvironmentError(f"扫描根目录不存在或不是目录：{root}")
    targets: list[Path] = []
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.is_dir():
            raise ScanEnvironmentError(f"扫描面缺失：{base} ⇒ 闸空转，拒绝放行")
        targets.extend(
            path for path in sorted(base.rglob("*.py")) if path.is_file() and "__pycache__" not in path.parts
        )
    if not targets:
        raise ScanEnvironmentError(f"扫描面为空：{root} 下 {' / '.join(SCAN_DIRS)} 无任何 .py ⇒ 闸空转，拒绝放行")
    sites: list[Site] = []
    for path in targets:
        try:
            source = path.read_text(encoding="utf-8-sig")  # utf-8-sig：容忍 BOM，不因 BOM 崩
        except (OSError, UnicodeDecodeError) as exc:
            raise ScanEnvironmentError(f"文件不可读：{path}（{exc}）") from exc
        try:
            hits = scan_source(source)
        except SyntaxError as exc:
            raise ScanEnvironmentError(f"文件无法解析（无法判定 ⇒ 拒绝放行）：{path}:{exc.lineno} {exc.msg}") from exc
        comments = comments_by_line(source)
        rel_path = path.relative_to(root).as_posix()
        for hit in hits:
            exempt, reason, empty_reason = suppression_state(comments, hit.line)
            sites.append(
                Site(
                    path=rel_path,
                    line=hit.line,
                    criterion=hit.criterion,
                    snippet=hit.snippet,
                    exempt=exempt,
                    reason=reason,
                    empty_reason=empty_reason,
                )
            )
    sites.sort(key=lambda site: (site.path, site.line, site.criterion))
    return len(targets), sites


def run_scan(
    root: Path,
    *,
    report_only: bool = False,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
) -> int:
    """核心运行：返回退出码（0/1/2）。豁免一律显式打印（绝不静默）。"""
    stdout: TextIO = sys.stdout if out is None else out
    stderr: TextIO = sys.stderr if err is None else err

    try:
        files_scanned, sites = collect_sites(root)
    except ScanEnvironmentError as exc:
        print(f"[silent-degradation] 环境不可用：{exc}", file=stderr)
        return 2

    violations = [site for site in sites if not site.exempt]
    for site in sites:
        print(site.render(), file=stdout)

    per_criterion = " / ".join(
        f"{criterion}={sum(1 for site in sites if site.criterion == criterion)}" for criterion in CRITERIA
    )
    print(
        f"[silent-degradation] 扫描完成：{files_scanned} 个 .py；命中 {len(sites)} 个站点"
        f"（{per_criterion}）；已豁免 {len(sites) - len(violations)} 个，未豁免 {len(violations)} 个。",
        file=stdout,
    )

    if report_only:
        print("[silent-degradation] --report-only：仅报告，不影响退出码（本模式恒 0；环境错误仍为 2）。", file=stdout)
        return 0
    if violations:
        print(
            f"[silent-degradation] 违规：{len(violations)} 个未豁免站点"
            f"（判据 C1/C2/C3，逐行清单见 stdout）⇒ 非零退出。",
            file=stderr,
        )
        return 1
    print("[silent-degradation] 通过：无未豁免站点。", file=stdout)
    return 0


def _default_root() -> Path:
    """仓库根 = 本脚本的上一级目录（tools/ 的父目录），与 CWD 无关。"""
    return Path(__file__).resolve().parents[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。退出码：0=通过；1=有未豁免站点；2=环境不可用（同 check_master_commit_scope）。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：中文需 UTF-8
        except ValueError:  # silent-ok: 仅显示层编码（流已关闭/不可重配置），失败时保持原流，不影响判定与退出码
            pass

    parser = argparse.ArgumentParser(
        description="无静默降级机械闸（C1 静默吞错 / C2 裸 except / C3 证书校验静默关闭）。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="扫描根目录（默认=本脚本所在仓库根；从根下解析 delector/ 与 tools/）",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="只报告不判红（退出码恒 0；环境不可用仍为 2）",
    )
    args = parser.parse_args(argv)
    root: Path = _default_root() if args.root is None else args.root
    return run_scan(root, report_only=bool(args.report_only))


if __name__ == "__main__":
    raise SystemExit(main())