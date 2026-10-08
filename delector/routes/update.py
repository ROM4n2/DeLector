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
from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import APIRouter

from delector.core.version import APP_VERSION, version_code

__all__ = [
    "UpdateCheckError",
    "UpdateCheckNotFound",
    "UpdateCheckRateLimited",
    "UpdateCheckTimeout",
    "_fetch_latest_release",
    "api_update_check",
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


def _release_page_url(tag: str) -> str:
    """由 tag 构造 Release 页地址（`html_url` 缺失时的兜底）。"""
    return f"https://github.com/ROM4n2/DeLector/releases/tag/{tag}"


def _fetch_latest_release(timeout: float) -> Dict[str, Any]:
    """真实出网：GET GitHub releases/latest。

    返回 `{"tag_name": str, "html_url": str}`。超时/限流/404 抛本模块的错误子类；
    其余 httpx 异常（连接失败、非 2xx）向上抛，由 check_for_update 归类为 network。
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
    return {"tag_name": tag, "html_url": html_url if isinstance(html_url, str) else ""}


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
