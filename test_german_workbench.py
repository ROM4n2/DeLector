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
import json
import re
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
    """搬运完整性：682 词种子数据与 playWord 主函数还在。"""
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
    682 词的进度还留在 localStorage 里，用户以为整体替换了其实没有；
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


# ── 核心词模式契约：CORE_WORD_SEED_IDS / CORE_CUSTOM_WORDS（Task 0） ───────

def _slice_balanced(text, start_idx, open_ch, close_ch):
    """从 start_idx 起找第一个 open_ch，返回到其配对 close_ch 的闭合切片。

    只做括号计数（种子/核心词常量里没有含括号的字符串字面量），
    目的是让测试真正解析常量内容，而不是做整文件模糊字符串匹配。
    """
    begin = text.index(open_ch, start_idx)
    depth = 0
    for i in range(begin, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[begin:i + 1]
    raise AssertionError("括号未闭合：%s ... %s" % (open_ch, close_ch))


def _core_seed_ids():
    decl = "const CORE_WORD_SEED_IDS"
    assert decl in _WORKBENCH, "workbench.html 缺少 CORE_WORD_SEED_IDS 常量"
    at = _WORKBENCH.index(decl)
    head = _WORKBENCH[at:at + 120]
    assert "new Set(" in head, "CORE_WORD_SEED_IDS 必须是 new Set([...])（O(1) 查表）"
    return json.loads(_slice_balanced(_WORKBENCH, at, "[", "]"))


def _core_custom_words():
    decl = "const CORE_CUSTOM_WORDS"
    assert decl in _WORKBENCH, "workbench.html 缺少 CORE_CUSTOM_WORDS 常量"
    at = _WORKBENCH.index(decl)
    return json.loads(_slice_balanced(_WORKBENCH, at, "[", "]"))


def test_core_words_constants_declared_before_seed():
    """两个核心词常量必须声明在 SEED_WORDS 之前（初始化时按序可见）。"""
    seed_at = _WORKBENCH.index("const SEED_WORDS")
    assert _WORKBENCH.index("const CORE_WORD_SEED_IDS") < seed_at, (
        "CORE_WORD_SEED_IDS 必须声明在 const SEED_WORDS 之前"
    )
    assert _WORKBENCH.index("const CORE_CUSTOM_WORDS") < seed_at, (
        "CORE_CUSTOM_WORDS 必须声明在 const SEED_WORDS 之前"
    )


def test_core_word_seed_ids_are_213_real_seed_ids():
    """CORE_WORD_SEED_IDS 恰好 213 个、无重复，且每个 id 都真在 SEED_WORDS 里。

    变异验证：删任一 id → 长度断言红；把 id 写错一位 → 存在性断言红。
    """
    ids = _core_seed_ids()
    assert len(ids) == 213, "CORE_WORD_SEED_IDS 应为 213 个 id，实际 %d" % len(ids)
    assert len(set(ids)) == 213, "CORE_WORD_SEED_IDS 有重复 id"
    assert all(re.fullmatch(r"a1-\d{4}", i) for i in ids), "id 格式必须是 a1-NNNN"
    # 人工确认的 2 个模糊匹配必须在列（211 精确 + 2 模糊 = 213）
    assert "a1-0473" in ids, "缺少人工确认的模糊匹配 a1-0473（Partnerin）"
    assert "a1-0603" in ids, "缺少人工确认的模糊匹配 a1-0603（übernachten）"
    # 每个 id 必须真存在于 SEED_WORDS —— 挡住拼错/幻觉 id
    seed_ids = set(re.findall(r'"id":"(a1-\d{4})"', _WORKBENCH))
    assert seed_ids, "未从 SEED_WORDS 解析出任何种子词 id（切片跑偏）"
    missing = sorted(set(ids) - seed_ids)
    assert not missing, "这些核心词 id 不存在于 SEED_WORDS：%s" % missing


def test_core_custom_words_are_22_wellformed_new_words():
    """CORE_CUSTOM_WORDS 恰好 22 个新词，字段齐全、id 连号、不与种子词撞 id。

    22 = 24 个未匹配词剔除 `mit Karte`（短语）与 `aufmachen`（假阳性）。
    变异验证：漏字段/漏 core tag/id 改重 → 断言红。
    """
    words = _core_custom_words()
    assert len(words) == 22, "CORE_CUSTOM_WORDS 应为 22 个词，实际 %d" % len(words)

    expected_ids = ["core-%03d" % n for n in range(1, 23)]
    assert [w["id"] for w in words] == expected_ids, "id 必须是 core-001..core-022 连号"

    seed_ids = set(re.findall(r'"id":"(a1-\d{4})"', _WORKBENCH))
    for w in words:
        wid = w["id"]
        assert wid not in seed_ids, "%s 与种子词 id 冲突" % wid
        for field in ("hw", "pos", "gloss", "ipa", "ex", "letter", "page", "tags", "custom"):
            assert field in w, "%s 缺字段 %s" % (wid, field)
        assert w["hw"].strip(), "%s 的 hw 为空" % wid
        assert w["gloss"].strip(), "%s 的 gloss 为空" % wid
        assert w["ipa"].strip(), "%s 的 ipa 为空（不得留空/编造）" % wid
        assert w["tags"] == ["core"], "%s 的 tags 必须是 ['core']" % wid
        assert w["custom"] is True, "%s 的 custom 必须为 true" % wid
        assert w["page"] == 0, "%s 的 page 必须为 0（非教材页）" % wid
        assert isinstance(w["ex"], list) and w["ex"], "%s 必须有至少一条例句" % wid
        for ex in w["ex"]:
            assert ex.get("de", "").strip() and ex.get("zh", "").strip(), (
                "%s 的例句必须 de/zh 齐全" % wid
            )
        # letter = 去冠词后首字母大写
        bare = re.sub(r"^(der|die|das)\s+", "", w["hw"])
        assert w["letter"] == bare[0].upper(), (
            "%s 的 letter 应为去冠词后首字母 %s，实际 %s" % (wid, bare[0].upper(), w["letter"])
        )

    # 明确排除的两个词不得出现
    heads = {w["hw"] for w in words}
    assert "mit Karte" not in heads, "`mit Karte` 是短语，不应进核心词表"
    assert not any(h.endswith("aufmachen") for h in heads), "`aufmachen` 是假阳性，应剔除"


def test_core_custom_words_headwords_match_source_export():
    """22 个新词的 hw/gloss/ipa 必须与 A1 导出词库一致（不得编造）。

    源文件缺失时跳过（该 JSON 不在仓库内），存在时逐字段对齐。
    """
    src = Path("d:/Ran/Goethe_A1/delector_custom_words.json")
    if not src.exists():
        import pytest
        pytest.skip("源词库 %s 不存在，跳过对源校验" % src)
    raw = json.loads(src.read_text(encoding="utf-8"))
    by_hw = {w["hw"]: w for w in raw.get("customWords", [])}
    for w in _core_custom_words():
        origin = by_hw.get(w["hw"])
        assert origin, "%s（%s）在源词库中找不到，疑似编造" % (w["id"], w["hw"])
        assert w["gloss"] == origin["gloss"], "%s gloss 与源不一致" % w["id"]
        assert w["ipa"] == origin["ipa"], "%s ipa 与源不一致" % w["id"]
        assert w["pos"] == origin["pos"], "%s pos 与源不一致" % w["id"]


# ── 核心词模式契约：初始化打 core tag + 新词注入（Task 1） ─────────────────

def _load_all_body():
    """loadAll 函数体（到下一个顶层 function 为止）。"""
    body = _WORKBENCH.split("function loadAll()")[1].split("\nfunction ")[0]
    assert "SEED_WORDS.map(" in body, "切片没落在 loadAll 上（找不到种子建表）"
    return body


def _seed_init_block():
    """loadAll 里「localStorage 无词表 → 用 SEED_WORDS 建表」那个分支体。

    上界是 `if (!Array.isArray(S.words))` 守卫，下界是该分支内的 saveWords()。
    切这么窄是为了让断言不能被「写在 if 外面」的实现骗过去：
    分支外的注入每次加载都会重复追加词，切片里看不到就红。
    """
    body = _load_all_body()
    assert "if (!Array.isArray(S.words))" in body, "loadAll 缺少种子建表守卫"
    block = body.split("if (!Array.isArray(S.words))")[1].split("saveWords();")[0]
    assert "SEED_WORDS.map(" in block, "切片没落在种子建表分支上"
    return block


def test_core_tag_applied_during_seed_init():
    """种子建表时按 CORE_WORD_SEED_IDS 打 core tag，而不是无条件 tags: []。

    tag 是核心词模式唯一的运行时身份来源（词表过滤 / 复习队列 / 统计都读它），
    这里不打，后面所有 scope 过滤都会筛出 0 个词。

    变异验证：把 tags 改回 `tags: []` → 两条断言同时红。
    """
    block = _seed_init_block()
    assert re.search(r"tags:\s*CORE_WORD_SEED_IDS\.has\(w\.id\)\s*\?", block), (
        "种子词的 tags 必须按 CORE_WORD_SEED_IDS.has(w.id) 判定"
    )
    assert re.search(r"\?\s*\[\s*['\"]core['\"]\s*\]", block), (
        "命中核心词 id 时 tags 必须是 ['core']"
    )
    assert not re.search(r"tags:\s*\[\s*\]", block), (
        "种子词 tags 不得无条件置空（无条件 tags: [] 会抹掉核心词身份）"
    )


def test_core_custom_words_injected_during_seed_init():
    """22 个核心新词必须在种子建表分支内、map 之后注入，且只注入一次。

    三条不变量：
      1. 在 `!Array.isArray(S.words)` 分支内 —— 写在分支外则每次加载重复追加 22 词；
      2. 在 SEED_WORDS.map 之后 —— 先建表再追加；
      3. 整个 loadAll 里只出现一次 —— 挡住「顺手多写一处」的重复注入。

    变异验证：把 push 移到 saveWords() 之后 / 分支外 → 断言 1 红；
              复制一份 push → 断言 3 红。
    """
    block = _seed_init_block()
    assert "CORE_CUSTOM_WORDS" in block, (
        "核心新词必须在种子建表分支内注入 S.words（写在分支外会每次加载重复追加）"
    )
    assert block.index("SEED_WORDS.map(") < block.index("CORE_CUSTOM_WORDS"), (
        "核心新词必须在 SEED_WORDS.map 建表之后追加"
    )
    assert _load_all_body().count("CORE_CUSTOM_WORDS") == 1, (
        "loadAll 里只能注入一次 CORE_CUSTOM_WORDS"
    )
    push = block[block.index("CORE_CUSTOM_WORDS"):]
    assert re.search(r"S\.words\.push\(|S\.words\s*=\s*S\.words\.concat\(", block), (
        "核心新词必须真的进 S.words（push / concat）"
    )
    assert re.search(r"\{\s*\.\.\.\s*w\b", push), (
        "必须展开复制成新对象，不能把 CORE_CUSTOM_WORDS 里的对象引用直接塞进 S.words"
        "（否则用户编辑核心词会改到常量本身）"
    )


# ── 核心词模式契约：已有用户数据幂等补 core tag + 缺失核心新词注入（Task 7） ─

def _backfill_function_body():
    """backfillCoreWords 函数体（定义到下一个顶层 function 为止）。"""
    assert "function backfillCoreWords(" in _WORKBENCH, "缺少 backfillCoreWords 函数定义"
    body = _WORKBENCH.split("function backfillCoreWords(")[1].split("\nfunction ")[0]
    return body


def test_core_backfill_defined_outside_loadAll():
    """backfillCoreWords 必须定义在 loadAll 外部，否则 CORE_CUSTOM_WORDS 在 loadAll 内出现两次，破坏既有计数断言。

    现有 test_core_custom_words_injected_during_seed_init 用 _load_all_body().count('CORE_CUSTOM_WORDS') == 1
    把注射逻辑钉在种子分支内；backfill 作为对老用户的补偿必须独立在外。
    变异验证：把函数整个挪进 loadAll 末尾 → 本断言红，且上述计数断言也红。
    """
    load_all_body = _load_all_body()
    assert "backfillCoreWords" not in load_all_body, (
        "backfillCoreWords 不得定义在 loadAll 函数体内"
    )
    assert "function backfillCoreWords(" in _WORKBENCH, "缺少 backfillCoreWords 函数定义"


def test_core_backfill_retags_only_missing_core_seed_tags():
    """对已有 S.words 幂等补 core tag：只处理 SEED 核心词，且仅当尚未带 core 时才 push。

    老用户 S.words 里 682 词可能全未打 tag；二次运行若不加 guard 会重复 push。
    变异验证：把 !w.tags.includes('core') guard 删掉 → 本断言红；
              把判定集合换成 CORE_CUSTOM_WORDS → 第一条断言红。
    """
    body = _backfill_function_body()
    assert "CORE_WORD_SEED_IDS.has(w.id)" in body, (
        "必须按 CORE_WORD_SEED_IDS.has(w.id) 判定哪些种子词需要 core tag"
    )
    guard = re.search(r"if\s*\(\s*!w\.tags\.includes\(\s*['\"]core['\"]\s*\)\s*\)", body)
    assert guard, "必须检查 core tag 不存在才添加，否则二次运行会重复 push 丧失幂等性"
    push = body.index('w.tags.push("core")')
    assert guard.start() < push, "core tag 的缺失检查必须在 push 之前"


def test_core_backfill_injects_missing_custom_words_idempotently():
    """已有词表缺少的 22 个核心新词，按 id 查重后展开注入。

    变异验证：去掉 !existingIds.has(cw.id) guard → 本断言红；
              不写 { ...cw } 展开 → 最后一条断言红。
    """
    body = _backfill_function_body()
    assert "CORE_CUSTOM_WORDS" in body, "必须引用 CORE_CUSTOM_WORDS 作为注入源"
    guard = re.search(r"if\s*\(\s*!existingIds\.has\(\s*cw\.id\s*\)\s*\)", body)
    assert guard, "必须按 id 判重后才注入，否则每次加载都会重复追加 22 词"
    push = body.index("S.words.push(")
    assert guard.start() < push, "id 判重必须在 push 之前"
    assert re.search(r"\{\s*\.\.\.\s*cw\b", body), (
        "必须展开复制新对象，不能把 CORE_CUSTOM_WORDS 里的引用直接塞进 S.words"
    )


def test_core_backfill_does_not_touch_fsrs_progress():
    """补 tag / 注入新词必须零触碰 FSRS 进度（cards/log/wrong）。

    变异验证：在 backfill 里加一行 S.cards = {} → 本断言红。
    """
    body = _backfill_function_body()
    for var in ("S.cards", "S.log", "S.wrong"):
        assert var not in body, "backfillCoreWords 不得引用 %s" % var


def test_core_backfill_writes_only_when_changed():
    """backfillCoreWords 返回 changed 布尔值；调用处仅在 true 时 saveWords，避免每次启动都写存储。

    变异验证：return changed 改成 return true → 调用处断言仍可绿，但「return changed」断言红；
              调用处改成裸 backfillCoreWords(); saveWords(); → 第二条断言红。
    """
    body = _backfill_function_body()
    assert re.search(r"\breturn\s+changed\s*;", body), (
        "backfillCoreWords 必须返回 changed 布尔值"
    )
    # 同步启动路径
    startup = _WORKBENCH.split("loadAll();")[1].split("(async () => {")[0]
    assert "if (backfillCoreWords()) saveWords();" in startup, (
        "同步启动后必须以 if (backfillCoreWords()) saveWords() 形式调用"
    )


def test_core_backfill_runs_after_idb_hydration():
    """IDB hydration 完成后会重新 loadAll；backfill 必须紧接其后，防止异步覆盖把 core tag 冲掉。

    现有启动序列：await idbHydrate() → if (updated) { loadAll(); ... }。
    如果 backfill 只写在同步启动处，IDB 更新后的 S.words 仍是旧数据，核心模式对老用户保持沉默。
    变异验证：把 if (backfillCoreWords()) saveWords(); 从 updated 分支里删掉 → 断言红。
    """
    async_block = _WORKBENCH.split("(async () => {")[1].split("})();")[0]
    updated_branch = async_block.split("if (updated) {")[1].split("console.log")[0]
    assert "loadAll();" in updated_branch, "切片没落在 hydration 后的更新分支上"
    assert "if (backfillCoreWords()) saveWords();" in updated_branch, (
        "IDB 更新后重新 loadAll 必须接幂等 backfill"
    )


# ── 核心词模式契约：词表视图 scope 过滤（Task 2） ───────────────────────────

def _words_toolbar():
    """词库视图 toolbar 区段（`#view-words` 开头 → `#wCount` 提示行为止）。

    切这么窄是为了让「把控件写到别的视图 / 写在表格下面」骗不过断言。
    """
    marker = '<section class="view" id="view-words">'
    assert marker in _WORKBENCH, "找不到词库视图 section"
    block = _WORKBENCH.split(marker)[1].split('id="wCount"')[0]
    assert 'id="wTag"' in block, "切片没落在词库视图 toolbar 上"
    return block


def _words_filter_predicate():
    """renderWords 里 `S.words.filter(` 的谓词体（到 #wCount 计数赋值为止）。

    只认谓词体内的 scope 检查 —— 写在 filter 之后再 slice/标记颜色的实现
    不会让 #wCount 与表格行数变化，切片里看不到就红。
    """
    body = _WORKBENCH.split("function renderWords()")[1].split("\nfunction ")[0]
    assert "S.words.filter(" in body, "renderWords 里找不到词表过滤"
    pred = body.split("S.words.filter(")[1].split('$("wCount")')[0]
    assert "wordFilters.tag" in pred, "切片没落在 renderWords 的过滤谓词上"
    return pred


def _words_filter_listener():
    """词表 filter 控件的事件绑定块（`["wSearch", ...].forEach`）。"""
    m = re.search(r'\[\s*"wSearch".*?\]\.forEach\(id\s*=>\s*\{.*?\n\}\);', _WORKBENCH, re.S)
    assert m, "找不到词表 filter 控件的事件绑定块"
    return m.group(0)


def test_scope_control_is_globally_single():
    """scope 切换控件全局只有一个，就是顶栏的 #scopeSeg。

    迁移自 test_core_scope_toggle_in_words_toolbar（原来钉词库 toolbar 里那个
    scope 下拉 select）。ADR-0002 Task 2 把那个 select 删了：同一状态两个
    写入口就得双向同步，漏一处就出现「顶栏显示核心、词库下拉显示全部」。
    与 Task 1 的 test_scope_segment_has_both_modes **不重复**：那条只证明顶栏里
    有两档按钮，别处再冒出第二个控件它照样绿；这条钉的是 DOM 侧的**唯一性**。
    变异验证（已实跑）：把 scope 下拉 select 加回词库 toolbar → 第一条红。
    """
    tb = _words_toolbar()
    assert not re.search(r"scope", tb, re.I), (
        "词库 toolbar 里不许再有 scope 控件 —— scope 是全局模式，唯一入口在顶栏 #scopeSeg"
    )
    assert len(re.findall(r'id="scopeSeg"', _WORKBENCH)) == 1, (
        "#scopeSeg 必须全文件只出现一次（多个同 id 容器 = 多个写入口）"
    )
    hdr = _header_top()
    assert len(re.findall(r'data-scope="', _WORKBENCH)) == 2, (
        "全文件的 data-scope 档位按钮必须恰好两个（all / core）"
    )
    assert len(re.findall(r'data-scope="', hdr)) == 2, (
        "两个档位按钮必须都在顶栏切片里（在别处 = 又多了一个控件）"
    )


def test_core_scope_filter_in_words_view():
    """wordFilters 有 scope 字段（默认 all），且 renderWords 谓词按 core tag 过滤。

    默认必须是 all —— 默认 core 会让老用户打开词表突然只剩 235 词。
    变异验证：默认值改成 "core" → 默认档断言红；
              把 scope 检查从谓词里挪走 → 谓词断言红；
              把 `return false` 改成 `return true` → 过滤方向断言红。
    """
    m = re.search(r"const wordFilters\s*=\s*\{[^}]*\}", _WORKBENCH)
    assert m, "找不到 wordFilters 定义"
    assert re.search(r"scope:\s*[\"']all[\"']", m.group(0)), (
        "wordFilters 必须有 scope 字段且默认为 'all'（默认展示全部词）"
    )

    pred = _words_filter_predicate()
    scope_lines = [ln for ln in pred.splitlines() if "wordFilters.scope" in ln]
    assert scope_lines, "renderWords 的过滤谓词里没有 wordFilters.scope 检查"
    line = scope_lines[0]
    assert re.search(r"wordFilters\.scope\s*===\s*[\"']core[\"']", line), (
        "scope 检查必须判定 wordFilters.scope === 'core'"
    )
    assert re.search(r"!\s*\(\s*w\.tags\s*\|\|\s*\[\s*\]\s*\)\.includes\(\s*[\"']core[\"']\s*\)", line), (
        "core 档必须按 (w.tags || []).includes('core') 判定，且排除不含 core tag 的词"
    )
    assert "return false" in line, "core 档下非核心词必须 return false（真过滤掉）"


_SCOPE_WRITE = r"wordFilters\.scope\s*=[^=]"


def _scope_write_sites():
    """所有写 wordFilters.scope 的位置（赋值，不含 `===` / `!==` 比较）。

    返回 [(行号, 从赋值处到所在顶层块结尾的代码), ...]。
    切到「第 0 列的 `}`」为止 —— 只有同一个块里、赋值**之后**的代码才算
    「这次切模式做了什么」，写在别的函数里的调用不算数。
    """
    sites = []
    for m in re.finditer(_SCOPE_WRITE, _WORKBENCH):
        end = _WORKBENCH.index("\n}", m.end())
        sites.append((_WORKBENCH[: m.start()].count("\n") + 1, _WORKBENCH[m.end() : end]))
    return sites


def test_scope_has_single_write_site():
    """wordFilters.scope 全文件只有一个写入点，且它在顶栏 #scopeSeg 的 click handler 里。

    迁移自 test_core_scope_listener_wired（原来钉词库 scope 下拉进词表 filter
    绑定数组、并在那个 handler 里写回 scope）。ADR-0002 Task 2 的产出就是「单一写入口」，
    所以断言从「第二个入口存在」翻转成「第二个入口不存在」。
    与 Task 1 的 test_scope_segment_click_reuses_refilter_chain **不重复**：那条只问
    顶栏 handler 里**有没有**一处赋值，别处再加第二个写入点它照样绿；这条数的是
    全文件命中数，多一处就红。
    变异验证（已实跑）：删掉顶栏 handler 里 `wordFilters.scope = next;` → 命中数 0，红。
    """
    sites = _scope_write_sites()
    assert len(sites) == 1, (
        "wordFilters.scope 的写入点必须全局唯一（顶栏 #scopeSeg），实际 %d 处：行 %r"
        % (len(sites), [ln for ln, _ in sites])
    )
    fn = _scope_seg_click_handler()
    assert re.search(_SCOPE_WRITE, fn), (
        "唯一的 scope 写入点必须落在顶栏 #scopeSeg 的 click handler 里"
    )
    blk = _words_filter_listener()
    assert not re.search(_SCOPE_WRITE, blk), (
        "词表 filter 控件的 handler 不许再写 wordFilters.scope（scope 已收敛到顶栏）"
    )
    assert "renderWords()" in blk, "词表 filter handler 仍必须重新渲染词表"


# --------------------------------------------------------------------------
# Task 3 · 复习队列的核心词模式过滤
# --------------------------------------------------------------------------
_CORE_TAG_CHECK = r'includes\(\s*["\']core["\']\s*\)'
_SCOPE_IS_CORE = r'wordFilters\.scope\s*===\s*["\']core["\']'
_INSCOPE_WORD_CALL = r'\binScopeWord\s*\('


def _inscope_helper_definition():
    """全局 helper inScopeWord 的定义体。"""
    m = re.search(
        r'function\s+inScopeWord\s*\(\s*w\s*\)\s*\{.*?\n\}',
        _WORKBENCH,
        re.S,
    )
    assert m, "workbench.html 缺少模块级 inScopeWord helper"
    return m.group(0)


def _build_review_queue_body():
    """buildReviewQueue 的函数体（切到下一个顶层 function 为止）。

    只认函数体内的 scope 过滤 —— 建完队列再在别处裁剪的实现，
    「上一张」回看历史和 queueInfoText 计数都会错，切片里看不到就红。
    """
    body = _WORKBENCH.split("function buildReviewQueue()")[1].split("\nfunction ")[0]
    assert "revQueue = dueIds.concat(newIds)" in body, "切片没落在 buildReviewQueue 上"
    return body


def _split_top_level_commas(text):
    """按顶层逗号切分声明列表：括号/方括号/花括号内、引号内的逗号一律不切。

    朴素的 `text.split(",")` 在这两个函数体上直接切烂 ——
    `Math.max(0, dailyNew - nw)`、`S.cards[id]`、`wordFilters.scope === "core"`
    里的逗号都不是声明分隔符。只在深度 0 且不在引号里时切。
    """
    parts, buf, depth, quote, esc = [], [], 0, None, False
    for ch in text:
        if quote:                      # 引号内：只找收尾引号，其余字符原样收
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth <= 0:  # <=0：切片可能从括号内部起头（深度会先变负）
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


# 单个声明子句 `name = <初始化表达式>`；无初始化的（`let a, b;`）直接不算判定
_DECLARATOR = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*=\s*(.+)$", re.S)


def _scope_gate_names(body):
    """函数体里由 wordFilters.scope / core tag 派生出来的判定标识符。

    容忍 `isCoreOnly` 布尔 + `inScope(w)` 谓词这类拆写，
    也容忍调用全局 helper `inScopeWord(w)` —— 只要 helper 本身以 wordFilters.scope 为核心 truth source。
    拒绝「压根没引用 scope / 没调用 helper」的实现。

    逐个声明子句判各自的 RHS —— 不能用「首个变量名 + 到分号为止的一大坨」：
    `let due = 0, nw = 0, isCoreOnly = wordFilters.scope === "core";` 会把
    `due` 也登记成判定标识符，于是「due++」这类光提了变量名、scope 判定已被删掉的
    片段照样过关（本函数正是被这个洞害成死测的）。
    """
    names = set()
    for m in re.finditer(r"\b(?:const|let|var)\s+([^;]+);", body):
        for part in _split_top_level_commas(m.group(1)):
            d = _DECLARATOR.match(part)
            if not d:
                continue
            name, rhs = d.group(1), d.group(2)
            if "wordFilters.scope" in rhs or re.search(_CORE_TAG_CHECK, rhs):
                names.add(name)
    return names


def _is_scope_gated(fragment, gates):
    """片段本身做了 core 判定、引用了 body 里派生出来的判定标识符，或调用了 inScopeWord。"""
    if re.search(_SCOPE_IS_CORE, fragment) and re.search(_CORE_TAG_CHECK, fragment):
        return True
    if re.search(_INSCOPE_WORD_CALL, fragment):
        return True
    return any(re.search(r"\b" + re.escape(g) + r"\b", fragment) for g in gates)


def test_core_scope_in_review_queue():
    """buildReviewQueue 的「到期卡」和「今日新词池」两路都按当前 scope 过滤。

    两路都要钉：只过滤到期卡会让核心模式下继续灌非核心新词；
    只过滤新词池会让昨天学的非核心词今天照样弹出来。
    实现允许调用全局 inScopeWord helper，但 helper 本身必须以 wordFilters.scope 为 truth source。
    变异验证：任一路去掉 inScopeWord / scope 判定 → 对应断言红；
              把 inScopeWord 内部改成无条件 true → helper 定义断言红。
    """
    helper = _inscope_helper_definition()
    assert re.search(_SCOPE_IS_CORE, helper), (
        "inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source"
    )
    assert re.search(_CORE_TAG_CHECK, helper), (
        "inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词"
    )

    body = _build_review_queue_body()
    assert re.search(_INSCOPE_WORD_CALL, body), (
        "buildReviewQueue 必须调用 inScopeWord 进行 scope 过滤（或保留 inline 判定）"
    )
    gates = _scope_gate_names(body)

    due = body.split("const dueIds")[1].split(".sort(")[0]
    assert "wordById(id)" in due, "到期卡过滤必须保留 wordById(id) 存在性守卫"
    assert _is_scope_gated(due, gates), "到期卡过滤里没有 scope 判定（核心模式下会混入非核心到期卡）"

    assert "S.words.filter(" in body, "buildReviewQueue 里找不到今日新词池"
    pool = body.split("S.words.filter(")[1].split(".map(w => w.id)")[0]
    assert "!S.cards[w.id]" in pool, "切片没落在新词池过滤上"
    assert _is_scope_gated(pool, gates), "新词池过滤里没有 scope 判定（核心模式下会灌入非核心新词）"


def _scope_refilter_body():
    """复习中途切 scope 的静默过滤函数体。"""
    m = re.search(r"function refilterReviewQueueForScope\(\)\s*\{.*?\n\}", _WORKBENCH, re.S)
    assert m, "找不到复习中途切 scope 的队列重过滤函数 refilterReviewQueueForScope()"
    return m.group(0)


def test_core_scope_midreview_switch_filters_only_upcoming():
    """复习中途切 scope：只静默剔除 revIdx 之后的越界词，历史与进度一律不动。

    FSRS 记录唯一 —— 切模式不能重建队列（会丢 ratedCount / 让「上一张」回看断链），
    也不能动 revIdx 之前已评价过的卡。
    分界要钉两半（各自一条断言，禁止一条模式兼职两处）：
    尾段必须从 `revQueue.slice(revIdx + 1)` 起过滤，保留段必须是
    `revQueue.slice(0, revIdx + 1)` —— 只搜裸片段 `revIdx + 1` 是死断言，
    该片段在本函数里出现两次，把尾段裁成 slice(0) 也照样匹配得上。
    变异验证（均已实跑确认红）：
        尾段 revQueue.slice(revIdx + 1) → revQueue.slice(0)（每张待复习卡重复一遍）→ 尾段断言红；
        保留段 revQueue.slice(0, revIdx + 1) → revQueue.slice(0, revIdx)（丢当前卡）→ 保留段断言红；
        裁剪时不判 core tag → tag 断言红。
    """
    fn = _scope_refilter_body()
    assert re.search(r"revQueue\.slice\(\s*revIdx\s*\+\s*1\s*\)", fn), (
        "待复习尾段必须整段取自 revQueue.slice(revIdx + 1) 再过滤"
        "（从 0 起裁会把已复习过的卡重新塞回队列）"
    )
    assert re.search(r"revQueue\.slice\(\s*0\s*,\s*revIdx\s*\+\s*1\s*\)", fn), (
        "revIdx 及之前是已评价历史，必须整段 revQueue.slice(0, revIdx + 1) 原样保留"
    )
    assert _is_scope_gated(fn, set()), "重过滤必须按 scope/core 判定要不要剔除"
    assert "buildReviewQueue(" not in fn, (
        "重过滤不能重建队列（重建会重置 revIdx 并丢掉本轮历史）"
    )
    for var in ("revIdx", "ratedCount", "queueDay"):
        assert not re.search(r"\b" + var + r"\s*=[^=]", fn), (
            f"重过滤禁止改写 {var}（进度与队列日必须保持不变）"
        )
    assert re.search(r'curView\s*===\s*["\']review["\']', fn), (
        "只有当前在复习视图时才需要重渲染卡面"
    )
    assert "renderReview()" in fn, "重过滤后必须刷新复习视图"


def test_scope_switch_refilters_review_queue():
    """凡是写 wordFilters.scope 的地方，同块内**随后**都必须调 refilterReviewQueueForScope()。

    迁移自 test_core_scope_midreview_switch_wired（原来钉词库 scope 下拉的 change handler）。
    守的不变式一字未改：切模式必须同步复习队列，否则切到核心词后队列里还留着
    非核心词，用户以为切了其实没切。
    与 Task 1 的 test_scope_segment_click_reuses_refilter_chain **不重复**：那条只问
    顶栏 handler 里出不出现这个调用，先后顺序不管、将来新开的写入点也不管；这条
    遍历**每一个**写入点，且切片从赋值处起算 —— 调用写在赋值**之前**（用旧 scope
    过滤，等于永远慢一拍）同样红。
    变异验证（已实跑）：删掉顶栏 handler 里的 refilterReviewQueueForScope() → 红。
    """
    sites = _scope_write_sites()
    assert sites, "全文件找不到 wordFilters.scope 的写入点，无从检查队列同步"
    for line, seg in sites:
        assert "refilterReviewQueueForScope()" in seg, (
            "行 %d 写了 wordFilters.scope 却没在其后调 refilterReviewQueueForScope()"
            "，复习队列不会跟着切模式" % line
        )


# --------------------------------------------------------------------------
# Task 4 · 统计与徽章的核心词模式适配
# --------------------------------------------------------------------------

def _fn_body(name):
    """顶层无参函数的函数体（切到第 0 列的 `}` 为止）。

    第 0 列缩进作边界 —— 函数内部的块级 `}` 都有缩进，所以切片不会溢出到下一个函数。
    """
    m = re.search(r"function %s\(\)\s*\{.*?\n\}" % re.escape(name), _WORKBENCH, re.S)
    assert m, "找不到函数 %s()" % name
    return m.group(0)


def _sole_line(body, needle, what):
    """body 里唯一含 needle 的那一行。

    出现多处就直接失败 —— 断言必须钉在唯一一处上，否则「改了一处另一处仍匹配」
    会让测试在实现被回退后照样绿。
    """
    lines = [ln for ln in body.splitlines() if needle in ln]
    assert lines, "%s：找不到含 `%s` 的行" % (what, needle)
    assert len(lines) == 1, (
        "%s：含 `%s` 的行有 %d 处，断言不具区分度" % (what, needle, len(lines))
    )
    return lines[0]


def _kpi_row_assign():
    """renderStats 里 `$("kpiRow").innerHTML = ...;` 整条赋值（可跨行）。"""
    body = _fn_body("renderStats")
    at = body.index('$("kpiRow").innerHTML')
    return body[at:body.index(";", at)]


def _kpi_call(assign, label):
    """kpiRow 赋值里 label 那一格的完整 kpi(...) 调用（括号配平，含全部实参）。

    钉整条调用而不是裸片段 —— 只搜 label 字符串的话，把动态值换成写死的数字
    也照样绿。
    """
    at = assign.find('"%s"' % label)
    assert at > 0, "统计页 KPI 区缺少「%s」这一格" % label
    return _slice_balanced(assign, assign.rindex("kpi(", 0, at), "(", ")")


def test_core_scope_aware_header_badge():
    """顶栏「今日待学」必须与 buildReviewQueue 同口径：核心模式下只算核心词。

    徽标口径不跟队列走，核心模式下就会显示一堆永远进不了队列的非核心待学数
    ——「今日待学 40」点进去只有 8 张卡，且永远清不到「今日已完成 ✓」。
    实现允许调用全局 inScopeWord helper。
    变异验证：到期路 / 新词路任一处去掉 inScopeWord → 对应断言红；
              inScopeWord 内部改成无条件 true → helper 定义断言红。
    """
    helper = _inscope_helper_definition()
    assert re.search(_SCOPE_IS_CORE, helper), (
        "inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source"
    )
    assert re.search(_CORE_TAG_CHECK, helper), (
        "inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词"
    )

    body = _fn_body("renderHeaderBadge")
    assert re.search(_INSCOPE_WORD_CALL, body), (
        "renderHeaderBadge 必须调用 inScopeWord 进行 scope 过滤（或保留 inline 判定）"
    )
    gates = _scope_gate_names(body)
    assert "wordById(" in body, "renderHeaderBadge 必须保留词存在性守卫（孤儿卡不计数）"

    due = _sole_line(body, "due++", "到期计数")
    assert _is_scope_gated(due, gates), (
        "到期计数没有 scope 判定（核心模式下会多算非核心到期卡）"
    )
    for guard in ("c.reps > 0", "!c.manual", "c.due <= eod"):
        assert guard in due, "到期计数丢了原有守卫 %s" % guard

    new_line = _sole_line(body, "S.words.filter(", "新词余量计数")
    assert "!S.cards[w.id]" in new_line, "新词余量必须只数没有 FSRS 记录的词"
    assert _is_scope_gated(new_line, gates), (
        "新词余量没有 scope 判定（核心模式下会多算非核心新词）"
    )


def test_header_badge_refreshed_on_scope_switch():
    """徽标重算与 scope 写入点绑定：写入点之后必须调 renderHeaderBadge()，别处不许调。

    守的不变式没变，且是**两侧**的：
      正向 —— 徽标口径随 scope 变（核心模式下待学数只该数核心词），切了模式不重算，
              顶栏就还挂着上一个模式的数；
      反向 —— 迁移前的旧版本把调用限制在 `scope !== prevScope` 分支里，理由是
              「不让搜索框每敲一个字母都重算徽标」。renderHeaderBadge() 每次全扫
              S.cards + S.words，挂到 input 事件上是真的性能退化。迁移后这一侧必须
              显式补回来（就是最后那条 not-in 断言），否则丢的是「不按键重算」这半个。
    **重定向说明**：这条原先钉的是词表 filter handler 里的 `scope !== prevScope`
    分支。Task 2 删掉了那个 handler 的 scope 赋值，该分支随即恒为 false ——
    测试仍会绿，但守的是一段不可达代码，属于假信心。故改为与
    test_scope_switch_refilters_review_queue 同构地遍历每一个 scope 写入点。
    与 Task 1 的 test_scope_segment_click_reuses_refilter_chain 的关系：那条**同样**
    断言了顶栏 handler 内有 renderHeaderBadge()，在**当前唯一的那个写入点**上二者重叠。
    但不是冗余——那条钉的是「#scopeSeg 这一个 handler 的完整链路」，本条钉的是
    「**任何** scope 写入点都必须重算徽标」：将来新增第二个写入点（比如设置页再加一个
    模式开关）而忘了调 renderHeaderBadge()，那条照绿，本条红。
    变异验证（已实跑）：删掉顶栏 handler 里的 renderHeaderBadge() → 第一条红；
    注意同一发变异下 Task 1 那条也红（二者在这个写入点上重叠），不是只打红本条。
    往词表 filter listener 里无条件加 renderHeaderBadge() → 第二条红。
    """
    sites = _scope_write_sites()
    assert sites, "全文件找不到 wordFilters.scope 的写入点，无从检查徽标重算"
    for line, seg in sites:
        assert "renderHeaderBadge()" in seg, (
            "行 %d 写了 wordFilters.scope 却没在其后调 renderHeaderBadge()"
            "，顶栏徽标会停在上一个模式的口径" % line
        )
    assert "renderHeaderBadge()" not in _words_filter_listener(), (
        "词表 filter listener 不许调 renderHeaderBadge() —— 它每次全扫 S.cards + S.words，"
        "挂在搜索框上等于每敲一个字母全扫一遍；scope 已经不在这个 listener 里变了"
    )


# --------------------------------------------------------------------------
# ADR-0002 Task 1 · 顶栏 scope 分段控件 + 徽标模式前缀
# --------------------------------------------------------------------------

def _header_top():
    """`<header class="top"> … </header>` 整段（顶栏那一行 flex 容器）。

    必须切片再断言 —— `id="scopeSeg"` 写在文件任何角落，整文件搜索都为真，
    只有钉进顶栏切片才能证明「常驻可见、不藏在词库视图里」。
    """
    opens = re.findall(r'<header class="top">', _WORKBENCH)
    assert len(opens) == 1, (
        '<header class="top"> 出现 %d 次，切片不具区分度' % len(opens)
    )
    m = re.search(r'<header class="top">.*?</header>', _WORKBENCH, re.S)
    assert m, '找不到 <header class="top"> 顶栏'
    blk = m.group(0)
    assert 'id="dueBadge"' in blk, "切片没落在顶栏上（缺 #dueBadge）"
    return blk


def _scope_seg_click_handler():
    """顶栏分段控件 click handler 的整段（到第 0 列的 `});` 为止）。"""
    hits = re.findall(
        r'\$\(\s*"scopeSeg"\s*\)\.addEventListener\(\s*"click".*?\n\}\);',
        _WORKBENCH,
        re.S,
    )
    assert hits, "找不到 #scopeSeg 的 click 事件绑定（控件加了没接线）"
    assert len(hits) == 1, (
        "#scopeSeg 的 click 绑定有 %d 处，断言不具区分度" % len(hits)
    )
    return hits[0]


def _badge_text_assign():
    """renderHeaderBadge 里 `b.textContent = …;` 整条赋值（允许跨行）。"""
    body = _fn_body("renderHeaderBadge")
    hits = len(re.findall(r"\btextContent\s*=", body))
    assert hits == 1, (
        "renderHeaderBadge 里 textContent 赋值有 %d 处，断言不具区分度" % hits
    )
    at = body.index("b.textContent")
    return body[at:body.index(";", at) + 1]


def test_scope_segment_control_in_header():
    """顶栏 flex 行里常驻 scope 分段控件 #scopeSeg。

    ADR-0002 §3.1：模式状态必须时刻可见（D1）。原先藏在词库工具栏里的那个下拉
    在复习视图看不见也够不着，队列变短时用户分不清是「学完了」还是「切了范围」。
    变异验证：把 <div id="scopeSeg"> 移出顶栏 / 删掉 → 断言红。
    """
    hdr = _header_top()
    assert 'id="scopeSeg"' in hdr, (
        '<header class="top"> 里缺少常驻 scope 分段控件 #scopeSeg'
    )


def test_scope_segment_has_both_modes():
    """#scopeSeg 里恰好两个 button，data-scope 依次覆盖 all / core。

    变异验证：删掉任一 data-scope 属性 → 断言红（实际值变成单元素列表）。
    """
    hdr = _header_top()
    assert 'id="scopeSeg"' in hdr, "顶栏里没有 #scopeSeg，无从检查档位"
    seg = hdr.split('id="scopeSeg"')[1].split("</div>")[0]
    assert len(re.findall(r"<button", seg)) == 2, (
        "#scopeSeg 必须恰好两个档位按钮"
    )
    scopes = re.findall(r'<button[^>]*\bdata-scope="([a-z]+)"', seg)
    assert scopes == ["all", "core"], (
        "#scopeSeg 两个 button 的 data-scope 必须依次为 all / core，实际 %r" % (scopes,)
    )


def test_scope_segment_click_reuses_refilter_chain():
    """顶栏切模式复用既有链路，禁止整队重建。

    buildReviewQueue() 会 `revIdx = 0` 并重新洗牌 —— 复习到一半切模式会被弹回
    第一张卡且顺序全变，比不生效更糟（ADR-0002 D5）。只能走
    refilterReviewQueueForScope() 的尾部手术。
    变异验证（已实跑）：把 refilterReviewQueueForScope() 换成 buildReviewQueue()
              → 本测试红（pytest 停在「必须调 refilter」这条；同一变异下
              「禁止 buildReviewQueue」经单独求值同样为假，两条都有判别力）。
    """
    fn = _scope_seg_click_handler()
    assert re.search(r"wordFilters\.scope\s*=[^=]", fn), (
        "handler 必须把点中的档位写回 wordFilters.scope"
    )
    assert "refilterReviewQueueForScope()" in fn, (
        "handler 必须调 refilterReviewQueueForScope() 同步复习队列尾部"
    )
    assert "buildReviewQueue(" not in fn, (
        "handler 禁止调 buildReviewQueue()（revIdx 归零会把用户弹回第一张卡）"
    )
    assert "renderWords()" in fn, "handler 必须重渲染词表"
    assert "renderHeaderBadge()" in fn, "handler 必须重算顶栏徽标"
    assert "syncScopeControls()" in fn, (
        "handler 必须调 syncScopeControls() 把新档位同步到另一处控件"
    )


def test_header_badge_carries_scope_mode():
    """徽标同时承载模式与待学数：`⭐核心 · 今日待学 12` / `全部 · 今日已完成 ✓`。

    pending>0 与「已完成」**两个分支都要带**前缀 —— 只给待学分支加的话，
    核心模式刷完后徽标又变回无模式的「今日已完成 ✓」，模式状态凭空消失。
    变异验证：任一分支去掉前缀变量 → 对应分支断言红；
              前缀写死成常量（不读 wordFilters.scope）→ 派生断言红。
    """
    body = _fn_body("renderHeaderBadge")
    label = _sole_line(body, "⭐核心", "模式前缀")
    assert re.search(_SCOPE_IS_CORE, label), (
        "模式前缀必须由 wordFilters.scope === 'core' 派生，不能写死"
    )
    assert "全部" in label, "模式前缀缺少「全部」档文案"
    m = re.match(r"\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", label)
    assert m, "模式前缀应赋给一个局部变量，供徽标两个分支复用"
    var = m.group(1)

    assign = _badge_text_assign()
    arms = assign.partition("?")[2]
    pending_arm, sep, done_arm = arms.partition(":")
    assert sep, "徽标文案应为 `pending > 0 ? … : …` 两个分支"
    assert "今日待学" in pending_arm, "三元第一分支应是「今日待学」"
    assert "今日已完成" in done_arm, "三元第二分支应是「今日已完成」"
    assert var in pending_arm, "「今日待学」分支缺少模式前缀 %s" % var
    assert var in done_arm, "「今日已完成」分支缺少模式前缀 %s" % var


def test_core_progress_kpi_in_stats():
    """统计页 KPI 区必须有一格动态算出的核心词进度（已学 / 核心词总数）。

    分母必须从 core tag 现数，不得硬编码 235/213 —— 用户增删词后写死的数字就骗人了。
    变异验证：删掉这格 KPI → 存在性断言红；分母写死 235 → 动态/无三位数断言红；
              已学数不判 reps > 0（建了卡没评价也算学过）→ 判定断言红。
    """
    body = _fn_body("renderStats")
    m = re.search(
        r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*S\.words\.filter\(\s*w\s*=>\s*"
        r"\(\s*w\.tags\s*\|\|\s*\[\s*\]\s*\)\.includes\(\s*[\"']core[\"']\s*\)\s*\)",
        body,
    )
    assert m, "renderStats 必须用 (w.tags || []).includes('core') 从 S.words 现数核心词集合"
    core_name = m.group(1)

    m2 = re.search(
        r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*"
        + re.escape(core_name) + r"\.filter\(([^;]*?)\)\.length\s*;",
        body,
    )
    assert m2, "renderStats 必须从核心词集合里数出已学数（%s.filter(...).length）" % core_name
    learned_name, pred = m2.group(1), m2.group(2)
    assert "S.cards[w.id]" in pred, "核心词已学数必须查 S.cards（有 FSRS 记录才算学过）"
    assert re.search(r"reps\s*>\s*0", pred), (
        "核心词已学数必须判 reps > 0（建了卡但一次没评价不算已学）"
    )

    call = _kpi_call(_kpi_row_assign(), "核心词进度")
    assert re.search(r"\b" + re.escape(learned_name) + r"\b", call), (
        "核心词进度 KPI 的分子必须是动态算出的已学数 %s" % learned_name
    )
    assert re.search(r"\b" + re.escape(core_name) + r"\.length\b", call), (
        "核心词进度 KPI 的分母必须是 %s.length（现数，不得硬编码）" % core_name
    )
    assert not re.search(r"\d{3}", call), (
        "核心词进度 KPI 不得出现硬编码词数（235/213 之类）"
    )


def test_stats_totals_and_heatmap_stay_global():
    """统计页总览与字母分布保持全局口径，只有核心词进度那一格是核心视角。

    ADR 决策：scope 是「复习范围」不是「统计范围」—— 总词数/字母分布永远显示整副牌，
    否则切一次核心模式就以为自己丢了 470 个词。
    变异验证：总词数 改成 scope 过滤 → 首条断言红；renderStats 读 wordFilters.scope
              → 第二条红；letterHeatmap / 各字母掌握度 加 core 过滤 → 后三条红。
    """
    body = _fn_body("renderStats")
    total = _sole_line(body, "const total", "总词数")
    assert re.search(r"const total\s*=\s*S\.words\.length\s*;", total), (
        "总词数必须是 S.words.length（全局），不得按 scope 过滤"
    )
    assert not re.search(_SCOPE_IS_CORE, body), (
        "renderStats 不得读 wordFilters.scope（统计是全局总览，核心词只单列一格进度）"
    )

    hm = _fn_body("letterHeatmap")
    assert "for (const w of S.words)" in hm, "字母热图必须遍历全部 S.words"
    assert not re.search(_SCOPE_IS_CORE, hm), "字母热图不得按 scope 过滤（全局学习分布概览）"
    assert not re.search(_CORE_TAG_CHECK, hm), "字母热图不得按 core tag 过滤（全局学习分布概览）"

    letters = body.split("const letters = {}")[1].split("const Ls =")[0]
    assert "S.words" in letters, "切片没落在「各字母掌握度」统计上"
    assert not re.search(_CORE_TAG_CHECK, letters), (
        "各字母掌握度必须保持全局，不得按 core tag 过滤"
    )


# --------------------------------------------------------------------------
# Task 5 · 错题/测试/额外练习的核心词模式过滤 + 导入导出兼容性
# --------------------------------------------------------------------------

def _quiz_pool_body():
    """quizPool 函数体（到 startQuiz 之前）。"""
    body = _WORKBENCH.split("function quizPool()")[1].split("function startQuiz(")[0]
    assert '$("qPoolSel")' in body, "切片没落在 quizPool 上"
    return body


def _inject_wrong_words_body():
    """injectWrongWords 函数体。"""
    body = _WORKBENCH.split("function injectWrongWords(")[1].split("\nfunction ")[0]
    assert "revQueue.unshift" in body, "切片没落在 injectWrongWords 上"
    return body


def _extra_practice_body():
    """extraPractice 函数体。"""
    body = _WORKBENCH.split("function extraPractice()")[1].split("\nfunction ")[0]
    assert "S.words.filter(" in body, "切片没落在 extraPractice 上"
    return body


def _extra_new_words_body():
    """extraNewWords 函数体。"""
    body = _WORKBENCH.split("function extraNewWords()")[1].split("\nfunction ")[0]
    assert "S.words.filter(" in body, "切片没落在 extraNewWords 上"
    return body


def test_core_scope_quiz_pool_filtered():
    """quizPool 在核心模式下必须只从当前 scope 的词里抽题。

    4 条分支（forgotten / wrong / weak / 默认全池）都要过滤：
    漏任何一条，核心模式下都会抽到非核心词作为题目/干扰项。
    允许调用全局 inScopeWord helper。
    变异验证：任一分支去掉 inScopeWord → 对应断言红。
    """
    helper = _inscope_helper_definition()
    assert re.search(_SCOPE_IS_CORE, helper), (
        "inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source"
    )
    assert re.search(_CORE_TAG_CHECK, helper), (
        "inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词"
    )

    body = _quiz_pool_body()
    assert re.search(_INSCOPE_WORD_CALL, body), (
        "quizPool 必须调用 inScopeWord 进行 scope 过滤"
    )

    # forgotten 分支
    forgotten = body.split('if (p === "forgotten")')[1].split('if (p === "wrong")')[0]
    assert "wordById(id)" in forgotten, "forgotten 分支应保留 wordById(id) 守卫"
    # 候选错题过滤段 & 无数据 fallback 段都要过滤
    forgotten_candidate = forgotten.split("const ids")[1].split("return ids.length")[0]
    assert _is_scope_gated(forgotten_candidate, set()), (
        "forgotten 候选错题过滤没有 scope 判定"
    )
    forgotten_fallback = forgotten.split("return ids.length")[1]
    assert _is_scope_gated(forgotten_fallback, set()), (
        "forgotten 无数据 fallback 没有 scope 判定（核心模式会从整副牌抽题）"
    )

    # wrong 分支
    wrong = body.split('if (p === "wrong")')[1].split('if (p === "weak")')[0]
    assert "wordById(id)" in wrong, "wrong 分支应保留 wordById(id) 守卫"
    wrong_candidate = wrong.split("const ids")[1].split("return ids.length")[0]
    assert _is_scope_gated(wrong_candidate, set()), (
        "wrong 候选错题过滤没有 scope 判定"
    )
    wrong_fallback = wrong.split("return ids.length")[1]
    assert _is_scope_gated(wrong_fallback, set()), (
        "wrong 无数据 fallback 没有 scope 判定（核心模式会从整副牌抽题）"
    )

    # weak 分支：到它自己的 }).map(w => w.id); 为止
    weak = body.split('if (p === "weak")')[1].split("}).map(w => w.id);")[0]
    assert "S.words.filter(" in weak, "切片没落在 weak 分支上"
    assert _is_scope_gated(weak, set()), (
        "weak 分支没有 scope 判定（核心模式下会混入非核心弱词）"
    )

    # 默认全池分支（最后一个 return）
    last_return = body.rsplit("return", 1)[1]
    assert "S.words.filter(" in last_return, "切片没落在默认全池分支上"
    assert _is_scope_gated(last_return, set()), (
        "默认全池分支没有 scope 判定（核心模式下会从整副牌抽题）"
    )


def test_core_scope_inject_wrong_words_filtered():
    """错题本智能推送必须只推当前 scope 内的词，避免核心模式被非核心错题顶到队头。

    当前实现是 unshift 到 revQueue 头部；若不过滤，核心模式下队头会出现
    不在复习计划内的非核心词，直接绕过 buildReviewQueue 的过滤。
    允许调用全局 inScopeWord helper。
    变异验证：filter 里去掉 inScopeWord → 断言红。
    """
    helper = _inscope_helper_definition()
    assert re.search(_SCOPE_IS_CORE, helper), (
        "inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source"
    )
    assert re.search(_CORE_TAG_CHECK, helper), (
        "inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词"
    )

    body = _inject_wrong_words_body()
    assert re.search(_INSCOPE_WORD_CALL, body), (
        "injectWrongWords 必须调用 inScopeWord 进行 scope 过滤"
    )

    candidates = body.split("Object.entries(S.wrong)")[1].split(".slice(0, n)")[0]
    assert _is_scope_gated(candidates, set()), (
        "candidates 筛选里没有 scope 判定（核心模式会 unshift 非核心错题到队头）"
    )


def test_core_scope_extra_practice_and_new_filtered():
    """额外练习 / 额外学新词追加时必须按当前 scope 过滤。

    这两个按钮在复习队列底部追加 20 张卡；若不过滤，核心模式下会灌入非核心词。
    允许调用全局 inScopeWord helper。
    变异验证：任一路去掉 inScopeWord → 对应断言红。
    """
    helper = _inscope_helper_definition()
    assert re.search(_SCOPE_IS_CORE, helper), (
        "inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source"
    )
    assert re.search(_CORE_TAG_CHECK, helper), (
        "inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词"
    )

    practice = _extra_practice_body()
    new_words = _extra_new_words_body()

    for name, body in (("extraPractice", practice), ("extraNewWords", new_words)):
        assert re.search(_INSCOPE_WORD_CALL, body), (
            "%s 必须调用 inScopeWord 进行 scope 过滤" % name
        )

    # extraPractice：从已学且不在队列中的词里筛选
    p_pool = practice.split("S.words.filter(")[1].split(").slice(0, 20)")[0]
    assert "S.cards[w.id]" in p_pool, "extraPractice 池必须只取已有卡片的词"
    assert "reps > 0" in p_pool, "extraPractice 池必须只取已评价过的词"
    assert _is_scope_gated(p_pool, set()), (
        "extraPractice 池没有 scope 判定（核心模式会追加非核心已学词）"
    )

    # extraNewWords：从未学且不在队列中的词里筛选
    n_pool = new_words.split("S.words.filter(")[1].split("const ordered")[0]
    assert "!S.cards[w.id]" in n_pool, "extraNewWords 池必须只取未学新词"
    assert _is_scope_gated(n_pool, set()), (
        "extraNewWords 池没有 scope 判定（核心模式会追加非核心新词）"
    )


def test_core_sync_export_import_round_trips_custom_core_tags():
    """wb-sync 只导出 custom: true 的词；CORE_CUSTOM_WORDS 自带 custom:true，会随 tags 导出 core。

    关键约束：
      1. 导出按钮处 customWords = S.words.filter(w => w.custom) —— 种子词不导出；
      2. applyMerge 用 Object.assign 合并自定义词，tags 字段会被完整带入；
      3. 种子词不走 merge，因此其 core tag 始终由本机常量决定。
    本测试只验证源码中这三处行为存在，不跑真导入导出。
    """
    export_block = _WORKBENCH.split('$("btnExportSync").addEventListener')[1].split("});\n$(\"fileImport\")")[0]
    assert "S.words.filter(w => w.custom)" in export_block, (
        "同步导出必须只取 custom: true 的词"
    )
    assert "customWords: custom" in export_block, (
        "同步导出对象必须带 customWords 字段"
    )

    merge = _WORKBENCH.split("function applyMerge(")[1].split("$(\"btnResetProgress\")")[0]
    assert "Object.assign(cur, w)" in merge, (
        "applyMerge 必须用 Object.assign 覆盖旧自定义词，确保 tags（含 core）被更新"
    )
    assert "S.words.push(w)" in merge, (
        "applyMerge 必须把新自定义词追加到 S.words"
    )
    # 确认没有「同步时给 seed 词打 core tag」的奇异逻辑
    assert not re.search(_CORE_TAG_CHECK, merge), (
        "applyMerge 不应自己处理 core tag（种子词不走 merge，自定义词的 tags 随字段自然合并）"
    )


# --------------------------------------------------------------------------
# Task 8 · applyMerge 按归一词头去重 + 重复种子词下架的 id 归并
# --------------------------------------------------------------------------

def _normhw_body():
    """normHw 函数体（定义到下一个顶层 function 为止）。"""
    assert "function normHw(" in _WORKBENCH, "缺少 normHw 归一函数"
    return _WORKBENCH.split("function normHw(")[1].split("\nfunction ")[0]


def _apply_merge_body():
    """applyMerge 函数体（到 btnResetProgress 绑定为止，与 Task 5 断言同切法）。"""
    assert "function applyMerge(data)" in _WORKBENCH, "缺少 applyMerge 定义"
    return _WORKBENCH.split("function applyMerge(data)")[1].split('$("btnResetProgress")')[0]


def _apply_merge_words_block():
    """applyMerge 里处理单词表的那一段（`const inWords` → `if (data.settings)`）。

    切这么窄是为了把断言钉在真正的合并循环里：写在循环之后再「事后去重」
    的实现不会出现在这个切片内。
    """
    body = _apply_merge_body()
    assert "const inWords" in body, "applyMerge 里找不到单词合并段"
    block = body.split("const inWords")[1].split("if (data.settings)")[0]
    assert "byId" in block, "切片没落在单词合并段上"
    return block


def _seed_words():
    """SEED_WORDS 常量的实际内容（真解析，不做模糊字符串匹配）。"""
    at = _WORKBENCH.index("const SEED_WORDS")
    return json.loads(_slice_balanced(_WORKBENCH, at, "[", "]"))


def _norm_hw_py(hw):
    """normHw 的 Python 等价物 —— 去定冠词 + trim，**不小写**。"""
    return re.sub(r"^(der|die|das)\s+", "", str(hw or "").strip()).strip()


def _alias_migration_body():
    """migrateSeedIdAliases 函数体（定义到下一个顶层 function 为止）。"""
    assert "function migrateSeedIdAliases(" in _WORKBENCH, "缺少 migrateSeedIdAliases 定义"
    return _WORKBENCH.split("function migrateSeedIdAliases(")[1].split("\nfunction ")[0]


def test_merge_normhw_preserves_case_and_strips_article():
    """normHw 只去定冠词 + trim；**绝不小写**，也不折入 pos。

    德语首字母大写是语义的：a1-0551 `sie`（她/他们）与 a1-0552 `Sie`（您，敬称）
    只差大小写且 pos 都是 Pron，小写折叠会把敬称并进第三人称 —— 数据丢失。
    essen / das Essen、leben / das Leben 同理靠大小写区分，因此 key 里也不需要 pos
    （导入词库有 7 个词 pos 与种子词不一致，带 pos 反而会漏过去重）。

    变异验证（已实跑确认红）：
      - 在 normHw 里加 .toLowerCase() → 第 2 条断言红，且 node 探针的 sie/Sie 分离断言红；
      - 删掉 replace(/^(der|die|das)\\s+/) → 第 1 条断言红。
    """
    body = _normhw_body()
    strip = re.findall(r"\.replace\(\s*/\^\(der\|die\|das\)\\s\+/\s*,", body)
    assert len(strip) == 1, (
        "normHw 必须且只能有一处去定冠词的 replace(/^(der|die|das)\\s+/, ...)，实际 %d 处" % len(strip)
    )
    assert "toLowerCase" not in body, "normHw 不得小写化（会把 sie/Sie、essen/Essen 合并成一条）"
    assert "toUpperCase" not in body, "normHw 不得大写化"
    assert ".pos" not in body, "normHw 不得把 pos 折进 key（导入库 pos 与种子词不一致会漏过去重）"
    assert len(re.findall(r"\.trim\(\)", body)) == 2, (
        "normHw 必须在去冠词前后各 trim 一次（`  der  Wohnort ` 这类脏数据）"
    )


def test_merge_dedups_by_normalized_headword():
    """applyMerge 必须建归一词头二级索引，并在 id 未命中时回退查它。

    没有这一步，把 delector_custom_words.json 再导一次就会把 u-008 `der Wohnort`
    并排塞在内建 core-001 `der Wohnort` 旁边：两条同词记录、两张独立 FSRS 卡、
    复习队列里同一个词出现两次。

    变异验证（已实跑确认红）：
      - 把 `sameId || (k ? byHw.get(k) : null)` 改回 `byId.get(w.id)` → fallback 断言红，
        且 node 探针二次导入不再是 no-op；
      - 删掉 push 之后的 byHw.set → byHw.set 计数断言红（同一次导入里的同词头会重复追加）。
    """
    block = _apply_merge_words_block()

    pre = block.split("for (const w of inWords)")[0]
    assert "for (const w of S.words)" in pre, "二级索引必须在合并循环之前用 S.words 建好"
    assert "byHw.set(" in pre, "合并循环之前必须真的往 byHw 里塞条目"

    assert re.search(r"const\s+sameId\s*=\s*byId\.get\(\s*w\.id\s*\)", block), (
        "必须先按 id 查（id 命中是最强的同一性证据）"
    )
    fallback = re.findall(
        r"sameId\s*\|\|\s*\(\s*k\s*\?\s*byHw\.get\(\s*k\s*\)\s*:\s*null\s*\)", block
    )
    assert len(fallback) == 1, (
        "id 未命中时必须回退查归一词头索引，且只有一处这样的回退，实际 %d 处" % len(fallback)
    )

    sets = re.findall(r"byHw\.set\(", block)
    assert len(sets) == 2, (
        "byHw.set 应恰好两处（建索引一次 + push 新词后回填一次），实际 %d 处；"
        "少了回填，同一次导入里的两个同词头会各自 push" % len(sets)
    )
    assert "normHw(w.hw)" in block, "索引 key 必须由 normHw 生成"


def test_merge_headword_hit_keeps_local_identity_fields():
    """跨 id 的同词头命中时，id / tags / custom 必须留在本机，只让内容按 up 取新。

    导入库里 237 个词的 up 全是 1788164859221（远大于种子词的 0），
    裸 Object.assign(cur, w) 会：
      1. 把 cur.id 改写成 u-XXX → S.cards[原 id] 当场变孤儿卡，FSRS 进度丢失；
      2. 把 tags 抹成 [] → 实测 148 条命中全部落在核心词上，核心模式当场空一半；
      3. 把 custom 改成 true → 126 个种子词开始混进 wb-sync 导出，每轮同步越滚越大。
    id 命中（sameId 为真）时不做保护 —— 那是同一条记录，tags 本就该按 up 取新
    （见 test_core_sync_export_import_round_trips_custom_core_tags）。

    变异验证（已实跑确认红）：把 `if (own) Object.assign(cur, own)` 删掉 →
    顺序断言红，且 node 探针的 core tag 存活数从 148 掉到 0。
    """
    block = _apply_merge_words_block()
    own = re.search(r"const\s+own\s*=\s*sameId\s*\?\s*null\s*:\s*\{([^}]*)\}", block)
    assert own, "跨 id 命中时必须先扣下本机身份字段（sameId ? null : {...}）"
    kept = own.group(1)
    for field in ("id: cur.id", "tags: cur.tags", "custom: cur.custom"):
        assert field in kept, "本机身份字段必须含 %s" % field

    assigns = re.findall(r"Object\.assign\(cur, w\)", block)
    assert len(assigns) == 1, "内容覆盖只应有一处 Object.assign(cur, w)，实际 %d 处" % len(assigns)
    restore = re.findall(r"if \(own\) Object\.assign\(cur, own\)", block)
    assert len(restore) == 1, "身份字段回填只应有一处，实际 %d 处" % len(restore)
    assert block.index("Object.assign(cur, w)") < block.index("if (own) Object.assign(cur, own)"), (
        "身份字段必须在内容覆盖之后回填，否则照样被冲掉"
    )

    recency = re.findall(r"\(w\.up \|\| 0\) > \(cur\.up \|\| 0\)", block)
    assert len(recency) == 1, "取新规则仍必须是 (w.up || 0) > (cur.up || 0)，不得改动"


def test_merge_toast_reports_added_and_merged_counts():
    """合并完成提示不得只报总词数 —— 现在有词是「合并掉」而不是「追加」的。

    只报 S.words.length 会让用户以为 237 个词都进来了；实测其中 148 个被并进已有词条。

    变异验证（已实跑确认红）：把 toast 改回只拼 S.words.length → added/merged 断言红。
    """
    body = _apply_merge_body()
    toasts = re.findall(r'toast\("合并导入完成：[^;]*\);', body)
    assert len(toasts) == 1, "合并完成提示应恰好一处，实际 %d 处" % len(toasts)
    line = toasts[0]
    assert "added" in line and "merged" in line, (
        "提示必须同时报「新增」与「合并」两个计数，否则误导用户"
    )
    assert "S.words.length" in line, "提示仍应给出合并后的总词数"

    block = _apply_merge_words_block()
    assert len(re.findall(r"\badded\+\+", block)) == 1, "added 只应在 push 分支自增一次"
    assert len(re.findall(r"\bmerged\+\+", block)) == 1, "merged 只应在命中分支自增一次"


def test_seed_words_have_682_unique_entries():
    """SEED_WORDS 下架两条重复词后为 682 条，且 (hw,pos,gloss) 与归一词头都不再撞。

    a1-0544/a1-0545 与 a1-0034/a1-0052 的 hw+pos+gloss 逐字相同（教材第 10 页与
    第 23 页重复收录），是先于本任务就存在的数据缺陷。归一词头唯一是 applyMerge
    二级索引成立的前提 —— 有重复时索引只能保留一条，另一条永远合不进去。

    变异验证（已实跑确认红）：把 a1-0544 塞回 SEED_WORDS → 682 断言与
    「(hw,pos,gloss) 无重复」「归一词头无碰撞」三条同时红。
    """
    from collections import Counter
    seeds = _seed_words()
    assert len(seeds) == 682, "SEED_WORDS 应为 682 条，实际 %d" % len(seeds)

    ids = [w["id"] for w in seeds]
    assert len(set(ids)) == 682, "SEED_WORDS 有重复 id"
    for gone in ("a1-0544", "a1-0545"):
        assert gone not in set(ids), "%s 是重复条目，必须已下架" % gone
    for kept in ("a1-0034", "a1-0052"):
        assert kept in set(ids), "%s 是保留的那一条，不得误删" % kept

    triples = Counter((w["hw"], w.get("pos", ""), w.get("gloss", "")) for w in seeds)
    dup_triples = sorted(k for k, v in triples.items() if v > 1)
    assert not dup_triples, "SEED_WORDS 仍有 hw/pos/gloss 完全相同的重复词：%s" % dup_triples

    norms = Counter(_norm_hw_py(w["hw"]) for w in seeds)
    dup_norms = sorted(k for k, v in norms.items() if v > 1)
    assert not dup_norms, "SEED_WORDS 归一词头碰撞（applyMerge 二级索引会漏词）：%s" % dup_norms


def test_seed_words_removal_does_not_touch_core_id_set():
    """下架的两个 id 都不在 CORE_WORD_SEED_IDS 里，「恰好 213」的断言不受影响。"""
    ids = set(_core_seed_ids())
    for gone in ("a1-0544", "a1-0545"):
        assert gone not in ids, "%s 若在核心集里，下架会把核心词数打成 212" % gone
    assert len(ids) == 213, "核心词 id 数必须仍是 213"


def test_seed_id_aliases_map_removed_ids_to_kept_ones():
    """SEED_ID_ALIASES 精确映射「已下架 id → 保留 id」，两侧都对得上 SEED_WORDS。

    变异验证（已实跑确认红）：把 value 写成一个不存在的 id → 「新 id 必须仍在」断言红；
    把 key 写成一个仍在表里的 id → 「旧 id 必须已下架」断言红。
    """
    assert "const SEED_ID_ALIASES" in _WORKBENCH, "缺少 SEED_ID_ALIASES 常量"
    at = _WORKBENCH.index("const SEED_ID_ALIASES")
    aliases = json.loads(_slice_balanced(_WORKBENCH, at, "{", "}"))
    assert aliases == {"a1-0544": "a1-0034", "a1-0545": "a1-0052"}, (
        "别名表与本次下架的两条重复词不一致：%s" % aliases
    )
    seed_ids = {w["id"] for w in _seed_words()}
    for old, new in aliases.items():
        assert old not in seed_ids, "%s 仍在 SEED_WORDS 里，不该出现在别名表左侧" % old
        assert new in seed_ids, "%s 不在 SEED_WORDS 里，别名会把进度搬到另一张孤儿卡上" % new


def test_alias_migration_moves_every_store_and_drops_stale_words():
    """migrateSeedIdAliases 必须扫 cards/log/wrong 三个库 + 清掉残留的 S.words 条目。

    老用户 localStorage 里可能已有 a1-0544 的 FSRS 进度；只删词不迁进度，
    S.cards["a1-0544"] 就成了 wordById() 查不到的孤儿卡 —— 违反 ADR 的首要约束
    「进度一致性 MUST，FSRS 进度零丢失」。

    变异验证（已实跑确认红）：
      - 删掉 move(S.wrong, ...) 那一行 → 三库计数断言红；
      - 把 delete 挪进 if 里（只在覆盖时删）→ node 探针的幂等断言红。
    """
    body = _alias_migration_body()
    for store in ("S.cards", "S.log", "S.wrong"):
        calls = re.findall(r"move\(\s*%s\s*," % re.escape(store), body)
        assert len(calls) == 1, (
            "%s 应恰好被 move 一次，实际 %d 次" % (store, len(calls))
        )
    deletes = re.findall(r"delete store\[oldId\]", body)
    assert len(deletes) == 1, "旧 key 删除应恰好一处（幂等性的唯一来源），实际 %d 处" % len(deletes)
    assert "wins(old, store[newId])" in body, "两边都有记录时必须走 wins 比较，不能无脑覆盖"
    assert re.search(r"\(a\.reps \|\| 0\) > \(b\.reps \|\| 0\)", body), (
        "卡片取舍必须先比 reps（复习次数）"
    )
    assert re.search(r"\(a\.due \|\| 0\) > \(b\.due \|\| 0\)", body), (
        "reps 相同再比 due（间隔更长 = 记得更牢）"
    )
    stale = re.findall(
        r"S\.words\.filter\(w => !Object\.prototype\.hasOwnProperty\.call\(SEED_ID_ALIASES, w\.id\)\)",
        body,
    )
    assert len(stale) == 1, (
        "必须把仍带已下架 id 的 S.words 条目剔掉（老 localStorage 词表里还留着），实际 %d 处" % len(stale)
    )
    assert re.search(r"\breturn\s+changed\s*;", body), (
        "必须沿用 backfillCoreWords 的 return changed 契约，仅在真变更时落盘"
    )


def test_alias_migration_runs_before_backfill_at_both_startup_sites():
    """同步启动与 idbHydrate 后的重载分支都必须先跑迁移、再跑 backfill。

    只挂在同步启动处的话，IDB 里更新的旧词表会在 hydrate 后重新灌回孤儿卡。
    顺序也不能反 —— backfill 会遍历 S.words，迁移得先把已下架条目清掉。

    变异验证（已实跑确认红）：把 updated 分支里的迁移调用删掉 → 计数断言 2 变 1 红。
    """
    call = "if (migrateSeedIdAliases()) { saveWords(); saveCards(); saveLog(); saveWrong(); }"
    backfill = "if (backfillCoreWords()) saveWords();"

    startup = _WORKBENCH.split("loadAll();")[1].split("(async () => {")[0]
    assert call in startup, "同步启动路径缺少 id 归并迁移"
    assert startup.index(call) < startup.index(backfill), "迁移必须在 backfill 之前"

    async_block = _WORKBENCH.split("(async () => {")[1].split("})();")[0]
    updated = async_block.split("if (updated) {")[1].split("console.log")[0]
    assert "loadAll();" in updated, "切片没落在 hydration 后的更新分支上"
    assert call in updated, "IDB 更新后重新 loadAll 也必须跑一次幂等迁移"
    assert updated.index(call) < updated.index(backfill), "迁移必须在 backfill 之前"

    assert _WORKBENCH.count(call) == 2, (
        "迁移调用应恰好两处（同步启动 + hydrate 重载），实际 %d 处" % _WORKBENCH.count(call)
    )


def test_merge_and_alias_migration_behave_under_node():
    """动态探针：把真实 normHw / applyMerge / migrateSeedIdAliases 抽出来在 node 里真跑。

    静态正则只能证明「代码长这样」，证明不了「二次导入是 no-op」。
    tools/wb_merge_probe.mjs 用真实 d:/Ran/Goethe_A1/delector_custom_words.json
    连导两次，并对迁移做三组进度取舍 + 幂等复跑。
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        import pytest
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    probe = _ROOT / "tools" / "wb_merge_probe.mjs"
    assert probe.exists(), "缺少 tools/wb_merge_probe.mjs 动态探针"
    res = subprocess.run(
        ["node", str(probe), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT),
    )
    assert res.returncode == 0, "探针执行失败：\n%s\n%s" % (res.stdout, res.stderr)
    out = json.loads(res.stdout)

    # 1) 双次导入：第二次是纯 no-op
    imp = out["doubleImport"]
    if imp.get("skipped"):
        import pytest
        pytest.skip("源词库不存在：%s" % imp.get("reason"))
    assert imp["afterFirst"] == imp["afterSecond"], (
        "二次导入必须是 no-op，实际 %d → %d" % (imp["afterFirst"], imp["afterSecond"])
    )
    assert imp["dupNormHwAfterFirst"] == 0, (
        "首次导入后就不该有归一词头重复：%s" % imp["dupSamples"]
    )
    assert imp["dupNormHwAfterSecond"] == 0, "二次导入后出现重复词头：%s" % imp["dupSamples"]
    assert imp["merged"] > 0 and imp["added"] > 0, "命中/新增计数不该有一边为 0"
    assert imp["merged"] + imp["added"] == imp["incoming"], "命中 + 新增必须等于导入词数"
    assert imp["coreTaggedAfterSecond"] >= imp["coreTaggedBefore"], (
        "导入不得抹掉 core tag：%d → %d"
        % (imp["coreTaggedBefore"], imp["coreTaggedAfterSecond"])
    )
    assert imp["idsChanged"] == 0, "合并不得改写已有词的 id（会造孤儿卡）"
    assert imp["seedTurnedCustom"] == 0, "合并不得把种子词标成 custom（会混进同步导出）"

    # 2) 大小写敏感：sie/Sie、essen/Essen、leben/Leben 保持两条
    case = out["caseSensitivity"]
    assert case["normHwSie"] == "Sie" and case["normHwsie"] == "sie", (
        "normHw 把大小写吃掉了：%s" % case
    )
    for pair in ("sie|Sie", "essen|Essen", "leben|Leben"):
        assert case["pairs"][pair] == 2, (
            "%s 必须保持两条独立词条，实际 %d 条" % (pair, case["pairs"][pair])
        )

    # 3) 别名迁移：搬进度、按 reps/due 取多者、幂等、不留孤儿卡
    mig = out["aliasMigration"]
    assert mig["movedWhenTargetEmpty"] == {"reps": 5, "due": 200}, (
        "目标位为空时应整条搬过去，实际 %s" % mig["movedWhenTargetEmpty"]
    )
    assert mig["keptHigherReps"] == 7, "两边都有时应保留 reps 更大的一条"
    assert mig["keptHigherRepsReversed"] == 9, "反向摆放也必须保留 reps 更大的一条"
    assert mig["keptLaterDueOnRepsTie"] == 999, "reps 相同应保留 due 更晚的一条"
    assert mig["wrongKeptHigherN"] == 4, "错题本应保留错得更多的一条"
    assert mig["oldKeysLeft"] == 0, "旧 id 必须被删干净"
    assert mig["staleWordsLeft"] == 0, "S.words 里不得残留已下架 id 的词条"
    assert mig["firstRunChanged"] is True, "首次迁移必须返回 changed = true"
    assert mig["secondRunChanged"] is False, "二次迁移必须返回 false（幂等）"
    assert mig["snapshotStable"] is True, "二次迁移不得改动任何数据（幂等）"
    assert mig["orphanCards"] == 0, "迁移后不得留下 wordById 查不到的孤儿卡"
