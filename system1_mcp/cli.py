"""Unified Command Line Interface for System 1 MCP.

Supports:
- Zero-arg / serve: Default stdio MCP server execution for IDEs
- install: 1-click IDE configuration (Claude, Cursor, Antigravity, Windsurf, Zed, Roo)
- doctor: Diagnostic health check, API key verification, and live latency benchmark
- config: View and manage ~/.system1/config.json
"""

import argparse
import getpass
import os
import sys
import time
from typing import List, Optional

from system1_mcp import __version__
from system1_mcp.config import (
    System1Config,
    get_config_path,
    load_config,
    mask_api_key,
    resolve_api_key,
    save_config,
)
from system1_mcp.installer import inspect_targets, install_to_target


def _get_icons():
    # Safe symbols for terminals with or without UTF-8 encoding
    enc = (sys.stderr.encoding or "").lower()
    is_utf = "utf" in enc or os.name != "nt"
    return {
        "bolt": "⚡" if is_utf else ">>",
        "ok": "✅" if is_utf else "[OK]",
        "fail": "❌" if is_utf else "[FAIL]",
    }


def run_server() -> None:
    """Launch the MCP server on stdio transport."""
    from system1_mcp.server import main as server_main
    server_main()


def cmd_install(args: argparse.Namespace) -> int:
    """Handle the 'install' subcommand."""
    icons = _get_icons()
    print(f"\n{icons['bolt']} System 1 MCP Installer (v{__version__})\n", file=sys.stderr)

    api_key = (args.api_key or "").strip()
    existing_key, source = resolve_api_key()

    if not api_key:
        if existing_key:
            print(f"Found existing API key from {source}: {mask_api_key(existing_key)}", file=sys.stderr)
            use_existing = input("Use this key? [Y/n]: ").strip().lower() if sys.stdin.isatty() else "y"
            if use_existing in ("", "y", "yes"):
                api_key = existing_key

        if not api_key:
            if sys.stdin.isatty():
                prompt_key = getpass.getpass("Enter your TypeSafe API Key (from https://console.typesafe.ai): ").strip()
                if prompt_key:
                    api_key = prompt_key
            else:
                print("Notice: No API key provided. Run with --api-key <KEY> or configure ~/.system1/config.json", file=sys.stderr)

    # Save to global config if a key is provided
    if api_key:
        cfg = load_config()
        cfg.api_key = api_key
        saved_path = save_config(cfg)
        print(f"{icons['ok']} Saved API key to {saved_path}", file=sys.stderr)

    # Inspect IDEs
    targets = inspect_targets()
    target_filter = [t.strip().lower() for t in args.targets.split(",")] if args.targets else None

    configured_count = 0
    print("\nScanning development environments...", file=sys.stderr)

    for target in targets:
        if target_filter and target.id not in target_filter and "all" not in target_filter:
            continue

        if not target.detected and not target_filter:
            continue

        success, msg = install_to_target(
            target_id=target.id,
            mode=args.mode,
            api_key=api_key if args.inject_env else None,
        )

        status_icon = icons["ok"] if success else icons["fail"]
        print(f"  {status_icon} {target.name}: {msg}", file=sys.stderr)
        if success:
            configured_count += 1

    print(f"\nDone! Configured {configured_count} environment(s).", file=sys.stderr)

    if getattr(args, "with_local_model", False):
        print(f"\n{icons['bolt']} Downloading pinned Verdict local model weights...", file=sys.stderr)
        from system1_mcp.models import download_verdict_model
        try:
            download_verdict_model(verbose=True)
            print(f"{icons['ok']} Local Verdict model installed successfully.", file=sys.stderr)
        except Exception as e:
            print(f"{icons['fail']} Failed to download local model: {e}", file=sys.stderr)

    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Handle the 'doctor' diagnostic subcommand."""
    icons = _get_icons()
    print(f"\n{icons['bolt']} System 1 MCP Diagnostics (v{__version__})\n", file=sys.stderr)

    # 1. Environment info
    print("Environment:", file=sys.stderr)
    print(f"  Python:        {sys.version.split()[0]} ({sys.executable})", file=sys.stderr)
    print(f"  Platform:      {sys.platform}", file=sys.stderr)
    print(f"  Config File:   {get_config_path()} ({'exists' if get_config_path().exists() else 'not found'})", file=sys.stderr)

    # 2. Key Resolution
    key, source = resolve_api_key()
    print("\nAPI Key Status:", file=sys.stderr)
    if key:
        print(f"  Status:        {icons['ok']} Configured", file=sys.stderr)
        print(f"  Resolved Key:  {mask_api_key(key)}", file=sys.stderr)
        print(f"  Source Origin: {source}", file=sys.stderr)
    else:
        print(f"  Status:        {icons['fail']} Missing TYPESAFE_API_KEY", file=sys.stderr)
        print("  Remediation:   Run `system1-mcp install` or set TYPESAFE_API_KEY in environment", file=sys.stderr)

    # 3. Live TypeSafe API Health Ping
    if key:
        print("\nLive TypeSafe Jev Connectivity:", file=sys.stderr)
        try:
            from typesafe_sdk import Noul, NoulCriteria, TypeSafeClient
            client = TypeSafeClient(api_key=key, timeout=5.0)

            t0 = time.perf_counter()
            res = client.system_one(
                state={"text": "System 1 ping check"},
                questions={
                    "ping": Noul(
                        instructions="Is this a valid test statement?",
                        criteria=NoulCriteria(true="Yes", false="No"),
                    )
                },
                model="jev-latest",
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            noul_val = float(res.nouls["ping"].noul)
            print(f"  Status:        {icons['ok']} Connected to api.typesafe.ai", file=sys.stderr)
            print(f"  Model:         {res.model}", file=sys.stderr)
            print(f"  Roundtrip:     {icons['bolt']} {elapsed_ms:.1f}ms", file=sys.stderr)
            print(f"  Calibration:   P(valid) = {noul_val:.2f}", file=sys.stderr)
        except Exception as e:
            print(f"  Status:        {icons['fail']} Connection failed: {e}", file=sys.stderr)

    # 4. Decision Backend & Local Model Status
    from system1_mcp.backend import VerdictBackend
    from system1_mcp.config import resolve_local_model_path

    cfg = load_config()
    print("\nDecision Backend Status:", file=sys.stderr)
    print(f"  Configured Mode:       {cfg.backend}", file=sys.stderr)
    print(f"  Experimental Fallback: {'Enabled' if cfg.allow_experimental_fallback else 'Disabled (safe default)'}", file=sys.stderr)

    local_path = resolve_local_model_path(cfg.local_model_path)
    if local_path:
        local_backend = VerdictBackend(model_dir=local_path)
        avail = local_backend.is_available
        status_str = f"{icons['ok']} Ready (CPU ONNX)" if avail else f"{icons['fail']} Missing dependencies (onnxruntime/tokenizers)"
        print(f"  Local Model:           {status_str}", file=sys.stderr)
        print(f"  Model Path:            {local_path}", file=sys.stderr)
    else:
        print(f"  Local Model:           Not installed (run 'system1-mcp models download' to install)", file=sys.stderr)

    # 5. Target IDE Detection
    print("\nDetected IDE Configurations:", file=sys.stderr)
    targets = inspect_targets()
    for t in targets:
        detect_str = "Detected" if t.detected else "Not Installed"
        config_str = f"Configured {icons['ok']}" if t.configured else "Not Configured"
        print(f"  {t.name:20} [{detect_str:13}] -> {config_str}", file=sys.stderr)

    # 6. Response Cache Status
    from system1_mcp.cache import get_cache_stats
    cache_stats = get_cache_stats()
    hits = int(cache_stats.get("hits", 0))
    misses = int(cache_stats.get("misses", 0))
    total = hits + misses
    hit_ratio = (hits / total * 100.0) if total > 0 else 0.0

    print("\nResponse Cache Status:", file=sys.stderr)
    print(f"  Hits:          {hits}", file=sys.stderr)
    print(f"  Misses:        {misses}", file=sys.stderr)
    print(f"  Hit Ratio:     {hit_ratio:.1f}%", file=sys.stderr)
    print(f"  Cache TTL:     {cfg.cache_ttl_seconds:.0f}s", file=sys.stderr)

    print("", file=sys.stderr)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Handle the 'config' subcommand."""
    action = args.action

    if action == "path":
        print(str(get_config_path()))
        return 0

    if action == "set-key":
        if not args.key:
            print("Error: Specify key via `system1-mcp config set-key <KEY>`", file=sys.stderr)
            return 1
        cfg = load_config()
        cfg.api_key = args.key.strip()
        p = save_config(cfg)
        print(f"Saved key to {p}", file=sys.stderr)
        return 0

    if action == "set-backend":
        if not args.key:
            print("Error: Specify backend via `system1-mcp config set-backend <typesafe|local|auto>`", file=sys.stderr)
            return 1
        val = args.key.strip().lower()
        if val not in ("typesafe", "local", "auto"):
            print("Error: Backend must be one of: 'typesafe', 'local', 'auto'", file=sys.stderr)
            return 1
        cfg = load_config()
        cfg.backend = val
        p = save_config(cfg)
        print(f"Saved backend mode '{val}' to {p}", file=sys.stderr)
        return 0

    if action == "set-model-path":
        if not args.key:
            print("Error: Specify path via `system1-mcp config set-model-path <PATH>`", file=sys.stderr)
            return 1
        p_val = args.key.strip()
        cfg = load_config()
        cfg.local_model_path = p_val
        p = save_config(cfg)
        print(f"Saved local_model_path '{p_val}' to {p}", file=sys.stderr)
        return 0

    if action == "set-experimental-fallback":
        if not args.key:
            print("Error: Specify true/false via `system1-mcp config set-experimental-fallback <true|false>`", file=sys.stderr)
            return 1
        val = args.key.strip().lower() in ("true", "1", "yes")
        cfg = load_config()
        cfg.allow_experimental_fallback = val
        p = save_config(cfg)
        print(f"Saved allow_experimental_fallback={val} to {p}", file=sys.stderr)
        return 0

    # Default: show config
    cfg = load_config()
    key, src = resolve_api_key()
    print("System 1 Configuration:")
    print(f"  Config path:           {get_config_path()}")
    print(f"  Active API Key:        {mask_api_key(key)} (from {src})")
    print(f"  Backend Mode:          {cfg.backend}")
    print(f"  Experimental Fallback: {cfg.allow_experimental_fallback}")
    print(f"  Local Model Path:      {cfg.local_model_path or '<default search>'}")
    print(f"  Default Model:         {cfg.default_model}")
    print(f"  Timeout (s):           {cfg.timeout_seconds}")
    print(f"  Cache TTL (s):         {cfg.cache_ttl_seconds}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Handle the 'models' subcommand."""
    action = getattr(args, "models_action", None)
    if action == "download":
        from system1_mcp.models import download_verdict_model
        try:
            download_verdict_model(
                target_dir=getattr(args, "target_dir", None),
                force=getattr(args, "force", False),
                verbose=True,
            )
            return 0
        except Exception as e:
            print(f"Error downloading model: {e}", file=sys.stderr)
            return 1

    print("Usage: system1-mcp models download [--force] [--target-dir <DIR>]", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point with zero-argument MCP server default."""
    raw_args = sys.argv[1:] if argv is None else argv

    # Zero arguments or explicitly 'serve' / 'run' -> run the stdio MCP server
    if not raw_args or raw_args[0] in ("serve", "run"):
        run_server()
        return 0

    parser = argparse.ArgumentParser(
        prog="system1-mcp",
        description="System 1 MCP - Jev-powered System 1 reflex engine for AI agents",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Serve command
    subparsers.add_parser("serve", help="Run the stdio MCP server (default when no args provided)")
    subparsers.add_parser("run", help="Alias for 'serve'")

    # Install command
    install_parser = subparsers.add_parser("install", help="1-Click IDE configurator for Claude, Cursor, Antigravity, etc.")
    install_parser.add_argument("--api-key", help="TypeSafe API key to store and configure")
    install_parser.add_argument("--targets", help="Comma-separated target IDEs (e.g. 'claude,cursor,antigravity')")
    install_parser.add_argument("--mode", choices=["uvx", "python"], default="uvx", help="Invocation mode in IDE config (default: uvx)")
    install_parser.add_argument("--inject-env", action="store_true", help="Explicitly inject API key into the IDE config's 'env' block")
    install_parser.add_argument("--with-local-model", action="store_true", help="Also download pinned local Verdict model weights (~151M)")

    # Models command
    models_parser = subparsers.add_parser("models", help="Manage local decision models")
    models_sub = models_parser.add_subparsers(dest="models_action", help="Model actions")
    download_parser = models_sub.add_parser("download", help="Download pinned Verdict local model artifacts (~151M)")
    download_parser.add_argument("--force", action="store_true", help="Force re-download even if files exist and verify")
    download_parser.add_argument("--target-dir", help="Custom destination directory (defaults to ~/.system1/models/verdict)")

    # Doctor command
    subparsers.add_parser("doctor", help="Run diagnostic health checks and latency benchmark")

    # Config command
    config_parser = subparsers.add_parser("config", help="Manage ~/.system1/config.json")
    config_parser.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "path", "set-key", "set-backend", "set-model-path", "set-experimental-fallback"],
        help="Config action",
    )
    config_parser.add_argument("key", nargs="?", help="Value (for set-key, set-backend, set-model-path, set-experimental-fallback)")

    parsed = parser.parse_args(raw_args)

    if parsed.subcommand in ("serve", "run") or not parsed.subcommand:
        run_server()
        return 0
    elif parsed.subcommand == "install":
        return cmd_install(parsed)
    elif parsed.subcommand == "models":
        return cmd_models(parsed)
    elif parsed.subcommand == "doctor":
        return cmd_doctor(parsed)
    elif parsed.subcommand == "config":
        return cmd_config(parsed)

    return 0


if __name__ == "__main__":
    sys.exit(main())
