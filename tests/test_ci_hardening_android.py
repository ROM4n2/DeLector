# -*- coding: utf-8 -*-
"""Android 运行时契约：ABI flavor、模拟器隔离、工具链矩阵与 pydantic 兼容性。"""

import ast
import re
from pathlib import Path

import pytest
from _ci_hardening_support import (
    REPO_ROOT,
    _read_guard_file,
)

# ── Android Python 运行时契约（pydantic v1 兼容；2026-09-28 swarm 审计 P1）────────
# 背景：Android 打包面走 Chaquopy，只能装纯 Python 依赖 ⇒ 锁 `pydantic<2.0.0`
# （v2 的 pydantic-core 是 Rust 写的，Android 上编译不了）⇒ fastapi 连带锁
# `<0.100.0`（见 android/app/build.gradle 的 pip 块）。而 delector 源码**桌面/Android
# 共用**、CI 只在 pydantic v2 + fastapi 0.141.1 下校验 —— 一旦有人用了 v2-only API，
# CI 全绿、APK 在 import 阶段直接崩，且没有任何门禁会拦（审计认定的最危险盲区）。
#
# 本守卫在普通套件内**静态**钉住"delector 不使用 pydantic v2-only API"。它是**近似**
# 而非等价：覆盖最常见的 API 形态回归，但不能替代真机覆盖安装点检（v1/v2 的校验/强转
# 等行为差异不在此覆盖范围）。

ANDROID_GRADLE = REPO_ROOT / "android" / "app" / "build.gradle"
DELECTOR_DIR = REPO_ROOT / "delector"


def _gradle_block(text: str, header_re: str) -> str:
    """返回 Groovy 块 `header { ... }` 的内部文本（按花括号配对，取最外层）。

    只服务于 build.gradle 这种**注释与字符串里都没有裸花括号**的文件；一旦该文件
    出现花括号字面量，本函数会失配并显式 fail，而不是静默给出半截文本。
    """
    match = re.search(header_re, text)
    if match is None:
        raise AssertionError(f"build.gradle 里找不到块头 {header_re!r}")
    open_brace = text.find("{", match.start())
    depth = 0
    for index in range(open_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : index]
    raise AssertionError(f"块 {header_re!r} 的花括号不配对")


def _flavor_body(name: str) -> str:
    """取 `productFlavors { ... }` 里某个 flavor 的内部文本。"""
    text = _read_guard_file(ANDROID_GRADLE)
    flavors = _gradle_block(text, r"\bproductFlavors\s*\{")
    return _gradle_block(flavors, rf"\b{re.escape(name)}\s*\{{")


def _build_type_body(name: str) -> str:
    """取 `buildTypes { ... }` 里某个 buildType 的内部文本。"""
    text = _read_guard_file(ANDROID_GRADLE)
    build_types = _gradle_block(text, r"\bbuildTypes\s*\{")
    return _gradle_block(build_types, rf"\b{re.escape(name)}\s*\{{")


def _abi_filters(body: str) -> list[str]:
    """解析块内**唯一的** abiFilters 声明，返回带引号的 ABI 列表。"""
    declarations = re.findall(r"\babiFilters\s+([^\n]+)", body)
    assert len(declarations) == 1, (
        f"块内应恰好有一条 abiFilters 声明，实际 {len(declarations)} 条：{declarations}"
    )
    return re.findall(r'"([^"]+)"', declarations[0])


def test_android_device_flavor_abi_is_arm64_only():
    """正式 device 渠道的 abiFilters 只允许 arm64-v8a（x86_64 会撑大正式包）。

    这条闸拦的是「为了模拟器顺手把 x86_64 塞进 device」：spaCy 原生栈按 ABI
    各占 21–29MB，双 ABI 的 debug APK 2026-11-04 实测 87.87 MiB。
    """
    text = _read_guard_file(ANDROID_GRADLE)
    default_config = _gradle_block(text, r"\bdefaultConfig\s*\{")
    assert not re.search(r"\babiFilters\s+\"", default_config), (
        "abiFilters 不得留在 defaultConfig：它会被所有 flavor 继承，"
        "x86_64 会渗进 device。请下移到 productFlavors 各自声明。"
    )
    assert "productFlavors" in text, (
        "ABI 必须按 product flavor 声明：Chaquopy 的 getAbis 只读 defaultConfig 与 "
        "productFlavors，完全不看 buildType，放在 buildType 会直接构建失败。"
    )

    device_abis = _abi_filters(_flavor_body("device"))
    assert device_abis == ["arm64-v8a"], (
        f"device 的 abiFilters 只允许 ['arm64-v8a']，实际 {device_abis}。"
        "x86_64 属模拟器渠道，不许进正式包。"
    )

    release_body = _build_type_body("release")
    assert not re.search(r"\babiFilters\s+\"", release_body), (
        "release buildType 不得声明 abiFilters：Chaquopy 不读 buildType，"
        "这里写了也无效，只会让人误以为 ABI 被改过。"
    )
    assert "variantBuilder.enable = false" in text, (
        "必须禁用 emulatorRelease，否则 assembleRelease 也会产出模拟器包，"
        "发版产物集合不再只有一个正式 APK。"
    )


