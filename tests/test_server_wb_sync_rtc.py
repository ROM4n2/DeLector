# -*- coding: utf-8 -*-
"""wb 同步 / WebRTC 信令 / Workbench 进度镜像域的端点测试（C6 Task 4 自 `tests/test_server.py` 逐字搬出）。

搬出的四段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `1978`-`2086`  POST /api/wb/sync/store & GET /api/wb/sync/fetch/{code}
  `2087`-`2172`  WebRTC 信令中继 /api/wb/rtc/signal（Stage B M3）
  `2865`-`2964`  Workbench 进度 server 同步
  `2965`-`3070`  ADR-0016 Phase 3 / Task 2：wb 镜像写入与统一池投影同事务

断言、用例名与幂等 / 只增 / 同事务语义逐字未改；只新增本文件的显式 import。
共享夹具（clean_db / client / lan_client）住在 `tests/server_helpers.py` 与
`tests/conftest.py`，按名即可见，无需本文件重复定义。
"""

import re

from fastapi.testclient import TestClient
from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client

from delector import server
from delector.core.database import db_conn
from delector.server import app, init_db

# ── POST /api/wb/sync/store & GET /api/wb/sync/fetch/{code} ───────────────────


def test_sync_sdp_store_and_fetch(client):
    """SDP 短码：存入后返回 6 位码，取出内容一致，再次 GET 返回 404（一次性消费）。"""
    key = client.get("/api/wb/state/key").json()["key"]
    sdp = {"type": "offer", "sdp": "v=0\r\no=- 123456 2 IN IP4 127.0.0.1\r\ns=-\r\n"}
    resp = client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "offer"}, headers={"X-WB-Key": key})
    assert resp.status_code == 200
    data = resp.json()
    assert "code" in data
    code = data["code"]
    assert len(code) == 6
    assert code.isalnum()

    # 首次 GET 成功取出
    fetch_resp = client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key})
    assert fetch_resp.status_code == 200
    fetch_data = fetch_resp.json()
    assert fetch_data["sdp"] == sdp
    assert fetch_data["role"] == "offer"

    # 再次 GET 返回 404（已被一次性消费）
    assert client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key}).status_code == 404


def test_sync_sdp_fetch_invalid_code(client):
    """查询不存在或过期的短码返回 404（带对 key 才走到这一步）。"""
    key = client.get("/api/wb/state/key").json()["key"]
    resp = client.get("/api/wb/sync/fetch/NON999", headers={"X-WB-Key": key})
    assert resp.status_code == 404


