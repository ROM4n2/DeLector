#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""按批重算 / 回退 processed_json（``PROCESSED_JSON_VERSION`` 升级的维护工具）。

何时需要它
==========
应用内升级只做**按需惰性重算**（打开一篇旧文章才重算那一篇），启动路径不扫全表。
本工具用于维护者/高级用户主动把整库重算一遍，或把结果整体回退。

用法
====
::

    # 预览还有多少篇待重算（不加载模型、不写库）
    python tools/recompute_processed.py --dry-run

    # 按批重算（默认每批 20 篇；单篇一次事务）
    python tools/recompute_processed.py --batch-size 20

    # 只处理前 N 篇
    python tools/recompute_processed.py --limit 5

    # 从备份逐字回退（可先 --article-id 只回退一篇）
    python tools/recompute_processed.py --restore
    python tools/recompute_processed.py --restore --article-id 12

行为与安全边界
==============
- **单篇失败不中断整批**：``[FAIL]`` 后继续下一篇，退出码 1 提示有失败。
- **可中断 / 幂等**：每篇「备份 + UPDATE」在同一个事务里提交；已迁移行版本号已等于当前
  值 ⇒ 直接跳过。中途 Ctrl-C 后重跑即可续上，不会留下半写状态。
- **原始正文永不改写**：只读 ``raw_text``；生词卡 / 批注 / 讲义等其他表完全不碰。
- **旧结果可回退**：每次覆盖前把上一版 ``processed_json`` / ``stats_json`` 存进
  ``processed_json_backup``（见 ``delector/core/db/processed_migration.py``）。

回退注意（必须照做，否则会「回退后又被重算」）
==============================================
``--restore`` 写回的是**旧内容**，其版本号仍是旧值。若当前程序的
``PROCESSED_JSON_VERSION`` 仍是升级后的值，该文章**下次打开会再次被惰性迁移覆盖**。
完整回退 = ① 执行 ``--restore``；② 把 ``PROCESSED_JSON_VERSION`` 改回旧值并发布
（在发布前不要打开刚才回退的文章）。``raw_text`` 从未被修改，因此「重新导入一篇」也始终安全。

控制台输出只用 ASCII 标记（GBK 终端安全）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 导入期只碰路径常量，不加载模型（processor 的 nlp 是惰性代理）。
from delector.core.database import db_conn, get_db_path, init_db  # noqa: E402
from delector.core.db.processed_migration import (  # noqa: E402
    needs_migration,
    restore_article,
    write_migrated,
)
from delector.nlp_engine.processor import PROCESSED_JSON_VERSION, process_german_text  # noqa: E402

Processor = Callable[[str], Dict[str, Any]]


def _coerce_raw_text(raw: Any) -> str:
    """库里的 raw_text 容错成 str：BLOB（非 UTF-8）→ 有损解码；None → 空串。**只读不改库**。"""
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode("utf-8", errors="replace")
    if raw is None:
        return ""
    return raw if isinstance(raw, str) else str(raw)


def _parse_processed(text: Any) -> Any:
    try:
        return json.loads(text or "")
    except (TypeError, ValueError):
        return {}


