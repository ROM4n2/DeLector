# -*- coding: utf-8 -*-
"""`GET /api/update/check` —— 代查 GitHub Releases 并规约成稳定契约（Task 3）。

设计要点：
- **失败绝不伪装成"已是最新"**：出错时 `has_update` 为 `null`（不是 `false`），并附
  `error_reason`，让前端能区分"确认已是最新"与"这次没查成"。
- `has_update` 用 versionCode 语义判定（`version_code(latest) > version_code(APP_VERSION)`），
  不做字符串比较 —— 字符串比较在段数到两位（3.9 vs 3.10）时给出错误结论。
- 红线 9：import 期**不联网** —— 顶层只定义函数与常量，出网只发生在请求真正到来时。
"""

import threading
import time
from typing import Any, Callable, Dict, Literal, Optional

import httpx
from fastapi import APIRouter

from delector.core.version import APP_VERSION, version_code

__all__ = [
    "UpdateAssetMissing",
    "UpdateChecksumMissing",
    "UpdateCheckError",
    "UpdateCheckNotFound",
    "UpdateCheckRateLimited",
    "UpdateCheckTimeout",
    "_fetch_latest_release",
    "api_update_artifact",
    "api_update_check",
    "check_artifact",
    "check_for_update",
    "router",
]

router = APIRouter(prefix="/api/update", tags=["update"])

_RELEASES_API = "https://api.github.com/repos/ROM4n2/DeLector/releases/latest"

# 3 秒：桌面与移动网络都够跑完一次 releases/latest，又不会把请求挂死。
_HTTP_TIMEOUT = 3.0

# 成功缓存 6 小时；失败只缓存 60 秒 —— 失败若也长缓存，会把"网络已恢复"
# 这一事实锁死 6 小时，用户看不到期间已经能连上了。
_CACHE_TTL_SECONDS = 6 * 3600
_CACHE_FAIL_TTL_SECONDS = 60

# 缓存形如 {"payload": Dict[str, Any], "expires_at": float}。Lock 保护**缓存读写**
# （查/写两步原子）—— 它不覆盖出网：并发首个 miss 可各出网一次。该端点是低频只读、
# 上游是 GitHub 未鉴权限速 60/h，重复一次出网比"持锁出网"（会把并发请求全部串行化、
# 甚至被慢网拖住）更可接受。
_CACHE_LOCK = threading.Lock()
_cache: Dict[str, Any] = {}


# ── 错误分类（必须可被测试注入，故需能表达四类失败）──────────────────────────
class UpdateCheckError(Exception):
    """检查更新的失败基类。`reason` 供 check_for_update 规约成 `error_reason`。"""

    reason: str = "network"


class UpdateCheckTimeout(UpdateCheckError):
    """出网超时。"""

    reason = "timeout"


class UpdateCheckRateLimited(UpdateCheckError):
    """GitHub 未鉴权限速（HTTP 403/429）。"""

    reason = "rate_limited"


class UpdateCheckNotFound(UpdateCheckError):
    """仓库/Release 不存在（404），或 `tag_name` 缺失/不可解析。"""

    reason = "not_found"


class UpdateAssetMissing(UpdateCheckError):
    """Release 里没有该平台/形态对应的资产（CI 命名漂移或产物缺失）。"""

    reason = "asset_missing"


class UpdateChecksumMissing(UpdateCheckError):
    """资产存在但缺少配套的 `.sha256` —— 拒绝降级为"无校验下载"。"""

    reason = "checksum_missing"


def _release_page_url(tag: str) -> str:
    """由 tag 构造 Release 页地址（`html_url` 缺失时的兜底）。"""
    return f"https://github.com/ROM4n2/DeLector/releases/tag/{tag}"


