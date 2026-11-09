"""TTFD 口径与探针守卫（只加可见性，不改启动行为）。

守四件事：
1. TTFD 的定义真的落在「首条 .article-row 首次绘制」上：JS 双 rAF + 非零盒子。
2. 原生侧以进程启动为计时基准，并且真的调用 reportFullyDrawn()（系统口径一致）。
3. 只上报一次；桥缺失（桌面浏览器）或调用失败都不影响列表渲染。
4. ① 不许顺手改启动行为：splash 200ms 撤场、端口文件唯一真相、fatalError 早退保持原样。

为什么是静态断言而不是运行期测试：TTFD 的唯一真值来自真机/模拟器的首帧时序，
本仓 pytest 矩阵里没有 Android runtime；能机械守住的是「口径写对了没有」「有没有
把探针写成改行为」。实测基线见 docs/agents/architecture.md「启动指标 TTFD」。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app"
MAIN = APP / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
READER = ROOT / "static" / "js" / "reader.js"


def _main_source() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


def _bridge_body() -> str:
    src = _main_source()
    assert "public class StartupReportBridge" in src, "缺少 StartupReportBridge"
    return src.split("public class StartupReportBridge", 1)[1].split("\n    }", 1)[0]


def _js_probe_body() -> str:
    src = READER.read_text(encoding="utf-8")
    assert "function reportFirstArticleVisible" in src, "缺少 reportFirstArticleVisible"
    return src.split("function reportFirstArticleVisible", 1)[1].split(
        "// 陈旧响应守卫", 1
    )[0]


def test_ttfd_anchor_is_first_article_row_after_paint():
    src = READER.read_text(encoding="utf-8")
    assert src.index("reportFirstArticleVisible(el);") > src.index('.join("");'), (
        "探针必须在文章列表 innerHTML 落盘之后调用"
    )
    body = _js_probe_body()
    assert 'querySelector(".article-row")' in body
    assert body.count("requestAnimationFrame(") == 2, "必须是双 rAF：第二次回调时上一帧已提交"
    assert "rect.width > 0 && rect.height > 0" in body, "必须确认首条真的渲染出非零盒子"
    # 首页列表在折叠线以下（实测 top≈1169 > innerHeight≈866），用视口相交会让 TTFD 永不触发。
    assert "innerHeight" not in body
    assert "IntersectionObserver" not in body


def test_js_hook_is_noop_without_bridge_and_reports_once():
    body = _js_probe_body()
    assert "window.DeLectorStartup" in body
    assert "typeof bridge.onFirstArticleVisible" in body, "桌面浏览器必须走空操作分支"
    assert "_ttfdReported" in body
    assert "_ttfdReported = true" in body, "必须只上报一次"
    assert "try {" in body and "catch (_)" in body, "桥调用失败不能影响列表渲染"


def test_native_bridge_uses_process_start_and_calls_report_fully_drawn():
    body = _bridge_body()
    assert "Process.getStartElapsedRealtime()" in body, "TTFD 必须以进程启动为基准"
    assert "SystemClock.elapsedRealtime()" in body
    assert "TTFD_FIRST_ARTICLE_MS=" in body, "必须给出可被 adb logcat 复现的数值"
    assert "TTFD_ROW_EPOCH=" in body, "页面侧 epoch 必须落日志，供跨来源核对"
    assert "::reportFullyDrawn" in body, "系统口径必须与 TTFD 对齐"
    assert "compareAndSet(false, true)" in body, "JS 桥来自 WebView 线程，必须原子去重"
    assert "mainHandler.post" in body, "reportFullyDrawn 必须在主线程调用"


def test_bridge_registered_and_report_fully_drawn_not_called_elsewhere():
    src = _main_source()
    assert 'addJavascriptInterface(new StartupReportBridge(), "DeLectorStartup")' in src
    assert src.count("::reportFullyDrawn") == 1, "reportFullyDrawn 只能由 TTFD 探针触发"


def test_no_startup_behavior_regression():
    """① 只加可见性：下面这些既有行为必须原样保留。"""
    src = _main_source()
    assert "splashLayout.postDelayed" in src, "splash 撤场时序不属于 ①，不能被顺手改掉"
    assert "}, 200);" in src
    assert "if (fatalError != null) {" in src, "fatalError 早退语义必须保留"
    assert "serverPort = readServerPort(dataDir);" in src, "端口只能从端口文件读，不能猜"
    assert '"DELECTOR_PORT_FILE"' in src, "端口文件环境变量名与 start.py 必须一致"
    assert "reportFullyDrawn" not in src.split("protected void onCreate", 1)[1].split(
        "private void ", 1
    )[0], "onCreate 里不得提前调用 reportFullyDrawn（会让 TTID == TTFD）"
