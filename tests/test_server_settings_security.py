# -*- coding: utf-8 -*-
"""安全 / 设置域的端点测试（C6 Task 5 自 `tests/test_server.py` 逐字搬出）。

搬出的五段（搬前 `test_server.py` 行号，实测，含各段头注释与段间空行）：
  `1183`-`1253`  查词链修复测试（lemma-first / EXT 接线 / 诚实 source）
  `1254`-`1671`  安全加固回归：SSRF 多地址校验 / 重定向逐跳预校验 / TTS 长度闸
          + IPv6 过渡格式子段（判定落在「内嵌的目的 IPv4」上）
  `1672`-`1798`  v4.4 Task1 Settings localhost-only 边界（段尾含 C8 Task6 的回环来源
          字段集合锚 `_SETTINGS_LOOPBACK_KEYS` 与其 2 条用例，同段逐字随搬）
  `1950`-`1976`  GET /api/audio/tts
  `1977`-`2668`  Task 1 Hardening & Regression Test Suite

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client /
lan_client / test_db_path）住在 `tests/server_helpers.py` 与 `tests/conftest.py`，
按名即可见。
"""

import ipaddress
import json
import os
import re

import pytest
from fastapi.testclient import TestClient
from server_helpers import ROOT, _calls_named, _package_windows_build_windows_fn
from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client
from server_helpers import test_db_path as test_db_path

from delector import server
from delector.core.database import db_conn, db_progress_conn
from delector.routes.main import ingest_from_url
from delector.server import app, is_safe_public_url, set_setting

# ── 查词链修复测试（lemma-first / EXT 接线 / 诚实 source）────────────────────


def test_lookup_lemma_first(client, monkeypatch):
    """前端带 lemma → 直接命中核心词库，不触发 AI。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht", "lemma": "gehen"})
    data = r.json()
    assert data["source"] == "local_dict"
    assert "去" in data["definition_zh"]


def test_lookup_lemma_absent_present_irregular(client, monkeypatch):
    """无 lemma 时 geht 靠现在时反查 → stammformen + 三态表释义回填。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht"})
    data = r.json()
    assert data.get("stammformen", {}).get("infinitiv") == "gehen"
    assert data["definition_zh"]
    assert data["source"] == "linguistics"


def test_lookup_plural_haeuser(client, monkeypatch):
    """变元音复数 Häuser + lemma Haus → 核心词库命中。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post(
        "/api/lookup/vocab", json={"sentence": "Die Häuser sind alt.", "target_word": "Häuser", "lemma": "Haus"}
    )
    data = r.json()
    assert data["source"] == "local_dict"
    assert "房屋" in data["definition_zh"]


def test_lookup_linguistics_ext_tier(client, monkeypatch):
    """主链查不到时落 EXT（LINGUISTICS_VOCAB_EXT 接线）。

    探针词从旧的 ``klima`` 换为 ``tunnel``：官方词表接入主干后 ``klima`` 已是
    core_dict 命中词（source=local_dict），不再能证明 EXT 回退层；``tunnel`` 只在
    LINGUISTICS_VOCAB_EXT、不在任何主干分片里，仍能钉住这条回退链。
    """
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Tunnel.", "target_word": "tunnel"})
    data = r.json()
    assert data["source"] == "linguistics_ext"
    assert "隧道" in data["definition_zh"]


def test_lookup_no_hit_honest_none(client, monkeypatch):
    """未知词 + 无 key → source=none 空释义（不再是 AI 已预填谎言）。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "")
    r = client.post("/api/lookup/vocab", json={"sentence": "Xyzzy.", "target_word": "zzzznonsense"})
    data = r.json()
    assert data["source"] == "none"
    assert not data["definition_zh"]


def test_lookup_ai_error_backfill_linguistics(client, monkeypatch):
    """key 假 + httpx 崩 → ai_exception；强动词变位词回填三态表释义。"""
    monkeypatch.setattr("delector.routes.main.get_effective_api_key", lambda: "sk-bogus")

    class _BoomClient:
        def post(self, *a, **k):
            raise RuntimeError("simulated network down")

    monkeypatch.setattr("delector.routes.main.httpx.AsyncClient", lambda *a, **k: _BoomClient())
    r = client.post("/api/lookup/vocab", json={"sentence": "Er geht.", "target_word": "geht"})
    data = r.json()
    assert data["source"] == "linguistics"
    assert data["definition_zh"]


# ── 安全加固回归：SSRF 多地址校验 / 重定向逐跳预校验 / TTS 长度闸 ─────────────


def test_is_safe_public_url_rejects_when_any_resolved_ip_is_private(monkeypatch):
    """域名解析出的每一条地址都必须过闸。

    只查第一条 A 记录的旧写法（gethostbyname）会放过「公网 A 记录掩护下的
    内网 A/AAAA 记录」组合。monkeypatch 同时钉住新旧两条解析路径：
    旧实现查 gethostbyname 拿到公网 IP 会误判通过，本测试对它是红的。
    """
    import socket as _socket

    public_ip, private_v6 = "93.184.216.34", "fd00::1"

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (public_ip, port or 0)),
            (_socket.AF_INET6, _socket.SOCK_STREAM, 17, "", (private_v6, port or 0)),
        ]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_socket, "gethostbyname", lambda host: public_ip)

    assert is_safe_public_url("https://mixed-dns.example/") is False


def test_is_safe_public_url_accepts_all_public_resolution(monkeypatch):
    """全部地址都是公网时照常放行，不能因为加了校验而误杀正常站点。"""
    import socket as _socket

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0)),
            (_socket.AF_INET6, _socket.SOCK_STREAM, 17, "", ("2606:2800:220:1:248:1893:25c8:1946", port or 0)),
        ]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    assert is_safe_public_url("https://all-public.example/") is True


# ── IPv6 过渡格式：判定必须落在「内嵌的目的 IPv4」上，而不是外层包装 ────────────


def _pin_resolution(monkeypatch, addr: str):
    """把 getaddrinfo 钉成只返回 addr 一条，避免测试依赖真实 DNS。"""
    import socket as _socket

    family = _socket.AF_INET6 if ":" in addr else _socket.AF_INET
    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (family, _socket.SOCK_STREAM, 6, "", (addr, 443, 0, 0)),
        ],
    )


@pytest.mark.parametrize(
    "addr, note",
    [
        ("2002:c0a8:0101::1", "6to4 内嵌 192.168.1.1"),
        ("2002:7f00:0001::1", "6to4 内嵌 127.0.0.1"),
        ("2002:a9fe:a9fe::1", "6to4 内嵌 169.254.169.254 云元数据"),
        ("2001:0:0:0:0:0:3f57:fefe", "Teredo client 内嵌 192.168.1.1"),
        ("2001:0:c0a8:101:0:0:4746:748", "Teredo server 内嵌 192.168.1.1"),
        ("::ffff:127.0.0.1", "IPv4-mapped 回环"),
        ("::ffff:10.0.0.5", "IPv4-mapped 内网"),
    ],
)
def test_is_safe_public_url_rejects_ipv4_smuggled_in_ipv6(monkeypatch, addr, note):
    """内网 IPv4 套进 IPv6 过渡格式后必须照样被拦。

    这是真能打进内网的 SSRF 通道，不是理论风险：6to4 的 `2002:c0a8:0101::1`
    外层 `is_global` 为真、六个旗标一个不沾，旧写法（只看外层 `is_private` 等）
    对它一路放行，而内核会把包路由到 192.168.1.1。
    """
    _pin_resolution(monkeypatch, addr)
    assert is_safe_public_url("https://smuggle.example/") is False, note


