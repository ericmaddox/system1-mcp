"""Golden-set integration tests for System 1 MCP against live TypeSafe Jev API."""

import json
import os
from pathlib import Path
import pytest

from system1_mcp.tools import guard_impl, judge_impl, score_impl, verify_impl

GOLDEN_CASES_PATH = Path(__file__).parent / "golden_cases.json"
HAS_API_KEY = bool(os.environ.get("TYPESAFE_API_KEY", "").strip())


@pytest.mark.integration
@pytest.mark.skipif(not HAS_API_KEY, reason="Requires TYPESAFE_API_KEY environment variable")
def test_golden_guard_cases():
    """Run all 15 golden cases against the live TypeSafe Jev model."""
    with open(GOLDEN_CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    for case in cases[:15]:
        result = guard_impl(
            command=case["command"],
            goal=case["goal"],
            workspace=case["workspace"],
        )

        assert not result.get("error"), f"API error on case {case['id']}: {result}"

        actual_action = result["action"]
        expected = case["expected_action"]

        if isinstance(expected, list):
            assert actual_action in expected, (
                f"Case '{case['id']}' failed: command '{case['command']}' produced '{actual_action}', "
                f"expected one of {expected}. Result: {result}"
            )
        else:
            assert actual_action == expected, (
                f"Case '{case['id']}' failed: command '{case['command']}' produced '{actual_action}', "
                f"expected '{expected}'. Result: {result}"
            )


@pytest.mark.integration
@pytest.mark.skipif(not HAS_API_KEY, reason="Requires TYPESAFE_API_KEY environment variable")
def test_live_judge():
    """Verify live fast_judge behavior."""
    result = judge_impl(
        question="Which file is the primary TypeScript configuration file?",
        options={
            "tsconfig.json": "TypeScript compiler settings",
            "package.json": "NPM package manifest",
            "README.md": "Project documentation",
        },
    )
    assert not result.get("error")
    assert result["choice"] == "tsconfig.json"
    assert result["confidence"] > 0.70


@pytest.mark.integration
@pytest.mark.skipif(not HAS_API_KEY, reason="Requires TYPESAFE_API_KEY environment variable")
def test_live_verify():
    """Verify live fast_verify behavior."""
    result = verify_impl(
        statement="The deployment was successful and healthy",
        evidence="2026-09-18 20:00:00 [INFO] Deployment completed with 0 errors. All 5 pods healthy.",
    )
    assert not result.get("error")
    assert result["is_true"] is True
    assert result["probability"] > 0.85
    assert result["assessment"] == "high_confidence_yes"


@pytest.mark.integration
@pytest.mark.skipif(not HAS_API_KEY, reason="Requires TYPESAFE_API_KEY environment variable")
def test_live_score():
    """Verify live fast_score behavior."""
    result = score_impl(
        question="How critical is this security alert?",
        levels=[
            "Informational / Low: routine scan notice",
            "Medium: deprecated dependency without known exploit",
            "Critical: Remote Code Execution vulnerability actively exploitable",
        ],
        content="CVE-2026-9999: Unauthenticated remote code execution in auth header parser.",
    )
    assert not result.get("error")
    assert result["score"] >= 1.5
    assert result["is_confident"] is True
