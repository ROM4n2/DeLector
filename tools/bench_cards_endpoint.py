# -*- coding: utf-8 -*-
"""`GET /api/cards` 成本构成基准（子计划 2 / Task 1）。

为什么需要这个脚本
------------------
审计 dba 座在 20k 行上实测：`SELECT * FROM vocab_cards ORDER BY mastered ASC,
wrong_count DESC, id DESC` 的 EXPLAIN 是
`SCAN vocab_cards USING INDEX idx_vocab_srs` + **`USE TEMP B-TREE FOR RIGHT PART OF
ORDER BY`**（右段 `wrong_count DESC, id DESC` 无索引可用），SQLite 侧 93.8 ms。

但 **93.8 ms 里 filesort 到底占多少，未知**。因为同一次请求里还叠着三笔开销：
``SELECT *``（19+ 列 ⇒ 必然逐行回表）、``dict(r)`` 物化 2 万个 dict、以及**逐卡
``get_fsrs_next_intervals``**（2 万卡 = 8 万次 `_calc_fsrs_step` 递推 + 8 万次
``datetime.now()``）。**不拆开就没法回答"要不要加 idx_vocab_list"** ——
若 FSRS 递推占大头，加索引的收益上限就被死死压住。

四段分解（**同一份数据、同一连接**）
--------------------------------
======  ====================================================  ==========================
段     测什么                                                  差值含义
======  ====================================================  ==========================
A      ``SELECT id ... ORDER BY``（走覆盖索引 + filesort）        基线
B      ``SELECT * ... ORDER BY``（A + 逐行回表全列）            B−A = 多列回表成本
C      ``SELECT *``（无 ORDER BY，整表顺序扫）                  B−C = **排序 filesort 成本**
D      完整 ``get_cards()``（含 dict(r) 物化 + 逐卡 FSRS 递推）    D−B = Python 物化 + FSRS
======  ====================================================  ==========================

口径诚实说明
------------
- A/B/C 按计划只打 ``vocab_cards``；``get_cards()``（段 D）**同时**读
  ``vocab_cards`` 与 ``grammar_cards``。故 ``filesort_pct``（排序占端点总耗时）是
  **下界**——真实 vocab:grammar 比例下 grammar 段会稀释分母。grammar 按 realistic
  比例 N/4 灌（段 D 确实含它，且它自己也有同样的 filesort）。
- ``filesort_pct_of_sqlite`` = (B−C)/B，是"**加索引最多能省下多少**"的上限
  （索引只能消掉 filesort，消不掉回表与 Python 侧开销）。
- ``python_pct`` = (D−B)/D，与 ``filesort_pct`` **同分母**（都是端点总耗时 D），
  故两者可直接横向比大小。它是 ADR-0018 §6 判定门的输入：Python 侧占比 > 50%
  才够格进入"热点下沉"评估；反过来它也给出**查询侧优化的收益上限**。
- **不跑 ``ANALYZE``**：本仓生产路径无人执行它（`grep ANALYZE` 零命中），跑了
  反而让 SQLite 拿到生产环境没有的统计信息，测出来的计划偏乐观。故与生产一致。

隔离纪律（`[Instinct: Isolated-DB]`）
------------------------------------
``tempfile.mkdtemp()`` + ``DATABASE_PATH`` / ``PROGRESS_DB_PATH`` / ``DELECTOR_DATA_DIR``
三个环境变量**在 import delector 之前**设好（``database.py`` 在导入期就读
``DATA_DIR`` 建 ``.cache/audio``），``finally`` 里 ``shutil.rmtree`` 清理。
**绝不打开仓库根的真实 ``delector.db``**（桌面端用户数据）。

用法
----
::

    export PYTHONIOENCODING=utf-8
    python tools/bench_cards_endpoint.py                    # 1k / 20k / 50k
    BENCH_SCALES=8000 BENCH_ROUNDS=5 python tools/bench_cards_endpoint.py   # 门禁快档

输出契约（``tests/test_cards_endpoint_cost.py`` 逐行断言，勿改格式）::

    segment_A_ms=1.234
    segment_B_ms=...
    segment_C_ms=...
    segment_D_ms=...
    filesort_pct=NN.N%
    python_pct=NN.N%
    per_row_us=NN.NN
    python_verdict=<可判定区间结论：只报 ADR-0018 §6 的条件①，非路线裁决>
"""

