# -*- coding: utf-8 -*-
"""HTTP 路由子包（ADR-0008 Phase 1 Task 4）。

原扁平模块 `delector/routes_*.py` 收进本子包，`routes_` 前缀由包路径取代
（`delector.routes_a1` → `delector.routes.a1`）。

对外只暴露一个入口 `register_routes(app)`：app 工厂（server.create_app）不需要
知道有几个路由模块、各自内部叫什么名字，新增路由模块只改这里一处。

`sync` 的两个内部符号在此 re-export，是因为 `delector.server` 对它们有历史
re-export 契约（测试 `test_server.py` 直接 `from delector.server import
_sync_sdp_cache`）——测试钉的是"缓存与容量上限"，不是模块路径，这里保持可达。
"""
from fastapi import FastAPI

from delector.routes import (
    a1,
    a1_hoeren,
    a1_lesen,
    a2,
    corpus,
    exam,
    rtc,
    sync,
)
from delector.routes.sync import (
    MAX_SYNC_CACHE_ENTRIES,
    _SYNC_INSTANCE_ID,
    _sync_sdp_cache,
)

__all__ = [
    "a1",
    "a1_hoeren",
    "a1_lesen",
    "a2",
    "corpus",
    "exam",
    "rtc",
    "sync",
    "MAX_SYNC_CACHE_ENTRIES",
    "_SYNC_INSTANCE_ID",
    "_sync_sdp_cache",
    "register_routes",
]


def register_routes(app: FastAPI) -> None:
    """按既有顺序挂载全部分域路由。

    顺序不是随意的：`/api/a1/hoeren` 与 `/api/a1/lesen` 挂在 `/api/a1` 之后，
    先挂载的路由先匹配；改动顺序可能让同前缀路径命中到别的 handler。
    """
    app.include_router(a1.router)
    app.include_router(a2.router)
    app.include_router(sync.router)
    app.include_router(rtc.router)
    app.include_router(corpus.router)
    app.include_router(a1_hoeren.hoeren_router)
    app.include_router(a1_lesen.lesen_router)
    app.include_router(exam.router)
