# -*- coding: utf-8 -*-
"""测试代码卫生机械闸：恒真断言与本机路径字面量。"""

import re

from _ci_hardening_support import (
    ANDROID_APP_BUILD_GRADLE,
    REPO_ROOT,
    _read_guard_file,
)

# ── 测试代码恒真断言机械闸（2026-11-05：`sys.stdout is not None` 恒真）────────────
# pytest 的 capture 插件必然装入非 None 的流；无控制台场景由
# `_run_with_missing_streams` 临时置 None 后，被测代码再绑定 devnull ⇒ `is not None`
# 恒真，抓不到「收口后流仍是 None」或「被替换成别的文件对象」这类真实回归。
# 本闸要求改为身份 / 语义断言（例：`sys.stdout.name == os.devnull`）。

DESKTOP_SHELL_TESTS = REPO_ROOT / "tests" / "test_desktop_shell.py"

#: 恒真形态：**无消息**的 `assert sys.stdout is not None` / `sys.stderr is not None`。
#: 带消息的同形断言（如"收口后 stderr 必须已绑上"）是刻意的存在性检查，不算恒真。
_TAUTOLOGICAL_STREAM_ASSERT = re.compile(
    r"assert\s+sys\.(?:stdout|stderr)\s+is\s+not\s+None\s*$", re.MULTILINE
)


def test_desktop_shell_has_no_tautological_stream_assertions() -> None:
    """tests/test_desktop_shell.py 不得出现「流非 None」恒真断言。

    判据是**现读源码**的正则扫描；改钉语义断言后本闸转绿，把断言改回恒真即转红。
    """
    src = _read_guard_file(DESKTOP_SHELL_TESTS)
    offenders = _TAUTOLOGICAL_STREAM_ASSERT.findall(src)
    assert offenders == [], (
        f"{DESKTOP_SHELL_TESTS.name} 出现 {len(offenders)} 处恒真断言 "
        "`assert sys.stdout/stderr is not None`：pytest capture 下恒真，对回归零区分度。\n"
        "修法：改钉对象身份（`is original_out`）或语义（`sys.stdout.name == os.devnull`），"
        "而不是改回恒真写法。"
    )


# 本机 wheel 供给与代理地址同理：只能来自 android/local.properties 的
# python.pipFindLinks（或构建环境），build.gradle 里不许出现字面量。
# 2026-11-05 曾把 D:/Android/chaquo-wheels 临时写进 build.gradle；该目录在
# CI 与其他人机器上不存在，而 ci.yml 不含 gradle 步骤 ⇒ PR 全绿、发版日才炸。
_LOCAL_SUPPLY_LITERALS = (
    (re.compile(r"chaquo-wheels"), "本机 wheel 目录"),
    (re.compile(r"127\.0\.0\.1"), "本机回环地址（代理）"),
    (re.compile(r"proxyHost"), "JVM/Gradle 代理配置键"),
)


def test_android_build_gradle_has_no_local_wheel_or_proxy_literals() -> None:
    """build.gradle 不得含本机 wheel 目录或代理字面量（只能经 local.properties 注入）。"""
    text = _read_guard_file(ANDROID_APP_BUILD_GRADLE)

    offenders = [
        f"{lineno}: {line.strip()}（命中：{name}）"
        for lineno, line in enumerate(text.splitlines(), 1)
        for pattern, name in _LOCAL_SUPPLY_LITERALS
        if pattern.search(line)
    ]
    assert not offenders, (
        "android/app/build.gradle 出现本机专属的 wheel/代理字面量：\n"
        + "\n".join(offenders)
        + "\n这些内容应写在 android/local.properties 的 python.pipFindLinks（逗号分隔目录），"
        "仓库里只保留键名分支；否则 CI/他人机器没有该目录或代理，gradle 构建会失败，"
        "而 ci.yml 不含 gradle 步骤 ⇒ PR 仍然全绿。"
    )