import os
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Tuple

# 允许从任意 CWD 直接 `python tools/bench_cards_endpoint.py` 运行（同 tools/ 其余脚本约定）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 段 A/B/C 的 SQL。**字面量**取自 delector/routes/main.py::get_cards（逐字对齐，
# 改这里等于改被测对象，必须同步改生产码并重跑本基准）。
SQL_A = "SELECT id FROM vocab_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
SQL_B = "SELECT * FROM vocab_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
SQL_C = "SELECT * FROM vocab_cards"

# 段标签 → 供测试正则 `^segment_[ABCD]_ms=` 抓取。
SEGMENT_LABELS = ("segment_A", "segment_B", "segment_C", "segment_D")

DEFAULT_SCALES = (1000, 20000, 50000)
MIN_ROUNDS = 5  # 取中位数而非均值；少于 5 轮噪声压不住（[Instinct: Median-Not-Mean]）

CEFR = ("A1", "A2", "B1", "B2", "C1")
POS = ("NOUN", "VERB", "ADJ", "ADV", "PRON", "PREP", "CONJ")
GENDER = ("Masc", "Fem", "Neut", "None")
PLURAL = ("-e", "-en", "-er", "-ung", "-heit", "-")
POSITIONS = ("Hauptwort", "Zeitform", "Adjektiv", "Nebensatz", "Verweis", "Konjunktion")


# --------------------------------------------------------------------------- #
# 环境准备：必须在 import delector 之前完成
# --------------------------------------------------------------------------- #
def _env_scales() -> List[int]:
    raw = os.environ.get("BENCH_SCALES", "").strip()
    if not raw:
        return list(DEFAULT_SCALES)
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


def _env_rounds() -> int:
    raw = os.environ.get("BENCH_ROUNDS", "").strip()
    if not raw:
        return 7
    return max(MIN_ROUNDS, int(raw))


def _bootstrap_env(tmpdir: str) -> Dict[str, str]:
    """把三处库/缓存路径全部钉进 tmpdir，返回要写回 os.environ 的键值。

    ``DELECTOR_DATA_DIR`` 必须一起设：``delector/core/database.py`` 在**导入期**就
    用它算 ``AUDIO_CACHE_DIR`` 并 ``makedirs``，只设 ``DATABASE_PATH`` 的话脚本仍会
    在仓库根创建 ``.cache/audio``（违反隔离纪律）。
    """
    env = {
        "DELECTOR_DATA_DIR": tmpdir,
        "DATABASE_PATH": os.path.join(tmpdir, "bench_delector.db"),
        "PROGRESS_DB_PATH": os.path.join(tmpdir, "bench_progress.db"),
    }
    os.environ.update(env)
    return env


