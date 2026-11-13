"""发布文档守卫：把「CHANGELOG 顺序 / README 三版 / Release 文案无 emoji」变成机械检查。

背景（2026-11-10）：`docs/agents/ops.md` 曾写「升序：接在最新版本条目之后」，而
`CHANGELOG.md` 实际是降序（最新在最上）—— 规程与文件自相矛盾，每次发版都要靠人记；
README 的「版本历史」表也可能随手工编辑越过 3 行；Release 文案模板曾引用 emoji 示例。

本脚本只读，检查四份「发布面」文档：

1. ``CHANGELOG.md``：版本头必须是 ``## vX.Y.Z - YYYY-MM-DD``；版本号严格降序、日期不增；
   版本之间用一行 ``---`` 分隔；最新版本块必须含 ``### 已知限制`` 与 ``### 回滚``；无 emoji。
2. ``README.md``：``## 版本历史`` 表格的数据行不超过 3 行（旧版只进 CHANGELOG）。
3. ``.github/release-notes-template.md``：无 emoji。
4. ``.github/workflows/build-release.yml``：正文无 emoji。

规则来源：``CHANGELOG.md`` 顶部 FORMAT RULES 注释与 ``docs/agents/ops.md`` 第 8/9 条；
改规则时三处同步（本脚本 docstring / CHANGELOG 注释 / ops.md）。

用法：``python tools/check_release_docs.py [--root <仓库根>]``；无违规 exit 0，有则 exit 1。
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 常见 emoji 区段：杂项符号（⚠ ✅ 等）、装饰符号（✨ 等）、dingbats、pictographs、变体选择符、ZWJ。
# 刻意不收箭头（U+2190-21FF）、带圈数字（U+2460-24FF）与几何/制表符（U+2500-25FF）：
# 它们在中文技术文档里是正文编号与排版符号，不是 emoji（CHANGELOG 用 ①②③ 做列表编号）。
_EMOJI_RE = re.compile("[\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\U0001F000-\U0001FAFF]")
# 允许的排版符号：本仓正文常用的箭头与中点，即便落在上面的码段里也不报。
_EMOJI_ALLOW = set("→←↑↓↔⇒⇔·—–…")

_VERSION_HEAD_RE = re.compile(r"^## v(\d+)\.(\d+)\.(\d+) - (\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class Violation:
    where: str
    message: str

    def render(self) -> str:
        return f"{self.where}: {self.message}"


def _emoji_hits(text: str) -> list[str]:
    hits: list[str] = []
    for ch in text:
        if ch in _EMOJI_ALLOW:
            continue
        if _EMOJI_RE.match(ch):
            hits.append(ch)
    return sorted(set(hits))


def _parse_versions(lines: list[str]) -> list[tuple[int, tuple[int, int, int], str, int]]:
    out: list[tuple[int, tuple[int, int, int], str, int]] = []
    for idx, line in enumerate(lines):
        m = _VERSION_HEAD_RE.match(line.strip())
        if m:
            out.append((idx, (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4), idx))
    return out


def _check_changelog(root: Path) -> list[Violation]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return [Violation("CHANGELOG.md", "文件缺失")]
    text = path.read_text(encoding="utf-8")
    lines = text.replace("\r\n", "\n").split("\n")
    violations: list[Violation] = []

    versions = _parse_versions(lines)
    if not versions:
        return [Violation("CHANGELOG.md", "未找到任何 `## vX.Y.Z - YYYY-MM-DD` 版本头")]

    # 降序：版本号严格递减、日期不增
    for prev, cur in zip(versions, versions[1:]):
        if cur[1] >= prev[1]:
            violations.append(
                Violation(
                    "CHANGELOG.md",
                    f"版本顺序不是严格降序：{prev[1]} 之后出现 {cur[1]}（最新必须在上）",
                )
            )
        if cur[2] > prev[2]:
            violations.append(
                Violation(
                    "CHANGELOG.md",
                    f"日期不是单调不增：{prev[2]} 之后出现 {cur[2]}",
                )
            )

    # 版本之间必须有 --- 分隔
    for _idx, ver, date, line_no in versions[1:]:
        j = line_no - 1
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        if j < 0 or lines[j].strip() != "---":
            violations.append(
                Violation(
                    "CHANGELOG.md",
                    f"v{'.'.join(map(str, ver))}（{date}）之前缺少一行 `---` 分隔",
                )
            )

    # 最新版本块必须含 已知限制 / 回滚
    first = versions[0][0]
    second = versions[1][0] if len(versions) > 1 else len(lines)
    head = "\n".join(lines[first:second])
    if "### 已知限制" not in head:
        violations.append(Violation("CHANGELOG.md", "最新版本块缺少 `### 已知限制（Known Limitations）`"))
    if "### 回滚" not in head:
        violations.append(Violation("CHANGELOG.md", "最新版本块缺少 `### 回滚（Rollback）`"))
    # FORMAT RULES 规则 2（2026-11-13 审计 P2 #14 补闸）：每版至少一个变更小节。
    # 只判**最新版本块**——规则 4 明确 v5.22.1 及更早的小节标题保留历史格式，
    # 对历史正文追判会把「不要为统一而重写历史」这条自己破掉。
    if not re.search(r"^###\s+(新增|修复|内部|文档)", head, re.MULTILINE):
        violations.append(
            Violation(
                "CHANGELOG.md",
                "最新版本块缺少 `### 新增/修复/内部/文档` 中至少一个变更小节（FORMAT RULES 规则 2）",
            )
        )

    hits = _emoji_hits(text)
    if hits:
        violations.append(Violation("CHANGELOG.md", f"包含 emoji：{''.join(hits)}"))

    return violations


def _check_readme(root: Path) -> list[Violation]:
    path = root / "README.md"
    if not path.is_file():
        return [Violation("README.md", "文件缺失")]
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## 版本历史")
    except StopIteration:
        return [Violation("README.md", "缺少 `## 版本历史` 节")]

    rows = 0
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or set(cells[0]) <= {":", "-", " "}:
            continue  # 表头分隔行
        if cells[0] in {"版本", ""}:
            continue  # 表头
        rows += 1
    if rows > 3:
        return [Violation("README.md", f"`## 版本历史` 表有 {rows} 行，超过 3 行上限（旧版只进 CHANGELOG）")]
    return []


def _check_plain_file(root: Path, rel: str) -> list[Violation]:
    path = root / rel
    if not path.is_file():
        return [Violation(rel, "文件缺失")]
    hits = _emoji_hits(path.read_text(encoding="utf-8"))
    if hits:
        return [Violation(rel, f"包含 emoji：{''.join(hits)}")]
    return []


def check(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(_check_changelog(root))
    violations.extend(_check_readme(root))
    violations.extend(_check_plain_file(root, ".github/release-notes-template.md"))
    violations.extend(_check_plain_file(root, ".github/workflows/build-release.yml"))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布文档守卫（CHANGELOG 顺序 / README 三版 / 无 emoji）")
    parser.add_argument("--root", default=".", help="仓库根目录")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = check(root)
    if violations:
        print(f"发布文档守卫失败：{len(violations)} 处", file=sys.stderr)
        for v in violations:
            print(f"  - {v.render()}", file=sys.stderr)
        print(
            "规则见 CHANGELOG.md 顶部 FORMAT RULES 注释与 docs/agents/ops.md 第 8/9 条。",
            file=sys.stderr,
        )
        return 1
    print("发布文档守卫通过：CHANGELOG 降序且结构完整、README 版本表 ≤3 行、发布面文档无 emoji。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