@pytest.mark.parametrize(
    "addr, note",
    [
        ("2001::b92d:7b9", "Teredo client 70.210.248.70 公网、server 段全零"),
        ("2002:8080:8080::1", "6to4 内嵌 128.128.128.128 公网"),
        ("::ffff:8.8.8.8", "IPv4-mapped 公网"),
    ],
)
def test_is_safe_public_url_accepts_public_target_behind_ipv6_transition(monkeypatch, addr, note):
    """过渡格式包着公网地址时必须放行——修误放不能顺手把误拒留下。

    `2001::/32`(Teredo) 落在 ipaddress 的私有段清单 `2001::/23` 里、
    `::ffff:0:0/96` 被判 `is_reserved`，只看外层旗标会把它们全拒掉：
    本机 `www.dw.com` 曾解析出 `2001::b92d:7b9`，于是 URL 导入对**所有**站点
    全废。CI 的 Linux runner 没有 Teredo，这个方向在 CI 上永远看不见。
    """
    _pin_resolution(monkeypatch, addr)
    assert is_safe_public_url("https://transition.example/") is True, note


_IPV6_SPECIAL_ADDRS = (
    "2001:db8::1",  # documentation（在 2001::/23 之外）
    "2001:2::1",  # benchmarking
    "2001:3::1",  # AMT
    "2001:4:112::1",  # AS112-v6
    "2001:10::1",  # ORCHID（已弃用）
    "2001:20::1",  # ORCHIDv2 —— 3.11.16 上从 ipaddress 的表里掉了出来
    "2001:30::1",  # Drone Remote ID
    "100::1",  # discard-only
    "5f00::1",  # SRv6 SID
    "64:ff9b:1::1",  # 本地用 IPv4/IPv6 转换
)


def test_is_safe_public_url_still_rejects_non_teredo_2001_ranges(monkeypatch):
    """`2001::/23` 里除 Teredo 之外的保留段不能被顺手放开。

    修法是「只对 Teredo/6to4/IPv4-mapped 解包」，不是「把 2001:: 整段当公网」。
    """
    for addr in _IPV6_SPECIAL_ADDRS:
        _pin_resolution(monkeypatch, addr)
        assert is_safe_public_url("https://reserved.example/") is False, addr


def test_ipv6_special_ranges_are_pinned_in_our_own_code():
    """这些段必须由**我们自己的常量**兜住，不能只靠 `ipaddress` 的私有段表。

    那张表会随 Python 补丁版本变：3.11.8 里有一条粗粒度的 `2001::/23`，把整个
    IETF Protocol Assignments 块兜住；3.11.16 换成细粒度条目后 `2001:20::/28`
    (ORCHIDv2) 掉了出来，闸门就此放行。同一份代码、同一个 3.11 大版本，
    判定结果相反 —— 本机绿而 CI 红，v4.4.8 首次发布就是这么挂的。
    """
    import ipaddress as _ip

    from delector import server as _srv

    for addr in _IPV6_SPECIAL_ADDRS:
        obj = _ip.ip_address(addr)
        assert obj in _srv._IETF_PROTOCOL_ASSIGNMENTS or any(obj in net for net in _srv._IPV6_DENY_PREFIXES), (
            f"{addr} 只靠 ipaddress 的表兜着，换个 Python 补丁版本就会漏"
        )


class _FlaglessIPv6(ipaddress.IPv6Address):
    """把 stdlib 的所有旗标压成假的 IPv6 地址替身。

    要单独验证「我们自己钉的段」在起作用，就必须把 `ipaddress` 那张表的贡献
    摘干净：真地址在 3.11.8 上会被粗粒度的 `2001::/23` 条目兜住，把
    `_is_blocked_addr` 里我们的范围检查整段删掉，本机照样全绿 —— v4.4.8
    第一次发版就是这么被放过去的。

    为什么不改 stdlib 那张表来模拟 CI 的 Python：3.11.8 的 `is_private` 上还挂着
    `functools.lru_cache`，只要**任何**更早的测试算过同一个地址，结果就被永久缓存，
    之后改表毫无作用 —— 测试会随执行顺序时红时绿。替身不碰 CPython 内部，
    换 Python 版本也不会漂。
    """

    is_private = False
    is_loopback = False
    is_link_local = False
    is_reserved = False
    is_multicast = False
    is_unspecified = False


def test_is_blocked_addr_relies_on_our_own_pinned_ranges():
    """旗标全假时仍要拒 —— 拒绝理由只能来自我们钉的段，不能来自 stdlib。"""
    for addr in _IPV6_SPECIAL_ADDRS:
        assert server._is_blocked_addr(_FlaglessIPv6(addr)) is True, addr

    # 反向：替身不是「什么都拒」。公网地址、以及 Teredo 包着的公网 IPv4
    # （已在 `_resolve_ssrf_targets` 里解包成 70.210.248.70）都必须放行。
    for addr in ("2a03:2880:f11b:83:face:b00c:0:25de", "2606:4700::1111", "2001::b92d:7b9"):
        assert server._is_blocked_addr(_FlaglessIPv6(addr)) is False, addr


def test_url_ingest_gate_is_pinned_not_dns_dependent():
    """端点实现必须经过 is_safe_public_url 门禁保护，防止盲 SSRF。

    `ingest_from_url` 必须在发出网络请求前通过 `is_safe_public_url` 校验请求 URL。
    """
    import inspect

    src = inspect.getsource(ingest_from_url)
    assert "is_safe_public_url(req.url)" in src, "端点必须钉住 SSRF 闸，必须先做安全校验"


