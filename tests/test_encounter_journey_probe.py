# -*- coding: utf-8 -*-
"""A7 客户端行为探针（T2）：把 A7 六步里的**客户端判定段**变成跨边界行为探针。

这是 tests/test_encounter_journey_e2e.py（T1，服务端全链路）的**客户端对偶**。

A7 六步：
   ①背词工作台背 ≥3 词使 reps>0
   ②遇见区加一篇短文
   ③打开详情断言已背词高亮 + 覆盖数>0
   ④点未知词出本地词典释义
   ⑤点「加入卡片」写 deck 并触发 wb 同步
   ⑥重开工作台断言新词进入新词池

T1 覆盖服务端可观测段（①-⑥ 的服务端等价物）。本文件覆盖 **③ 与 ⑤ 的前端判定逻辑**，
且**不手写假 annotate JSON**——而是：

  1) 用 fastapi.testclient.TestClient（本机来源 + tmp 双库，沿用 T1 夹具）
     **真实**调 POST /api/encounter/texts 建短文、GET .../annotate 取真实响应；
  2) 把**真实响应 JSON** 通过 stdin 喂给 node 探针；
  3) 探针逐字节拷贝真源码 static/js/deck-bridge.js 为临时 .mjs，
     调 buildKnownSet / isKnown / annotateWithDeck / addCardToDeck，
     把结果 JSON 吐回 Python 端做具体断言。

红线 11（跨边界契约必须行为探针，字符串存在断言是死测）的落地：
本文件不再做「源里出现某字符串」的存在断言，而是让真实数据穿过真实函数、验行为。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_journey_probe.py -v
node 缺失时整文件显式 skip（显式理由），既不让 CI 因缺 node 变红，也不静默假绿。
"""
import json
import os
import gc
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# env 双钉必须在 import app 之前（沿用 T1：database.get_db_path() 每次调用读 os.environ）。
# setdefault 而非直接赋值：`delector/server.py:339` 的模块级单例 `app = create_app()` 在
# 收集期首次 import 时按此 env 建库并被其它模块共用；抢占 env 会让它们的 app 指向本测试的库。
os.environ.setdefault("DATABASE_PATH", "test_delector.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_progress.db")

from delector.server import create_app, init_db  # noqa: E402

ROOT = Path(__file__).parent.parent
DECK_BRIDGE_SRC = ROOT / "static" / "js" / "deck-bridge.js"

# 正文设计与 T1 对齐：Mann / gehen 是 deck 里 reps>0 的**已背词**；
# Schule / unverzagt 是正文出现但 deck 没有的**未背词**（unverzagt 连词典都没有）。
ARTICLE = "Der Mann geht unverzagt in die Schule."

# deck 形状与真实 deck 逐字段同源（words:[{id,hw,pos,gloss,...}]；cards:{id:{reps,...}}）。
# ≥3 个 reps>0 词 —— 满足 A7 第①步「背 ≥3 词」。
DECK_PAYLOAD = {
    "words": [
        {"id": "u-mann", "hw": "Mann", "pos": "NOUN", "gloss": "男人"},
        {"id": "u-gehen", "hw": "gehen", "pos": "VERB", "gloss": "走，去"},
        {"id": "u-wasser", "hw": "Wasser", "pos": "NOUN", "gloss": "水"},
    ],
    "cards": {
        "u-mann": {"reps": 4, "lapses": 0},
        "u-gehen": {"reps": 3, "lapses": 1},
        "u-wasser": {"reps": 2, "lapses": 0},
    },
}


