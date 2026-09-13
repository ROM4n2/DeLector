# -*- coding: utf-8 -*-
"""PWA 更新提示的可用性契约（2026-09-13 用户报障固化）。

报障原文：「新版本已就绪点击重新加载的这个弹窗没有用，而且一直站在那里影响使用」

根因（双缺陷，见 git 历史修复 commit）：
1. **点不动**：更新提示复用了 `#wb-notify`，而 `.wb-notify` 在 `static/style.css`
   带 `pointer-events: none`（toast 的正确设计——不拦截下层点击），可刷新动作却被绑在
   **该元素自身**（`#wb-notify` 的 onclick）→ 点击物理上不可达，onclick 是死绑定。
2. **不消失**：提示用 `sticky: true`（`core.js` 的 notify 在 sticky 时不设 timeout）
   且没有任何关闭入口 → 常驻遮挡界面。

既有 `test_audit_hardening.py::test_sw_pwa_update_is_gentle_not_force_reload` 只断言
「`main.js` 里出现 `location.reload()`」这类**字符串存在**——只能证明"绑了"，
证明不了"点得到/关得掉"（Vault 红线 11：字符串存在断言是死测）。

本文件把这两条可用性契约变成可执行断言：
- 更新提示必须是**可点**的（其承载元素不得落在 pointer-events:none 的规则下）；
- 更新提示必须有**关闭/移除**路径（不能既 sticky 又无退路）。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _css_rule_block(css: str, selector: str) -> str:
    """取出 selector 的首个规则块（选择器须精确匹配，避免 .wb-notify 命中 .wb-notify.show）。"""
    pattern = re.compile(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.MULTILINE)
    m = pattern.search(css)
    return m.group(1) if m else ""


def _update_notice_element_id() -> str:
    """从 main.js 里找出更新提示的承载元素 id（当前实现用 getElementById('...')）。"""
    # 更新提示监听块：定位 delector-update 之后的 getElementById 调用
    idx = MAIN_JS.find("delector-update")
    assert idx != -1, "main.js 缺少 delector-update 监听（PWA 更新提示被删？）"
    tail = MAIN_JS[idx:]
    m = re.search(r"getElementById\(\s*[\"']([^\"']+)[\"']\s*\)", tail)
    assert m, (
        "更新提示没有定位到任何承载元素——若改为自建元素，请同步更新本测试的探测点；"
        "但无论如何，提示必须有一个可被点击/可被关闭的承载元素"
    )
    return m.group(1)


def test_update_notice_is_pointer_reachable():
    """更新提示承载元素必须可点：不得只落在 pointer-events:none 的规则下。

    2026-09-13 报障的直接原因：刷新动作绑在 `.wb-notify`（基础规则带
    pointer-events:none）上，点击永远到不了。

    判据（关键：解除必须是**针对该元素**的，不能用"全局某处出现过 auto"糊过去）：
      - 若该元素实际生效的规则块里没有 pointer-events:none → 直接可点，通过；
      - 若有 none → 必须存在针对该元素的 pointer-events:auto 规则（id 块或
        已启用的交互变体类），否则即为死绑定。
    """
    el_id = _update_notice_element_id()

    id_block = _css_rule_block(STYLE_CSS, f"#{el_id}")

    # 该元素的基础类：优先 HTML 静态 class，其次 JS className 赋值
    base_class = None
    idx_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html_m = re.search(r"id=[\"']" + re.escape(el_id) + r"[\"'][^>]*class=[\"']([^\"']+)[\"']", idx_html)
    if html_m:
        base_class = html_m.group(1).split()[0]

    cls_block = _css_rule_block(STYLE_CSS, f".{base_class}") if base_class else ""
    effective = id_block + cls_block
    if "pointer-events: none" not in effective:
        return  # 不受 pointer-events 限制 → 可点，契约满足

    # 受限：必须有一条**指向该元素**的解除规则（id 选择器内 pointer-events:auto），
    # 且 JS 侧确实在绑定点击时启用它（交互态）。
    assert "pointer-events: auto" in id_block.replace(" ", " "), (
        f"#{el_id} 落在 .{base_class} 的 pointer-events:none 之下，"
        "而刷新动作绑在该元素自身 → 点击物理不可达（2026-09-13 报障）。"
        f"修复须给该元素一条 pointer-events:auto 的规则，例如 "
        f"`#{el_id}.interactive {{ pointer-events: auto; }}`"
    )
    assert ("interactive" in MAIN_JS) or ("pointerEvents" in MAIN_JS), (
        "CSS 提供了可交互变体，但 main.js 绑定点击时没有启用它——提示仍不可点"
    )


def test_update_notice_has_dismiss_path():
    """更新提示必须可关闭：不能既 sticky 又没有任何隐藏/移除路径。

    2026-09-13 报障的第二个原因：提示 sticky 常驻且无关闭入口，遮挡界面。
    要求：更新提示路径上存在显式的关闭/移除动作（remove / display:none / hidden）。
    """
    idx = MAIN_JS.find("delector-update")
    assert idx != -1, "main.js 缺少 delector-update 监听"
    # 取监听块之后的一段代码（到下一个顶层事件注册或文件末），在其内找关闭动作
    tail = MAIN_JS[idx : idx + 3000]
    has_dismiss = any(token in tail for token in (".remove()", 'display = "none"', "display = 'none'", "hidden = true"))
    assert has_dismiss, "更新提示没有关闭/移除路径（既 sticky 又无退路 → 常驻遮挡，2026-09-13 报障症状）"