def test_fetch_remote_html_never_requests_blocked_redirect_target(monkeypatch):
    """重定向目标必须在请求发出**之前**过 SSRF 闸。

    follow_redirects=True 的旧写法先打请求、后校验最终 URL——重定向到内网时
    内网服务已经收到 GET（盲 SSRF），哪怕响应随后被丢弃。
    """
    import asyncio
    import ipaddress as _ipaddress
    import socket as _socket

    from fastapi import HTTPException

    import delector.core.security as security

    requested = []

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        host = host.strip("[]")
        try:
            _ipaddress.ip_address(host)  # 字面量 IP 原样返回，让内网判定照常生效
        except ValueError:
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (host, port or 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    def fake_gethostbyname(host):
        # 字面量内网 IP 原样返回，旧实现的最终校验才能识别它；
        # 其余域名一律解析成公网 IP——否则 .example 真实解析失败会在
        # 请求发出前就被拒，测试对旧实现假绿。
        return host if host.startswith("169.254") else "93.184.216.34"

    monkeypatch.setattr(_socket, "gethostbyname", fake_gethostbyname)

    class FakeResp:
        def __init__(self, status_code, headers=None, text="", url=""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self.url = url

        @property
        def is_redirect(self):
            return self.status_code in (301, 302, 303, 307, 308)

    class FakeClient:
        """按构造参数忠实模拟 httpx 的跟随语义：follow_redirects=True（旧实现）
        在 get() 内部自动追跳每一跳；False 时原样返回 3xx，由服务端逐跳驱动。"""

        def __init__(self, *args, follow_redirects=False, **kwargs):
            self.follow_redirects = follow_redirects

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            url = str(url)
            while True:
                requested.append(url)
                if url == "https://public-start.example/article":
                    if self.follow_redirects:
                        url = "http://169.254.169.254/latest/meta-data/"
                        continue
                    return FakeResp(302, {"location": "http://169.254.169.254/latest/meta-data/"}, url=url)
                if url.startswith("http://169.254.169.254"):
                    # 内网目标照常「应答」——旧实现下这个请求已经发生（盲 SSRF）
                    return FakeResp(200, {}, "fake-internal-body", url=url)
                return FakeResp(200, {}, "<html>ok</html>", url=url)

    monkeypatch.setattr(security.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://public-start.example/article"))
    assert exc_info.value.status_code == 400
    assert all("169.254" not in u for u in requested), f"盲 SSRF 发生了: {requested}"


def test_fetch_remote_html_still_follows_public_redirects(monkeypatch):
    """公网站点之间的正常重定向链不受影响——加固不能误杀正常抓取。"""
    import asyncio
    import socket as _socket

    import delector.core.security as security

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(_socket, "gethostbyname", lambda host: "93.184.216.34")

    requested = []

    class FakeResp:
        def __init__(self, status_code, headers=None, text="", url=""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self.url = url

        @property
        def is_redirect(self):
            return self.status_code in (301, 302, 303, 307, 308)

    class FakeClient:
        """与被拒测试同一套跟随语义：True 时桩内追跳（旧行为），False 时裸 3xx。"""

        def __init__(self, *args, follow_redirects=False, **kwargs):
            self.follow_redirects = follow_redirects

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            url = str(url)
            while True:
                requested.append(url)
                if url == "https://short.example/x":
                    if self.follow_redirects:
                        url = "https://short.example/final"
                        continue
                    return FakeResp(302, {"location": "/final"}, url=url)
                return FakeResp(200, {}, "<html>ok</html>", url=url)

    monkeypatch.setattr(security.httpx, "AsyncClient", FakeClient)

    body = asyncio.run(security.fetch_remote_html("https://short.example/x"))
    assert body == "<html>ok</html>"
    assert len(requested) == 2


def test_fetch_remote_html_network_error_returns_502(monkeypatch):
    """P1-3: 出网抓取遇到 DNS/连接失败/httpx.HTTPError 时，必须返回 502 并携带明确人话说明。"""
    import asyncio
    import socket as _socket

    import httpx
    from fastapi import HTTPException

    import delector.core.security as security

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda *a, **kw: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    class ErrorClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("Connection refused by peer")

        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("Connection refused by peer")

    monkeypatch.setattr(security.httpx, "AsyncClient", ErrorClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://example.com/unreachable"))
    assert exc_info.value.status_code == 502
    assert "连接失败" in exc_info.value.detail or "ConnectError" in exc_info.value.detail


def test_fetch_remote_html_total_timeout_returns_502(monkeypatch):
    """P1-3: 出网抓取总耗时超出截止时间时，必须掐断并返回 502。"""
    import asyncio
    import socket as _socket

    from fastapi import HTTPException

    import delector.core.security as security

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda *a, **kw: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    class SlowClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            await asyncio.sleep(0.5)
            return None

        def stream(self, *args, **kwargs):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _slow_stream():
                await asyncio.sleep(0.5)
                yield None

            return _slow_stream()

    monkeypatch.setattr(security.httpx, "AsyncClient", SlowClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(security.fetch_remote_html("https://example.com/slow", total_timeout=0.05))
    assert exc_info.value.status_code == 502
    assert "超时" in exc_info.value.detail


def test_tts_rejects_oversized_text(client):
    """朗读接口有长度上限：局域网可达的端点不该被超大文本打满合成与磁盘缓存。"""
    res = client.post("/api/audio/tts", json={"text": "A" * 1001})
    assert res.status_code == 400


# ── v4.4 Task1: Settings localhost-only security boundary (failing before Task2) ──


def test_settings_post_rejects_non_loopback_client(lan_client):
    """非本机不得修改敏感设置：POST /api/settings 来自局域网必须 403。"""
    res = lan_client.post("/api/settings", json={"api_key": "sk-should-be-rejected"})
    assert res.status_code == 403


def test_settings_test_key_rejects_non_loopback_client(lan_client):
    """非本机不得测试连通性：POST /api/settings/test-key 来自局域网必须 403。"""
    res = lan_client.post("/api/settings/test-key", json={"api_key": "sk-any"})
    assert res.status_code == 403


def test_settings_post_lan_does_not_mutate_sensitive_settings(lan_client, test_db_path):
    """被 403 时数据库中的敏感设置必须保持不变。"""
    import sqlite3

    set_setting("DEEPSEEK_API_KEY", "sk-original-keep", db_path=test_db_path)
    set_setting("API_BASE_URL", "https://original.example/v1", db_path=test_db_path)

    res = lan_client.post(
        "/api/settings",
        json={
            "api_key": "sk-hacked-rejected",
            "api_base_url": "https://evil.example/v1",
        },
    )
    assert res.status_code == 403

    conn = sqlite3.connect(test_db_path)
    rows = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM app_settings").fetchall()}
    conn.close()
    assert rows.get("DEEPSEEK_API_KEY") == "sk-original-keep"
    assert rows.get("API_BASE_URL") == "https://original.example/v1"


def test_settings_test_key_lan_does_not_leak_or_mutate(lan_client, test_db_path):
    """test-key 被 403 时也不得改库或泄露信息。"""
    import sqlite3

    set_setting("DEEPSEEK_API_KEY", "sk-keep-intact", db_path=test_db_path)
    res = lan_client.post("/api/settings/test-key", json={"api_key": "sk-evil"})
    assert res.status_code == 403
    conn = sqlite3.connect(test_db_path)
    val = conn.execute("SELECT value FROM app_settings WHERE key='DEEPSEEK_API_KEY'").fetchone()
    conn.close()
    assert val and val[0] == "sk-keep-intact"


def test_settings_post_succeeds_on_loopback(client):
    """回环来源的合法设置更新仍返回成功；已有 /api/settings 行为保持不变。"""
    res = client.post(
        "/api/settings",
        json={
            "api_key": "sk-loopback-ok-1234567890",
            "api_base_url": "https://api.loopback.example/v1",
            "tts_voice": "de-DE-ConradNeural",
        },
    )
    assert res.status_code == 200
    assert res.json().get("success") is True

    # verify persisted and masked correctly
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["has_api_key"] is True
    assert data["api_base_url"] == "https://api.loopback.example/v1"
    assert data["tts_voice"] == "de-DE-ConradNeural"


def test_settings_test_key_succeeds_on_loopback(client, monkeypatch):
    """回环来源的 test-key 不应被 403 拦截（空 key 时返回 success=False 而非 403）。"""
    # 同上：切断本机 .env 真 key，避免真实外呼（密闭性 + 不烧 token）。
    monkeypatch.setattr("delector.routes.settings.get_effective_api_key", lambda *a, **k: "")
    res = client.post("/api/settings/test-key", json={"api_key": ""})
    # 未被来源闸拦截：返回 200 且 success 为 False（提示输入 key），而非 403
    assert res.status_code == 200
    assert res.json().get("success") is False


# GET /api/settings 回环来源的字段集合口径锚（C8 Task6）：非回环来源恰好少
# `api_key_masked` 一项，其余逐字一致——否则桌面端会静默失去配置面板。
_SETTINGS_LOOPBACK_KEYS = {
    "has_api_key",
    "api_key_masked",
    "api_base_url",
    "api_model",
    "tts_voice",
    "tts_rate",
    "nlp_engine",
    "nlp_engine_detail",
    "reasoning_effort",
}


def test_settings_get_loopback_origin_keeps_api_key_masked_field():
    """回环来源（127.0.0.1）的字段集合 MUST 与今日逐字一致。"""
    loopback = TestClient(app, client=("127.0.0.1", 54321))
    res = loopback.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == _SETTINGS_LOOPBACK_KEYS
    assert "api_key_masked" in data


def test_settings_get_non_loopback_origin_omits_api_key_masked_field():
    """非回环来源（192.168.1.50）不得读到 api key（哪怕已掩码）。

    注意这是**按来源收敛字段**，不是整门拦截：局域网手机端仍要能读 base_url /
    model / tts_* 来渲染设置面板（前端 static/js/main.js:632-634），
    故 MUST NOT 加 `_require_localhost`（那会让手机端直接吃 403）。
    """
    lan = TestClient(app, client=("192.168.1.50", 54322))
    res = lan.get("/api/settings")
    assert res.status_code == 200, "LAN 来源必须仍能读该端点（不得整门 403）"
    data = res.json()
    assert "api_key_masked" not in data
    assert set(data.keys()) == _SETTINGS_LOOPBACK_KEYS - {"api_key_masked"}
    # 只收敛这一项：其余字段照旧
    assert "has_api_key" in data
    assert "api_base_url" in data
    assert "api_model" in data
    assert "tts_voice" in data


# ── GET /api/audio/tts ───────────────────────────────────────────────────────


def test_get_audio_tts_returns_mp3(client):
    """GET 版 TTS 端点：供 workbench <audio src> 直接用，无需 fetch + blob。"""
    r = client.get("/api/audio/tts", params={"text": "hallo"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert len(r.content) > 0
    assert 'filename="speech.mp3"' in r.headers.get("content-disposition", "")


def test_get_audio_tts_rejects_empty_text(client):
    r = client.get("/api/audio/tts", params={"text": ""})
    assert r.status_code == 400


def test_get_audio_tts_rejects_overlong_text(client):
    r = client.get("/api/audio/tts", params={"text": "x" * 1001})
    assert r.status_code == 400


def test_get_audio_tts_rejects_malformed_rate(client):
    r = client.get("/api/audio/tts", params={"text": "hallo", "rate": "banana"})
    assert r.status_code == 400


# ── Task 1 Hardening & Regression Test Suite ──────────────────────────────────


def test_task1_restore_req_includes_a1_records(client):
    """RestoreReq 正确支持 a1_hoeren_records 与 a1_lesen_records 还原。"""
    payload = {
        "version": 2,
        "a1_hoeren_records": [
            {
                "id": 101,
                "set_id": 1,
                "score_raw": 14,
                "score_official": 23.3,
                "total_questions": 15,
                "duration_seconds": 580,
                "answers_json": '{"q1": "A"}',
                "wrong_questions_json": "[]",
                "created_at": "2026-09-01T12:00:00",
            }
        ],
        "a1_lesen_records": [
            {
                "id": 201,
                "set_id": 2,
                "score_raw": 13,
                "score_official": 21.7,
                "total_questions": 15,
                "duration_seconds": 650,
                "answers_json": '{"q1": "B"}',
                "wrong_questions_json": "[]",
                "created_at": "2026-09-01T12:00:00",
            }
        ],
    }
    res = client.post("/api/backup/restore", json=payload)
    assert res.status_code == 200

    with db_progress_conn() as pconn:
        h = pconn.execute("SELECT * FROM a1_hoeren_records WHERE id = 101").fetchone()
        lr = pconn.execute("SELECT * FROM a1_lesen_records WHERE id = 201").fetchone()
    assert h is not None and h["score_raw"] == 14
    assert lr is not None and lr["score_raw"] == 13


def test_task1_review_card_computes_elapsed_days(client):
    """review_card_sm2 从 due_date 计算真实的 elapsed_days。"""
    from datetime import datetime, timedelta

    ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO vocab_cards (word, lemma, pos, cefr_level, definition_zh, sentence_context,
                interval_days, ease_factor, repetition_count, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            ("TestWord", "TestWord", "NOUN", "A1", "测试词义", "Context sentence", 3, 2.5, 2, ten_days_ago),
        )
        card_id = cur.lastrowid

    # 逾期 10 天复习，elapsed_days 应 > interval_days (3)
    res = client.post(f"/api/cards/vocab/{card_id}/review", json={"grade": 3})
    assert res.status_code == 200
    data = res.json()
    assert data["interval_days"] > 3


def test_task1_tts_fallback_chain_on_mini_failure(monkeypatch):
    """当 edge_tts 缺失且 edge_tts_mini 抛异常时，平滑降级到备选引擎。"""
    import asyncio
    import sys


    # 模拟 edge_tts 缺失
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    # 模拟 edge_tts_mini（services.tts）失败
    class FakeMini:
        @staticmethod
        def synthesize(*args, **kwargs):
            raise RuntimeError("Mini TTS simulated error")

    monkeypatch.setitem(sys.modules, "delector.services.tts", FakeMini)

    # 模拟有道兜底响应
    class MockHttpxResp:
        status_code = 200
        content = b"ID3" + b"\x00" * 300  # 合法音频 mock 数据

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, *args, **kwargs):
            return MockHttpxResp()

    from delector.routes import audio as routes_audio

    monkeypatch.setattr(routes_audio.httpx, "AsyncClient", MockAsyncClient)

    audio_file = asyncio.run(routes_audio.generate_edge_tts_audio("Guten Morgen", voice="de-DE-KatjaNeural"))
    assert os.path.exists(audio_file)
    assert os.path.getsize(audio_file) > 200


def test_task1_localhost_protection_on_destructive_endpoints(client, lan_client):
    """验证 delete_article, delete_card, clear_audio_cache, delete_essay, delete_essay_version 的局域网拦截。"""
    # 1. 局域网访问一律 403
    assert lan_client.delete("/api/articles/999").status_code == 403
    assert lan_client.delete("/api/cards/vocab/999").status_code == 403
    assert lan_client.post("/api/audio/cache/clear").status_code == 403
    assert lan_client.delete("/api/essays/999").status_code == 403
    assert lan_client.delete("/api/essays/999/versions/999").status_code == 403

    # 2. 本机访问正常通过拦截（业务 404 或 200）
    assert client.delete("/api/articles/999").status_code == 404
    assert client.delete("/api/cards/vocab/999").status_code == 404
    assert client.post("/api/audio/cache/clear").status_code == 200
    assert client.delete("/api/essays/999").status_code == 404
    assert client.delete("/api/essays/999/versions/999").status_code == 404


def test_task1_get_article_corrupted_json(client):
    """get_article 面对损坏的 processed_json 能够平滑重新分析，不产生 500。"""
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO articles (title, raw_text, processed_json)
            VALUES (?, ?, ?)
        """,
            ("Corrupted Test", "Das ist ein Test.", "{invalid json broken syntax"),
        )
        art_id = cur.lastrowid

    res = client.get(f"/api/articles/{art_id}")
    assert res.status_code == 200
    data = res.json()
    assert "stats" in data
    assert data["sentence_count"] >= 1


def test_task1_create_writing_card_bounds_check(client):
    """save_writing_card 对越界的 sentence_id / span_index 进行防御性校验，返回 400 而非 500。"""
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO essays (title, content, analysis_json, cefr_level, error_count, sentence_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            ("Essay", "Content", json.dumps({"sentences": [{"text": "Hallo", "spans": []}]}), "A1", 0, 1),
        )
        essay_id = cur.lastrowid

    # 越界 sentence_id
    res1 = client.post("/api/writing/cards", json={"essay_id": essay_id, "sentence_id": 99, "span_index": 0})
    assert res1.status_code == 400

    # 越界 span_index
    res2 = client.post("/api/writing/cards", json={"essay_id": essay_id, "sentence_id": 0, "span_index": 99})
    assert res2.status_code == 400


def test_task1_is_safe_public_url_port_validation(monkeypatch):
    """is_safe_public_url 仅允许白名单端口 (80, 443, 8080, 8443, None)。"""
    import socket as _socket

    monkeypatch.setattr(
        _socket, "getaddrinfo", lambda host, port: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    )

    # 允许的端口
    assert is_safe_public_url("https://example.com") is True
    assert is_safe_public_url("http://example.com:80") is True
    assert is_safe_public_url("https://example.com:443") is True
    assert is_safe_public_url("http://example.com:8080/rss") is True
    assert is_safe_public_url("https://example.com:8443/feed") is True

    # 危险端口必须拒绝
    assert is_safe_public_url("http://example.com:22") is False
    assert is_safe_public_url("http://example.com:25") is False
    assert is_safe_public_url("http://example.com:3306") is False
    assert is_safe_public_url("http://example.com:6379") is False
    assert is_safe_public_url("http://example.com:27017") is False


def test_task1_fetch_remote_html_max_bytes_limit(monkeypatch):
    """fetch_remote_html 拦截 Content-Length > 2MB 或流式传输体积超过 2MB 的响应。"""
    import asyncio
    import socket as _socket

    from fastapi import HTTPException

    from delector.routes import main as routes_main

    monkeypatch.setattr(
        _socket, "getaddrinfo", lambda host, port: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    )

    class BigContentLengthResp:
        status_code = 200
        headers = {"content-length": str(3 * 1024 * 1024)}  # 3MB
        is_redirect = False

        async def aiter_bytes(self):
            yield b"small"

    class BigStreamResp:
        status_code = 200
        headers = {}
        is_redirect = False

        async def aiter_bytes(self):
            # 产生超过 2MB 的 chunk
            for _ in range(5):
                yield b"A" * (600 * 1024)

    class StreamMockClient:
        def __init__(self, mode="header"):
            self.mode = mode

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        from contextlib import asynccontextmanager  # type: ignore[misc]

        @asynccontextmanager
        async def stream(self, method, url, headers=None):
            if self.mode == "header":
                yield BigContentLengthResp()
            else:
                yield BigStreamResp()

    from delector.core import security as core_security

    # 1. 响应头 Content-Length 超过 2MB
    monkeypatch.setattr(core_security.httpx, "AsyncClient", lambda *args, **kwargs: StreamMockClient("header"))
    with pytest.raises(HTTPException) as exc1:
        asyncio.run(routes_main.fetch_remote_html("https://example.com/big-header"))
    assert exc1.value.status_code == 400
    assert "体积超限" in exc1.value.detail

    # 2. 实际传输流数据超过 2MB
    monkeypatch.setattr(core_security.httpx, "AsyncClient", lambda *args, **kwargs: StreamMockClient("stream"))
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(routes_main.fetch_remote_html("https://example.com/big-stream"))
    assert exc2.value.status_code == 400
    assert "体积超限" in exc2.value.detail


def test_task1_a1_anki_export_has_attachment_headers(client):
    """A1 Anki 导出接口携带符合规范的 _attachment_headers (含 no-store 与 UTF-8 编码文件名)。"""
    res = client.get("/api/a1/export/anki")
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert 'filename="Goethe_A1_Wortliste.apkg"' in cd
    assert "no-store" in res.headers.get("cache-control", "")


def test_task1_sync_router_thread_safety(client):
    """WebRTC 同步路由器具备 _sync_lock 保护，能正常存取。"""
    from delector.routes import sync as routes_sync

    assert hasattr(routes_sync, "_sync_lock")

    key = client.get("/api/wb/state/key").json()["key"]
    store_res = client.post(
        "/api/wb/sync/store",
        json={"sdp": {"type": "offer", "sdp": "v=0..."}, "role": "offer"},
        headers={"X-WB-Key": key},
    )
    assert store_res.status_code == 200
    code = store_res.json()["code"]

    fetch_res = client.get(f"/api/wb/sync/fetch/{code}", headers={"X-WB-Key": key})
    assert fetch_res.status_code == 200
    assert fetch_res.json()["role"] == "offer"


def test_task1_corpus_dict_registered_in_all_packaging_targets():
    """corpus_dict 完整注册在 package_windows.py, CI workflow 以及 DeLector.spec 中。"""
    root = ROOT
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert "--hidden-import=delector.data.corpus_dict" in pkg
    assert "--hidden-import=delector.data.core_dict" in pkg

    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert wf.count("--hidden-import=delector.data.corpus_dict") == 2, "Linux & macOS 两个构建都要"

    # DeLector.spec 是本地 PyInstaller 产物：.gitignore 的 `*.spec` 把它排除，且 CI 里
    # pytest 跑在 package_windows.py / PyInstaller 之前，干净 checkout 下必然不存在。
    # 用显式 skip 而非静默 if，避免 CI 输出里看起来"通过了"其实一条都没断言。
    spec_path = os.path.join(root, "DeLector.spec")
    if not os.path.exists(spec_path):
        pytest.skip("DeLector.spec 未生成（本地构建产物，非 canonical）——跳过 spec 断言")
    spec = open(spec_path, encoding="utf-8").read()
    assert "'delector.data.corpus_dict'" in spec
    assert "'delector.routes.corpus'" in spec


def test_all_backend_modules_registered_in_all_packaging_targets():
    """所有路由与核心词典模块必须完整注册在 package_windows.py、CI workflow 以及 Android 拷贝清单中。

    防范 regression：
    - v4.8.1：routes_corpus.py 遗漏导致 Android APK 崩溃
    - v5.2.0：routes_rtc.py, routes_exam.py, exam_catalog.py 遗漏导致 Chaquopy 启动报
      ModuleNotFoundError: No module named 'routes_rtc'
    """
    root = ROOT
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()

    # Phase 1 Task 2：8 个纯数据词典已收进 delector.data/ 子包
    # T5：encounter_seed_dict 为第 9 个纯数据模块（被 database.py 延迟导入），
    # 逐条钉死进打包面，否则打包后运行期 ModuleNotFoundError 而本地全绿。
    data_dict_modules = {
        "core_dict",
        "core_dict_ext",
        "prep_dict",
        "a1_dict",
        "a1_writing_dict",
        "a1_hoeren_dict",
        "a1_lesen_dict",
        "corpus_dict",
        "encounter_seed_dict",
        # ADR-0011 Task 1：A1 工作台词库单一真相（被 database.py 延迟导入），
        # 漏登记 = 打包后 ModuleNotFoundError 而本地 pytest 全绿。
        "a1_workbench_dict",
        # R8 交付 1：本分支新增两片，均住 delector/data/，与其它数据模块同口径
        # （前缀 delector.data.）逐条钉进打包面 —— 漏登记 = 打包后 ModuleNotFoundError
        # 而本地 pytest 全绿。official_vocab=官方歌德词表分片；lexicon_merge=字段级
        # 合并共享纯函数（被 delector.core.lexicon 与 core_dict 共用）。
        "official_vocab",
        "lexicon_merge",
        # Phase 2 · S1：富字段 side-car 分片 official_vocab_rich（ipa/例句），
        # 同口径逐条钉进打包面 —— 漏登记 = 打包后 ModuleNotFoundError 而本地全绿。
        "official_vocab_rich",
        "a1_fragments",
        "a1_sidecar",
        # Task 4（rektion）：a1_verb_case 被 services/writing.py 静态导入 —— 漏登记 = 打包后 ModuleNotFoundError。
        "a1_verb_case",
    }
    # Phase 1 Task 4：8 个 routes_*.py 收进 delector.routes/ 子包，`routes_` 前缀由
    # 包路径取代（delector.routes_a1 → delector.routes.a1）。漏改打包清单 =
    # 打包后 ModuleNotFoundError，而本地 pytest 全绿，只能靠这条断言挡住。
    route_modules = {
        "a1",
        "a2",
        "a1_hoeren",
        "a1_lesen",
        "corpus",
        "sync",
        "rtc",
        "exam",
        "listen",
        "syntax_hard",
        "main",
        "tools",
    }
    # Phase 1 Task 5：4 个服务模块收进 delector.services/ 子包（edge_tts_mini →
    # services.tts，monkeypatch 契约同步迁到 delector.services.tts，不再有顶层 shim）
    # Task 3：listen 服务（听写诊断/填空引擎）与路由同步进打包面。
    # Task 3（长难句）：syntax_score 服务（句子难度评分）与 syntax_hard 路由同步进打包面。
    # Task 3（LLM 收口）：llm_client 服务（唯一出网口）与路由同步进打包面 —— 本批次新增，
    # 集合是硬编码的，不登记 ⇒ 这条守卫对新模块永久失明（本地全绿、打包后 ModuleNotFoundError）。
    # Task 4（循环内核）：polish_loop 服务（验证驱动 agent 循环内核）与路由同步进打包面 —— 本批次新增，
    # 集合是硬编码的，不登记 ⇒ 这条守卫对新模块永久失明（本地全绿、打包后 ModuleNotFoundError）。
    # Task 5（工具白名单）：polish_tools 服务（任务级白名单 + 前置钩子，同进程直调）同步进打包面 ——
    # 同上：集合硬编码，不登记 ⇒ 守卫对它永久失明。
    service_modules = {
        "writing",
        "essay_diff",
        "exam_catalog",
        "tts",
        "listen",
        "syntax_score",
        "llm_client",
        "polish_loop",
        "polish_tools",
    }
    top_level_modules: set[str] = set()
    required_modules = sorted(data_dict_modules | route_modules | service_modules | top_level_modules)

    def _mod_prefix(mod: str) -> str:
        if mod in data_dict_modules:
            return "delector.data."
        if mod in route_modules:
            return "delector.routes."
        if mod in service_modules:
            return "delector.services."
        return "delector."

    for mod in required_modules:
        hidden = f"--hidden-import={_mod_prefix(mod)}{mod}"
        # 1. Windows PyInstaller
        assert hidden in pkg, f"{mod} 未在 package_windows.py 的 --hidden-import 中注册"
        # 2. Linux & macOS CI PyInstaller
        assert wf.count(hidden) >= 2, (
            f"{mod} 未在 build-release.yml Linux/macOS 的 --hidden-import 中完整注册 (count={wf.count(hidden)})"
        )
    # 3. Android Chaquopy：Phase 2 后整目录拷入。再逐个 cp 扁平 .py 会漏模块 ——
    #    v5.3.0 实际漏过 routes_a2.py（server.py:233 静态 import 它），整目录拷贝修掉它。
    assert "cp -r start.py" in wf, "Android 应单独拷贝入口 start.py"
    assert "cp -r delector" in wf, "Android 应整目录拷入 delector/（覆盖全部 26 个业务模块）"

    critical_apk_needles = [
        "delector/server.py",
        "de_core_news_sm",
        "delector/routes/corpus.py",
        "delector/routes/a1_hoeren.py",
        "delector/routes/a1_lesen.py",
        "delector/routes/rtc.py",
        "delector/routes/exam.py",
        "delector/routes/listen.py",
        "delector/routes/syntax_hard.py",
        "delector/services/listen.py",
        "delector/services/syntax_score.py",
        "delector/services/exam_catalog.py",
        # Task 4（循环内核）：polish_loop 服务进 APP_NEEDLES 验包探针 —— 与
        # services/listen|syntax_score|exam_catalog 同口径（Android 由 `cp -r delector`
        # 整目录拷入覆盖，这里钉住「产物里真有」这一环）。
        "delector/services/polish_loop.py",
        # Task 5（工具白名单）：polish_tools 服务同口径进 APP_NEEDLES 验包探针。
        "delector/services/polish_tools.py",
        "delector/routes/a2.py",
    ]
    for needle in critical_apk_needles:
        assert f'"{needle}"' in wf, f"{needle} 未在 build-release.yml 的 APP_NEEDLES 验包探针中"

    spec_path = os.path.join(root, "DeLector.spec")
    if os.path.exists(spec_path):
        spec = open(spec_path, encoding="utf-8").read()
        for mod in required_modules:
            assert f"'{_mod_prefix(mod)}{mod}'" in spec, f"{mod} 未在 DeLector.spec 的 hiddenimports 中注册"


def test_preset_processed_data_registered_in_all_packaging_targets():
    """子计划 2A：预置文章预生成数据文件必须在**三个**打包位点显式纳入，且产物验收闸有断言。

    为什么不能只靠 `--hidden-import`：那只收 `.py` —— `delector/data/preset_processed.json`
    是数据文件，MUST 用 `--add-data` 显式纳入；否则产物里没有它，运行时会**静默降级**成纯
    Python 口径（「列表 A2 → 点进去 A1」跳变复发），而本地 pytest 全绿（同 v4.8.1 / v5.2.0
    的漏模块事故同款失效面）。

    Android 端（DEV-RULES §2.4 第③端）由 `build-release.yml` 的 `cp -r delector` 整目录拷贝覆盖
    ——`preset_processed.json` 就在 `delector/` 目录下，随整目录进 APK，故**无需**单独声明。
    """
    root = ROOT
    needle = "delector/data/preset_processed.json"

    # 断言的是「PyInstaller 命令里真有一行 --add-data 引用了这个数据文件」，而非只是常量定义在场
    # —— 否则删掉 add-data 那行、只留常量，纯子串断言仍会绿（本守卫会被绕过）。
    pkg = open(os.path.join(root, "package_windows.py"), encoding="utf-8").read()
    assert any("--add-data" in line and "PRESET_PROCESSED_DATA_REL" in line for line in pkg.splitlines()), (
        "package_windows.py 未在 PyInstaller 命令里用 --add-data 纳入预生成数据文件（Windows 位点）："
        "漏收 ⇒ 产物静默降级为纯 Python 口径，本地全绿"
    )
    assert needle in pkg, "package_windows.py 缺少预生成数据文件的相对路径常量 PRESET_PROCESSED_DATA_REL"

    wf = open(os.path.join(root, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert wf.count(needle) == 2, (
        f"build-release.yml 应在 Linux / macOS 两个 PyInstaller 位点各纳入一次 (count={wf.count(needle)})"
    )
    # Android 覆盖：整目录拷贝（与四端打包同步守卫同款依据）。
    assert "cp -r delector" in wf, "Android 端需整目录拷入 delector/ 才能带上该数据文件"

    verify = open(os.path.join(root, "tools", "verify_windows_portable.py"), encoding="utf-8").read()
    assert needle in verify, "verify_windows_portable.py 缺少对预生成数据文件的**真产物**断言"
    assert "missing_data_files" in verify, (
        "verify_windows_portable.py 必须真扫产物、缺数据文件即 FAIL（这是「只在真产物上才能发现」的闸）"
    )


def _workflow_job_segment(workflow: str, job: str) -> str:
    """截取 workflow 中某个 job 的文本段（从 `  <job>:` 头到下一个 `  <name>:` 头）。

    为什么按 job 头切片而非只 `wf.count(...)`：只数出现次数不钉"落在哪个 job" —— 把安装整体
    挪到 Linux job 里，count 仍是 1、断言照样绿。切片后即可断言"Windows 段含、Linux/macOS 段不含"。
    job 头缩进恰好 2 空格（其 body 至少 4 空格），故 `^  name:` 只会命中 job 边界。
    """
    header = re.compile(rf"^  {re.escape(job)}:\s*$", re.M).search(workflow)
    assert header is not None, f"build-release.yml 缺 job {job!r}"
    boundary = re.compile(r"^  [A-Za-z0-9_-]+:\s*$", re.M).search(workflow, header.end())
    return workflow[header.start() : boundary.start() if boundary else len(workflow)]


def test_windows_portable_entry_is_desktop_shell_and_isolates_desktop_deps():
    """Windows 便携包入口改为桌面壳 `desktop.py`，且桌面依赖只在 Windows 位点安装。

    为什么入口要换成 desktop.py：Task 4 的 pywebview 桌面壳（窗口 + 托盘）才是"双击 exe"
    该有的形态；旧的 `start.py` 只起服务 + 开浏览器，不是桌面应用。

    为什么桌面依赖**不并** requirements.txt：`import webview` 在缺 GTK/WebKit 的 Linux 上
    直接抛异常 —— 一旦进公共依赖面，CI 在 Linux 装依赖 / 收集测试就会炸，而这与桌面壳
    的正确性无关。故桌面依赖独占 `requirements-desktop.txt`，且**只允许** Windows 位点安装。

    为什么不但数次数（见 `_workflow_job_segment`）：`wf.count(...) == 1` 不钉"落在哪个 job"，
    把安装整体挪到 Linux job 仍绿。故额外钉 job 边界：build-windows 段必须含、build-linux /
    build-macos 段必须不含。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()
    wf = open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()

    assert "desktop.py" in pkg, "Windows 便携包入口必须是桌面壳 desktop.py"
    assert '"start.py"' not in pkg, "入口已改为 desktop.py，不得残留旧的 start.py 入口"

    # count==1 钉"只装一次"；job 边界钉"装对了 job"（二者缺一都能被绕过）。
    assert wf.count("requirements-desktop.txt") == 1, (
        "requirements-desktop.txt 只允许在 Windows 位点安装一次"
        "（Linux/macOS 装了会因缺 GTK/WebKit 崩，且与桌面壳正确性无关）"
    )
    assert "pip install -r requirements-desktop.txt" in _workflow_job_segment(wf, "build-windows"), (
        "build-windows 位点缺桌面依赖安装步骤"
    )
    for job in ("build-linux", "build-macos"):
        assert "requirements-desktop.txt" not in _workflow_job_segment(wf, job), (
            f"{job} 不得安装桌面依赖：Linux/macOS 缺 GTK/WebKit，装了必崩且与桌面壳无关"
        )

    # 依赖隔离反向钉：requirements.txt 必须零桌面依赖（防被顺手合并）。
    # pillow 同为桌面独占（pystray 生成托盘图标用），一并纳入黑名单。
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    for dep in ("pywebview", "pystray", "pythonnet", "pillow"):
        assert dep not in req, f"{dep} 不得进 requirements.txt：会污染 Linux/Android 依赖面"


def test_windows_portable_declares_webview2_freeze_items():
    """打包冻结项：按 pywebview 官方 PyInstaller 建议收集 webview 包 + Windows 平台后端。

    漏收 ⇒ `webview.platforms.winforms` / `edgechromium` 在冻结后 import 失败，exe 起得来
    却拉不起窗口（白屏 / 直接崩），而本地 pytest 全绿。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    for needle in (
        "--collect-all=webview",
        "--hidden-import=webview.platforms.edgechromium",
        "--hidden-import=webview.platforms.winforms",
        "--hidden-import=pystray._win32",
    ):
        assert needle in pkg, f"{needle} 未在 package_windows.py 的冻结项中"


def test_windows_portable_builds_windowed_with_brand_icon():
    """Windows 便携包必须 `--windowed` + `--icon=assets/DeLector.ico`，且**不得**再 `--console`。

    黑框根因：服务是同进程非 daemon 线程（没有子进程），`--console` 让每次双击都多弹一个
    控制台窗口 —— 用户以为"多开了 PowerShell"。stdout/stderr 已由 ensure_streams 收口到
    launch.log（提交 3217161），控制台不再承担"看服务日志与 IP"的职责；无控制台下的失败
    改走原生弹窗 / 托盘提示，故 `--console` 必须退役为 `--windowed`。`--icon` 缺省时 exe
    用 PyInstaller 默认图标，与 DeLector 品牌不一致，故显式挂 assets/DeLector.ico。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "--windowed" in pkg, "Windows 打包必须 --windowed：双击 DeLector.exe 不应再弹出控制台黑框"
    assert "--console" not in pkg, (
        "不得再出现 --console：stdout/stderr 已由 ensure_streams 收口到 launch.log，"
        "留着 --console 等于每次双击多弹一个黑框（服务是同进程线程，没有子进程需要它）"
    )

    icon_lines = [ln for ln in pkg.splitlines() if "--icon=" in ln]
    assert icon_lines, "打包命令缺 --icon=：exe 会用 PyInstaller 默认图标而非 assets/DeLector.ico"
    for ln in icon_lines:
        assert "DeLector.ico" in ln and "assets" in ln, (
            f"--icon= 必须指向 assets/DeLector.ico，实际：{ln.strip()}"
        )
        assert "root_dir" in ln, (
            f"图标路径必须与 --add-data 同口径经 root_dir 构造（打包机目录不定），实际：{ln.strip()}"
        )


def test_windows_portable_declares_webview2_payload_verification():
    """Windows 便携包必须**构建后自检** WebView2 运行时 DLL，且缺了就**硬失败**。

    为什么这是"最能防事故"的一条：pywebview 走系统 Edge WebView2，一旦打包漏收
    WebView2Loader.dll / Microsoft.Web.WebView2*.dll，exe 能起、窗口却**白屏**（无报错弹窗）
    —— 与 v4.8.1（routes_corpus 漏） / v5.2.0（routes_rtc/exam 漏）同款的"本地全绿、
    打包后静默失败"。故断言：① 自检函数存在；② 所需 DLL 清单完整登记（删一项即白屏）；
    ③ 缺失走**非零退出**（不是打印警告）；④ 文案点名"白屏"，让后人看懂为何不能删。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "verify_webview2_payload" in pkg, "缺构建后自检函数：漏收 WebView2 DLL 会白屏而无人发现"
    assert "assert_webview2_payload" in pkg, "缺「缺失即失败」的执行入口（自检与失败处置分离更好测）"

    for needle in ("WebView2Loader.dll", "Microsoft.Web.WebView2"):
        assert needle in pkg, f"WebView2 DLL 清单缺 {needle!r}：漏了它 exe 就白屏"

    assert "白屏" in pkg, "失败文案必须点明后果（白屏），否则后人会把自检当噪音删掉"


def test_verify_webview2_payload_reports_missing_dlls_recursively(tmp_path):
    """行为级：递归 + 大小写不敏感地查 WebView2 DLL；缺谁就精确点名谁。

    产物里 DLL 落在 `_internal/webview/lib/` 之类的**子目录**，只扫顶层会漏判 ⇒ 白屏放行。
    """
    import package_windows

    nested = tmp_path / "_internal" / "webview" / "lib"
    nested.mkdir(parents=True)
    (nested / "webview2loader.dll").write_bytes(b"")  # 小写：大小写不敏感
    (nested / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"")
    assert package_windows.verify_webview2_payload(str(tmp_path)) == [], "齐全时不得误报缺失"

    (nested / "Microsoft.Web.WebView2.Core.dll").unlink()
    missing = package_windows.verify_webview2_payload(str(tmp_path))
    assert missing == ["Microsoft.Web.WebView2"], f"缺失清单必须精确点名，实际 {missing}"


def test_assert_webview2_payload_hard_fails_when_dll_missing(tmp_path):
    """缺 DLL ⇒ **非零退出**（`SystemExit`），绝不能只打印警告就放行。

    这是本任务的核心守卫：自检**必须真的会让构建失败**，否则白屏包照样发布。
    """
    import package_windows

    with pytest.raises(SystemExit) as excinfo:
        package_windows.assert_webview2_payload(str(tmp_path))

    assert excinfo.value.code != 0, "缺 WebView2 DLL 时必须非零退出（构建失败）"


def test_assert_webview2_payload_passes_when_dlls_present(tmp_path):
    """齐全 ⇒ 不抛、正常返回（否则每次正常构建都会被自己的自检拒掉）。"""
    import package_windows

    (tmp_path / "WebView2Loader.dll").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"")

    package_windows.assert_webview2_payload(str(tmp_path))  # 不抛即通过


def test_verify_webview2_payload_requires_a_dll_suffix(tmp_path):
    """同名 `.xml`/`.pdb` 不得冒充 DLL：只收集到 `Microsoft.Web.WebView2.Core.xml` 时仍判缺失。

    为什么必须锚定 `.dll`：产物常伴同名 `.xml`/`.pdb`，只做子串匹配会被同伴文件名命中 ⇒ 真漏收
    DLL 却**假绿**，白屏包照样发布。
    """
    import package_windows

    (tmp_path / "WebView2Loader.dll").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.xml").write_bytes(b"")
    (tmp_path / "Microsoft.Web.WebView2.Core.pdb").write_bytes(b"")

    missing = package_windows.verify_webview2_payload(str(tmp_path))

    assert missing == ["Microsoft.Web.WebView2"], f"只有同名 .xml/.pdb 时仍须判缺失，实际 {missing}"


def test_build_windows_actually_invokes_webview2_payload_check():
    """`assert_webview2_payload(...)` 的调用点 MUST 落在 `build_windows()` 函数体内。

    为什么用 AST 钉调用点而非只查函数名出现在源码里：现有守卫只断言"函数名 / DLL 名 / '白屏'
    字样在源码中"，把 `build_windows()` 里那行调用删掉，闸就**失效**而全套测试仍绿。AST 把
    "定义存在"提升为"真的在构建路径上被调用"，删调用即红（本轮已做变异自证）。
    """
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "assert_webview2_payload"), (
        "build_windows() 内必须真调用 assert_webview2_payload()：否则验包闸形同虚设（删调用全套仍绿）"
    )


def test_windows_portable_readme_matches_desktop_entry():
    """产物《说明_README.txt》必须与入口一致：双击=桌面窗口、手机访问=`--server-only`。

    防"入口改了、文案没跟"的文档漂移：否则用户会照着 README 找一个已不存在的"默认浏览器"启动方式。
    """
    import package_windows

    readme = package_windows.release_readme("v9.9.9")

    assert "桌面窗口" in readme, "README 必须点明双击 DeLector.exe 打开的是桌面窗口"
    assert "--server-only" in readme, "README 必须告诉用户手机/平板访问要走 --server-only"
    assert "默认浏览器" not in readme, "入口已改为桌面窗口，README 不得再写'默认浏览器'"


def test_readme_generation_is_wired_into_build_windows():
    """`build_windows()` 必须把 `release_readme(...)` 的文本写进产物 README（防守卫与被写文本脱钩）。"""
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "release_readme"), (
        "build_windows() 必须调用 release_readme() 生成产物文案，否则守卫测的不是真正的产物内容"
    )
