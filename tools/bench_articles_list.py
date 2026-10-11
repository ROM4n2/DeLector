# -*- coding: utf-8 -*-
"""``GET /api/articles`` 列表成本基准（P1-6：改前 / 方案 A / 方案 B 三段对比）。

为什么需要这个脚本
------------------
审计实测（dba 席）：列表查询捞出**整列** ``processed_json``（单篇 45–54KB），
却只交付 ~216B 的 ``stats``；无 LIMIT；2000 篇 ≈616ms，其中 Python 侧
``json.loads`` ≈511ms。列表成本随文章数 O(N×blob) 增长。本脚本在同一份合成库
（tmp 隔离、N 行 × ~36KB blob）上量三段：

======  ====================================================================  ====
段      测什么                                                                 差值含义
======  ====================================================================  ====
before  改前实现复刻：整列 SELECT（无 LIMIT）+ Python 逐行 ``json.loads``       基线
B       方案 B：SQLite JSON1 ``json_extract(processed_json,'$.stats')`` + LIMIT  不迁移
        schema，仍是 O(blob) I/O，省的是 Python 解析与网络传输
A       方案 A：``stats_json`` 投影列 + LIMIT（列已在造数时同步写好 + 回填）      结构性修复
======  ====================================================================  ====

口径诚实说明
------------
- before / B / A 用**同一份合成数据、同一个库文件**（B/A 只比 before 多一个
  ``stats_json`` 列；B 不读它，A 读它），同一进程内分轮计时取中位数。
- ``json.loads`` 的输入字节数被独立计数（``py_parse_bytes_*``）：这是"Python 侧
  解析成本"的**结构性**量（与机器主频无关），是门禁断言的依据——绝对毫秒会被
  CI 机器漂移打假红（[Instinct: Flaky-Aware]）。
- 方案 A 的回填成本（迁移时一次性 ``UPDATE ... SET stats_json =
  json_extract(...)``）单独计为 ``backfill_ms``，只出现在迁移时点，不在列表路径。
- **不跑 ANALYZE**：生产路径无人执行它，跑了会让计划偏乐观（与生产不一致）。

隔离纪律（[Instinct: Isolated-DB]）
----------------------------------
``tempfile.mkdtemp()`` + 三个环境变量在 import delector 前钉好，finally 里
``shutil.rmtree``。绝不打开仓库根真实 ``delector.db``。JSON1 可用性显式自检，
不可用 ⇒ 硬失败（不静默降级，否则 B 段数字会变成谎言）。

用法
----
::

    export PYTHONIOENCODING=utf-8
    python tools/bench_articles_list.py                 # 默认 2000 行 × 7 轮
    BENCH_ARTICLE_ROWS=8000 BENCH_ROUNDS=5 python tools/bench_articles_list.py

输出契约（tests/test_articles_list_cost.py 逐行断言，勿改格式）::

    rows=2000
    blob_kb=36
    list_limit=200
    segment_before_ms=...
    segment_A_ms=...
    segment_B_ms=...
    segment_A_p95_ms=...
    samples_segment_A_ms=...
    py_parse_bytes_before=...
    py_parse_bytes_after=...
    backfill_ms=...
    speedup_A=...
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
from typing import Any, Callable, Dict, List, Tuple

# 允许从任意 CWD 直接运行（同 tools/ 其余脚本约定）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (_REPO_ROOT,):
    if _path not in sys.path:
        sys.path.insert(0, _path)

DEFAULT_ROWS = 2000
DEFAULT_ROUNDS = 7
LIST_LIMIT = 200  # 与生产 list_articles 的默认 LIMIT 对齐，改一边必须同步另一边

CEFR = ("A1", "A2", "B1", "B2", "C1")
POS = ("NOUN", "VERB", "ADJ", "ADV", "PRON", "DET", "AUX")


def _bootstrap_env(tmpdir: str) -> None:
    """import delector 前钉三处路径（database.py 在导入期读 DATA_DIR 建 .cache/audio）。"""
    os.environ["DELECTOR_DATA_DIR"] = tmpdir
    os.environ["DATABASE_PATH"] = os.path.join(tmpdir, "bench_articles.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmpdir, "bench_progress.db")


def _synthetic_processed_json(i: int, rng: random.Random, target_blob_kb: int) -> str:
    """一条 ~target_blob_kb 的 processed_json：真实形状（version/sentences/stats）。

    句子数按目标体积反推：每 token 约 90B JSON，约 40 token/句 ⇒ 单句 ~3.6KB，
    10 句 ≈ 36KB。stats 保持真实体量（~200B）——它才是列表唯一消费的字段。
    """
    n_sentences = max(1, target_blob_kb * 1024 // 3600)
    sentences: List[Dict[str, Any]] = []
    for s in range(n_sentences):
        tokens = []
        for t in range(40):
            word = f"wort{i}_{s}_{t}"
            tokens.append(
                {
                    "id": t,
                    "text": word.capitalize(),
                    "lemma": word,
                    "pos": rng.choice(POS),
                    "cefr": rng.choice(CEFR),
                    "is_punct": False,
                    "morph": {"Case": "Nom", "Number": "Sing"},
                }
            )
        sentences.append(
            {
                "id": s,
                "text": " ".join(str(t["text"]) for t in tokens) + ".",
                "tokens": tokens,
                "topology": {"vf": tokens[0]["text"], "lk": "verb", "mf": []},
                "clause_tree": {"type": "main", "children": []},
            }
        )
    payload = {
        "version": "3.5.0",
        "sentence_count": n_sentences,
        "sentences": sentences,
        "stats": {
            "word_count": n_sentences * 40,
            "total_words": n_sentences * 40,
            "sentence_count": n_sentences,
            "cefr_percentages": {"A1": 42, "A2": 31, "B1": 18, "B2": 6, "C1": 3},
            "avg_sentence_len": 40,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_db(db_path: str, rows: int, blob_kb: int) -> None:
    """建库 + 灌 N 行合成数据（stats_json 列同步写——即方案 A 的落库形态）。"""
    from delector.core.database import init_db

    init_db(db_path)
    rng = random.Random(42)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        # 方案 A 的列自举：产品侧未落该列（改前基准）时脚本自己补，
        # 使基准在改动前后都能独立复跑（量测不依赖实现时序）。
        a_cols = [c[1] for c in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "stats_json" not in a_cols:
            conn.execute("ALTER TABLE articles ADD COLUMN stats_json TEXT")
        conn.execute("DELETE FROM articles")
        batch: List[Tuple[str, str, str]] = []
        for i in range(rows):
            pj = _synthetic_processed_json(i, rng, blob_kb)
            stats_json = json.dumps(json.loads(pj)["stats"], ensure_ascii=False)
            batch.append((f"Artikel {i}", pj, stats_json))
        conn.executemany(
            "INSERT INTO articles (title, raw_text, processed_json, stats_json, source_url) "
            "VALUES (?, ?, ?, ?, '')",
            [(t, pj[:512], pj, sj) for (t, pj, sj) in batch],
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 三段被测实现（before 逐字对齐改前的 routes/main.py::list_articles）
# --------------------------------------------------------------------------- #
def _run_before(conn: sqlite3.Connection) -> Tuple[float, int]:
    """改前实现：整列 SELECT（无 LIMIT）+ Python 逐行 json.loads。返回 (耗时秒, 解析字节数)。"""
    t0 = time.perf_counter()
    parsed_bytes = 0
    rows = conn.execute(
        "SELECT id, title, created_at, length(raw_text) as char_count, processed_json "
        "FROM articles ORDER BY id DESC"
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for r in rows:
        d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
        try:
            pj = json.loads(r["processed_json"])
            parsed_bytes += len(r["processed_json"])
            if not isinstance(pj, dict):
                d["stats"] = {}
            else:
                d["stats"] = pj.get("stats", {})
        except Exception:
            d["stats"] = {}
        result.append(d)
    elapsed = time.perf_counter() - t0
    # 消费 result：防止被优化掉（诚实计时，结果必须真的被构造）
    assert len(result) == conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return elapsed, parsed_bytes


def _run_plan_a(conn: sqlite3.Connection, limit: int) -> Tuple[float, int]:
    """方案 A：stats_json 投影 + LIMIT，Python 只解析 ~200B 的 stats_json。"""
    t0 = time.perf_counter()
    parsed_bytes = 0
    rows = conn.execute(
        "SELECT id, title, created_at, length(raw_text) as char_count, "
        "COALESCE(stats_json, json_extract(processed_json, '$.stats')) AS stats_json "
        "FROM articles ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for r in rows:
        d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
        raw = r["stats_json"]
        if raw:
            try:
                stats = json.loads(raw)
                parsed_bytes += len(raw)
                d["stats"] = stats if isinstance(stats, dict) else {}
            except Exception:
                d["stats"] = {}
        else:
            d["stats"] = {}
        result.append(d)
    elapsed = time.perf_counter() - t0
    assert len(result) == limit
    return elapsed, parsed_bytes


def _run_plan_b(conn: sqlite3.Connection, limit: int) -> Tuple[float, int]:
    """方案 B：SQL 侧 json_extract + LIMIT，不迁移 schema（仍读整 blob 由 C 侧裁剪）。"""
    t0 = time.perf_counter()
    parsed_bytes = 0
    rows = conn.execute(
        "SELECT id, title, created_at, length(raw_text) as char_count, "
        "json_extract(processed_json, '$.stats') AS stats_json "
        "FROM articles ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    result: List[Dict[str, Any]] = []
    for r in rows:
        d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
        raw = r["stats_json"]
        if raw:
            try:
                stats = json.loads(raw)
                parsed_bytes += len(raw)
                d["stats"] = stats if isinstance(stats, dict) else {}
            except Exception:
                d["stats"] = {}
        else:
            d["stats"] = {}
        result.append(d)
    elapsed = time.perf_counter() - t0
    assert len(result) == limit
    return elapsed, parsed_bytes


def _median_of(fn: Callable[[], Tuple[float, int]], rounds: int) -> Tuple[float, int]:
    samples: List[float] = []
    bytes_total = 0
    for _ in range(rounds):
        elapsed, parsed = fn()
        samples.append(elapsed * 1000.0)
        bytes_total = parsed
    return statistics.median(samples), bytes_total


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    rows = int(os.environ.get("BENCH_ARTICLE_ROWS", str(DEFAULT_ROWS)))
    rounds = int(os.environ.get("BENCH_ROUNDS", str(DEFAULT_ROUNDS)))
    blob_kb = int(os.environ.get("BENCH_BLOB_KB", "36"))

    tmpdir = tempfile.mkdtemp(prefix="bench_articles_")
    _bootstrap_env(tmpdir)
    db_path = os.path.join(tmpdir, "bench_articles.db")
    try:
        _build_db(db_path, rows, blob_kb)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # JSON1 自检：B 段依赖它，不可用必须硬失败（静默降级 = 造假数）。
            try:
                conn.execute("SELECT json_extract('{\"a\":1}', '$.a')").fetchone()
            except sqlite3.Error as exc:
                print(f"FAIL json1_unavailable: {exc}")
                return 2

            before_ms, py_bytes_before = _median_of(lambda: _run_before(conn), rounds)
            a_ms, py_bytes_after = _median_of(lambda: _run_plan_a(conn, LIST_LIMIT), rounds)
            b_ms, _ = _median_of(lambda: _run_plan_b(conn, LIST_LIMIT), rounds)

            # 方案 A 的迁移一次性回填成本（单独口径：不在列表路径上）
            t0 = time.perf_counter()
            conn.execute(
                "UPDATE articles SET stats_json = json_extract(processed_json, '$.stats') "
                "WHERE stats_json IS NULL"
            )
            conn.commit()
            backfill_ms = (time.perf_counter() - t0) * 1000.0

            # p95 与样本行（与 bench_cards_endpoint 同纪律：可复核）
            a_samples: List[float] = []
            for _ in range(rounds):
                elapsed, _ = _run_plan_a(conn, LIST_LIMIT)
                a_samples.append(elapsed * 1000.0)
            p95 = statistics.quantiles(sorted(a_samples), n=100, method="inclusive")[94]

            print(f"rows={rows}")
            print(f"blob_kb={blob_kb}")
            print(f"list_limit={LIST_LIMIT}")
            print(f"segment_before_ms={before_ms:.3f}")
            print(f"segment_A_ms={a_ms:.3f}")
            print(f"segment_B_ms={b_ms:.3f}")
            print(f"segment_A_p95_ms={p95:.3f}")
            print("samples_segment_A_ms=" + ",".join(f"{s:.3f}" for s in a_samples))
            print(f"py_parse_bytes_before={py_bytes_before}")
            print(f"py_parse_bytes_after={py_bytes_after}")
            print(f"backfill_ms={backfill_ms:.3f}")
            print(f"speedup_A={before_ms / a_ms:.1f}x")
            print("verdict=" + (
                "A_decouples_list_from_article_count"
                if a_ms < before_ms and py_bytes_after < py_bytes_before
                else "NO_IMPROVEMENT"
            ))
            return 0
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
