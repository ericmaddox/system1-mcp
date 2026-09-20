"""Unit tests for system1_mcp.config module."""

import os
from pathlib import Path
import pytest

from system1_mcp.config import (
    System1Config,
    get_config_dir,
    get_config_path,
    load_config,
    load_persisted_config,
    mask_api_key,
    resolve_api_key,
    save_config,
)


def test_mask_api_key():
    assert mask_api_key(None) == "<not set>"
    assert mask_api_key("") == "<not set>"
    assert mask_api_key("12345") == "[REDACTED]"
    assert mask_api_key("ts_live_9876543210") == "ts_...3210"
    assert mask_api_key("custom_secret_key_1234") == "cus...1234"


def test_config_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))

    cfg = System1Config(
        api_key="ts_test_key_abc",
        endpoint="https://custom.endpoint.ai",
        default_model="jev-v1",
        timeout_seconds=8.0,
    )

    saved_path = save_config(cfg)
    assert saved_path.exists()
    assert saved_path == tmp_path / "config.json"

    loaded = load_persisted_config()
    assert loaded["api_key"] == "ts_test_key_abc"
    assert loaded["endpoint"] == "https://custom.endpoint.ai"
    assert loaded["default_model"] == "jev-v1"
    assert loaded["timeout_seconds"] == 8.0


def test_resolve_api_key_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))

    # Case 1: Environment variable has highest priority
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_env_priority")
    save_config(System1Config(api_key="ts_stored_file"))

    key, source = resolve_api_key()
    assert key == "ts_env_priority"
    assert source == "env"

    # Case 2: Config file takes priority when env var is absent
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    key, source = resolve_api_key()
    assert key == "ts_stored_file"
    assert source == "config_file"

    # Case 3: Missing when both absent
    save_config(System1Config(api_key=None))
    key, source = resolve_api_key()
    assert key is None
    assert source == "missing"
