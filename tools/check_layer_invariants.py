# -*- coding: utf-8 -*-
"""分层依赖与循环引用自动化机械闸 (Layer Invariants Gate)。

依据 docs/agents/architecture.md Layer 0~5 层序声明与 01-Rules/LAYERED-ARCHITECTURE.md：
  Layer 5 [运行装配层]: delector.routes, delector.server, static
  Layer 4 [工具接口层]: delector.tools
  Layer 3 [领域服务层]: delector.services
  Layer 2 [处理引擎层]: delector.nlp_engine
  Layer 1 [核心底座层]: delector.core
  Layer 0 [纯数据出口]: delector.data

判定口径：
  1. 顶层强双向循环依赖（A ⇄ B）：任两模块顶层互相直接 import 即为架构严重缺陷，一票否决；
  2. 严格单向层序：低层模块顶层严禁导入高层模块（例如 core 顶层禁导入 nlp_engine/services/tools/routes）；
  3. 受控豁免：允许行内或上一行带 `# layer-ok: <REASON>` 注释抑制，空理由视为无效豁免。
"""

from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, TextIO, Tuple

LAYER_HIERARCHY: Dict[str, int] = {
    "delector.data": 0,
    "delector.core": 1,
    "delector.nlp_engine": 2,
    "delector.services": 3,
    "delector.tools": 4,
    "delector.routes": 5,
    "delector.server": 5,
}

LAYER_NAMES: Dict[int, str] = {
    0: "Layer 0 [data]",
    1: "Layer 1 [core]",
    2: "Layer 2 [nlp_engine]",
    3: "Layer 3 [services]",
    4: "Layer 4 [tools]",
    5: "Layer 5 [routes/server]",
}


def get_module_layer(mod_name: str) -> Optional[int]:
    """根据模块名判定其所属层级。"""
    for prefix, layer in LAYER_HIERARCHY.items():
        if mod_name == prefix or mod_name.startswith(prefix + "."):
            return layer
    return None


class ImportSite(NamedTuple):
    source_mod: str
    target_mod: str
    file_path: Path
    line_no: int
    raw_line: str
    is_top_level: bool


def _find_py_files(delector_dir: Path) -> Dict[str, Path]:
    """扫描 delector/ 下全部 Python 模块，建立 模块全名 -> 物理路径 映射。"""
    modules: Dict[str, Path] = {}
    repo_root = delector_dir.parent
    for p in delector_dir.rglob("*.py"):
        rel = p.relative_to(repo_root)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            mod_name = ".".join(parts[:-1])
        else:
            parts[-1] = parts[-1][:-3]
            mod_name = ".".join(parts)
        modules[mod_name] = p
    return modules


def _resolve_target_module(raw_target: str, known_modules: Set[str]) -> Optional[str]:
    """将 import 目标解析到最长已知的 delector 内部模块名。"""
    if not raw_target.startswith("delector."):
        return None
    cur = raw_target
    while cur:
        if cur in known_modules:
            return cur
        if "." in cur:
            cur = cur.rsplit(".", 1)[0]
        else:
            break
    return None


