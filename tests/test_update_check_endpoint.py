# -*- coding: utf-8 -*-
"""`GET /api/update/check` 端点契约（Task 3）。

红线 11：跨边界契约要**行为验证** —— 收尾用 TestClient 真调端点，而非只测内部函数。
本文件**绝不真联网**：所有出网都走注入的 fake fetcher（CI 不可靠且会打 GitHub 限速）。

核心不变式（失败绝不伪装成"已是最新"）：
- ``has_update is None`` 当且仅当 ``error_reason is not None``（双向）；
- 检查失败**绝不**返回 ``has_update: false``；
- ``current`` 来自 ``APP_VERSION``；``has_update`` 判定用 versionCode 语义。
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from delector import server
from delector.core import database
from delector.core.version import APP_VERSION
from delector.routes import update

# 契约的 7 个键，逐字固定（前端与探针依赖）。
CONTRACT_KEYS = {
    "current",
    "latest",
    "has_update",
    "page_url",
    "checked_at",
    "cached",
    "error_reason",
}

RELEASES_TAG = "https://github.com/ROM4n2/DeLector/releases/tag/"

# TTL 边界（与模块内常量同口径）：成功 6h、失败 60s。
_SUCCESS_TTL = 6 * 3600
_FAIL_TTL = 60


def _bump(version: str) -> str:
    """把 patch 段 +1，得到一个 versionCode 严格更大的"有新版"目标。

    从 APP_VERSION 派生而非写死字面量：版本 bump 后这条测试依然表达"新版"语义，
    不会因为真相源前进而变成"同版"从而失去覆盖。
    """
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


class FakeFetcher:
    """记录调用次数，并按需返回固定 release 或抛出固定异常的假 fetcher。

    出网注入点，保证测试**零真实网络**。``calls`` 是"零出网"断言的计数钉。
    """

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
    """每个用例前后清空模块级 TTL 缓存，避免用例间串味。"""
    update._cache.clear()
    yield
    update._cache.clear()


@pytest.fixture
def client(tmp_path: Path) -> Any:
    """真 app + TestClient：env 切到 tmp_path throwaway 库，避免污染真实库。"""
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
# 1. 版本判定：有新版 / 同版
# ==========================================================================
def test_has_update_true_when_newer_release() -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert set(result) == CONTRACT_KEYS
    assert result["current"] == APP_VERSION
    assert result["latest"] == newer  # 输出不带 v 前缀
    assert result["has_update"] is True
    assert result["page_url"] == RELEASES_TAG + "v" + newer
    assert result["error_reason"] is None
    assert result["cached"] is False
    assert result["checked_at"] == 1_000


def test_has_update_false_when_same_version() -> None:
    fetcher = FakeFetcher(release={"tag_name": "v" + APP_VERSION, "html_url": RELEASES_TAG + "v" + APP_VERSION})

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is False
    assert result["error_reason"] is None
    assert result["latest"] == APP_VERSION


# ==========================================================================
# 2. 错误分类四类：timeout / rate_limited / not_found / network
# ==========================================================================
def test_timeout_yields_none_and_never_false() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("boom"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["has_update"] is not False  # 失败绝不伪装成"已是最新"
    assert result["error_reason"] == "timeout"
    assert result["latest"] is None
    assert result["page_url"] is None


def test_rate_limited_reason() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckRateLimited("403"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "rate_limited"


@pytest.mark.parametrize(
    "release,error",
    [
        (None, update.UpdateCheckNotFound("404")),        # 404
        ({"tag_name": "not-a-version"}, None),            # 坏 tag（不可解析）
        ({"html_url": RELEASES_TAG}, None),               # tag_name 缺失
    ],
)
def test_not_found_reason(release: Optional[Dict[str, Any]], error: Optional[Exception]) -> None:
    fetcher = FakeFetcher(release=release, error=error)

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "not_found"


def test_network_reason_on_unexpected_error() -> None:
    fetcher = FakeFetcher(error=httpx.ConnectError("connection refused"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "network"


# ==========================================================================
# 3. 缓存：命中零出网 + 失败短 TTL / 成功长 TTL
# ==========================================================================
def test_cache_hit_serves_without_refetch() -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": ""})

    first = update.check_for_update(fetcher=fetcher, now=5_000.0)
    second = update.check_for_update(fetcher=fetcher, now=5_000.0)

    assert first["cached"] is False
    assert second["cached"] is True
    assert fetcher.calls == 1  # 命中缓存 ⇒ 零出网
    assert second["latest"] == first["latest"]


def test_failed_check_cached_short_then_retries() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("t"))

    update.check_for_update(fetcher=fetcher, now=0.0)
    update.check_for_update(fetcher=fetcher, now=_FAIL_TTL - 30)  # 30s 内仍命中缓存
    assert fetcher.calls == 1

    update.check_for_update(fetcher=fetcher, now=_FAIL_TTL + 1)  # 61s 后重试
    assert fetcher.calls == 2


def test_success_cached_six_hours_then_retries() -> None:
    fetcher = FakeFetcher(release={"tag_name": "v" + APP_VERSION, "html_url": ""})

    update.check_for_update(fetcher=fetcher, now=0.0)
    update.check_for_update(fetcher=fetcher, now=_SUCCESS_TTL - 1)  # 6h 内不重试
    assert fetcher.calls == 1

    update.check_for_update(fetcher=fetcher, now=_SUCCESS_TTL + 1)  # 6h+1s 后重试
    assert fetcher.calls == 2


# ==========================================================================
# 4. 跨边界行为验证：TestClient 真调端点
# ==========================================================================
def test_endpoint_returns_exact_contract_keys(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    resp = client.get("/api/update/check")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == CONTRACT_KEYS  # 恰好 7 个键
    assert body["current"] == APP_VERSION
    assert body["has_update"] is True
    assert isinstance(body["checked_at"], int)
    assert fetcher.calls == 1


def test_endpoint_failure_path_serializes_null_has_update(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败路径也必须过 HTTP 层：验证 JSON `null` 在端点反序列化回 Python None。

    锁死"失败绝不伪装成已是最新"到跨边界层面 —— `has_update` 必须是 `None`，
    既不是字符串 ``"null"`` 也不是 ``False``。
    """
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("boom"))
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    resp = client.get("/api/update/check")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == CONTRACT_KEYS  # 恰好 7 个键
    assert body["has_update"] is None  # 必须是 None，不是 "null"，也不是 False
    assert body["error_reason"] == "timeout"
    assert fetcher.calls == 1


