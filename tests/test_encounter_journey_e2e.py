# -*- coding: utf-8 -*-
"""A7 服务端全链路 E2E：把「背词 → 加短文 → 逐词注解 → 离线取义 → 进卡镜像回读」
的服务端可观测段串成一条自动验收。

这是原「A7 双端手工冒烟六步」中**服务端可观测段**的自动化第一步（T1）：
   ①背词工作台背 ≥3 词使 reps>0        → 用例 1（deck 镜像写入，含 ≥3 个 reps>0 词）
   ②遇见区加一篇短文                    → 用例 2（POST /api/encounter/texts）
   ③打开详情断言已背词高亮 + 覆盖数>0  → 用例 3（annotate + 服务端等价 known/unknown 匹配）
   ④点未知词出本地词典释义              → 用例 4（/api/lookup/vocab 本地词典分支，纯离线）
   ⑤点「加入卡片」写 deck 并触发 wb 同步 → 用例 5（进卡后 PUT + 回读，服务端等价物）
   ⑥重开工作台断言新词进入新词池        → 用例 5 的镜像回读（word-only 进卡语义）
安全回归：用例 6（不带 key 的 PUT 被拒，闸不退化）。

设计原则（Vault PYTHON-STANDARDS §8.2）：
- 尽量少 mock，走真实路由 + 真实 DB（tmp 双库）。
- 每条断言验证具体状态码/字段/错误类型；禁止「不抛异常即过」「非空即过」的假绿。
- 用例 4 把 AI 兜底 tier 的 key 与网络出口 monkeypatch 成抛错，证明本地词典分支
  纯离线、不依赖网络（红线 9 精神）。

已知/未知匹配的服务端等价物（关键）：
    真实的「已背词高亮」由前端 deck-bridge.js 的 buildKnownSet 完成：
        knownSet = { stripGermanArticle(w.hw).toLowerCase() | cards[id].reps > 0 }
        isKnown(lemma) = knownSet.has(lemma.toLowerCase())
    本测试不跑 JS，故在 Python 里复刻同一语义（见 `_build_known_set`），
    用与 deck 对应的词表设计正文，保证 known / unknown 两边都**确定非空**。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_journey_e2e.py -v
"""
import gc
import os

import pytest
from fastapi.testclient import TestClient

# env 双钉必须在 import app 之前：database.get_db_path() 每次调用读 os.environ。
os.environ["DATABASE_PATH"] = "test_delector.db"
os.environ["PROGRESS_DB_PATH"] = "test_progress.db"

from delector.server import create_app, init_db  # noqa: E402

# 正文设计：包含确定「已背词」（Mann / gehen，进 deck 且有 reps>0）与
# 确定「未背词」（Schule，正文出现但不在 deck；unverzagt 更极端——连词典都没有）。
ARTICLE = "Der Mann geht unverzagt in die Schule."

# deck payload：words 与 cards 同源，与 deck-bridge 的真实形状对齐
# （words: [{id, hw, pos, gloss, ...}]；cards: {id: {reps, ...}}）。
# 三个 reps>0 词 —— 满足 A7 第①步「背 ≥3 词」。
_DECK_WORDS = [
    {"id": "u-mann", "hw": "Mann", "pos": "NOUN", "gloss": "男人"},
    {"id": "u-gehen", "hw": "gehen", "pos": "VERB", "gloss": "走，去"},
    {"id": "u-wasser", "hw": "Wasser", "pos": "NOUN", "gloss": "水"},
]
_DECK_CARDS = {
    "u-mann": {"reps": 4, "lapses": 0},
    "u-gehen": {"reps": 3, "lapses": 1},
    "u-wasser": {"reps": 2, "lapses": 0},
}
DECK_PAYLOAD = {"words": _DECK_WORDS, "cards": _DECK_CARDS}


def _strip_german_article(hw: str) -> str:
    """复刻 deck-bridge.js stripGermanArticle：剥德语冠词前缀。"""
    s = (hw or "").strip()
    low = s.lower()
    for art in ("der ", "die ", "das "):
        if low.startswith(art):
            return s[len(art):]
    return s


def _build_known_set(deck: dict) -> set:
    """复刻 deck-bridge.js buildKnownSet：仅收 reps>0 的词，剥冠词再小写。"""
    known = set()
    words = deck.get("words") if isinstance(deck, dict) else None
    cards = deck.get("cards") if isinstance(deck, dict) else None
    for w in words or []:
        if not isinstance(w, dict) or w.get("id") is None or w.get("hw") is None:
            continue
        card = (cards or {}).get(str(w["id"]))
        if isinstance(card, dict) and int(card.get("reps", 0)) > 0:
            known.add(_strip_german_article(str(w["hw"])).lower())
    return known


def _is_known(known_set: set, lemma: str) -> bool:
    """复刻 deck-bridge.js isKnown：lemma 小写后是否命中。"""
    return bool(lemma) and str(lemma).lower() in known_set


