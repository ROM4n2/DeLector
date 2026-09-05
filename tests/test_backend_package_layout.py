# -*- coding: utf-8 -*-
"""后端收包（Phase 2）期间的布局守卫：数据目录与静态目录不许跟着包搬家。

为什么值得先立这两条再动手：`database.py` 里

    DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", os.path.dirname(__file__))

的默认值就是 **__file__ 所在目录**。模块搬进 `delector/` 之后，`dirname(__file__)`
会从"仓库根"变成"仓库根/delector"，于是 `delector.db` / `progress.db` 整体搬家 ——
桌面端没有 `DELECTOR_DATA_DIR` 兜底（Android 由 MainActivity 注入），用户看到的效果
就是"升级之后数据全没了"，而这种失败在本地跑测试时是全绿的，根本不会有人发现。

同理 `server.py` 的静态目录回退链里有一级 `dirname(__file__)/static`，包化后也会
指到 `delector/static`（不存在），靠 CWD 侥幸兜住 —— 换个工作目录就 404。

这两条断言在迁移**之前**就该是绿的，迁移过程中任何一步改错会立刻变红，
把"数据搬家"这种最坏的失败挡在 CI 里，而不是等到用户升级才发现。
"""
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 与其它测试同款纪律：先钉隔离 env，再 import server（顶层 init_db 有副作用）
os.environ.setdefault("DATABASE_PATH", "test_pkg_layout_delector.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_pkg_layout_progress.db")

from database import DATA_DIR  # noqa: E402
from server import STATIC_DIR  # noqa: E402


def test_data_dir_defaults_to_repo_root_not_package_dir():
    """DATA_DIR 必须落在仓库根，不能落到 delector/ 包目录里。

    delector.db / progress.db 都挂在它下面，指错一级 = 用户数据整体消失。
    """
    if os.environ.get("DELECTOR_DATA_DIR"):
        pytest.skip("本次运行显式设了 DELECTOR_DATA_DIR，默认路径不生效，跳过")

    actual = Path(DATA_DIR).resolve()
    assert actual == REPO_ROOT, (
        f"DATA_DIR 指向 {actual}，但仓库根是 {REPO_ROOT}。\n"
        "database.py 搬进 delector/ 后 os.path.dirname(__file__) 会指到包目录，"
        "导致 delector.db / progress.db 换个地方重建 —— 用户数据表现为全部消失。"
        "包化后默认值必须回指一级。"
    )


def test_static_dir_resolves_to_repo_root_static():
    """静态资源目录必须解析到仓库根的 static/，且里面真有 index.html。"""
    if os.environ.get("STATIC_DIR"):
        pytest.skip("本次运行显式设了 STATIC_DIR，跳过回退链解析断言")

    assert STATIC_DIR, "server 没能解析出静态目录（回退链全落空）"
    resolved = Path(STATIC_DIR).resolve()
    assert resolved == REPO_ROOT / "static", (
        f"STATIC_DIR 指向 {resolved}，期望 {REPO_ROOT / 'static'}。"
    )
    assert (resolved / "index.html").exists(), (
        f"{resolved} 里没有 index.html —— 静态资源挂载错了，全站会 404。"
    )


def test_no_static_dir_inside_backend_package():
    """包目录里不该出现 static/ —— 出现说明有人把资源跟着模块一起搬了。"""
    pkg = REPO_ROOT / "delector"
    if not pkg.exists():
        pytest.skip("delector/ 包还没建立（Task 1 之前）")

    assert not (pkg / "static").exists(), (
        f"{pkg / 'static'} 不该存在：静态资源留在仓库根的 static/，由 server 的"
        "回退链去解析，不要跟着模块进包。"
    )
