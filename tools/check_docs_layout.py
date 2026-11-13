# -*- coding: utf-8 -*-
"""docs/ 目录归置机械闸。

为什么存在
----------
2026-11-08 ``docs/reviews/README.md`` 刚写明「专项技术调研归 ``docs/research/``」，
同日晚些时候仍有调研报告写进 ``docs/reviews/``，且长期未登记索引。约定只写在
README 里、没有机械检查 ⇒ 失守。本脚本把「归置声明」变成可判定的检查。

规则来源（MUST 与 README 原文一致；改 README 时同步改这里）
------------------------------------------------------------
- ``docs/README.md`` §分层 / §放置规则（速查）/ §命名豁免
- ``docs/reviews/README.md`` 顶部定位与分类表
- ``docs/research/README.md`` 顶部定位与分类表
- ``docs/adr/INDEX.md`` 顶部「新增 / 取代 / 废弃 ADR 时，同一 PR 更新本表」

检查项（全部机械可判）
----------------------
1. **顶层归属**：``docs/`` 顶层只允许 §分层 列出的目录与 ``*.md``；不得新开平行目录。
2. **命名与扩展名**：各目录文件名符合 README 明示的命名式，扩展名符合该目录产出类型。
3. **索引登记**：``reviews/`` / ``research/`` 下的文件（含子目录）必须在对应 README
   中以**文件名**登记；``adr/*.md`` 必须在 ``adr/INDEX.md`` 登记；顶层 ``*.md`` 必须
   在 ``docs/README.md`` 登记。新增文档不登记 ⇒ 红。
4. **白名单**：只豁免逐条列明的历史既成事实，条目 MUST 带理由；白名单失效（对应文件
   已不存在）本身判红，防止白名单腐烂后静默放行。

刻意不做的事
------------
不按关键词判断「这份报告该放 reviews 还是 research」——那是语义判断，机械闸只钉
「归置声明」（目录命名 + 索引登记）。一份调研报告放进 ``reviews/`` 仍能通过命名，
但 MUST 在 ``reviews/README.md`` 登记，登记时作者必须选择分类；未登记即红。

退出码
------
0 = 通过；1 = 有违规；2 = 配置/环境错误（白名单理由为空、docs 根或索引文件缺失等）。
照 ``tools/check_master_commit_scope.py`` 的 0/1/2 惯例。

只读：仅遍历 ``docs/`` 与读取 README/INDEX 文本，不写任何文件。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

#: docs/README.md §分层 列出的顶层目录（images/ 见白名单）。
TOP_LEVEL_DIRS: frozenset[str] = frozenset(
    {"plans", "specs", "adr", "reviews", "research", "agents"}
)

#: docs/README.md §分层 列出的顶层 *.md（README.md 自身是索引，不再要求登记）。
TOP_LEVEL_FILES: frozenset[str] = frozenset(
    {"README.md", "design-system.md", "svg-character-spec.md"}
)

#: docs/README.md §分层 的命名式（逐条对应，别在这里“放宽”）。
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
PLAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
DESIGN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+-design\.md$")
ADR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-adr-\d{4}-.+\.md$")
REVIEW_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+$")
RESEARCH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.(?:md|html|css|js)$")


class Exemption(NamedTuple):
    """白名单条目：``path`` 相对 docs 根；目录前缀以 ``/`` 结尾。"""

    path: str
    reason: str


#: 白名单：逐条列明、理由可追溯。新增条目前先问「能否改 README 让规则覆盖它」。
WHITELIST: tuple[Exemption, ...] = (
    Exemption(
        "plans/archive/workbench-scope-control-and-live-settings.md",
        "docs/README.md §命名豁免：早于 <日期>- 命名规则的既成事实，改名会打断引用",
    ),
    Exemption(
        "plans/archive/workbench-progress-server-sync.md",
        "docs/README.md §命名豁免：早于 <日期>- 命名规则的既成事实，改名会打断引用",
    ),
    Exemption(
        "plans/archive/workbench-core-words-mode.md",
        "docs/README.md §命名豁免：早于 <日期>- 命名规则的既成事实，改名会打断引用",
    ),
    Exemption(
        "plans/archive/plan-companion-mascot.md",
        "docs/README.md §命名豁免：早于 <日期>- 命名规则的既成事实，改名会打断引用",
    ),
    Exemption(
        "specs/2026-11-06-android-spacy-parity-spec.md",
        "docs/README.md 的设计稿命名式是 <日期>-<主题>-design.md；该文件随 ADR-0028 / "
        "PR #237 以 -spec.md 交付并被跨文件引用，改名收益不足以抵风险（人工判断项）",
    ),
    Exemption(
        "images/",
        "docs/README.md §分层未列 images/，但它是 README/FEATURES 引用的截图资产桶"
        "（既有目录，无文档索引语义）",
    ),
)


class Violation(NamedTuple):
    path: str
    message: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel_files(docs_root: Path) -> list[str]:
    """返回 docs 根下全部文件的 POSIX 相对路径（含未跟踪文件，便于本地自查）。"""
    return sorted(
        path.relative_to(docs_root).as_posix()
        for path in docs_root.rglob("*")
        if path.is_file()
    )


def _match_exemption(rel_path: str, whitelist: Sequence[Exemption]) -> Optional[Exemption]:
    """精确文件或目录前缀匹配白名单。"""
    for exemption in whitelist:
        if exemption.path.endswith("/"):
            if rel_path.startswith(exemption.path):
                return exemption
        elif rel_path == exemption.path:
            return exemption
    return None


def _check_whitelist_health(
    docs_root: Path, whitelist: Sequence[Exemption], files: Iterable[str]
) -> list[Violation]:
    """白名单 MUST 可解释且不腐烂：空理由 / 失效条目都判红。"""
    file_list = list(files)
    violations: list[Violation] = []
    for exemption in whitelist:
        if not exemption.reason.strip():
            violations.append(
                Violation(exemption.path, "白名单条目缺少理由（MUST 说明为何豁免）")
            )
            continue
        if exemption.path.endswith("/"):
            exists = (docs_root / exemption.path).is_dir() and any(
                rel.startswith(exemption.path) for rel in file_list
            )
        else:
            exists = (docs_root / exemption.path).is_file()
        if not exists:
            violations.append(
                Violation(
                    exemption.path,
                    "白名单条目已失效（对应文件不存在）：删除该条目，别让它继续静默放行",
                )
            )
    return violations


def _check_top_level(rel_path: str) -> list[Violation]:
    """docs/ 顶层只允许 README 列出的目录与文件名。"""
    parts = rel_path.split("/")
    if len(parts) == 1:
        if parts[0] not in TOP_LEVEL_FILES:
            return [
                Violation(
                    rel_path,
                    "docs/ 顶层只允许 docs/README.md §分层 列出的 *.md "
                    f"（{', '.join(sorted(TOP_LEVEL_FILES))}）；新文档请归入对应子目录",
                )
            ]
        return []
    if parts[0] not in TOP_LEVEL_DIRS:
        return [
            Violation(
                rel_path,
                f"docs/{parts[0]}/ 不在 docs/README.md §分层 列出的目录中"
                f"（{', '.join(sorted(TOP_LEVEL_DIRS))}）；禁止新开平行目录",
            )
        ]
    return []


def _require_registered(
    rel_path: str,
    index_rel: str,
    index_text: str,
    token: str,
    rule: str,
) -> list[Violation]:
    """文件 MUST 以 ``token`` 出现在索引文本中（精确文件名/目录名，不做模糊匹配）。"""
    if token in index_text:
        return []
    return [Violation(rel_path, f"未在 {index_rel} 登记（{rule}）")]


def _check_plans(rel_path: str, docs_root: Path) -> list[Violation]:
    parts = rel_path.split("/")
    if len(parts) > 3:
        return [Violation(rel_path, "plans/ 最多两层（plans/<日期>-<主题>.md 或 plans/archive/<文件>）")]
    if len(parts) == 3 and parts[1] != "archive":
        return [Violation(rel_path, "plans/ 下只允许 archive/ 子目录（docs/README.md §分层）")]
    if not rel_path.endswith(".md"):
        return [Violation(rel_path, "plans/ 只放 Markdown（docs/README.md §分层）")]
    if not PLAN_RE.match(parts[-1]):
        return [Violation(rel_path, "计划命名必须为 <日期>-<主题>.md（docs/README.md §放置规则 1）")]
    return []


def _check_specs(rel_path: str) -> list[Violation]:
    if not rel_path.endswith(".md"):
        return [Violation(rel_path, "specs/ 只放 Markdown 设计稿（docs/README.md §分层）")]
    if not DESIGN_RE.match(rel_path.split("/")[-1]):
        return [
            Violation(
                rel_path,
                "设计稿命名必须为 <日期>-<主题>-design.md（docs/README.md §分层 / §放置规则 2）",
            )
        ]
    return []


def _check_adr(rel_path: str, docs_root: Path) -> list[Violation]:
    name = rel_path.split("/")[-1]
    index_rel = "adr/INDEX.md"
    index_path = docs_root / index_rel
    if not index_path.is_file():
        return [Violation(rel_path, f"索引文件缺失：{index_rel}（规则来源不可用）")]
    if name == "INDEX.md":
        return []
    if not ADR_RE.match(name):
        return [
            Violation(
                rel_path,
                "ADR 命名必须为 <日期>-adr-XXXX-<主题>.md（docs/README.md §分层）",
            )
        ]
    return _require_registered(
        rel_path,
        index_rel,
        _read_text(index_path),
        name,
        "docs/adr/INDEX.md 顶部：新增 ADR 时同一 PR 更新本表",
    )


def _check_reviews(rel_path: str, docs_root: Path) -> list[Violation]:
    parts = rel_path.split("/")
    readme_rel = "reviews/README.md"
    readme_path = docs_root / readme_rel
    if not readme_path.is_file():
        return [Violation(rel_path, f"索引文件缺失：{readme_rel}（规则来源不可用）")]
    readme_text = _read_text(readme_path)
    name = parts[-1]
    if name == "README.md":
        return []
    if len(parts) == 2:
        if not name.endswith((".md", ".json")):
            return [Violation(rel_path, "reviews/ 只放 .md 报告与 .json 原始数据（docs/reviews/README.md）")]
        if not REVIEW_RE.match(name):
            return [Violation(rel_path, "reviews/ 文件名必须带 <日期>- 前缀（docs/README.md §放置规则 3）")]
        return _require_registered(
            rel_path,
            readme_rel,
            readme_text,
            name,
            "落位后必须在 reviews/README.md 补登分类索引",
        )
    if len(parts) == 3:
        subdir = parts[1]
        if not DATE_PREFIX_RE.match(subdir):
            return [Violation(rel_path, "reviews/ 子目录名必须带 <日期>- 前缀（如 <日期>-<主题>-images/）")]
        if subdir not in readme_text:
            return [
                Violation(
                    rel_path,
                    f"子目录 {subdir}/ 未在 {readme_rel} 登记（落位后必须补登分类索引）",
                )
            ]
        return []
    return [Violation(rel_path, "reviews/ 只允许一层资产子目录（reviews/<日期>-<主题>/<文件>）")]


def _check_research(rel_path: str, docs_root: Path) -> list[Violation]:
    parts = rel_path.split("/")
    readme_rel = "research/README.md"
    readme_path = docs_root / readme_rel
    if not readme_path.is_file():
        return [Violation(rel_path, f"索引文件缺失：{readme_rel}（规则来源不可用）")]
    if len(parts) != 2:
        return [Violation(rel_path, "research/ 不放子目录（docs/research/README.md）")]
    name = parts[-1]
    if name == "README.md":
        return []
    if not RESEARCH_RE.match(name):
        return [
            Violation(
                rel_path,
                "research/ 文件名必须为 <日期>-<主题>.{md,html,css,js}"
                "（docs/README.md §放置规则 4；原型与模板见 research README §五）",
            )
        ]
    return _require_registered(
        rel_path,
        readme_rel,
        _read_text(readme_path),
        name,
        "落位后必须在 research/README.md 补登分类索引",
    )


def _check_agents(rel_path: str) -> list[Violation]:
    parts = rel_path.split("/")
    if len(parts) != 2:
        return [Violation(rel_path, "agents/ 不放子目录（docs/README.md §分层）")]
    if not rel_path.endswith(".md"):
        return [Violation(rel_path, "agents/ 只放 Markdown 常青文档（docs/README.md §分层）")]
    return []


def _check_top_level_registration(rel_path: str, docs_root: Path) -> list[Violation]:
    readme_path = docs_root / "README.md"
    if not readme_path.is_file():
        return [Violation(rel_path, "索引文件缺失：README.md（规则来源不可用）")]
    name = rel_path.split("/")[-1]
    if name == "README.md":
        return []
    return _require_registered(
        rel_path,
        "README.md",
        _read_text(readme_path),
        name,
        "顶层 *.md 是跨领域常青规范，必须在 docs/README.md §分层 登记",
    )


def _classify(rel_path: str, docs_root: Path) -> list[Violation]:
    violations = _check_top_level(rel_path)
    if violations or "/" not in rel_path:
        return violations
    top = rel_path.split("/", 1)[0]
    if top == "plans":
        return _check_plans(rel_path, docs_root)
    if top == "specs":
        return _check_specs(rel_path)
    if top == "adr":
        return _check_adr(rel_path, docs_root)
    if top == "reviews":
        return _check_reviews(rel_path, docs_root)
    if top == "research":
        return _check_research(rel_path, docs_root)
    if top == "agents":
        return _check_agents(rel_path)
    return []


def check_docs(
    docs_root: Path = DOCS_ROOT, whitelist: Sequence[Exemption] = WHITELIST
) -> tuple[list[Violation], list[Exemption]]:
    """返回 (违规, 实际用到的白名单条目)。纯函数，便于测试。"""
    files = _rel_files(docs_root)
    violations = _check_whitelist_health(docs_root, whitelist, files)
    used: list[Exemption] = []
    for rel_path in files:
        exemption = _match_exemption(rel_path, whitelist)
        if exemption is not None:
            if exemption not in used:
                used.append(exemption)
            continue
        violations.extend(_classify(rel_path, docs_root))
        if "/" not in rel_path:
            violations.extend(_check_top_level_registration(rel_path, docs_root))
    return violations, used


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    docs_root: Optional[Path] = None,
    whitelist: Sequence[Exemption] = WHITELIST,
) -> int:
    parser = argparse.ArgumentParser(
        description="检查 docs/ 目录归置是否符合各目录 README 的约定。",
    )
    parser.add_argument(
        "--docs-root",
        default=str(DOCS_ROOT),
        help="docs 目录路径（默认仓库内 docs/，测试用）",
    )
    args = parser.parse_args(argv)
    root = docs_root if docs_root is not None else Path(args.docs_root)

    if not root.is_dir():
        print(f"[docs-layout] 环境不可用：docs 根不存在：{root}", file=sys.stderr)
        return 2
    if not (root / "README.md").is_file():
        print(
            f"[docs-layout] 环境不可用：缺少规则来源 {root / 'README.md'}",
            file=sys.stderr,
        )
        return 2
    for exemption in whitelist:
        if not exemption.reason.strip():
            print(
                f"[docs-layout] 配置错误：白名单 {exemption.path!r} 缺少理由",
                file=sys.stderr,
            )
            return 2

    violations, used = check_docs(root, whitelist)

    for exemption in used:
        print(
            f"[docs-layout][whitelist] {exemption.path} 豁免：{exemption.reason}",
            file=sys.stderr,
        )
    for violation in violations:
        print(f"[docs-layout] {violation.path}: {violation.message}", file=sys.stderr)

    checked = len(_rel_files(root))
    if violations:
        print(
            f"[docs-layout] FAIL：{len(violations)} 项违规（共检查 {checked} 个文件）",
            file=sys.stderr,
        )
        return 1
    print(f"[docs-layout] OK：{checked} 个文件，{len(used)} 条白名单豁免")
    return 0


if __name__ == "__main__":
    sys.exit(main())
