# -*- coding: utf-8 -*-
"""ADR-0016 Phase 3 / Task 6：统一词池端到端验收（跨 T1–T5 全链路集成断言）。

这是 Phase 3「单池可见」核心主张的**用户可见结论**级验收：

   背词工作台背过的词（reps>0）经 ``PUT /api/wb/state`` 幂等投影进统一池
   ``vocab_cards``（T1/T2）→ 在 ``GET /api/cards`` 可见；冷种子词（非自建且未学）
   被范围闸挡下；用户手编数据只补空、绝不覆盖；三段时序幂等；只读对账无缺口
   （T4）；备份往返（含 source/fsrs_*）逐字保留 + 还原后按 wb 快照自愈（T5）。
   另加一条**静态**断言钉住 Phase 3 边界「不改前端 static/」（T3 已按用户决定跳过）。

库隔离照搬 ``tests/test_server.py::clean_db``：保存/还原 env、建库、并把 WAL 旁文件
``-wal`` / ``-shm`` 一并清理（启用 WAL 后只删主库会把陈旧 ``-shm`` 留给下个用例 →
   打开即 ``disk I/O error``）。``client`` 用本机来源 ``("127.0.0.1", ...)``：
``PUT /api/wb/state`` 与 ``GET /api/wb/state/key`` 均有本机闸。

身份键说明（关键）：统一池按 ``lemma_key(hw)``（小写归一）判「同一个词」，但存储的
``lemma`` 列保留**原始形态**（``POST /api/cards/vocab`` 原样写入，如 ``"Haus"``）。
投影 / 对账的**比较口径**统一走 ``lemma_key``（``delector.core.vocab_pool``），故用户卡
以真实未归一形态落库时，deck 投影仍命中同一行——这是「只补空不覆盖」可被断言、且对
「改成无条件覆盖」这一变异敏感的前提。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_unified_pool_e2e.py -q
"""

import gc
import os
import subprocess
from collections.abc import Iterator
from typing import Any, Dict, List

import pytest
from db_cleanup import remove_db_files
from fastapi.testclient import TestClient

from delector.core.database import db_conn
from delector.core.lexicon import lemma_key, primary_source
from delector.core.vocab_pool import reconcile_report
from delector.server import app, init_db

DB_FILE = "test_delector.db"
PROGRESS_FILE = "test_progress.db"


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    """每例独立库：照搬 tests/test_server.py::clean_db（含 env 保存/还原 + 三件套清理）。

    前后双钉 env：``database.get_db_path()`` 每次调用都读 ``os.environ``（非 import 时
    冻结），全量 pytest 时更晚收集的文件可能在模块顶层改写 DATABASE_PATH，收集顺序若
    让本文件先 import、用例后执行，默认路径就会命中未建表的别家库 → 「no such table」。
    """
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = DB_FILE
    os.environ["PROGRESS_DB_PATH"] = PROGRESS_FILE
    # sqlite3.Connection 与内部 statement 互为引用环：先 gc.collect() 断环，Windows 上
    # 句柄未释放时 os.remove 抛 PermissionError（被吞），旧库残留 → 隔离失效。
    gc.collect()
    remove_db_files(DB_FILE, PROGRESS_FILE)
    init_db(DB_FILE)
    yield
    gc.collect()
    remove_db_files(DB_FILE, PROGRESS_FILE)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client() -> TestClient:
    """本机来源地址：PUT /api/wb/state 与 GET /api/wb/state/key 有 _require_localhost 闸。"""
    return TestClient(app, client=("127.0.0.1", 54321))


def _put_deck(client: TestClient, payload: Dict[str, Any]) -> Any:
    """取本机 key 后带 X-WB-Key 写入 deck 镜像（服务端契约：body 顶层单键 payload）。"""
    key = client.get("/api/wb/state/key").json()["key"]
    return client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})


def _pool_rows() -> Dict[str, Dict[str, Any]]:
    """统一池现有行，按 ``lemma`` 列（池内身份键）为 dict 键。"""
    with db_conn(DB_FILE) as conn:
        return {r["lemma"]: dict(r) for r in conn.execute("SELECT * FROM vocab_cards").fetchall()}


def _card_for(cards: List[Dict[str, Any]], lemma: str) -> Any:
    """在 ``GET /api/cards`` 的 vocab_cards 里按归一键找卡；找不到返回 None。"""
    lk = lemma_key(lemma)
    for c in cards:
        if lemma_key(str(c.get("lemma"))) == lk:
            return c
    return None


