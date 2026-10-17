# -*- coding: utf-8 -*-
"""mock 漂移机械闸（C8 事故族的**类级**固化；C9 Task 3）。

为什么要这道闸
--------------
C8 批次的真实事故：生产 `_shelf_get`（delector/routes/encounter.py）把
`httpx.get(url, timeout=…)` 改成 `httpx.stream("GET", url, timeout=…)`，而 4 个测试仍
`monkeypatch.setattr(encounter_mod.httpx, "get", …)` —— 补丁**钉在了一个已无调用点的
符号**上：它照常执行、零报错，但生产已不再调用被替换的符号 ⇒ 补丁空转，测试从
「验证真实路径」退化为「假绿」。CI 直到真实网络调用打出站才红 —— 属反馈最晚的一类失败。
本闸把这一**形状**做成可测判定器：CI job ``mock-drift`` 按 fail-loud 口径执行它
（退出码 1 = 有未豁免站点）。结构照 ``tools/check_silent_degradation.py``（纯 stdlib、
0/1/2 退出码、``--report-only`` 只看清单不判红）。

判据（窄，一条；MUST NOT 扩成泛化的 mock 风格审查）
--------------------------------------------------
对 ``tests/**/*.py`` 中每个 ``monkeypatch.setattr(<obj>, "<symbol>", …)``：
  1. 解析 ``<obj>`` 的来源（测试文件内的 ``import`` 别名链 → 模块；取**最长可达模块
     前缀**，故 ``encounter_mod.httpx`` 归属 ``delector.routes.encounter``）；
  2. 若该模块是**生产模块**（``delector.*`` / ``tools.*``），要求 ``<symbol>`` 在该模块
     源码内**至少被引用/调用一次**（除其定义点外；判定按名字形状，见「极限」#4）；
  3. 否则判违规 —— 补丁目标符号已无调用点（死测 / 假绿形状）。

极限（抓不到什么；决定去留 / 扩判据时 MUST 读）
----------------------------------------------
本闸是**死测 / 假绿探测器**，不是风格规则；判定面止于静态可达范围。以下一律不判：
  1. 符号名非字符串字面量（``setattr(obj, name_var, …)``）⇒ 静态拿不到符号名；
  2. 间接 / 动态解析：``importlib.import_module(…)``、模块别名经**本地变量转存**
     （``m = encounter_mod`` 后再 ``setattr(m, …)``）、re-export 别名、以及经字符串
     注册表间接消费的符号 —— 本闸只解析测试文件内的 ``import`` 别名链；
  3. 字符串寻址形态 ``monkeypatch.setattr("delector.x.y.sym", value)``（首参为点分字符串）
     **不在本条判据口径内**（判据只看 ``<obj>, "<symbol>"`` 形态）—— 不投机扩大；
  4. **名字 ≠ 对象**：引用判定按名字形状（``x.sym`` 与 ``target.sym`` 同名同形不可区分）
     ⇒ 「目标对象已不再使用该符号、但同模块他处仍有同名属性/名字」的漂移会**漏报**；
     反之，本地变量遮蔽 import 别名的极端场景可能误报（登记为已知边界）；
  5. 「符号仍被调用但语义已变」（签名 / 行为变更）与「补丁是否真的生效」（monkeypatch
     字符串寻址、目标对象与生产调用路径是否同一对象）一律不判 —— 超出静态可达范围，
     做了就是假精度；
  6. 非 ``monkeypatch.setattr`` 的 mock 面（``unittest.mock.patch`` / pytest-mock /
     其他 fixture 注入）不在扫描面。

豁免约定（**绝不静默**：豁免站点也逐行打印并在行尾标注）
----------------------------------------------------
候选行（``monkeypatch.setattr(…)`` 调用行）的**同一行**或**上一行**的**注释**里出现
``mock-drift-ok: REASON`` ⇒ 豁免该站点。REASON 留空（标记后什么都不写）= 抑制无效：
站点照常判红，并在输出中标注。REASON MUST 具体到「为什么此站点安全」（例：符号经
字符串注册表消费、目标按 re-export 使用……）；具体性由评审把关 —— 故豁免行一律打印、
可被审阅。多行 ``monkeypatch.setattr(`` 的标记请写在调用行行尾或其上一行 —— 判定只看
这两行。

退出码
------
0 = 通过（含 ``--report-only``；该模式扫描完成即 0，候选不影响退出码）
1 = 有**未豁免**的站点
2 = 环境不可用（扫描面缺失 / 为空 / 文件不可读 / 无法解析 / 参数错误）

只读：仅读 ``<root>/tests/**/*.py`` 与（做引用判定时）被解析到的生产模块源码；零子进程、零网络。
"""

