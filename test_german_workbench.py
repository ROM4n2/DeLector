"""German workbench 集成的静态契约。

三层钉子：
1. workbench.html 自身的音频补丁（tryServer 优先于 tryOnline、走 GET 端点、
   file:// 下跳过、iframe 里跳过 PWA）
2. DeLector 外壳的接入（view-german + iframe + nav tab + dock button）
3. server.py 的 GET /api/audio/tts 端点存在性

与 test_prep_matrix.py 前端段同款模式：源码字符串匹配，不渲染 DOM。
本仓库教训：静态断言必须能被「回退实现」打破 —— 每条断言都切成
尽可能窄的作用域（函数体内/块内），不做整文件级别的模糊匹配。
"""
from pathlib import Path

_ROOT = Path(__file__).parent
_WORKBENCH = (_ROOT / "static" / "german" / "workbench.html").read_text(encoding="utf-8")
_INDEX = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
_CSS = (_ROOT / "static" / "style.css").read_text(encoding="utf-8")
_SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")


def test_workbench_has_server_tts_priority():
    """tryServer 必须在 tryOnline 之前定义（playWord 内 server 优先于在线链）。"""
    server_pos = _WORKBENCH.index("const tryServer")
    online_pos = _WORKBENCH.index("const tryOnline")
    assert server_pos < online_pos, "tryServer 必须定义在 tryOnline 之前"


def test_server_tts_uses_get_endpoint():
    """tryServer 走 <audio src> + GET 查询串，不走 fetch + blob。"""
    block = _WORKBENCH.split("const tryServer")[1].split("const tryOnline")[0]
    assert "/api/audio/tts?text=" in block, "server TTS 必须用 GET 查询串 URL"
    assert "fetch(" not in block, "server TTS 不应走 fetch（<audio src> 直接用即可）"


def test_server_tts_skipped_off_http():
    """file:// / content:// 下跳过 server TTS（零延迟，不等 6s 超时）。"""
    assert "_ttsServerReachable" in _WORKBENCH
    assert "location.protocol.startsWith('http')" in _WORKBENCH


def test_pwa_guarded_in_iframe():
    """嵌入 iframe 时 setupPWA 直接 return（Blob URL SW 在同源 iframe 注册必败）。"""
    block = _WORKBENCH.split("(function setupPWA()")[1][:400]
    assert "window.frameElement" in block


def test_engine_select_has_server_option():
    """设置页 TTS 引擎下拉有 DeLector 服务端选项。"""
    block = _WORKBENCH.split('id="setTtsEngine"')[1].split("</select>")[0]
    assert 'value="server"' in block


def test_workbench_data_intact():
    """搬运完整性：684 词种子数据与 playWord 主函数还在。"""
    assert "const SEED_WORDS" in _WORKBENCH
    assert "function playWord" in _WORKBENCH


def test_view_german_embeds_workbench():
    """DeLector 有 view-german，内含指向 workbench 的 iframe + autoplay 许可。"""
    block = _INDEX.split('id="view-german"')[1].split("</main>")[0]
    assert 'src="/german/workbench.html"' in block
    assert "autoplay" in block


def test_nav_and_dock_wired_to_german():
    """桌面 nav + 移动 dock 都有背词入口，且 dock 按钮在 settings 之前。"""
    assert 'id="nav-btn-german"' in _INDEX
    assert 'id="mob-btn-german"' in _INDEX
    assert _INDEX.index('id="mob-btn-german"') < _INDEX.index('id="mob-btn-settings"')


def test_german_view_css_scoped_to_active():
    """display 规则必须挂在 .active 上：裸 #view-german { display:flex } 的
    specificity (1,0,0) 会压过 .view { display:none } (0,1,0)，视图失去开关。"""
    # 取第一个 @media (max-width: 1024px) 之前的桌面段（该 view 规则在 436 行，
    # 早于首个 768px 媒体查询，所以按 1024px 切更贴近这段代码的实际位置）
    desktop_block = _CSS.split("@media (max-width: 1024px)")[0]
    assert "#view-german.active" in desktop_block
    assert "#view-german {" not in desktop_block, "桌面段 display 规则必须挂在 .active 上，不能裸用 #view-german"
    assert "#view-german iframe" in _CSS
    assert "min-height: 0" in _CSS


def test_mobile_dock_offset_for_german_view():
    """移动端 iframe 高度必须显式扣掉 sticky nav + fixed dock，否则 dock 盖住
    工作台底部按钮（评审 fix-first 项）。"""
    media_pos = _CSS.index("@media (max-width: 1024px)")
    block = _CSS[media_pos:]
    rule = block.split("#view-german.active")[1].split("}")[0]
    assert "calc(" in rule and "100dvh" in rule, "移动端高度必须显式计算"
    assert "safe-area-inset-bottom" in rule, "必须处理刘海屏安全区"


def test_get_audio_tts_route_registered():
    """server.py 有 GET /api/audio/tts 路由（区别于既有 POST 的函数名）。"""
    assert '@app.get("/api/audio/tts")' in _SERVER
    assert "async def audio_tts_get(" in _SERVER