def test_android_emulator_flavor_abi_includes_x86_64():
    """emulator 渠道必须同时含 arm64-v8a 与 x86_64，且与正式包可共存。"""
    body = _flavor_body("emulator")
    emulator_abis = _abi_filters(body)
    assert "x86_64" in emulator_abis, f"emulator 必须含 x86_64，实际 {emulator_abis}"
    assert "arm64-v8a" in emulator_abis, f"emulator 应保留 arm64-v8a，实际 {emulator_abis}"
    assert 'applicationIdSuffix ".emulator"' in body, (
        "emulator 必须用 applicationIdSuffix 与正式包区分，否则无法并存安装"
    )


def test_emulator_workflow_is_isolated_from_release():
    """模拟器 APK 必须有独立构建入口，且绝不复用 release 的产物路径/命名。"""
    path = REPO_ROOT / ".github" / "workflows" / "android-emulator.yml"
    if not path.exists():
        pytest.fail(f"缺少模拟器构建 workflow：{path}（模拟器变体将无法产出 APK）")
    workflow = path.read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow, "模拟器构建必须手动触发，不得进 tag 发版链路"
    assert "tags:" not in workflow and "push:" not in workflow, (
        "模拟器构建不得挂 push / tag 触发：它会把 runner 分钟数烧在非发版场景"
    )
    assert "assembleEmulator" in workflow, "必须构建 emulator 变体（assembleEmulator）"
    assert "DeLector-emulator-apk" in workflow, "产物 artifact 必须用模拟器专属名称"
    assert "dist/DeLector-" not in workflow, (
        "模拟器构建不得写 dist/DeLector-*：那些路径属发版产物，混用会让 release 抓错包"
    )


# ── Android 工具链矩阵守卫（2026-11-05）────────────────────────────────────────
# 背景：Android Studio 的 AGP Upgrade Assistant 会**一键**把 AGP 与 Gradle wrapper
# 同时推出去（2026-11-05 实测 `TRIGGER_AGP_VERSION_UPDATED` 把 AGP→8.13.0、wrapper→8.13）；
# 而 CI 的 `gradle-version:` 并不读 wrapper ⇒ 三处版本可能各说各话。
# 下面把当前这套组合**精确钉住**：不做 `>=` 之类宽松比较，语义就是"此刻的组合"。
# 漂移的后果是构建期才炸（依赖解析 / 插件 API 不匹配），而不是测试红。

_TOOLCHAIN_MATRIX = {
    "agp": "8.4.2",
    "chaquopy": "15.0.1",
    "gradle": "8.6",
    "compileSdk": "34",
    "minSdk": "24",
    "buildToolsVersion": "34.0.0",
}
_TOOLCHAIN_REMEDY = (
    "若要升级工具链，需同时更新此守卫（tests/test_ci_hardening_android.py）与 "
    ".github/workflows/build-release.yml、android-emulator.yml，"
    "并验证 assemble 双变体（assembleDeviceDebug / assembleEmulatorDebug）。"
)

ANDROID_ROOT_GRADLE = REPO_ROOT / "android" / "build.gradle"
GRADLE_WRAPPER_PROPERTIES = REPO_ROOT / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-release.yml"
EMULATOR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "android-emulator.yml"


def _cite(text: str, path: Path, index: int) -> str:
    """把字符下标折算成 `文件:行号：行内容`，用于失败消息里直接定位。"""
    line_no = text.count("\n", 0, index) + 1
    line = text.splitlines()[line_no - 1].strip()
    return f"{path}:{line_no}：{line}"


def _assert_pinned_version(*, text: str, path: Path, index: int, what: str, actual: str, expected: str) -> None:
    """精确比较版本；失败消息同时给出期望值、实际值、位置与升级流程。"""
    assert actual == expected, (
        f"{what} 版本不符：期望 {expected!r}，实际 {actual!r}；位置 {_cite(text, path, index)}。\n"
        f"{_TOOLCHAIN_REMEDY}"
    )