# ── 缺陷族档案（决定这道闸的去留时读这里，不要读 PR 描述）────────────────────────────
# 缺陷形态（一句话）：测试的补丁**钉在一个已无调用点的符号**上 —— 补丁照常执行、零报错，
#   但生产路径已不再调用被替换的符号 ⇒ 测试验证的东西消失了（假绿），而非失败。
#
# 具体事故（本仓实测，2026-10 C8 批次）：生产 `_shelf_get`（delector/routes/encounter.py）
#   把 `httpx.get(url, timeout=…)` 改为 `httpx.stream("GET", url, timeout=…)`；4 个用例
#   （tests/test_encounter_pull.py ×3 · tests/test_syntax_hard_api.py ×1，同形状站点另见
#   tests/test_server.py）仍 `monkeypatch.setattr(<encounter 模块>.httpx, "get", …)`
#   ⇒ 补丁空转，真实网络调用打到假私网地址，CI 双 runner 齐红。
#
# 为什么更便宜的层不够（CI 才是权威层）：单元测试自身看不见「补丁是否仍有意义」
#   （空转补丁不抛错）；code review 对人眼也近乎不可见（diff 里两个词之差）；
#   `.githooks/pre-commit` 只做暂存区密钥扫描，对本形态零覆盖且可被 --no-verify 绕过。
#   只有对「补丁符号 × 目标模块」做机械引用判定，才能把该形状变成必红。
#
# 判据的固有边界（MUST 明说）：判据检测的是**形状**，不是某个 one-off；形状合规 ≠
#   测试有效（补丁仍可能覆盖不到真实路径，那属于动态可达性的另一问题，见「极限」#5）。
#   发现新形态时应当**另立判据并以建议形式报告**，MUST NOT 顺手扩大本条。

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple, Optional, Sequence, TextIO

#: 扫描面（相对根目录）：仅测试面，与任务书逐字一致，MUST NOT 顺手扩大。
SCAN_DIR = "tests"

#: 生产模块顶层包：只有指向这两个包内模块的补丁站点才受判据约束。
PRODUCTION_ROOTS: frozenset[str] = frozenset({"delector", "tools"})

#: 豁免标记。形式：``mock-drift-ok: REASON``（REASON 非空才生效）。
SUPPRESSION_MARKER = "mock-drift-ok:"

#: 输出片段的长度上限（超出截断加省略号），防止超长行刷屏。
MAX_SNIPPET_CHARS = 120

_SUPPRESSION_RE = re.compile(r"mock-drift-ok:(?P<reason>.*)")


class ScanEnvironmentError(RuntimeError):
    """扫描环境不可用（扫描面缺失 / 为空、文件不可读 / 无法解析）⇒ CLI 退出码 2。"""


class RawHit(NamedTuple):
    """AST 层的一条原始命中（尚未做引用判定与豁免判定）。"""

    line: int
    symbol: str
    module: str
    obj: str


class Site(NamedTuple):
    """最终候选站点：补丁目标符号在目标模块内已无引用/调用点 + 豁免判定结果。"""

    path: str  # 仓库相对路径（posix 分隔）
    line: int
    symbol: str
    module: str
    obj: str
    exempt: bool
    reason: str
    empty_reason: bool

    def render(self) -> str:
        """渲染单行输出：``file:line | symbol | module | obj=…``（豁免/空理由加尾注）。"""
        head = f"{self.path}:{self.line} | {self.symbol} | {self.module} | obj={self.obj!r}"
        if self.exempt:
            return f"{head} | [exempt] mock-drift-ok: {self.reason}"
        if self.empty_reason:
            return f"{head} | [违规] mock-drift-ok 的 REASON 为空：抑制无效，站点照常判红"
        return head


