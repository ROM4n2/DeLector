"""备考域 (Prüfungsbereich) 的静态与动态契约 —— ADR-0005 Task 1/2。

Task 1 只加「骨架」：桌面 nav + 移动 dock 各一个静态备考按钮、
index.html 一个 <main id="view-exam" class="view"> 壳（等级页签条 +
模块卡片区占位）。零 JS 改动 —— main.js 的 show(view) 是 view-id
惯例（querySelectorAll(".view") + nav-btn-/mob-btn- 点亮），
show('exam') 天然工作。

Task 2 起备考域接管 A1 五模块：写作(formular/email)/听力/阅读/口语/词表
面板从 view-writer / view-cards 迁入，view-exam 内换成模块页签 + 面板
容器结构（exam-card-* 保留为模块选中页签）。

与 test_german_workbench.py / test_prep_matrix.py 前端段同款模式：
源码字符串匹配 + node:vm 动态探针（tools/ia_dom_mount_probe.mjs），
断言切到各自按钮/容器的**自身标签**内，不做整文件级别的模糊匹配
（本仓库 static-string-assertion-dead-test 教训）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parent
_INDEX = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
_CSS = (_ROOT / "static" / "style.css").read_text(encoding="utf-8")
_MAIN_JS = (_ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

EXAM_MODULE_IDS = (
    "exam-card-writing",
    "exam-card-hoeren",
    "exam-card-lesen",
    "exam-card-sprechen",
    "exam-card-vocab",
)

# Task 2：五个模块面板容器（exam-card-* 页签点击点亮的目标）
EXAM_PANEL_IDS = (
    "exam-writing",
    "exam-cards-family",
)
# 备考域接管后，工具视图不得再出现 A1 id（切片级断言见 test_*_slice_forbids）
TOOL_VIEW_FORBIDDEN = ("seg-a1", "writer-mode-a1-formular", "writer-mode-a1-email")


def _button_block(id_attr):
    """index.html 里给定 id 的 <button ...> 自身开标签（到第一个 > 为止）。

    钉开标签内的 onclick —— 把按钮挪出 nav/dock、或 onclick 写丢，
    切片里看不到就红；写进别的按钮不算。
    """
    m = re.search(r"<button\b[^>]*\b%s\b[^>]*>" % re.escape(id_attr), _INDEX, re.S)
    assert m, "index.html 里找不到 id=%r 的按钮" % id_attr
    return m.group(0)


# ── 桌面 nav + 移动 dock 的静态备考入口 ─────────────────────────────────────

def test_desktop_nav_has_static_exam_button():
    """桌面 nav 有 nav-btn-exam，且 onclick 指向 show('exam')。"""
    blk = _button_block("nav-btn-exam")
    assert "show('exam')" in blk, "nav-btn-exam 的 onclick 必须含 show('exam')"


def test_desktop_nav_exam_button_ordered():
    """备考按钮必须插在 writer 之后、cards 之前（只插入不改既有按钮）。"""
    assert _INDEX.index('id="nav-btn-writer"') < _INDEX.index('id="nav-btn-exam"') < _INDEX.index('id="nav-btn-cards"')


def test_mobile_dock_has_static_exam_button():
    """移动 dock 有 mob-btn-exam，onclick 同指 show('exam')。"""
    blk = _button_block("mob-btn-exam")
    assert "show('exam')" in blk, "mob-btn-exam 的 onclick 必须含 show('exam')"


def test_mobile_dock_exam_button_ordered():
    """dock 备考按钮在 writer 之后、cards 之前（与既有 dock 顺序同构）。"""
    assert _INDEX.index('id="mob-btn-writer"') < _INDEX.index('id="mob-btn-exam"') < _INDEX.index('id="mob-btn-cards"')


# ── view-exam 容器壳 ────────────────────────────────────────────────────────

def test_view_exam_shell_exists():
    """有 <main id="view-exam" class="view"> 壳（main.js show() 按惯例点亮）。"""
    m = re.search(r'<main\b[^>]*\bid="view-exam"[^>]*>', _INDEX)
    assert m, "index.html 缺少 <main id=\"view-exam\"> 壳"
    blk = m.group(0)
    assert "view" in blk.split("class=")[1], "view-exam 的 class 必须含 view（否则 show() 管不到它）"


def test_view_exam_shell_before_german_view():
    """view-exam 必须在 view-german 之前（不破 test_german_workbench 的 split 切块，
    且置于 progress 之后 —— 插入式改动不挪任何既有视图）。"""
    exam_at = _INDEX.index('id="view-exam"')
    german_at = _INDEX.index('id="view-german"')
    assert exam_at < german_at, "view-exam 必须置于 view-german 之前"
    assert _INDEX.index('id="view-progress"') < exam_at, "view-exam 必须置于 view-progress 之后"


def test_exam_domain_containers_exist():
    """等级页签条 + 模块卡片区容器齐全（Task 2 起面板挂进来的锚点）。"""
    for attr in ("exam-level-tabs", "exam-level-a1", "exam-module-grid"):
        assert 'id="%s"' % attr in _INDEX, "view-exam 缺少 id=%r" % attr


def test_exam_module_cards_all_present():
    """五张模块卡片 id 齐全（写作/听力/阅读/口语/词表，Task 2 起充当模块页签）。"""
    for attr in EXAM_MODULE_IDS:
        assert 'id="%s"' % attr in _INDEX, "view-exam 缺少模块卡片 id=%r" % attr


def test_exam_module_cards_inside_module_grid():
    """五张卡片必须写在 exam-module-grid 容器**内部** —— 挂到容器外的占位
    不属于骨架本 Task 的产出（grid 选择器也管不到）。"""
    grid_at = _INDEX.index('id="exam-module-grid"')
    # 容器内 = 自 grid 开标签起、到 grid 的闭合 </div> 止（骨架无嵌套 div，取第一个闭合即容器自身）
    blk = _INDEX[grid_at:_INDEX.index("</div>", grid_at)]
    for attr in EXAM_MODULE_IDS:
        assert 'id="%s"' % attr in blk, "模块卡片 %s 必须写在 exam-module-grid 内" % attr


def test_exam_module_cards_wired_to_panels():
    """五张模块卡片必须 onclick 调 setExamModule 并指向对应面板/页签。

    Task 2 起它们是「模块选中页签」：点它显示对应面板。只有按钮没有
    接线 = 死按钮（static-string-assertion-dead-test 教训：按钮存在
    不等于可点）。"""
    for attr, target in (
        ("exam-card-writing", "'writing'"),
        ("exam-card-hoeren", "'hoeren'"),
        ("exam-card-lesen", "'lesen'"),
        ("exam-card-sprechen", "'sprechen'"),
        ("exam-card-vocab", "'vocab'"),
    ):
        blk = _button_block(attr)
        assert "setExamModule(%s)" % target in blk, (
            "模块卡片 %s 的 onclick 必须含 setExamModule(%s)" % (attr, target)
        )


# ── style.css 最小样式 ──────────────────────────────────────────────────────

def test_exam_css_rules_exist():
    """style.css 有 .exam-level-tab 与 .exam-module-card 规则（切到规则自己的声明块）。"""
    rules = [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", _CSS)]
    for sel in (".exam-level-tab", ".exam-module-card"):
        hits = [s for s, _ in rules if sel in s]
        assert hits, "style.css 缺少 %s 规则" % sel


def test_exam_css_grid_uses_auto_fill():
    """.exam-module-grid 必须是自适应 grid（桌面 200px 起格，移动窄屏同款规则天然收列）。"""
    rules = [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", _CSS)]
    grids = [d for s, d in rules if ".exam-module-grid" in s and "grid" in d]
    assert grids, "style.css 缺少 .exam-module-grid 的 grid 规则"
    assert any("repeat(auto-fill" in d and "minmax(" in d for d in grids), (
        "模块卡片区必须是 auto-fill + minmax 自适应 grid，实际：%r" % grids
    )


# ── Task 2：A1 五模块迁入备考域（面板容器 + 工具视图删净 + 探针） ────────────

def _view_slice(id_attr):
    """<main> 不嵌套：视图切片 = 自带 id 的 <main 开标签到下一个 </main>。"""
    at = _INDEX.index('id="%s"' % id_attr)
    open_at = _INDEX.rindex("<main", 0, at)
    return _INDEX[open_at:_INDEX.index("</main>", at)]


def _section_slice(id_attr):
    at = _INDEX.index('id="%s"' % id_attr)
    open_at = _INDEX.rindex("<section", 0, at)
    return _INDEX[open_at:_INDEX.index("</section>", at)]


def test_exam_panel_containers_exist():
    """五个模块面板容器齐全（Task 2 挂 A1 面板的锚点）。"""
    for attr in EXAM_PANEL_IDS:
        assert 'id="%s"' % attr in _INDEX, "view-exam 缺少模块面板容器 id=%r" % attr


def test_exam_writing_panel_holds_a1_writing():
    """exam-writing 面板内必须有写作页签 + formular/email 两个子面板。"""
    blk = _section_slice("exam-writing")
    for attr in ("exam-tab-formular", "exam-tab-email", "a1-formular-view", "a1-email-view"):
        assert 'id="%s"' % attr in blk, "exam-writing 缺少 id=%r" % attr
    # 页签接线：onclick 调 setExamWritingTab（存在不等于可点）
    tab_blk = _button_block("exam-tab-formular")
    assert "setExamWritingTab('formular')" in tab_blk, "exam-tab-formular 必须调 setExamWritingTab('formular')"
    tab_blk = _button_block("exam-tab-email")
    assert "setExamWritingTab('email')" in tab_blk, "exam-tab-email 必须调 setExamWritingTab('email')"


def test_exam_cards_family_panel_holds_a1_modules():
    """exam-cards-family 面板内必须有词表工具栏 + 备考域渲染容器 + 听读容器。"""
    blk = _section_slice("exam-cards-family")
    for attr in (
        "a1-toolbar", "a1-topic-pills", "a1-search-row",
        "exam-cards-container", "exam-cards-view-toggle",
        "a1-hoeren-container", "a1-lesen-container",
    ):
        assert 'id="%s"' % attr in blk, "exam-cards-family 缺少 id=%r" % attr


def test_tool_views_no_longer_host_a1():
    """view-writer / view-cards 切片内不得再有任何 A1 id（迁出必须删净）。

    漏删 = 同 id 双现，getElementById 挂载歧义 + 渲染进隐藏旧容器，
    页面照常渲染但交互全死（v4.8.2 同族症状）。"""
    writer_blk = _view_slice("view-writer")
    cards_blk = _view_slice("view-cards")
    for attr in ("a1-formular-view", "a1-email-view", "writer-mode-a1-formular",
                 "writer-mode-a1-email", "a1-formular-select", "a1-email-input"):
        assert attr not in writer_blk, "view-writer 仍残留 A1 写作 id=%r" % attr
    assert 'id="writer-mode-essay"' in writer_blk, "view-writer 保留了纯 essay 单按钮条"
    for attr in ("a1-toolbar", "a1-hoeren-container", "a1-lesen-container",
                 "seg-a1", "a1-tab-vocab", "a1-topic-pills"):
        assert attr not in cards_blk, "view-cards 仍残留 A1 id=%r" % attr


def test_moved_a1_ids_are_unique_in_index_html():
    """id 唯一性铁律：每个被搬移的 id 全文件恰好 1 次。"""
    for attr in (
        "a1-formular-view", "a1-email-view", "a1-toolbar", "a1-topic-pills",
        "a1-search-row", "exam-cards-container", "a1-hoeren-container",
        "a1-lesen-container", "writer-mode-essay",
    ):
        n = _INDEX.count('id="%s"' % attr)
        assert n == 1, 'id="%s" 全文件出现 %d 次（必须恰好 1 次，双现 = 挂载歧义）' % (attr, n)
    assert "setCardSegment('a1')" not in _INDEX, "index.html 仍引用 setCardSegment('a1')（seg-a1 应删除）"
    assert "switchWriterMode('formular')" not in _INDEX, "index.html 仍引用 switchWriterMode('formular')"
    assert "switchWriterMode('email')" not in _INDEX, "index.html 仍引用 switchWriterMode('email')"


def test_main_js_show_routes_exam_domain():
    """show() 的备考域路由：离开 exam 停考计时器、进入 exam 渲染模块。"""
    body = _MAIN_JS.split("export function show(")[1].split("\nexport ")[0]
    assert 'if (view !== "exam")' in body, (
        'show() 缺 if (view !== "exam") 守卫 —— 离开备考域不停听力/阅读考试计时器'
    )
    assert 'if (view !== "cards")' not in body, (
        'show() 仍用 view !== "cards" 守卫停考计时器（备考域宿主已改 view-exam）'
    )
    assert 'if (view === "exam")' in body and "setExamModule" in body, (
        'show() 缺 view === "exam" 分支（进入备考域要点亮模块面板）'
    )


def test_exam_module_mount_probe():
    """动态探针：view-exam 挂载 + 渲染目标回退必红（node:vm 真跑 a1_cards.js）。"""
    if not shutil.which("node"):
        import pytest
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    probe = _ROOT / "tools" / "ia_dom_mount_probe.mjs"
    assert probe.exists(), "缺少 tools/ia_dom_mount_probe.mjs 动态探针"
    res = subprocess.run(
        ["node", str(probe), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT),
    )
    assert res.returncode == 0, "探针执行失败：\n%s\n%s" % (res.stdout, res.stderr)
    out = json.loads(res.stdout)
    assert out["ok"] is True
    assert out["dynamic"]["mainCardsContainerUntouched"], (
        "探针动态场景：renderA1 不得把词卡写进主站 #cards-container"
    )
    assert out["dynamic"]["vocabDeckTarget"] == "exam-cards-container"
    assert out["dynamic"]["vocabGridTarget"] == "exam-cards-container"
