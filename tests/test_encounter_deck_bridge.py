# -*- coding: utf-8 -*-
"""遇见区 (view-encounter) 已背词 deck 桥（Task A5）。

deck-bridge.js 是纯逻辑 ES module（零 import、零浏览器全局、storage 靠参数注入），
因此可以在 Node 侧把它当普通 ESM 真跑断言，无需 DOM。

Node 可测性硬约束（Plan Task A5）：
  - 本仓库根没有 package.json 的 "type":"module"，所以 deck-bridge.js 按 `.js`
    后缀会被 Node 当成 CommonJS → import 报错。对策（mandatory）：把
    static/js/deck-bridge.js **逐字节复制** 成临时目录的 `deck-bridge.mjs`，
    再在同目录放一个 `_runner.mjs` 去 `await import("./deck-bridge.mjs")`。
    `.mjs` 扩展名嗅探让 Node 按 ESM 解析该源码 —— 因此 deck-bridge.js 必须
    满足：无 import 语句、模块顶层不碰浏览器全局、只信 storage 参数注入。
  - 每个 node 运行前都断言临时 `.mjs` 与真源码逐字节一致（verbatim 保证）。

前端静态探针（无 node）：
  - index.html 必须含 `#enc-coverage` 覆盖统计容器；
  - encounter.js 必须 import './deck-bridge.js'（模块图可达）；
  - encounter.js 消费 annotate 端点 + deck 纯函数。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_deck_bridge.py -v
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

# 单条 ESM 探针脚本：按 ctx.op 分派，import 同目录 deck-bridge.mjs（逐字节复制品）。
# 从 stdin 读 ctx JSON，把计算结果写到 stdout（buildKnownSet 的 Set 先转数组）。
_RUNNER = r"""
import fs from "node:fs";
const ctx = JSON.parse(fs.readFileSync(0, "utf8"));
const DB = await import("./deck-bridge.mjs");
const out = {};
if (ctx.op === "loadDeck") {
  const storage = ctx.falsy ? null : {
    getItem: (k) => (ctx.store && Object.prototype.hasOwnProperty.call(ctx.store, k) ? ctx.store[k] : null),
  };
  const d = DB.loadDeck(storage);
  out.words = d.words;
  out.cards = d.cards;
} else if (ctx.op === "buildKnownSet") {
  const s = DB.buildKnownSet(ctx.deck);
  out.known = [...s].sort();
  out.probeHits = (ctx.probe || []).map((l) => s.has(String(l).toLowerCase()));
} else if (ctx.op === "annotateWithDeck") {
  const r = DB.annotateWithDeck(ctx.deck, ctx.annotate);
  out.sentences = r.sentences;
  out.stats = r.stats;
} else if (ctx.op === "mergeServerDeck") {
  out.result = DB.mergeServerDeck(ctx.deck, ctx.server);
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture
def bridge(tmp_path):
    """把真 deck-bridge.js 逐字节复制成 deck-bridge.mjs；缺失即 RED。

    返回 deck-bridge.mjs 的 Path。每次 node 运行都会再次断言 verbatim，
    这里先做一次以保证任何调用者拿到的一定是逐字节副本。
    """
    if not DECK_BRIDGE_SRC.exists():
        pytest.fail("static/js/deck-bridge.js 尚不存在（Task A5 未实现 → RED）")
    dest = tmp_path / "deck-bridge.mjs"
    src_bytes = DECK_BRIDGE_SRC.read_bytes()
    dest.write_bytes(src_bytes)
    assert dest.read_bytes() == src_bytes, "deck-bridge.mjs 必须逐字节等于真源码"
    return dest


def _run_node(ctx, bridge):
    """在同目录写 _runner.mjs，把 ctx 从 stdin 喂进 Node，返回解析后的结果 dict。"""
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过 Node 探针")
    runner = bridge.parent / "_runner.mjs"
    runner.write_text(_RUNNER, encoding="utf-8")
    # verbatim 保证：运行前再断言临时 .mjs == 真源码，杜绝测试跑的不是线上代码。
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
    assert res.returncode == 0, "deck-bridge Node 探针执行失败：\n%s\n%s" % (
        res.stdout,
        res.stderr,
    )
    return json.loads(res.stdout)


# ── 逐字节 verbatim 保证 ────────────────────────────────────────────────────


def test_verbatim_source_is_byte_copy_of_real_file(bridge):
    """deck-bridge.mjs 是 static/js/deck-bridge.js 的逐字节复制。"""
    assert bridge.read_bytes() == DECK_BRIDGE_SRC.read_bytes()


# ── loadDeck ────────────────────────────────────────────────────────────────


def test_load_deck_parses_realish_json_with_number_and_string_ids(bridge):
    """loadDeck 能解析含数字/字符串 word.id 的真实形状 JSON。"""
    words = [
        {"id": 5, "hw": "Haus"},  # 数字 id
        {"id": "a1-0001", "hw": "gehen"},  # 字符串 id
    ]
    cards = {"5": {"reps": 2}, "a1-0001": {"reps": 0}}
    store = {
        "wb.words.v1": json.dumps(words, ensure_ascii=False),
        "wb.cards.v1": json.dumps(cards, ensure_ascii=False),
    }
    out = _run_node({"op": "loadDeck", "store": store}, bridge)
    assert [w["id"] for w in out["words"]] == [5, "a1-0001"]
    assert out["words"][0]["hw"] == "Haus"
    assert out["cards"]["5"]["reps"] == 2
    assert out["cards"]["a1-0001"]["reps"] == 0


def test_load_deck_corrupt_json_returns_empty_no_throw(bridge):
    """loadDeck 遇坏 JSON / 缺键 / 假 storage 都返回空 deck，不抛异常。"""
    bad_store = {
        "wb.words.v1": "{not valid json!!",
        "wb.cards.v1": "[[[",
    }
    out = _run_node({"op": "loadDeck", "store": bad_store}, bridge)
    assert out["words"] == []
    assert out["cards"] == {}

    # 缺键 → 空
    out = _run_node({"op": "loadDeck", "store": {}}, bridge)
    assert out["words"] == [] and out["cards"] == {}

    # falsy storage → 空，不抛
    out = _run_node({"op": "loadDeck", "falsy": True}, bridge)
    assert out["words"] == [] and out["cards"] == {}


# ── buildKnownSet：reps>0 learned / reps=0 unlearned / 缺卡 unlearned ───────


def test_build_known_set_reps_gate_and_case_normalization(bridge):
    """known 词 = word 存在且 cards[id].reps>0；reps=0 或缺卡不算；hw 小写归一。"""
    deck = {
        "words": [
            {"id": "w1", "hw": "gehen"},
            {"id": "w2", "hw": "Haus"},
            {"id": "w3", "hw": "schön"},
            {"id": "w4", "hw": "Auto"},
            {"id": "w5", "hw": "Ball"},
        ],
        "cards": {
            "w1": {"reps": 3},  # learned
            "w2": {"reps": 1},  # learned → lower "haus"
            "w3": {"reps": 1},  # learned → lower "schön"（元音变音归一）
            "w4": {"reps": 0},  # unlearned（reps=0）
            # w5 缺卡 → unlearned
        },
    }
    out = _run_node(
        {
            "op": "buildKnownSet",
            "deck": deck,
            "probe": ["gehen", "HAUS", "schön", "Auto", "GEHEN"],
        },
        bridge,
    )
    assert out["known"] == ["gehen", "haus", "schön"]
    # probeHits：已知词大小写无关命中（含 umlaut）；未学/缺卡不命中
    assert out["probeHits"] == [True, True, True, False, True]


def test_build_known_set_strips_german_articles(bridge):
    """评审 ⑤：deck 词头带定/不定冠词（背词工作台 NOUN 拼装 der/die/das…
    如 "die Abfahrt"）时，known 集存剥冠词后的核心词——annotate 的 lemma 原形
    （无冠词，如 "abfahrt"）才能命中。纯 lower 整串比对会让名词永远高亮不了。
    """
    deck = {
        "words": [
            {"id": "w1", "hw": "die Abfahrt"},  # learned（带定冠词 NOUN）
            {"id": "w2", "hw": "der Bahnhof."},  # learned（冠词 + 句点尾巴）
            {"id": "w3", "hw": "ein Auto"},  # learned（不定冠词）
            {"id": "w4", "hw": "Haus"},  # learned（本来就无冠词）
            {"id": "w5", "hw": "das nicht"},  # unlearned（reps=0，不参与）
        ],
        "cards": {
            "w1": {"reps": 1},
            "w2": {"reps": 2},
            "w3": {"reps": 1},
            "w4": {"reps": 3},
            "w5": {"reps": 0},
        },
    }
    out = _run_node(
        {
            "op": "buildKnownSet",
            "deck": deck,
            "probe": ["Abfahrt", "abfahrt", "ABFAHRT", "bahnhof", "Auto", "Haus"],
        },
        bridge,
    )
    # 去冠词/清标点后的小写核心词集合
    assert out["known"] == ["abfahrt", "auto", "bahnhof", "haus"]
    # probeHits：核心词（任意大小写）命中冠词词头；"Haus" 本就无冠词仍命中
    assert out["probeHits"] == [True, True, True, True, True, True]


# ── annotateWithDeck：known flags + stats 精确值 ────────────────────────────


def test_annotate_with_deck_marks_known_and_exact_coverage(bridge):
    """mini annotate：known 标记正确，total/known/rate 精确，unknown_top 排序正确。"""
    deck = {
        "words": [
            {"id": "w1", "hw": "gehen"},
            {"id": "w2", "hw": "schön"},
        ],
        "cards": {"w1": {"reps": 3}, "w2": {"reps": 1}},
    }
    annotate = {
        "text_id": 1,
        "total_tokens": 7,
        "sentences": [
            {
                "idx": 0,
                "tokens": [
                    {"text": "Geht", "lemma": "gehen", "pos": "VERB"},  # known
                    {"text": "schön", "lemma": "schön", "pos": "ADJ"},  # known
                    {"text": "Haus", "lemma": "haus", "pos": "NOUN"},  # unknown
                    {"text": ",", "lemma": ",", "pos": "PUNCT"},  # known=false（punct）
                    {"text": "!", "lemma": "!", "pos": "PUNCT"},  # known=false（punct）
                ],
            },
            {
                "idx": 1,
                "tokens": [
                    {"text": "Haus", "lemma": "haus", "pos": "NOUN"},  # unknown ×2
                    {"text": "gehen", "lemma": "gehen", "pos": "VERB"},  # known
                ],
            },
        ],
    }
    out = _run_node({"op": "annotateWithDeck", "deck": deck, "annotate": annotate}, bridge)

    # 逐 token known
    s0 = out["sentences"][0]["tokens"]
    assert [t["known"] for t in s0] == [True, True, False, False, False]
    s1 = out["sentences"][1]["tokens"]
    assert [t["known"] for t in s1] == [False, True]

    # stats 精确
    stats = out["stats"]
    assert stats["total_tokens"] == 7
    assert stats["known_tokens"] == 3
    assert stats["known_rate"] == 0.43  # 3/7 四舍五入两位
    # unknown_top：punct 不参与；候选 = haus ×2
    assert stats["unknown_top"] == [{"lemma": "haus", "count": 2}]


def test_annotate_with_deck_noun_hw_with_article_is_known(bridge):
    """评审 ⑤ 行为钉死：deck 已背名词头带冠词（die Abfahrt），annotate 的
    lemma 原形（abfahrt）必须算 known——这是「已背 A1/A2 名词在文章里高亮」
    的前提；不带冠词的生词 haus 仍 unknown 进 unknown_top。
    """
    deck = {
        "words": [
            {"id": "w6", "hw": "die Abfahrt"},  # learned 名词（背词台拼装冠词）
            {"id": "w7", "hw": "Haus"},  # learned 名词（无冠词词头）
        ],
        "cards": {"w6": {"reps": 1}, "w7": {"reps": 3}},
    }
    annotate = {
        "text_id": 2,
        "total_tokens": 2,
        "sentences": [
            {
                "idx": 0,
                "tokens": [
                    {"text": "Abfahrt", "lemma": "abfahrt", "pos": "NOUN"},  # known（剥冠词命中）
                    {"text": "Haus", "lemma": "haus", "pos": "NOUN"},  # known（无冠词词头）
                ],
            },
            {
                "idx": 1,
                "tokens": [
                    {"text": "Auto", "lemma": "auto", "pos": "NOUN"},  # unknown → 候选
                ],
            },
        ],
    }
    out = _run_node({"op": "annotateWithDeck", "deck": deck, "annotate": annotate}, bridge)
    s0 = out["sentences"][0]["tokens"]
    assert [t["known"] for t in s0] == [True, True]
    assert out["sentences"][1]["tokens"][0]["known"] is False
    stats = out["stats"]
    assert stats["known_tokens"] == 2
    assert stats["unknown_top"] == [{"lemma": "auto", "count": 1}]


def test_annotate_with_deck_empty_known_set_rank_and_cap(bridge):
    """空 deck（无已背词）：rate=0、unknown_top 按频率/先现排序、cap=10、punct/数字排除。"""
    deck = {"words": [], "cards": {}}
    annotate = {
        "text_id": 9,
        "total_tokens": 17,
        "sentences": [
            {
                "idx": 0,
                "tokens": [
                    {"text": "go", "lemma": "rep", "pos": "NOUN"},
                    {"text": "a1", "lemma": "aaa", "pos": "NOUN"},
                    {"text": "b1", "lemma": "bbb", "pos": "NOUN"},
                    {"text": "c1", "lemma": "ccc", "pos": "NOUN"},
                    {"text": "d1", "lemma": "ddd", "pos": "NOUN"},
                    {"text": "e1", "lemma": "eee", "pos": "NOUN"},
                    {"text": "f1", "lemma": "fff", "pos": "NOUN"},
                    {"text": "g1", "lemma": "ggg", "pos": "NOUN"},
                    {"text": "h1", "lemma": "hhh", "pos": "NOUN"},
                    {"text": "i1", "lemma": "iii", "pos": "NOUN"},
                    {"text": "j1", "lemma": "jjj", "pos": "NOUN"},
                    {"text": "k1", "lemma": "kkk", "pos": "NOUN"},
                    {"text": "l1", "lemma": "lll", "pos": "NOUN"},
                    {"text": "m1", "lemma": "mmm", "pos": "NOUN"},
                    {"text": "go2", "lemma": "rep", "pos": "NOUN"},
                    {"text": ",", "lemma": ",", "pos": "PUNCT"},
                    {"text": "3", "lemma": "3", "pos": "NUM"},
                ],
            },
        ],
    }
    out = _run_node({"op": "annotateWithDeck", "deck": deck, "annotate": annotate}, bridge)
    stats = out["stats"]
    assert stats["total_tokens"] == 17
    assert stats["known_tokens"] == 0
    assert stats["known_rate"] == 0
    # top10：rep(count2) 居首，其后 count=1 按首现顺序；逗号/数字不参与、被 cap 挤出
    assert stats["unknown_top"] == [
        {"lemma": "rep", "count": 2},
        {"lemma": "aaa", "count": 1},
        {"lemma": "bbb", "count": 1},
        {"lemma": "ccc", "count": 1},
        {"lemma": "ddd", "count": 1},
        {"lemma": "eee", "count": 1},
        {"lemma": "fff", "count": 1},
        {"lemma": "ggg", "count": 1},
        {"lemma": "hhh", "count": 1},
        {"lemma": "iii", "count": 1},
    ]
    assert len(stats["unknown_top"]) == 10


# ── mergeServerDeck：本地为准 ───────────────────────────────────────────────


def test_merge_server_deck_adds_server_only_and_keeps_local(bridge):
    """mergeServerDeck：server-only 词补进；本地已存在词/卡冲突保留本地。"""
    deck = {
        "words": [{"id": "w1", "hw": "gehen", "gloss": "local-gloss"}],
        "cards": {"w1": {"reps": 1, "src": "local"}},
    }
    server = {
        "words": [
            {"id": "w1", "hw": "gehen", "gloss": "server-gloss"},
            {"id": "w2", "hw": "Haus"},
            {"id": "w3", "hw": "Auto"},
        ],
        "cards": {
            "w1": {"reps": 9, "src": "server"},  # 冲突 → 保留本地
            "w2": {"reps": 1},  # 无本地 → 补进
        },
    }
    out = _run_node({"op": "mergeServerDeck", "deck": deck, "server": server}, bridge)
    merged = out["result"]
    by_id = {w["id"]: w for w in merged["words"]}
    # 本地词保 local-gloss（不覆盖）
    assert by_id["w1"]["gloss"] == "local-gloss"
    # server-only 词补进
    assert set(by_id.keys()) == {"w1", "w2", "w3"}
    # 卡冲突保留本地 reps=1；server-only 卡 w2 补进
    assert merged["cards"]["w1"]["reps"] == 1
    assert merged["cards"]["w1"]["src"] == "local"
    assert merged["cards"]["w2"]["reps"] == 1


# ── 前端接线静态探针 ───────────────────────────────────────────────────────


def test_index_has_coverage_container():
    """index.html 必须含 #enc-coverage 覆盖统计容器（静态存在，encounter.js 往里面写）。"""
    assert 'id="enc-coverage"' in INDEX


def test_encounter_js_imports_deck_bridge_module():
    """encounter.js 必须 import './deck-bridge.js'（模块图可达 + deck 纯函数接线）。"""
    assert "./deck-bridge.js" in ENCOUNTER_JS
    assert "loadDeck" in ENCOUNTER_JS
    assert "annotateWithDeck" in ENCOUNTER_JS


def test_encounter_js_consumes_annotate_endpoint():
    """encounter.js 必须消费 annotate 端点（Promise.all 拉注解数据）。"""
    assert "/annotate" in ENCOUNTER_JS
    assert "Promise.all" in ENCOUNTER_JS


def test_encounter_js_idb_double_write_on_add_card():
    """评审 ① 静态探针：进卡成功路径必须双写 IndexedDB（与 workbench F2 同库
    db "wb"、store words、单条 key "main"），否则手机/离线清 localStorage 后
    新词会丢。encIdbWriteWords 调用出现在 setItem 之后（写成功才双写）。
    """
    assert "encIdbWriteWords" in ENCOUNTER_JS
    assert 'indexedDB.open("wb", 1)' in ENCOUNTER_JS
    assert '"words"' in ENCOUNTER_JS
    assert '{ key: "main", value: words }' in ENCOUNTER_JS


def test_encounter_js_403_adding_hint_in_human_words():
    """评审 ⑦ 静态探针：POST /texts 仅本机放行（_require_localhost），手机/
    局域网端点添加会 403。UI 需把人话提示做进两处：提交失败的 catch 文案 +
    空列表引导，别让用户以为功能坏了。
    """
    assert "仅允许本机" in ENCOUNTER_JS
    assert "新增短篇仅限运行本服务的电脑本机操作" in ENCOUNTER_JS
    assert "电脑本机点右上" in ENCOUNTER_JS


# ── deck-bridge.js 源码卫生（node 可测性硬约束）────────────────────────────


def _strip_js_comments(src):
    """把 // 与 /* */ 注释剥掉，便于只对"真实代码"做卫生断言（注释不影响 Node 解析）。"""
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


def test_deck_bridge_source_is_esm_clean():
    """deck-bridge.js 可执行代码不得 import、不得碰浏览器全局（保证 .js→.mjs 直读可跑）。

    注释里允许解释 localStorage/window 注入约定，因此先剥注释再扫代码体。
    """
    src = _strip_js_comments(DECK_BRIDGE_SRC.read_text(encoding="utf-8"))
    assert "import " not in src, "deck-bridge.js 顶层不得有 import（node 直读需 ESM 纯净）"
    # 浏览器全局只能惰性出现在函数体里（storage 参数注入），不得模块顶层引用
    for glob in ("localStorage", "window.", "document."):
        assert glob not in src, "deck-bridge.js 不得引用浏览器全局：%r" % glob
    for fn in ("loadDeck", "mergeServerDeck", "buildKnownSet", "isKnown", "annotateWithDeck"):
        assert ("export function " + fn) in src or ("export const " + fn) in src, "deck-bridge.js 缺导出 %r" % fn
