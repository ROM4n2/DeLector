# -*- coding: utf-8 -*-
"""WiFi 内容分发：桌面货架端点 + 手机出站拉取端点（T1 + T2）。

架构（不可偏离）：
    桌面（job#1 产包落库）作局域网"货架"：GET /api/encounter/packs 及 /packs/{pack_id}
    只读开放（与 GET /api/wb/state 同级"拉取免 key"）；
    手机服务端**出站**拉取并幂等落库：POST /api/encounter/pull-pack（挂本机闸）。
    方向反转的理由见 start.py:36-42（Android 绑回环，出站不受绑定限制）。

测试纪律：
- **双 TestClient**（app_shelf 桌面 / app_phone 手机），各自独立 tmp 库：路由走
  database.get_db_path()，每次调用读 os.environ，故用 _ShelvedClient 在每次请求前后
  切换 DATABASE_PATH —— 两个"实例"共享同一进程但指向不同库。
- 出站不打真端口：monkeypatch delector.routes.encounter.httpx.get 转调 shelf 的
  TestClient 对应路径，保持"真实 shelf 代码路径"被执行。
- env 用 setdefault（`delector/server.py:339` 有模块级单例 app，收集期首次 import 即
  按此 env 建库并被其它测试模块共用）；autouse fixture 只切 env、不删库文件。
"""

import gc
import os

import httpx
import pytest

# env 双钉必须在 import app 之前（同 test_encounter_routes.py / test_encounter_journey_e2e.py）。
os.environ.setdefault("DATABASE_PATH", "test_encounter_pull.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_pull_progress.db")

from fastapi.testclient import TestClient  # noqa: E402

from delector.core import database  # noqa: E402
from delector.routes import encounter as encounter_mod  # noqa: E402
from delector.server import create_app  # noqa: E402

CARD_PACK_SCHEMA = "encounter-pack/v1"


class _ShelvedClient:
    """包一层 TestClient：每次请求前把 DATABASE_PATH 切到本实例的库。

    `get_db_path()` 每次调用读 env，因此同一进程内可用 env 切换"实例"。
    用 context 管理保证异常路径也复原 env。
    """

    def __init__(self, app, db_path, client_addr):
        self._client = TestClient(app, client=client_addr)
        self._db_path = db_path

    def request(self, method, url, **kwargs):
        saved = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = self._db_path
        try:
            return self._client.request(method, url, **kwargs)
        finally:
            if saved is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = saved

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def _fixture_pack(pack_id="shelf-1", cefr="a2", title="Ein Tag im Park", raw_text="Es war einmal ein sonniger Tag."):
    """合法的 encounter-pack/v1 夹具；estimated_cefr 默认小写以测归一化。"""
    return {
        "schema": CARD_PACK_SCHEMA,
        "pack_id": pack_id,
        "source": {"kind": "job1"},
        "article": {
            "title": title,
            "raw_text": raw_text,
            "char_count": len(raw_text),
        },
        "analysis": {"tokens_total": 8, "known_rate": 0.25},
        "glosses": [],
        "estimated_cefr": cefr,
    }


@pytest.fixture(autouse=True)
def clean_env():
    """每例把 env 复原；不删库文件（单例 app 共享，删库会打爆其它测试模块）。"""
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    yield
    gc.collect()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def shelf(tmp_path):
    """桌面货架实例：独立 tmp 库 + 本机来源地址。"""
    db = str(tmp_path / "shelf.db")
    database.init_db(db)
    return _ShelvedClient(create_app(), db, ("127.0.0.1", 54321))


@pytest.fixture
def phone(tmp_path):
    """手机实例：另一独立 tmp 库 + 本机来源地址（pull-pack 挂本机闸）。"""
    db = str(tmp_path / "phone.db")
    database.init_db(db)
    return _ShelvedClient(create_app(), db, ("127.0.0.1", 12345))


