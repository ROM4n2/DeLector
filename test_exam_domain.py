"""备考域 (Prüfungsbereich) 骨架的静态契约 —— ADR-0005 Task 1。

本 Task 只加「骨架」：桌面 nav + 移动 dock 各一个静态备考按钮、
index.html 一个 <main id="view-exam" class="view"> 壳（等级页签条 +
模块卡片区占位）。零 JS 改动 —— main.js 的 show(view) 是 view-id
惯例（querySelectorAll(".view") + nav-btn-/mob-btn- 点亮），
show('exam') 天然工作。

与 test_german_workbench.py / test_prep_matrix.py 前端段同款模式：
源码字符串匹配，不渲染 DOM。断言切到各自按钮/容器的**自身标签**
内，不做整文件级别的模糊匹配（本仓库 static-string-assertion-dead-test
教训）。
"""
import re
from pathlib import Path

_ROOT = Path(__file__).parent
_INDEX = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
_CSS = (_ROOT / "static" / "style.css").read_text(encoding="utf-8")

EXAM_VIEW_IDS = (
    "exam-card-writing",
    "exam-card-hoeren",
    "exam-card-lesen",
    "exam-card-sprechen",
    "exam-card-vocab",
)


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
    """五张模块卡片 id 齐全（写作/听力/阅读/口语/词表，本 Task 占位）。"""
    for attr in EXAM_VIEW_IDS:
        assert 'id="%s"' % attr in _INDEX, "view-exam 缺少模块卡片 id=%r" % attr


def test_exam_module_cards_inside_module_grid():
    """五张卡片必须写在 exam-module-grid 容器**内部** —— 挂到容器外的占位
    不属于骨架本 Task 的产出（grid 选择器也管不到）。"""
    grid_at = _INDEX.index('id="exam-module-grid"')
    # 容器内 = 自 grid 开标签起、到 grid 的闭合 </div> 止（骨架无嵌套 div，取第一个闭合即容器自身）
    blk = _INDEX[grid_at:_INDEX.index("</div>", grid_at)]
    for attr in EXAM_VIEW_IDS:
        assert 'id="%s"' % attr in blk, "模块卡片 %s 必须写在 exam-module-grid 内" % attr


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
