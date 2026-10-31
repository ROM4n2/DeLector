from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

from delector.core.go_agent_supervisor import GoAgentSupervisor


def test_supervisor_command_discovery_with_binary(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    binary = agent_dir / "delector.exe"
    binary.write_text("dummy binary")

    supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path)
    cmd, cwd = supervisor.find_command()
    assert cmd is not None
    assert str(binary) in cmd[0]
    assert cmd[1:] == ["agent", "--port", "8002"]
    assert cwd == agent_dir


def test_supervisor_command_discovery_with_go_cli(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "go.mod").write_text("module test\n")

    with patch("shutil.which", return_value="C:\\Go\\bin\\go.exe"):
        supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path)
        cmd, cwd = supervisor.find_command()
        assert cmd is not None
        assert "go.exe" in cmd[0]
        assert cmd[1:] == ["run", "./cmd/delector", "agent", "--port", "8002"]
        assert cwd == agent_dir


def test_supervisor_command_discovery_none(tmp_path: Any) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    with patch("shutil.which", return_value=None):
        supervisor = GoAgentSupervisor(port=8002, root_dir=tmp_path)
        cmd, cwd = supervisor.find_command()
        assert cmd is None
        assert cwd == agent_dir


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
