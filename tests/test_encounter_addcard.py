# -*- coding: utf-8 -*-
"""遇见区 A6：生词点词弹层 → 一键进卡 → 读完小复习（纯函数 + 静态探针）。

覆盖两层：
  1) deck-bridge.js 新增的**纯**函数（A6 契约，零 import、零浏览器全局、可 Node 直读）：
       makeWordObject(lemma, gloss, pos, genId, nowMs)
       addCardToDeck(deck, lemma, {gloss,pos,genId,nowMs})
     这些只操作 deck 对象（{words, cards}），不碰 localStorage / fetch —— 存储写入与
     PUT /api/wb/state 镜像同步发生在 encounter.js（页面侧），不在纯函数里。
  2) 前端静态探针：index.html 必须含 `#enc-popover` 弹层与 `#enc-review` 会话复习容器；
     encounter.js 必须消费 /api/lookup/vocab（释义）、/api/wb/state（镜像同步）、
     '加入卡片' 语义、以及 deck-bridge 的 DECK_KEYS（写回 wb.words.v1）。

workbench 真实形状 truth（static/german/workbench.html）：
  S.words.push({ id:"u-"+now.toString(36), hw, pos, gloss, ipa, ex, letter,
                 page:0, tags:[...], custom:true, up:now });   // up = 真实毫秒
  FSRS 卡形状 {s,d,due,last,reps,lapses}（fsrsReview，line ~2023/2043）。

RED-1 语义真相（与工作台队列真值对齐）：
  工作台里「新/待排」词 = cards 里**没有**它的条目（!S.cards[w.id]）；due 词要求
  reps>0；工作台自己的 setWordState("new") 就是 delete S.cards[id]。若 A6 进卡时写
  一张 reps:0 / due=ISO 的 starter 卡，会让该词对两个池都不可见 → 永不排期。
  故 A6 进卡 = **只写词（word），绝不建卡**：新词天然满足 !S.cards[w.id] 语义，
  进入背词工作台可见词表、可被复习。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_addcard.py -v
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DECK_BRIDGE_SRC = ROOT / "static" / "js" / "deck-bridge.js"
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
ENCOUNTER_JS = (ROOT / "static" / "js" / "encounter.js").read_text(encoding="utf-8")


# ── Node ESM 探针（逐字节复制真源码成 .mjs 直读）─────────────────────────────
_RUNNER = r"""
import fs from "node:fs";
const ctx = JSON.parse(fs.readFileSync(0, "utf8"));
const DB = await import("./deck-bridge.mjs");
const out = {};
function noThrow(fn) {
  try { return { ok: true, v: fn() }; }
  catch (e) { return { ok: false, err: String(e && e.message || e) }; }
}
if (ctx.op === "makeWordObject") {
  out.word = DB.makeWordObject(ctx.lemma, ctx.gloss, ctx.pos, ctx.genId,
                               ctx.nowMs != null ? ctx.nowMs : undefined);
} else if (ctx.op === "probeExports") {
  out.have = ["makeWordObject", "addCardToDeck"].map((f) => typeof DB[f]);
  out.goneCard = typeof DB.makeCardObject;  // 应为 undefined（RED-1 移除）
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
        pytest.fail("static/js/deck-bridge.js 尚不存在（Task A5 未实现 → RED）")
    dest = tmp_path / "deck-bridge.mjs"
    src_bytes = DECK_BRIDGE_SRC.read_bytes()
    dest.write_bytes(src_bytes)
    assert dest.read_bytes() == src_bytes, "deck-bridge.mjs 必须逐字节等于真源码"
    return dest


def _run_node(ctx, bridge):
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过 Node 探针")
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
    assert res.returncode == 0, "deck-bridge A6 Node 探针执行失败：\n%s\n%s" % (
        res.stdout,
        res.stderr,
    )
    return json.loads(res.stdout)


def _strip_comments(src):
    out = []
    i = 0
    n = len(src)
    while i < n:
        if src[i : i + 2] == "/*":
            j = src.find("*/", i + 2)
            i = (j + 2) if j >= 0 else n
        elif src[i : i + 2] == "//":
            j = src.find("\n", i + 2)
            i = j if j >= 0 else n
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


# ── verbatim + ESM 纯净（node 可测性硬约束）──────────────────────────────────
def test_deck_bridge_still_esm_clean_and_exports_a6(bridge):
    """deck-bridge.js 继续零 import / 零浏览器全局；A6 导出仅剩 word-only 集合。"""
    assert bridge.read_bytes() == DECK_BRIDGE_SRC.read_bytes()
    src = _strip_comments(DECK_BRIDGE_SRC.read_text(encoding="utf-8"))
    assert "import " not in src
    for glob in ("localStorage", "window.", "document."):
        assert glob not in src, "deck-bridge.js 不得引用浏览器全局：%r" % glob
    for fn in ("makeWordObject", "addCardToDeck"):
        assert ("export function " + fn) in src, "deck-bridge.js 缺导出 %r" % fn
    # RED-1：makeCardObject 已删除，不得再导出
    assert "makeCardObject" not in src, "makeCardObject 已被移除（RED-1）"


def test_make_card_object_gone(bridge):
    """RED-1：makeCardObject 已从 deck-bridge 移除（不再写 reps0/ISO 卡）。"""
    out = _run_node({"op": "probeExports"}, bridge)
    assert out["goneCard"] == "undefined"


# ── makeWordObject：workbench 自定义词字段 truth ─────────────────────────────
def test_make_word_object_matches_workbench_custom_shape(bridge):
    """makeWordObject 产出与 workbench 自定义词一致的字段集（id='u-'+genId，up=nowMs）。"""
    now = 1757212800000
    out = _run_node(
        {"op": "makeWordObject", "lemma": "gehen", "gloss": "去；走", "pos": "VERB",
         "genId": "zzz", "nowMs": now},
        bridge,
    )
    w = out["word"]
    # 字段集合与 workbench 自定义词一致
    assert set(w.keys()) >= {"id", "hw", "pos", "gloss", "ipa", "ex", "letter",
                             "page", "tags", "custom", "up"}
    assert w["id"] == "u-zzz"
    assert w["hw"] == "gehen"
    assert w["pos"] == "VERB"
    assert w["gloss"] == "去；走"
    assert w["ipa"] == ""
    assert w["ex"] == []
    assert w["letter"] == "G"
    assert w["page"] == 0
    assert w["tags"] == []
    assert w["custom"] is True
    # YELLOW-3：up 直接取注入 nowMs（真实毫秒），不靠解析 id 后缀
    assert w["up"] == now


def test_make_word_object_default_up_is_real_now_ms(bridge):
    """不传 nowMs 时 up=Date.now()（真实毫秒，非由 id 后缀反解）。"""
    out = _run_node(
        {"op": "makeWordObject", "lemma": "laufen", "gloss": "跑", "pos": "V",
         "genId": None, "nowMs": None},
        bridge,
    )
    w = out["word"]
    assert w["id"].startswith("u-")
    assert isinstance(w["up"], int) and w["up"] > 0


def test_make_word_object_up_does_not_derive_from_genid_suffix(bridge):
    """YELLOW-3：up 不随 genId 后缀变化——同 genId、不同 nowMs → up=各自 nowMs。"""
    a = _run_node(
        {"op": "makeWordObject", "lemma": "sitzen", "gloss": "坐", "pos": "V",
         "genId": "abc", "nowMs": 1000},
        bridge,
    )["word"]
    b = _run_node(
        {"op": "makeWordObject", "lemma": "sitzen", "gloss": "坐", "pos": "V",
         "genId": "abc", "nowMs": 9999999999000},
        bridge,
    )["word"]
    # 同 genId → id 相同（u-abc），但 up 严格等于各自注入的 nowMs
    assert a["id"] == b["id"] == "u-abc"
    assert a["up"] == 1000
    assert b["up"] == 9999999999000


def test_make_word_object_letter_strips_articles(bridge):
    """letterOf 语义：冠词打头时归到实体首字母（与 workbench letterOf 一致）。"""
    out = _run_node(
        {"op": "makeWordObject", "lemma": "das Haus", "gloss": "房子", "pos": "n.",
         "genId": "q9", "nowMs": 1},
        bridge,
    )
    assert out["word"]["hw"] == "das Haus"
    assert out["word"]["letter"] == "H"


# ── addCardToDeck：word-only（不加卡）────────────────────────────────────────
def test_add_card_is_word_only_no_card_created(bridge):
    """RED-1：首次添加 added=true，deck.words +1；cards 不加任何键（无新词条目）。"""
    now = 1757212800000
    base = {"words": [], "cards": {}}
    r1 = _run_node(
        {"op": "addCardToDeck", "deck": base, "lemma": "gehen", "gloss": "走",
         "pos": "V", "genId": "aaa", "nowMs": now},
        bridge,
    )
    assert r1["result"]["added"] is True
    assert r1["result"]["reason"] == "added"
    d1 = r1["result"]["deck"]
    assert len(d1["words"]) == 1
    assert d1["words"][0]["hw"] == "gehen"
    assert d1["words"][0]["up"] == now
    wid = d1["words"][0]["id"]
    # word-only：cards 绝不新增键（让工作台 !S.cards[w.id]「新词」语义成立）
    assert wid not in d1["cards"]
    assert len(d1["cards"]) == 0


def test_add_card_preserves_existing_cards_untouched(bridge):
    """RED-1：新词加入不写卡，也不触碰既有卡——cards 原样保留。"""
    deck = {
        "words": [{"id": "w9", "hw": "Haus"}],
        "cards": {"w9": {"reps": 2, "due": 1757000000000}},
    }
    out = _run_node(
        {"op": "addCardToDeck", "deck": deck, "lemma": "Auto", "gloss": "汽车",
         "pos": "n.", "genId": "k1", "nowMs": 1757212800000},
        bridge,
    )
    assert out["result"]["added"] is True
    d = out["result"]["deck"]
    # 既有卡保留
    assert d["cards"]["w9"] == {"reps": 2, "due": 1757000000000}
    # 新词无卡条目
    new_w = [w for w in d["words"] if w["hw"] == "Auto"][0]
    assert new_w["id"] not in d["cards"]


def test_add_card_duplicate_lemma_exists_no_repeat(bridge):
    """二次同 lemma（大小写无关）→ added=false reason='exists'，不重复追加。"""
    now = 1757212800000
    base = {"words": [], "cards": {}}
    r1 = _run_node(
        {"op": "addCardToDeck", "deck": base, "lemma": "gehen", "gloss": "走",
         "pos": "V", "genId": "aaa", "nowMs": now},
        bridge,
    )
    d1 = r1["result"]["deck"]
    r2 = _run_node(
        {"op": "addCardToDeck", "deck": d1, "lemma": "Gehen", "gloss": "走",
         "pos": "V", "genId": "bbb", "nowMs": now},
        bridge,
    )
    assert r2["result"]["added"] is False
    assert r2["result"]["reason"] == "exists"
    assert len(r2["result"]["deck"]["words"]) == 1
    # 不建卡：cards 保持空
    assert len(r2["result"]["deck"]["cards"]) == 0


def test_add_card_learned_word_not_added(bridge):
    """词已在 deck 且 cards[id].reps>0（已学习）→ added=false reason='learned'。"""
    deck = {
        "words": [{"id": "w9", "hw": "Haus"}],
        "cards": {"w9": {"reps": 2}},
    }
    out = _run_node(
        {"op": "addCardToDeck", "deck": deck, "lemma": "haus", "gloss": "房子",
         "pos": "n.", "genId": "x1", "nowMs": 1757212800000},
        bridge,
    )
    assert out["result"]["added"] is False
    assert out["result"]["reason"] == "learned"
    assert len(out["result"]["deck"]["words"]) == 1
    assert len(out["result"]["deck"]["cards"]) == 1


def test_add_card_genid_and_nowms_injection_deterministic(bridge):
    """同注入 genId/nowMs → 二次调用产生逐字段一致的 word（无时间随机性）。"""
    ctx = {"op": "addCardToDeck", "deck": {"words": [], "cards": {}},
           "lemma": "schön", "gloss": "漂亮", "pos": "ADJ",
           "genId": "f00", "nowMs": 1757212800000}
    a = _run_node(ctx, bridge)
    b = _run_node(ctx, bridge)
    assert a["result"]["added"] is True
    assert a["result"]["deck"] == b["result"]["deck"]
    assert a["result"]["deck"]["words"][0]["up"] == 1757212800000


def test_add_card_corrupt_deck_safe(bridge):
    """deck 形状残缺（非数组/缺键）→ 安全按空处理并添加 word，不抛异常。"""
    for bad in (None, {"words": None, "cards": None}, "garbage", {}):
        out = _run_node(
            {"op": "addCardToDeck", "deck": bad, "lemma": "Auto", "gloss": "汽车",
             "pos": "n.", "genId": "ok", "nowMs": 1757212800000},
            bridge,
        )
        assert out["result"]["added"] is True, "corrupt deck must degrade to empty-add"
        d = out["result"]["deck"]
        assert isinstance(d, dict) and isinstance(d.get("words"), list)
        assert any(w["hw"] == "Auto" for w in d["words"])
        # 坏 cards → 兜底空 {}，且新词不加卡键
        new_w = [w for w in d["words"] if w["hw"] == "Auto"][0]
        assert new_w["id"] not in d.get("cards", {})


# ── 前端静态探针 ─────────────────────────────────────────────────────────────
def test_index_has_popover_and_review_containers():
    """index.html 必须含 #enc-popover（点词弹层）与 #enc-review（读完小复习）。"""
    assert 'id="enc-popover"' in INDEX
    assert "enc-popover" in INDEX
    assert 'id="enc-review"' in INDEX
    assert "enc-review" in INDEX


def test_encounter_js_has_addcard_semantics():
    """encounter.js 含 '加入卡片' 语义与进卡/复习函数钩子。"""
    assert "加入卡片" in ENCOUNTER_JS
    assert "已加入" in ENCOUNTER_JS


def test_encounter_js_writes_deck_and_mirror_sync():
    """encounter.js 消费 lookup 释义端点、deck keys、wb 镜像同步端点与鉴权头。"""
    assert "/api/lookup/vocab" in ENCOUNTER_JS
    assert "/api/wb/state" in ENCOUNTER_JS
    assert "X-WB-Key" in ENCOUNTER_JS
    assert "wb.pair.v1" in ENCOUNTER_JS
    # 复用 deck-bridge 的 DECK_KEYS 写回 wb.words.v1
    assert "DECK_KEYS" in ENCOUNTER_JS
    # RED-1：进卡只把 words 写回 localStorage（wb.words.v1），不再写 wb.cards.v1
    assert "DECK_KEYS.words" in ENCOUNTER_JS


def test_encounter_js_does_not_write_cards_on_add():
    """RED-1：encounter.js 进卡路径只 setItem words，不 setItem cards。"""
    assert "DECK_KEYS.cards" not in ENCOUNTER_JS, (
        "进卡不再写 wb.cards.v1（RED-1：卡由工作台写/删）"
    )


def test_encounter_js_has_session_review_and_tts():
    """encounter.js 提供会话小复习翻转 + 经既有 TTS 端点/playGermanAudio 发音。"""
    assert "enc-review" in ENCOUNTER_JS
    # 发音：走既有 playGermanAudio（内部打 /api/audio/tts）或直接音频端点
    assert "playGermanAudio" in ENCOUNTER_JS or "/api/audio/tts" in ENCOUNTER_JS
