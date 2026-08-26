import re
from pathlib import Path


ROOT = Path(__file__).parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
WRITER = (ROOT / "static" / "js" / "writer.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
SW = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
GRADLE = (ROOT / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
MAIN_ACTIVITY = (
    ROOT / "android" / "app" / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
).read_text(encoding="utf-8")


def _rule_body(selector_regex, must_contain=None):
    """按括号深度取出 CSS 规则体。

    不用 split("}")：规则体里可能嵌套（媒体块、@supports），split 会在第一个
    右花括号处截断，拿到半截规则还看不出错 —— 断言于是在不完整的文本上做，
    要么假绿要么报得莫名其妙。must_contain 用来在同名选择器的多条规则里
    挑出想要的那一条（base vs 各断点覆盖）。
    """
    for m in re.finditer(selector_regex, STYLE):
        depth, j = 1, m.end()
        while depth and j < len(STYLE):
            if STYLE[j] == "{":
                depth += 1
            elif STYLE[j] == "}":
                depth -= 1
            j += 1
        body = STYLE[m.end():j - 1]
        if must_contain is None or must_contain in body:
            return body
    raise AssertionError(
        f"CSS 里找不到匹配 {selector_regex} 的规则"
        + (f"（且规则体含 {must_contain!r}）" if must_contain else "")
    )


def test_mobile_writer_has_panel_sheet_controls():
    assert 'id="writer-mobile-panel-trigger"' in INDEX
    assert 'id="writer-mobile-panel-sheet"' in INDEX
    assert "writer-mobile-panel-sheet" in STYLE


def test_writer_supports_tap_to_open_error_details():
    assert "editor.addEventListener('click'" in WRITER
    assert "selectWriterSpan" in WRITER


def test_android_disables_inlay_hints_by_default():
    assert "navigator.userAgent" in WRITER
    assert "inlayEnabled" in WRITER


def test_version_is_consistent_across_release_surfaces():
    """版本号有两个必须一致的落点：sw.js 的 CACHE_NAME（决定旧缓存何时被清）
    与 build.gradle 的 fallback（无 CI 环境变量时本地构建的版本）。

    断言两者相等，而不是断言某个字面量 —— 写死字面量的测试每次 bump 都要改，
    而改测试的人迟早只改测试、不查它守的东西是否还成立（v4.4.4 就是这样：
    测试守着 index.html 的 ?v= 查询串，而那个机制早已挡不住任何东西）。
    """
    sw_match = re.search(r"delector-static-v(\d+\.\d+\.\d+)", SW)
    assert sw_match, "sw.js 里找不到 delector-static-vX.Y.Z 形式的 CACHE_NAME"
    gradle_name = re.search(r'DELECTOR_VERSION_NAME"\)\s*\?:\s*"(\d+\.\d+\.\d+)"', GRADLE)
    assert gradle_name, "build.gradle 里找不到 DELECTOR_VERSION_NAME 的 fallback"
    assert sw_match.group(1) == gradle_name.group(1), (
        f"版本不一致：sw.js={sw_match.group(1)} vs build.gradle={gradle_name.group(1)}"
    )

    # index.html 顶栏那句 "System · vX.Y.Z Online" 是用户判断「前端刷新了没有」的
    # 唯一肉眼指标。v4.4.5 发版时漏 bump 了它，于是修好的升级链路看起来像没生效
    # —— 缓存闸门是对的，指示灯是坏的，而指示灯说什么用户就信什么。
    index_label = re.search(r"System · v(\d+\.\d+\.\d+) Online", INDEX)
    assert index_label, "index.html 顶栏找不到 'System · vX.Y.Z Online' 版本标签"
    assert index_label.group(1) == gradle_name.group(1), (
        f"版本不一致：index.html 顶栏={index_label.group(1)} vs build.gradle={gradle_name.group(1)}"
    )

    # versionCode 编码规则 major*10000 + minor*100 + patch，必须与 versionName 对得上。
    # 旧规则 major*100+minor*10+patch 在 3.10.0 与 4.0.0 上撞车过，而 versionCode
    # 撞车意味着新版无法覆盖安装旧版。
    gradle_code = re.search(r'DELECTOR_VERSION_CODE"\)\s*\?:\s*"(\d+)"', GRADLE)
    assert gradle_code, "build.gradle 里找不到 DELECTOR_VERSION_CODE 的 fallback"
    major, minor, patch = (int(x) for x in gradle_name.group(1).split("."))
    assert int(gradle_code.group(1)) == major * 10000 + minor * 100 + patch

    # tag → 构建的注入链路
    assert 'System.getenv("DELECTOR_VERSION_NAME")' in GRADLE
    assert 'System.getenv("DELECTOR_VERSION_CODE")' in GRADLE
    assert "versionName releaseVersionName" in GRADLE
    assert "versionCode releaseVersionCode" in GRADLE

    # CI 的非 tag 回落路径不许再自存一份版本号。原来它硬编码 4.4.0/40400，
    # 而 build.gradle 已走到别处 —— 副本漂了不会构建失败，只会产出 versionCode
    # 偏小、装不上现有设备的 APK（versionCode 必须严格递增）。
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(encoding="utf-8")
    assert not re.search(r'VER="\d+\.\d+\.\d+"', workflow), (
        "build-release.yml 又硬编码了版本号，应从 build.gradle 读取"
    )
    assert "DELECTOR_VERSION_NAME" in workflow and "android/app/build.gradle" in workflow, (
        "build-release.yml 的回落路径应解析 build.gradle 的 fallback"
    )


def test_android_reunpacks_static_assets_on_version_change():
    """APK 覆盖安装不清 getFilesDir()，而 copyAssetFile() 见目标已存在就跳过，
    于是升级后旧前端永远不被覆盖 —— 只有卸载重装才好（v4.4.5 修的就是这个）。
    闸门是 versionCode 标记文件；标记不符就整个 static/ 删掉重解包。
    """
    assert "syncStaticAssets" in MAIN_ACTIVITY
    assert "BuildConfig.VERSION_CODE" in MAIN_ACTIVITY
    assert "static.version" in MAIN_ACTIVITY
    # BuildConfig 的生成在 AGP 8 各版本默认值不同，必须显式开，否则只在 CI 编译时炸
    assert "buildConfig true" in GRADLE
    # 删除范围钉死在 filesDir/static：同级就躺着 delector.db / progress.db，
    # 装着用户全部学习数据，删错一级不可恢复
    assert 'new File(dataDir, "static")' in MAIN_ACTIVITY
    assert "getAbsolutePath().equals(expected.getAbsolutePath())" in MAIN_ACTIVITY


def test_frontend_cache_gate_is_server_side():
    """?v= 查询串对 APK 升级无效：磁盘上那份文件本身就是旧的，
    请求 URL 与响应内容是一对自洽的旧配对，浏览器没有理由怀疑。
    而它连覆盖面都不全 —— main.js 的 ES module import 全是裸路径。
    真正的闸门在 server 端强制回源校验，手工版本串已退役。
    """
    assert "add_frontend_no_cache_headers" in SERVER
    assert '"Cache-Control"' in SERVER
    assert "?v=" not in INDEX, "index.html 不该再有手工维护的 ?v= 版本串"
    assert "?v=" not in SW, "sw.js 的缓存键不该带 ?v=，真实请求匹配不上"


def test_writer_rows_share_one_click_contract():
    """三个 tab 的行为必须一致：整行点击 = 定位/预览（无副作用），
    行内按钮 = 破坏性或次要操作，且必须拦住冒泡免得连带触发整行动作。
    版本快照原本是唯一的例外（整行不可点、藏一个 👁️ 查看按钮）。
    """
    assert 'onclick="previewEssayVersion(${v.id})" title="点击预览此快照内容"' in WRITER
    assert '<div class="version-actions" onclick="event.stopPropagation()">' in WRITER
    assert "👁️ 查看" not in WRITER, "整行点击已替代该按钮"


def test_jump_to_sentence_closes_mobile_panel():
    """跳转结果（编辑器滚动 + 闪烁）发生在 bottom sheet 背后，
    不收起面板等于什么都没发生。一处改动覆盖句子导航与问题清单两条路径。
    """
    body = WRITER.split("export function jumpToSentence(")[1].split("\nexport ")[0]
    assert "closeWriterMobilePanel()" in body


def test_open_writer_problem_switches_to_diag_only_for_errors():
    """错误详情卡 #writer-err-detail 在 diag pane 内，不切 tab 就写进 display:none 的面板。
    但 warning 分支不渲染详情，切过去只会露出上一次点击留下的陈旧错误卡
    （resetErrorDetailView 只在换文/应用修改时跑），所以切 tab 必须留在 error 分支里。
    """
    body = WRITER.split("export function openWriterProblem(")[1].split("\nexport ")[0]
    assert "switchWriterPanelTab('diag')" in body
    error_branch = body.split("if (kind === 'error')")[1]
    assert "switchWriterPanelTab('diag')" in error_branch, "切 tab 必须在 error 分支内"


def test_toggle_writer_mobile_panel_actually_toggles():
    """trigger 按钮常驻可见，面板已开时再点必须收起。
    v4.4.4 的实现只 add class 从不 remove，再点无反应、还会强制切回问题清单，
    把用户切到版本快照的选择覆盖掉。
    """
    body = WRITER.split("export function toggleWriterMobilePanel(")[1].split("\nexport ")[0]
    assert "classList.contains('mobile-panel-open')" in body
    assert "closeWriterMobilePanel()" in body
    # 自动切 tab 只在首次打开时发生，之后不再覆盖用户（或 B2）选定的 tab
    assert "writerMobilePanelDidAutoSwitch" in body


def test_version_row_hover_matches_other_rows():
    # 用 _rule_body 而不是 split(".version-item {")：并集规则
    # （.writer-nav-item, .writer-problem-row, .version-item { … }）里也以
    # ".version-item {" 结尾，且出现得更早，split 会抓错那一条。
    version_item = _rule_body(r"\.version-item\s*\{", "cursor: pointer")
    assert "cursor: pointer" in version_item
    version_hover = _rule_body(r"\.version-item:hover\s*\{")
    assert "translateX(2px)" in version_hover


def test_mobile_sheet_is_geometrically_stable():
    """v4.4.5 的 sheet 是 bottom-anchored + 无 top + 只用 max-height，
    高度跟内容走 —— 切 tab、错误卡填内容、问题清单从空变 N 条时顶边一路跳，
    整个面板在眼前挪位置，"像收起了一样"。v4.4.6 改用 height 把几何固定成
    同一矩形：内容多时内部滚动，sheet 自身位置不动。
    配套：内层列表去掉 max-height / overflow-y，让滚动只归 sheet 管，
    否则内层（460/320/220px）几乎占满 600px sheet，手指被它吃掉，
    外层 sheet 永远滚不到底。
    """
    # 选那个把 .writer-sidebar 改成 position: fixed 的块（底边 bottom-sheet
    # 几何在这一块里定义，规则改成 max-height → height 也是这一块）。
    # 笨办法：找出所有 ".writer-sidebar {" 的位置，挑后面紧跟
    # "position: fixed" 的那个，然后按括号深度读到匹配的 }。
    sidebar_idxs = [m.end() for m in re.finditer(r"\.writer-sidebar\s*\{", STYLE)]
    fixed_idx = next(
        i for i in sidebar_idxs if "position: fixed" in STYLE[i:i + 300]
    )
    depth = 1
    j = fixed_idx
    while depth and j < len(STYLE):
        c = STYLE[j]
        if c == "{": depth += 1
        elif c == "}": depth -= 1
        j += 1
    sheet = STYLE[fixed_idx:j - 1]

    assert "height: min(" in sheet, (
        "移动端 sheet 必须用 height 固定几何，不能让高度跟内容走（会整块跳）"
    )
    assert "max-height: none" in sheet, (
        "sheet 必须显式解掉基规则的 max-height 帽子，让这个断点的几何自我描述完整"
    )
    assert "overflow-y: auto" in sheet, "sheet 自身必须能滚动"

    # 关键：移动端 sheet 的 .writer-pane 不能被父容器压扁
    assert "flex-shrink: 0" in STYLE.split(".writer-pane {")[1].split("}")[0], (
        "父容器高度固定后，pane 缺 flex-shrink:0 会被压扁、溢出但滚不动"
    )


def test_desktop_sidebar_is_internally_scrollable_when_tall():
    """桌面端 .writer-sidebar 是 sticky 列且 align-items: start，高度跟内容走。
    没有 max-height + overflow-y 时，一旦内容高过视口，超出的下半截就永远停在
    视口外 —— sticky 只在自己的 grid 行内平移，页面滚到底也带不出来。
    这是 v4.4.6 移动端修复的同族缺陷（v4.4.7 收口）。
    """
    sidebar = _rule_body(r"\.writer-sidebar\s*\{", "position: sticky")

    assert "max-height: calc(100dvh" in sidebar, (
        "桌面 sidebar 必须有视口相关的 max-height 帽，否则内容高过视口时下半截滚不到"
    )
    assert "overflow-y: auto" in sidebar, "加了帽子就必须让 sidebar 自己能滚"
    assert not re.search(r"(?<!max-)height:", sidebar), (
        "桌面 sticky 列只能用 max-height；写死 height 会在内容少时撑出一片空白"
    )

    # tab 条吸在滚动容器顶部，切 tab 不必先滚回去找
    tabs = _rule_body(r"\.writer-panel-tabs\s*\{", "position: sticky")
    assert "top: 0" in tabs, "tab 条要吸顶就必须给 top"
    assert "background:" in tabs, "吸顶的 tab 条需要不透明背景盖住滚过的内容"

    # 滚动只有一个主人：内层三个列表不许再各开一个滚动区
    for sel in ("writer-sent-nav-list", "writer-problem-list", "writer-version-list"):
        body = _rule_body(rf"\.{sel}\s*\{{")
        assert "max-height" not in body, (
            f".{sel} 不能有 max-height 帽 —— 内层吃掉滚动后外层 sidebar 底部滚不到"
        )
        assert "overflow-y" not in body, (
            f".{sel} 不能自己开滚动区，滚动归 .writer-sidebar 一个人管"
        )


def test_writer_rows_have_active_press_feedback():
    """三种可点击行在触屏上只有 :hover 等于按下去毫无反馈
    （:hover 在触屏不触发，或点完粘住不放）。:active 是触屏唯一可靠的按压态。
    """
    for sel, expected in (
        ("writer-nav-item", "rgba("),
        ("writer-problem-row", "var(--paper-deep)"),
        ("version-item", "var(--paper-deep)"),
    ):
        body = _rule_body(rf"\.{sel}:active\s*\{{")
        assert "background" in body and expected in body, (
            f".{sel}:active 必须给出可见的按压背景（期望含 {expected}）"
        )

    # 安卓 WebView 自带的灰色点击高亮会和自定义按压色叠着闪一下。
    # 必须钉在这三行的并集规则上：全文搜 "in STYLE" 是不够的 —— 文件里另有
    # 一处无关规则也清了 tap-highlight，删掉这条并集规则测试照样绿（已实测）。
    union = _rule_body(
        r"\.writer-nav-item,\s*\.writer-problem-row,\s*\.version-item\s*\{"
    )
    assert "-webkit-tap-highlight-color: transparent" in union, (
        "三行需要清掉系统点击高亮，否则和自定义 :active 背景叠加"
    )

    # .version-item:active 与 .version-item.version-checkpoint 特异性相同（同为两个类的量级），
    # 同分时源序决定胜负。写在 checkpoint 之前的话，checkpoint 行按下去不会有任何反馈 ——
    # 而那恰恰是最常被点的一批行。
    assert STYLE.index(".version-item:active") > STYLE.index(
        ".version-item.version-checkpoint"
    ), (
        ".version-item:active 必须排在 .version-item.version-checkpoint 之后，"
        "否则 checkpoint 行没有按压反馈"
    )


def test_no_undefined_css_variables_in_writer_surfaces():
    """CSS 变量拼错不会报错，只会让颜色静默回退成继承色 —— 肉眼几乎看不出，
    但那一处的设计意图就丢了。--ink-secondary 从未在 :root 定义过（v4.4.7 修）。

    这是个棘轮：KNOWN_LEGACY_UNDEFINED 现在是空的 —— 原先挂在上面的 5 个历史欠账
    (--border / --font-sans / --note-blue / --paper-accent / --paper-warm)
    已在 :root 定义完毕。新增未定义变量会让这个测试变红；确实一时修不了的
    才临时进这个集合，且下面第二条断言会催着修完就删掉它。
    """
    # 声明式匹配不能按行锚定：`--hl-A1: #E3EFFB;  --hl-A1-ink: #1D548C;`
    # 这样一行两个声明的写法在文件里很常见，^ 锚定只看得见第一个，
    # 于是把第二个误判成"未定义"（写这个测试时就先踩了一次）。
    declared = set(re.findall(r"(--[\w-]+)\s*:", STYLE))
    used = set(re.findall(r"var\(\s*(--[\w-]+)", STYLE))

    KNOWN_LEGACY_UNDEFINED = set()
    undefined = used - declared - KNOWN_LEGACY_UNDEFINED
    assert not undefined, f"用到了未定义的 CSS 变量：{sorted(undefined)}"

    # 欠账修完后要记得把条目从上面删掉，否则这个集合会慢慢变成一张"永久豁免"名单
    still_missing = KNOWN_LEGACY_UNDEFINED - declared
    assert still_missing == KNOWN_LEGACY_UNDEFINED, (
        f"这些历史欠账已经修好了，请从 KNOWN_LEGACY_UNDEFINED 里删掉："
        f"{sorted(KNOWN_LEGACY_UNDEFINED - still_missing)}"
    )


def _style_without_comments():
    """去掉 CSS 注释再找选择器。

    否则注释里提到的 `.btn-xs`、`.btn-del` 会被当成已定义 —— 这个测试本来就是
    为了抓"类名写了但规则不存在"，而解释性注释恰恰最爱提这些类名，
    不剥注释等于自己把要抓的东西喂给自己（写下面那条棘轮时就先踩了一次）。
    """
    return re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)


def _btn_classes_used_in_markup():
    used = set()
    for src in (INDEX, WRITER):
        for attr in re.findall(r'class="([^"]*)"', src):
            used.update(t for t in attr.split() if t.startswith("btn"))
        # writer.js 有几处是运行时挂类，不在 class="" 里
        for t in re.findall(r"classList\.(?:add|toggle|remove)\(\s*['\"]([\w-]+)", src):
            if t.startswith("btn"):
                used.add(t)
    return used


def test_every_btn_class_in_markup_has_a_css_rule():
    """按钮类名拼错/漏定义不会报错，只会静默回退成裸 .btn。

    v4.4.8 前 .btn-xs / .btn-del / .btn-secondary 三个类在 HTML/JS 里共用了 15 处，
    但 CSS 里一条规则都没有：那些按钮全都拿着 .btn 的 36px 高和 1rem 内距在渲染，
    看起来"能用"，所以谁都没发现 —— 于是作者改用 inline style 逐个硬调
    （index.html:95-97,610,678 就是这么来的）。这条棘轮让下一次漏定义直接变红。
    """
    defined = set(re.findall(r"\.(btn[\w-]*)", _style_without_comments()))
    missing = _btn_classes_used_in_markup() - defined
    assert not missing, f"这些按钮类在 HTML/JS 里用了但 CSS 里没有规则：{sorted(missing)}"


def test_btn_size_modifiers_all_reset_the_base_min_height():
    """.btn 的 min-height:36px 会一直兜着，所以尺寸类光改 padding 和 font-size
    是缩不小的 —— 每一档都必须显式 !important 重置 min-height 才真的生效。

    `.btn-sm` 就是靠反例证明这一点的：它长期只写了 padding/字号，于是 4 处
    调用点（index.html:542 保存快照、1167-1169 伴读面板三个键）实际全是 36px，
    名字叫 sm 而尺寸和普通按钮一样，没人发现。

    尺寸阶梯保持 36 → 30 → 26 三档单调递减；30px 取自 index.html:95-97
    当初手写的 inline `min-height:30px`。
    """
    base = _rule_body(r"\.btn\s*\{")
    assert "min-height: 36px" in base, "基规则的 36px 前提变了，本测试的理由需要重写"

    heights = {}
    for name, expected in (("btn-sm", 30), ("btn-xs", 26)):
        body = _rule_body(rf"\.{name}\s*\{{")
        m = re.search(r"min-height:\s*(\d+)px\s*!important", body)
        assert m, f".{name} 必须带 !important 重置 min-height——否则盖不住 .btn 的 36px"
        heights[name] = int(m.group(1))
        assert int(m.group(1)) == expected, f".{name} 期望 {expected}px，实际 {m.group(1)}px"

    assert 36 > heights["btn-sm"] > heights["btn-xs"], (
        f"尺寸阶梯必须单调递减，现在是 36 / {heights['btn-sm']} / {heights['btn-xs']}"
    )
    assert re.search(r"padding:\s*0\s+0\.5rem\s*!important", _rule_body(r"\.btn-xs\s*\{"))


def test_btn_secondary_is_visibly_different_from_btn_ghost():
    """`.btn-secondary` 与 `.btn-ghost` 同外观 = 把状态指示器做成隐形的。

    两处**只靠这个类的外观**传达状态，没有别的视觉线索：

    - `writer.js:261` 用 ghost ↔ secondary 的互斥切换表示格提示 ON/OFF
    - `writer.js:905` 用 accent → secondary 表示「已存为 Anki 语法卡」

    v4.4.8 首次补上 `.btn-secondary` 规则时，正是照着 `.btn-ghost` 逐字写的
    （当时的理由是"目前同外观，将来再分化"）—— 结果格提示按钮按下去只有文字
    在变，背景边框一动不动。**在此之前反而是能看出区别的**：类没定义，OFF 态
    回退成裸 .btn，无边框无底色。等于"补上缺失的规则"这个动作本身弄坏了状态显示。

    所以这里断言的不是某个具体配色，而是**两者的声明必须不同**。
    """
    def declarations(selector):
        body = _rule_body(rf"{selector}\s*\{{")
        return {
            (m.group(1).strip(), m.group(2).strip())
            for m in re.finditer(r"([\w-]+)\s*:\s*([^;]+);", body)
        }

    ghost, secondary = declarations(r"\.btn-ghost"), declarations(r"\.btn-secondary")
    assert ghost and secondary, "两条规则都得存在，否则下面的比较没有意义"
    assert ghost != secondary, (
        "`.btn-secondary` 与 `.btn-ghost` 的声明完全相同，格提示 ON/OFF 与"
        "「已存为卡片」两处状态切换会变成隐形的（只有文字在变）。"
        f"当前共同声明：{sorted(ghost)}"
    )

    # hover 态同样不能塌成一样 —— 否则鼠标一悬停两者又无从区分
    assert declarations(r"\.btn-ghost:hover") != declarations(r"\.btn-secondary:hover"), (
        "两者的 :hover 声明也相同，悬停时状态又变回不可区分"
    )


def test_destructive_surfaces_use_the_danger_token():
    """删除类控件不得写死红色字面量，也不得借用 --cherry。

    迁移前三处删除控件是三种不同的红：`.btn-del` 用 --danger(#B03030)、
    `.card-del-btn` 用 --cherry(同色但语义是"答错")、`.article-row-del` 用
    硬编码 #dc2626（**明显更亮的另一种红**）。同一个动作三种红，且其中两处
    改 token 也带不动。

    --cherry 仍然合法 —— 但只用于答错/错误反馈（cloze.js:40、main.js:205,253
    的报错文字就该留着用它），不用于破坏性操作。
    """
    bare = _style_without_comments()

    for selector in (r"\.btn-del", r"\.btn-del:hover", r"\.card-del-btn:hover",
                     r"\.article-row-del:hover"):
        body = _rule_body(rf"{selector}\s*\{{")
        assert "var(--cherry)" not in body, (
            f"{selector} 用了 --cherry；破坏性操作应该用 --danger"
        )
        assert not re.search(r"#dc2626|#fde8e8|rgba\(220,\s*38,\s*38", body), (
            f"{selector} 里还有写死的红色字面量，应该走 --danger"
        )

    # 至少 .btn-del 与 .card-del-btn 要真的引用 token（article-row-del 用
    # rgba() 调透明度，无法直接套 var()，只断言它不再是另一种红）
    for selector in (r"\.btn-del", r"\.card-del-btn:hover"):
        assert "var(--danger)" in _rule_body(rf"{selector}\s*\{{"), \
            f"{selector} 应该引用 --danger"

    # 删除按钮的红不该再靠 inline style 挂在 HTML 上 —— 那样既绕过 token
    # 体系又没有 hover 态（index.html:684 的删便签键原先就是这样）
    for m in re.finditer(r'<button[^>]*style="[^"]*var\(--cherry\)[^"]*"[^>]*>', INDEX):
        assert "del" not in m.group(0), (
            f"删除按钮还在用 inline 的 --cherry，应该改挂 .btn-del 类：{m.group(0)[:120]}"
        )


def test_no_rule_is_fully_shadowed_by_btn_xs_important():
    """`.btn-xs` 三条声明全带 !important，同元素上的伴生类会被整条盖死。

    `.version-restore-btn` 就是这么变成死规则的：它设 font-size / padding /
    border-radius 三项，而调用点写的是 `btn btn-ghost btn-xs version-restore-btn`
    —— `.btn-xs` 的 !important 把三项全盖掉，一条声明都没生效。删掉比留着强：
    留着会让下一个人以为改它有用。

    这里检查所有与 .btn-xs 同时出现在 class 里的伴生类，其声明不能被
    .btn-xs 的 !important 属性集完全覆盖。
    """
    xs_important = {
        m.group(1)
        for m in re.finditer(r"([\w-]+)\s*:[^;]*!important\s*;",
                             _rule_body(r"\.btn-xs\s*\{"))
    }
    assert xs_important, ".btn-xs 里没有 !important 声明，本测试的前提变了"

    companions = set()
    for src in (INDEX, WRITER):
        for attr in re.findall(r'class="([^"]*)"', src):
            classes = attr.split()
            if "btn-xs" in classes:
                companions.update(c for c in classes
                                  if c not in {"btn", "btn-xs"} and not c.startswith("btn-"))

    bare = _style_without_comments()
    for cls in sorted(companions):
        if not re.search(rf"^\.{re.escape(cls)}\s*\{{", bare, re.M):
            continue                                  # 没有规则，谈不上被盖
        props = {
            m.group(1)
            for m in re.finditer(r"([\w-]+)\s*:", _rule_body(rf"\.{re.escape(cls)}\s*\{{"))
        }
        assert not (props and props <= xs_important), (
            f".{cls} 的全部声明 {sorted(props)} 都被 .btn-xs 的 !important 盖掉了，"
            f"整条规则不生效。要么删掉，要么给需要生效的那几项加 !important"
        )


def test_btn_del_uses_the_danger_token_and_outranks_btn_ghost():
    """--danger 与 --cherry 目前同色，但语义分开：cherry = 答错反馈（SRS/quiz/
    错误下划线），danger = 破坏性操作。同色时合并看着更省，可一旦要单独调其中
    一个（比如把答错色调柔和），共用一个 token 就得先把几十处调用点分类，
    那时候已经分不清哪处是哪个意思了。
    """
    root = _rule_body(r":root\s*\{")
    assert re.search(r"--danger:\s*#B03030", root)
    assert re.search(r"--danger-strong:\s*#C84444", root)

    body = _rule_body(r"\.btn-del\s*\{")
    assert "var(--danger)" in body, ".btn-del 应该用 --danger，不要直接写死色值"

    hover = _rule_body(r"\.btn-del:hover\s*\{")
    assert "var(--danger)" in hover

    # 调用点写的是 class="btn btn-ghost btn-xs btn-del"：.btn-ghost 和 .btn-del
    # 都是单类选择器，特异度相同，只有源序能决定谁的 color 生效。
    bare = _style_without_comments()
    assert bare.index(".btn-del") > bare.index(".btn-ghost"), (
        ".btn-del 必须排在 .btn-ghost 之后，否则删除键的红字被 ghost 的字色盖掉"
    )


def test_button_rules_are_not_duplicated():
    """.deck-btn-nav 曾整块（含 :hover / :disabled）逐字重复两遍。

    完全相同的重复块不会改变渲染，所以永远不会有人因为"看起来不对"而发现它；
    真正的代价是下一个人只改了其中一份，另一份继续生效，于是"改了没用"。
    """
    bare = _style_without_comments()
    for selector in (".deck-btn-nav", ".btn-secondary", ".btn-xs", ".btn-del"):
        n = len(re.findall(rf"^{re.escape(selector)}\s*\{{", bare, re.M))
        assert n == 1, f"{selector} 的基规则出现了 {n} 次，应该只有 1 次"

