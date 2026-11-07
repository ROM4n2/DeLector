# -*- coding: utf-8 -*-
r"""前端端口守卫：static/ 不得出现硬编码的绝对服务地址。

⚠️ 这是结构守卫（文本结构断言），不是运行时行为测试
--------------------------------------------------
本仓没有 JS 测试基建，本文件只能断言“请求地址是相对路径”这一代码形状，
不能证明真实浏览器里的请求确实落在当前端口。真实验收仍靠 HITL。

为什么需要它
------------
桌面端 8000 被占用时会顺延到 8002–8010（`start.py` 的 `PORT_CANDIDATES`）。
浏览器里的页面由同一个 FastAPI 服务托管，请求必须走相对路径（`/api/...`）；
一旦有人写出 `http://127.0.0.1:8000/api/...`，端口顺延后页面就会朝一个不存在的
服务发请求，等于自断连接。

钉住什么
--------
1. `static/**` 下任何“协议 + 主机 + 字面端口 + `/api`”的 URL 字面量 → 红；
2. `static/js/**` 下任何“http(s):// + 回环主机 + 字面端口”的字符串 → 红
   （同源场景回环绝对地址恒错；Android WebView 的服务地址由宿主注入）；
3. 统一请求出口 `core.js:api()` 必须把 URL 原样交给 fetch，不得自行拼 origin/base。

刻意不覆盖的边界（避免把文案误判成连接地址）
------------------------------------------
- 帮助文案与输入框占位符里的示例地址（如 `http://192.168.1.5:8000`）不是请求；
- `python -m http.server 8000`、`adb reverse tcp:8000` 是第三方/Android 固定端口说明；
- 跨端配对的动态拼接（`"http://" + pair.host + "/api/wb/state"`）主机来自运行时输入。

变异自证
--------
- 在 `static/js/core.js` 把 `fetch(url` 改成 `fetch("http://127.0.0.1:8000" + url)`
  ⇒ 用例 1/2/3 立即转红；
- 在 `static/js/` 新增 `const BASE = "http://localhost:8000";` ⇒ 用例 2 转红；
- 在任意 `static/` 文件写 `const X = "http://192.168.1.5:8000/api/x";` ⇒ 用例 1 转红。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

_ABS_API_WITH_PORT = re.compile(
    r"(?:https?:)?//[^\s\"'`<>()]+?:\d{2,5}[^\s\"'`<>()]*?/api(?:/|\b)"
)
_LOOPBACK_ORIGIN_WITH_PORT = re.compile(
    r"(?:https?:)?//(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]):\d{2,5}\b",
    re.IGNORECASE,
)

_SCAN_SUFFIXES = (".js", ".mjs", ".html")


def _frontend_files():
    for path in sorted(STATIC.rglob("*")):
        if path.is_file() and path.suffix in _SCAN_SUFFIXES:
            yield path


def _hits(pattern: re.Pattern, files):
    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    return hits


def test_static_has_no_absolute_api_url_with_literal_port():
    hits = _hits(_ABS_API_WITH_PORT, _frontend_files())
    assert not hits, (
        "static/ 里出现了带字面端口的绝对 API 地址；浏览器同源请求必须用相对路径"
        "（/api/...），否则端口顺延后会打到不存在的服务：\n" + "\n".join(hits)
    )


def test_static_js_has_no_loopback_origin_with_literal_port():
    js_files = [p for p in _frontend_files() if p.suffix in (".js", ".mjs")]
    hits = _hits(_LOOPBACK_ORIGIN_WITH_PORT, js_files)
    assert not hits, (
        "static/js/ 里出现了带字面端口的回环绝对地址；同源请求必须用相对路径，"
        "Android WebView 的服务地址由宿主注入：\n" + "\n".join(hits)
    )


def test_api_wrapper_forwards_url_unchanged():
    core = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
    match = re.search(r"export async function api\(url, opts = \{\}\) \{(.+?)\n\}", core, re.S)
    assert match, "core.js:api() 的实现形状变了，请同步更新守卫"
    body = match.group(1)
    assert "fetch(url," in body, "api() 必须把调用方给的 URL 原样交给 fetch"
    assert "http://" not in body and "https://" not in body, (
        "api() 不得硬编码协议/主机；同源请求一律由调用方传相对路径"
    )
    assert "location.origin" not in body and "location.host" not in body, (
        "api() 不得自行拼 origin/host；否则 Android 与端口顺延场景会再次错位"
    )
