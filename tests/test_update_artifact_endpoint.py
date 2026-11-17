# -*- coding: utf-8 -*-
"""`GET /api/update/artifact` 端点契约（ADR-0034 / 里程碑 M1）。

与 `test_update_check_endpoint.py` 的分工：
- 那边冻结 `/check` 的 **7 键**契约，本文件**不改它**；
- 本文件钉 `/artifact` 的 **12 键**契约、资产选择、校验和资产存在性与失败语义。

本文件**绝不真联网**：所有出网都走注入的 fake fetcher。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from delector import server
from delector.core import database
from delector.core.version import APP_VERSION
from delector.routes import update

# `/artifact` 的 12 个键，逐字固定（前端与后续下载会话依赖）。
ARTIFACT_KEYS = {
    "platform",
    "channel",
    "arch",
    "version",
    "asset_name",
    "asset_url",
    "asset_size",
    "checksum_url",
    "page_url",
    "checked_at",
    "cached",
    "error_reason",
}

# `/check` 的 7 个键：本文件只做「加 assets 后仍不泄漏」的旁证，不改原测试。
CHECK_KEYS = {
    "current",
    "latest",
    "has_update",
    "page_url",
    "checked_at",
    "cached",
    "error_reason",
}

_SUCCESS_TTL = 6 * 3600
_FAIL_TTL = 60

TAG = "v9.9.9"
LATEST = "9.9.9"
RELEASES_TAG = "https://github.com/ROM4n2/DeLector/releases/tag/"


def _asset(name: str, size: int = 1024, scheme: str = "https") -> Dict[str, Any]:
    return {"name": name, "url": f"{scheme}://example.test/{name}", "size": size}


def _release(
    tag: str = TAG,
    assets: Optional[List[Dict[str, Any]]] = None,
    html_url: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "tag_name": tag,
        "html_url": RELEASES_TAG + tag if html_url is None else html_url,
        "assets": [] if assets is None else assets,
    }


def _standard_assets(tag: str = TAG) -> List[Dict[str, Any]]:
    names = [
        f"DeLector-{tag}-Windows-x64-Portable.zip",
        f"DeLector-{tag}-Windows-x64-Setup.exe",
        f"DeLector-{tag}-Linux-x64.tar.gz",
        f"DeLector-{tag}-macOS.tar.gz",
        f"DeLector-{tag}-Android.apk",
    ]
    assets: List[Dict[str, Any]] = []
    for index, name in enumerate(names):
        assets.append(_asset(name, size=1000 + index))
        assets.append(_asset(name + ".sha256", size=80))
    return assets


class FakeFetcher:
    """记录调用次数，并按需返回固定 release 或抛出固定异常。"""

    def __init__(
        self,
        release: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.calls = 0
        self._release = release
        self._error = error

    def __call__(self, timeout: float) -> Dict[str, Any]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self._release or {})


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    update._cache.clear()
    yield
    update._cache.clear()


@pytest.fixture
def client(tmp_path: Path) -> Any:
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = str(tmp_path / "update.db")
    os.environ["PROGRESS_DB_PATH"] = str(tmp_path / "update_progress.db")
    database.init_db(os.environ["DATABASE_PATH"])
    yield TestClient(server.create_app(), client=("127.0.0.1", 54321))
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ==========================================================================
# 1. 资产选择：五个平台/形态组合逐字命中
# ==========================================================================
@pytest.mark.parametrize(
    "platform,channel,arch,expected",
    [
        ("windows", "installer", "x64", f"DeLector-{TAG}-Windows-x64-Setup.exe"),
        ("windows", "portable", "x64", f"DeLector-{TAG}-Windows-x64-Portable.zip"),
        ("linux", "portable", "x64", f"DeLector-{TAG}-Linux-x64.tar.gz"),
        ("macos", "portable", "x64", f"DeLector-{TAG}-macOS.tar.gz"),
        ("android", "portable", "arm64", f"DeLector-{TAG}-Android.apk"),
    ],
)
def test_selects_expected_asset(platform: str, channel: str, arch: str, expected: str) -> None:
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    body = update.check_artifact(platform=platform, channel=channel, arch=arch, fetcher=fetcher, now=1_000.0)

    assert set(body) == ARTIFACT_KEYS
    assert body["asset_name"] == expected
    assert body["checksum_url"] == f"https://example.test/{expected}.sha256"
    assert body["version"] == LATEST
    assert body["checked_at"] == 1_000
    assert body["error_reason"] is None
    assert body["cached"] is False


def test_android_request_is_normalized_to_arm64() -> None:
    """Android 只出 arm64：请求里写 x64 也必须收敛，不能拼出不存在的资产名。"""
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    body = update.check_artifact(platform="android", channel="portable", arch="x64", fetcher=fetcher, now=1_000.0)

    assert body["arch"] == "arm64"
    assert body["asset_name"] == f"DeLector-{TAG}-Android.apk"


def test_linux_ignores_windows_channel() -> None:
    """Linux/macOS 没有形态概念：传 installer 也必须按便携包解析，而不是报错。"""
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    body = update.check_artifact(platform="linux", channel="installer", arch="x64", fetcher=fetcher, now=1_000.0)

    assert body["channel"] == "portable"
    assert body["asset_name"] == f"DeLector-{TAG}-Linux-x64.tar.gz"


def test_page_url_falls_back_when_html_url_missing() -> None:
    fetcher = FakeFetcher(release={"tag_name": TAG, "html_url": "", "assets": _standard_assets()})

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert body["page_url"] == RELEASES_TAG + TAG


# ==========================================================================
# 2. 失败语义：缺资产 / 缺校验和 / 上游四类 / 非 https
# ==========================================================================
def test_missing_asset_reports_asset_missing_without_download_fields() -> None:
    fetcher = FakeFetcher(release=_release(assets=[]))

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert set(body) == ARTIFACT_KEYS
    assert body["error_reason"] == "asset_missing"
    for key in ("version", "asset_name", "asset_url", "asset_size", "checksum_url", "page_url"):
        assert body[key] is None


def test_missing_checksum_asset_is_refused_not_silently_downgraded() -> None:
    name = f"DeLector-{TAG}-Windows-x64-Setup.exe"
    fetcher = FakeFetcher(release=_release(assets=[_asset(name)]))

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert body["error_reason"] == "checksum_missing"
    assert body["asset_url"] is None
    assert body["checksum_url"] is None


def test_missing_assets_field_is_asset_missing() -> None:
    fetcher = FakeFetcher(release={"tag_name": TAG, "html_url": ""})

    body = update.check_artifact(platform="android", fetcher=fetcher, now=1_000.0)

    assert body["error_reason"] == "asset_missing"


@pytest.mark.parametrize(
    "error,reason",
    [
        (update.UpdateCheckTimeout("t"), "timeout"),
        (update.UpdateCheckRateLimited("403"), "rate_limited"),
        (update.UpdateCheckNotFound("404"), "not_found"),
        (httpx.ConnectError("boom"), "network"),
    ],
)
def test_upstream_failures_map_to_reasons(error: Exception, reason: str) -> None:
    fetcher = FakeFetcher(error=error)

    body = update.check_artifact(platform="windows", channel="portable", fetcher=fetcher, now=1_000.0)

    assert body["error_reason"] == reason
    assert body["asset_url"] is None


def test_unparseable_tag_is_not_found() -> None:
    fetcher = FakeFetcher(release=_release(tag="vNext", assets=_standard_assets(tag="vNext")))

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert body["error_reason"] == "not_found"


def test_non_https_asset_url_is_rejected() -> None:
    name = f"DeLector-{TAG}-Windows-x64-Setup.exe"
    fetcher = FakeFetcher(
        release=_release(assets=[_asset(name, scheme="http"), _asset(name + ".sha256")])
    )

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert body["error_reason"] == "not_found"
    assert body["asset_url"] is None


# ==========================================================================
# 3. 缓存：成功 6h / 失败 60s，命中零出网，按平台分桶
# ==========================================================================
def test_cache_hit_serves_without_refetch() -> None:
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    first = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=5_000.0)
    second = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=5_000.0)

    assert first["cached"] is False
    assert second["cached"] is True
    assert fetcher.calls == 1
    assert second["asset_name"] == first["asset_name"]


def test_different_platforms_do_not_share_cache() -> None:
    """分桶回归：Windows 的解析结果不得被 Linux 请求直接吃掉。"""
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    win = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=5_000.0)
    lin = update.check_artifact(platform="linux", fetcher=fetcher, now=5_000.0)

    assert win["asset_name"].endswith("Setup.exe")
    assert lin["asset_name"].endswith("Linux-x64.tar.gz")
    assert fetcher.calls == 2


def test_failed_artifact_cached_short_then_retries() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("t"))

    update.check_artifact(platform="windows", fetcher=fetcher, now=0.0)
    update.check_artifact(platform="windows", fetcher=fetcher, now=_FAIL_TTL - 30)
    assert fetcher.calls == 1

    update.check_artifact(platform="windows", fetcher=fetcher, now=_FAIL_TTL + 1)
    assert fetcher.calls == 2


def test_success_cached_six_hours_then_retries() -> None:
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))

    update.check_artifact(platform="windows", fetcher=fetcher, now=0.0)
    update.check_artifact(platform="windows", fetcher=fetcher, now=_SUCCESS_TTL - 1)
    assert fetcher.calls == 1

    update.check_artifact(platform="windows", fetcher=fetcher, now=_SUCCESS_TTL + 1)
    assert fetcher.calls == 2


def test_cached_failure_is_still_a_failure() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("t"))

    update.check_artifact(platform="windows", fetcher=fetcher, now=0.0)
    second = update.check_artifact(platform="windows", fetcher=fetcher, now=_FAIL_TTL - 30)

    assert second["cached"] is True
    assert second["error_reason"] == "timeout"
    assert second["asset_url"] is None


# ==========================================================================
# 4. 不变式：error_reason is None ⇔ asset_url is not None
# ==========================================================================
_INVARIANT_PARAMS: list[Any] = [
    pytest.param(_release(assets=_standard_assets()), None, id="ok"),
    pytest.param(_release(assets=[]), None, id="fail-asset-missing"),
    pytest.param(None, update.UpdateCheckTimeout("t"), id="fail-timeout"),
    pytest.param(None, httpx.ConnectError("boom"), id="fail-network"),
]


@pytest.mark.parametrize("release,error", _INVARIANT_PARAMS)
def test_artifact_invariant_bidirectional(
    release: Optional[Dict[str, Any]], error: Optional[Exception]
) -> None:
    fetcher = FakeFetcher(release=release, error=error)

    body = update.check_artifact(platform="windows", channel="installer", fetcher=fetcher, now=1_000.0)

    assert (body["error_reason"] is None) == (body["asset_url"] is not None)


# ==========================================================================
# 5. 跨边界：TestClient 真调端点 + `/check` 契约不被 assets 污染
# ==========================================================================
def test_endpoint_returns_exact_artifact_keys(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    resp = client.get("/api/update/artifact?platform=windows&channel=installer&arch=x64")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == ARTIFACT_KEYS
    assert body["asset_name"] == f"DeLector-{TAG}-Windows-x64-Setup.exe"
    assert isinstance(body["checked_at"], int)
    assert fetcher.calls == 1


def test_endpoint_defaults_to_windows_portable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    body = client.get("/api/update/artifact").json()

    assert body["platform"] == "windows"
    assert body["channel"] == "portable"
    assert body["asset_name"].endswith("Windows-x64-Portable.zip")


def test_endpoint_rejects_unknown_platform_with_422(client: TestClient) -> None:
    resp = client.get("/api/update/artifact?platform=beos")

    assert resp.status_code == 422


def test_check_endpoint_still_returns_exactly_seven_keys(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反证：`_fetch_latest_release` 多返回 assets 后，`/check` 仍恰好 7 键。"""
    fetcher = FakeFetcher(release=_release(assets=_standard_assets()))
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    body = client.get("/api/update/check").json()

    assert set(body) == CHECK_KEYS
    assert body["current"] == APP_VERSION