# ── 断言 1：单池可见性（背过的词 → 卡盒/统一池可见；冷种子被范围闸挡下）───────────
def test_group1_single_pool_visibility(client: TestClient) -> None:
    payload = {
        "words": [
            {"id": "u-haus", "hw": "Haus", "pos": "NOUN", "gloss": "房子", "ex": [{"de": "Das Haus ist groß."}]},
            {"id": "u-baum", "hw": "Baum", "pos": "NOUN", "gloss": "树"},  # 冷种子：非 custom、无卡
        ],
        "cards": {"u-haus": {"reps": 1, "s": 12.5, "d": 4.2, "lapses": 3}},
    }
    res = _put_deck(client, payload)
    assert res.status_code == 200, res.text

    cards = client.get("/api/cards").json()["vocab_cards"]
    haus = _card_for(cards, "Haus")
    assert haus is not None, "背词工作台背过的 Haus 应进入统一池（GET /api/cards 可见）"
    assert haus["source"] == primary_source("Haus"), f"Haus.source 应落定为 {primary_source('Haus')!r}"
    assert haus["fsrs_s"] == 12.5, f"Haus.fsrs_s 应等于卡里的 s(12.5)，实际 {haus['fsrs_s']!r}"

    assert _card_for(cards, "Baum") is None, "未学、非自建的冷种子词 Baum 不应入池（范围闸生效）"


# ── 断言 2：用户数据零覆盖（只补空、不覆盖既有用户释义）─────────────────────────
def test_group2_user_data_never_overwritten(client: TestClient) -> None:
    # 用户先手建一张卡（走真实端点：POST /api/cards/vocab 原样写入**未归一** lemma "Haus"）。
    r = client.post(
        "/api/cards/vocab",
        json={
            "word": "Haus",
            "lemma": "Haus",
            "definition_zh": "用户手编释义",
            "sentence_context": "Mein Haus ist alt.",
            "cefr_level": "A1",
        },
    )
    assert r.status_code == 200, r.text

    # 再用**不同 gloss** 的 Haus 走 deck 投影。
    payload = {
        "words": [{"id": "u-haus", "hw": "Haus", "gloss": "房子（工作台不同 gloss）"}],
        "cards": {"u-haus": {"reps": 2, "s": 9.0, "d": 5.0, "lapses": 1}},
    }
    res = _put_deck(client, payload)
    assert res.status_code == 200, res.text

    # 行数断言走 COUNT(*)：_pool_rows() 以 lemma 为键会折叠同 lemma 多行 —— 不能让它
    # 把「按原始口径另插一行」静默折叠成通过。
    with db_conn(DB_FILE) as conn:
        count = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    assert count == 1, f"同一身份键应只 1 行（投影命中用户卡同一行），实际 COUNT(*)={count}"

    rows = _pool_rows()
    # 身份判定按**内容**（lemma_key）：存储的 lemma 保留原始形态 'Haus'，归一后 = 'haus'。
    assert {lemma_key(k) for k in rows} == {lemma_key("Haus")}, f"身份键按内容归一后应为 {{haus}}，实际 {set(rows)}"
    row = next(iter(rows.values()))
    assert row["lemma"] == "Haus", "存储值不被本修复改写（仍是原始形态）"
    assert row["definition_zh"] == "用户手编释义", "既有用户释义不得被 deck gloss 覆盖（只补空）"
    assert row["sentence_context"] == "Mein Haus ist alt.", "既有语境句不得被覆盖"
    assert row["fsrs_s"] == 9.0, "空槽 fsrs_s 应被补上（证明投影命中同一行，而非另插一行）"


# ── 断言 3：三段时序幂等（PUT → 同 payload PUT → 新增已学词 PUT）───────────────
def test_group3_three_phase_idempotency(client: TestClient) -> None:
    p1 = {
        "words": [{"id": "u-haus", "hw": "Haus", "gloss": "房子"}],
        "cards": {"u-haus": {"reps": 1, "s": 1.0}},
    }
    assert _put_deck(client, p1).status_code == 200
    assert _put_deck(client, p1).status_code == 200  # 同 payload 二次 PUT

    with db_conn(DB_FILE) as conn:
        count_a = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
        lemmas_a = {r["lemma"] for r in conn.execute("SELECT lemma FROM vocab_cards").fetchall()}
    assert count_a == 1, f"同 payload 二次 PUT 不得新增行，实际 COUNT(*)={count_a}"
    assert lemmas_a == {lemma_key("Haus")}, f"lemma 集合应仍为 {{haus}}，实际 {lemmas_a}"

    # 追加一个**新增**已学词：行数只 +1。
    p2 = {
        "words": [
            {"id": "u-haus", "hw": "Haus", "gloss": "房子"},
            {"id": "u-wasser", "hw": "Wasser", "gloss": "水"},
        ],
        "cards": {"u-haus": {"reps": 1, "s": 1.0}, "u-wasser": {"reps": 2, "s": 2.0}},
    }
    assert _put_deck(client, p2).status_code == 200

    with db_conn(DB_FILE) as conn:
        count_b = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
        lemmas_b = {r["lemma"] for r in conn.execute("SELECT lemma FROM vocab_cards").fetchall()}
    assert count_b == 2, f"新增已学词应只 +1 行（1→2），实际 COUNT(*)={count_b}"
    assert lemmas_b == {lemma_key("Haus"), lemma_key("Wasser")}, f"lemma 集合应为 {{haus, wasser}}，实际 {lemmas_b}"