# ── Node ESM 探针（逐字节复制真源码成 .mjs 直读，严格沿用既有 deck-bridge 探针模式）──
_RUNNER = r"""
import fs from "node:fs";
const ctx = JSON.parse(fs.readFileSync(0, "utf8"));
const DB = await import("./deck-bridge.mjs");
const out = {};
if (ctx.op === "probeKeys") {
  out.deckKeys = DB.DECK_KEYS;
} else if (ctx.op === "annotateWithDeck") {
  const r = DB.annotateWithDeck(ctx.deck, ctx.annotate);
  out.sentences = r.sentences;
  out.stats = r.stats;
} else if (ctx.op === "addCardToDeck") {
  const r = DB.addCardToDeck(ctx.deck, ctx.lemma, {
    gloss: ctx.gloss, pos: ctx.pos,
    genId: ctx.genId,
    nowMs: ctx.nowMs != null ? ctx.nowMs : undefined,
  });
  out.result = { added: r.added, reason: r.reason, deck: r.deck };
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture
def bridge(tmp_path):
    """deck-bridge.js 逐字节复制成 .mjs；缺失即 RED（未实现）。"""
    if not DECK_BRIDGE_SRC.exists():
        pytest.fail("static/js/deck-bridge.js 尚不存在（未实现 → RED）")
    dest = tmp_path / "deck-bridge.mjs"
    src_bytes = DECK_BRIDGE_SRC.read_bytes()
    dest.write_bytes(src_bytes)
    assert dest.read_bytes() == src_bytes, "deck-bridge.mjs 必须逐字节等于真源码"
    return dest


def _run_node(ctx, bridge):
    """node 直跑探针：node 缺失 → 显式 skip（不假绿、不让 CI 变红）。"""
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过客户端行为探针（显式 skip，非假绿）")
    runner = bridge.parent / "_runner.mjs"
    runner.write_text(_RUNNER, encoding="utf-8")
    # verbatim 保证：跑前再断言临时 .mjs 与真源码逐字节一致。
    assert bridge.read_bytes() == DECK_BRIDGE_SRC.read_bytes(), (
        "测试用的 deck-bridge.mjs 必须是 static/js/deck-bridge.js 的逐字节副本"
    )
    res = subprocess.run(
        ["node", str(runner)],
        input=json.dumps(ctx, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, "deck-bridge 行为探针执行失败：\n%s\n%s" % (
        res.stdout,
        res.stderr,
    )
    return json.loads(res.stdout)


# ── 服务端夹具（沿用 T1）：清表不删库 + 本机来源 TestClient ───────────────────
@pytest.fixture(autouse=True)
def clean_db():
    """每例只**清空本测试涉及的表**；绝不删库文件（Windows 句柄纪律 + 单例 app 共享）。

    与 test_encounter_journey_e2e.py 同一理由：`delector/server.py:339` 的模块级
    单例 app 被多个测试模块共用，删库文件会让它们 no such table。
    """
    from delector.core.database import db_conn, get_db_path

    db = get_db_path()
    init_db(db)  # 幂等建表：修补干净环境或前序测试留下的缺表
    with db_conn(db) as conn:
        conn.execute("DELETE FROM encounter_texts")
        conn.execute("DELETE FROM wb_state")
    yield
    gc.collect()


@pytest.fixture
def client():
    """本机来源地址：POST /texts 有 _require_localhost 闸。"""
    app = create_app()
    return TestClient(app, client=("127.0.0.1", 54321))


# node 缺失时整文件跳过（显式理由），避免每个用例各跳一次噪音，且保证 CI 不红不假绿。
pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：客户端行为探针需要 node 直跑真源码 deck-bridge.js",
)


def _real_annotate(client):
    """真实走服务端：建短文 → 取 annotate 真实响应 JSON（不手写假 JSON）。"""
    create = client.post("/api/encounter/texts", json={
        "title": "Probe Article", "level": "A2", "content": ARTICLE,
    })
    assert create.status_code == 201, create.text
    text_id = create.json()["id"]
    res = client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert res.status_code == 200, res.text
    return res.json()


# ── 断言组 1：已背词高亮成立（known_tokens>0，且 Mann/gehen 被标 known）──────
def test_known_highlight_real_annotate(client, bridge):
    """真实 annotate 响应喂给 annotateWithDeck：known_tokens>0 且已背词被标 known。"""
    annotate = _real_annotate(client)
    # 前提：真实响应结构就是 deck-bridge 消费的形状。
    assert annotate["total_tokens"] > 0
    assert isinstance(annotate["sentences"], list) and annotate["sentences"]

    out = _run_node(
        {"op": "annotateWithDeck", "deck": DECK_PAYLOAD, "annotate": annotate},
        bridge,
    )
    stats = out["stats"]
    # 按真源码实际字段名断言（known_tokens / known_rate）。
    assert stats["known_tokens"] > 0, "已背词高亮：known_tokens 必须 >0"
    assert stats["known_tokens"] <= stats["total_tokens"]

    # 正文里的已背词 Mann / gehen 确实被标记 known=True。
    tokens = [t for s in out["sentences"] for t in s["tokens"]]
    known_lemmas = {str(t["lemma"]).lower() for t in tokens if t.get("known") is True}
    assert "mann" in known_lemmas, "已背词 Mann 的 token 必须 known=True"
    assert "gehen" in known_lemmas, "已背词 gehen 的 token 必须 known=True"
    # 对照：正文里的未背词 Schule 不得被标 known。
    schule_toks = [t for t in tokens if str(t.get("lemma")).lower() == "schule"]
    assert schule_toks and all(t["known"] is False for t in schule_toks), \
        "未背词 Schule 必须 known=False（高亮不是「凡词皆亮」）"


# ── 断言组 2：覆盖统计（A7 第③步「覆盖数>0」的等价物）──────────────────────
def test_coverage_stats_positive(client, bridge):
    """stats.known_rate > 0（覆盖数>0），且与 known_tokens/total_tokens 自洽。"""
    annotate = _real_annotate(client)
    out = _run_node(
        {"op": "annotateWithDeck", "deck": DECK_PAYLOAD, "annotate": annotate},
        bridge,
    )
    stats = out["stats"]
    assert stats["known_rate"] > 0, "A7 第③步：覆盖数 known_rate 必须 >0"
    # 自洽：rate == round(known/total, 2)
    expect = round(stats["known_tokens"] / stats["total_tokens"], 2)
    assert abs(stats["known_rate"] - expect) < 1e-9, "known_rate 必须等于 known/total 四舍五入2位"
    # 计数不做假：total 等于各句 token 数之和。
    recomputed_total = sum(len(s["tokens"]) for s in out["sentences"])
    assert stats["total_tokens"] == recomputed_total


# ── 断言组 3：unknown_top 不含已背词（防「已背词被当生词推」）─────────────────
def test_unknown_top_excludes_known_lemmas(client, bridge):
    """unknown_top 里不得出现 deck 已背词 lemma（Mann/gehen/wasser）。"""
    annotate = _real_annotate(client)
    out = _run_node(
        {"op": "annotateWithDeck", "deck": DECK_PAYLOAD, "annotate": annotate},
        bridge,
    )
    unknown_lemmas = {e["lemma"] for e in out["stats"]["unknown_top"]}
    # 已背词（strip 冠词后小写）不得出现在生词推送里。
    for learned in ("mann", "gehen", "wasser"):
        assert learned not in unknown_lemmas, \
            "语义错误：已背词 %r 不得出现在 unknown_top" % learned
    # 对照：真正未背的 schule 应当被推为生词候选之一。
    assert "schule" in unknown_lemmas, "未背词 Schule 应出现在 unknown_top"


# ── 断言组 4：进卡形状（word-only 语义）─────────────────────────────────────
def test_add_card_shape_word_only(client, bridge):
    """addCardToDeck 后 words +1、cards 不新增键，且新词按源码字段写入。"""
    # 用真实 annotate 响应确认「进卡的目标词」确实在正文里（端到端语义连续）。
    annotate = _real_annotate(client)
    body_lemmas = {
        str(t["lemma"]).lower()
        for s in annotate["sentences"] for t in s["tokens"]
    }
    assert "unverzagt" in body_lemmas, "进卡探针的目标词应在正文里（端到端语义连续）"

    words_before = len(DECK_PAYLOAD["words"])
    cards_before = dict(DECK_PAYLOAD["cards"])
    out = _run_node(
        {"op": "addCardToDeck", "deck": DECK_PAYLOAD, "lemma": "unverzagt",
         "gloss": "毫不畏惧地", "pos": "ADV", "genId": "uv1", "nowMs": 1757212800000},
        bridge,
    )
    r = out["result"]
    assert r["added"] is True
    assert r["reason"] == "added"
    deck = r["deck"]
    # words 长度 +1
    assert len(deck["words"]) == words_before + 1
    # cards 不新增键（新词只入新词池、不建卡）
    assert deck["cards"] == cards_before, "进卡绝不建卡：cards 必须原样保留"
    new_w = [w for w in deck["words"] if w["hw"] == "unverzagt"][0]
    assert "u-uv1" not in deck["cards"], "word-only：新词不得在 cards 里建键"
    # 新词对象按源码实际字段写入（id=u-{genId} / up=注入 nowMs / custom=True）。
    assert new_w["id"] == "u-uv1"
    assert new_w["hw"] == "unverzagt"
    assert new_w["pos"] == "ADV"
    assert new_w["gloss"] == "毫不畏惧地"
    assert new_w["up"] == 1757212800000
    assert new_w["custom"] is True


# ── 断言组 5：回写键常量（防前后端存储键漂移）───────────────────────────────
def test_deck_keys_constant_matches_payload_shape(bridge):
    """真源码导出的 DECK_KEYS.words/.cards 与探针构造的 payload 字段一致。"""
    out = _run_node({"op": "probeKeys"}, bridge)
    keys = out["deckKeys"]
    assert keys["words"] == "wb.words.v1", "deck 现词键必须为 wb.words.v1"
    assert keys["cards"] == "wb.cards.v1", "deck 卡键必须为 wb.cards.v1"
    # 探针构造的 payload 用 words / cards 作为顶层字段——与 loadDeck/mergeServerDeck
    # 消费的键名（deck.words / deck.cards）一致，防键名漂移。
    assert set(DECK_PAYLOAD.keys()) == {"words", "cards"}
