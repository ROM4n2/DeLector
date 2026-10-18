# -*- coding: utf-8 -*-
"""tools/check_layer_invariants.py 机械闸单元测试与变异自证套件。"""

import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "tools" / "check_layer_invariants.py"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_module() -> Any:
    if not _SCRIPT.exists():
        pytest.fail(f"判定器脚本不存在：{_SCRIPT}（分层机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_layer_invariants", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_layer_invariants"] = module
    spec.loader.exec_module(module)
    return module


def test_repo_layers_pass_clean(tmp_path: Path) -> None:
    """真实仓库扫描必须返回 exit 0 且无未豁免违规。"""
    mod = _load_module()
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = mod.run_gate(_REPO_ROOT, stdout=buf_out, stderr=buf_err)
    assert code == 0, f"真实仓库分层检查失败:\n{buf_err.getvalue()}"
    assert "通过: 全仓分层与依赖规范符合 100% 单向层序" in buf_out.getvalue()


def test_reverse_layer_import_triggers_failure(tmp_path: Path) -> None:
    """变异自证 1: 低层顶层导入高层且未带豁免时，机械闸必须 exit 1。"""
    mod = _load_module()
    dummy_repo = tmp_path / "repo"
    core_dir = dummy_repo / "delector" / "core"
    routes_dir = dummy_repo / "delector" / "routes"
    core_dir.mkdir(parents=True)
    routes_dir.mkdir(parents=True)

    (routes_dir / "mod_b.py").write_text("x = 1\n", encoding="utf-8")
    # core (Layer 1) 逆向导入 routes (Layer 5)
    (core_dir / "mod_a.py").write_text("from delector.routes import mod_b\n", encoding="utf-8")

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = mod.run_gate(dummy_repo, stdout=buf_out, stderr=buf_err)
    assert code == 1, "未拦截跨层逆向导入"
    assert "跨层逆向导入" in buf_err.getvalue()


def test_reverse_layer_import_with_valid_exemption_passes(tmp_path: Path) -> None:
    """变异自证 2: 带有明确理由的 # layer-ok: <REASON> 豁免时放行 exit 0。"""
    mod = _load_module()
    dummy_repo = tmp_path / "repo"
    core_dir = dummy_repo / "delector" / "core"
    routes_dir = dummy_repo / "delector" / "routes"
    core_dir.mkdir(parents=True)
    routes_dir.mkdir(parents=True)

    (routes_dir / "mod_b.py").write_text("x = 1\n", encoding="utf-8")
    (core_dir / "mod_a.py").write_text(
        "# layer-ok: 合法架构垫片测试\nfrom delector.routes import mod_b\n",
        encoding="utf-8",
    )

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = mod.run_gate(dummy_repo, stdout=buf_out, stderr=buf_err)
    assert code == 0, f"合法豁免未能放行: {buf_err.getvalue()}"
    assert "[exempt]" in buf_out.getvalue()
    assert "合法架构垫片测试" in buf_out.getvalue()


def test_empty_exemption_reason_is_rejected(tmp_path: Path) -> None:
    """变异自证 3: 空理由的 # layer-ok: 视为假豁免，依然 exit 1。"""
    mod = _load_module()
    dummy_repo = tmp_path / "repo"
    core_dir = dummy_repo / "delector" / "core"
    routes_dir = dummy_repo / "delector" / "routes"
    core_dir.mkdir(parents=True)
    routes_dir.mkdir(parents=True)

    (routes_dir / "mod_b.py").write_text("x = 1\n", encoding="utf-8")
    (core_dir / "mod_a.py").write_text(
        "# layer-ok:   \nfrom delector.routes import mod_b\n",
        encoding="utf-8",
    )

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = mod.run_gate(dummy_repo, stdout=buf_out, stderr=buf_err)
    assert code == 1, "假豁免（空理由）未被拦截"


def test_top_level_cycle_triggers_failure(tmp_path: Path) -> None:
    """变异自证 4: 同层或跨层顶层双向循环 (A ⇄ B) 必须 exit 1。"""
    mod = _load_module()
    dummy_repo = tmp_path / "repo"
    services_dir = dummy_repo / "delector" / "services"
    services_dir.mkdir(parents=True)

    (services_dir / "svc_a.py").write_text("from delector.services import svc_b\n", encoding="utf-8")
    (services_dir / "svc_b.py").write_text("from delector.services import svc_a\n", encoding="utf-8")

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    code = mod.run_gate(dummy_repo, stdout=buf_out, stderr=buf_err)
    assert code == 1, "未拦截顶层双向循环依赖"
    assert "顶层双向循环依赖" in buf_err.getvalue()


def test_ci_workflow_invokes_check_layer_invariants() -> None:
    """CI 契约守卫：.github/workflows/ci.yml 必须包含该机械闸调用。"""
    assert _CI_WORKFLOW.exists(), f"CI 配置文件不存在：{_CI_WORKFLOW}"
    text = _CI_WORKFLOW.read_text(encoding="utf-8")
    assert "python3 tools/check_layer_invariants.py" in text, (
        "ci.yml 缺少 check_layer_invariants 机械闸调用"
    )