class _ImportExtractor(ast.NodeVisitor):
    def __init__(self, current_mod: str, file_path: Path, known_modules: Set[str], lines: Sequence[str]):
        self.current_mod = current_mod
        self.file_path = file_path
        self.known_modules = known_modules
        self.lines = lines
        self.scope_depth = 0
        self.sites: List[ImportSite] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def _add_site(self, raw_target: str, line_no: int) -> None:
        tgt = _resolve_target_module(raw_target, self.known_modules)
        if tgt and tgt != self.current_mod:
            raw_line = self.lines[line_no - 1] if 0 < line_no <= len(self.lines) else ""
            self.sites.append(
                ImportSite(
                    source_mod=self.current_mod,
                    target_mod=tgt,
                    file_path=self.file_path,
                    line_no=line_no,
                    raw_line=raw_line.strip(),
                    is_top_level=(self.scope_depth == 0),
                )
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_site(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_str = node.module or ""
        if node.level > 0:
            cur_parts = self.current_mod.split(".")
            base = cur_parts[: -node.level]
            if module_str:
                base_str = ".".join(base + [module_str])
            else:
                base_str = ".".join(base)
        else:
            base_str = module_str

        targets_seen: Set[str] = set()
        for alias in node.names:
            sub = f"{base_str}.{alias.name}" if base_str else alias.name
            target = sub if sub in self.known_modules else base_str
            if target and target not in targets_seen:
                targets_seen.add(target)
                self._add_site(target, node.lineno)


def _check_exemption(file_path: Path, line_no: int) -> Optional[str]:
    """检查指定行（或前一行）是否有合法的 # layer-ok: <REASON> 豁免。"""
    try:
        content = file_path.read_text(encoding="utf-8")
        tokens = tokenize.tokenize(io.BytesIO(content.encode("utf-8")).readline)
        comments: Dict[int, str] = {}
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = tok.string
    except Exception:
        return None

    marker = "layer-ok:"
    for target_line in (line_no, line_no - 1):
        com = comments.get(target_line, "")
        if marker in com:
            idx = com.index(marker) + len(marker)
            reason = com[idx:].strip()
            if reason:
                return reason
    return None


class ScanViolation(NamedTuple):
    kind: str  # "CYCLE" or "REVERSE_LAYER"
    detail: str
    site: Optional[ImportSite] = None
    exempted: bool = False
    exemption_reason: str = ""


def scan_layers(delector_dir: Path) -> Tuple[List[ScanViolation], int]:
    """对 delector 目录执行分层与依赖分析。"""
    modules = _find_py_files(delector_dir)
    known = set(modules.keys())
    all_sites: List[ImportSite] = []

    for mod_name, path in modules.items():
        try:
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            tree = ast.parse(content)
            extractor = _ImportExtractor(mod_name, path, known, lines)
            extractor.visit(tree)
            all_sites.extend(extractor.sites)
        except Exception as e:
            sys.stderr.write(f"解析 {path} 失败: {e}\n")

    # 1. 顶层依赖邻接矩阵
    top_edges: Dict[str, Set[str]] = {m: set() for m in known}
    top_sites_by_pair: Dict[Tuple[str, str], ImportSite] = {}
    for site in all_sites:
        if site.is_top_level:
            top_edges[site.source_mod].add(site.target_mod)
            top_sites_by_pair[(site.source_mod, site.target_mod)] = site

    violations: List[ScanViolation] = []

    # 检查 1: 顶层强双向循环 (A ⇄ B)
    visited_pairs: Set[Tuple[str, str]] = set()
    for a in sorted(known):
        for b in sorted(top_edges[a]):
            if a in top_edges[b]:
                pair = (min(a, b), max(a, b))
                if pair not in visited_pairs:
                    visited_pairs.add(pair)
                    site_a = top_sites_by_pair.get((a, b))
                    reason_a = _check_exemption(site_a.file_path, site_a.line_no) if site_a else None
                    violations.append(
                        ScanViolation(
                            kind="CYCLE",
                            detail=f"顶层双向循环依赖: {a} <===> {b}",
                            site=site_a,
                            exempted=bool(reason_a),
                            exemption_reason=reason_a or "",
                        )
                    )

    # 检查 2: 顶层逆向跨层依赖 (低层 -> 高层)
    for site in all_sites:
        if not site.is_top_level:
            continue
        l_src = get_module_layer(site.source_mod)
        l_tgt = get_module_layer(site.target_mod)
        if l_src is not None and l_tgt is not None and l_src < l_tgt:
            reason = _check_exemption(site.file_path, site.line_no)
            violations.append(
                ScanViolation(
                    kind="REVERSE_LAYER",
                    detail=(
                        f"跨层逆向导入: {site.source_mod} ({LAYER_NAMES[l_src]}) 顶层导入了 "
                        f"{site.target_mod} ({LAYER_NAMES[l_tgt]}) at {site.file_path.name}:{site.line_no}"
                    ),
                    site=site,
                    exempted=bool(reason),
                    exemption_reason=reason or "",
                )
            )

    return violations, len(modules)


def run_gate(
    root: Path,
    report_only: bool = False,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    delector_dir = root / "delector"
    if not delector_dir.exists():
        print(f"[layer-gate] 错误：目录 {delector_dir} 不存在。", file=stderr)
        return 2

    violations, total_mods = scan_layers(delector_dir)
    unexempted = [v for v in violations if not v.exempted]

    print(
        f"[layer-gate] 扫描完成: {total_mods} 个模块; 发现 {len(violations)} 处潜在违规 "
        f"（已豁免 {len(violations) - len(unexempted)} 个, 未豁免 {len(unexempted)} 个）。",
        file=stdout,
    )

    for v in violations:
        if v.exempted:
            print(f"  [exempt] {v.detail} | 理由: {v.exemption_reason}", file=stdout)
        else:
            print(f"  [VIOLATION] [{v.kind}] {v.detail}", file=stderr)

    if report_only:
        print("[layer-gate] --report-only 模式，保持退出码 0", file=stdout)
        return 0

    if unexempted:
        print(f"[layer-gate] 失败: 存在 {len(unexempted)} 处未豁免的分层/循环依赖违规！", file=stderr)
        return 1

    print("[layer-gate] 通过: 全仓分层与依赖规范符合 100% 单向层序。", file=stdout)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")
        except ValueError:  # silent-ok: 仅显示层编码（流已关闭/不可重配置），失败时保持原流，不影响判定与退出码
            pass

    parser = argparse.ArgumentParser(description="DeLector 架构分层与循环依赖机械闸。")
    parser.add_argument("--root", type=Path, default=None, help="仓库根目录（默认上一级）")
    parser.add_argument("--report-only", action="store_true", help="只报告不拦截")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent if args.root is None else args.root
    return run_gate(root, report_only=bool(args.report_only))


if __name__ == "__main__":
    sys.exit(main())
