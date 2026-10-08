# -*- coding: utf-8 -*-
"""应用级版本单一真相源。

为什么需要它：后端此前没有任何应用级版本常量，机器可读的版本落点只有
android/app/build.gradle 的 fallback（DELECTOR_VERSION_NAME / DELECTOR_VERSION_CODE）。
各处若再各抄一份版本，副本漂了不会报错，只会静默产出偏小的 versionCode。

纪律：本模块是**叶模块**，只吃标准库、不 import 任何 delector.* ——
它会被最底层的 server / tools / 测试引用，反向依赖会制造循环 import。
"""

__all__ = ["APP_VERSION", "version_code"]

# 与 android/app/build.gradle:8 的 versionName fallback 同口径：不带 'v' 前缀。
APP_VERSION: str = "5.16.0"

# 每段版本号只有两位空间（minor/patch < 100），故步进 100 / 10000。
_MINOR_STEP = 100
_MAJOR_STEP = 10000


def version_code(version: str = APP_VERSION) -> int:
    """把 'major.minor.patch' 编成 Android 的 versionCode。

    规则（红线 4，见 android/app/build.gradle:9 与 tests/test_writer_mobile.py:84-90）：
    major*10000 + minor*100 + patch。旧规则 major*100 + minor*10 + patch 在
    minor 到 10 时溢出撞车（3.10.0 与 4.0.0 都得 400），而 versionCode 必须严格
    单调递增 —— 撞车意味着 4.0.0 无法覆盖安装 3.10.0。

    非法输入一律抛 ValueError，绝不静默出数：段数不为 3、段内含非数字、负数。
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"版本号必须是 major.minor.patch 三段，实际 {version!r}")
    for part in parts:
        # 用 isdigit 而非 int()：int() 会吞掉首尾空白（'3 ' → 3），把
        # '1.2.3 ' 这种含非数字的输入静默放行。
        if not (part.isascii() and part.isdigit()):
            raise ValueError(f"版本段必须是纯数字，实际 {version!r} 含 {part!r}")
    major, minor, patch = (int(p) for p in parts)
    return major * _MAJOR_STEP + minor * _MINOR_STEP + patch