def _classpath_version(text: str, path: Path, coordinate: str, expected: str) -> tuple[str, int]:
    """从 `classpath '<group>:<artifact>:<version>'` 解析版本，返回 (版本, 下标)。"""
    match = re.search(rf"classpath\s+['\"]{re.escape(coordinate)}:([^'\"]+)['\"]", text)
    assert match is not None, (
        f"{path} 找不到 classpath {coordinate}（期望 {expected!r}）：声明缺失或被改名。\n"
        f"{_TOOLCHAIN_REMEDY}"
    )
    return match.group(1), match.start(1)


def _wrapper_gradle_version(text: str, path: Path) -> tuple[str, int]:
    """解析 `distributionUrl` 里的 Gradle 版本；URL 形态异常时返回整条 URL 作为实际值。"""
    url_match = re.search(r"distributionUrl=(\S+)", text)
    assert url_match is not None, (
        f"{path} 缺少 distributionUrl 声明（期望指向 gradle-{_TOOLCHAIN_MATRIX['gradle']}-bin.zip）。\n"
        f"{_TOOLCHAIN_REMEDY}"
    )
    version_match = re.search(r"gradle-(\d+(?:\.\d+){1,2})-bin\.zip", url_match.group(1))
    if version_match is None:
        return url_match.group(1), url_match.start(1)
    return version_match.group(1), url_match.start(1)


def _workflow_gradle_version(text: str, path: Path) -> tuple[str, int]:
    """解析 workflow 里 `gradle-version:` 的取值（去掉引号），返回 (版本, 下标)。"""
    match = re.search(r"^[ \t-]*gradle-version:\s*([^\s#]+)", text, re.MULTILINE)
    assert match is not None, (
        f"{path} 找不到 gradle-version: 声明（期望 \"{_TOOLCHAIN_MATRIX['gradle']}\"）。\n"
        f"{_TOOLCHAIN_REMEDY}"
    )
    return match.group(1).strip("\"'"), match.start()


def _gradle_version_sources() -> list[tuple[str, str, Path, str, int]]:
    """三个 Gradle 版本来源：wrapper 文件 + 两个 workflow 的 `gradle-version:`。"""
    sources: list[tuple[str, str, Path, str, int]] = []
    wrapper_text = _read_guard_file(GRADLE_WRAPPER_PROPERTIES)
    version, index = _wrapper_gradle_version(wrapper_text, GRADLE_WRAPPER_PROPERTIES)
    sources.append(
        ("gradle-wrapper.properties 的 distributionUrl", version, GRADLE_WRAPPER_PROPERTIES, wrapper_text, index)
    )
    for path in (RELEASE_WORKFLOW, EMULATOR_WORKFLOW):
        text = _read_guard_file(path)
        version, index = _workflow_gradle_version(text, path)
        sources.append((f"{path.name} 的 gradle-version", version, path, text, index))
    return sources


def _flavor_abi_cite(name: str) -> str:
    """返回 flavor 内 `abiFilters` 声明所在行（`文件:行号：行内容`）。"""
    text = _read_guard_file(ANDROID_GRADLE)
    body = _flavor_body(name)
    index = text.find(body) + body.find("abiFilters")
    return _cite(text, ANDROID_GRADLE, index)


def test_android_agp_and_chaquopy_versions_are_pinned() -> None:
    """`android/build.gradle` 的 AGP / Chaquopy 版本必须精确等于矩阵值。"""
    text = _read_guard_file(ANDROID_ROOT_GRADLE)
    for coordinate, key in (
        ("com.android.tools.build:gradle", "agp"),
        ("com.chaquo.python:gradle", "chaquopy"),
    ):
        expected = _TOOLCHAIN_MATRIX[key]
        actual, index = _classpath_version(text, ANDROID_ROOT_GRADLE, coordinate, expected)
        _assert_pinned_version(
            text=text,
            path=ANDROID_ROOT_GRADLE,
            index=index,
            what=coordinate,
            actual=actual,
            expected=expected,
        )


def test_gradle_wrapper_pins_gradle_version() -> None:
    """wrapper 的 `distributionUrl` 必须指向 gradle-8.6-bin.zip（Upgrade Assistant 的入口）。"""
    text = _read_guard_file(GRADLE_WRAPPER_PROPERTIES)
    actual, index = _wrapper_gradle_version(text, GRADLE_WRAPPER_PROPERTIES)
    _assert_pinned_version(
        text=text,
        path=GRADLE_WRAPPER_PROPERTIES,
        index=index,
        what="distributionUrl 的 Gradle",
        actual=actual,
        expected=_TOOLCHAIN_MATRIX["gradle"],
    )


