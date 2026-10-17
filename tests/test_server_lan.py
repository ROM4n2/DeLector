# -*- coding: utf-8 -*-
"""局域网 CORS 与 lan-info 域的端点测试（C6 Task 4 自 `tests/test_server.py` 逐字搬出）。

搬出的两段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `3071`-`3147`  局域网 CORS（lan-silent-sync Stage A Task 1）
  `3148`-`3169`  GET /api/wb/lan-info（lan-silent-sync Stage A Task 2）

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client /
lan_client）住在 `tests/server_helpers.py` 与 `tests/conftest.py`，按名即可见。
"""

from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client

# ── 局域网 CORS（docs/plans/archive/2026-09-03-lan-silent-sync-stage-a.md Task 1）──
# 手机 APP 的 WebView 页面 origin 是它自己的 127.0.0.1:8000（Chaquopy 本地 server），
# 要跨域访问桌面 192.168.x.x 的 /api/wb/state 必须拿到 ACAO 反射；公网 Origin 不得反射。


def test_wb_state_cors_loopback_origin_reflected(lan_client):
    """APP WebView（origin=http://127.0.0.1:8000）跨域读镜像需 ACAO 反射。"""
    origin = "http://127.0.0.1:8000"
    r = lan_client.get("/api/wb/state", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_wb_state_cors_private_lan_origin_reflected(lan_client):
    """同局域网私有网段 origin（另一台设备的 http://192.168.x.x）也反射。"""
    origin = "http://192.168.1.88:8000"
    r = lan_client.get("/api/wb/state", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_wb_state_cors_public_origin_not_reflected(lan_client):
    """公网恶意站点 Origin 不得拿到跨域读权限（无 ACAO → 浏览器拦截响应）。"""
    r = lan_client.get("/api/wb/state", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_wb_state_put_preflight_loopback_allows_methods_and_key(lan_client):
    """PUT（JSON + X-WB-Key）触发浏览器预检：回环 Origin 需放行方法与自定义头。"""
    origin = "http://127.0.0.1:8000"
    r = lan_client.options(
        "/api/wb/state",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type, x-wb-key",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    assert "PUT" in r.headers.get("access-control-allow-methods", "")
    assert "X-WB-Key" in r.headers.get("access-control-allow-headers", "")


def test_wb_state_put_preflight_public_origin_not_allowed(lan_client):
    """公网 Origin 的预检不放行：显式 403 且不给 ACAO，浏览器按跨域失败处理。

    任务书契约是「公共 Origin 预检 403」，不是「无路由落 405」：
    405 靠没有 ACAO 兜底，语义含糊；403 才是明确的拒绝。
    """
    r = lan_client.options(
        "/api/wb/state",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_wb_sync_signaling_cors_loopback(lan_client):
    """WebRTC 信令端点（/api/wb/sync/*）同样对回环 Origin 反射（Stage B 铺垫）。"""
    origin = "http://127.0.0.1:8000"
    r = lan_client.get("/api/wb/sync/info", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_wb_state_no_origin_header_unchanged(client):
    """无 Origin 头（本机/同源/存量 TestClient 用例）→ 不加 ACAO，行为与现状一致。"""
    r = client.get("/api/wb/state")
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


# ── GET /api/wb/lan-info（docs/plans/archive/2026-09-03-lan-silent-sync-stage-a.md Task 2）──


def test_wb_lan_info_open_to_lan(lan_client):
    """局域网设备可读主机信息（供配对 UI 提示填 IP）；不含密钥等机密。"""
    r = lan_client.get("/api/wb/lan-info")
    assert r.status_code == 200
    body = r.json()
    assert body.get("port") == 8000
    assert body.get("hostname")
    assert body.get("instance_id")
    # 决不允许混入同步密钥/秘密
    assert "key" not in body and "secret" not in body


def test_wb_lan_info_does_not_leak_sync_key(lan_client, client):
    """lan-info 响应文本不含 X-WB-Key 值；同步 key 仍只经本机端点取。"""
    r = lan_client.get("/api/wb/lan-info")
    assert "X-WB-Key" not in r.text
    assert client.get("/api/wb/state/key").status_code == 200
