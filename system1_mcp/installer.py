"""Universal 1-Click MCP Installer & IDE Configurator for System 1 MCP.

Discovers and safely injects System 1 MCP configuration across:
- Claude Desktop
- Cursor
- Google Antigravity
- Windsurf (Codeium)
- Roo Code & Cline (VS Code)
- Zed Editor
"""

import json
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TargetInfo:
    id: str
    name: str
    config_path: Path
    detected: bool
    configured: bool
    schema_type: str = "standard"  # "standard" (mcpServers) or "zed" (context_servers)


def get_system_paths(system: Optional[str] = None, base_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return platform-specific IDE configuration file locations."""
    sys_name = system or platform.system()
    home = base_dir if base_dir is not None else Path.home()

    if sys_name == "Windows":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        if base_dir is not None:
            appdata = base_dir / "AppData" / "Roaming"

        return {
            "claude": {
                "name": "Claude Desktop",
                "path": appdata / "Claude" / "claude_desktop_config.json",
                "schema": "standard",
            },
            "cursor": {
                "name": "Cursor",
                "path": home / ".cursor" / "mcp.json",
                "schema": "standard",
            },
            "antigravity": {
                "name": "Google Antigravity",
                "path": home / ".gemini" / "config" / "mcp_config.json",
                "schema": "standard",
            },
            "windsurf": {
                "name": "Windsurf (Codeium)",
                "path": home / ".codeium" / "windsurf" / "mcp_config.json",
                "schema": "standard",
            },
            "roo": {
                "name": "Roo Code (VS Code)",
                "path": appdata / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "cline": {
                "name": "Cline (VS Code)",
                "path": appdata / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "zed": {
                "name": "Zed Editor",
                "path": home / ".config" / "zed" / "settings.json",
                "schema": "zed",
            },
        }

    elif sys_name == "Darwin":  # macOS
        app_support = home / "Library" / "Application Support"
        return {
            "claude": {
                "name": "Claude Desktop",
                "path": app_support / "Claude" / "claude_desktop_config.json",
                "schema": "standard",
            },
            "cursor": {
                "name": "Cursor",
                "path": home / ".cursor" / "mcp.json",
                "schema": "standard",
            },
            "antigravity": {
                "name": "Google Antigravity",
                "path": home / ".gemini" / "config" / "mcp_config.json",
                "schema": "standard",
            },
            "windsurf": {
                "name": "Windsurf (Codeium)",
                "path": home / ".codeium" / "windsurf" / "mcp_config.json",
                "schema": "standard",
            },
            "roo": {
                "name": "Roo Code (VS Code)",
                "path": app_support / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "cline": {
                "name": "Cline (VS Code)",
                "path": app_support / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "zed": {
                "name": "Zed Editor",
                "path": home / ".config" / "zed" / "settings.json",
                "schema": "zed",
            },
        }

    else:  # Linux / default
        config_dir = home / ".config"
        return {
            "claude": {
                "name": "Claude Desktop",
                "path": config_dir / "Claude" / "claude_desktop_config.json",
                "schema": "standard",
            },
            "cursor": {
                "name": "Cursor",
                "path": home / ".cursor" / "mcp.json",
                "schema": "standard",
            },
            "antigravity": {
                "name": "Google Antigravity",
                "path": home / ".gemini" / "config" / "mcp_config.json",
                "schema": "standard",
            },
            "windsurf": {
                "name": "Windsurf (Codeium)",
                "path": home / ".codeium" / "windsurf" / "mcp_config.json",
                "schema": "standard",
            },
            "roo": {
                "name": "Roo Code (VS Code)",
                "path": config_dir / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "cline": {
                "name": "Cline (VS Code)",
                "path": config_dir / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                "schema": "standard",
            },
            "zed": {
                "name": "Zed Editor",
                "path": config_dir / "zed" / "settings.json",
                "schema": "zed",
            },
        }


def clean_jsonc(text: str) -> str:
    """Remove comments and trailing commas from JSONC text for safe parsing."""
    no_comments = re.sub(r"//.*?$|/\*.*?\*/", "", text, flags=re.MULTILINE | re.DOTALL)
    no_trailing_commas = re.sub(r",\s*([\]}])", r"\1", no_comments)
    return no_trailing_commas


def inspect_targets(system: Optional[str] = None, base_dir: Optional[Path] = None) -> List[TargetInfo]:
    """Inspect all supported IDE targets on the system and report configuration state."""
    specs = get_system_paths(system, base_dir)
    results = []

    for target_id, info in specs.items():
        p: Path = info["path"]
        detected = p.exists() or p.parent.exists()
        configured = False

        if p.exists():
            try:
                raw_text = p.read_text(encoding="utf-8")
                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError:
                    data = json.loads(clean_jsonc(raw_text))

                if info["schema"] == "zed":
                    servers = data.get("context_servers", {})
                    configured = "system1" in servers or "fastpath" in servers
                else:
                    servers = data.get("mcpServers", {})
                    configured = "system1" in servers or "fastpath" in servers
            except Exception:
                configured = False

        results.append(
            TargetInfo(
                id=target_id,
                name=info["name"],
                config_path=p,
                detected=detected,
                configured=configured,
                schema_type=info["schema"],
            )
        )

    return results


def resolve_python_interpreter() -> str:
    """Resolve Python interpreter path for local module execution."""
    exe = sys.executable
    if exe and not Path(exe).name.lower().startswith("pytest"):
        return str(Path(exe))
    return "python" if os.name == "nt" else "python3"


def build_mcp_entry(
    mode: str = "uvx",
    api_key: Optional[str] = None,
    schema_type: str = "standard",
) -> Dict[str, Any]:
    """Build the MCP server configuration payload."""
    if mode == "uvx":
        entry: Dict[str, Any] = {
            "command": "uvx",
            "args": ["system1-mcp"],
        }
    else:
        entry = {
            "command": resolve_python_interpreter(),
            "args": ["-m", "system1_mcp.server"],
        }

    if api_key:
        entry["env"] = {"TYPESAFE_API_KEY": api_key.strip()}

    return entry


def install_to_target(
    target_id: str,
    mode: str = "uvx",
    api_key: Optional[str] = None,
    system: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Safely inject System 1 MCP configuration into a target IDE config file."""
    specs = get_system_paths(system, base_dir)
    target_norm = target_id.lower().strip()

    aliases = {
        "gemini": "antigravity",
        "agy": "antigravity",
        "codeium": "windsurf",
        "vscode": "roo",
        "vs_code": "roo",
    }
    target_norm = aliases.get(target_norm, target_norm)

    if target_norm not in specs:
        return False, f"Unknown target: {target_id}. Supported: {', '.join(specs.keys())}"

    info = specs[target_norm]
    path: Path = info["path"]
    schema: str = info["schema"]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}

        if path.exists():
            # 1. Preserve original backup if not present
            orig_bak = path.with_suffix(path.suffix + ".orig.bak")
            if not orig_bak.exists():
                shutil.copy2(path, orig_bak)

            # 2. Maintain backup of preceding state
            bak_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak_path)

            raw_text = path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                try:
                    data = json.loads(clean_jsonc(raw_text))
                except Exception as e:
                    return False, f"Existing config at {path} is invalid JSON: {e}"

        entry = build_mcp_entry(mode=mode, api_key=api_key, schema_type=schema)

        if schema == "zed":
            if "context_servers" not in data or not isinstance(data["context_servers"], dict):
                data["context_servers"] = {}
            # Clean legacy fastpath key if present
            data["context_servers"].pop("fastpath", None)
            data["context_servers"]["system1"] = entry
        else:
            if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
                data["mcpServers"] = {}
            # Clean legacy fastpath key if present
            data["mcpServers"].pop("fastpath", None)
            data["mcpServers"]["system1"] = entry

        # Atomic replacement
        tmp_path = path.with_suffix(path.suffix + f".tmp_{os.getpid()}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(path)

        return True, f"Successfully configured {info['name']} ({path})"

    except Exception as e:
        return False, f"Failed to configure {info['name']}: {e}"
