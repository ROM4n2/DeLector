from __future__ import annotations

from unittest.mock import MagicMock, patch

from start import _parse_args, main


def test_parse_args_supports_no_agent() -> None:
    args_default = _parse_args([])
    assert args_default.no_agent is False

    args_no_agent = _parse_args(["--no-agent"])
    assert args_no_agent.no_agent is True


def test_main_starts_and_stops_go_agent_supervisor() -> None:
    mock_sup = MagicMock()
    mock_sup.start.return_value = True

    mock_decision = MagicMock()
    mock_decision.port = 8000
    mock_decision.lock = MagicMock()

    with patch("start.claim_instance", return_value=mock_decision), \
         patch("start.bootstrap_data_dir"), \
         patch("start.is_android", return_value=False), \
         patch("start.get_bind_host", return_value="127.0.0.1"), \
         patch("start.print_banner"), \
         patch("start.open_browser"), \
         patch("delector.core.server_lifecycle.build_server") as mock_build, \
         patch("delector.core.server_lifecycle.serve_in_thread") as mock_serve, \
         patch("delector.core.server_lifecycle.shutdown", return_value=True), \
         patch("delector.core.go_agent_supervisor.GoAgentSupervisor", return_value=mock_sup):

        mock_server = MagicMock()
        mock_build.return_value = mock_server

        mock_thread = MagicMock()
        mock_thread.is_alive.side_effect = [True, False]
        mock_serve.return_value = mock_thread

        main(debug_console=True, no_agent=False)

        mock_sup.start.assert_called_once()
        mock_sup.stop.assert_called_once()
        mock_decision.lock.release.assert_called_once()


def test_main_with_no_agent_flag_skips_supervisor() -> None:
    mock_sup = MagicMock()

    mock_decision = MagicMock()
    mock_decision.port = 8000
    mock_decision.lock = MagicMock()

    with patch("start.claim_instance", return_value=mock_decision), \
         patch("start.bootstrap_data_dir"), \
         patch("start.is_android", return_value=False), \
         patch("start.get_bind_host", return_value="127.0.0.1"), \
         patch("start.print_banner"), \
         patch("start.open_browser"), \
         patch("delector.core.server_lifecycle.build_server") as mock_build, \
         patch("delector.core.server_lifecycle.serve_in_thread") as mock_serve, \
         patch("delector.core.server_lifecycle.shutdown", return_value=True), \
         patch("delector.core.go_agent_supervisor.GoAgentSupervisor", return_value=mock_sup):

        mock_server = MagicMock()
        mock_build.return_value = mock_server

        mock_thread = MagicMock()
        mock_thread.is_alive.side_effect = [True, False]
        mock_serve.return_value = mock_thread

        main(debug_console=True, no_agent=True)

        mock_sup.start.assert_not_called()
        mock_sup.stop.assert_not_called()
