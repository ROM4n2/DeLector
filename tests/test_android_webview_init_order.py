"""WebView 初始化时机守卫（③）。

守四件事：
1. `new WebView(this)` 只出现在 ensureWebView 里，onCreate 不得直接创建；
2. onCreate 用「首帧画完」的调度（OnDrawListener + post）触发创建，而不是定时器；
3. ensureWebView 幂等，且挂在 index 0（splash 仍在其上）；
4. readiness 回调在 loadUrl 之前兜底调用 ensureWebView，避免空指针。

为什么是静态断言：本仓 pytest 矩阵没有 Android runtime；能机械守住的是
「创建时机是否被改回与首帧争抢」「splash 是否还在上层」。
实测数字见 PR 描述（TTFD 同会话 A/B）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"


def _src() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


def test_new_webview_only_in_ensure_webview():
    src = _src()
    assert src.count("new WebView(this)") == 1, "WebView 只允许在 ensureWebView 里创建一次"
    assert "private void ensureWebView(FrameLayout root)" in src, "缺少 ensureWebView"
    body = src.split("private void ensureWebView(FrameLayout root)", 1)[1]
    body = body.split("\n    }", 1)[0]
    assert "new WebView(this)" in body, "ensureWebView 没有创建 WebView"
    # onCreate 内不得创建
    onCreate = src.split("protected void onCreate(Bundle savedInstanceState)", 1)[1]
    onCreate = onCreate.split("\n    }", 1)[0]
    assert "new WebView(this)" not in onCreate, "onCreate 又直接在首帧前创建 WebView 了"


def test_scheduled_after_first_frame_not_timer():
    src = _src()
    assert "scheduleWebViewAfterFirstFrame()" in src, "缺少首帧后调度的入口"
    assert src.count("scheduleWebViewAfterFirstFrame();") == 1, "调度只允许在 onCreate 调用一次"
    body = src.split("private void scheduleWebViewAfterFirstFrame()", 1)[1]
    body = body.split("\n    }", 1)[0]
    assert "addOnDrawListener" in body, "没有用绘制回调判断首帧"
    assert ".post(" in body, "OnDrawListener 在绘制前触发，必须在 post 里创建才算首帧之后"
    assert "removeOnDrawListener" in body, "首次绘制后必须摘掉监听器，避免重复创建"
    assert "postDelayed" not in body, "不允许用定时器猜首帧"


def test_ensure_webview_idempotent_and_below_splash():
    src = _src()
    body = src.split("private void ensureWebView(FrameLayout root)", 1)[1].split("\n    }", 1)[0]
    assert "if (webView != null)" in body, "ensureWebView 必须幂等（调度与 readiness 都会调用）"
    assert "root.addView(webView, 0," in body, "WebView 必须挂在 index 0，否则会盖住 splash"
    # splash 依旧是后在 index 之上的一层
    assert "root.addView(splashLayout" in src, "splash 挂载点缺失"


def test_readiness_ensures_webview_before_loadurl():
    src = _src()
    body = src.split("private void pollServerReadiness(File dataDir)", 1)[1]
    body = body.split("\n    }", 1)[0]
    assert "ensureWebView(rootLayout);" in body, "readiness 回调缺少 WebView 兜底创建"
    idx_ensure = body.index("ensureWebView(rootLayout);")
    idx_load = body.index("webView.loadUrl(")
    assert idx_ensure < idx_load, "必须保证 loadUrl 之前 WebView 已存在"
