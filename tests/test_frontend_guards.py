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

**变异自证**：把 openReader 的 try/catch 删掉 / 把 submitCardReview 的
disabled 与重入闸删掉 ⇒ 对应用例立即转红。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
READER = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")


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
