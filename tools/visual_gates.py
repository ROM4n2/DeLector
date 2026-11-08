#!/usr/bin/env python3
"""P0 视觉闸门：颜色字面量预算、对比度、循环动画白名单。

所有数值都从当前 CSS **现算**，不读取手抄统计；阈值是产品约定：

- `static/style.css` 规则体（`:root` 以外）的 hex 字面量 <= 582
- `static/style.css` 的 rgba/rgb 唯一值 <= 118
- `static/**/*.css` 中 `animation*: ... infinite` 的循环动画 == 7
- 语义颜色对：正文 >= 4.5:1；大字与图形 >= 3:1

用法：
    python tools/visual_gates.py
    python tools/visual_gates.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "static" / "style.css"
STATIC_ROOT = REPO_ROOT / "static"

HEX_BUDGET = 582
RGBA_BUDGET = 118
INFINITE_BUDGET = 7

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_ROOT_RE = re.compile(r":root\s*\{")
_TOKEN_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGBA_RE = re.compile(r"rgba?\(\s*[^)]*\)", re.I)
_INFINITE_RE = re.compile(r"\binfinite\b")

# (id, 前景 token, 背景 token, 角色, 阈值, 是否纳入闸门)
# `advisory=True` 的项属于已登记的存量欠账（调研报告 §4），P0 只报告不阻断；
# P1 换皮必须把它们清零后移入闸门清单。
CONTRAST_PAIRS: tuple[tuple[str, str, str, str, float, bool], ...] = (
    ("ink-on-paper", "ink", "paper", "body", 4.5, False),
    ("ink-mute-on-paper", "ink-mute", "paper", "body", 4.5, False),
    ("pencil-on-paper", "pencil", "paper", "body", 4.5, False),
    ("paper-on-ink", "paper", "ink", "body", 4.5, False),
    ("white-on-accent", "paper-card", "accent", "body", 4.5, False),
    ("danger-on-paper", "danger", "paper", "body", 4.5, False),
    ("moss-on-paper", "moss", "paper", "body", 4.5, False),
    ("accent-on-paper", "accent", "paper", "large", 3.0, False),
    ("ink-on-mustard", "ink", "mustard", "large", 3.0, False),
    ("white-on-moss", "paper-card", "moss", "large", 3.0, False),
    ("ink-on-paper-graphic", "ink", "paper", "graphic", 3.0, False),
    ("muted-on-paper", "muted", "paper", "body", 4.5, True),
    ("ink-faint-on-paper", "ink-faint", "paper", "body", 4.5, True),
    ("coral-on-paper", "coral", "paper", "graphic", 3.0, True),
    ("white-on-coral", "paper-card", "coral", "large", 3.0, True),
    ("mustard-on-paper", "mustard", "paper", "graphic", 3.0, True),
)


@dataclass
class GateResult:
    name: str
    ok: bool
    actual: Any
    budget: Any
    unit: str = ""
    detail: str = ""


def strip_comments(text: str) -> str:
    return _COMMENT_RE.sub("", text)


def _root_ranges(text: str) -> list[tuple[int, int]]:
    """返回每个 :root 规则体的 [start, end) 区间（含花括号）。"""
    ranges: list[tuple[int, int]] = []
    for match in _ROOT_RE.finditer(text):
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


def _inside(pos: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in ranges)


def count_hex_outside_root(css: str) -> int:
    """规则体（`:root` token 定义之外）的 hex 字面量出现次数。"""
    text = strip_comments(css)
    roots = _root_ranges(text)
    return sum(1 for match in _HEX_RE.finditer(text) if not _inside(match.start(), roots))


def unique_rgba_values(css: str) -> set[str]:
    """全文件 rgba()/rgb() 唯一值（忽略空白、大小写与 0.5/.5 写法差异）。"""
    text = strip_comments(css)
    values = set()
    for match in _RGBA_RE.finditer(text):
        value = re.sub(r"\s+", "", match.group(0).lower())
        value = re.sub(r"(?<![\d.])0\.(\d+)", r".\1", value)
        values.add(value)
    return values


def count_infinite_animations(css_files: Iterable[Path]) -> int:
    """所有 CSS 中 `infinite` 循环动画声明数量（注释不计）。"""
    total = 0
    for path in css_files:
        text = strip_comments(path.read_text(encoding="utf-8"))
        total += len(_INFINITE_RE.findall(text))
    return total


def _parse_color(raw: str) -> tuple[int, int, int] | None:
    value = raw.strip().lower()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        if len(digits) != 6:
            return None
        try:
            return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return None
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,[^)]*)?\)", value)
    if not match:
        return None
    return tuple(int(float(part)) for part in match.groups())  # type: ignore[return-value]


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(part) for part in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    light, dark = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def parse_root_tokens(css: str) -> dict[str, str]:
    """读取所有 :root 块里的自定义属性；后声明覆盖先声明。"""
    text = strip_comments(css)
    tokens: dict[str, str] = {}
    for start, end in _root_ranges(text):
        body = text[start:end]
        for match in _TOKEN_RE.finditer(body):
            tokens[match.group(1)] = match.group(2).strip()
    return tokens


def resolve_token(name: str, tokens: dict[str, str], seen: set[str] | None = None) -> str:
    """解析 `var(--x)` 链；找不到就原样返回，交给调用方报错。"""
    seen = seen or set()
    if name in seen:
        return ""
    seen.add(name)
    if name not in tokens:
        return ""
    value = tokens[name]
    match = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", value)
    if not match:
        return value
    resolved = resolve_token(match.group(1), tokens, seen)
    if resolved:
        return resolved
    return (match.group(2) or "").strip()


def evaluate_contrast(css: str) -> list[dict[str, Any]]:
    tokens = parse_root_tokens(css)
    results: list[dict[str, Any]] = []
    for pair_id, fg, bg, role, threshold, advisory in CONTRAST_PAIRS:
        fg_raw = resolve_token(f"--{fg}", tokens)
        bg_raw = resolve_token(f"--{bg}", tokens)
        fg_rgb = _parse_color(fg_raw)
        bg_rgb = _parse_color(bg_raw)
        ratio = contrast_ratio(fg_rgb, bg_rgb) if fg_rgb and bg_rgb else 0.0
        results.append(
            {
                "id": pair_id,
                "foreground": fg,
                "background": bg,
                "role": role,
                "threshold": threshold,
                "advisory": advisory,
                "ratio": round(ratio, 2),
                "ok": bool(ratio >= threshold),
                "resolved": {"foreground": fg_raw, "background": bg_raw},
            }
        )
    return results


def evaluate(css_path: Path = STYLE_CSS, static_root: Path = STATIC_ROOT) -> dict[str, Any]:
    css = css_path.read_text(encoding="utf-8")
    css_files = sorted(static_root.rglob("*.css"))
    contrast = evaluate_contrast(css)
    gated = [item for item in contrast if not item["advisory"]]
    advisory = [item for item in contrast if item["advisory"]]

    gates = [
        GateResult(
            name="hex literals outside :root",
            ok=count_hex_outside_root(css) <= HEX_BUDGET,
            actual=count_hex_outside_root(css),
            budget=HEX_BUDGET,
            unit="occurrences",
        ),
        GateResult(
            name="unique rgba literals",
            ok=len(unique_rgba_values(css)) <= RGBA_BUDGET,
            actual=len(unique_rgba_values(css)),
            budget=RGBA_BUDGET,
            unit="unique values",
        ),
        GateResult(
            name="infinite animations",
            ok=count_infinite_animations(css_files) == INFINITE_BUDGET,
            actual=count_infinite_animations(css_files),
            budget=INFINITE_BUDGET,
            unit="declarations",
        ),
        GateResult(
            name="contrast",
            ok=all(item["ok"] for item in gated),
            actual=min(item["ratio"] for item in gated) if gated else 0.0,
            budget="正文 4.5 / 大字与图形 3.0",
            detail=", ".join(
                f"{item['id']} {item['ratio']:.2f}<{item['threshold']}"
                for item in gated
                if not item["ok"]
            )
            or "all gated pairs pass",
        ),
    ]
    return {
        "source": str(css_path.relative_to(REPO_ROOT)),
        "gates": [asdict(gate) for gate in gates],
        "contrast": contrast,
        "advisory_failures": [item for item in advisory if not item["ok"]],
        "ok": all(gate.ok for gate in gates),
    }


def _print_report(report: dict[str, Any]) -> None:
    print(f"视觉闸门 — {report['source']}")
    for gate in report["gates"]:
        status = "PASS" if gate["ok"] else "FAIL"
        print(f"[{status}] {gate['name']}: {gate['actual']} (预算 {gate['budget']})")
        if gate.get("detail"):
            print(f"       {gate['detail']}")
    print("对比度（纳入闸门）：")
    for item in report["contrast"]:
        if item["advisory"]:
            continue
        status = "PASS" if item["ok"] else "FAIL"
        print(
            f"  [{status}] {item['id']:<26} {item['ratio']:>5.2f} "
            f">= {item['threshold']} ({item['role']})"
        )
    if report["advisory_failures"]:
        print("对比度欠账（P0 只报告，P1 换皮必须清零）：")
        for item in report["advisory_failures"]:
            print(
                f"  [WARN] {item['id']:<26} {item['ratio']:>5.2f} "
                f"< {item['threshold']} ({item['role']})"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeLector P0 视觉闸门")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--style", type=Path, default=STYLE_CSS, help="CSS 文件路径")
    args = parser.parse_args(argv)

    report = evaluate(args.style)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