@pytest.fixture(autouse=True)
def clean_db():
    """每次测试前后删库重建 + gc.collect（Windows 句柄纪律，见 test_server.py）。"""
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = "test_delector.db"
    os.environ["PROGRESS_DB_PATH"] = "test_progress.db"
    gc.collect()
    for f in ("test_delector.db", "test_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    init_db("test_delector.db")
    yield
    gc.collect()
    for f in ("test_delector.db", "test_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client():
    """本机来源地址：POST /texts 与 /state/key 有 _require_localhost 闸。"""
    app = create_app()
    return TestClient(app, client=("127.0.0.1", 54321))


def _put_deck(client, payload: dict):
    """取 key 后带 X-WB-Key 写入 deck 镜像，返回 PUT 响应。"""
    key = client.get("/api/wb/state/key").json()["key"]
    return client.put("/api/wb/state", json={"payload": payload},
                      headers={"X-WB-Key": key})


# ── 用例 1：deck 镜像写入（A7 第①步）────────────────────────────────────────
def test_1_deck_mirror_write_with_three_reps_positive(client):
    """写入含 ≥3 个 reps>0 词的 deck，断言 200 且 GET 回读一致。"""
    reps_positive = [k for k, v in DECK_PAYLOAD["cards"].items() if v["reps"] > 0]
    assert len(reps_positive) >= 3, "夹具应先满足 A7 第①步：≥3 个 reps>0 词"

    res = _put_deck(client, DECK_PAYLOAD)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["updated_at"], str) and body["updated_at"], \
        "PUT 应返回非空 updated_at 时间戳"

    got = client.get("/api/wb/state")
    assert got.status_code == 200
    assert got.json() == DECK_PAYLOAD, "回读的镜像必须与写入逐字段一致"


# ── 用例 2：加短文（A7 第②步）──────────────────────────────────────────────
def test_2_add_article_and_visible_in_list(client):
    """POST 建德语短文断言 201 与返回 id；GET 列表可见该 id。"""
    res = client.post("/api/encounter/texts", json={
        "title": "Der unverzagte Mann",
        "level": "A2",
        "source": "e2e",
        "content": ARTICLE,
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["title"] == "Der unverzagte Mann"
    assert body["level"] == "A2", "level 应被规一为大写白名单值"

    listing = client.get("/api/encounter/texts")
    assert listing.status_code == 200
    ids = [t["id"] for t in listing.json()["texts"]]
    assert body["id"] in ids, "新建短文必须出现在列表里"
    row = next(t for t in listing.json()["texts"] if t["id"] == body["id"])
    assert row["level"] == "A2"
    assert row["word_count"] == len(ARTICLE.split()), "word_count 应等于空白分词数"


# ── 用例 3：逐词注解 + known/unknown 双向断言（A7 第③步）──────────────────
def test_3_annotate_has_known_and_unknown_tokens(client):
    """annotate 结构完整、total_tokens>0，且已知/未知两面**都确定非空**。"""
    create = client.post("/api/encounter/texts", json={
        "title": "Annotate Me", "level": "A2", "content": ARTICLE,
    })
    text_id = create.json()["id"]

    res = client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["text_id"] == text_id
    assert data["total_tokens"] > 0, "正文非空，token 总数必须 >0"
    assert isinstance(data["sentences"], list) and data["sentences"], \
        "至少应解析出一句"

    # 结构断言：每句有 idx 与 tokens；每个 token 有 text/lemma/pos 三字段。
    for sent in data["sentences"]:
        assert "idx" in sent and isinstance(sent["tokens"], list)
        for tok in sent["tokens"]:
            assert set(("text", "lemma", "pos")).issubset(tok.keys())

    total_tokens = sum(len(s["tokens"]) for s in data["sentences"])
    assert data["total_tokens"] == total_tokens, \
        "total_tokens 必须等于各句 token 数之和"

    # 服务端等价「已背词高亮」：用 deck 的 knownSet 对 annotate 的 lemma 做匹配。
    known_set = _build_known_set(DECK_PAYLOAD)
    assert "mann" in known_set and "gehen" in known_set, \
        "夹具前提：Mann / gehen 是已背词（reps>0）"

    known_lemmas, unknown_lemmas = [], []
    for sent in data["sentences"]:
        for tok in sent["tokens"]:
            lemma = tok["lemma"]
            if not lemma or lemma == "--":
                continue
            (known_lemmas if _is_known(known_set, lemma) else unknown_lemmas).append(lemma)

    assert "mann" in [l.lower() for l in known_lemmas], \
        "正文里的已背词 Mann 必须被 annotate 出对应 lemma 并匹配为 known"
    assert "gehen" in [l.lower() for l in known_lemmas], \
        "正文里的已背词 gehen 必须被 annotate 出对应 lemma 并匹配为 known"
    # 未背词：schule（不在 deck）必须出现在 unknown 一侧。
    assert any(l.lower() == "schule" for l in unknown_lemmas), \
        "正文里的未背词 Schule 必须落在 unknown 一侧（known/unknown 双向非空）"
    assert any(l.lower() == "unverzagt" for l in unknown_lemmas), \
        "正文里的生词 unverzagt 必须落在 unknown 一侧"


# ── 用例 4：本地词典释义，纯离线（A7 第④步，红线 9）──────────────────────
def test_4_local_dict_lookup_is_offline(client, monkeypatch):
    """本地词典分支：命中具体释义/词性字段，且网络 tier 被证明不参与。

    Schule 在正文里出现但不在 deck（对学习者未知），却在本地核心词库中。
    把 API key 设为伪值、并把 httpx 出口打桩成抛错：若实现偷偷走了网络，
    该用例必红 —— 从而证明本地词典分支纯离线。
    """
    # 前提：Schule 确实不在 deck（学习者未背），否则证明不了「未知词取义」。
    known_set = _build_known_set(DECK_PAYLOAD)
    assert not _is_known(known_set, "schule"), "前提：schule 不在已背词集合里"

    # 迫使 AI 兜底 tier「有条件触发」：给一个伪 key。
    monkeypatch.setattr(
        "delector.routes.main.get_effective_api_key", lambda *a, **k: "test-fake-key"
    )

    # 网络出口一律惊雷：本地命中则永不触达。
    class _BoomClient:
        def __init__(self, *a, **k):
            raise AssertionError("本地词典分支不应构造网络客户端（离线红线）")

    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", _BoomClient)

    res = client.post("/api/lookup/vocab", json={
        "sentence": ARTICLE, "target_word": "Schule", "lemma": "schule",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "local_dict", \
        "应命中本地词典分支（source=local_dict），而非 none/ai"
    assert body["definition_zh"], "本地词典分支必须给出非空中文释义"
    assert "学校" in body["definition_zh"], "Schule 的本地释义应含「学校」"
    assert body["pos"] == "NOUN", "本地词典分支应带具体词性"
    assert body["cefr_level"] == "A1", "本地词典分支应带具体 CEFR 等级"
    assert body["gender"] == "Fem", "本地词典分支应带名词性别"
    assert body["plural"] == "-n", "本地词典分支应带复数形式"


# ── 用例 5：进卡后镜像回读（A7 第⑤⑥步的服务端等价物）────────────────────
def test_5_add_card_then_mirror_readback(client):
    """模拟进卡后的 deck（words 追加一词、cards 不变）→ 回读断言新词在案。"""
    _put_deck(client, DECK_PAYLOAD)

    # 前端「加入卡片」= 只写 word、绝不建卡（word-only 语义，对齐工作台新词池真值）。
    new_word = {"id": "u-unverzagt", "hw": "unverzagt", "pos": "ADV", "gloss": "毫不畏惧地"}
    after_deck = {
        "words": _DECK_WORDS + [new_word],
        "cards": dict(_DECK_CARDS),  # cards 语义不变（不建新卡）
    }

    res = _put_deck(client, after_deck)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    got = client.get("/api/wb/state")
    assert got.status_code == 200
    payload = got.json()
    assert payload == after_deck, "回读镜像应与进卡后的 deck 逐字段一致"

    hws = {w["hw"] for w in payload["words"]}
    assert "unverzagt" in hws, "进卡的新词应出现在回读的 payload.words 中"
    # 新词不建卡：cards 里不得出现它的 id（否则对新词池/复习队列都不可见）。
    assert "u-unverzagt" not in payload["cards"], \
        "word-only 进卡语义：新词不应在 cards 里建卡"


# ── 用例 6：安全回归——不带 key 的 PUT 被拒（闸不退化）─────────────────────
def test_6_put_without_key_is_rejected(client):
    """不带 X-WB-Key 的 PUT /api/wb/state 必须 403，且未污染镜像。"""
    # 先写入一份已知镜像，验证越权写没被落库。
    _put_deck(client, DECK_PAYLOAD)

    res = client.put("/api/wb/state", json={"payload": {"words": [{"id": "evil"}]}})
    assert res.status_code == 403, f"无 key 写入应被拒，实际 {res.status_code}"

    # 越权 payload 绝不应落库。
    got = client.get("/api/wb/state")
    assert got.json() == DECK_PAYLOAD, "被拒的写入不得污染镜像"

    # 错误 key 同样被拒（不只是「缺 header」这条分支）。
    bad = client.put("/api/wb/state", json={"payload": {"words": []}},
                     headers={"X-WB-Key": "0" * 32})
    assert bad.status_code == 403, f"错误 key 写入应被拒，实际 {bad.status_code}"
    assert client.get("/api/wb/state").json() == DECK_PAYLOAD
