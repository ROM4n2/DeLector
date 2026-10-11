# -*- coding: utf-8 -*-
"""``save_wb_state`` 耗时拆解基准（P1-7：先量再改，决策依据）。

审计口径
--------
save_wb_state 单事务写 1MB blob + ``_pool_index`` 全表 SELECT + ~3k 条语句。
本脚本在真实规模（~1MB payload / 2979 words）下拆解三段：

======  ===============================================================  ====
段      测什么                                                            含义
======  ===============================================================  ====
blob    单独执行 wb_state 的 1MB upsert（不投影）                          I/O 下限
first   完整 save_wb_state（首次：~3k INSERT + 全表 SELECT）               首存
repeat  完整 save_wb_state（再次：幂等，几乎全 unchanged）                  日常保存
poolidx _pool_index 全表 SELECT 单独计时                                    投影前置成本
======  ===============================================================  ====

隔离纪律：tmp 库（[Instinct: Isolated-DB]），绝不打开真实库。

用法::

    export PYTHONIOENCODING=utf-8
    python tools/bench_save_wb_state.py          # 默认 2979 词 / ~1MB

输出契约（tests/test_save_wb_state_cost.py 断言）::

    payload_mb=...
    words=...
    segment_blob_ms=...
    segment_first_ms=...
    segment_repeat_ms=...
    segment_pool_index_ms=...
    verdict=...
"""

import json
import os
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DEFAULT_WORDS = 2979  # 审计实测规模


def _bootstrap_env(tmpdir: str) -> None:
    os.environ["DELECTOR_DATA_DIR"] = tmpdir
    os.environ["DATABASE_PATH"] = os.path.join(tmpdir, "bench_wb.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmpdir, "bench_wb_progress.db")


def _build_payload(words: int, rng: random.Random) -> Dict[str, Any]:
    """~1MB 的 wb 快照：2979 词（gloss/ex 撑体积）+ 对应 FSRS 卡。"""
    payload_words: List[Dict[str, Any]] = []
    cards: Dict[str, Any] = {}
    for i in range(words):
        wid = 100000 + i
        payload_words.append(
            {
                "id": wid,
                "hw": f"Wort{i}",
                "gloss": f"释义{i}：为了贴近真实 payload 体积而写的较长中文释义文本。",
                "ex": [{"de": f"Dies ist Beispielsatz Nummer {i} im Arbeitsbuch.", "zh": f"例句{i}。"}],
                "custom": True,
                "reps": rng.randint(0, 8),
                "lapses": rng.randint(0, 2),
            }
        )
        cards[str(wid)] = {
            "s": round(rng.uniform(0.5, 30.0), 3),
            "d": round(rng.uniform(1.0, 9.0), 3),
            "lapses": rng.randint(0, 2),
        }
    return {"words": payload_words, "cards": cards, "log": [], "wrong": [], "settings": {}}


def _median_ms(fn: Callable[[], None], rounds: int) -> float:
    samples: List[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    words = int(os.environ.get("BENCH_WB_WORDS", str(DEFAULT_WORDS)))
    rounds = int(os.environ.get("BENCH_ROUNDS", "5"))

    tmpdir = tempfile.mkdtemp(prefix="bench_wb_")
    _bootstrap_env(tmpdir)
    try:
        from delector.core.database import get_db, init_db, save_wb_state

        init_db()
        rng = random.Random(7)
        payload = _build_payload(words, rng)
        payload_mb = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / (1024 * 1024)

        # 段 blob：单独 upsert 1MB（不投影）——I/O 下限
        conn = get_db()

        def blob_only() -> None:
            conn.execute(
                "INSERT INTO wb_state (id, payload, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
                (json.dumps(payload, ensure_ascii=False), "bench"),
            )
            conn.commit()

        blob_ms = _median_ms(blob_only, rounds)
        conn.close()

        # 段 first：完整 save_wb_state（空池首次投影 ≈ 全 INSERT）
        # 注意每轮把投影产物清掉，让每轮都是"首存"形态
        def first_save() -> None:
            c = get_db()
            try:
                c.execute("DELETE FROM vocab_cards WHERE source != 'user' OR lemma LIKE 'wort%'")
                c.execute("DELETE FROM vocab_cards")
                c.commit()
            finally:
                c.close()
            save_wb_state(payload)

        first_ms = _median_ms(first_save, rounds)

        # 段 repeat：再次保存（幂等投影：几乎全 unchanged）
        def repeat_save() -> None:
            save_wb_state(payload)

        repeat_ms = _median_ms(repeat_save, rounds)

        # 段 poolidx：_pool_index 全表 SELECT 单独计时（此时池里已有 ~3k 行）
        conn = get_db()
        poolidx_ms = _median_ms(lambda: _run_pool_index(conn), rounds)
        conn.close()

        print(f"payload_mb={payload_mb:.2f}")
        print(f"words={words}")
        print(f"segment_blob_ms={blob_ms:.3f}")
        print(f"segment_first_ms={first_ms:.3f}")
        print(f"segment_repeat_ms={repeat_ms:.3f}")
        print(f"segment_pool_index_ms={poolidx_ms:.3f}")
        # 决策口径：repeat（日常保存路径）是否值得动。阈值取"可感知"量级（50ms），
        # 低于它改动的风险（事务语义/映射不变量）大于收益。
        verdict = "optimization_unnecessary" if repeat_ms < 50.0 else "worth_revisiting"
        print(f"verdict={verdict}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_pool_index(conn: sqlite3.Connection) -> None:
    from delector.core.vocab_pool import _pool_index

    _pool_index(conn)


if __name__ == "__main__":
    raise SystemExit(main())
