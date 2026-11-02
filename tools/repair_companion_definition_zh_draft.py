# -*- coding: utf-8 -*-
"""【草案 · 默认不执行任何写操作】修复伴学生词卡的 definition_zh 错位数据。

背景：早期提议把读音/分音节写进了 definition_zh（中文释义位）。本轮已统一
「缺释义留空 + UI 显示待补充」的口径，历史数据只能经人工确认后修复。

允许运行的全部条件（缺一不可）：
1. 操作者已逐条核对候选行，确认 definition_zh 里确实是读音/分音节而非中文释义；
2. 已用 --backup 指定一个全新的备份路径（脚本会先整库复制，再动笔）；
3. 显式传入 --apply。缺省为 dry-run，只打印候选与计划改动，绝不写库。

用法（先只读预览）：
    python tools/repair_companion_definition_zh_draft.py --db /path/to/delector.db
确认无误并备份后才允许：
    python tools/repair_companion_definition_zh_draft.py --db /path/to/delector.db \
        --backup /path/to/delector.before-repair.db --apply

修复动作：把候选行的 definition_zh 置为空串（不是猜测中文释义），
让 UI 统一显示「待补充」，由学习者后续自行补全。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys

DEFAULT_IDS = (125, 126, 127, 128)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="目标 SQLite 数据库路径")
    parser.add_argument("--backup", help="--apply 时必填：整库备份输出路径，必须不存在")
    parser.add_argument("--apply", action="store_true", help="真正写库；缺省为 dry-run")
    parser.add_argument("--ids", default=",".join(str(i) for i in DEFAULT_IDS), help="候选行 id，逗号分隔")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    if not ids:
        print("没有候选 id，退出。")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, word, definition_zh FROM vocab_cards WHERE id IN ({marks}) AND source = 'companion'",
        ids,
    ).fetchall()
    print(f"候选 {len(rows)} 行（id: {ids}）：")
    for row in rows:
        print(f"  id={row['id']} word={row['word']!r} definition_zh={row['definition_zh']!r} -> ''")

    if not args.apply:
        print("\ndry-run：未写库。确认以上行确实为读音/分音节后，加 --backup 与 --apply 再运行。")
        conn.close()
        return 0

    if not args.backup:
        print("--apply 必须同时提供 --backup。", file=sys.stderr)
        conn.close()
        return 2

    shutil.copyfile(args.db, args.backup)
    print(f"已备份到 {args.backup}")
    with conn:
        conn.execute(
            f"UPDATE vocab_cards SET definition_zh = '' WHERE id IN ({marks}) AND source = 'companion'",
            ids,
        )
    print(f"已将 {len(rows)} 行 definition_zh 置空。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
