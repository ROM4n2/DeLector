# -*- coding: utf-8 -*-
"""应用级版本单一真相源（delector/core/version.py）的守卫。

后端此前没有任何应用级版本常量：机器可读的版本落点只有
android/app/build.gradle 的 fallback（DELECTOR_VERSION_NAME / DELECTOR_VERSION_CODE）。
本模块把「版本真相」收进 Python 侧，供后端/工具/测试引用，避免各处再各抄一份。

守两件事：
1. versionName ↔ versionCode 的编码规则（红线 4：major*10000 + minor*100 + patch）。
   旧规则 major*100 + minor*10 + patch 在 3.10.0 与 4.0.0 上撞车，而 versionCode
   必须严格单调递增 —— 撞车意味着新版无法覆盖安装旧版，这是历史事故。
2. 非法输入必须显式抛 ValueError，而不是静默算出离谱的 code。
"""

import re
from pathlib import Path

import pytest

from delector.core.version import APP_VERSION, version_code


def test_app_version_matches_gradle_fallback():
    """APP_VERSION 必须与 build.gradle 的 versionName fallback 同口径（无 v 前缀）。

    写死字面量是为了 bump 时让这条测试变红、逼人同步；同时断言无 'v' 前缀，
    因为它要与 build.gradle:8 的 "5.16.0" 逐字对齐（带 v 会让 code 解析先炸）。
    """
    assert APP_VERSION == "5.16.0", f"APP_VERSION 应为 '5.16.0'（无 v 前缀），实际 {APP_VERSION!r}"
    assert not APP_VERSION.startswith("v"), "APP_VERSION 不带 'v' 前缀，与 build.gradle fallback 口径一致"


def test_version_code_encodes_major_minor_patch():
    """编码规则 major*10000 + minor*100 + patch（红线 4，与 build.gradle:9 一致）。"""
    assert version_code("5.16.0") == 51600, "5.16.0 应编码为 51600（5*10000 + 16*100 + 0）"
    assert version_code("0.0.1") == 1, "0.0.1 应编码为 1"
    assert version_code("1.0.0") == 10000, "1.0.0 应编码为 10000"


def test_version_code_default_uses_app_version():
    """无参调用回落到 APP_VERSION，保证默认口径与真相源同源。"""
    assert version_code() == version_code(APP_VERSION) == 51600, (
        f"version_code() 默认值应等于 version_code(APP_VERSION)={version_code(APP_VERSION)}"
    )


def test_version_code_is_strictly_monotonic_across_minor_ten():
    """3.10.0 与 4.0.0 不得撞车。

    旧规则 major*100 + minor*10 + patch 在此撞车（都得 400）。versionCode 撞车
    意味着它不再严格递增 → 新版无法覆盖安装旧版，这是历史事故。
    """
    assert version_code("3.10.0") != version_code("4.0.0"), (
        "3.10.0 与 4.0.0 的 versionCode 撞车：旧规则 major*100+minor*10+patch 的缺陷复现了"
    )
    assert version_code("3.10.0") < version_code("4.0.0"), "3.10.0 的 code 必须小于 4.0.0（严格单调递增）"


@pytest.mark.parametrize(
    "bad",
    [
        "1.2",  # 段数不足 3
        "1.2.3.4",  # 段数超过 3
        "1.2.x",  # 含非数字
        "a.b.c",  # 整段非数字
        "1..3",  # 空段
        "",  # 空串
        "-1.2.3",  # 首段负数
        "1.2.-3",  # 尾段负数
        "1.2.3 ",  # 段内含非数字（尾随空格）
        "５.１.０",  # 全角数字 U+FF15 等，属 Unicode 十进制类 Nd，isdigit 为真但非 ASCII
        "1.2.٣",  # 阿拉伯-印度数字 U+0663，isdigit 为真但非 ASCII
    ],
)
def test_version_code_rejects_malformed_input(bad):
    """段数不为 3、含非数字、负数一律抛 ValueError，绝不静默出数。"""
    with pytest.raises(ValueError):
        version_code(bad)


def test_version_module_is_a_leaf_without_package_imports():
    """version.py 必须是叶模块：不 import 任何 delector.* —— 否则会引入循环依赖。

    版本真相源会被最底层的模块（server、tools、测试）引用；它一旦反向依赖
    包内模块，import 顺序就会变成地雷。
    """
    src_path = Path(__file__).parent.parent / "delector" / "core" / "version.py"
    src = src_path.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:from|import)\s+delector", src, re.M), (
        "version.py 不该 import 任何 delector.* 模块（叶模块纪律，避免循环依赖）"
    )
