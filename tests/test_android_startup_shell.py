"""Android 启动静态壳守卫。

启动壳（`assets/shell/startup.html`）的唯一目的是在 Python 就绪前把 WebView 的渲染
进程与网络栈预热起来；它必须**自包含**（无外链，否则启动期会额外发网络请求）、
视觉与同色原生 splash 一致（避免切换时闪色），并且只能在 onCreate 里、Python 启动
线程之前加载。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
SHELL = ROOT / "android" / "app" / "src" / "main" / "assets" / "shell" / "startup.html"

SHELL_URL = "file:///android_asset/shell/startup.html"


def _main_source() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


def test_shell_exists_and_is_self_contained():
    assert SHELL.is_file(), f"缺少启动壳 {SHELL}"
    html = SHELL.read_text(encoding="utf-8")
    offenders = re.findall(r"""(?:src|href)\s*=\s*["'](https?:)?//""", html)
    assert not offenders, f"启动壳不得引用外部资源（启动期会多发网络请求）: {offenders}"
    assert not re.search(r"<script\b", html), "启动壳不应含脚本：它只负责预热渲染，不承载业务逻辑"


def test_shell_visual_matches_native_splash():
    html = SHELL.read_text(encoding="utf-8")
    assert "#FAF8F5" in html, "启动壳背景必须与原生 splash 同色（#FAF8F5），否则切换会闪色"
    for text in ("DeLector", "德语欧标精读与备考工作台", "正在启动德语语言学引擎与本地词库..."):
        assert text in html, f"启动壳缺少与 splash 一致的文案: {text}"


def test_main_activity_preloads_shell_before_python_thread():
    src = _main_source()
    assert f'"{SHELL_URL}"' in src, "MainActivity 必须引用启动壳地址"

    on_create = src.split("protected void onCreate")[1].split("private boolean handleExternalNavigation")[0]
    assert "webView.loadUrl(STARTUP_SHELL_URL)" in on_create, "启动壳必须在 onCreate 内加载"
    assert on_create.index("setContentView(root)") < on_create.index("webView.loadUrl(STARTUP_SHELL_URL)"), (
        "启动壳必须在 setContentView 之后加载：WebView 需要先挂到有尺寸的容器上"
    )
    assert on_create.index("webView.loadUrl(STARTUP_SHELL_URL)") < on_create.index(
        "new Thread(this::initAndStartServer).start()"
    ), "启动壳必须早于 Python 启动线程：并行的意义就是让 WebView 冷启动与 Python 启动重叠"


def test_splash_hide_only_trusts_server_page():
    """壳是 file:// 页面，它自己的 onPageFinished 不能提前撤掉 splash。"""
    src = _main_source()
    on_page_finished = src.split("public void onPageFinished")[1].split("public void onReceivedError")[0]
    assert "isServerReady" in on_page_finished, "onPageFinished 仍须以服务就绪为前提"
    assert "serverBaseUrl(" in on_page_finished, (
        "onPageFinished 必须校验 url 属于服务页面：否则启动壳的完成事件可能提前撤 splash"
    )
