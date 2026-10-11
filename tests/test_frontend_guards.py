# -*- coding: utf-8 -*-
r"""P0-3 / P0-4 前端守卫：openReader 失败可见化 + 评分按钮重入闸。

⚠️ **这是结构守卫（文本结构断言），弱于行为测试**
------------------------------------------------
本仓**没有** JS 测试基建（无 jsdom / 无 JS test runner），本文件只能断言
"正确的代码形状存在"（try/catch、notify 调用、disabled、重入闸），
**不能**证明这些代码在真实浏览器里的运行时行为。真实验收靠 HITL
（人在环手动验收：真实点击 / 真实超时场景）。若未来引入 JS 测试基建，
本文件应升级为行为级测试后退役。

钉住什么
--------
- P0-3：`reader.js:openReader` 全程静默失败（无 try/catch、无加载态，
  首次打开恰逢 spaCy 惰性迁移 25s 超时 ⇒ 页面停在列表零提示）
  ⇒ openReader 体内必须含 try / catch / notify / "载入中"占位 / finally；
  `static/js/core.js` 必须有浏览器侧全局兜底
  （unhandledrejection + window.onerror → notify，带节流）。
- P0-4：`cards.js:submitCardReview` 无重入闸 + 评分按钮无 disabled
  ⇒ 连点会 FSRS 双推进 + 跳两张卡（学习数据写脏且不可回滚）
  ⇒ 函数体内必须含 `_reviewInFlight` 重入闸、按钮 disabled、finally 恢复。
- P2 首屏惰性：`index.html` 的 workbench iframe 曾带静态 `src`（383KB 的
  workbench.html 首屏即加载并启动内部轮询，即使从不进背词工作台）
  ⇒ iframe 必须只带 `data-src`、**不含**静态 `src=`；`main.js` 在 `show('german')`
  时按视图幂等赋值。

**变异自证**：把 openReader 的 try/catch 删掉 / 把 submitCardReview 的
disabled 与重入闸删掉 / 把 workbench iframe 的静态 `src=` 加回去 ⇒ 对应用例立即转红。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
READER = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

# 与 index.html / main.js 同源的惰性工作台路由（漂移即两侧一起改）。
_WORKBENCH_ROUTE = "/german/workbench.html"


def _extract_function(source: str, signature: str) -> str:
    """按函数签名截取函数体（从签名行到下一个顶层 `export` 或文件尾）。

    够用的文本级近似：JS 函数体行首缩进恒为 0（本仓格式化纪律），
    顶层 export 声明即可作为边界。
    """
    start = source.find(signature)
    assert start != -1, f"找不到函数签名 {signature!r}（前提变了，需重写守卫）"
    next_export = source.find("\nexport ", start + len(signature))
    end = next_export if next_export != -1 else len(source)
    return source[start:end]


# ── P0-3：openReader 失败可见化 ───────────────────────────────────────────────
def test_open_reader_body_has_try_catch_and_notify():
    body = _extract_function(READER, "export async function openReader(")

    assert "try {" in body, "openReader 必须包 try（曾全程静默失败，页面停在列表零提示）"
    assert "catch (" in body, "openReader 必须捕获失败"
    assert "notify(" in body, "失败必须走既有 notify 通知（不许只 console.error）"
    assert "finally" in body, "加载态必须在 finally 里恢复（不许卡死在占位文案）"


def test_open_reader_shows_loading_placeholder_in_title():
    body = _extract_function(READER, "export async function openReader(")

    assert "载入中" in body, "进入时必须在 reader-title 置加载占位（25s 超时也要有反馈）"


# ── P0-3：浏览器侧全局兜底（去重/节流，别弹成一串） ────────────────────────────
def test_core_has_global_error_fallback_with_throttle():
    assert 'unhandledrejection' in CORE and 'addEventListener' in CORE, (
        "core.js 必须挂 unhandledrejection 全局兜底（static/ 内此前为零）"
    )
    assert "window.onerror" in CORE, "core.js 必须挂 window.onerror 全局兜底"
    assert "notify(" in CORE, "全局兜底必须统一走 notify"
    assert "Date.now()" in CORE, "全局兜底必须节流（同错连发不得弹成一串）"


# ── P0-4：评分请求防重入（FSRS 双推进 + 跳两张卡） ────────────────────────────
def test_submit_card_review_has_reentry_gate_and_disabled_buttons():
    body = _extract_function(CARDS, "export async function submitCardReview(")

    assert "if (_reviewInFlight) return" in body, (
        "函数入口必须有重入闸：连点期间的新请求直接丢弃"
    )
    assert "_reviewInFlight = true" in body and "_reviewInFlight = false" in body, (
        "飞行标志必须成对置位/复位"
    )
    assert "disabled = true" in body, "请求飞行期间评分按钮必须 disabled（照 writer.js 既有模式）"
    assert "finally" in body, "按钮恢复必须放 finally（失败路径也不许把按钮锁死）"


# ── 评分按钮的 onclick 与重入闸共存（按钮本体仍可点，由函数内部挡） ────────────
def test_rating_bar_buttons_still_rendered_with_submit_handler():
    assert "submitCardReview(" in CARDS, "评分按钮必须仍接线 submitCardReview（守卫不得误删接线）"


# ── P2 首屏惰性：workbench iframe 不得静态挂载（data-src + 按视图赋值）────────────
def _german_view_block() -> str:
    """截取 index.html 里 `#view-german` 的 `<main>` 块（与 test_german_workbench 同切法）。"""
    return INDEX.split('id="view-german"')[1].split("</main>")[0]


def test_workbench_iframe_is_lazy_no_static_src():
    """首屏不得静态挂载 workbench iframe：必须用 `data-src`，且**没有**裸 `src=` 属性。

    ⚠️ **结构守卫（文本结构断言），弱于行为测试**：本仓无 JS 测试基建，它只能证明
    "正确的代码形状存在"，**不能**证明真实浏览器里首屏真的不再加载该 iframe。真实验收
    靠 HITL（真实启动一次、看 network 面板 / `launch.log` 首屏口径）。
    """
    block = _german_view_block()
    assert f'data-src="{_WORKBENCH_ROUTE}"' in block, "workbench iframe 必须用 data-src 惰性路由"
    # data-src= 里含子串 `src=`，故用负向后顾 `(?<![-\w])` 排除 `-src=` / 标识符前缀，
    # 只匹配真正的 `src=` 属性；否则守卫会被 data-src 形态骗过。
    assert re.search(r"(?<![-\w])src\s*=", block) is None, (
        "workbench iframe 不得带静态 src=（会让 383KB 的 workbench.html 首屏即加载、并启动其内部轮询）"
    )


def test_main_js_wires_lazy_workbench_on_german_view():
    """main.js 必须在进入 german 视图时按视图幂等赋 src（结构守卫，弱于行为测试）。"""
    helper = _extract_function(MAIN, "function ensureGermanWorkbench(")
    assert 'getElementById("german-workbench-frame")' in helper, "未按 id 取到 workbench iframe"
    assert 'getAttribute("data-src")' in helper, "未从 data-src 读取惰性路由"
    assert 'setAttribute("src"' in helper, "未把惰性路由赋给 src"
    assert 'getAttribute("src")' in helper, "缺少幂等守卫（重设 src 会整页重载、丢工作台状态）"

    show_body = _extract_function(MAIN, "export function show(")
    assert "ensureGermanWorkbench()" in show_body, "show('german') 未接线 ensureGermanWorkbench()"
