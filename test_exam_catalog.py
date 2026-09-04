# -*- coding: utf-8 -*-
"""exam catalog 目录化（ADR-0005 Task 3）的行为级回归。

端点契约：
- GET /api/exams/catalog → {"levels": [{"id", "title", "modules": [
  {"id", "title", "panel", "api_prefix", "count"}]}]}。纯只读导航发现层，
  **不迁移**任何 /api/a1/* 取题端点（旧契约照常可用，见 smoke 锚）。
- count 全部由代码注册目录（exam_catalog.py 单源）从数据模块常量实时
  推导：不复制数据、不入 SQLite；数据模块缺失/重命名时 count 记 0，
  不得拖垮 server 启动。

与 test_server.py / test_audit_hardening.py 同款纪律：模块顶层先钉隔离
env 再 import server（server 模块顶层有 init_db() 副作用），clean_db
autouse 前后双钉 env + gc.collect() 后删库（Windows 句柄释放纪律）。
"""
import os
import gc
import pytest

os.environ["DATABASE_PATH"] = "test_catalog.db"
os.environ["PROGRESS_DB_PATH"] = "test_catalog_progress.db"

from fastapi.testclient import TestClient  # noqa: E402

from server import app  # noqa: E402
import exam_catalog  # noqa: E402
import a1_dict  # noqa: E402
import a1_hoeren_dict  # noqa: E402
import a1_lesen_dict  # noqa: E402
import a1_writing_dict  # noqa: E402

_ROOT = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_ROOT, "static", "index.html"), encoding="utf-8") as _f:
    _INDEX = _f.read()


@pytest.fixture
def client():
    # 显式 127.0.0.1 来源：与 test_server.py 同款（个别端点有 localhost 闸）。
    return TestClient(app, client=("127.0.0.1", 54321))


