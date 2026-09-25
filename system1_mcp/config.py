"""Configuration management and persistent settings for System 1 MCP.

Supports tiered key resolution:
1. Process Environment Variable (TYPESAFE_API_KEY)
2. Global User Configuration (~/.system1/config.json with fallback to ~/.fastpath/config.json)
3. Local Workspace .env file
"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
from dotenv import load_dotenv


@dataclass
class System1Config:
    """System 1 MCP runtime configuration."""
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    default_model: str = "jev-latest"
    timeout_seconds: float = 5.0
    cache_ttl_seconds: float = 300.0
    backend: str = "auto"
    local_model_path: Optional[str] = None


def get_config_dir() -> Path:
    """Return the global configuration directory (~/.system1 or SYSTEM1_CONFIG_DIR)."""
    override = os.environ.get("SYSTEM1_CONFIG_DIR") or os.environ.get("FASTPATH_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".system1"


def get_config_path() -> Path:
    """Return path to global config.json."""
    return get_config_dir() / "config.json"


def get_legacy_config_path() -> Path:
    """Return path to legacy ~/.fastpath/config.json for backward compatibility."""
    return Path.home() / ".fastpath" / "config.json"


def mask_api_key(key: Optional[str]) -> str:
    """Return a masked representation of an API key for safe display."""
    if not key or not isinstance(key, str):
        return "<not set>"
    key = key.strip()
    if len(key) <= 8:
        return "[REDACTED]"
    if key.startswith("ts_"):
        return f"ts_...{key[-4:]}"
    return f"{key[:3]}...{key[-4:]}"


def load_persisted_config() -> Dict[str, Any]:
    """Read raw persisted config dictionary from ~/.system1/config.json (or ~/.fastpath fallback)."""
    config_path = get_config_path()
    target_path = config_path if config_path.exists() else get_legacy_config_path()

    if not target_path.exists():
        return {}
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(config: System1Config) -> Path:
    """Save configuration to ~/.system1/config.json with secure file permissions."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_config_path()

    payload = asdict(config)
    tmp_path = config_path.with_suffix(f".tmp_{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # Enforce POSIX owner-only permissions (0600)
    if os.name != "nt":
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass

    tmp_path.replace(config_path)

    if os.name != "nt":
        try:
            os.chmod(config_path, 0o600)
        except OSError:
            pass

    return config_path


def resolve_api_key() -> Tuple[Optional[str], str]:
    """Resolve API key using tiered resolution order:

    1. Process Environment Variable (TYPESAFE_API_KEY)
    2. Global User Configuration (~/.system1/config.json or legacy ~/.fastpath)
    3. Workspace .env file

    Returns:
        Tuple of (resolved_key, source_name)
    """
    # 1. Check direct process environment
    env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env_key:
        return env_key, "env"

    # 2. Check global user configuration (~/.system1/config.json)
    persisted = load_persisted_config()
    stored_key = (persisted.get("api_key") or "").strip()
    if stored_key:
        return stored_key, "config_file"

    # 3. Check workspace .env file
    load_dotenv()
    dotenv_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if dotenv_key:
        return dotenv_key, "dotenv"

    return None, "missing"


def resolve_local_model_path(custom_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Resolve the directory containing the local Verdict ONNX model and tokenizer.

    Resolution order:
    1. Explicit custom_path argument
    2. config.local_model_path from persisted ~/.system1/config.json
    3. SYSTEM1_LOCAL_MODEL_PATH environment variable
    4. ~/.system1/models/verdict
    """

    candidates = []
    if custom_path:
        candidates.append(Path(custom_path))

    persisted = load_persisted_config()
    cfg_path = persisted.get("local_model_path")
    if cfg_path:
        candidates.append(Path(cfg_path))

    env_path = os.environ.get("SYSTEM1_LOCAL_MODEL_PATH")
    if env_path:
        candidates.append(Path(env_path))

    # Standard user configuration path (~/.system1/models/verdict)
    candidates.append(get_config_dir() / "models" / "verdict")

    for cand in candidates:
        if cand.is_dir():
            model_file = cand / "model.onnx"
            tokenizer_file = cand / "tokenizer.json"
            if model_file.is_file() and tokenizer_file.is_file():
                return cand

    return None


def load_config() -> System1Config:
    """Load full System1Config merging file persistence and environment."""
    persisted = load_persisted_config()
    key, _ = resolve_api_key()

    endpoint = os.environ.get("TYPESAFE_ENDPOINT") or persisted.get("endpoint")
    default_model = persisted.get("default_model", "jev-latest")
    timeout = float(persisted.get("timeout_seconds", 5.0))
    cache_ttl = float(persisted.get("cache_ttl_seconds", os.environ.get("SYSTEM1_CACHE_TTL", 300.0)))
    backend = os.environ.get("SYSTEM1_BACKEND") or persisted.get("backend", "auto")
    local_model = os.environ.get("SYSTEM1_LOCAL_MODEL_PATH") or persisted.get("local_model_path")

    return System1Config(
        api_key=key,
        endpoint=endpoint,
        default_model=default_model,
        timeout_seconds=timeout,
        cache_ttl_seconds=cache_ttl,
        backend=backend.lower().strip(),
        local_model_path=str(local_model) if local_model else None,
    )

