from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from delector.core.go_agent_supervisor import (
    GO_AGENT_PORT_CANDIDATES,
    GO_AGENT_SERVICE_ID,
    GoAgentSupervisor,
    pick_agent_port,
)


def test_supervisor_command_discovery_with_binary(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    binary_name = "delector.exe" if os.name == "nt" else "delector"
    binary = agent_dir / binary_name
    binary.write_text("dummy binary")
    binary.chmod(0o755)

    supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path, python_port=8000)
    cmd, cwd = supervisor.find_command()
    assert cmd is not None
    assert str(binary) in cmd[0]
    assert cmd[1:] == ["agent", "--port", "8002", "--python-url", "http://127.0.0.1:8000"]
    assert cwd == agent_dir


def test_supervisor_command_discovery_with_go_cli(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "go.mod").write_text("module test\n")

    with patch("shutil.which", return_value="C:\\Go\\bin\\go.exe"):
        supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path, python_port=8000)
        cmd, cwd = supervisor.find_command()
        assert cmd is not None
        assert "go.exe" in cmd[0]
        assert cmd[1:] == ["run", "./cmd/delector", "agent", "--port", "8002", "--python-url", "http://127.0.0.1:8000"]
        assert cwd == agent_dir


def test_supervisor_command_discovery_none(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    with patch("shutil.which", return_value=None):
        supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path)
        cmd, cwd = supervisor.find_command()
        assert cmd is None
        assert cwd == agent_dir


def test_go_fallback_ports_are_disjoint_from_python_candidates() -> None:
    """8002 是双方共用的历史首选；但 Go 的**顺延区间** MUST 与 Python 候选完全不重叠。"""
    from start import PORT_CANDIDATES

    overlap = set(GO_AGENT_PORT_CANDIDATES[1:]) & set(PORT_CANDIDATES)
    assert not overlap, f"Go 顺延端口与 Python 候选重叠 {sorted(overlap)}"


def test_pick_agent_port_never_returns_python_port() -> None:
    """Python 顺延到 8002 时，Go MUST 跳过它选 8011（否则同端口双 bind，主服务被遮蔽）。"""
    port = pick_agent_port(python_port=8002, probe=lambda _p: False)

    assert port == 8011, f"Go 端口不得等于 Python 端口 8002，实际 {port}"


def test_pick_agent_port_skips_busy_candidates() -> None:
    """候选逐个顺延：8002 被陌生程序占、8011 与 Python 冲突 ⇒ 取 8012。"""
    busy = {8002}

    port = pick_agent_port(python_port=8011, probe=lambda p: p in busy)

    assert port == 8012, f"应跳过被占用/冲突的候选，实际 {port}"


def test_pick_agent_port_returns_none_when_all_busy() -> None:
    assert pick_agent_port(python_port=8000, probe=lambda _p: True) is None


def test_supervisor_refuses_to_bind_python_port() -> None:
    """显式传入与 Python 相同的端口 ⇒ MUST 拒绝启动，且不拉起子进程。"""
    supervisor = GoAgentSupervisor(port=8002, python_port=8002)

    with patch("subprocess.Popen") as mock_popen:
        assert supervisor.start(deadline_s=0.1) is False
        mock_popen.assert_not_called()
    assert "与 Python 主服务端口相同" in supervisor.last_error


def test_supervisor_auto_port_excludes_python_port() -> None:
    with patch("delector.core.go_agent_supervisor.pick_agent_port", return_value=8011) as mock_pick:
        supervisor = GoAgentSupervisor(python_port=8002)

    mock_pick.assert_called_once_with(8002)
    assert supervisor.port == 8011


def test_health_requires_go_agent_service_identity() -> None:
    """`status=ok` 不足以证明是 Go Agent；service 字段必须匹配。"""
    supervisor = GoAgentSupervisor(port=8011)

    ok_other = MagicMock(status_code=200)
    ok_other.json.return_value = {"status": "ok"}
    with patch("delector.core.go_agent_supervisor.httpx.get", return_value=ok_other):
        assert supervisor.is_healthy() is False

    ok_go = MagicMock(status_code=200)
    ok_go.json.return_value = {"status": "ok", "service": GO_AGENT_SERVICE_ID}
    with patch("delector.core.go_agent_supervisor.httpx.get", return_value=ok_go):
        assert supervisor.is_healthy() is True


def test_supervisor_start_and_health_poll_success() -> None:
    supervisor = GoAgentSupervisor(port=8002)

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None

    with patch.object(supervisor, "find_command", return_value=(["mock_agent"], None)):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch.object(supervisor, "is_healthy", side_effect=[False, False, True]):
                success = supervisor.start(deadline_s=2.0)
                assert success is True
                assert supervisor.is_running() is True


def test_supervisor_start_timeout_cleans_up() -> None:
    supervisor = GoAgentSupervisor(port=8002)

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None

    with patch.object(supervisor, "find_command", return_value=(["mock_agent"], None)):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch.object(supervisor, "is_healthy", return_value=False):
                with patch.object(supervisor, "stop") as mock_stop:
                    success = supervisor.start(deadline_s=0.2)
                    assert success is False
                    mock_stop.assert_called_once()


def test_supervisor_stop_terminates_and_waits() -> None:
    supervisor = GoAgentSupervisor(port=8002)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    supervisor.proc = mock_proc

    supervisor.stop(grace_s=1.0)
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once_with(timeout=1.0)
    assert supervisor.proc is None


def test_supervisor_start_injects_settings_env() -> None:
    supervisor = GoAgentSupervisor(port=8002)

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None

    with patch.object(supervisor, "find_command", return_value=(["mock_agent"], Path("agent"))), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch.object(supervisor, "is_healthy", side_effect=[False, True]), \
         patch("delector.core.db.settings.get_effective_api_key", return_value="sk-test-key"), \
         patch("delector.core.db.settings.get_effective_api_base_url", return_value="https://api.test.com"), \
         patch("delector.core.db.settings.get_effective_api_model", return_value="test-model"):

        success = supervisor.start(deadline_s=1.0)
        assert success is True
        mock_popen.assert_called_once()
        _, kwargs = mock_popen.call_args
        env = kwargs.get("env", {})
        assert env.get("DEEPSEEK_API_KEY") == "sk-test-key"
        assert env.get("API_BASE_URL") == "https://api.test.com"
        assert env.get("API_MODEL") == "test-model"