# ── 断言 4：只读对账无缺口（同一 wb payload：可投影 2 / 在池 2 / missing 空）────
def test_group4_reconcile_has_no_gap(client: TestClient) -> None:
    payload = {
        "words": [
            {"id": "u-haus", "hw": "Haus", "gloss": "房子"},
            {"id": "u-wasser", "hw": "Wasser", "gloss": "水"},
            {"id": "u-baum", "hw": "Baum", "gloss": "树"},  # 冷种子：非 custom、无卡 → 不计入可投影
        ],
        "cards": {"u-haus": {"reps": 1, "s": 1.0}, "u-wasser": {"reps": 2, "s": 2.0}},
    }
    assert _put_deck(client, payload).status_code == 200

    with db_conn(DB_FILE) as conn:
        report = reconcile_report(conn, payload)
    assert report["deck_projectable"] == 2, f"可投影应 2（Haus/Wasser），实际 {report}"
    assert report["deck_in_pool"] == 2, f"在池应 2，实际 {report}"
    assert report["missing"] == [], f"对账不得有缺口，实际 missing={report['missing']}"


# ── 断言 5：备份往返（source/fsrs_* 逐字保留）+ 还原后 wb 快照自愈 ──────────────
def test_group5_backup_roundtrip_and_restore_selfheal(client: TestClient) -> None:
    payload = {
        "words": [
            {"id": "u-haus", "hw": "Haus", "gloss": "房子"},
            {"id": "u-wasser", "hw": "Wasser", "gloss": "水"},
        ],
        "cards": {
            "u-haus": {"reps": 1, "s": 12.5, "d": 4.2, "lapses": 3},
            "u-wasser": {"reps": 2, "s": 7.5, "d": 6.1, "lapses": 0},
        },
    }
    assert _put_deck(client, payload).status_code == 200

    before = _pool_rows()
    assert set(before) == {lemma_key("Haus"), lemma_key("Wasser")}, f"投影后应两行，实际 {set(before)}"

    # prepare → download（本机闸）。
    prep = client.post("/api/backup/prepare", json={"local_storage": {}})
    assert prep.status_code == 200, prep.text
    dl = client.get(f"/api/backup/download/{prep.json()['token']}")
    assert dl.status_code == 200, dl.text
    backup = dl.json()

    # 模拟「换机」且备份取自 Wasser 尚未投影之时：从备份 vocab_cards 里去掉 Wasser，
    # 令它只能靠 wb 快照在还原后 self-heal 补回（wb_state 镜像**不进备份清单**）。
    # Haus 保留在备份里，用于断言 source/fsrs_* 经备份往返逐字保留。
    backup["vocab_cards"] = [
        c for c in backup["vocab_cards"] if lemma_key(str(c.get("lemma"))) != lemma_key("Wasser")
    ]
    assert {lemma_key(str(c.get("lemma"))) for c in backup["vocab_cards"]} == {lemma_key("Haus")}

    with db_conn(DB_FILE) as conn:
        conn.execute("DELETE FROM vocab_cards")  # 清空目标池，模拟全新设备

    res = client.post("/api/backup/restore", json=backup)
    assert res.status_code == 200, res.text

    after = _pool_rows()
    # ① source/fsrs_* 逐字保留（Haus＝备份往返；Wasser＝wb 快照自愈）。
    for lemma, exp in before.items():
        assert lemma in after, f"还原后应存在 {lemma}（Haus=备份往返 / Wasser=wb 自愈）"
        got = after[lemma]
        for col in ("source", "fsrs_s", "fsrs_d", "fsrs_lapses"):
            assert got[col] == exp[col], f"{lemma}.{col} 还原后被改写：{got[col]!r} != {exp[col]!r}"

    # ② 对账无缺口（wb 快照里两词均已入池）。
    with db_conn(DB_FILE) as conn:
        report = reconcile_report(conn, payload)
    assert report["missing"] == [], f"还原后对账不得有缺口，实际 missing={report['missing']}"
    assert report["deck_in_pool"] == 2, f"还原后应在池 2，实际 {report}"


# ── 附加：静态钉住「Phase 3 不改前端 static/」（T3 已按用户决定跳过）────────────
def test_phase3_does_not_modify_frontend_static() -> None:
    """Phase 3 的明确边界：不改前端。用 git 钉住 static/ 零改动。

    离线 CI（无 git / 无 origin/master）显式 pytest.skip——**绝不**用 ``except: pass``
    变成「环境缺失即静默通过」的假绿。
    """
    try:
        base_proc = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/master"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git / origin/master 不可用（离线 CI？），跳过 static/ 静态断言：{exc}")

    base = base_proc.stdout.strip()
    if not base:
        pytest.skip("git merge-base 输出为空，无法确定 Phase 3 基座，跳过 static/ 静态断言")

    try:
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD", "--", "static/"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git diff 不可用，跳过 static/ 静态断言：{exc}")

    changed = diff_proc.stdout.strip()
    assert changed == "", f"Phase 3 不得修改 static/ 下的文件，实际改动：\n{changed}"
