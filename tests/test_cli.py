"""Unit tests for system1_mcp.cli module."""

from unittest.mock import MagicMock, patch
import pytest

from system1_mcp.cli import main


def test_cli_zero_arg_defaults_to_server():
    with patch("system1_mcp.cli.run_server") as mock_server:
        # Zero arguments
        ret = main([])
        assert ret == 0
        mock_server.assert_called_once()


def test_cli_serve_subcommand():
    with patch("system1_mcp.cli.run_server") as mock_server:
        ret = main(["serve"])
        assert ret == 0
        mock_server.assert_called_once()


def test_cli_config_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))

    # set-key
    ret_set = main(["config", "set-key", "ts_cli_set_key"])
    assert ret_set == 0

    # get / show
    ret_get = main(["config", "show"])
    assert ret_get == 0
    captured = capsys.readouterr()
    assert "ts_..._key" in captured.out or "ts_...key" in captured.out or "ts_cli_set_key" in captured.out or "Active API Key" in captured.out


def test_cli_doctor_missing_key(monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with patch("system1_mcp.cli.resolve_api_key", return_value=(None, "missing")):
        ret = main(["doctor"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Missing TYPESAFE_API_KEY" in captured.err or "System 1 MCP Diagnostics" in captured.err


def test_cli_doctor_cache_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))
    with patch("system1_mcp.cli.resolve_api_key", return_value=(None, "missing")):
        ret = main(["doctor"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Response Cache Status:" in captured.err
        assert "Hits:" in captured.err
        assert "Misses:" in captured.err
        assert "Cache TTL:" in captured.err
        assert "Decision Backend Status:" in captured.err


def test_cli_config_backend_and_model_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))

    # set-backend
    ret_b = main(["config", "set-backend", "local"])
    assert ret_b == 0

    # set-model-path
    ret_m = main(["config", "set-model-path", str(tmp_path / "models")])
    assert ret_m == 0

    # show
    ret_show = main(["config", "show"])
    assert ret_show == 0
    captured = capsys.readouterr()
    assert "Backend Mode:     local" in captured.out
    assert "Local Model Path:" in captured.out

