# -*- coding: utf-8 -*-
"""遇见区 i+1 硬不变量 I-1：索引端点与 annotate 端点「逐 token 口径完全同源」（端到端）。

本文件钉死的命题
----------------
服务端**预计算**的 `pack_json.analysis.lemma_seq` / `tokens_total`（由离线脚本用
`process_german_text` 生成，见 tools/build_encounter_seed.py）与 annotate 端点**运行时**
逐 token 产出的 lemma 序列，是**同一口径**：

- 同源口径：遍历每句 tokens、**剔除 `is_space` 空白 token、保留标点 token**。
- 因此前端用「索引端点返回的 lemma_seq」在本机算出的覆盖率，与阅读页用 annotate 逐 token
  产出的覆盖率，**必然逐位一致**——这是 i+1 就近选材不产生「选材/展示打架」的前提。

强形式断言（比"rate 相等"更强）
------------------------------
对每个预置包（遍历全部 `PRESET_ENCOUNTER_PACKS`，至少 7 篇）：
1. `import_encounter_pack` 落库取 id；
2. annotate → 抽 `sentences[].tokens[]` 剔除 `is_space` 后的 lemma 有序列表 `annotate_lemmas`；
3. index → 取该项 `lemma_seq` 与 `total_tokens`；
4. **`index.lemma_seq == annotate_lemmas`（逐元素、全序列相等）**；
5. **`index.total_tokens == annotate["total_tokens"]`**；
6. 用**同一** known 集合（取自 annotate_lemmas 的前 1/3 个不同 lemma，**再按
   `static/js/deck-bridge.js` 的生产语义归一**（剥冠词 + 小写）构成 known 集合）
   分别算 `annotate_rate` 与 `index_rate`，**逐位相等（==，非近似）**。

降级一致性
----------
手工短文（`create_encounter_text`，无 pack_json）→ index 该项 `total_tokens is None and
lemma_seq is None`，**且仍在 items 内**（端到端链路对"未分析行"的降级一致）。

隔离纪律（对齐 test_encounter_index.py / test_encounter_seed.py）
----------------------------------------------------------------
模块顶部先钉 `DATABASE_PATH` / `PROGRESS_DB_PATH` 再 import server；autouse fixture 建
tmp_path 临时双库；**绝不碰仓库根 `delector.db`**；Windows 句柄释放：删文件前 gc.collect()。

口径漂移红线
------------
本用例若因**真实口径差异**变红（annotate 与离线产包不一致），是产品缺陷信号，
**禁止**用近似/容差"修好"——须回到两侧（tools/build_encounter_seed.py::_annotate_lemma_seq
与 delector/routes/encounter.py::_annotate_tokens）对齐口径。
"""

import gc
import os
import re
from pathlib import Path

import pytest

