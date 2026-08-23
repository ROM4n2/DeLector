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
    version_item = STYLE.split(".version-item {")[1].split("}")[0]
    assert "cursor: pointer" in version_item
    version_hover = STYLE.split(".version-item:hover {")[1].split("}")[0]
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

    # j 上面算的是 .writer-sidebar 单个规则的右花括号位置，但移动端
    # 覆盖（max-height: none 等）是在它之后、同一个 @media 媒体块里。
    # 把 j 推前到 @media 媒体块的结尾（或者下一个 @media 的开头之前）。
    next_media = STYLE.find("@media", j)
    j = next_media if next_media > 0 else len(STYLE)
    assert "height:" in sheet and "max-height:" not in sheet, (
        "移动端 sheet 必须用 height 固定几何，不能用 max-height（会跟内容走、整块跳）"
    )
    assert "overflow-y: auto" in sheet, "sheet 自身必须能滚动"

    # 内层列表在移动端不能自己再开一个滚动区
    # 找的是移动端块里"最后一次出现"的选择器 —— CSS 源序决定级联，
    # base 规则在媒体块之前，移动端覆盖必须出现在媒体块内且靠后。
    for sel in ("writer-sent-nav-list", "writer-problem-list", "writer-version-list"):
        needle = sel
        # 在媒体块（以 j 截断）中找这个选择器最后出现的规则体
        block = STYLE[STYLE.find("@media (max-width: 860px) {"):j]
        assert needle in block, f"移动端块里没出现 .{sel} 的覆盖规则"
        # 抓选择器后第一个 { ... } 块；写死用宽口选择器（base 是 ".X {…}"，
        # 移动端用 ".X, .Y, .Z {…}" 的并集，needle 后一定是 {）
        last = block.rfind(needle)
        brace = block.find("{", last)
        depth = 1
        k = brace + 1
        while depth and k < len(block):
            if block[k] == "{": depth += 1
            elif block[k] == "}": depth -= 1
            k += 1
        rule = block[brace + 1:k - 1]
        assert "max-height: none" in rule, (
            "移动端 ." + sel + " 必须解掉 max-height，否则内层吃滚动"
        )

    # 关键：移动端 sheet 的 .writer-pane 不能被父容器压扁
    assert "flex-shrink: 0" in STYLE.split(".writer-pane {")[1].split("}")[0], (
        "父容器高度固定后，pane 缺 flex-shrink:0 会被压扁、溢出但滚不动"
    )
