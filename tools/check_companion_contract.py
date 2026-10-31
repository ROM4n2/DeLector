# -*- coding: utf-8 -*-
"""tools/check_companion_contract.py —— 伴学 Agent SSE 事件双向契约静态断言门禁.

依据: docs/plans/2026-10-31-companion-study-agent.md Task 6.
双向校验:
  1. Python 后端 (companion_agent.py) 产出的所有 SSE 事件必须被前端 (cp-drawer.js) 处理。
  2. 前端 (cp-drawer.js) 处理的所有 SSE 事件必须在后端契约集合中存在。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SPEC_EVENTS = {
    "thought",
    "tool_start",
    "tool_end",
    "delta",
    "proposal",
    "done",
    "error",
}


def _pin_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def extract_backend_events(py_path: Path) -> set[str]:
    """从 companion_agent.py 源码静态提取 {"event": "xxx"} 结构中的事件名."""
    content = py_path.read_text(encoding="utf-8")
    pattern = re.compile(r"""["']event["']\s*:\s*["'](\w+)["']""")
    return set(pattern.findall(content))


def extract_frontend_events(js_path: Path) -> set[str]:
    """从 cp-drawer.js 源码静态提取 event === event_name 分支的事件名."""
    content = js_path.read_text(encoding="utf-8")
    pattern = re.compile(r"""event\s*===\s*['"](\w+)['"]""")
    return set(pattern.findall(content))


def main() -> int:
    _pin_utf8_streams()
    py_file = ROOT / "delector" / "services" / "companion_agent.py"
    js_file = ROOT / "static" / "js" / "cp-drawer.js"

    if not py_file.is_file():
        print(f"[check_companion_contract] FAIL: 后端文件不存在: {py_file}")
        return 1
    if not js_file.is_file():
        print(f"[check_companion_contract] FAIL: 前端文件不存在: {js_file}")
        return 1

    backend_events = extract_backend_events(py_file)
    frontend_events = extract_frontend_events(js_file)

    errors: list[str] = []

    # 1. 后端产生但前端未处理
    missing_in_frontend = backend_events - frontend_events
    if missing_in_frontend:
        errors.append(f"后端触发但前端未消费的事件: {sorted(missing_in_frontend)}")

    # 2. 前端处理但后端未产生
    missing_in_backend = frontend_events - backend_events
    if missing_in_backend:
        errors.append(f"前端消费但后端未触发的事件: {sorted(missing_in_backend)}")

    # 3. 与规范契约 SPEC_EVENTS 比对
    drift_from_spec = (backend_events | frontend_events) ^ SPEC_EVENTS
    if drift_from_spec:
        errors.append(f"与规范契约 SPEC_EVENTS 存在漂移: {sorted(drift_from_spec)}")

    # 4. 机械校验 main.js window.CompanionDrawer 导出接口完整性（防 onclick 死绑定与未导出缺陷）
    main_js_file = ROOT / "static" / "js" / "main.js"
    if main_js_file.is_file():
        main_content = main_js_file.read_text(encoding="utf-8")
        required_drawer_methods = [
            "init",
            "toggle",
            "open",
            "close",
            "handleSend",
            "sendPrompt",
            "syncContext",
            "renderContextBar",
            "setReasoningEffort",
            "newSession",
            "switchSession",
            "refreshSessionSelect",
        ]
        for meth in required_drawer_methods:
            if f"{meth}:" not in main_content and f"{meth}," not in main_content:
                errors.append(f"main.js window.CompanionDrawer 缺少对外暴露接口: {meth}")

    if errors:
        print("[check_companion_contract] FAIL: 伴学双向契约校验失败!")
        for err in errors:
            print(f"  - {err}")
        return 1

    events_str = ", ".join(sorted(SPEC_EVENTS))
    print(f"[check_companion_contract] PASS: 伴学双向 SSE 契约完美对齐 ({len(SPEC_EVENTS)} 种事件: {events_str})。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
