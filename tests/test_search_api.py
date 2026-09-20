# -*- coding: utf-8 -*-
"""`GET /api/search` 路由契约测试（spec 2026-09-20 §3.3 / §3.5，Task 3）。

覆盖：
- 正常命中：`q=公寓`（中文两字词）/ `q=wohnung` → 200、四组键集完整、vocab 非空；
- 响应形状：`{q,scope,total,groups{4},truncated}`；
- 过短 `q`（`x`）→ 200 且四组空、`total==0`（不 500）；
- 非法 `scope` → 400（路由层校验）；合法五值均 200；
- `limit=999` 透传（search 内钳到 100，路由**不重复钳制**）；`limit=1` 每组 ≤1；
- `q` 缺失 → 422（FastAPI 必填校验）；
- 语料命中（`corpus` 组 + snippet）与 **truncated OR 合并**（CRV Y5）：语料 hard cap
  触发时必须为 True，且该场景**不因 limit 截断**——保证断言可区分（删掉 OR 必红）。

隔离纪律（对齐 `test_listen_api.py` / `test_search_service.py`）：
- `delector/server.py` 模块级单例 app 在收集期首次 import 即 `create_app()`
  （会 `init_db` + `seed_preset_articles`）；故 import 前先 `setdefault` 一个**测试名**的
  `DATABASE_PATH`，**绝不落到仓库根 `delector.db`**（否则 import 即污染真库）。
- autouse fixture 把 `DATABASE_PATH`/`PROGRESS_DB_PATH` 切到 `tmp_path` throwaway 文件并
  `init_db`；清理只清表不删库。
- 语料一律塞进 tmp 临时库；查询用合成 token（`Zorblax`），与真实词库零碰撞，避免真实
  分布导致断言漂移。
"""

import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_PATH", "test_search_api.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_search_api_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.server import app  # noqa: E402

_GROUP_KEYS = {"vocab", "example", "colloc", "corpus"}
# 与 service 的 `iter_corpus_docs(max_docs=...)` 默认值同源：路由不可传 cap，故靠塞够多
# 语料触发 hard cap（2001 篇 > max_docs 默认 2000）。
_CORPUS_MAX_DOCS_DEFAULT = 2000


@pytest.fixture(autouse=True)
def clean_db(tmp_path: Path):
    """每个用例独立 tmp_path 双 throwaway DB；清理只清表不删库。"""
    _db = str(tmp_path / "search_api.db")
    _pdb = str(tmp_path / "search_api_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    yield
    # 只清表不删库：模块级单例 app 与共享进程都依赖这些 env 指向的库文件仍在
    try:
        conn = database.get_db(_db)
        try:
            conn.execute("DELETE FROM articles")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client():
    """显式本机来源：命中 `_require_localhost` 放行分支（本路由只读无闸，仍保持一致）。"""
    return TestClient(app, client=("127.0.0.1", 54321))


def _seed_article(title: str, text: str) -> int:
    """直插一篇文章（绕过 `ingest_article` 的 spaCy 处理，测试只需 `raw_text`）。"""
    conn = sqlite3.connect(os.environ["DATABASE_PATH"])
    try:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            (title, text, "{}"),
        )
        conn.commit()
        assert cur.lastrowid is not None  # INSERT 后运行时恒为 int；收窄供 mypy
        return cur.lastrowid
    finally:
        conn.close()


def _seed_articles(count: int) -> None:
    """批量直插 `count` 篇填充文章（触发语料 hard cap 用）。"""
    conn = sqlite3.connect(os.environ["DATABASE_PATH"])
    try:
        conn.executemany(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            [(f"Fuellung {i}", f"Fuellungstext Nummer {i}.", "{}") for i in range(count)],
        )
        conn.commit()
    finally:
        conn.close()


# ── 正常命中 + 响应形状 ─────────────────────────────────────────────────────────


def test_response_shape_and_group_keys(client):
    """响应含 `q/scope/total/groups/truncated`，groups 键集固定为四类且均为列表。"""
    res = client.get("/api/search", params={"q": "wohnung"})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"q", "scope", "total", "groups", "truncated"}
    assert set(body["groups"]) == _GROUP_KEYS
    assert body["q"] == "wohnung"
    assert body["scope"] == "all"
    assert isinstance(body["total"], int)
    assert isinstance(body["truncated"], bool)
    assert all(isinstance(v, list) for v in body["groups"].values())