def _fetch_latest_release(timeout: float) -> Dict[str, Any]:
    """真实出网：GET GitHub releases/latest。

    返回 `{"tag_name": str, "html_url": str, "assets": [...]}`。`/check` 只读前两项，
    `/artifact` 才用 `assets`；多取一项不改变 7 键契约。超时/限流/404 抛本模块的
    错误子类；其余 httpx 异常（连接失败、非 2xx）向上抛，由调用方归类为 network。
    """
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "DeLector-UpdateCheck"}
    try:
        resp = httpx.get(_RELEASES_API, timeout=timeout, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpdateCheckTimeout("请求 GitHub Releases 超时") from exc

    if resp.status_code in (403, 429):
        raise UpdateCheckRateLimited(f"GitHub 限速: HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise UpdateCheckNotFound("Release 不存在: HTTP 404")
    resp.raise_for_status()  # 其余非 2xx → httpx.HTTPStatusError → 归类 network

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateCheckError("GitHub 响应不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise UpdateCheckError("GitHub 响应不是 JSON 对象")

    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise UpdateCheckNotFound("GitHub release 缺少 tag_name")
    html_url = data.get("html_url")
    return {
        "tag_name": tag,
        "html_url": html_url if isinstance(html_url, str) else "",
        "assets": _normalized_assets(data),
    }


# ── 资产元数据（`GET /api/update/artifact`）─────────────────────────────────
# 与 `/check` 的 7 键契约完全分离：本端点只回答"该平台的可执行资产在哪、多大、
# 校验和在哪"，不参与"有没有新版"的判定。
#
# 缓存按 (platform, channel, arch) 分桶：全局单桶会把 Windows 的解析结果喂给
# Android 请求。桶整体挂在 `_cache` 下，既有测试的 `update._cache.clear()` 仍能清零。

_ARTIFACT_BUCKET_KEY = "artifact_bucket"

# 平台/形态 → 资产名后缀。与 `.github/workflows/build-release.yml` 的产物名逐字对应；
# CI 改名必须同步改这里，否则端点报 asset_missing（宁可报错，不猜资产）。
_ASSET_SUFFIX = {
    ("windows", "installer", "x64"): "Windows-x64-Setup.exe",
    ("windows", "portable", "x64"): "Windows-x64-Portable.zip",
    ("linux", "portable", "x64"): "Linux-x64.tar.gz",
    ("macos", "portable", "x64"): "macOS.tar.gz",
    ("android", "portable", "arm64"): "Android.apk",
}

ArtifactKey = tuple[str, str, str]


def _normalize_asset(item: Any) -> Optional[Dict[str, Any]]:
    """把 GitHub asset 条目规约成 `{name, url, size}`；不可用条目返回 None。

    兼容两种来源：真实 GitHub JSON 用 `browser_download_url`，测试 fixture 可直接给
    `url`。缺名/缺地址一律丢弃（不拿 `url`（API 资源地址）冒充下载地址）。
    """
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    url = item.get("browser_download_url")
    if not isinstance(url, str) or not url:
        url = item.get("url")
    size = item.get("size")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(url, str) or not url:
        return None
    return {"name": name, "url": url, "size": size if isinstance(size, int) and size >= 0 else 0}


def _normalized_assets(release: Dict[str, Any]) -> list[Dict[str, Any]]:
    """release 里的 assets 规约成列表；缺失/非列表一律空列表（→ asset_missing）。"""
    raw = release.get("assets")
    if not isinstance(raw, list):
        return []
    normalized = (_normalize_asset(item) for item in raw)
    return [asset for asset in normalized if asset is not None]


def _normalize_platform_args(platform: str, channel: str, arch: str) -> ArtifactKey:
    """把请求参数收敛到实际可用的组合。

    - Android 只出 arm64、无形态概念；
    - Linux / macOS 只有 x64 便携包，形态参数被忽略；
    - Windows 只有 x64；形态参数（安装版/便携版）保留。
    """
    if platform == "android":
        return ("android", "portable", "arm64")
    if platform == "windows":
        return ("windows", channel if channel in ("installer", "portable") else "portable", "x64")
    return (platform, "portable", "x64")


def _expected_asset_name(tag: str, key: ArtifactKey) -> str:
    """由 tag 与平台组合构造期望资产名；不支持的组合 → not_found。"""
    platform, channel, arch = key
    suffix = _ASSET_SUFFIX.get((platform, channel, arch))
    if suffix is None:
        raise UpdateCheckNotFound(f"不支持的平台组合: {platform}/{channel}/{arch}")
    return f"DeLector-{tag}-{suffix}"


def _build_artifact_success(release: Dict[str, Any], key: ArtifactKey, checked_at: int) -> Dict[str, Any]:
    """把 release 规约成资产契约；任何缺失/不可信都转成明确 error_reason。"""
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise UpdateCheckNotFound("release 缺少 tag_name")

    latest = tag[1:] if tag.startswith("v") else tag
    try:
        version_code(latest)  # 与 /check 同口径：解析不了就是 not_found
    except ValueError as exc:
        raise UpdateCheckNotFound(f"tag 无法解析为版本号: {tag!r}") from exc

    expected = _expected_asset_name(tag, key)
    by_name = {asset["name"]: asset for asset in _normalized_assets(release)}

    asset = by_name.get(expected)
    if asset is None:
        raise UpdateAssetMissing(f"Release 缺少资产: {expected}")
    checksum = by_name.get(expected + ".sha256")
    if checksum is None:
        raise UpdateChecksumMissing(f"Release 缺少校验和资产: {expected}.sha256")

    # 地址只接受 https：GitHub 正常返回 https，出现 http 说明数据被篡改或出错。
    for item in (asset, checksum):
        if not item["url"].startswith("https://"):
            raise UpdateCheckNotFound("资产地址不是 https")

    html_url = release.get("html_url")
    page_url = html_url if isinstance(html_url, str) and html_url else _release_page_url(tag)
    platform, channel, arch = key
    return {
        "platform": platform,
        "channel": channel,
        "arch": arch,
        "version": latest,
        "asset_name": asset["name"],
        "asset_url": asset["url"],
        "asset_size": asset["size"],
        "checksum_url": checksum["url"],
        "page_url": page_url,
        "checked_at": checked_at,
        "cached": False,
        "error_reason": None,
    }


def _build_artifact_failure(key: ArtifactKey, checked_at: int, reason: str) -> Dict[str, Any]:
    """失败契约：所有可下载字段为 None，绝不降级到别的资产。"""
    platform, channel, arch = key
    return {
        "platform": platform,
        "channel": channel,
        "arch": arch,
        "version": None,
        "asset_name": None,
        "asset_url": None,
        "asset_size": None,
        "checksum_url": None,
        "page_url": None,
        "checked_at": checked_at,
        "cached": False,
        "error_reason": reason,
    }


def _resolve_artifact(
    fetch: Callable[[float], Dict[str, Any]], key: ArtifactKey, checked_at: int
) -> "tuple[Dict[str, Any], int]":
    """出网 + 规约；返回 `(契约, 该结果应缓存多久)`。"""
    try:
        return _build_artifact_success(fetch(_HTTP_TIMEOUT), key, checked_at), _CACHE_TTL_SECONDS
    except UpdateCheckError as exc:
        return _build_artifact_failure(key, checked_at, exc.reason), _CACHE_FAIL_TTL_SECONDS
    except Exception:  # 未预期异常（httpx.HTTPError 等）→ network，绝不伪装成可用
        return _build_artifact_failure(key, checked_at, "network"), _CACHE_FAIL_TTL_SECONDS


def _build_success(release: Dict[str, Any], checked_at: int) -> Dict[str, Any]:
    """把 GitHub release 规约成契约；tag 缺失/不可解析一律转 not_found。"""
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise UpdateCheckNotFound("release 缺少 tag_name")

    latest = tag[1:] if tag.startswith("v") else tag
    try:
        latest_code = version_code(latest)
    except ValueError as exc:
        raise UpdateCheckNotFound(f"tag 无法解析为版本号: {tag!r}") from exc

    html_url = release.get("html_url")
    page_url = html_url if isinstance(html_url, str) and html_url else _release_page_url(tag)
    return {
        "current": APP_VERSION,
        "latest": latest,
        "has_update": latest_code > version_code(APP_VERSION),
        "page_url": page_url,
        "checked_at": checked_at,
        "cached": False,
        "error_reason": None,
    }


def _build_failure(reason: str, checked_at: int) -> Dict[str, Any]:
    """失败契约：`has_update` 为 None（绝不 false），`latest`/`page_url` 为 None。"""
    return {
        "current": APP_VERSION,
        "latest": None,
        "has_update": None,
        "page_url": None,
        "checked_at": checked_at,
        "cached": False,
        "error_reason": reason,
    }


def _resolve(fetch: Callable[[float], Dict[str, Any]], checked_at: int) -> "tuple[Dict[str, Any], int]":
    """出网 + 规约；返回 `(契约, 该结果应缓存多久)`。"""
    try:
        return _build_success(fetch(_HTTP_TIMEOUT), checked_at), _CACHE_TTL_SECONDS
    except UpdateCheckError as exc:
        return _build_failure(exc.reason, checked_at), _CACHE_FAIL_TTL_SECONDS
    except Exception:  # 未预期异常（httpx.HTTPError 等）→ network，绝不伪装成最新
        return _build_failure("network", checked_at), _CACHE_FAIL_TTL_SECONDS


def check_for_update(
    *,
    fetcher: Optional[Callable[[float], Dict[str, Any]]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """纯逻辑：TTL 缓存 + 规约 + 版本判定。`fetcher`/`now` 可注入以便测试。"""
    instant = time.time() if now is None else now
    fetch = _fetch_latest_release if fetcher is None else fetcher

    with _CACHE_LOCK:
        cached_payload = _cache.get("payload")
        if cached_payload is not None and instant < _cache.get("expires_at", 0.0):
            served: Dict[str, Any] = dict(cached_payload)
            served["cached"] = True
            return served

    payload, ttl = _resolve(fetch, int(instant))

    with _CACHE_LOCK:
        _cache["payload"] = payload
        _cache["expires_at"] = instant + ttl
    return dict(payload)


@router.get("/check")
def api_update_check() -> Dict[str, Any]:
    """GET /api/update/check —— 只读端点，代查 GitHub Releases。

    **不挂 `_require_localhost`**：这是 ADR-0017 §4.3 的**显式决定** —— LAN 浏览器版
    用户同样需要更新可见性，且本端点只读、不写库。**勿当漏网补闸**。
    """
    return check_for_update()


def check_artifact(
    platform: str = "windows",
    channel: str = "portable",
    arch: str = "x64",
    *,
    fetcher: Optional[Callable[[float], Dict[str, Any]]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """纯逻辑：按平台解析 Release 资产元数据（缓存 + 规约）。`fetcher`/`now` 可注入。"""
    instant = time.time() if now is None else now
    fetch = _fetch_latest_release if fetcher is None else fetcher
    key = _normalize_platform_args(platform, channel, arch)

    with _CACHE_LOCK:
        bucket = _cache.get(_ARTIFACT_BUCKET_KEY)
        entry = bucket.get(key) if isinstance(bucket, dict) else None
        if isinstance(entry, dict) and instant < entry.get("expires_at", 0.0):
            served: Dict[str, Any] = dict(entry["payload"])
            served["cached"] = True
            return served

    payload, ttl = _resolve_artifact(fetch, key, int(instant))

    with _CACHE_LOCK:
        if not isinstance(_cache.get(_ARTIFACT_BUCKET_KEY), dict):
            _cache[_ARTIFACT_BUCKET_KEY] = {}
        _cache[_ARTIFACT_BUCKET_KEY][key] = {"payload": payload, "expires_at": instant + ttl}
    return dict(payload)


@router.get("/artifact")
def api_update_artifact(
    platform: Literal["windows", "linux", "macos", "android"] = "windows",
    channel: Literal["installer", "portable"] = "portable",
    arch: Literal["x64", "arm64"] = "x64",
) -> Dict[str, Any]:
    """GET /api/update/artifact —— 只读资产元数据端点（独立于 7 键检查契约）。

    只回答"该平台的资产在哪、多大、校验和在哪"，不判定有没有新版；非法枚举由
    FastAPI 返回 422。与 `/check` 一样**不挂本机闸**：只读、不写库，LAN 浏览器版
    也需要看到下载体积。
    """
    return check_artifact(platform=platform, channel=channel, arch=arch)
