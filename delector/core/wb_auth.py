# -*- coding: utf-8 -*-
"""X-WB-Key 鉴权的**单一实现**：信令端点（sync / rtc）与工作台镜像写端点共用。

为什么单列这个模块（而非各路由各写一份）
----------------------------------------
`delector.core.database.verify_wb_key` 是**恒定时间比较**的统一入口（`secrets.compare_digest`），
但「取 `X-WB-Key` 头 → 比对 → 不符即 403」这段封装曾在 `routes/sync.py` 与 `routes/rtc.py`
里**逐字节重复两份**（`routes/main.py` 的 `PUT /api/wb/state` 另有第三份内联）。三份同构实现
⇒ **改一处漏一处 = 信令端点鉴权绕过**（信令在 LAN 上中继 SDP，裸奔即把会话描述递给同网段任何人）。
故收敛到此处唯一一份；各路由只调 `require_wb_key(request)`。

为什么住 `core/` 而非 `routes/`（实测约束）
------------------------------------------
`tests/test_server.py::test_register_routes_covers_every_module_in_routes_package` 要求
`delector/routes/` 下**每个**模块都定义 `APIRouter`（`pkgutil.iter_modules` 全扫）——本模块是
纯鉴权工具、无路由，放 `routes/` 会当场被该守卫判红，故归入 `core/`。

HTTP 语义**保持不变**（回归锁：相同请求头在两端点得到同一状态码）：缺 / 错 key 一律 403，
文案 `invalid X-WB-Key`。
"""

from fastapi import HTTPException, Request

from delector.core.database import get_wb_sync_key, verify_wb_key


def require_wb_key(request: Request) -> None:
    """校验请求头 `X-WB-Key` 与本机同步密钥一致；不符抛 403（与收敛前逐字一致）。"""
    if not verify_wb_key(request.headers.get("X-WB-Key"), get_wb_sync_key()):
        raise HTTPException(403, "invalid X-WB-Key")