def test_chinese_two_char_query_hits_vocab(client):
    """中文两字词 `公寓` → vocab 组非空且含 `wohnung`（放弃 FTS5 的回归锚点）。"""
    res = client.get("/api/search", params={"q": "公寓"})
    assert res.status_code == 200
    lemmas = [d["lemma"] for d in res.json()["groups"]["vocab"]]
    assert "wohnung" in lemmas


# ── 过短 q（不报错） ───────────────────────────────────────────────────────────


def test_short_query_returns_empty_without_error(client):
    """`fold(q)` 后长度 <2（单字符）→ 200、四组空、`total==0`、绝不 500。"""
    res = client.get("/api/search", params={"q": "x"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["groups"] == {"vocab": [], "example": [], "colloc": [], "corpus": []}
    assert body["truncated"] is False


# ── scope 校验 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scope", ["all", "vocab", "example", "colloc", "corpus"])
def test_valid_scopes_accepted(client, scope):
    """合法五值均 200，且响应 `scope` 回显请求值。"""
    res = client.get("/api/search", params={"q": "wohnung", "scope": scope})
    assert res.status_code == 200
    assert res.json()["scope"] == scope


def test_invalid_scope_returns_400(client):
    """非法 `scope` → 400（路由层校验；service 纯函数不承担输入校验）。"""
    res = client.get("/api/search", params={"q": "wohnung", "scope": "bad"})
    assert res.status_code == 400


# ── limit（透传 + search 内钳制） ─────────────────────────────────────────────


def test_limit_high_does_not_error_and_is_capped(client):
    """`limit=999` 不报错；透传后在 search 内钳到 100 → 每组 ≤100（路由不重复钳制）。"""
    res = client.get("/api/search", params={"q": "en", "limit": 999})
    assert res.status_code == 200
    body = res.json()
    assert all(len(v) <= 100 for v in body["groups"].values())


def test_limit_one_caps_each_group(client):
    """`limit=1` → 每组 ≤1。"""
    res = client.get("/api/search", params={"q": "en", "limit": 1})
    assert res.status_code == 200
    body = res.json()
    assert all(len(v) <= 1 for v in body["groups"].values())


# ── q 必填校验 ────────────────────────────────────────────────────────────────


def test_missing_q_returns_422(client):
    """`q` 缺失 → 422（FastAPI 必填校验）。"""
    res = client.get("/api/search")
    assert res.status_code == 422


# ── 语料命中 + truncated OR 合并（CRV Y5） ───────────────────────────────────


def test_corpus_hit_appears_in_corpus_group_with_snippet(client):
    """语料命中 → corpus 组含该 doc + 有界 snippet；未截断时 `truncated is False`。"""
    # `init_db` 会连带 seed 4 篇预置文章（database.py），故 id 不假定为 1，取真实返回 id。
    aid = _seed_article("Zorblax Bericht", "Hier steht Zorblax im Fliesstext.")
    res = client.get("/api/search", params={"q": "Zorblax"})
    assert res.status_code == 200
    body = res.json()
    assert [d["id"] for d in body["groups"]["corpus"]] == [f"article:{aid}"]
    snippet = body["groups"]["corpus"][0]["payload"]["snippet"]
    assert "Zorblax" in snippet
    assert body["truncated"] is False


def test_corpus_hard_cap_truncated_or_merged_into_response(client):
    """**CRV Y5**：路由层把语料 hard cap 的 `truncated` 与 limit 截断按 OR 合并。

    构造：先插一篇命中合成 token 的文章（`init_db` seed 的 4 篇预置之后 → 落在前 2000 内），
    再塞满 2000 篇填充 → 总篇数 > `max_docs` 默认 2000，`iter_corpus_docs` 返回 `truncated=True`。
    查询用合成 token `Zorblax`（与真实词库零碰撞）→ 命中数 = 1，默认 `limit=20` 下
    `search()` 自身**不会**因 limit 截断。故 `truncated is True` **只能**来自语料 hard cap：
    删掉路由里的 `or corpus_truncated` 合并，则 `search()` 回落的 `False` 会让本断言必红
    （即本断言能区分「语料截断」与「limit 截断」）。
    """
    aid = _seed_article("Zorblax Bericht", "Hier steht Zorblax im Fliesstext.")
    _seed_articles(_CORPUS_MAX_DOCS_DEFAULT)  # 合计 > max_docs → 语料被截断
    res = client.get("/api/search", params={"q": "Zorblax"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1, "命中仅 1 条 → search 自身不因 limit 截断"
    assert [d["id"] for d in body["groups"]["corpus"]] == [f"article:{aid}"]
    assert body["truncated"] is True, "语料 hard cap 截断必须 OR 合并进响应"
