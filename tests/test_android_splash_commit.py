"""splash 撤场时序守卫：必须由「首帧内容已提交」驱动，不得用固定定时器猜。

背景：旧实现是 `loadUrl` 之后 `postDelayed(..., 200)` 撤 splash。本机（x86_64 模拟器）
页面首帧约 0.7s，慢设备更长，于是 200ms 撤场后会把用户甩到白屏/半成品上。

能机械守住的三件事：
1. 正常路径只认 `onPageCommitVisible`，且撤场前只露本地服务页（端口文件给出的地址）。
2. `revealWebView()` 幂等、只改可见性、内部没有任何计时器。
3. 失败路径仍把 splash 拉回来并显示可复制的错误，不能因为改撤场而丢失败可见性。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"


def _src() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


def _reveal_body() -> str:
    src = _src()
    assert "private void revealWebView()" in src
    return src.split("private void revealWebView()", 1)[1].split("\n    }", 1)[0]


def test_splash_removal_is_driven_by_first_content_commit():
    src = _src()
    assert "onPageCommitVisible" in src, "正常撤场信号必须是首帧内容已提交"
    assert "view.postOnAnimation(MainActivity.this::revealWebView)" in src, (
        "撤场要延到下一个动画帧，确保内容帧已提交"
    )
    assert "splashLayout.postDelayed" not in src, "不得再用 loadUrl 后的固定定时器撤 splash"
    assert "}, 200);" not in src


def test_commit_callback_only_reveals_the_local_server_page():
    src = _src()
    assert "if (isServerReady && isLocalServerUrl(url))" in src
    assert "url.startsWith(serverBaseUrl(serverPort))" in src
    assert "serverPort > 0 && url != null" in src, "端口必须来自端口文件，不能猜 8000"


def test_reveal_is_idempotent_and_has_no_timer():
    body = _reveal_body()
    # S1 起壳阶段 WebView 恒为 VISIBLE（GONE 会停绘制、rAF 不回调），幂等键改为「splash 是否已撤」。
    assert "splashLayout.getVisibility() != View.VISIBLE" in body, "重复回调必须安全"
    assert "splashLayout.setVisibility(View.GONE)" in body
    assert "webView.setVisibility(View.VISIBLE)" in body
    assert "postDelayed" not in body
    assert "sleep" not in body


def test_failure_path_keeps_splash_and_visible_error():
    src = _src()
    assert "statusTextView.setTextIsSelectable(true)" in src, "fatalError 必须可选中"
    assert "splashLayout.setVisibility(View.VISIBLE)" in src, "失败时 splash 必须回到前台"
    assert "webView.setVisibility(View.GONE)" in src
    assert "请用 adb logcat 查看 python.stderr" in src


def test_page_finished_is_only_an_event_based_fallback():
    src = _src()
    assert "onPageFinished" in src
    # 兜底也必须是事件驱动、且只在服务就绪后；不能重新引入计时器。
    finished = src.split("public void onPageFinished", 1)[1].split("\n            }", 1)[0]
    assert "if (isServerReady)" in finished
    assert "revealWebView();" in finished
    assert "postDelayed" not in finished