@pytest.mark.parametrize("path", [RELEASE_WORKFLOW, EMULATOR_WORKFLOW], ids=["build-release", "android-emulator"])
def test_ci_workflows_pin_gradle_version(path: Path) -> None:
    """两个 workflow 的 `gradle-version:` 必须都是 "8.6"（CI 不读 wrapper）。"""
    text = _read_guard_file(path)
    actual, index = _workflow_gradle_version(text, path)
    _assert_pinned_version(
        text=text,
        path=path,
        index=index,
        what="gradle-version",
        actual=actual,
        expected=_TOOLCHAIN_MATRIX["gradle"],
    )


def test_gradle_version_is_consistent_across_toolchain() -> None:
    """wrapper 与两个 workflow 解析出的 Gradle 版本必须三者相同，且等于矩阵值。

    两条断言顺序有意：先查"三处是否一致"，再查"是否等于期望值"。只改一处
    （典型：手动编辑 build-release.yml）会命中第一条的"三处不一致"；三处被
    同时改（典型：升级脚本批量替换）会命中第二条的"版本不符"。
    """
    sources = _gradle_version_sources()
    labels = [
        f"{label} = {version!r}（{_cite(text, path, index)}）" for label, version, path, text, index in sources
    ]
    distinct = sorted({version for _, version, *_ in sources})
    assert len(distinct) == 1, (
        "Gradle 版本三处不一致（wrapper / 两个 CI workflow）：\n  "
        + "\n  ".join(labels)
        + "\n三处必须指向同一版本，否则本地与 CI 的构建面不同。\n"
        + _TOOLCHAIN_REMEDY
    )
    assert distinct == [_TOOLCHAIN_MATRIX["gradle"]], (
        f"Gradle 版本不符：期望三处均为 {_TOOLCHAIN_MATRIX['gradle']!r}，实际 {distinct}；位置：\n  "
        + "\n  ".join(labels)
        + f"\n{_TOOLCHAIN_REMEDY}"
    )


def test_android_app_sdk_and_flavors_are_pinned() -> None:
    """`android/app/build.gradle` 的 SDK / buildTools / flavor 矩阵必须精确匹配。"""
    text = _read_guard_file(ANDROID_GRADLE)

    for keyword in ("compileSdk", "minSdk"):
        match = re.search(rf"^[ \t]+{keyword}\s+(\d+)", text, re.MULTILINE)
        assert match is not None, (
            f"{ANDROID_GRADLE} 找不到 {keyword} 声明（期望 {_TOOLCHAIN_MATRIX[keyword]!r}）。\n"
            f"{_TOOLCHAIN_REMEDY}"
        )
        _assert_pinned_version(
            text=text,
            path=ANDROID_GRADLE,
            index=match.start(1),
            what=keyword,
            actual=match.group(1),
            expected=_TOOLCHAIN_MATRIX[keyword],
        )

    # buildToolsVersion 未显式声明时不断言：AGP 8.4.2 的默认 build-tools 由 compileSdk
    # 决定，断言"必须没写"会与 AGP 默认值的演化耦合；显式写了就必须是矩阵值。
    build_tools = re.search(r"^[ \t]+buildToolsVersion\s+['\"]?([0-9.]+)", text, re.MULTILINE)
    if build_tools is not None:
        _assert_pinned_version(
            text=text,
            path=ANDROID_GRADLE,
            index=build_tools.start(1),
            what="buildToolsVersion",
            actual=build_tools.group(1),
            expected=_TOOLCHAIN_MATRIX["buildToolsVersion"],
        )

    device_abis = _abi_filters(_flavor_body("device"))
    assert device_abis == ["arm64-v8a"], (
        f"device flavor 的 abiFilters 期望 ['arm64-v8a']，实际 {device_abis}；"
        f"位置 {_flavor_abi_cite('device')}。\n"
        "x86_64 属模拟器渠道，不许进正式包。\n"
        + _TOOLCHAIN_REMEDY
    )

    emulator_abis = _abi_filters(_flavor_body("emulator"))
    missing_abis = {"arm64-v8a", "x86_64"} - set(emulator_abis)
    assert not missing_abis, (
        f"emulator flavor 的 abiFilters 必须含 arm64-v8a 与 x86_64，实际 {emulator_abis}，"
        f"缺 {sorted(missing_abis)}；位置 {_flavor_abi_cite('emulator')}。\n"
        + _TOOLCHAIN_REMEDY
    )

    disabled = re.search(
        r'if\s*\(\s*variantBuilder\.name\s*==\s*"emulatorRelease"\s*\)\s*\{'
        r"\s*variantBuilder\.enable\s*=\s*false",
        text,
    )
    assert disabled is not None, (
        "emulatorRelease 未被禁用：期望 androidComponents 的 beforeVariants 里对 "
        '"emulatorRelease" 置 `variantBuilder.enable = false`'
        f"（现值形态见 {ANDROID_GRADLE} 的 androidComponents 块），实际未找到该组合。\n"
        + _TOOLCHAIN_REMEDY
    )