def test_endpoint_cache_hit_keeps_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命中路径也必须过 HTTP 层：第二次请求经端点返回完整快照且零再出网。

    端点内部用 ``time.time()``；此处 monkeypatch 该时钟（不改生产签名），
    推进时间但不越过 TTL，验证 ``cached: True`` 与快照一致性。
    """
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    clock = {"now": 1_000.0}
    monkeypatch.setattr(update.time, "time", lambda: clock["now"])

    first = client.get("/api/update/check").json()
    clock["now"] = 1_000.0 + _SUCCESS_TTL - 1  # 推进但仍在 TTL 内
    second = client.get("/api/update/check").json()

    assert set(second) == CONTRACT_KEYS  # 命中快照契约仍完整
    assert first["cached"] is False
    assert second["cached"] is True
    assert fetcher.calls == 1  # 命中 ⇒ 零再出网
    assert second["latest"] == first["latest"]


# ==========================================================================
# 5. 源码纪律：无版本号字面量 / 统一 httpx / import 期不联网
# ==========================================================================
def test_source_has_no_version_literal_and_unifies_on_httpx() -> None:
    src = Path(update.__file__).read_text(encoding="utf-8")

    assert not re.search(r"\d+\.\d+\.\d+", src), "update.py 不得出现版本号字面量（不变式 3）"
    banned = re.search(r"^\s*(?:import|from)\s+(requests|aiohttp|urllib\.request)\b", src, re.M)
    assert banned is None, f"出网必须统一 httpx，禁用 {banned.group(1) if banned else ''}"


def test_import_does_not_trigger_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """红线 9：import 期不得联网 —— 顶层若调 _fetch_latest_release 会在此处炸。"""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("import 期不得联网")

    monkeypatch.setattr(httpx, "get", _boom)
    import importlib

    importlib.reload(update)  # 触发模块顶层重新执行；若联网即失败
    assert hasattr(update, "check_for_update")