# --------------------------------------------------------------------------- #
# 造数（[Instinct: Realistic-Data]）
# --------------------------------------------------------------------------- #
def _vocab_rows(n: int, rng: random.Random) -> List[Tuple[Any, ...]]:
    """N 行 vocab_cards，分布贴近真实使用。

    关键：**MUST NOT 全 0 值**。``wrong_count`` 全 0 ⇒ ORDER BY 右段排序键退化
    （SQLite 少排一半比较，filesort 成本被严重低估）；``mastered`` 全 0 同理。
    故：``mastered`` 约 80% 为 0；``wrong_count`` 约 55% 为 0、其余 1..6；
    ``correct_count`` / ``interval_days`` / ``repetition_count`` / FSRS 三列全填非空。
    """
    rows: List[Tuple[Any, ...]] = []
    for i in range(n):
        mastered = 1 if rng.random() < 0.20 else 0
        rows.append(
            (
                rng.randint(1, 400),  # article_id
                f"Wort{i}",  # word
                f"lemma{i}",  # lemma
                rng.choice(POS),
                rng.choice(GENDER),
                rng.choice(PLURAL),
                rng.choice(CEFR),
                f"释义{i}（中文对照，说明较长以贴近真实行宽）",  # definition_zh
                f"Der Satz Nummer {i} ist ein Beispiel für den Gebrauch im Alltag.",  # sentence_context
                mastered,
                f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)} 09:{rng.randint(10, 59)}:00" if mastered else None,
                rng.randint(0, 24) if mastered else rng.randint(0, 9),  # correct_count
                0 if rng.random() < 0.55 else rng.randint(1, 6),  # wrong_count
                f"2026-10-{rng.randint(10, 28)}",  # due_date
                1 if rng.random() < 0.30 else rng.choice((2, 3, 5, 8, 15, 30, 90, 180)),  # interval_days
                round(rng.uniform(1.3, 3.2), 2),  # ease_factor
                rng.randint(0, 6),  # repetition_count
                rng.choice(("official", "manual", "ai", "user")),  # source
                round(rng.uniform(1.0, 10.0), 2),  # fsrs_s
                round(rng.uniform(0.0, 10.0), 2),  # fsrs_d
                rng.randint(0, 3),  # fsrs_lapses
            )
        )
    return rows


def _grammar_rows(n: int, rng: random.Random) -> List[Tuple[Any, ...]]:
    """N 行 grammar_cards。同样按 realistic 分布灌（段 D 会一并读它）。"""
    rows: List[Tuple[Any, ...]] = []
    for i in range(n):
        mastered = 1 if rng.random() < 0.20 else 0
        rows.append(
            (
                rng.randint(1, 400),  # article_id
                f"Der Satz {i} zeigt eine typische Struktur.",  # sentence_context
                rng.choice(POSITIONS),  # grammar_name
                rng.choice(CEFR),
                f"语法点 {i} 的中文讲解：一句话说明规则本身",  # explanation_zh
                "Satz + Verb + Objekt",  # rule_formula
                f"示例{i}：用于说明该语法点的中文对照例句。",  # examples_zh
                f"Der Satz {i} ist korrigiert.",  # corrected_form
                rng.choice(("", "Konjunktiv", "Passiv", "Tempus")),  # error_type
                mastered,
                f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)} 09:{rng.randint(10, 59)}:00" if mastered else None,
                rng.randint(0, 20) if mastered else rng.randint(0, 8),
                0 if rng.random() < 0.55 else rng.randint(1, 6),
                f"2026-10-{rng.randint(10, 28)}",
                1 if rng.random() < 0.30 else rng.choice((2, 3, 5, 8, 15, 30, 90)),
                round(rng.uniform(1.3, 3.2), 2),
                rng.randint(0, 6),
            )
        )
    return rows


_VOCAB_COLS = (
    "article_id, word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context, "
    "mastered, mastered_at, correct_count, wrong_count, due_date, interval_days, ease_factor, "
    "repetition_count, source, fsrs_s, fsrs_d, fsrs_lapses"
)
_GRAMMAR_COLS = (
    "article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula, "
    "examples_zh, corrected_form, error_type, mastered, mastered_at, correct_count, wrong_count, "
    "due_date, interval_days, ease_factor, repetition_count"
)