# pydantic v2 才有、v1 没有的名字：导入 / 装饰器 / 类属性 / 方法调用命中即 v1 下必炸。
_PYDANTIC_V2_ONLY = {
    # 导入名（from pydantic import X）
    "ConfigDict",
    "field_validator",
    "model_validator",
    "field_serializer",
    "model_serializer",
    "computed_field",
    "TypeAdapter",
    "RootModel",
    "AliasChoices",
    "AliasPath",
    # 仅 v2 才有的类属性 / 方法
    "model_config",
    "model_validate",
    "model_validate_json",
    "model_construct",
    "model_fields",
    "model_json_schema",
    "model_rebuild",
}
# v2 的 dump API（v1 对应 .dict()/.json()）：只能经 hasattr 兼容垫片使用
_PYDANTIC_V2_COMPAT_DUMPS = {"model_dump", "model_dump_json"}
# 仅 v2 支持的 Field 关键字（v1 用 regex= 而非 pattern= 等）
_PYDANTIC_V2_FIELD_KWARGS = {"pattern", "json_schema_extra", "union_mode"}


def _iter_delector_py() -> list[Path]:
    """delector/ 下全部 .py（含子包），供静态扫描。"""
    return sorted(DELECTOR_DIR.rglob("*.py"))


def test_android_pins_pydantic_v1_and_fastapi_pre_0100():
    """android/app/build.gradle 必须仍锁 pydantic<2 / fastapi<0.100（契约锚点）。

    这条不是"崇拜旧版本"，而是把 Android 的 Python 运行时契约钉成显式断言：一旦有人
    改了 Android 的 pin，本测试会红，逼他同步复核下一条守卫（delector 是否仍对
    pydantic v1 兼容），而不是让桌面/Android 两边悄悄漂移。
    """
    text = _read_guard_file(ANDROID_GRADLE)
    for needle, why in (
        ('install "pydantic<2.0.0"', "Android 面必须锁 pydantic v1（Chaquopy 装不了 Rust 扩展）"),
        ('install "fastapi<0.100.0"', "fastapi 需与 pydantic v1 配套，故锁在 0.100 之前"),
    ):
        assert needle in text, (
            f"{ANDROID_GRADLE} 缺少 {needle!r}（{why}）。\n"
            "若这是有意的升级，请同步复核 delector 是否仍对 pydantic v1 兼容，"
            "并更新本守卫与 build.gradle 里 pin 理由的注释。"
        )


def test_delector_avoids_pydantic_v2_only_api():
    """delector 源码不得使用 pydantic v2-only API（否则 CI 绿、Android APK 崩）。"""
    offenders = []
    for path in _iter_delector_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "pydantic":
                for alias in node.names:
                    if alias.name in _PYDANTIC_V2_ONLY:
                        offenders.append(f"{path}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.Attribute) and node.attr in _PYDANTIC_V2_ONLY:
                offenders.append(f"{path}:{node.lineno} .{node.attr}")
            elif isinstance(node, ast.Name) and node.id in _PYDANTIC_V2_ONLY:
                offenders.append(f"{path}:{node.lineno} {node.id}")
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _PYDANTIC_V2_FIELD_KWARGS:
                        offenders.append(f"{path}:{node.lineno} Field(..., {kw.arg}=...)")
    assert not offenders, (
        "delector 使用了 pydantic v2-only API —— Android 面是 pydantic v1，"
        "这些写法在 APK 里 import/调用即崩（而 CI 的 pydantic v2 不会报）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：改用 v1/v2 兼容写法；dump 类 API 走 hasattr 兼容垫片。"
    )


def test_pydantic_dump_api_guarded_by_hasattr_shim():
    """model_dump/model_dump_json 是 v2-only，必须经 hasattr 兼容垫片使用。"""
    offenders = []
    for path in _iter_delector_py():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(f".{attr}" in line for attr in _PYDANTIC_V2_COMPAT_DUMPS):
                if "hasattr(" not in line:
                    offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "model_dump/model_dump_json 是 pydantic v2 才有的方法，v1 下会 AttributeError；"
        '必须写成 `x.model_dump() if hasattr(x, "model_dump") else x.dict()` 的兼容垫片：\n  '
        + "\n  ".join(offenders)
    )
