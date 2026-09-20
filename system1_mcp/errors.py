"""Structured error responses for System 1 MCP tools.

Provides consistent error shapes so AI agents can predictably handle failures
and fall back to their own System 2 reasoning.
"""


from typing import Any, Dict


def error_response(error_type: str, message: str) -> Dict[str, Any]:
    """Return a uniform structured error response.

    Args:
        error_type: Machine-readable category ("missing_api_key", "api_timeout",
                    "rate_limited", "api_error", "validation_error").
        message: Human/agent-readable explanation.

    Returns:
        Structured dictionary indicating failure with recommended fallback.
    """
    return {
        "error": True,
        "error_type": error_type,
        "message": message,
        "fallback_action": "escalate",
    }
