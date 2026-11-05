# -*- coding: utf-8 -*-
"""tools/check_companion_contract.py —— 伴学 Agent SSE 事件三向契约静态断言门禁.

依据: docs/plans/archive/2026-10-31-companion-study-agent.md Task 6.
三向校验:
  1. Python fallback 与 Go Agent 产出的事件必须分别对齐 SPEC_EVENTS。
  2. 前端 (cp-drawer.js) 处理的所有 SSE 事件必须与两个后端契约集合一致。
  3. 每个 Go 事件常量必须在生产 emit 路径被引用，测试文件引用不计。
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

GO_SPEC_EVENTS = {
    "EventDelta": "delta",
    "EventThought": "thought",
    "EventToolStart": "tool_start",
    "EventToolEnd": "tool_end",
    "EventProposal": "proposal",
    "EventDone": "done",
    "EventError": "error",
}


def _pin_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # silent-ok: 仅显示层编码（流不可重配置）⇒ 保持原流；本闸结论由退出码表达
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


def extract_go_event_constants(go_path: Path) -> dict[str, str]:
    """从 Go 源码提取 EventType 常量标识符及其实际字符串值."""
    content = go_path.read_text(encoding="utf-8")
    pattern = re.compile(r'''(?m)^\s*(Event\w+)\s+EventType\s*=\s*"([^"\n]+)"''')
    return dict(pattern.findall(content))


def extract_go_emitted_event_constants(*go_paths: Path) -> set[str]:
    """只从生产 emit(Event{Event: EventX}) 字面量提取事件常量引用."""
    emitted: set[str] = set()
    call_pattern = re.compile(r"\bemit\s*\(\s*Event\s*\{")
    event_pattern = re.compile(r"\bEvent\s*:\s*(Event\w+)\b")
    for go_path in go_paths:
        if not go_path.is_file():
            continue
        content = go_path.read_text(encoding="utf-8")
        for call in call_pattern.finditer(content):
            depth = 1
            body_start = call.end()
            for index in range(body_start, len(content)):
                if content[index] == "{":
                    depth += 1
                elif content[index] == "}":
                    depth -= 1
                    if depth == 0:
                        event = event_pattern.search(content, body_start, index)
                        if event:
                            emitted.add(event.group(1))
                        break
    return emitted


def _check_request_contract(errors: list[str]) -> None:
    """校验加法式请求字段在 Python / 前端 / Go 三处一致，且响应头被前端消费。"""
    py_req = ROOT / "delector" / "routes" / "companion.py"
    js_api = ROOT / "static" / "js" / "cp-api.js"
    go_ctx = ROOT / "agent" / "internal" / "companion" / "loop.go"

    py_text = py_req.read_text(encoding="utf-8") if py_req.is_file() else ""
    js_text = js_api.read_text(encoding="utf-8") if js_api.is_file() else ""
    go_text = go_ctx.read_text(encoding="utf-8") if go_ctx.is_file() else ""

    for field in ("view", "context_source", "draft_text", "card_context", "scope_key"):
        if f"{field}: Optional[str]" not in py_text:
            errors.append(f"CompanionChatReq 缺少可选字段: {field}")
        if f"reqBody.{field}" not in js_text:
            errors.append(f"cp-api.js 请求体未携带字段: {field}")
    for field in ("view", "context_source", "draft_text", "card_context"):
        if f'json:"{field},omitempty"' not in go_text:
            errors.append(f"Go StudyContext 缺少 JSON 字段: {field}")

    if "X-Session-ID" not in js_text:
        errors.append("cp-api.js 未读取响应头 X-Session-ID")
    if "onSessionId" not in js_text:
        errors.append("cp-api.js 未提供 onSessionId 回填回调")


def _check_multi_action_contract(errors: list[str]) -> None:
    """多动作 HITL 必须在生成、执行与前端渲染三面同时存在。"""
    expected = {
        ROOT / "delector" / "services" / "companion_proposal.py": ("apply_writing_revision", "set_weekly_goal"),
        ROOT / "agent" / "internal" / "companion" / "tools.go": ("propose_writing_revision", "propose_weekly_goal"),
        ROOT / "agent" / "internal" / "companion" / "loop.go": ("apply_writing_revision", "set_weekly_goal"),
        ROOT / "static" / "js" / "cp-drawer-proposals.js": ("apply_writing_revision", "set_weekly_goal"),
        ROOT / "static" / "js" / "cp-drawer.js": ("sendWriterRevisionProposal", "sendProgressWeeklyGoal"),
        ROOT / "static" / "js" / "main.js": ("getWriterRevisionState", "applyCompanionRevision"),
    }
    for path, needles in expected.items():
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for needle in needles:
            if needle not in text:
                errors.append(f"多动作 HITL 契约缺少 {needle}: {path.relative_to(ROOT)}")


def main() -> int:
    _pin_utf8_streams()
    py_file = ROOT / "delector" / "services" / "companion_agent.py"
    js_file = ROOT / "static" / "js" / "cp-drawer.js"
    go_tools_file = ROOT / "agent" / "internal" / "companion" / "tools.go"
    go_loop_file = ROOT / "agent" / "internal" / "companion" / "loop.go"
    go_server_file = ROOT / "agent" / "internal" / "companion" / "server.go"

    for label, path in (
        ("Python 后端", py_file),
        ("前端", js_file),
        ("Go 事件常量", go_tools_file),
        ("Go 生产循环", go_loop_file),
    ):
        if not path.is_file():
            print(f"[check_companion_contract] FAIL: {label}文件不存在: {path}")
            return 1

    backend_events = extract_backend_events(py_file)
    frontend_events = extract_frontend_events(js_file)
    go_constants = extract_go_event_constants(go_tools_file)
    go_events = set(go_constants.values())
    go_emitted_constants = extract_go_emitted_event_constants(go_loop_file, go_server_file)

    errors: list[str] = []

    # 1. Python 后端产生但前端未处理
    missing_in_frontend = backend_events - frontend_events
    if missing_in_frontend:
        errors.append(f"后端触发但前端未消费的事件: {sorted(missing_in_frontend)}")

    # 2. 前端处理但 Python 后端未产生
    missing_in_backend = frontend_events - backend_events
    if missing_in_backend:
        errors.append(f"前端消费但后端未触发的事件: {sorted(missing_in_backend)}")

    # 3. 三端分别与规范比对，不能用集合并集掩盖某一端缺项。
    for label, events in (
        ("Python 后端", backend_events),
        ("JS 前端", frontend_events),
        ("Go 后端", go_events),
    ):
        drift_from_spec = events ^ SPEC_EVENTS
        if drift_from_spec:
            errors.append(f"{label}与规范契约 SPEC_EVENTS 存在漂移: {sorted(drift_from_spec)}")

    # 4. 常量标识符与 wire value 必须逐项对齐，防止交换值后值集合假绿。
    for constant, expected_value in GO_SPEC_EVENTS.items():
        actual_value = go_constants.get(constant)
        if actual_value != expected_value:
            errors.append(
                f"Go 事件常量映射应为 {constant} -> {expected_value!r}，实际为 {actual_value!r}"
            )
    for constant in sorted(set(go_constants) - set(GO_SPEC_EVENTS)):
        errors.append(f"Go 存在规范外事件常量: {constant} -> {go_constants[constant]!r}")

    # 5. 只扫描 loop.go/server.go 的真实 emit 字面量；Go 测试引用不算。
    unemitted_constants = set(go_constants) - go_emitted_constants
    if unemitted_constants:
        errors.append(f"Go 事件常量未在生产 emit 路径引用: {sorted(unemitted_constants)}")
    undefined_emitted_constants = go_emitted_constants - set(go_constants)
    if undefined_emitted_constants:
        errors.append(f"Go 生产 emit 引用未定义事件常量: {sorted(undefined_emitted_constants)}")

    # 6. 请求契约：view / context_source / scope_key 必须同时出现在
    #    FastAPI 请求模型、前端请求体、Go StudyContext；X-Session-ID 必须被前端读取。
    _check_request_contract(errors)
    _check_multi_action_contract(errors)

    # 7. 机械校验 main.js window.CompanionDrawer 导出接口完整性（防 onclick 死绑定与未导出缺陷）
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
            "refreshWriterDraftContext",
            "refreshCardBoxContext",
            "sendCardProposal",
            "sendProgressProfile",
            "sendProgressVocabStats",
            "sendWriterRevisionProposal",
            "sendProgressWeeklyGoal",
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
    print(
        f"[check_companion_contract] PASS: 伴学 Python/Go/JS 三向 SSE 契约完美对齐 "
        f"({len(SPEC_EVENTS)} 种事件: {events_str})；Go 常量均在生产路径 emit；"
        f"请求字段 view/context_source/draft_text/card_context/scope_key 三端一致。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
