# -*- coding: utf-8 -*-
"""伴学前端模块契约与分层机械检查 (Task 3).

依据: docs/plans/archive/2026-10-31-companion-study-agent.md Task 3.
"""

from __future__ import annotations

from pathlib import Path

from tools.check_frontend_layers import LAYER_SPEC, MUTABLE_STATE_MODULES, collect_violations


def test_companion_modules_registered_in_layer_spec() -> None:
    """cp-state.js 与 cp-api.js 必须受 check_frontend_layers 严格纳管."""
    assert "cp-state.js" in LAYER_SPEC
    assert "cp-api.js" in LAYER_SPEC
    assert LAYER_SPEC["cp-state.js"].layer == "L1 纯状态容器"
    assert LAYER_SPEC["cp-api.js"].layer == "L2 持久化访问层"

    assert "cp-state.js" in MUTABLE_STATE_MODULES
    assert "cp-api.js" in MUTABLE_STATE_MODULES


def test_companion_modules_zero_violations() -> None:
    """扫描 static/js 目录，伴学模块必须零分层违规."""
    js_dir = Path(__file__).resolve().parent.parent / "static" / "js"
    assert (js_dir / "cp-state.js").is_file()
    assert (js_dir / "cp-api.js").is_file()

    violations = collect_violations(js_dir, route_pairs=None)
    companion_violations = [v for v in violations if "cp-state.js" in v.rel_path or "cp-api.js" in v.rel_path]
    assert companion_violations == [], f"伴学模块分层违规: {[v.render() for v in companion_violations]}"


def test_companion_sse_contract_bidirectional_alignment() -> None:
    """三向断言探针: Python、Go 产出事件与 JS 前端消费分支必须对齐 SPEC_EVENTS."""
    from tools.check_companion_contract import main as check_contract_main

    exit_code = check_contract_main()
    assert exit_code == 0


_GO_TOOLS_SOURCE = """package companion

type EventType string

const (
    EventDelta EventType = "delta"
    EventThought EventType = "thought"
    EventToolStart EventType = "tool_start"
    EventToolEnd EventType = "tool_end"
    EventProposal EventType = "proposal"
    EventDone EventType = "done"
    EventError EventType = "error"
)
"""

_GO_LOOP_SOURCE = """package companion

func produce(emit func(Event) error) {
    _ = emit(Event{Event: EventDelta})
    _ = emit(Event{Event: EventThought})
    _ = emit(Event{Event: EventToolStart})
    _ = emit(Event{Event: EventToolEnd})
    _ = emit(Event{Event: EventProposal})
    _ = emit(Event{Event: EventDone})
    _ = emit(Event{Event: EventError})
}
"""


def _run_contract_with_go_sources(monkeypatch, tmp_path: Path, tools_source: str, loop_source: str) -> int:
    """在隔离源码树上运行总闸，避免为契约测试永久变异 Go 生产文件."""
    from tools import check_companion_contract as contract

    monkeypatch.setattr(contract, "ROOT", tmp_path)
    monkeypatch.setattr(contract, "_check_request_contract", lambda errors: None)
    monkeypatch.setattr(contract, "_check_multi_action_contract", lambda errors: None)

    py_file = tmp_path / "delector" / "services" / "companion_agent.py"
    js_file = tmp_path / "static" / "js" / "cp-drawer.js"
    tools_file = tmp_path / "agent" / "internal" / "companion" / "tools.go"
    loop_file = tmp_path / "agent" / "internal" / "companion" / "loop.go"
    for path in (py_file, js_file, tools_file, loop_file):
        path.parent.mkdir(parents=True, exist_ok=True)

    py_file.write_text(
        "\n".join(f'emit({{"event": "{event}"}})' for event in sorted(contract.SPEC_EVENTS)),
        encoding="utf-8",
    )
    js_file.write_text(
        "\n".join(f"if (event === '{event}') {{}}" for event in sorted(contract.SPEC_EVENTS)),
        encoding="utf-8",
    )
    tools_file.write_text(tools_source, encoding="utf-8")
    loop_file.write_text(loop_source, encoding="utf-8")
    return contract.main()


def test_companion_sse_contract_rejects_go_event_value_drift(monkeypatch, tmp_path: Path) -> None:
    """Go 常量值偏离规范时总闸必须红，不能由 Python/JS 对齐所掩盖."""
    mutated_tools = _GO_TOOLS_SOURCE.replace('EventDone EventType = "done"', 'EventDone EventType = "finished"')
    assert _run_contract_with_go_sources(monkeypatch, tmp_path, mutated_tools, _GO_LOOP_SOURCE) == 1


def test_companion_sse_contract_rejects_swapped_go_event_values(monkeypatch, tmp_path: Path) -> None:
    """交换常量值仍保持值集合与 emit 集合不变，但常量到 wire value 映射必须红."""
    mutated_tools = _GO_TOOLS_SOURCE.replace(
        'EventDelta EventType = "delta"', 'EventDelta EventType = "done"'
    ).replace('EventDone EventType = "done"', 'EventDone EventType = "delta"')
    assert _run_contract_with_go_sources(monkeypatch, tmp_path, mutated_tools, _GO_LOOP_SOURCE) == 1


def test_companion_sse_contract_rejects_go_event_without_production_emit(monkeypatch, tmp_path: Path) -> None:
    """常量只被 Go 测试引用不算生产 emit，总闸仍必须红."""
    mutated_loop = _GO_LOOP_SOURCE.replace("    _ = emit(Event{Event: EventDone})\n", "")
    test_file = tmp_path / "agent" / "internal" / "companion" / "loop_test.go"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("package companion\nvar _ = EventDone\n", encoding="utf-8")
    assert _run_contract_with_go_sources(monkeypatch, tmp_path, _GO_TOOLS_SOURCE, mutated_loop) == 1

