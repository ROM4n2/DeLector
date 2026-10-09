# -*- coding: utf-8 -*-
"""顶栏版本更新 chip（Task 5）静态结构 + 行为级探针守卫。

覆盖：
- ``static/index.html``：顶栏 ``#update-chip`` 容器（初始 ``hidden``）+ 手动检查触发点
  ``#topbar-system``；且**不得**破坏 ``System · vX.Y.Z</span>`` 那句自证串；
- ``static/js/update.js``：``initUpdateCheck`` 驱动 ``/api/update/check``，**禁 setInterval**；
- ``static/js/main.js``：import + ``DOMContentLoaded`` 内接线；
- ``static/style.css``：``.update-chip`` 样式（含 ``[hidden]`` 覆盖）；
- 行为级真相在 ``tools/wb_update_chip_probe.mjs``：把 core.js 的 ``esc`` 与 update.js 的
  ``initUpdateCheck`` 按括号配对**真实切片**丢进 node:vm 真跑（探针里没有一份重抄的实现），
  钉死「无新版 / 拿不准 / 请求失败 ⇒ 零可见变化」这条红线 + XSS + 手动检查入口。

风格照 ``tests/test_search_ui.py``：读文件做静态切片/结构断言，不起服务。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

UPDATE_JS = ROOT / "static" / "js" / "update.js"
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

# 关键场景名清单：防「场景被删仍全绿」。必须与探针里 check() 的 name 逐字一致。
_PROBE_SCENARIOS = (
    "fixture_shape_matches_contract",
    "chip_shown_when_newer",
    "silent_when_up_to_date",
    "silent_when_check_failed",
    "silent_when_fetch_throws",
    "silent_when_non_2xx",
    "xss_latest_escaped",
    "xss_page_url_escaped",
    "manual_click_shows_latest",
    "manual_click_humanizes_error",
    "manual_entry_is_discoverable",
    "no_unhandled_rejection",
)


def _run_update_chip_probe() -> dict:
    """跑 ``tools/wb_update_chip_probe.mjs --json``，返回解析后的 dict（含 failures/total/cases）。"""
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    probe = ROOT / "tools" / "wb_update_chip_probe.mjs"
    assert probe.exists(), "缺少 tools/wb_update_chip_probe.mjs 动态探针"
    res = subprocess.run(
        ["node", str(probe), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, "探针执行失败：\n%s\n%s" % (res.stdout, res.stderr)
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(
            "探针 --json 输出不是合法 JSON：%s\nstdout 片段：%r\nstderr 片段：%r"
            % (e, res.stdout[:400], res.stderr[:400])
        )


# ── 行为级探针（Task 5 核心） ──────────────────────────────────────────────────


def test_update_chip_behaves_under_node():
    """真实 esc/initUpdateCheck 在 node:vm 里跑 4 种响应路径 + 零变化红线 + XSS + 手动检查。"""
    out = _run_update_chip_probe()
    assert set(out) == {"failures", "total", "cases"}, (
        "探针 --json 必须输出精确三键 {failures,total,cases}，实际 %s" % sorted(out)
    )
    assert out["failures"] == 0, "探针有失败场景：%s" % [c for c in out["cases"] if not c["ok"]]
    names = {c["name"] for c in out["cases"]}
    assert out["total"] == len(_PROBE_SCENARIOS), (
        "探针场景数必须精确为 %s，实际 %s" % (len(_PROBE_SCENARIOS), out["total"])
    )
    assert names == set(_PROBE_SCENARIOS), (
        "探针场景集合失配；实际场景：%s" % sorted(names)
    )


# ── update.js 静态契约 ────────────────────────────────────────────────────────


def test_update_module_exists_and_exports_init():
    assert UPDATE_JS.exists(), "static/js/update.js 必须存在"
    src = UPDATE_JS.read_text(encoding="utf-8")
    assert "export function initUpdateCheck" in src, "update.js 必须导出 initUpdateCheck"
    assert "/api/update/check" in src, "update.js 必须请求 /api/update/check"
    assert "esc(" in src, "所有动态值写入 DOM 前必须经 core.js 的 esc()"


def test_update_module_has_no_setinterval():
    """禁 setInterval：轮询会持续打后端且无意义，一次性 setTimeout 足够。"""
    src = UPDATE_JS.read_text(encoding="utf-8")
    assert "setInterval" not in src, "update.js 禁止 setInterval（只允许一次性 setTimeout）"
    assert "setTimeout" in src, "update.js 必须用一次性 setTimeout 做延迟检查"


def test_update_module_supports_dependency_injection():
    """依赖注入（探针同步驱动用）：fetchImpl / setTimeoutFn / delayMs 三个可选参数。"""
    src = UPDATE_JS.read_text(encoding="utf-8")
    for key in ("fetchImpl", "setTimeoutFn", "delayMs"):
        assert key in src, "initUpdateCheck 必须支持 options.%s（探针注入用）" % key


# ── index.html：chip 锚点 + 手动入口 + 自证串守卫 ─────────────────────────────


def test_index_has_update_chip_hidden_by_default():
    m = re.search(r"<span\b[^>]*id=\"update-chip\"[^>]*>", INDEX)
    assert m, "index.html 顶栏必须有 <span id=\"update-chip\"> 锚点"
    assert "hidden" in m.group(0), "update-chip 初始必须 hidden（无新版时零可见变化）"
    assert "update-chip" in m.group(0), "update-chip 必须带 class（供 style.css 命中）"


def test_index_has_discoverable_manual_check_trigger():
    m = re.search(r"<span\b[^>]*id=\"topbar-system\"[^>]*>", INDEX)
    assert m, "顶栏 System 版本号 span 必须有 id=\"topbar-system\"（手动检查触发点）"
    tag = m.group(0)
    assert re.search(r'title="[^"]*检查更新[^"]*"', tag), "手动检查入口必须用 title 说明用途"
    assert 'role="button"' in tag, "手动检查入口必须声明按钮语义"
    assert 'tabindex="0"' in tag, "手动检查入口必须可通过 Tab 聚焦"


def test_topbar_version_self_attest_string_intact():
    """chip 是兄弟元素，不得插进版本号与其紧邻 </span> 之间。

    ``test_writer_mobile.py`` 的正则锚定 ``</span``；一旦把 chip 塞进去，那条守卫立刻
    变红。这里做一次本地双保险（权威仍在 test_writer_mobile.py）。
    """
    assert re.search(r"System · v\d+\.\d+\.\d+</span", INDEX), (
        "顶栏 'System · vX.Y.Z</span>' 被改动：chip 必须是兄弟元素，"
        "不能插进版本号与其 </span> 之间（否则 test_writer_mobile 的顶栏守卫失配）"
    )


# ── main.js 接线 ─────────────────────────────────────────────────────────────


def test_main_imports_update_module():
    assert "./update.js" in MAIN_JS, "main.js 必须 import ./update.js"
    assert "initUpdateCheck" in MAIN_JS, "main.js 必须引用 initUpdateCheck"


def test_main_wires_update_check_in_domcontentloaded():
    block = MAIN_JS.split('document.addEventListener("DOMContentLoaded"', 1)[1]
    assert "initUpdateCheck()" in block, "initUpdateCheck() 必须在 DOMContentLoaded 回调内接线"


# ── style.css ────────────────────────────────────────────────────────────────


def test_style_defines_update_chip_rules():
    assert ".update-chip" in STYLE, "style.css 必须定义 .update-chip 样式"
    assert ".update-chip[hidden]" in STYLE, (
        "必须显式 .update-chip[hidden] { display: none }，"
        "否则作者样式的 display 会盖掉 hidden 属性（更新 chip 在无新版时反而可见）"
    )


def test_style_makes_manual_entry_discoverable():
    trigger_rule = re.search(r"#topbar-system\s*\{([^}]*)\}", STYLE, re.DOTALL)
    assert trigger_rule, "style.css 必须为 #topbar-system 定义交互样式"
    assert "cursor: pointer" in trigger_rule.group(1), "手动检查入口必须显示可点击指针"
    assert "#topbar-system:hover" in STYLE, "手动检查入口必须有 hover 视觉提示"