def _seed_shelf(shelf, packs):
    """往桌面货架直接落库若干 pack；返回 pack_id 列表。

    注意：这里走存储层 import_encounter_pack（**不做 level 归一**，归一是路由层职责），
    所以夹具 pack 的 estimated_cefr 必须已是白名单大写值——真实桌面上包经由
    job#1 --deliver-to 走 import-pack 路由，落库时已归一。
    """
    ids = []
    for pack in packs:
        saved = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = shelf._db_path
        try:
            database.import_encounter_pack(pack)
        finally:
            if saved is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = saved
        ids.append(pack["pack_id"])
    return ids


def _patch_outbound_to_shelf(monkeypatch, shelf, recorder=None):
    """把 encounter 模块的出站 httpx.get 转调到 shelf TestClient（不打真端口）。

    `recorder` 若是 list，则把每次出站的 url 记进去（供断言出站确实发生）。
    """
    real_get = encounter_mod.httpx.get

    def fake_get(url, *args, **kwargs):
        if recorder is not None:
            recorder.append(url)
        # url 形如 http://192.168.1.5:8000/api/encounter/packs
        parsed = httpx.URL(url)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query.decode()}"
        return shelf.get(path)

    monkeypatch.setattr(encounter_mod.httpx, "get", fake_get)
    return real_get


# ── T1 用例 1：货架清单（字段完整 + 无原文外泄）────────────────────────────
def test_shelf_list_returns_pack_metadata_only(shelf):
    """建 2 个 pack 行 → /packs 列出 2 条且字段完整；响应绝不含 pack_json/raw_text 原文。"""
    _seed_shelf(shelf, [_fixture_pack("shelf-1", cefr="A2"), _fixture_pack("shelf-2", cefr="A1", title="Zweite")])

    res = shelf.get("/api/encounter/packs")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["packs"], list)
    assert len(body["packs"]) == 2, f"应列出 2 个 pack，实际 {len(body['packs'])}"

    by_id = {p["pack_id"]: p for p in body["packs"]}
    assert set(by_id) == {"shelf-1", "shelf-2"}
    entry = by_id["shelf-1"]
    assert set(entry) == {"pack_id", "title", "level", "word_count"}, f"字段应恰为这四项，实际 {set(entry)}"
    assert entry["title"] == "Ein Tag im Park"
    assert entry["level"] == "A2"
    assert by_id["shelf-2"]["level"] == "A1"
    assert entry["word_count"] == len("Es war einmal ein sonniger Tag.".split())

    # 防泄：响应原文里绝不能出现 pack_json / raw_text 关键词或其内容。
    raw = res.text
    assert "pack_json" not in raw
    assert "raw_text" not in raw
    assert "Es war einmal" not in raw, "货架清单不得泄露正文原文"


def test_shelf_list_skips_manual_articles_and_empty_shelf(shelf):
    """空货架 → 200 空清单；手工短文（无 pack_json）不进清单。"""
    empty = shelf.get("/api/encounter/packs")
    assert empty.status_code == 200
    assert empty.json() == {"packs": []}

    # 手工短文：走真实路由落库（无 pack_json / pack_id）。
    created = shelf.post(
        "/api/encounter/texts",
        json={"title": "Handschrift", "level": "A2", "source": "manual", "content": "Guten Tag ich heiße Lukas."},
    )
    assert created.status_code == 201, created.text

    after = shelf.get("/api/encounter/packs").json()
    assert after == {"packs": []}, "手工短文不进货架清单"


# ── T1 用例 2：单包完整返回 ─────────────────────────────────────────────────
def test_shelf_get_pack_returns_valid_full_pack(shelf):
    """GET /packs/{pack_id} 返回完整 encounter-pack/v1：过 validate_pack 且 raw_text 与源一致。"""
    src_text = "Es war einmal ein sonniger Tag im Park."
    _seed_shelf(shelf, [_fixture_pack("shelf-1", raw_text=src_text)])

    res = shelf.get("/api/encounter/packs/shelf-1")
    assert res.status_code == 200, res.text
    pack = res.json()
    encounter_mod.validate_pack(pack)  # 不抛即结构合法
    assert pack["schema"] == CARD_PACK_SCHEMA
    assert pack["pack_id"] == "shelf-1"
    assert pack["article"]["raw_text"] == src_text, "货架单包必须与源正文逐字一致"


