"""Android WebView 外链策略与调试开关守卫。

为什么是「静态断言 + javac 直跑」而不是 Robolectric：
1. 本仓 `android/app/src/test` 原先没有任何测试基建，也没有 JUnit / Robolectric /
   androidx.test 依赖；引入它们会把 Android SDK 与 AGP unit test 任务拖进 PR 门禁，
   而当前 CI 的 pytest 矩阵只装 Python/Node（见 .github/workflows/ci.yml）。
2. 需要守的两件事都能在不装 SDK 的前提下钉死：
   - URL 判定抽成零 Android 依赖的 `WebUrlPolicy`，用 javac 直接编译执行（真行为断言）；
   - `MainActivity` 的调试开关是「有没有被 BuildConfig.DEBUG 包住」的形态问题，
     静态断言就是它的判据本身（Robolectric 需要 SDK + 模拟器才能渲染 WebView，
     而本次明确不装 SDK、不碰模拟器）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app"
MAIN = APP / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
POLICY = APP / "src" / "main" / "java" / "org" / "delector" / "app" / "WebUrlPolicy.java"
POLICY_TEST = APP / "src" / "test" / "java" / "org" / "delector" / "app" / "WebUrlPolicyTest.java"

EXPECTED_CHECKS = 25


def _main_source() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 一、调试开关：只允许 BuildConfig.DEBUG 分支里出现一次
# --------------------------------------------------------------------------- #
def test_webview_debug_enabled_only_inside_buildconfig_debug():
    src = _main_source()

    # 误开形态一：release 里也开着 —— 调用次数必须恰好 1。
    assert src.count("setWebContentsDebuggingEnabled") == 1, (
        "setWebContentsDebuggingEnabled 只能出现一次；多出来的那次很可能没有 DEBUG 守卫"
    )

    # 误开形态二：直接裸调 true（没有 if (BuildConfig.DEBUG) 包裹）。
    guarded = re.compile(
        r"if\s*\(\s*BuildConfig\.DEBUG\s*\)\s*\{\s*"
        r"WebView\.setWebContentsDebuggingEnabled\s*\(\s*true\s*\)\s*;\s*\}",
        re.S,
    )
    assert guarded.search(src), (
        "缺少 `if (BuildConfig.DEBUG) { WebView.setWebContentsDebuggingEnabled(true); }`："
        "release 会一并打开远程调试"
    )


# --------------------------------------------------------------------------- #
# 二、外链拦截：两个重载都要在，且统一走纯函数策略
# --------------------------------------------------------------------------- #
def test_should_override_url_loading_overloads_present():
    src = _main_source()
    assert re.search(
        r"boolean\s+shouldOverrideUrlLoading\s*\(\s*WebView\s+\w+\s*,\s*WebResourceRequest\s+\w+\s*\)",
        src,
    ), "缺少 shouldOverrideUrlLoading(WebView, WebResourceRequest)：API 24+ 实际走这个重载"
    assert re.search(
        r"boolean\s+shouldOverrideUrlLoading\s*\(\s*WebView\s+\w+\s*,\s*String\s+\w+\s*\)",
        src,
    ), "缺少 shouldOverrideUrlLoading(WebView, String)：旧 WebView / target=_blank 也走这个重载"


def test_external_navigation_uses_single_policy_and_never_crashes():
    src = _main_source()
    assert "setWebViewClient(new WebViewClient()" in src, "缺少 WebViewClient"
    assert "root.addView(webView" in src, "WebViewClient 区块的收尾锚点缺失"
    clients = src.split("setWebViewClient(new WebViewClient()")[1].split("root.addView(webView")[0]
    # 拦截器只做委派：判定与交付都在单一出口 handleExternalNavigation 里。
    assert clients.count("handleExternalNavigation(") == 2, "两个重载都必须走统一的 handleExternalNavigation"
    assert "startActivity(" not in clients, "WebViewClient 里出现了旁路 startActivity，绕过了统一策略"

    # Intent 解析失败必须被吞掉：没装浏览器 / 没装邮件 App 时不能崩。
    assert "private boolean handleExternalNavigation" in src, "缺少统一的 handleExternalNavigation"
    handler = src.split("private boolean handleExternalNavigation")[1].split("\n    }")[0]
    assert "WebUrlPolicy.shouldOpenExternally(" in handler, "没有使用统一的 URL 策略"
    assert "Intent.ACTION_VIEW" in handler, "外链没有交给系统浏览器（ACTION_VIEW）"
    assert re.search(r"catch\s*\(\s*Throwable", handler), "外部 Intent 缺少 catch (Throwable)"
    assert "return true" in handler, "已消费的导航必须返回 true，否则 WebView 会去加载错误页"
    assert src.count("Intent.ACTION_VIEW") == 1, "ACTION_VIEW 只允许出现在统一出口里"


# --------------------------------------------------------------------------- #
# 三、策略类保持「零 Android 依赖」，否则 javac 直跑的门禁会失效
# --------------------------------------------------------------------------- #
def test_policy_has_no_android_or_androidx_imports():
    text = POLICY.read_text(encoding="utf-8")
    imports = re.findall(r"^import\s+([\w.]+)\s*;", text, re.M)
    offenders = [i for i in imports if i.startswith("android.") or i.startswith("androidx.")]
    assert not offenders, f"WebUrlPolicy 必须零 Android 依赖，实际引入了: {offenders}"


# --------------------------------------------------------------------------- #
# 四、行为断言：javac 直编直跑
# --------------------------------------------------------------------------- #
def test_url_policy_behaviour_with_javac(tmp_path: Path):
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.skip("javac/java 不在 PATH 上；URL 策略的行为断言无法执行（静态断言仍然生效）")

    assert POLICY.is_file(), f"缺少 {POLICY}"
    classes = tmp_path / "classes"
    classes.mkdir()

    compiled = subprocess.run(
        [javac, "-encoding", "UTF-8", "-d", str(classes), str(POLICY), str(POLICY_TEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert compiled.returncode == 0, f"javac 编译失败:\n{compiled.stdout}\n{compiled.stderr}"

    run = subprocess.run(
        [java, "-cp", str(classes), "org.delector.app.WebUrlPolicyTest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (run.stdout or "") + (run.stderr or "")
    assert run.returncode == 0, f"WebUrlPolicyTest 失败（exit={run.returncode}）:\n{output}"
    assert "FAIL " not in output, f"存在失败用例:\n{output}"
    assert f"checks={EXPECTED_CHECKS} failed=0" in output, (
        f"用例数不是 {EXPECTED_CHECKS}（可能被删改）:\n{output}"
    )
