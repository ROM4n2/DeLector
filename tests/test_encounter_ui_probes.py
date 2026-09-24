# -*- coding: utf-8 -*-
"""遇见区 (view-encounter) SPA 骨架字符串探针。

P0 前端骨架由三块组成：
  1. index.html 新增 <main id="view-encounter" class="view">（列表 + 详情 + 加文本表单）；
  2. 德语文库 (view-home) 内加一张入口卡，携带「遇见区 i+1 短文」标记，点击 show('encounter')；
  3. main.js import './encounter.js' 并接入 show() 路由 —— 满足
     test_frontend_module_graph.py 的可达性要求。

Task A4 只做骨架，不引第三方库、不动 Python 路由 / workbench.html。此测试与
test_german_workbench.py 互不切片（它只 slice workbench.html），因此仅加
「遇见区」入口与结构断言，不碰任何 async-IIFE 定位记号。
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
ENCOUNTER_JS = (ROOT / "static" / "js" / "encounter.js").read_text(encoding="utf-8")


def _slice_function(src, name):
    """切出 `function <name>(...) { ... }` 整段（含签名，按大括号配对收尾）。

    用于把断言钉到某个具体函数体，替代「全文子串 in」这类恒真 / 无判别力弱断言
    —— 同一记号（如 Math.round(）往往在别的函数里也出现，全文匹配根本钉不住目标。
    """
    start = src.index(f"function {name}")
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"未找到 function {name} 的闭合大括号")


def _view_home_markup():
    """返回 <main id="view-home" ...>...</main> 的整段文本。"""
    start = INDEX.index('id="view-home"')
    # 从该 id 回溯到该 <main> 标签开头
    start = INDEX.rindex("<main", 0, start)
    end = INDEX.index("</main>", start)
    return INDEX[start:end]


def test_index_has_encounter_view_section():
    """index.html 必须含 <main id="view-encounter" class="view"> 结构。"""
    assert 'id="view-encounter"' in INDEX
    assert "view-encounter" in INDEX
    # 骨架结构：列表容器 + 详情容器 + 「＋ 加文本」表单入口
    assert 'id="encounter-text-list"' in INDEX
    assert "encounter-reader" in INDEX


def test_index_encounter_view_has_add_form_entry():
    """view-encounter 必须带一个「＋ 加文本」入口（内联表单开关/表单容器）。"""
    # 探针：加文本按钮文案 + 表单容器 id（主 DOM 中全局存在即可）
    assert "＋ 加文本" in INDEX or "+ 加文本" in INDEX
    assert 'id="encounter-add-form"' in INDEX or "encounter-add-form" in INDEX


def test_index_home_view_has_encounter_entry():
    """德语文库 (view-home) 内必须有进入遇见区的入口卡。"""
    home = _view_home_markup()
    assert "遇见区" in home
    assert "i+1 短文" in home
    # 入口必须真正触发 show('encounter')
    assert "show('encounter')" in home
    # 该入口标记确实落在 view-home 之内，而非顶层 nav（nav 不带遇见区入口）
    assert 'id="view-home"' in home


def test_main_js_imports_encounter_module():
    """main.js 必须 import './encounter.js'（模块图可达性契约）。"""
    assert "./encounter.js" in MAIN_JS
    assert "encounter.js" in MAIN_JS


def test_main_js_show_router_activates_encounter():
    """show() 路由遇到 'encounter' 必须触发列表渲染（惰性 show 式，不做 eager 初始化）。"""
    assert "view-encounter" in MAIN_JS or '=== "encounter"' in MAIN_JS or "view === 'encounter'" in MAIN_JS


def test_encounter_js_exports_view_hooks():
    """encounter.js 提供列表/详情渲染入口（字符串探针级的最小可达性）。"""
    assert "showView" in ENCOUNTER_JS
    assert "fetchTexts" in ENCOUNTER_JS
    assert "renderTextList" in ENCOUNTER_JS


def test_encounter_js_reuses_core_api_helper():
    """encounter.js 复用 core.js 的 api/esc 帮手，而非自行 reimplement fetch。"""
    assert "./core.js" in ENCOUNTER_JS
    assert "api(" in ENCOUNTER_JS
    assert "esc(" in ENCOUNTER_JS


# ── Task 5（i+1 就近选材）：不点开任何一篇即可按本机已背词覆盖率分组 + 标 i+1 ────
# 契约：遇见区列表按已背词覆盖率分区间排序并标出「正好读」；索引端点失败时**逐字**
# 退回既有列表行为（零破坏）。探针风格沿用本文件：读文件 + 子串/结构断言。


def _view_encounter_markup():
    """返回 <main id="view-encounter" ...>...</main> 的整段文本。"""
    start = INDEX.index('id="view-encounter"')
    start = INDEX.rindex("<main", 0, start)
    end = INDEX.index("</main>", start)
    return INDEX[start:end]


def test_encounter_view_has_i1_hint_before_list():
    """① view-encounter 段内必须有 i+1 提示条容器，且位于 #encounter-text-list 之前。"""
    view = _view_encounter_markup()
    assert 'id="enc-i1-hint"' in view
    assert "enc-i1-hint" in view
    hint_at = view.index('id="enc-i1-hint"')
    list_at = view.index('id="encounter-text-list"')
    assert hint_at < list_at, "i+1 提示条容器必须渲染在列表之前"


def test_encounter_js_imports_i1_and_deck_bridge():
    """② encounter.js 必须 import ./enc-i1.js（选材纯函数）与 ./deck-bridge.js（deck 桥）。"""
    assert "./enc-i1.js" in ENCOUNTER_JS
    assert "./deck-bridge.js" in ENCOUNTER_JS


def test_encounter_js_renders_three_band_badges_escaped():
    """③ 渲染路径含三态徽章 class，且展示字段经 esc()（XSS 安全）。"""
    assert "enc-i1-badge" in ENCOUNTER_JS
    for cls in ("enc-i1-i1", "enc-i1-easy", "enc-i1-hard"):
        assert cls in ENCOUNTER_JS, f"缺少三态徽章 class {cls}"
    # 三态文案单点定义（渲染层不散落各区间字面量）
    assert "正好读" in ENCOUNTER_JS
    assert "偏简单" in ENCOUNTER_JS
    assert "偏难" in ENCOUNTER_JS
    # 徽章模板行必须经 esc() 转义（去掉 esc( → 本断言必红）
    badge_lines = [ln for ln in ENCOUNTER_JS.splitlines() if "enc-i1-badge" in ln]
    assert badge_lines, "未找到 enc-i1-badge 徽章渲染"
    assert any("esc(" in ln for ln in badge_lines), "徽章展示字段必须经 esc()"
    # pct 取整 + 百分号必须落在 i1BadgeHtml 函数体内（全文 "Math.round(" 是恒真弱断言：
    # renderCoverage 内亦有，无判别力）。去掉 Math.round(Number(...)) 或 % → 本断言必红。
    badge_body = _slice_function(ENCOUNTER_JS, "i1BadgeHtml")
    assert "enc-i1-badge" in badge_body, "i1BadgeHtml 必须渲染 enc-i1-badge 徽章"
    assert "Math.round(Number(" in badge_body, (
        "i1BadgeHtml 的 pct 必须经 Math.round(Number(rate) * 100) 取整为整数百分比"
    )
    assert "%" in badge_body, "i1BadgeHtml 必须输出百分比（含 %）"


def test_encounter_js_degrades_when_index_endpoint_fails():
    """④ 降级路径：Promise.allSettled 并行拉取；索引失败仍按既有顺序渲染列表。"""
    assert "Promise.allSettled" in ENCOUNTER_JS
    assert "fetchIndex" in ENCOUNTER_JS
    # renderTextList 的 ranked 形参必须可为空（带默认值 → 省略即退回既有行为）。
    assert re.search(
        r"function\s+renderTextList\s*\(\s*texts\s*,\s*ranked\s*=", ENCOUNTER_JS
    ), "renderTextList 的 ranked 形参必须可为空（带默认值）"
    # 降级调用点：索引失败时以 renderTextList(texts, null, readState) 调用 —— 第二参
    # ranked 传 null（不排序、无徽章），但已读标记（readState）仍要在降级路径生效。
    assert re.search(
        r"renderTextList\s*\(\s*texts\s*,\s*null\s*,\s*readState\s*\)", ENCOUNTER_JS
    ), "索引失败降级路径必须以 renderTextList(texts, null, readState) 调用（不传 ranked）"


# ── Task 2（打开短篇即记已读 + 推荐条跳过已读顺延）：字符串探针 ──────────────
# 契约：复用 Task 1 的纯函数 ./enc-read.js（loadRead/markRead/isRead/pickUnread）；
#   翻开即记已读；列表逐卡标「✓ 已读」；推荐条跳过已读顺延（i+1 读完 → 降级文案；
#   全读完 → 完成态）。索引失败时行为与 v5.11.0 一致，但已读标记仍在。探针风格沿用
#   本文件：切函数体 + 结构/子串断言，避免「全文子串 in」这类无判别力弱断言。


def _enc_read_import_names():
    """抽 encounter.js 内 `import {…} from "./enc-read.js"` 的具名导入集合。"""
    m = re.search(
        r"""import\s*\{([^}]*)\}\s*from\s*["']\./enc-read\.js["']""",
        ENCOUNTER_JS,
        re.S,
    )
    assert m, "encounter.js 必须 import ./enc-read.js（复用纯函数，不重复实现）"
    return {n.strip() for n in m.group(1).split(",") if n.strip()}


def test_encounter_imports_enc_read_module():
    """① encounter.js 复用 ./enc-read.js 的四个纯函数（模块可达 + 无重复实现）。"""
    assert "./enc-read.js" in ENCOUNTER_JS
    names = _enc_read_import_names()
    for name in ("loadRead", "markRead", "isRead", "pickUnread"):
        assert name in names, f"enc-read 具名导入缺少 {name}"


def test_i1_card_html_renders_read_mark_escaped():
    """② 卡片渲染体含 .enc-read-mark 标记与 is-read 根类，且标记文案经 esc(READ_MARK_TEXT)。"""
    body = _slice_function(ENCOUNTER_JS, "i1CardHtml")
    assert "enc-read-mark" in body, "卡片内必须有 .enc-read-mark 已读标记"
    assert "is-read" in body, "已读卡片根 div 必须追加 is-read 类"
    # 去掉 esc( 或改回字面量 → 本断言必红（XSS 安全 + 文案单点定义）。
    assert re.search(r"esc\(\s*READ_MARK_TEXT\s*\)", body), (
        "已读标记必须以 esc(READ_MARK_TEXT) 输出"
    )
    assert "const READ_MARK_TEXT" in ENCOUNTER_JS, "READ_MARK_TEXT 必须在模块级单点定义"


def test_render_text_list_read_state_param_backward_compatible():
    """③ renderTextList 形参含 readState = null（省略即逐字保持 v5.11.0 行为）。"""
    assert re.search(
        r"function\s+renderTextList\s*\(\s*texts\s*,\s*ranked\s*=\s*null\s*,\s*readState\s*=\s*null\s*\)",
        ENCOUNTER_JS,
    ), "renderTextList 签名必须为 (texts, ranked = null, readState = null)"


def test_render_i1_hint_skips_read_and_escapes_copies():
    """④ renderI1Hint 用 pickUnread 顺延；完成态/降级两条文案常量各自经 esc()。"""
    body = _slice_function(ENCOUNTER_JS, "renderI1Hint")
    assert "pickUnread(" in body, "renderI1Hint 必须用 pickUnread(ranked, readState) 跳过已读顺延"
    assert "readState" in body, "renderI1Hint 必须消费 readState 形参"
    for const in ("I1_HINT_ALL_READ", "I1_HINT_FALLBACK"):
        assert f"const {const}" in ENCOUNTER_JS, f"{const} 文案常量必须在模块级单点定义"
        assert re.search(rf"esc\(\s*{const}\b", body), f"{const} 必须经 esc() 输出"


def test_open_text_marks_read_after_render():
    """⑤ openText 渲染成功后调用 markRead(encStorage(), id, …) 记录已读。"""
    body = _slice_function(ENCOUNTER_JS, "openText")
    assert "markRead(" in body, "openText 必须调用 markRead 记录已读"
    assert "encStorage(" in body, "openText 必须用既有 encStorage() 取 localStorage"


# ── 修订轮（CRV 黄牌 Y2/Y3/Y4）───────────────────────────────────────────────
# Y2：backToList / refreshList 复用列表渲染时漏传 readState（刚读完的那篇当场不显示 ✓ 已读）。
# Y3：renderI1Hint 两处分支比设计边界表更宽（ranked===[] 谎报完成态；无 i1 时谎报「i+1 都读完了」）。
# Y4：全局硬约束「MUST NOT 新增 .encounter-card 的 grid 子项」缺探针（已读标记须留在 meta 段内）。
#
# 工具函数用**源码扫描器**（配平括号 + 跳过字符串/注释）而非「全文子串 in」，
# 保证断言钉到具体调用点 / 具体切片，具备判别力（编辑器打回 Y2/Y3/Y4 时必红）。


def _strip_js_comments(src):
    """去掉 JS 源码里的 `//` 行注释与 `/* */` 块注释（保留字符串/模板串/正则字面量内容）。

    目的：doc comment 里常出现示例调用（如「renderTextList(texts, ranked)」），
    若不清除会被误判为真实调用点。字符串/模板串/正则字面量内的 `//` 不当作注释。
    正则字面量用「上一个有效字符」启发式识别（`= ( , : [ ! & | ? { } ;` 后跟 `/`）。
    """
    out = []
    i = 0
    n = len(src)
    quote = None
    prev_sig = ""  # 上一个非空白有效字符（用于识别正则字面量起始）
    regex_start_after = "=(,:[!&|?{};+*%^~"
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
                prev_sig = ch
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == "/" and prev_sig and prev_sig in regex_start_after:
            # 正则字面量：跳到闭合的未转义 '/'（字符类 [...] 内的 '/' 不算）
            out.append(ch)
            i += 1
            in_class = False
            while i < n:
                c = src[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    i += 1
                    break
                i += 1
            prev_sig = "/"
            continue
        out.append(ch)
        if not ch.isspace():
            prev_sig = ch
        i += 1
    return "".join(out)


def _iter_js_calls(src, name):
    """返回 src 内每个 `name(...)` 调用的**顶层参数列表文本**（排除 `function name(` 定义）。

    手写扫描器配平括号并跳过字符串/模板串 → 正确处理嵌套调用（如 loadRead(encStorage())）。
    """
    calls = []
    for m in re.finditer(r"(?<![\w$])" + re.escape(name) + r"\s*\(", src):
        if re.search(r"function\s+$", src[max(0, m.start() - 20) : m.start()]):
            continue  # 函数定义，非调用点
        i = m.end()  # '(' 之后
        depth = 1
        start = i
        while i < len(src):
            ch = src[i]
            if ch in "\"'`":
                q = ch
                i += 1
                while i < len(src) and src[i] != q:
                    if src[i] == "\\":
                        i += 1
                    i += 1
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        calls.append(src[start:i])
    return calls


def _split_top_level_args(argtext):
    """按**顶层**逗号切分参数列表（忽略嵌套括号 / 字符串内的逗号）。"""
    args = []
    cur = []
    depth = 0
    i = 0
    n = len(argtext)
    while i < n:
        ch = argtext[i]
        if ch in "\"'`":
            q = ch
            cur.append(ch)
            i += 1
            while i < n and argtext[i] != q:
                if argtext[i] == "\\" and i + 1 < n:
                    cur.append(argtext[i])
                    cur.append(argtext[i + 1])
                    i += 2
                    continue
                cur.append(argtext[i])
                i += 1
            if i < n:
                cur.append(argtext[i])
                i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if "".join(cur).strip():
        args.append("".join(cur))
    return args


def test_all_render_text_list_calls_pass_read_state():
    """Y2：encounter.js 内**所有** renderTextList(...) 调用点都传 readState（第三参非空）。

    backToList（← 返回列表）与 refreshList（导入后刷新）曾以 `then(renderTextList)` /
    `renderTextList(await fetchTexts())` 复用列表渲染而漏传 readState → 用户读完一篇点返回后
    那篇当场**不显示 ✓ 已读**（须重进视图才更新）。本断言用调用点**计数 + 每点 3 参形态**钉住：
    去掉任一处 readState（或退回裸回调 then(renderTextList)）→ 必红。
    """
    src = _strip_js_comments(ENCOUNTER_JS)
    calls = _iter_js_calls(src, "renderTextList")
    assert len(calls) >= 4, (
        f"renderTextList 调用点应 >= 4（showView 两条 + backToList + refreshList），实际 {len(calls)}"
    )
    for argtext in calls:
        args = _split_top_level_args(argtext)
        assert len(args) == 3, (
            f"每个 renderTextList 调用点必须传 3 参 (texts, ranked, readState)，"
            f"实际 {len(args)} => renderTextList({argtext.strip()})"
        )
        assert args[2].strip(), f"renderTextList 第三参 readState 不得为空 => renderTextList({argtext.strip()})"
    # 不得把 renderTextList 作为裸回调透传（then(renderTextList)）——那会丢掉 readState。
    assert not re.search(r"[(,]\s*renderTextList\s*[),]", src), (
        "renderTextList 不得作为裸回调透传（如 then(renderTextList)）—— 会丢 readState"
    )


def test_render_i1_hint_hides_on_empty_or_nonarray_ranked():
    """Y3②：ranked 为空数组/非数组 → hideI1Hint()（与 v5.11.0 一致）。

    设计边界表：`ranked` 为空数组 / 非数组 → `pickUnread` → `null` → **hideI1Hint()**。
    改回「显示完成态」会让 empty ranked 谎报「🎉 0 篇都读过了」→ 本断言必红。
    """
    body = _slice_function(ENCOUNTER_JS, "renderI1Hint")
    assert "hideI1Hint(" in body, "renderI1Hint 必须对空/非数组 ranked 调 hideI1Hint()"
    guard = re.search(
        r"if\s*\(\s*!Array\.isArray\(\s*ranked\s*\)\s*\|\|\s*ranked\.length\s*===?\s*0\s*\)", body
    )
    assert guard, "renderI1Hint 必须先守卫「ranked 为非空数组」（空/非数组 → hideI1Hint 早退）"
    hide_at = body.index("hideI1Hint(")
    allread_at = body.index("I1_HINT_ALL_READ")
    assert hide_at < allread_at, (
        "空 ranked 守卫必须出现在完成态之前（否则 ranked === [] 会显示「🎉 0 篇都读过了」）"
    )
    # 完成态篇数取 ranked.length（此处 ranked 已保证是非空数组）
    assert re.search(r"I1_HINT_ALL_READ\(\s*ranked\.length\s*\)", body), (
        "完成态篇数必须用 ranked.length（非空数组），不得再回退到 count=0 兜底"
    )


def test_render_i1_hint_neutral_copy_when_no_real_i1_read():
    """Y3③：未读池首条非 i+1 且**本就不存在 i+1**（全偏简单/偏难）→ 中性文案。

    原先只要首个未读 `band !== "i1"` 就打「i+1 都读完了」，但「本来就一篇 i+1 都没有」
    也会这么说 → 语义不精确。修法：用 isRead 判定 ranked 中**是否真的存在已读的 i+1**，
    有 → 降级文案（I1_HINT_FALLBACK）；无 → 中性文案（I1_HINT_NEUTRAL_PICK）。两条均经 esc()。
    """
    body = _slice_function(ENCOUNTER_JS, "renderI1Hint")
    assert re.search(r"ranked\.some\(", body), "renderI1Hint 必须用 ranked.some(...) 判定是否存在已读的 i+1"
    assert re.search(r"band\s*===\s*[\"']i1[\"']", body), "判定须锁定 band === \"i1\""
    assert re.search(r"isRead\(\s*readState", body), "判定须用 isRead(readState, r.id)"
    assert "const I1_HINT_FALLBACK" in ENCOUNTER_JS, "降级文案常量必须在模块级单点定义"
    assert "const I1_HINT_NEUTRAL_PICK" in ENCOUNTER_JS, "中性文案常量必须在模块级单点定义"
    assert re.search(r"esc\(\s*I1_HINT_FALLBACK\b", body), "降级文案必须经 esc() 输出"
    assert re.search(r"esc\(\s*I1_HINT_NEUTRAL_PICK\b", body), "中性文案必须经 esc() 输出"


def test_i1_card_read_mark_stays_inside_last_meta_child():
    """Y4：钉住硬约束「MUST NOT 新增 .encounter-card 的 grid 子项」。

    ✓ 已读标记（由 `readMark` 变量渲染）必须落在 `.encounter-card-meta` 段**内部**，且
    `.encounter-card-meta` 是卡片内的**最后**一个子项（该卡是 4 列 grid + `meta:last-child`
    补位规则；把标记挪到卡片根会错位）。

    用**切片内相对位置比较**（body.index 大小关系），避免「全文 in」弱断言：
      - `.encounter-card-meta` 开标签 < `${readMark}` 插值 < meta 的 `</span>`；
      - meta 的 `</span>` 之后到卡片 `</div>` 之间不得再出现新的 `<span` / `<div` 子项。
    注：`.enc-read-mark` 字面量在 `readMark` 变量定义处，真实 DOM 位置由 `${readMark}` 插值决定，
    故位置比较锚定 `${readMark}`。把 readMark 从 meta 段内移到卡片根（meta 之前或之后）→ 必红。
    """
    body = _slice_function(ENCOUNTER_JS, "i1CardHtml")
    # readMark 渲染体确实产出 .enc-read-mark span（把变量与标记绑定，位置比较才有意义）
    assert re.search(r"<span class=\"enc-read-mark\">", body), "readMark 必须渲染 .enc-read-mark span"
    # 切出 return 的卡片模板字面量：readMark 的 `${readMark}` 插值决定真实 DOM 位置
    ret_at = body.index("return")
    tmpl = body[body.index("`", ret_at) + 1 : body.rindex("`")]
    meta_open = tmpl.index('<span class="encounter-card-meta">')
    meta_close = tmpl.index("</span>", meta_open)
    readmark_use = tmpl.index("${readMark}")
    assert meta_open < readmark_use, (
        "✓ 已读标记（${readMark} 渲染的 .enc-read-mark）必须出现在 .encounter-card-meta 开标签**之后**"
    )
    assert readmark_use < meta_close, (
        "✓ 已读标记必须落在 .encounter-card-meta 段**内部**（meta 闭合 </span> 之前）"
    )
    # meta 必须是卡片最后一个子项：其 </span> 之后到卡片 </div> 之间不得有新子项
    tail = tmpl[meta_close + len("</span>") :]
    card_close = tail.index("</div>")
    rest = tail[:card_close]
    assert "<span" not in rest and "<div" not in rest, (
        f".encounter-card-meta 必须是卡片最后一个子项（其后不得再有子项），实际残留：{rest!r}"
    )
