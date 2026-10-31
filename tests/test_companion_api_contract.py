# -*- coding: utf-8 -*-
"""伴学前端模块契约与分层机械检查 (Task 3).

依据: docs/plans/2026-10-31-companion-study-agent.md Task 3.
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
    companion_violations = [v for v in violations if "cp-state.js" in v.file or "cp-api.js" in v.file]
    assert companion_violations == [], f"伴学模块分层违规: {[v.render() for v in companion_violations]}"


def test_companion_sse_contract_bidirectional_alignment() -> None:
    """双向断言探针: Python 后端产出事件与 JS 前端消费分支必须 100% 对齐 SPEC_EVENTS."""
    from tools.check_companion_contract import main as check_contract_main

    exit_code = check_contract_main()
    assert exit_code == 0

