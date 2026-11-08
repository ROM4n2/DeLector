#!/usr/bin/env python3
"""computed-style 基线比对 / 更新。

矩阵脚本（`tools/visual_matrix.py`）会把 12 个关键控件的关键属性导出为 JSON；
本工具把当前导出与入库基线逐控件、逐属性比对，并指出「哪个控件哪个属性从什么变成什么」。

用法：
    python tools/visual_baseline.py compare --current _artifacts/.../computed-style.json
    python tools/visual_baseline.py update  --current _artifacts/.../computed-style.json

`update` 是**有意变更**的入口：先跑矩阵、人工确认截图与 diff，再更新基线并提交。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "tests" / "fixtures" / "visual" / "computed_style_baseline.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("controls"), dict):
        raise SystemExit(f"不是有效的 computed-style 基线：{path}")
    return data


def _properties(entry: dict[str, Any]) -> dict[str, str]:
    props = entry.get("properties")
    return props if isinstance(props, dict) else {}


def compare(
    baseline: dict[str, Any], current: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    """返回 (差异行, 缺失控件行, 新增控件行)。"""
    base_controls = baseline["controls"]
    curr_controls = current["controls"]
    diffs: list[str] = []
    missing: list[str] = []
    added: list[str] = []

    for key, base_entry in base_controls.items():
        if key not in curr_controls:
            missing.append(f"{key}（{base_entry.get('label', '')}）：当前导出缺失")
            continue
        curr_entry = curr_controls[key]
        base_props = _properties(base_entry)
        curr_props = _properties(curr_entry)
        label = base_entry.get("label", key)
        selector = base_entry.get("selector", "")
        for prop, old in base_props.items():
            if prop not in curr_props:
                missing.append(f"{key}.{prop}：当前导出缺失该属性")
                continue
            new = curr_props[prop]
            if new != old:
                diffs.append(
                    f"{key}（{label} / {selector}）.{prop}: {old!r} -> {new!r}"
                )
        for prop in curr_props:
            if prop not in base_props:
                added.append(f"{key}.{prop}：基线没有该属性（当前 {curr_props[prop]!r}）")

    for key, curr_entry in curr_controls.items():
        if key not in base_controls:
            added.append(f"{key}（{curr_entry.get('label', '')}）：基线没有该控件")

    return diffs, missing, added


def update(baseline_path: Path, current: dict[str, Any]) -> None:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    baseline_path.write_text(serialized, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="computed-style 基线比对 / 更新")
    parser.add_argument("command", choices=("compare", "update"))
    parser.add_argument("--current", type=Path, required=True, help="矩阵导出的当前 JSON")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="入库基线路径")
    args = parser.parse_args(argv)

    current = load_json(args.current)
    if args.command == "update":
        update(args.baseline, current)
        print(f"已更新基线：{args.baseline}")
        return 0

    baseline = load_json(args.baseline)
    diffs, missing, added = compare(baseline, current)
    if not (diffs or missing or added):
        print(f"computed-style 基线一致（{len(baseline['controls'])} 个控件）")
        return 0

    for line in diffs:
        print(f"[DIFF] {line}")
    for line in missing:
        print(f"[MISSING] {line}")
    for line in added:
        print(f"[EXTRA] {line}")
    print(
        f"\n判定失败：{len(diffs)} 处属性变化 / {len(missing)} 处缺失 / {len(added)} 处新增。"
        "\n若为有意变更：确认截图后执行 update 并提交基线。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
