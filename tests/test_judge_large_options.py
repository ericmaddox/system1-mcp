"""Unit tests for fast_judge warning and margin-based confidence on large option sets."""

from unittest.mock import MagicMock
import pytest
from typesafe_sdk import ChoiceAnswer

from system1_mcp.tools import LARGE_OPTIONS_THRESHOLD, judge_impl
from tests.test_tools import make_mock_system_one_response


def test_judge_large_options_warning_emitted():
    """Verify that sets with >20 options emit accuracy warning and margin confidence."""
    # Generate 25 options
    options = {f"opt_{i}": f"Option description {i}" for i in range(25)}
    assert len(options) > LARGE_OPTIONS_THRESHOLD

    # Mock response where top choice has 0.42 and second choice has 0.10 (margin 0.32 >= 0.30)
    probs = {f"opt_{i}": 0.02 for i in range(25)}
    probs["opt_0"] = 0.42
    probs["opt_1"] = 0.10

    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "selection": ChoiceAnswer(
            choice="opt_0",
            confidence=0.42,
            probabilities=probs,
        )
    })

    result = judge_impl(
        question="Which option is best?",
        options=options,
        confidence_floor=0.60,
        margin_threshold=0.30,
        bypass_cache=True,
        client=mock_client,
    )

    assert result.get("error") is None
    assert result["choice"] == "opt_0"
    assert "warning" in result
    assert "accuracy degrades with >20 options" in result["warning"]
    # Under margin logic: 0.42 - 0.10 = 0.32 >= 0.30 -> confident!
    # (Under absolute 0.60 floor, this would have incorrectly failed)
    assert result["is_confident"] is True


def test_judge_large_options_margin_not_confident():
    """Verify that sets with >20 options are not confident when top choices are too close."""
    options = {f"opt_{i}": f"Option description {i}" for i in range(22)}

    # Top choice 0.28, second choice 0.22 (margin 0.06 < 0.30)
    probs = {f"opt_{i}": 0.02 for i in range(22)}
    probs["opt_0"] = 0.28
    probs["opt_1"] = 0.22

    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "selection": ChoiceAnswer(
            choice="opt_0",
            confidence=0.28,
            probabilities=probs,
        )
    })

    result = judge_impl(
        question="Which option is best?",
        options=options,
        confidence_floor=0.60,
        margin_threshold=0.30,
        bypass_cache=True,
        client=mock_client,
    )

    assert result["choice"] == "opt_0"
    assert "warning" in result
    assert result["is_confident"] is False


def test_judge_small_options_retains_absolute_floor():
    """Verify that sets with <=20 options do not emit warning and use absolute floor."""
    options = {f"opt_{i}": f"Option {i}" for i in range(5)}

    probs = {"opt_0": 0.55, "opt_1": 0.15, "opt_2": 0.10, "opt_3": 0.10, "opt_4": 0.10}

    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "selection": ChoiceAnswer(
            choice="opt_0",
            confidence=0.55,
            probabilities=probs,
        )
    })

    # Floor is 0.60. Margin is 0.55 - 0.15 = 0.40 >= 0.30, but since <= 20, absolute floor applies!
    result = judge_impl(
        question="Which option?",
        options=options,
        confidence_floor=0.60,
        bypass_cache=True,
        client=mock_client,
    )

    assert "warning" not in result
    assert result["is_confident"] is False  # 0.55 < 0.60 floor


def test_judge_margin_threshold_validation():
    """Verify input validation on margin_threshold parameter."""
    res_nan = judge_impl(
        question="Which?",
        options={"a": "1", "b": "2"},
        margin_threshold=float("nan"),
    )
    assert res_nan.get("error") is True
    assert "margin_threshold" in res_nan.get("message", "")

    res_neg = judge_impl(
        question="Which?",
        options={"a": "1", "b": "2"},
        margin_threshold=-0.1,
    )
    assert res_neg.get("error") is True
    assert "margin_threshold" in res_neg.get("message", "")