def run_migration(
    db_path: Optional[str] = None,
    *,
    batch_size: int = 20,
    limit: int = 0,
    dry_run: bool = False,
    process: Optional[Processor] = None,
    out: Callable[[str], None] = print,
) -> Dict[str, int]:
    """按 id 分批扫描并按需重算；返回计数汇总。

    每篇一个独立事务（``db_conn`` 正常退出即提交、异常即回滚）；单篇异常被捕获后继续。
    ``limit`` 限制**命中陈旧**的篇数（不是扫描行数），0 表示不限制。
    """
    if batch_size < 1:
        raise ValueError("batch_size 必须 >= 1")
    target_path = get_db_path(db_path)
    init_db(target_path)  # 确保 processed_json_backup 存在（幂等）
    processor: Processor = process or process_german_text
    current = PROCESSED_JSON_VERSION

    counts = {"scanned": 0, "stale": 0, "migrated": 0, "skipped": 0, "failed": 0}
    last_id = 0
    hit_limit = False
    while not hit_limit:
        with db_conn(target_path) as conn:
            rows = conn.execute(
                "SELECT id, raw_text, processed_json, stats_json FROM articles "
                "WHERE id > ? ORDER BY id LIMIT ?",
                (last_id, batch_size),
            ).fetchall()
        if not rows:
            break
        for row in rows:
            last_id = int(row["id"])
            counts["scanned"] += 1
            old_pj = _parse_processed(row["processed_json"])
            if not needs_migration(old_pj, current):
                counts["skipped"] += 1
                continue
            counts["stale"] += 1
            if limit and counts["stale"] > limit:
                hit_limit = True
                counts["stale"] -= 1
                break
            if dry_run:
                out(f"[STALE] id={last_id} old_version={old_pj.get('version') if isinstance(old_pj, dict) else ''}")
                continue
            try:
                new_pj = processor(_coerce_raw_text(row["raw_text"]))
                with db_conn(target_path) as conn:
                    write_migrated(
                        conn,
                        last_id,
                        old_processed_json=row["processed_json"],
                        old_stats_json=row["stats_json"],
                        payload=new_pj,
                    )
                    conn.commit()
            except Exception as exc:  # 单篇失败不中断整批
                counts["failed"] += 1
                out(f"[FAIL] id={last_id} keep-old error={exc!r}")
                continue
            counts["migrated"] += 1
            out(f"[OK] id={last_id}")
    return counts


def run_restore(
    db_path: Optional[str] = None,
    *,
    article_id: Optional[int] = None,
    out: Callable[[str], None] = print,
) -> Dict[str, int]:
    """从 ``processed_json_backup`` 逐字写回；每篇一个事务，可中断、可重跑。"""
    target_path = get_db_path(db_path)
    init_db(target_path)
    if article_id is not None:
        ids = [int(article_id)]
    else:
        with db_conn(target_path) as conn:
            ids = [
                int(r["article_id"])
                for r in conn.execute("SELECT article_id FROM processed_json_backup ORDER BY article_id")
            ]
    restored = 0
    missing = 0
    for aid in ids:
        with db_conn(target_path) as conn:
            ok = restore_article(conn, aid)
        if ok:
            restored += 1
            out(f"[RESTORED] id={aid}")
        else:
            missing += 1
            out(f"[MISS] id={aid} no-backup")
    if restored:
        out(
            "WARN: restored rows still carry their old version; they will be re-migrated on next open "
            f"while PROCESSED_JSON_VERSION={PROCESSED_JSON_VERSION}. Revert the constant to complete rollback."
        )
    return {"restored": restored, "missing": missing}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="按批重算 / 回退 articles.processed_json")
    parser.add_argument("--db", default=None, help="主库路径（默认 DATABASE_PATH 或 DATA_DIR/delector.db）")
    parser.add_argument("--batch-size", type=int, default=20, help="每批扫描行数（默认 20）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少篇陈旧文章（0 = 不限）")
    parser.add_argument("--dry-run", action="store_true", help="只列出待重算文章，不加载模型、不写库")
    parser.add_argument("--restore", action="store_true", help="从备份逐字回退（与重算互斥）")
    parser.add_argument("--article-id", type=int, default=None, help="只处理/回退指定文章 id")
    args = parser.parse_args(argv)

    try:
        if args.restore:
            result = run_restore(args.db, article_id=args.article_id)
            print(f"restored={result['restored']} missing={result['missing']}")
            return 0 if result["missing"] == 0 else 1
        counts = run_migration(
            args.db,
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("interrupted; committed rows are kept, rerun to continue")
        return 130
    print(
        "scanned={scanned} stale={stale} migrated={migrated} skipped={skipped} failed={failed}".format(**counts)
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
