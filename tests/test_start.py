"""Task1 Step3: 平台绑定行为测试 — Android vs Desktop get_bind_host()"""

import start


def test_get_bind_host_on_android(monkeypatch):
    monkeypatch.setattr(start, "is_android", lambda: True)
    assert start.get_bind_host() == "127.0.0.1"


def test_get_bind_host_on_desktop(monkeypatch):
    monkeypatch.setattr(start, "is_android", lambda: False)
    assert start.get_bind_host() == "0.0.0.0"


def test_get_bind_host_android_loopback_only(monkeypatch):
    """Android 上必须只监听回环：POST /api/settings 无鉴权，绑 0.0.0.0 会暴露给整个局域网。"""
    monkeypatch.setattr(start, "is_android", lambda: True)
    host = start.get_bind_host()
    assert host == "127.0.0.1"
    assert host != "0.0.0.0"


def test_get_bind_host_desktop_allows_lan(monkeypatch):
    """桌面端有意绑 0.0.0.0 以允许同 Wi-Fi 设备访问文章。"""
    monkeypatch.setattr(start, "is_android", lambda: False)
    host = start.get_bind_host()
    assert host == "0.0.0.0"
