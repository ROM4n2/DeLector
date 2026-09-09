# -*- coding: utf-8 -*-
"""`GET /api/encounter/texts/{text_id}/annotate`（遇见区 i+1 Task A3）。

契约面（delector/routes/encounter.py，annotate 端点走默认 env DB 路径）：
- GET  /api/encounter/texts/{text_id}/annotate → 200
  { "text_id": <id>, "total_tokens": N,
    "sentences": [ {"idx": 0, "tokens": [ {"text":"geht","lemma":"gehen","pos":"VERB"} ] } ] }
- text 缺失 → 404 {"detail":"短文未找到: <id>"}
- 语义：按数据库正文字面逐句逐 token 产出 lemma（spaCy 小写）+ 粗粒度 POS（VERB/NOUN/...）。
- 标点也保留（前端自己 filter），total_tokens = 各句 token 数之和，sentence idx 0-based 顺序。

隔离纪律（对齐 test_encounter_routes.py）：autouse fixture 把 DATABASE_PATH /
PROGRESS_DB_PATH 钉到 tmp_path throwaway 文件并 init_db；Windows 句柄释放：删文件前
gc.collect()。TestClient 本机闸：client=("127.0.0.1",..) 放行（POST 建行需要）。

analyze/既有 NLP 契约零漂移保证：annotate 不改动 process_german_text 的返回结构，
只把它产出的 tokens（已含 text/lemma/pos）映射成新 shape，因此 test_tools.py 跑过
即证明 analyze 契约无漂移。
"""
import gc
import os

import pytest

# 先钉 env 再 import server（模块级 create_app 的 init_db 有副作用）
os.environ.setdefault("DATABASE_PATH", "test_encounter_annotate.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_annotate_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.server import app  # noqa: E402
from delector.core import database  # noqa: E402
from delector.nlp_engine import processor as _enc_nlp  # noqa: E402


def _de_spacy_model_loaded() -> bool:
    """annotate 跑 process_german_text → processor 模块级 nlp（spaCy 德模）。

    'geht'→'gehen' 是 spaCy 真实词形还原，德模缺席时处理器静默降级纯 Python
    （lemma 退化成 'geht'）。这里钉的是「真模型是否生效」，与 test_writing_rules.py
    对 de_core_news_sm 缺席就 pytest.skip 的纪律一致：模型不在就干净跳过，
    不让真实词形用例在降级路径上误报绿/红。
    """
    return _enc_nlp.NLP_ENGINE == "spacy" and _enc_nlp.nlp is not None


_SKIP_NO_DE_MODEL = pytest.mark.skipif(
    not _de_spacy_model_loaded(),
    reason="spaCy 德语模型（de_core_news_sm/md）不可用，跳过真实词形还原用例",
)


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB（encounter + progress）。"""
    _db = str(tmp_path / "encounter_annotate.db")
    _pdb = str(tmp_path / "encounter_annotate_progress.db")
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
    yield
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
def local_client():
    """显式本机来源：命中 _require_localhost 放行分支（annotate 本身无闸，POST 建行需要）。"""
    return TestClient(app, client=("127.0.0.1", 54321))


def _create_text(client, content="Das ist ein Test.", title="t"):
    resp = client.post(
        "/api/encounter/texts",
        json={"title": title, "level": "A2", "source": "manual", "content": content},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 响应结构 ────────────────────────────────────────────────────────────────

def test_annotate_returns_expected_shape(local_client):
    """200：text_id/total_tokens/sentences 结构齐全，token 均带 text/lemma/pos 三键。"""
    text_id = _create_text(local_client, content="Die Katze schläft.")
    resp = local_client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"text_id", "total_tokens", "sentences"}
    assert body["text_id"] == text_id
    assert body["total_tokens"] > 0
    assert isinstance(body["sentences"], list) and body["sentences"]
    for s in body["sentences"]:
        assert set(s.keys()) == {"idx", "tokens"}
        for tok in s["tokens"]:
            assert {"text", "lemma", "pos"} <= set(tok.keys())


# ── 德语真实词形：geht → gehen（de_core_news_sm 真 lemma） ───────────────────

@_SKIP_NO_DE_MODEL
def test_annotate_german_lemma_gehen(local_client):
    """含 'geht' 的句子必须产出 lemma=='gehen'（spaCy 真实词形还原）。"""
    text_id = _create_text(local_client, content="Er geht heute nach Hause.")
    resp = local_client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert resp.status_code == 200
    lemmas = [
        tok["lemma"]
        for s in resp.json()["sentences"]
        for tok in s["tokens"]
        if tok["text"] == "geht"
    ]
    assert lemmas, "'geht' 应出现在 token 流中"
    assert lemmas[0] == "gehen"


# ── 句索引 0-based 顺序 + total_tokens == 各句 token 数之和 ────────────────

def test_annotate_sentence_indices_and_total(local_client):
    """多句：idx 0-based 顺序，total_tokens == 各句 token 数之和。"""
    content = "Der Hund beißt den Mann. Die Katze schläft gern."
    text_id = _create_text(local_client, content=content)
    resp = local_client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert resp.status_code == 200
    body = resp.json()
    sentences = body["sentences"]
    assert [s["idx"] for s in sentences] == list(range(len(sentences)))
    assert body["total_tokens"] == sum(len(s["tokens"]) for s in sentences)
    assert body["total_tokens"] > 0


def test_annotate_punctuation_included(local_client):
    """标点 token 保留（用其真实 lemma/pos），不跳过——前端自行 filter。"""
    text_id = _create_text(local_client, content="Hallo, Welt!")
    resp = local_client.get(f"/api/encounter/texts/{text_id}/annotate")
    assert resp.status_code == 200
    texts = [tok["text"] for s in resp.json()["sentences"] for tok in s["tokens"]]
    assert "," in texts and "!" in texts


# ── 404 ─────────────────────────────────────────────────────────────────────

def test_annotate_missing_text_404(local_client):
    """不存在的 text_id → 404 中文 detail。"""
    resp = local_client.get("/api/encounter/texts/99999/annotate")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "短文未找到: 99999"