def test_sync_info_endpoint(client):
    """实例指纹端点：返回 instance_id + started_at，供前端判断两端是否同一实例。"""
    resp = client.get("/api/wb/sync/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "instance_id" in data and len(data["instance_id"]) == 12
    assert "started_at" in data and isinstance(data["started_at"], (int, float))
    assert data["ttl_seconds"] == 300
    # 同一进程内两次调用应返回同一实例 ID（短码 cache 是本进程模块级单例）
    resp2 = client.get("/api/wb/sync/info")
    assert resp2.json()["instance_id"] == data["instance_id"]


def test_sync_sdp_lan_accessible(client, lan_client):
    """局域网设备间同步：端点不应被仅限本地的 _require_localhost 误伤拦截。

    注意 key 只能从本机端点取（lan 取 key 是 403），拿到后 lan 侧凭 key 读写——
    这正是「凭 key 说话」而非「凭来源 IP 说话」的模型。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    sdp = {"type": "answer", "sdp": "v=0\r\no=- 654321 2 IN IP4 192.168.1.77\r\ns=-\r\n"}
    resp = lan_client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "answer"}, headers={"X-WB-Key": key})
    assert resp.status_code == 200
    code = resp.json()["code"]
    assert len(code) == 6

    fetch_resp = lan_client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key})
    assert fetch_resp.status_code == 200
    assert fetch_resp.json()["sdp"] == sdp
    assert fetch_resp.json()["role"] == "answer"


def test_sync_store_requires_key(client):
    """信令 store 须带 X-WB-Key：缺 key / 错 key 均 403（SDP 要在 LAN 上中继，不能裸奔）。"""
    sdp = {"type": "offer", "sdp": "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\n"}
    assert client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "offer"}).status_code == 403
    wrong = client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "offer"}, headers={"X-WB-Key": "0" * 32})
    assert wrong.status_code == 403


def test_sync_fetch_requires_key(client):
    """信令 fetch 同样须带 key：否则任何人都能截获/消费对端的 SDP 短码。"""
    key = client.get("/api/wb/state/key").json()["key"]
    sdp = {"type": "answer", "sdp": "v=0\r\no=- 2 2 IN IP4 127.0.0.1\r\ns=-\r\n"}
    code = client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "answer"}, headers={"X-WB-Key": key}).json()[
        "code"
    ]

    assert client.get(f"/api/wb/sync/fetch/{code}").status_code == 403
    assert client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": "0" * 32}).status_code == 403
    # 403 不得有副作用：短码没被上述失败请求消费掉，带对 key 仍能取到
    ok = client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key})
    assert ok.status_code == 200
    assert ok.json()["sdp"] == sdp


def test_sync_store_preflight_allows_post_and_key(lan_client):
    """store 是 POST 且带 X-WB-Key → 预检必须放行 POST 方法与自定义头。

    Allow-Methods 缺 POST 会让跨域浏览器在预检阶段就被拒，信令永远发不出去。
    """
    origin = "http://127.0.0.1:8000"
    r = lan_client.options(
        "/api/wb/sync/store",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-wb-key",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    assert "POST" in r.headers.get("access-control-allow-methods", "")
    assert "X-WB-Key" in r.headers.get("access-control-allow-headers", "")


# ── WebRTC 信令中继 /api/wb/rtc/signal（Stage B M3）────────────────────────────


def test_rtc_signal_requires_key(client):
    """信令中继须带 X-WB-Key：缺 key / 错 key 都 403。

    SDP/ICE 在 LAN 上裸奔等于把会话描述直接递给同网段的任何人。
    """
    body = {"client": "A", "type": "offer", "payload": {"sdp": "v=0"}}
    assert client.post("/api/wb/rtc/signal", json=body).status_code == 403
    assert client.post("/api/wb/rtc/signal", json=body, headers={"X-WB-Key": "0" * 32}).status_code == 403
    assert client.get("/api/wb/rtc/signal").status_code == 403
    assert client.get("/api/wb/rtc/signal", headers={"X-WB-Key": "0" * 32}).status_code == 403


def test_rtc_signal_roundtrip(client):
    """两端靠同一把配对密钥中继 offer/answer，且各自只收到对端的消息。"""
    key = client.get("/api/wb/state/key").json()["key"]
    r = client.post(
        "/api/wb/rtc/signal",
        json={"client": "A", "type": "offer", "payload": {"sdp": "v=0 offer"}},
        headers={"X-WB-Key": key},
    )
    assert r.status_code == 200

    # B 拉得到 A 的 offer
    got = client.get("/api/wb/rtc/signal?client=B", headers={"X-WB-Key": key})
    assert got.status_code == 200
    msgs = got.json()["messages"]
    assert [m for m in msgs if m["type"] == "offer"], f"B 没收到 offer：{msgs}"
    assert msgs[-1]["payload"] == {"sdp": "v=0 offer"}

    # A 不该看到自己发的：否则两端会把自己的 offer 当新 offer 反复建连
    mine = client.get("/api/wb/rtc/signal?client=A", headers={"X-WB-Key": key})
    assert all(m.get("sender") != "A" for m in mine.json()["messages"]), (
        f"发信端收到了自己的信令：{mine.json()['messages']}"
    )

    # B 回 answer，A 能收到
    assert (
        client.post(
            "/api/wb/rtc/signal",
            json={"client": "B", "type": "answer", "payload": {"sdp": "v=0 answer"}},
            headers={"X-WB-Key": key},
        ).status_code
        == 200
    )
    types = [m["type"] for m in client.get("/api/wb/rtc/signal?client=A", headers={"X-WB-Key": key}).json()["messages"]]
    assert "answer" in types, f"A 没收到 answer：{types}"


def test_rtc_signal_cursor_filters_consumed(client):
    """after 游标：已消费的信令不再重复投递（否则每轮轮询都重放整个建连过程）。"""
    key = client.get("/api/wb/state/key").json()["key"]
    assert (
        client.post(
            "/api/wb/rtc/signal",
            json={"client": "A", "type": "candidate", "payload": {"c": "1"}},
            headers={"X-WB-Key": key},
        ).status_code
        == 200
    )
    first = client.get("/api/wb/rtc/signal?client=B", headers={"X-WB-Key": key}).json()
    assert first["messages"], "B 首轮应收到 candidate"
    cursor = first["now"]
    second = client.get(f"/api/wb/rtc/signal?client=B&after={cursor}", headers={"X-WB-Key": key}).json()
    assert second["messages"] == [], f"游标之后不该再重复投递：{second['messages']}"


def test_rtc_signal_cors_preflight_allows_post(lan_client):
    """新前缀 /api/wb/rtc/ 也要过 CORS 预检（APP WebView 是跨域发信令的）。"""
    origin = "http://127.0.0.1:8000"
    r = lan_client.options(
        "/api/wb/rtc/signal",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-wb-key",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    assert "POST" in r.headers.get("access-control-allow-methods", "")
    assert "X-WB-Key" in r.headers.get("access-control-allow-headers", "")


# ── Workbench 进度 server 同步（docs/plans/archive/workbench-progress-server-sync.md）──


def test_wb_state_roundtrip():
    """save_wb_state → get_wb_state 回读一致，且可覆盖写入。"""
    assert server.get_wb_state() == {}
    server.save_wb_state({"words": []})
    assert server.get_wb_state() == {"words": []}
    server.save_wb_state({"words": [1]})
    assert server.get_wb_state() == {"words": [1]}


def test_wb_state_empty_returns_empty_dict():
    """空 DB（从未写入）get_wb_state 返回 {}，不抛异常。"""
    assert server.get_wb_state() == {}


def test_wb_state_sync_key_local_only(client, lan_client):
    """同步 key 仅本机能取（GET /api/wb/state/key 走 _require_localhost）。"""
    r = client.get("/api/wb/state/key")
    assert r.status_code == 200
    key = r.json()["key"]
    assert isinstance(key, str) and len(key) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", key), "key 应为 32 位 hex"
    # 同一把 key 幂等：再取一次不变（已持久化，重启后仍一致）
    assert client.get("/api/wb/state/key").json()["key"] == key
    # 局域网设备不可取 key
    assert lan_client.get("/api/wb/state/key").status_code == 403


def test_wb_state_key_regenerate_requires_localhost(lan_client):
    """重新生成同步密钥是高危操作：仅本机可调（局域网设备不得重置别人的凭证）。"""
    assert lan_client.post("/api/wb/state/key").status_code == 403


def test_wb_state_key_regenerate_invalidates_old_key(client):
    """撤销配对 = 重新生成密钥：旧 key 立即失效、新 key 可用，否则撤销形同虚设。

    这是「持久凭证」敢长期有效的前提：一旦泄露或换设备，用户必须能一键作废。
    """
    old = client.get("/api/wb/state/key").json()["key"]
    r = client.post("/api/wb/state/key")
    assert r.status_code == 200
    new = r.json()["key"]
    assert new != old
    assert re.fullmatch(r"[0-9a-f]{32}", new), "新 key 仍是 32 位 hex"

    payload = {"cards": {"c3": {"reps": 1}}, "words": []}
    # 旧 key 立即失效
    assert client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": old}).status_code == 403
    # 新 key 可用，且 GET /key 回读一致
    assert client.get("/api/wb/state/key").json()["key"] == new
    ok = client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": new})
    assert ok.status_code == 200


def test_wb_state_put_requires_key(client):
    """PUT /api/wb/state 必须带对 X-WB-Key，否则 403。"""
    assert client.put("/api/wb/state", json={"payload": {"cards": {}}}).status_code == 403
    wrong = client.put("/api/wb/state", json={"payload": {"cards": {}}}, headers={"X-WB-Key": "0" * 32})
    assert wrong.status_code == 403

    key = client.get("/api/wb/state/key").json()["key"]
    payload = {"words": [{"id": "x"}], "cards": {"c1": {"reps": 1, "last": 9}}, "log": {}, "wrong": {}, "settings": {}}
    r = client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True and body.get("updated_at")
    assert client.get("/api/wb/state").json() == payload


def test_wb_state_cross_device_write(client, lan_client):
    """局域网另一设备带对 key 也能写入，且本机可回读（需求核心）。"""
    key = client.get("/api/wb/state/key").json()["key"]
    payload = {"cards": {"c2": {"s": 6, "due": 0, "last": 123}}, "words": []}
    r = lan_client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})
    assert r.status_code == 200
    assert client.get("/api/wb/state").json() == payload
    # 不带 key 的局域网设备仍只能读不能写
    assert lan_client.put("/api/wb/state", json={"payload": payload}).status_code == 403


def test_wb_state_survives_reinit(client):
    """真文件落盘锁定：save_wb_state → init_db 重开同一库文件 → 数据仍在。

    clean_db 是「每次测试前删库重建」，单靠它证明不了落盘。这里在同一个
    测试内显式重开 DB：等价于 server 重启后 /api/wb/state 仍能回读，
    wb_state 行只存在内存里的话这一步必然读到 {}。
    """
    payload = {"cards": {"c9": {"reps": 3, "last": 42}}, "words": [{"id": "u-9"}]}
    server.save_wb_state(payload)
    init_db("test_delector.db")
    assert server.get_wb_state() == payload
    # 经 HTTP 也读得到同一份（重开后的文件）
    key = client.get("/api/wb/state/key").json()["key"]
    r = client.put("/api/wb/state", json={"payload": {"words": []}}, headers={"X-WB-Key": key})
    assert r.status_code == 200
    assert client.get("/api/wb/state").json() == {"words": []}


# ── ADR-0016 Phase 3 / Task 2：wb 镜像写入与统一池投影同事务（Migration-Idempotency §2/§3）──


def test_wb_state_put_projects_into_vocab_pool(client):
    """接线生效：PUT /api/wb/state 落盘的同时把 wb 快照幂等投影进统一池 vocab_cards。

    证明 Task 1 的 ``project_wb_deck`` 已接进写镜像路径：PUT 后 vocab_cards 出现该
    lemma 行，且 FSRS-6 参数（``fsrs_s``/``fsrs_d``/``fsrs_lapses``）来自 wb 卡。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    payload = {
        "words": [
            {
                "id": "a1-0001",
                "hw": "der Abfahrt",
                "gloss": "出发；发车",
                "ex": [{"de": "Die Abfahrt ist um acht.", "zh": "八点发车。"}],
            }
        ],
        # reps=1 ⇒ 已学，满足范围闸「可投影」前提（Projection 只收自建/已学）
        "cards": {"a1-0001": {"s": 3.5, "d": 4.2, "lapses": 1, "reps": 1}},
    }
    r = client.put("/api/wb/state", json={"payload": payload}, headers={"X-WB-Key": key})
    assert r.status_code == 200
    assert r.json().get("updated_at")

    with db_conn("test_delector.db") as conn:
        row = conn.execute(
            "SELECT word, definition_zh, fsrs_s, fsrs_d, fsrs_lapses "
            "FROM vocab_cards WHERE word = ?",
            ("der Abfahrt",),
        ).fetchone()
    assert row is not None, "投影应把 wb 词条写进 vocab_cards（接线未生效？）"
    assert row["fsrs_s"] == 3.5
    assert row["fsrs_d"] == 4.2
    assert row["fsrs_lapses"] == 1
    assert row["definition_zh"] == "出发；发车"


def test_wb_state_put_projection_idempotent_three_phase(client):
    """Migration-Idempotency §3 三段时序：PUT → 追加新词 → 再 PUT 只新增新词，旧词不重复。

    第二次 PUT 的 payload 仍含旧词条（wb 快照是全量镜像），投影必须按内容去重，
    只新增那条新词条——不得把旧词条重复插入。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    word_a = {"id": "a1-0001", "hw": "der Abfahrt", "gloss": "出发；发车"}
    # reps=1 ⇒ 已学，满足范围闸「可投影」前提（Projection 只收自建/已学）
    payload1 = {"words": [word_a], "cards": {"a1-0001": {"s": 3.5, "reps": 1}}}
    assert client.put("/api/wb/state", json={"payload": payload1}, headers={"X-WB-Key": key}).status_code == 200
    with db_conn("test_delector.db") as conn:
        n1 = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
    assert n1 == 1, "首次 PUT 应投影出 1 行"

    # 追加一条新词条，旧词条仍留在全量 payload 中
    word_b = {"id": "a1-0002", "hw": "der Bahnhof", "gloss": "火车站"}
    payload2 = {
        "words": [word_a, word_b],
        "cards": {"a1-0001": {"s": 3.5, "reps": 1}, "a1-0002": {"s": 2.0, "reps": 1}},
    }
    assert client.put("/api/wb/state", json={"payload": payload2}, headers={"X-WB-Key": key}).status_code == 200
    with db_conn("test_delector.db") as conn:
        n2 = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
        dup_a = conn.execute("SELECT COUNT(*) FROM vocab_cards WHERE word = ?", ("der Abfahrt",)).fetchone()[0]
    assert n2 == 2, "再 PUT 只应新增 1 行，旧词条不得被重复插入"
    assert dup_a == 1, "同一条 wb 词条二次投影不得产生重复行（幂等）"


def test_wb_state_put_rolls_back_blob_when_projection_fails(client, monkeypatch):
    """Task 2 核心：投影失败 ⇒ 同一事务整体回滚，wb 镜像 blob 也不写（无「半写」）。

    用桩把 ``project_wb_deck`` 换成抛异常：PUT 必须失败（500），且 wb_state 表
    **未被更新**（读回仍是旧 updated_at / 旧 payload）——证明 blob 写入与投影同事务。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    # raise_server_exceptions=False 才能拿到 500 响应而非让异常从 TestClient 冒出
    fail_client = TestClient(app, client=("127.0.0.1", 54321), raise_server_exceptions=False)

    # 先写一版基线，记录 updated_at / payload
    # reps=1 ⇒ 已学，满足范围闸「可投影」前提（Projection 只收自建/已学）
    base_payload = {"words": [{"id": "a1-0001", "hw": "der Abfahrt"}], "cards": {"a1-0001": {"s": 3.5, "reps": 1}}}
    assert client.put("/api/wb/state", json={"payload": base_payload}, headers={"X-WB-Key": key}).status_code == 200
    before = server.get_wb_state()
    with db_conn("test_delector.db") as conn:
        before_ts = conn.execute("SELECT updated_at FROM wb_state WHERE id = 1").fetchone()[0]

    def _boom(conn, payload):
        raise RuntimeError("projection forced failure")

    # save_wb_state 函数体内惰性 import project_wb_deck ⇒ 运行时取到本桩
    monkeypatch.setattr("delector.core.vocab_pool.project_wb_deck", _boom)

    new_payload = {
        "words": [{"id": "a1-0001", "hw": "der Abfahrt"}, {"id": "a1-0002", "hw": "der Bahnhof"}],
        "cards": {"a1-0001": {"s": 9.0, "reps": 1}},
    }
    r = fail_client.put("/api/wb/state", json={"payload": new_payload}, headers={"X-WB-Key": key})
    assert r.status_code >= 500, "投影抛错应向上冒泡成 500，而非被吞掉"

    # blob 必须未被更新（同事务回滚）
    assert server.get_wb_state() == before, "投影失败时 wb_state 镜像 blob 不得被写入"
    with db_conn("test_delector.db") as conn:
        after_ts = conn.execute("SELECT updated_at FROM wb_state WHERE id = 1").fetchone()[0]
    assert after_ts == before_ts, "投影失败时 wb_state.updated_at 不得变化（半写）"
