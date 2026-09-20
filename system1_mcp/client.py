"""TypeSafe API client wrapper with lazy initialization and structured error handling."""

import os
import re
import threading
from typing import Any, Dict, Mapping, Optional, Union
from dotenv import load_dotenv

load_dotenv()
from typesafe_sdk import (
    Choice,
    Noul,
    RetryPolicy,
    Score,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeRateLimitError,
)

from system1_mcp.config import load_config, resolve_api_key
from system1_mcp.errors import error_response

_CLIENT_INSTANCE: Optional[TypeSafeClient] = None
_CLIENT_LOCK = threading.Lock()
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 2

# Regex patterns for sanitizing potential secrets from error messages
_SECRET_REDACT_PATTERNS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"ts_[a-zA-Z0-9_\-]{8,}", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(key=)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(api[-_]?key\s*[:=]\s*['\"]?)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE), r"\1[REDACTED]"),
]


def _sanitize_error_message(message: str) -> str:
    """Redact sensitive API keys or auth headers from error output."""
    if not isinstance(message, str):
        message = str(message)
    sanitized = message

    # Sanitize active key from env or config file
    active_key, _ = resolve_api_key()
    if active_key and len(active_key) >= 6:
        sanitized = sanitized.replace(active_key, "[REDACTED]")

    env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env_key and len(env_key) >= 6:
        sanitized = sanitized.replace(env_key, "[REDACTED]")

    for pattern, replacement in _SECRET_REDACT_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def get_client() -> TypeSafeClient:
    """Get or create the singleton TypeSafeClient instance.

    Uses tiered key resolution: Environment -> ~/.system1/config.json -> .env
    Thread-safe via _CLIENT_LOCK.
    """
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is None:
        with _CLIENT_LOCK:
            if _CLIENT_INSTANCE is None:
                api_key, source = resolve_api_key()
                if not api_key:
                    raise ValueError(
                        "TYPESAFE_API_KEY is missing or empty. "
                        "Configure it via `system1-mcp install`, set ~/.system1/config.json, "
                        "or set TYPESAFE_API_KEY environment variable."
                    )

                config = load_config()
                base_url = config.endpoint or os.environ.get("TYPESAFE_ENDPOINT") or None
                timeout = config.timeout_seconds or DEFAULT_TIMEOUT_SECONDS

                retry_policy = RetryPolicy(
                    max_retries=DEFAULT_MAX_RETRIES,
                    backoff_initial=0.2,
                    backoff_max=1.0,
                    timeout=timeout,
                )

                _CLIENT_INSTANCE = TypeSafeClient(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    retry=retry_policy,
                )
    return _CLIENT_INSTANCE


def set_client(client: Optional[TypeSafeClient]) -> None:
    """Override client instance (primarily for testing and mock injection)."""
    global _CLIENT_INSTANCE
    _CLIENT_INSTANCE = client


def execute_system_one(
    state: Dict[str, Any],
    questions: Mapping[str, Union[Noul, Choice, Score]],
    model: str = DEFAULT_MODEL,
    client: Optional[TypeSafeClient] = None,
) -> Union[SystemOneResponse, Dict[str, Any]]:
    """Execute a System One call against Jev with safe error catching.

    Returns:
        SystemOneResponse on success, or a structured error dict on failure.
    """
    try:
        active_client = client or get_client()
        response = active_client.system_one(
            state=state,
            questions=questions,
            model=model,
        )
        return response
    except ValueError as e:
        clean_msg = _sanitize_error_message(str(e))
        if "TYPESAFE_API_KEY" in clean_msg:
            return error_response(
                "missing_api_key",
                clean_msg,
            )
        return error_response("validation_error", clean_msg)
    except TypeSafeAuthenticationError as e:
        return error_response(
            "missing_api_key",
            f"Authentication failed: {_sanitize_error_message(str(e))}",
        )
    except TypeSafeAPITimeoutError as e:
        return error_response(
            "api_timeout",
            f"TypeSafe API request timed out after {DEFAULT_TIMEOUT_SECONDS}s: {_sanitize_error_message(str(e))}",
        )
    except TypeSafeRateLimitError as e:
        return error_response(
            "rate_limited",
            f"TypeSafe API rate limit exceeded: {_sanitize_error_message(str(e))}",
        )
    except TypeSafeAPIConnectionError as e:
        return error_response(
            "api_error",
            f"Connection error reaching TypeSafe API: {_sanitize_error_message(str(e))}",
        )
    except TypeSafeAPIError as e:
        return error_response(
            "api_error",
            f"TypeSafe API error: {_sanitize_error_message(str(e))}",
        )
    except Exception as e:
        return error_response(
            "api_error",
            f"Unexpected error executing System One reflex: {_sanitize_error_message(str(e))}",
        )