# 先钉 env 再 import server（模块级 create_app 的 init_db 有副作用），对齐既有测试。
os.environ.setdefault("DATABASE_PATH", "test_encounter_i1_consistency.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_i1_consistency_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.data.encounter_seed_dict import PRESET_ENCOUNTER_PACKS  # noqa: E402
from delector.server import app  # noqa: E402

_INDEX_ENDPOINT = "/api/encounter/texts/index"


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB（encounter + progress）；yield 出 encounter 路径。"""
    _db = str(tmp_path / "encounter_i1_consistency.db")
    _pdb = str(tmp_path / "encounter_i1_consistency_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    yield _db
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client():
    """默认 TestClient：index / annotate 两端点均未挂本机闸，默认来源即可打。"""
    return TestClient(app)


# ── 口径抽取：与 _annotate_tokens 同源（剔除 is_space、保留标点） ──────────────


def _annotate_lemmas(payload):
    """从 annotate 响应抽「剔除 is_space 后」的 lemma 有序列表（标点 lemma 保留）。"""
    return [
        tok["lemma"]
        for sentence in payload["sentences"]
        for tok in sentence["tokens"]
        if not tok.get("is_space")
    ]


_GERMAN_ARTICLES: tuple[str, ...] = (
    "der", "die", "das", "ein", "eine", "eines", "einer", "einem", "einen",
    "den", "dem", "des",
)


def _strip_german_article(hw: str) -> str:
    """去德语冠词/格后缀/标点，返回核心词。

    与 ``static/js/deck-bridge.js::stripGermanArticle`` **同源**（零 import 硬约束下
    只能复制，两处改动须同步）。冠词表（第 2 步）由
    ``test_article_list_matches_deck_bridge_source`` 双向守卫（改任一侧即红）；
    第 3–5 步无自动守卫，改动时须与 JS 源逐条人工比对。
    规则逐条镜像 JS 源：
    1) ``trim()``；
    2) 删前导冠词 ``^(der|die|…)\\s+``（``re.I``）；
    3) 删 ``[,，·.].*\\Z``（逗号/中文逗号/间隔号/点起至字符串末尾；JS 的 ``$``
       无 ``m`` 标志 = 字符串末尾，此处以 ``\\Z`` 忠实镜像其语义源。**但注意**：
       在**本函数内** ``\\Z`` 与 ``$`` 行为完全等价——开头 ``trim()`` 已剥掉尾随
       换行，任何经由本函数的输入都无法判别二者；``\\Z`` 只是更贴近 JS 源写法的
       忠实镜像，并非有可观测差异的行为修正）；
    4) 删尾部破折号段 ``\\s*[–—-]+\\s*[^\\s]*\\Z``（同理用 ``\\Z``）；
    5) 仅保留 ``[A-Za-zÄÖÜäöüß\\s\\-']``；
    6) ``trim()``。空输入返回空串。
    """
    if not hw:
        return ""
    s = str(hw).strip()
    s = re.sub(
        r"^(der|die|das|ein|eine|eines|einer|einem|einen|den|dem|des)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"[,，·.].*\Z", "", s)
    s = re.sub(r"\s*[–—-]+\s*[^\s]*\Z", "", s)
    s = re.sub(r"[^A-Za-zÄÖÜäöüß\s\-']", "", s)
    return s.strip()


def _coverage_rate(seq, known, total):
    """覆盖率 = 命中 known 的 token 数 / total。

    与 ``static/js/enc-i1.js::coverageOf`` **同口径**：分母用 ``total_tokens``，
    双方成员判断均**小写**（``knownSet.has(String(l).toLowerCase())``）。
    """
    if not total:
        return 0.0
    known_tokens = sum(1 for lemma in seq if str(lemma).lower() in known)
    return known_tokens / total


def _first_third_known_set(seq):
    """取序列中不同 lemma 的前 1/3，再按 ``deck-bridge.js`` 生产语义归一为 known 集合。

    生产 known 集合（``buildKnownSet``）的元素是 ``stripGermanArticle(hw).lower()``
    ——**全小写、无标点、无冠词**；故本夹具对每个 lemma 走 ``_strip_german_article``
    后 ``.lower()`` 入集合，并丢掉空串。返回 ``set[str]``（生产形状）。
    """
    distinct = []
    for lemma in seq:
        if lemma not in distinct:
            distinct.append(lemma)
    k = max(1, len(distinct) // 3)
    known = {
        norm
        for norm in (
            _strip_german_article(str(lemma)).lower() for lemma in distinct[:k]
        )
        if norm
    }
    return known


# ── ① I-1 硬不变量：逐包端到端同源 ───────────────────────────────────────────


def test_preset_packs_cover_at_least_seven():
    """前置：本不变量至少覆盖 7 篇预置（A1×2 + A2×2 + B1×3）。"""
    assert len(PRESET_ENCOUNTER_PACKS) >= 7, f"预置包应 >= 7，实际 {len(PRESET_ENCOUNTER_PACKS)}"


@pytest.mark.parametrize(
    "pack",
    PRESET_ENCOUNTER_PACKS,
    ids=[p["pack_id"] for p in PRESET_ENCOUNTER_PACKS],
)
def test_index_lemma_seq_is_bit_identical_to_annotate(client, clean_db, pack):
    """I-1：index.lemma_seq 与 annotate 逐 token lemma 序列**全序列相等**；rate 逐位相等。

    任一处漂移（is_space 过滤缺失 / 标点被丢 / 大小写或词形还原不一致）→ 本用例必红。
    """
    text_id = database.import_encounter_pack(pack, db_path=clean_db)

    # annotate：运行时逐 token（spaCy 直跑）
    resp = client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert resp.status_code == 200, resp.text
    annotate = resp.json()
    annotate_lemmas = _annotate_lemmas(annotate)

    # index：预计算口径（读库内 pack_json.analysis）
    index_resp = client.get(_INDEX_ENDPOINT)
    assert index_resp.status_code == 200, index_resp.text
    item = next(it for it in index_resp.json()["items"] if it["id"] == text_id)

    # ④ 逐元素、全序列相等（最强形式）
    assert item["lemma_seq"] == annotate_lemmas, f"{pack['pack_id']}: index.lemma_seq 与 annotate 逐 token 序列不一致"
    # ⑤ 分母相等
    assert item["total_tokens"] == annotate["total_tokens"], f"{pack['pack_id']}: total_tokens 分母不一致"
    # 自洽：序列长度 == 分母
    assert len(item["lemma_seq"]) == item["total_tokens"]

    # ⑥ 同一 known 集合 → 两处 rate 逐位相等（== 而非近似）
    known = _first_third_known_set(annotate_lemmas)
    assert known, f"{pack['pack_id']}: known 集合不得为空"
    annotate_rate = _coverage_rate(annotate_lemmas, known, annotate["total_tokens"])
    index_rate = _coverage_rate(item["lemma_seq"], known, item["total_tokens"])
    assert annotate_rate == index_rate, f"{pack['pack_id']}: 覆盖率口径漂移 annotate={annotate_rate} index={index_rate}"


# ── ② 未分析行（手工短文）降级一致性：None 但仍在 items 内 ─────────────────────


def test_manual_text_end_to_end_degrades_consistently(client, clean_db):
    """手工短文（无 pack_json）：index 该项两字段 None 且仍出现；annotate 仍可正常产出。"""
    manual_id = database.create_encounter_text(
        title="Handschrift",
        level="A2",
        source="manual",
        content="Ein kurzer Satz auf Deutsch.",
        db_path=clean_db,
    )

    index_resp = client.get(_INDEX_ENDPOINT)
    assert index_resp.status_code == 200
    items = index_resp.json()["items"]
    row = next((it for it in items if it["id"] == manual_id), None)
    assert row is not None, "手工短文必须出现在索引里（不丢行）"
    assert row["total_tokens"] is None
    assert row["lemma_seq"] is None

    # annotate 侧对同一行仍照常逐 token 产出（链路未因"未分析"而断裂）
    resp = client.get(f"/api/encounter/texts/{manual_id}/annotate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_tokens"] > 0


# ── ③ 生产语义守卫：剥冠词镜像同源 + 查找侧小写口径 ──────────────────────────


def test_article_list_matches_deck_bridge_source():
    """同源守卫：本模块 `_GERMAN_ARTICLES` 必须与 deck-bridge.js 的冠词捕获组一致。

    零 import 硬约束下 `_strip_german_article` 只能复制 JS 源；本守卫读 JS 源取出
    第一处 ``replace(/^(der|die|…)\\s+/i`` 捕获组，去重后与本模块常量逐字比对，
    防止两处漂移。**失败即表示两处须同步**。
    """
    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "static" / "js" / "deck-bridge.js").read_text(encoding="utf-8")
    m = re.search(r"replace\(/\^\((der\|die\|[^)]+)\)\\s\+/i", src)
    assert m is not None, (
        "未能在 static/js/deck-bridge.js 定位前导冠词捕获组——"
        "两处须同步（该 JS 源或本模块 _GERMAN_ARTICLES 已漂移）"
    )
    js_articles = set(m.group(1).split("|"))
    assert js_articles == set(_GERMAN_ARTICLES), (
        "static/js/deck-bridge.js::stripGermanArticle 的冠词表与本模块 _GERMAN_ARTICLES "
        f"漂移，两处须同步：JS={sorted(js_articles)} Python={sorted(_GERMAN_ARTICLES)}"
    )


def test_known_lookup_is_case_insensitive_and_article_stripped():
    """行为钉：剥冠词（deck-bridge 同源）+ 查找侧小写（enc-i1 同口径）双语义。

    任一规则漏掉（未剥冠词 / 未 `.lower()`）→ 本用例必红。
    """
    # 剥前导冠词
    assert _strip_german_article("die Abfahrt") == "Abfahrt"
    assert _strip_german_article("der Samstag") == "Samstag"
    # 剥逗号后缀
    assert _strip_german_article("das Abenteuer,") == "Abenteuer"
    # 剥尾部破折号段
    assert _strip_german_article("Bahnhof –") == "Bahnhof"

    # 大写 lemma 必须命中"剥冠词后小写"的 known —— 任一侧漏 .lower() 即红
    assert _coverage_rate(["Samstag"], {"samstag"}, 1) == 1.0
