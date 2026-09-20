"""Unit tests for system1_mcp.installer module."""

import json
from pathlib import Path
import pytest

from system1_mcp.installer import (
    build_mcp_entry,
    clean_jsonc,
    inspect_targets,
    install_to_target,
)


def test_clean_jsonc():
    raw_jsonc = """
    {
        // Line comment
        "mcpServers": {
            /* Block comment */
            "existing": {
                "command": "python",
                "args": ["-m", "demo"],
            },
        },
    }
    """
    cleaned = clean_jsonc(raw_jsonc)
    data = json.loads(cleaned)
    assert "mcpServers" in data
    assert "existing" in data["mcpServers"]


def test_build_mcp_entry():
    uvx_entry = build_mcp_entry(mode="uvx")
    assert uvx_entry["command"] == "uvx"
    assert uvx_entry["args"] == ["system1-mcp"]
    assert "env" not in uvx_entry

    uvx_with_key = build_mcp_entry(mode="uvx", api_key="ts_test_123")
    assert uvx_with_key["env"]["TYPESAFE_API_KEY"] == "ts_test_123"

    python_entry = build_mcp_entry(mode="python")
    assert "system1_mcp.server" in python_entry["args"]


def test_install_to_target_preserves_backups(tmp_path):
    base_dir = tmp_path / "user_home"
    base_dir.mkdir()

    # Pre-populate Claude Desktop config with an existing server and stale fastpath entry
    claude_dir = base_dir / "AppData" / "Roaming" / "Claude"
    claude_dir.mkdir(parents=True)
    config_file = claude_dir / "claude_desktop_config.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "old_server": {"command": "node"},
                    "fastpath": {"command": "uvx", "args": ["fastpath-mcp"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    success, msg = install_to_target(
        target_id="claude",
        mode="uvx",
        api_key="ts_injected_key",
        system="Windows",
        base_dir=base_dir,
    )

    assert success is True
    assert config_file.exists()

    # Verify original backup created
    orig_bak = config_file.with_suffix(".json.orig.bak")
    assert orig_bak.exists()
    orig_data = json.loads(orig_bak.read_text(encoding="utf-8"))
    assert "old_server" in orig_data["mcpServers"]
    assert "system1" not in orig_data["mcpServers"]

    # Verify updated file contains old_server and system1, and cleaned legacy fastpath
    updated_data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "old_server" in updated_data["mcpServers"]
    assert "system1" in updated_data["mcpServers"]
    assert "fastpath" not in updated_data["mcpServers"]
    assert updated_data["mcpServers"]["system1"]["command"] == "uvx"
    assert updated_data["mcpServers"]["system1"]["args"] == ["system1-mcp"]
    assert updated_data["mcpServers"]["system1"]["env"]["TYPESAFE_API_KEY"] == "ts_injected_key"
