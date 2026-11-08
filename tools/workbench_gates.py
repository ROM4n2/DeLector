#!/usr/bin/env python3
"""workbench iframe 视觉闸门：字面量预算、亮/暗对比度、无定义引用、自引用。

为什么单独一套口径：`visual_gates.py` 只扫主站 `static/style.css`，而 workbench 是
独立 iframe，自带 `tokens.css` + `workbench.css`，并有一份 `[data-theme="dark"]` 暗色
重绑；它**不继承父级 `:root`**，所以暗色对比度必须按 workbench 自己的 token 解析，
不能复用主站亮色假设（`--wb-on-accent` 暗色曾只有 2.99，就是被漏掉的）。

四类闸（全部纯静态解析，不启浏览器）：

1. 字面量：规则体（`:root` / `[data-theme]` token 定义块之外）的 hex 次数与 rgba
   唯一值。上限**钉在实测值**上，只降不升。
2. 对比度：亮色与暗色两套；正文 >= 4.5，大字与图形 >= 3.0。
3. 无定义引用：`var(--x)` 用了但 workbench 作用域（tokens.css + workbench.css 的
   token 块）从未定义 `--x`；也扫 workbench.html 的行内 style 与脚本字符串。
4. 自引用：`--x: var(--x, ...)` 会静默变成 guaranteed-invalid，整条声明失效且不报错。

用法：
    python tools/workbench_gates.py
    python tools/workbench_gates.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import visual_gates as vg  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "static" / "css" / "tokens.css"
WORKBENCH_CSS = REPO_ROOT / "static" / "css" / "workbench.css"
WORKBENCH_HTML = REPO_ROOT / "static" / "german" / "workbench.html"

CSS_FILES = (TOKENS_CSS, WORKBENCH_CSS)

# 字面量硬顶：2026-11-08 首次实测值，只降不升（改进后必须同步下调）。
# workbench.css 唯一的规则体 rgba 是模态遮罩材质，见 docs/agents/visual-regression.md
# 的例外清单；token 块（:root / [data-theme]）与主站口径一致，不计入。
WB_HEX_BUDGET = 0
WB_RGBA_BUDGET = 1

_ATTR_BLOCK_RE = re.compile(r'\[data-theme\s*=\s*["\']dark["\']\]\s*\{')
_STYLE_ATTR_RE = re.compile(r'style\s*=\s*"([^"]*)"', re.I)
_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)")
_SELF_REF_RE = re.compile(r"(--[\w-]+)\s*:\s*var\(\s*\1\s*[,)]")

# (id, 前景 token, 背景 token, 角色, 阈值)。角色只影响文档说明，阈值全部纳入闸门。
CONTRAST_PAIRS: tuple[tuple[str, str, str, str, float], ...] = (
    # ── 正文（15px 及以下 / 非 WCAG「大字」）──
    ("ink-on-paper", "ink", "paper", "body", 4.5),
    ("ink-on-card", "ink", "paper-card", "body", 4.5),
    ("muted-on-paper", "muted", "paper", "body", 4.5),
    ("muted-on-card", "muted", "paper-card", "body", 4.5),
    ("muted-on-warm", "muted", "paper-warm", "body", 4.5),
    ("pencil-on-paper", "pencil", "paper", "body", 4.5),
    ("pencil-on-warm", "pencil", "paper-warm", "body", 4.5),
    ("ink-faint-on-paper", "ink-faint", "paper", "body", 4.5),
    ("accent-on-paper", "accent", "paper", "body", 4.5),
    ("accent-on-card", "accent", "paper-card", "body", 4.5),
    ("wb-accent-on-tint", "wb-accent-on-tint", "paper-tint", "body", 4.5),
    ("on-accent-on-accent", "wb-on-accent", "accent", "body", 4.5),
    ("on-accent-on-again", "wb-on-accent", "wb-again", "body", 4.5),
    ("good-on-good-soft", "wb-good", "wb-good-soft", "body", 4.5),
    ("hard-on-hard-soft", "wb-hard", "wb-hard-soft", "body", 4.5),
    ("again-on-again-soft", "wb-again", "wb-again-soft", "body", 4.5),
    ("paper-on-ink", "paper", "ink", "body", 4.5),
    # ── 图形（进度条、图例色块、2px 竖线）──
    ("accent-on-paper-graphic", "accent", "paper", "graphic", 3.0),
    ("good-on-paper-graphic", "wb-good", "paper", "graphic", 3.0),
    ("hard-on-paper-graphic", "wb-hard", "paper", "graphic", 3.0),
    ("moss-on-paper-graphic", "moss", "paper", "graphic", 3.0),
    ("again-on-card-graphic", "wb-again", "paper-card", "graphic", 3.0),
)


@dataclass
class GateResult:
    name: str
    ok: bool
    actual: Any
    budget: Any
    unit: str = ""
    detail: str = ""


def _block_ranges(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """返回匹配选择器之后花括号块的 [start, end) 区间。"""
    ranges: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        index = start
        while index < len(text):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    ranges.append((start, index + 1))
                    break
            index += 1
    return ranges


def token_blocks(text: str) -> list[tuple[int, int]]:
    """token 定义块：`:root` 与 `[data-theme="dark"]`（值是字面量，不计入预算）。"""
    return _block_ranges(text, vg._ROOT_RE) + _block_ranges(text, _ATTR_BLOCK_RE)


def parse_tokens(text: str, *, dark: bool) -> dict[str, str]:
    """解析 workbench 作用域的 token；dark=True 时叠加暗色重绑。"""
    text = vg.strip_comments(text)
    tokens: dict[str, str] = {}
    ranges = _block_ranges(text, vg._ROOT_RE)
    if dark:
        ranges += _block_ranges(text, _ATTR_BLOCK_RE)
    for start, end in ranges:
        body = text[start:end]
        for match in vg._TOKEN_RE.finditer(body):
            tokens[match.group(1)] = match.group(2).strip()
    return tokens


def resolve_scope_tokens(*, dark: bool) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for path in CSS_FILES:
        tokens.update(parse_tokens(path.read_text(encoding="utf-8"), dark=dark))
    return tokens


def count_hex(css_texts: Iterable[str], html_text: str | None = None) -> int:
    total = 0
    for text in css_texts:
        cleaned = vg.strip_comments(text)
        ranges = token_blocks(cleaned)
        total += sum(
            1 for match in vg._HEX_RE.finditer(cleaned) if not vg._inside(match.start(), ranges)
        )
    if html_text is not None:
        for style in _STYLE_ATTR_RE.findall(html_text):
            total += len(vg._HEX_RE.findall(style))
    return total


def _normalize_rgba(value: str) -> str:
    """统一字面量拼写，避免 `0.5` 与 `.5` 被当成两个唯一值虚增预算。"""
    compact = re.sub(r"\s+", "", value.lower())
    return re.sub(r"(?<=[,\(])0\.(?=\d)", ".", compact)


def unique_rgba(css_texts: Iterable[str], html_text: str | None = None) -> set[str]:
    values: set[str] = set()
    for text in css_texts:
        cleaned = vg.strip_comments(text)
        ranges = token_blocks(cleaned)
        for match in vg._RGBA_RE.finditer(cleaned):
            if not vg._inside(match.start(), ranges):
                values.add(_normalize_rgba(match.group(0)))
    if html_text is not None:
        for style in _STYLE_ATTR_RE.findall(html_text):
            for match in vg._RGBA_RE.finditer(style):
                values.add(_normalize_rgba(match.group(0)))
    return values


def defined_tokens() -> set[str]:
    names: set[str] = set()
    for path in CSS_FILES:
        text = vg.strip_comments(path.read_text(encoding="utf-8"))
        for start, end in token_blocks(text):
            names.update(match.group(1) for match in vg._TOKEN_RE.finditer(text[start:end]))
    return names


def undefined_in(text: str, defined: Iterable[str]) -> list[str]:
    """单份文本里引用了 `defined` 之外 token 的 `var(--x)`（去重排序）。"""
    known = set(defined)
    return sorted(
        {
            match.group(1)
            for match in _VAR_RE.finditer(vg.strip_comments(text))
            if match.group(1) not in known
        }
    )


def find_undefined_references() -> list[str]:
    """`var(--x)` 引用了 workbench 作用域里从未定义的 token。"""
    defined = defined_tokens()
    found: list[str] = []
    for path in (*CSS_FILES, WORKBENCH_HTML):
        text = path.read_text(encoding="utf-8")
        found.extend(f"{path.name}: var({name})" for name in undefined_in(text, defined))
    return sorted(set(found))


def self_references_in(text: str) -> list[str]:
    return sorted({match.group(1) for match in _SELF_REF_RE.finditer(vg.strip_comments(text))})


def find_self_references() -> list[str]:
    found: list[str] = []
    for path in CSS_FILES:
        text = path.read_text(encoding="utf-8")
        found.extend(f"{path.name}: {name}: var({name}, ...)" for name in self_references_in(text))
    return sorted(set(found))


def evaluate_contrast(*, dark: bool) -> list[dict[str, Any]]:
    tokens = resolve_scope_tokens(dark=dark)
    results: list[dict[str, Any]] = []
    for pair_id, fg, bg, role, threshold in CONTRAST_PAIRS:
        fg_raw = vg.resolve_token(f"--{fg}", tokens)
        bg_raw = vg.resolve_token(f"--{bg}", tokens)
        fg_rgb = vg._parse_color(fg_raw)
        bg_rgb = vg._parse_color(bg_raw)
        ratio = vg.contrast_ratio(fg_rgb, bg_rgb) if fg_rgb and bg_rgb else 0.0
        results.append(
            {
                "id": f"{'dark' if dark else 'light'}:{pair_id}",
                "foreground": fg,
                "background": bg,
                "role": role,
                "threshold": threshold,
                "ratio": round(ratio, 2),
                "ok": bool(ratio >= threshold),
                "resolved": {"foreground": fg_raw, "background": bg_raw},
            }
        )
    return results


def evaluate() -> dict[str, Any]:
    css_texts = [path.read_text(encoding="utf-8") for path in CSS_FILES]
    html_text = WORKBENCH_HTML.read_text(encoding="utf-8")
    hex_actual = count_hex(css_texts, html_text)
    rgba_actual = len(unique_rgba(css_texts, html_text))
    contrast = evaluate_contrast(dark=False) + evaluate_contrast(dark=True)
    undefined = find_undefined_references()
    self_refs = find_self_references()

    gates = [
        GateResult(
            name="hex literals outside token blocks",
            ok=hex_actual <= WB_HEX_BUDGET,
            actual=hex_actual,
            budget=WB_HEX_BUDGET,
            unit="occurrences",
        ),
        GateResult(
            name="unique rgba literals outside token blocks",
            ok=rgba_actual <= WB_RGBA_BUDGET,
            actual=rgba_actual,
            budget=WB_RGBA_BUDGET,
            unit="unique values",
        ),
        GateResult(
            name="contrast (light + dark)",
            ok=all(item["ok"] for item in contrast),
            actual=min(item["ratio"] for item in contrast) if contrast else 0.0,
            budget="正文 4.5 / 图形 3.0",
            detail=", ".join(
                f"{item['id']} {item['ratio']:.2f}<{item['threshold']}"
                for item in contrast
                if not item["ok"]
            )
            or "all light/dark pairs pass",
        ),
        GateResult(
            name="undefined var() references",
            ok=not undefined,
            actual=len(undefined),
            budget=0,
            unit="references",
            detail="; ".join(undefined) or "all references resolved in workbench scope",
        ),
        GateResult(
            name="self-referential custom properties",
            ok=not self_refs,
            actual=len(self_refs),
            budget=0,
            unit="declarations",
            detail="; ".join(self_refs) or "no --x: var(--x) declarations",
        ),
    ]
    return {
        "source": [str(path.relative_to(REPO_ROOT)) for path in CSS_FILES]
        + [str(WORKBENCH_HTML.relative_to(REPO_ROOT))],
        "gates": [asdict(gate) for gate in gates],
        "contrast": contrast,
        "undefined": undefined,
        "self_references": self_refs,
        "ok": all(gate.ok for gate in gates),
    }


def _print_report(report: dict[str, Any]) -> None:
    print("workbench 视觉闸门 — " + ", ".join(report["source"]))
    for gate in report["gates"]:
        status = "PASS" if gate["ok"] else "FAIL"
        print(f"[{status}] {gate['name']}: {gate['actual']} (预算 {gate['budget']})")
        if gate.get("detail"):
            print(f"       {gate['detail']}")
    print("对比度（亮色 / 暗色）：")
    for item in report["contrast"]:
        status = "PASS" if item["ok"] else "FAIL"
        print(
            f"  [{status}] {item['id']:<34} {item['ratio']:>5.2f} "
            f">= {item['threshold']} ({item['role']})"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeLector workbench iframe 视觉闸门")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    report = evaluate()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
