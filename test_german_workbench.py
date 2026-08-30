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


def test_backup_covers_workbench_state():
    """DeLector 备份必须带上 workbench 的 wb.* 键，否则「还原备份」后
    684 词的进度还留在 localStorage 里，用户以为整体替换了其实没有；
    跨设备迁移也会静默丢掉全部学习进度。"""
    from pathlib import Path
    cards = (Path(__file__).parent / "static" / "js" / "cards.js").read_text(encoding="utf-8")
    fn = cards.split("function backupLocalStorageKeys")[1].split("function ")[0]
    has_literal = '"wb."' in fn or "'wb.'" in fn or "'wb." in fn or '"wb.' in fn
    has_constant = "BACKUP_LS_WORKBENCH_PREFIX" in fn
    assert has_literal or has_constant, "备份键收集必须含 wb. 前缀"


# ── v4.6.1 回归：共享 <audio> 单例上的两个异步陷阱 ─────────────────────

def _playword_cleanup_block():
    """playWord 入口那段「停掉上一次播放」的互斥清理（到 finalResolve 为止）。"""
    body = _WORKBENCH.split("function playWord(hw, opts)")[1]
    return body.split("互斥：立即停掉上一次播放")[1].split("const finalResolve")[0]


def _tts_shared_audio_blocks():
    """共用全局 _ttsAudio 单例的两条链路。**不含 trySpeech** —— 它走
    speechSynthesis、不碰 _ttsAudio，attempt 守卫对它没有意义。"""
    server = _WORKBENCH.split("const tryServer")[1].split("const trySpeech")[0]
    online = _WORKBENCH.split("const tryOnline")[1].split("主调用链（server TTS 优先")[0]
    assert "_ttsAudio.src =" in server and "_ttsAudio.src =" in online, "切片没落在音频链路上"
    return {"tryServer": server, "tryOnline": online}


def test_playword_cleanup_does_not_reload_audio():
    """入口清理不得调 load()：removeAttribute('src') 之后再 load() 会给 <audio>
    **排一个异步 error 事件**，它在当前同步块跑完后才派发，正好命中同一 tick 里
    刚装上的 tryServer.onerror —— 首次点击于是被自己的清理判成 audio-error 而无声
    （v4.6.1 修的第一个根因）。pause() / removeAttribute 是同步的，不排事件。"""
    block = _playword_cleanup_block()
    # 先确认切到的确实是那段清理（否则下面的否定断言在空串上恒真）
    assert "_ttsAudio.pause()" in block, "切片没落在入口清理块上"
    assert "removeAttribute('src')" in block, "切片没落在入口清理块上"
    assert ".load()" not in block, "入口清理不能调 load()：会排一个异步 error 事件"


def test_every_shared_audio_handler_guards_attempt_id():
    """_ttsAudio 是 tryServer/tryOnline 共用的全局单例，per-attempt 的 settled
    闭包管不住**上一次**尝试的回调：旧 timer 醒来会 pause() + 清 src 掐掉新播放，
    旧 onplaying 又把新尝试判成已 settled —— 连点于是交叉干扰、重复出声
    （v4.6.1 修的第二个根因）。所以每个异步回调开头都必须比对 attempt 身份。"""
    openers = (
        "_ttsAudio.onerror = () => {",
        "_ttsAudio.onplaying = () => {",
        "setTimeout(() => {",
        "p.catch((err) => {",
    )
    per_chain = {}
    for chain, src in _tts_shared_audio_blocks().items():
        found = 0
        for opener in openers:
            start = 0
            while True:
                i = src.find(opener, start)
                if i < 0:
                    break
                start = i + len(opener)
                found += 1
                head = src[start:start + 160]
                assert "myAttempt !== _ttsAttemptId" in head, (
                    f"{chain} 里的回调 {opener!r}（块内偏移 {i}）开头缺 attempt 守卫，"
                    "stale handler 会去动共享的 _ttsAudio"
                )
        per_chain[chain] = found
    # 只钉下界：每条链至少 3 个异步回调（当前 server 4 / online 4）。
    # 数到 0 说明切片跑偏，否定式的守卫断言就会在空串上恒真。
    for chain, n in per_chain.items():
        assert n >= 3, f"{chain} 里只找到 {n} 个异步回调，切片可能跑偏了"
    # myAttempt 必须在两条链路定义之前就绑定好
    assert _WORKBENCH.index("const myAttempt = ++_ttsAttemptId") < _WORKBENCH.index("const tryServer")


# ── v4.6.6 β 契约：pickDeVoice 三级优先 + trySpeech 离线兜底 ──────────────

def _pick_de_voice_body():
    """pickDeVoice 函数体（不含签名行）。"""
    body = _WORKBENCH.split("function pickDeVoice()")[1].split("\nfunction ")[0]
    assert "de-DE" in body or "de[-_]DE" in body, "切片没落在 pickDeVoice 里"
    return body