def _fill(db_path: str, n_vocab: int, n_grammar: int, seed: int) -> None:
    """清空两表并按 realistic 分布灌入给定行数（同一 db 文件，逐规模覆写）。"""
    rng = random.Random(seed)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("DELETE FROM vocab_cards")
        conn.execute("DELETE FROM grammar_cards")
        if n_vocab:
            conn.executemany(
                f"INSERT INTO vocab_cards ({_VOCAB_COLS}) VALUES ({','.join('?' * 21)})",
                _vocab_rows(n_vocab, rng),
            )
        if n_grammar:
            conn.executemany(
                f"INSERT INTO grammar_cards ({_GRAMMAR_COLS}) VALUES ({','.join('?' * 17)})",
                _grammar_rows(n_grammar, rng),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 计时（[Instinct: Median-Not-Mean]）
# --------------------------------------------------------------------------- #
def _median_ms(fn: Callable[[], Any], rounds: int) -> float:
    """跑 rounds 轮，返回**中位数**毫秒。

    刻意不用均值：单轮会被 GC / 磁盘 / 页面缓存污染，均值把这些尖峰摊进结果里，
    差值（B−C 这种小差）就会失真。中位数对单侧尖峰不敏感。
    """
    samples: List[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return float(statistics.median(samples))


def _bench_scale(
    db_path: str, n_vocab: int, n_grammar: int, rounds: int, get_cards: Callable[[], Any]
) -> Dict[str, Any]:
    """跑完四段计时，返回各段中位数 + 差值 + 占比 + EXPLAIN 证据。"""
    conn = sqlite3.connect(db_path)
    try:
        plan: List[str] = [
            str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN " + SQL_B).fetchall()
        ]
        a = _median_ms(lambda: conn.execute(SQL_A).fetchall(), rounds)
        b = _median_ms(lambda: conn.execute(SQL_B).fetchall(), rounds)
        c = _median_ms(lambda: conn.execute(SQL_C).fetchall(), rounds)
    finally:
        conn.close()
    # 段 D 走生产码 get_cards() 自身开连接（与真实请求同路径），不复用上面的连接。
    d = _median_ms(get_cards, rounds)

    filesort_ms = b - c
    return {
        "n_vocab": n_vocab,
        "n_grammar": n_grammar,
        "A": a,
        "B": b,
        "C": c,
        "D": d,
        "lookup_ms": b - a,  # 多列回表
        "filesort_ms": filesort_ms,
        "python_ms": d - b,  # dict(r) 物化 + 逐卡 FSRS 递推
        "filesort_pct": filesort_ms / d * 100.0 if d > 0 else 0.0,
        "filesort_pct_of_sqlite": filesort_ms / b * 100.0 if b > 0 else 0.0,
        # 与 filesort_pct 同分母（端点总耗时 D）：两者可直接横向比大小，回答
        # "优化该砸在 SQLite 侧还是 Python 侧"。
        "python_pct": (d - b) / d * 100.0 if d > 0 else 0.0,
        "plan": plan,
    }


def _verdict(pct: float) -> str:
    """按计划 Fog 1 的阈值给**可判定**结论（[Instinct: No-Silent-Conclusion]）。"""
    if pct > 50.0:
        return "加索引（filesort 占比 > 50%，idx_vocab_list 值得建，预期消除 USE TEMP B-TREE）"
    if pct < 30.0:
        return "不加索引（filesort 占比 < 30%，索引收益上限被回表 + Python 侧开销压死，写代价不划算）"
    return "中间区间（30%~50%），需另带写代价评估后再定"


def _python_verdict(pct: float) -> str:
    """Python 侧占比的可判定结论（ADR-0018 §6 判定门的**条件①**输入）。

    沿用 `_verdict()` 的"可判定区间"风格：只报占比不给建议等于把判定的活推回给读
    者。阈值沿用同一套 50% / 30% 分档，因为两侧是**同分母**竞争关系——此消彼长，
    用同一把尺子才能直接比。

    措辞纪律（**勿改**，越权即误判）：本函数**只报条件①，不下路线裁决**。
    ADR-0018 §6 的门是**双条件 AND**：① Python CPU 占比 > 50%；② p95 > 2 倍目标。
    本脚本只供 ①（占比），② 必须等 Task 5 的分层剖析才能判定 —— 二者 AND 成立才
    走热点下沉。故 >50% 分支 MUST NOT 写成"走热点下沉"：那会让 Task 6 回填 ADR 时
    把它误当成最终结论。三个分支一律给"区间 + 建议"，不给定稿。
    """
    if pct > 50.0:
        return (
            "满足条件①（Python 侧占比 > 50%）；条件②（p95 > 2 倍目标）待分层剖析"
            "（Task 5）判定 —— 二者 AND 才走热点下沉，此处不下路线结论"
        )
    if pct < 30.0:
        return (
            "不满足条件①（Python 侧占比 < 30%）：瓶颈仍在 SQLite 查询侧，"
            "建议先优化查询侧再谈下沉（条件②仍待 Task 5，此处不下路线结论）"
        )
    return (
        "中间区间（30%~50%），条件①不成立：建议先压低占比更高的那一侧再复测"
        "（条件②仍待 Task 5，此处不下路线结论）"
    )


def main() -> int:
    scales = _env_scales()
    rounds = _env_rounds()
    tmpdir = tempfile.mkdtemp(prefix="delector_bench_cards_")
    try:
        _bootstrap_env(tmpdir)
        # 延迟导入：必须在 _bootstrap_env 之后，否则 database.py 会在仓库根建 .cache/audio。
        from delector.core.database import db_conn, init_db  # noqa: PLC0415
        from delector.routes.main import get_cards  # noqa: PLC0415

        db_path = os.environ["DATABASE_PATH"]
        init_db(db_path)  # 建表 + 建**生产那套**索引（idx_vocab_srs 等），保证测的是真 schema
        with db_conn(db_path) as conn:
            idx = [r["name"] for r in conn.execute("PRAGMA index_list(vocab_cards)").fetchall()]

        print("=== bench_cards_endpoint ===")
        print(f"scales={','.join(str(s) for s in scales)} rounds={rounds} (median) analyzer=off(与生产一致)")
        print(f"vocab_indexes={idx}")

        results: List[Dict[str, Any]] = []
        for n in scales:
            n_grammar = max(1, n // 4)  # realistic vocab:grammar ≈ 4:1
            _fill(db_path, n, n_grammar, seed=20261004 + n)
            r = _bench_scale(db_path, n, n_grammar, rounds, get_cards)
            results.append(r)
            print(f"--- scale={n} (vocab_rows={n} grammar_rows={n_grammar}) ---")
            for line in r["plan"]:
                print(f"plan_detail={line}")
            print(f"segment_A_ms={r['A']:.3f}")
            print(f"segment_B_ms={r['B']:.3f}")
            print(f"segment_C_ms={r['C']:.3f}")
            print(f"segment_D_ms={r['D']:.3f}")
            print(f"lookup_ms={r['lookup_ms']:.3f}")
            print(f"filesort_ms={r['filesort_ms']:.3f}")
            print(f"python_fsrs_ms={r['python_ms']:.3f}")
            print(f"filesort_pct={r['filesort_pct']:.1f}%")
            print(f"filesort_pct_of_sqlite={r['filesort_pct_of_sqlite']:.1f}%")
            print(f"python_pct={r['python_pct']:.1f}%")
            per_ms = r["D"] / n * 1000.0
            print(f"per_row_us={per_ms:.2f}")

        # 决策档：取规模最接近 20k 的那一档（审计 dba 座的实测规模），缺则取最大档。
        target = min(results, key=lambda r: abs(r["n_vocab"] - 20000))
        print("=== 结论 ===")
        print(f"decision_scale={target['n_vocab']}")
        print(
            f"构成：排序 filesort {target['filesort_ms']:.1f}ms（占端点 {target['filesort_pct']:.1f}%，"
            f"占 SQLite 侧 {target['filesort_pct_of_sqlite']:.1f}%）｜多列回表 {target['lookup_ms']:.1f}ms"
            f"｜Python 物化+FSRS {target['python_ms']:.1f}ms（占端点 {target['python_pct']:.1f}%）"
            f"｜端点总计 {target['D']:.1f}ms"
        )
        print(f"verdict={_verdict(target['filesort_pct'])}")
        print(f"python_verdict={_python_verdict(target['python_pct'])}")
        if len(results) > 1:
            lo, hi = results[0], results[-1]
            ratio_n = hi["n_vocab"] / lo["n_vocab"]
            ratio_d = hi["D"] / lo["D"] if lo["D"] > 0 else 0.0
            shape = "近线性" if ratio_d <= ratio_n * 1.25 else "超线性（增速快于行数，拐点在 20k~50k 之间）"
            print(
                f"scaling={shape}：行数 ×{ratio_n:.1f} ⇒ 端点耗时 ×{ratio_d:.1f}"
                f"（{lo['D']:.1f}ms → {hi['D']:.1f}ms）"
            )
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