@pytest.fixture(autouse=True)
def clean_db():
    # database.get_db_path() 每次调用都读 os.environ（不是 import 时冻结）：
    # 全量 pytest 时更晚收集的测试文件会在模块顶层改写 env，故每个用例
    # 前后双钉自己的库文件名，不能只靠模块顶层那一次赋值。
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = "test_catalog.db"
    os.environ["PROGRESS_DB_PATH"] = "test_catalog_progress.db"
    gc.collect()
    for f in ("test_catalog.db", "test_catalog_progress.db"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    from server import init_db, init_progress_db
    init_db("test_catalog.db")
    init_progress_db("test_catalog_progress.db")
    yield
    gc.collect()
    for f in ("test_catalog.db", "test_catalog_progress.db"):
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


# ── RED 1：端点契约（形状 + 数据推导 count + panel 指向真实 DOM） ────────────

def test_catalog_endpoint_contract(client):
    """/api/exams/catalog 返回 A1 五模块，count 与数据模块常量实测长度一致。"""
    res = client.get("/api/exams/catalog")
    assert res.status_code == 200
    levels = res.json()["levels"]
    assert [lv["id"] for lv in levels] == ["A1"]

    mods = {m["id"]: m for m in levels[0]["modules"]}
    assert {"writing", "hoeren", "lesen", "sprechen", "vocab"} <= set(mods)
    for m in mods.values():
        assert m["title"], "模块 %s 缺 title" % m["id"]
        assert m["panel"], "模块 %s 缺 panel（面板容器 id）" % m["id"]
        assert m["api_prefix"], "模块 %s 缺 api_prefix（取题端点前缀）" % m["id"]

    # count 是数据推导不是硬编码：必须等于数据模块常量的实测长度。
    assert mods["writing"]["count"] == (
        len(a1_writing_dict.A1_SCHREIBEN_TEIL1_EXERCISES)
        + len(a1_writing_dict.A1_SCHREIBEN_TEIL2_PROMPTS)
    )
    assert mods["hoeren"]["count"] == len(a1_hoeren_dict.A1_HOEREN_SETS)
    assert mods["lesen"]["count"] == len(a1_lesen_dict.A1_LESEN_SETS)
    assert mods["sprechen"]["count"] == (
        len(a1_dict.A1_SPRECHEN_TEIL2) + len(a1_dict.A1_SPRECHEN_TEIL3)
    )
    assert mods["vocab"]["count"] == len(a1_dict.GOETHE_A1_VOCAB)


def test_catalog_panels_point_at_real_dom(client):
    """panel 字段语义 = 该模块对应的面板容器 id，必须真实存在于 index.html。"""
    res = client.get("/api/exams/catalog")
    for lv in res.json()["levels"]:
        for m in lv["modules"]:
            assert 'id="%s"' % m["panel"] in _INDEX, (
                "模块 %s 的 panel=%r 在 index.html 里不存在（指向幻影容器 = 前端拿到死引用）"
                % (m["id"], m["panel"])
            )


# ── RED 2：扩展点变异断言 —— 加级 = 插一行 ───────────────────────────────────

def test_catalog_extension_point_adding_level(monkeypatch, client):
    """EXAM_CATALOG 追加一个等级 key，catalog 立即多一级且结构同构。

    这是「未来加 A2 = 在 exam_catalog.py 插一行注册」的变异证明：
    - 有 count_fn 的模块 → count 正常推导；
    - 无 count_fn 的模块（数据模块还没接上）→ 结构一致、count 记 0、不崩。
    """
    patched = dict(exam_catalog.EXAM_CATALOG)
    patched["A2"] = {
        "title": "A2",
        "modules": {
            "hoeren": {
                "title": "听力 (A2)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/exams",
                "count_fn": lambda: 7,
            },
            "lesen": {
                "title": "阅读 (A2)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/exams",
            },
        },
    }
    monkeypatch.setattr(exam_catalog, "EXAM_CATALOG", patched)

    res = client.get("/api/exams/catalog")
    assert res.status_code == 200
    levels = {lv["id"]: lv for lv in res.json()["levels"]}
    assert set(levels) == {"A1", "A2"}, "插一行的 A2 必须原样出现在 catalog 里"

    a2 = {m["id"]: m for m in levels["A2"]["modules"]}
    assert a2["hoeren"]["count"] == 7
    assert set(a2["lesen"].keys()) == set(a2["hoeren"].keys()), (
        "缺 count_fn 的模块也必须输出同构结构（id/title/panel/api_prefix/count）"
    )
    assert a2["lesen"]["count"] == 0


# ── 防御：count_fn 抛错（数据模块重命名）不拖垮端点 ─────────────────────────

def _boom():
    raise RuntimeError("data module renamed — catalog must survive")


def test_catalog_survives_broken_count_fn(monkeypatch, client, caplog):
    patched = dict(exam_catalog.EXAM_CATALOG)
    patched["A1"] = dict(patched["A1"])
    patched["A1"]["modules"] = dict(patched["A1"]["modules"])
    patched["A1"]["modules"]["hoeren"] = dict(patched["A1"]["modules"]["hoeren"])
    patched["A1"]["modules"]["hoeren"]["count_fn"] = _boom
    monkeypatch.setattr(exam_catalog, "EXAM_CATALOG", patched)

    # 零静默吞异常铁律：count 记 0 的同时必须 logger.warning 留痕。
    import logging
    with caplog.at_level(logging.WARNING, logger="delector"):
        res = client.get("/api/exams/catalog")
    assert res.status_code == 200, "单个模块 count 推导失败不得 500 整个 catalog"
    assert any("exam-catalog" in r.message for r in caplog.records), (
        "count 推导失败被静默吞掉（缺 logger.warning 留痕）"
    )
    a1 = next(lv for lv in res.json()["levels"] if lv["id"] == "A1")
    hoeren = next(m for m in a1["modules"] if m["id"] == "hoeren")
    assert hoeren["count"] == 0
    # 其余模块不受牵连
    vocab = next(m for m in a1["modules"] if m["id"] == "vocab")
    assert vocab["count"] == len(a1_dict.GOETHE_A1_VOCAB)


# ── RED 3：路由已注册 ────────────────────────────────────────────────────────

def test_catalog_route_registered(client):
    """/api/exams/catalog 必须挂在 app 上（openapi 枚举可查）。"""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/exams/catalog" in paths


# ── RED 4：旧 /api/a1 契约回归锚 —— catalog 上线不动旧端点 ───────────────────

def test_legacy_a1_endpoints_smoke(client):
    """catalog 只做导航发现：既有取题端点全部照常 200。"""
    for path in (
        "/api/a1/topics",
        "/api/a1/vocab",
        "/api/a1/sprechen/teil2",
        "/api/a1/sprechen/teil3",
        "/api/a1/hoeren/sets",
        "/api/a1/lesen/sets",
    ):
        res = client.get(path)
        assert res.status_code == 200, "旧端点 %s 被 catalog 上线破坏" % path