# ── T1 用例 3：未知 pack_id → 404 ────────────────────────────────────────────
def test_shelf_get_unknown_pack_404(shelf):
    """未知 pack_id → 404，中文 detail。"""
    res = shelf.get("/api/encounter/packs/does-not-exist")
    assert res.status_code == 404
    assert "detail" in res.json()
    assert "卡包" in res.json()["detail"], "404 detail 应为中文人话"


# ── T2 用例 4：手机代理货架清单 ─────────────────────────────────────────────
def test_phone_pull_pack_proxies_shelf_listing(shelf, phone, monkeypatch):
    """pack_id 省略 → 手机出站取桌面货架清单并原样返回。"""
    _seed_shelf(shelf, [_fixture_pack("shelf-1"), _fixture_pack("shelf-2", title="Zweite")])
    urls = []
    _patch_outbound_to_shelf(monkeypatch, shelf, recorder=urls)

    res = phone.post("/api/encounter/pull-pack", json={"desktop_base": "http://192.168.1.5:8000"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert {p["pack_id"] for p in body["packs"]} == {"shelf-1", "shelf-2"}
    assert urls == ["http://192.168.1.5:8000/api/encounter/packs"], "应出站打到桌面货架清单路径"
    # 代理清单也不得泄露原文。
    assert "raw_text" not in res.text and "pack_json" not in res.text


# ── T2 用例 5：手机拉取导入 + 幂等 ──────────────────────────────────────────
def test_phone_pull_pack_imports_and_is_idempotent(shelf, phone, monkeypatch):
    """带 pack_id → 落库到手机库；重复拉取返回同一 id 且行数不增。"""
    src_text = "Es war einmal ein sonniger Tag im Park."
    _seed_shelf(shelf, [_fixture_pack("shelf-1", raw_text=src_text)])
    urls = []
    _patch_outbound_to_shelf(monkeypatch, shelf, recorder=urls)

    base = "http://192.168.1.5:8000/"
    first = phone.post("/api/encounter/pull-pack", json={"desktop_base": base, "pack_id": "shelf-1"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["imported"] is True
    assert body["pack_id"] == "shelf-1"
    # 去尾斜杠后拼接：不得产生双斜杠。
    assert urls == ["http://192.168.1.5:8000/api/encounter/packs/shelf-1"]

    listing = phone.get("/api/encounter/texts")
    assert listing.status_code == 200
    texts = listing.json()["texts"]
    assert len(texts) == 1, f"手机列表应新增 1 篇，实际 {len(texts)}"
    assert texts[0]["id"] == body["id"]
    assert texts[0]["title"] == "Ein Tag im Park"
    assert texts[0]["level"] == "A2", "estimated_cefr 小写 a2 应被规一为 A2 后落库"

    # 幂等：重复拉取返回同一 id，且行数不增。
    second = phone.post("/api/encounter/pull-pack", json={"desktop_base": base, "pack_id": "shelf-1"})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == body["id"], "重复拉取同一 pack_id 必须返回同一行 id"
    assert len(phone.get("/api/encounter/texts").json()["texts"]) == 1, "重复拉取不得新增行"


# ── T2 用例 6：无 localhost 来源 → 403（红线 7）─────────────────────────────
def test_phone_pull_pack_denies_lan_source(shelf, tmp_path):
    """局域网来源调 pull-pack → 403（写路径闸不退化）。"""
    db = str(tmp_path / "lan.db")
    database.init_db(db)
    lan = _ShelvedClient(create_app(), db, ("10.0.0.9", 12345))

    res = lan.post("/api/encounter/pull-pack", json={"desktop_base": "http://192.168.1.5:8000"})
    assert res.status_code == 403, f"局域网来源应被拒，实际 {res.status_code}"


# ── T2 用例 7：desktop_base 非法 → 400 中文 ────────────────────────────────
@pytest.mark.parametrize("bad_base", ["192.168.1.5:8000", "ftp://x", "http://", ""])
def test_phone_pull_pack_rejects_bad_desktop_base(phone, bad_base):
    """desktop_base 非法（无 scheme / 非 http(s) / 空）→ 400 中文提示。"""
    res = phone.post("/api/encounter/pull-pack", json={"desktop_base": bad_base})
    assert res.status_code in (400, 422), f"{bad_base!r} 应被拒，实际 {res.status_code}"
    if res.status_code == 400:
        assert "desktop_base" in res.json()["detail"]
        assert "http" in res.json()["detail"]


# ── T2 用例 8：出站失败 → 502 人话引导 ─────────────────────────────────────
def test_phone_pull_pack_outbound_failure_is_humanized(phone, monkeypatch):
    """出站抛 httpx.ConnectError → 502，detail 含人话引导关键词（电脑/WiFi/防火墙）。"""

    def boom(url, *args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(encounter_mod.httpx, "get", boom)
    res = phone.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://192.168.1.5:8000", "pack_id": "shelf-1"},
    )
    assert res.status_code == 502, f"出站失败应为 502，实际 {res.status_code}"
    detail = res.json()["detail"]
    assert any(kw in detail for kw in ("电脑", "WiFi", "防火墙")), f"detail 应含人话引导，实际: {detail!r}"


def test_phone_pull_pack_shelf_404_is_humanized(phone, monkeypatch):
    """桌面货架 404（未知 pack_id）→ 手机侧 502 人话（非 2xx 一律人话化）。"""

    class _Resp:
        status_code = 404

        def json(self):
            return {"detail": "货架上没有这个卡包"}

    monkeypatch.setattr(encounter_mod.httpx, "get", lambda url, *a, **k: _Resp())
    res = phone.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://192.168.1.5:8000", "pack_id": "nope"},
    )
    assert res.status_code == 502, f"出站非 2xx 应为 502，实际 {res.status_code}"
    assert "电脑" in res.json()["detail"]


# ── T2 用例 8b：非法 pack → 400 ─────────────────────────────────────────────
def test_phone_pull_pack_invalid_pack_is_400(phone, monkeypatch):
    """出站拿到的 pack 结构非法（坏 schema）→ 400。"""
    bad_pack = _fixture_pack("bad")
    bad_pack["schema"] = "encounter-pack/OLD"

    class _Resp:
        status_code = 200

        def json(self):
            return bad_pack

    monkeypatch.setattr(encounter_mod.httpx, "get", lambda url, *a, **k: _Resp())
    res = phone.post(
        "/api/encounter/pull-pack",
        json={"desktop_base": "http://192.168.1.5:8000", "pack_id": "bad"},
    )
    assert res.status_code == 400, f"非法 pack 应为 400，实际 {res.status_code}"
    assert "schema" in res.json()["detail"]


# ── T1 用例 9：货架端点局域网可读（对照写操作仍 403）────────────────────────
def test_shelf_readable_from_lan_but_writes_denied(shelf, tmp_path):
    """局域网来源 GET /packs → 200；同来源写操作（import-pack）仍 403。"""
    _seed_shelf(shelf, [_fixture_pack("shelf-1")])

    lan = _ShelvedClient(create_app(), shelf._db_path, ("10.0.0.9", 12345))
    read = lan.get("/api/encounter/packs")
    assert read.status_code == 200, "货架是局域网只读内容数据，应放行"
    assert {p["pack_id"] for p in read.json()["packs"]} == {"shelf-1"}

    single = lan.get("/api/encounter/packs/shelf-1")
    assert single.status_code == 200, "单包读同样局域网开放"

    write = lan.post("/api/encounter/import-pack", json={"pack": _fixture_pack("lan-write")})
    assert write.status_code == 403, "写操作必须仍受本机闸保护"