def test_pick_de_voice_has_three_tier_fallback():
    """pickDeVoice 必须有三级优先：de-DE 原生 → 任何 de 开头 → voices[0] 最终兜底。

    国内 Android 机型多数没有 Google TTS 德语语音包，第三级是离线场景下
    trySpeech 唯一能出声的路径（用非德语语音念德语词，发音不准但至少有声）。
    删掉第三级 = 离线无网时静默无声，这条断言会变红。

    变异验证（手工）：把 return voices[0] 改成 return null → 断言红 ✓
    """
    body = _pick_de_voice_body()
    # 第一级：de-DE 区域匹配（用正则）
    assert "de[-_]DE" in body or "/de[-_]DE/" in body, "第一级：缺 de-DE 原生语音检测"
    # 第二级：任意 de 开头
    assert "de[-_]?" in body or "/^de" in body, "第二级：缺 de-* 泛德语检测"
    # 第三级：voices[0] 最终兜底（国内无德语语音时仍能出声）
    assert "return voices[0]" in body, (
        "第三级兜底缺失：无德语语音时 pickDeVoice 会返回 null，"
        "trySpeech 走 no-de-voice 路径静默无声。"
        "国内 Android 机型离线场景依赖这条 voices[0] 兜底。"
    )


def test_try_speech_handles_no_voice_explicitly():
    """trySpeech 在 pickDeVoice 返回 null 时必须走 no-de-voice 显式拒绝，
    而不是让后续代码对 null 抛 TypeError（静默失败或崩溃）。

    仅在 voices 列表本身为空（voiceschanged 尚未触发）时才会命中这条；
    只要 voices 非空，pickDeVoice 第三级兜底确保不会返回 null。
    """
    block = _WORKBENCH.split("const trySpeech")[1].split("const tryOnline")[0]
    assert "no-de-voice" in block, "trySpeech 缺少 no-de-voice 显式错误路径"
    # 确认是在 !voice 检查里返回，而不是直接用 voice 造成 TypeError
    voice_check_pos = block.find("if (!voice)")
    no_voice_pos = block.find("no-de-voice")
    assert voice_check_pos >= 0, "trySpeech 必须有 if (!voice) 守卫"
    assert voice_check_pos < no_voice_pos, "no-de-voice 必须在 if (!voice) 守卫内"


# ── v4.6.6 α 契约：EMBEDDED_AUDIO 嵌入音频词表 ─────────────────────────────

def test_embedded_audio_dict_declared_before_playword():
    """EMBEDDED_AUDIO 字典必须在 playWord 函数之前声明。

    playWord 入口立即检测 EMBEDDED_AUDIO[word]（最高优先级路径），
    声明在后面会导致 ReferenceError（或静默拿到 undefined 跳过内嵌路径）。

    变异验证：把 const EMBEDDED_AUDIO 移到 function playWord 之后 → 断言红 ✓
    """
    ea_pos = _WORKBENCH.index("const EMBEDDED_AUDIO")
    pw_pos = _WORKBENCH.index("function playWord(")
    assert ea_pos < pw_pos, (
        "EMBEDDED_AUDIO 必须声明在 playWord 之前，"
        "否则 playWord 入口无法访问它"
    )


def test_embedded_audio_lookup_uses_lowercase():
    """playWord 查 EMBEDDED_AUDIO 时必须做 toLowerCase() 归一。

    CORE_VOCAB_DB 的键全部小写，但 stripDeArticle 保留原始大小写
    （`die Adresse` → `Adresse` 仍大写）。不归一则名词永远查不到。

    修复：查词前 const embeddedKey = word.toLowerCase()，之后用 embeddedKey 查。

    变异验证：把 word.toLowerCase() 删掉 → 断言红 ✓
    """
    # 取 playWord 函数体内、tryServer 定义之前的 EMBEDDED_AUDIO 处理块
    pw_body = _WORKBENCH.split("function playWord(hw, opts)")[1].split("const tryServer")[0]
    # 区块必须有 EMBEDDED_AUDIO 查词（否则切片跑偏）
    assert "EMBEDDED_AUDIO" in pw_body, "切片未落在 playWord 的 EMBEDDED_AUDIO 检测区"
    # 必须用 toLowerCase() 归一（变量名不限，只要 .toLowerCase() 在查词前）
    lower_pos = pw_body.find("toLowerCase()")
    ea_check_pos = pw_body.find("EMBEDDED_AUDIO[")
    assert lower_pos >= 0, (
        "EMBEDDED_AUDIO 查词必须做 word.toLowerCase() 归一，"
        "否则名词（大写首字母）永远查不到嵌入音频。"
    )
    assert lower_pos < ea_check_pos, (
        "toLowerCase() 必须在 EMBEDDED_AUDIO[...] 查词之前（先归一再查）"
    )


def test_embedded_audio_build_script_exists_with_dry_run():
    """tools/build_embedded_audio.py 必须存在且支持 --dry-run 模式。

    build script 负责批量调用 edge-tts 生成 MP3 并输出 EMBEDDED_AUDIO 片段。
    --dry-run 模式只列词不调 edge-tts，让 CI 和测试无需联网即可验证脚本可 import。

    （本测试当前应红，是 TDD 红阶段——脚本尚未创建）
    """
    from pathlib import Path
    script = Path(__file__).parent / "tools" / "build_embedded_audio.py"
    assert script.exists(), (
        "tools/build_embedded_audio.py 尚未创建。"
        "该脚本负责批量生成 EMBEDDED_AUDIO 词典片段。"
    )
    src = script.read_text(encoding="utf-8")
    assert "--dry-run" in src, "build script 必须支持 --dry-run（CI/测试无需真调 edge-tts）"