class ScanResult(NamedTuple):
    """一次扫描的结果（供 run_scan 汇总输出与单测直接断言）。"""

    files_scanned: int
    patch_sites: int  # 生产模块目标的 monkeypatch.setattr 站点总数（含符号仍被引用的）
    sites: list[Site]  # 候选站点（符号已无引用/调用点；含豁免与否的判定结果）


# ── 文本工具 ─────────────────────────────────────────────────────────────────────


def _collapse_whitespace(text: str) -> str:
    """把任意空白折叠为单个空格并去首尾（多行片段压成一行，便于逐行输出）。"""
    return re.sub(r"\s+", " ", text).strip()


def _clip(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    """超长截断（保留 limit 个字符 + 省略号）。"""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ── <obj> → 生产模块的静态解析（只认测试文件内的 import 别名链）────────────────────


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    """测试文件内的 ``import`` 别名表：绑定名 → 点分路径（best effort）。

    只解析 ``import a.b.c [as x]`` 与 ``from a.b import c [as x]`` 两种形态；
    相对导入（level>0）与 ``import *`` 不参与 —— 见模块头「极限」#2。
    ``import a.b.c``（无 as）绑定的是顶层名 ``a``，attr 链在调用点再拼接。
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.asname:
                    aliases[item.asname] = item.name
                else:
                    top = item.name.split(".")[0]
                    aliases.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level:
                continue
            for item in node.names:
                if item.name == "*":
                    continue
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _module_file(root: Path, dotted: str) -> Optional[Path]:
    """点分模块路径 → 仓库内文件（``x/y.py`` 或 ``x/y/__init__.py``）；不存在返回 None。"""
    if not dotted:
        return None
    base = root.joinpath(*dotted.split("."))
    candidate = base.with_suffix(".py")
    if candidate.is_file():
        return candidate
    package_init = base / "__init__.py"
    if package_init.is_file():
        return package_init
    return None


def _resolve_module(root: Path, aliases: dict[str, str], expr: ast.expr) -> Optional[tuple[str, Path]]:
    """把 ``<obj>`` 表达式解析为（模块点分路径, 模块文件）；无法静态解析返回 None。

    取**最长可达模块前缀**：``encounter_mod.httpx`` → ``delector.routes.encounter``
    （尾随属性是模块内的子对象，不影响「补丁目标归属哪个生产模块」的判定）。
    表达式根部不是 import 别名（fixture / 本地变量 / 复合表达式）⇒ None（跳过，见「极限」#2）。
    """
    attrs: list[str] = []
    node: ast.expr = expr
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    base = aliases.get(node.id)
    if base is None:
        return None
    candidate = base if not attrs else base + "." + ".".join(reversed(attrs))
    parts = candidate.split(".")
    for end in range(len(parts), 0, -1):
        dotted = ".".join(parts[:end])
        path = _module_file(root, dotted)
        if path is not None:
            return dotted, path
    return None


def _is_production_module(dotted: str) -> bool:
    """生产模块判定：点分路径的顶层包属于 ``delector`` / ``tools``。"""
    return dotted.split(".")[0] in PRODUCTION_ROOTS


# ── 引用判定：符号在目标模块内是否仍有引用/调用点（除定义点外）──────────────────────


class _SymbolReferenceVisitor(ast.NodeVisitor):
    """名字形状口径的引用探测器（不追对象身份 —— 见模块头「极限」#4）。

    计入：``Name`` 的 Load / Del 上下文、``AugAssign`` 的目标名（读-改-写）、以及
    **任意上下文**的属性访问 ``x.<symbol>``（调用 ``.sym(…)``、读取 ``.sym``、赋值均计）。
    不计入（= 定义点本身）：``def <symbol>`` / ``class <symbol>``（名字是字符串字段，
    天然不是 Name 节点）、import 绑定、普通赋值目标、形参名、循环/with/except 的绑定名。
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.found = False

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.symbol and not isinstance(node.ctx, ast.Store):
            self.found = True
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == self.symbol:
            self.found = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == self.symbol:
            self.found = True
        self.generic_visit(node)


def _module_references_symbol(source: str, symbol: str) -> bool:
    """目标模块源码内，除定义点外是否还有该符号的引用/调用点。"""
    tree = ast.parse(source)
    visitor = _SymbolReferenceVisitor(symbol)
    visitor.visit(tree)
    return visitor.found


def _module_source(root: Path, module: str, sources: dict[str, str]) -> str:
    """读取（并缓存）目标模块源码；文件缺失 / 不可读 ⇒ 环境错误（拒绝放行）。"""
    if module not in sources:
        path = _module_file(root, module)
        if path is None:
            # 理论不可达：模块名来自 _resolve_module 的文件命中结果。
            raise ScanEnvironmentError(f"目标模块文件缺失（解析成功但取不到文件）：{module}")
        try:
            sources[module] = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise ScanEnvironmentError(f"目标模块不可读：{path}（{exc}）") from exc
    return sources[module]


def _module_reference_cached(
    root: Path,
    module: str,
    symbol: str,
    sources: dict[str, str],
    results: dict[tuple[str, str], bool],
) -> bool:
    """引用判定的缓存层：同一（模块, 符号）只解析一次。"""
    key = (module, symbol)
    if key not in results:
        source = _module_source(root, module, sources)
        try:
            results[key] = _module_references_symbol(source, symbol)
        except SyntaxError as exc:
            raise ScanEnvironmentError(
                f"目标模块无法解析（无法判定 ⇒ 拒绝放行）：{module}:{exc.lineno} {exc.msg}"
            ) from exc
    return results[key]


# ── 测试面扫描：收集 monkeypatch.setattr 站点 ─────────────────────────────────────


def _visit_mock_calls(node: ast.AST, root: Path, aliases: dict[str, str]) -> list[RawHit]:
    """收集单个 AST 树里指向生产模块的 ``monkeypatch.setattr(<obj>, "<symbol>", …)``。"""
    hits: list[RawHit] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if not (isinstance(func, ast.Attribute) and func.attr == "setattr"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "monkeypatch"):
            continue
        if len(sub.args) < 2:  # 判据口径：<obj> + "<symbol>" 两参形态
            continue
        obj_expr, symbol_expr = sub.args[0], sub.args[1]
        if not (isinstance(symbol_expr, ast.Constant) and isinstance(symbol_expr.value, str)):
            continue  # 符号名非字符串字面量 ⇒ 静态不可判（「极限」#1）
        resolved = _resolve_module(root, aliases, obj_expr)
        if resolved is None:
            continue
        dotted, _path = resolved
        if not _is_production_module(dotted):
            continue
        hits.append(
            RawHit(
                line=sub.lineno,
                symbol=symbol_expr.value,
                module=dotted,
                obj=_clip(_collapse_whitespace(ast.unparse(obj_expr))),
            )
        )
    return hits


def scan_test_source(source: str, root: Path) -> list[RawHit]:
    """扫描一个测试文件的源码，返回去重、按（行号, 符号, 模块）排序的原始命中。"""
    tree = ast.parse(source)
    aliases = _module_aliases(tree)
    unique: list[RawHit] = []
    seen: set[tuple[int, str, str, str]] = set()
    for hit in _visit_mock_calls(tree, root, aliases):
        key = (hit.line, hit.symbol, hit.module, hit.obj)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    unique.sort(key=lambda hit: (hit.line, hit.symbol, hit.module))
    return unique


# ── 豁免层（只认**注释**里的标记；字符串字面量里的不算）──────────────────────────


def comments_by_line(source: str) -> dict[int, list[str]]:
    """按行号收集注释文本（tokenize 口径 —— 字符串里的 ``mock-drift-ok:`` 不算注释）。"""
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

    查调用行与其上一行（任务书口径：same line or the line above）；取第一条非空理由。
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


def collect_sites(root: Path) -> ScanResult:
    """扫描 root/tests 下全部 .py；返回（扫描文件数, 生产补丁站点数, 候选站点列表）。

    环境问题（扫描面缺失 / 为空、文件不可读 / 无法解析）一律抛 ScanEnvironmentError：
    闸 MUST NOT 在「看不全」的情况下静默放行（这正是它要防的失败形态的镜像）。
    """
    if not root.is_dir():
        raise ScanEnvironmentError(f"扫描根目录不存在或不是目录：{root}")
    base = root / SCAN_DIR
    if not base.is_dir():
        raise ScanEnvironmentError(f"扫描面缺失：{base} ⇒ 闸空转，拒绝放行")
    targets = [path for path in sorted(base.rglob("*.py")) if path.is_file() and "__pycache__" not in path.parts]
    if not targets:
        raise ScanEnvironmentError(f"扫描面为空：{base} 下无任何 .py ⇒ 闸空转，拒绝放行")
    module_sources: dict[str, str] = {}
    reference_cache: dict[tuple[str, str], bool] = {}
    patch_sites = 0
    sites: list[Site] = []
    for path in targets:
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise ScanEnvironmentError(f"文件不可读：{path}（{exc}）") from exc
        try:
            hits = scan_test_source(source, root)
        except SyntaxError as exc:
            raise ScanEnvironmentError(
                f"文件无法解析（无法判定 ⇒ 拒绝放行）：{path}:{exc.lineno} {exc.msg}"
            ) from exc
        patch_sites += len(hits)
        if not hits:
            continue
        comments = comments_by_line(source)
        rel_path = path.relative_to(root).as_posix()
        for hit in hits:
            if _module_reference_cached(root, hit.module, hit.symbol, module_sources, reference_cache):
                continue  # 符号仍被引用/调用 ⇒ 补丁尚未漂移，不进入候选
            exempt, reason, empty_reason = suppression_state(comments, hit.line)
            sites.append(
                Site(
                    path=rel_path,
                    line=hit.line,
                    symbol=hit.symbol,
                    module=hit.module,
                    obj=hit.obj,
                    exempt=exempt,
                    reason=reason,
                    empty_reason=empty_reason,
                )
            )
    sites.sort(key=lambda site: (site.path, site.line, site.symbol))
    return ScanResult(files_scanned=len(targets), patch_sites=patch_sites, sites=sites)


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
        result = collect_sites(root)
    except ScanEnvironmentError as exc:
        print(f"[mock-drift] 环境不可用：{exc}", file=stderr)
        return 2

    violations = [site for site in result.sites if not site.exempt]
    for site in result.sites:
        print(site.render(), file=stdout)

    print(
        f"[mock-drift] 扫描完成：{result.files_scanned} 个 .py；生产模块补丁站点 {result.patch_sites} 个；"
        f"其中补丁目标符号已无引用/调用点的候选 {len(result.sites)} 个"
        f"（已豁免 {len(result.sites) - len(violations)} 个，未豁免 {len(violations)} 个）。",
        file=stdout,
    )

    if report_only:
        print("[mock-drift] --report-only：仅报告，不影响退出码（本模式恒 0；环境错误仍为 2）。", file=stdout)
        return 0
    if violations:
        print(
            f"[mock-drift] 违规：{len(violations)} 个未豁免站点（判据：补丁目标符号在目标模块内"
            f"已无引用/调用点 ⇒ 死测/假绿形状；逐行清单见 stdout）⇒ 非零退出。",
            file=stderr,
        )
        return 1
    print("[mock-drift] 通过：无未豁免站点。", file=stdout)
    return 0


def _default_root() -> Path:
    """仓库根 = 本脚本的上一级目录（tools/ 的父目录），与 CWD 无关。"""
    return Path(__file__).resolve().parents[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。退出码：0=通过；1=有未豁免站点；2=环境不可用（同 check_silent_degradation）。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：中文需 UTF-8
        except ValueError:  # silent-ok: 仅显示层编码（流已关闭/不可重配置），失败时保持原流，不影响判定与退出码
            pass

    parser = argparse.ArgumentParser(
        description="mock 漂移机械闸（判据：monkeypatch.setattr 的目标符号在生产模块内已无引用/调用点）。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="扫描根目录（默认=本脚本所在仓库根；从其下解析 tests/ 与目标生产模块）",
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