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

import ast
import os
import sqlite3
import time
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


# ── 性能守卫：全量（真实词库 ≈8175 doc + ~200KB 语料）单次 search < 50ms ─────────
#
# ADR-0014 的立论是「固定词库侧全量内存扫描 <50ms，故不需 FTS5」。静态断言证明不了
# 这条性能前提，它只能靠回归断言钉住：真跑全量 iter_vocab_docs()（不是小样本）+
# 注入 ~200KB 合成语料，断言单次 search() 的最小耗时 < 50ms。
#
# 阈值纪律（防环境抖动）：取多次采样的**最小值**（min 只受最快一次支配，屏蔽 GC /
# 调度抖动；实测量级 ≈20ms，阈值 50ms 留 2×+ 余量）。最小值仍会因为「被测对象被
# 换成小样本 / 人为放大语料 / 注入 sleep」而真实上升 —— 该守卫不会因此失去意义。

_ROOT = Path(__file__).resolve().parent.parent

# 语料填充句（含命中串 wohnung；×60 使单篇 ≈5KB → 40 篇 ≈ 200KB）。
_CORPUS_FILLER_SENTENCE = (
    "Der schnelle braune Fuchs springt ueber den faulen Hund und die Wohnung ist gross. "
)


def test_full_scan_search_under_50ms():
    """全量内存扫描单次 < 50ms（ADR-0014 FTS5 可行性的回归锚点）。

    实测（本机）：195KB 语料 min≈22ms；放大到 9.7MB（50×）→ min≈87ms 越过阈值。
    变异验证（已实跑）：把语料放大 50×（~9.7MB）→ best 87.2ms ≥ 50ms → 必红
    （语料/扫描被放大会真实推高耗时，故该守卫对小样本替换 / 放大 / sleep 敏感）。
    """
    from delector.services import search as svc

    docs = list(svc.iter_vocab_docs())
    assert len(docs) >= 8000, f"词库侧 doc 数异常（应 ≈8175）：{len(docs)}"

    filler = _CORPUS_FILLER_SENTENCE * 60
    corpus: list[dict] = [
        {
            "kind": "corpus",
            "id": f"article:{i}",
            "lemma": "",
            "hw": "",
            "pos": "article",
            "cefr": "",
            "fields": {"title": f"Titel {i} Wohnung", "text": filler},
            "payload": {"source": "article", "ref_id": i, "title": f"Titel {i}", "level": ""},
        }
        for i in range(40)
    ]
    corpus_bytes = sum(len(d["fields"]["text"]) + len(d["fields"]["title"]) for d in corpus)
    assert corpus_bytes >= 190_000, f"注入语料应 ≈200KB：{corpus_bytes}"

    samples: list[float] = []
    resp: dict = {}
    for _ in range(9):
        t0 = time.perf_counter()
        resp = svc.search("wohnung", corpus_docs=corpus)
        samples.append((time.perf_counter() - t0) * 1000.0)
    best = min(samples)
    assert resp["total"] > 0, "命中串应真有结果（否则扫描被短路，守卫失去意义）"
    assert best < 50.0, (
        f"全量扫描单次耗时 {best:.1f}ms ≥ 50ms（阈值）；"
        f"样本(ms)={[round(x, 1) for x in samples]}（min={best:.1f}）"
    )


# ── 注册守卫：search 必须在 main 之前 include（FastAPI 按注册序匹配） ──────────
#
# 落地依据：spec/计划「路由注册：新 router 在 register_routes 中于 main 之前 include」
# 与 delector/routes/__init__.py 的「分域路由在前、通用 handler 垫底」纪律。
# 用 AST 取 register_routes 内 include_router(...) 的调用序（不靠脆弱的行号/正则），
# 断言 search 的出现位置严格早于 main。变异验证（已实跑）：把注册顺序改成 main 在
# search 之前 → order.index('search') > order.index('main') → 必红。


def _register_routes_include_order() -> list[str]:
    """register_routes 内 app.include_router(X.router) 的模块名有序列表。"""
    src = (_ROOT / "delector" / "routes" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "register_routes"
        ),
        None,
    )
    assert fn is not None, "delector/routes/__init__.py 找不到 register_routes"
    order: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "include_router"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
            order.append(arg.value.id)
    return order


def test_search_router_registered_before_main():
    """register_routes 中 search.router 必须在 main.router 之前 include。"""
    order = _register_routes_include_order()
    assert "search" in order, f"register_routes 未 include search.router：{order}"
    assert "main" in order, f"register_routes 未 include main.router：{order}"
    assert order.index("search") < order.index("main"), (
        f"search 必须在 main 之前注册（分域路由在前、通用 handler 垫底）：{order}"
    )
