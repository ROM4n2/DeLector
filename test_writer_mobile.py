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
