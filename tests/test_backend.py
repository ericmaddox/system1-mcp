"""Unit tests for pluggable DecisionBackend, VerdictBackend, and FallbackBackend."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from typesafe_sdk import (
    Choice,
    Noul,
    NoulCriteria,
    Score,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeRateLimitError,
)
from typesafe_sdk._core.response_types import ChoiceAnswer, NoulAnswer, ScoreAnswer, Usage

from system1_mcp.backend import (
    DecisionBackend,
    FallbackBackend,
    TypeSafeBackend,
    VerdictBackend,
    get_backend,
)
from system1_mcp.config import System1Config, resolve_local_model_path
from system1_mcp.errors import error_response
from system1_mcp.tools import guard_impl, judge_impl, score_impl, verify_impl


def make_mock_response(answers: dict) -> SystemOneResponse:
    return SystemOneResponse(
        model="mock-model",
        usage=Usage(prompt_tokens=10, completion_tokens=1, total_tokens=11),
        answers=answers,
    )


def test_typesafe_backend_success():
    mock_client = MagicMock()
    mock_res = make_mock_response({"test_q": NoulAnswer(type="noul", noul=0.88)})
    mock_client.system_one.return_value = mock_res

    backend = TypeSafeBackend(client=mock_client)
    assert backend.name == "typesafe"

    res = backend.execute(state={"key": "val"}, questions={"test_q": Noul(instructions="Test?")})
    assert isinstance(res, SystemOneResponse)
    assert res.nouls["test_q"].noul == 0.88


def test_typesafe_backend_errors():
    # 1. Missing API Key
    mock_client = MagicMock()
    mock_client.system_one.side_effect = ValueError("TYPESAFE_API_KEY is missing or empty")
    backend = TypeSafeBackend(client=mock_client)
    res = backend.execute(state={}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "missing_api_key"

    # 2. Auth error
    mock_client.system_one.side_effect = TypeSafeAuthenticationError(
        status=401,
        body={"error": "Invalid API key"},
        headers=MagicMock(),
    )
    res = backend.execute(state={}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "missing_api_key"


    # 3. Timeout error
    mock_client.system_one.side_effect = TypeSafeAPITimeoutError("Timed out")
    res = backend.execute(state={}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "api_timeout"

    # 4. Connection error
    mock_client.system_one.side_effect = TypeSafeAPIConnectionError("Connection refused")
    res = backend.execute(state={}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "api_error"

    # 5. Rate limit error
    mock_client.system_one.side_effect = TypeSafeRateLimitError(status=429, body={}, headers={})
    res = backend.execute(state={}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "rate_limited"


def test_verdict_backend_availability(tmp_path):
    # Empty dir -> not available
    v_empty = VerdictBackend(model_dir=tmp_path)
    assert v_empty.is_available is False

    # Create dummy files
    (tmp_path / "model.onnx").write_bytes(b"dummy onnx")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")

    v_ready = VerdictBackend(model_dir=tmp_path)
    assert v_ready.is_available is True
    assert v_ready.name == "local"


def test_fallback_backend_primary_success():
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = make_mock_response({"q": NoulAnswer(type="noul", noul=0.9)})

    fallback = MagicMock()
    fallback.name = "local"

    fb = FallbackBackend(primary=primary, fallback=fallback)
    assert fb.name == "typesafe+fallback"

    res = fb.execute(state={}, questions={})
    assert isinstance(res, SystemOneResponse)
    primary.execute.assert_called_once()
    fallback.execute.assert_not_called()


def test_fallback_backend_disables_experimental_fallback_by_default():
    """Verify that FallbackBackend refuses to invoke local model unless allow_experimental_fallback=True."""
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("api_error", "Connection refused")

    fallback = MagicMock()
    fallback.name = "local"
    fallback.execute.return_value = make_mock_response({"q": NoulAnswer(type="noul", noul=0.85)})

    # Default: allow_experimental_fallback=False
    fb = FallbackBackend(primary=primary, fallback=fallback)
    assert fb.allow_experimental_fallback is False

    res = fb.execute(state={"cmd": "ls"}, questions={})
    assert res["error"] is True
    assert res["error_type"] == "api_error"
    primary.execute.assert_called_once()
    fallback.execute.assert_not_called()


def test_fallback_backend_failover_when_experimental_enabled():
    """Verify failover proceeds when allow_experimental_fallback=True."""
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("api_error", "Connection refused")

    fallback = MagicMock()
    fallback.name = "local"
    fallback.execute.return_value = make_mock_response({"q": NoulAnswer(type="noul", noul=0.85)})

    fb = FallbackBackend(primary=primary, fallback=fallback, allow_experimental_fallback=True)
    res = fb.execute(state={"cmd": "ls"}, questions={})

    assert isinstance(res, SystemOneResponse)
    assert res.nouls["q"].noul == 0.85
    primary.execute.assert_called_once()
    fallback.execute.assert_called_once()


def test_fallback_backend_failover_on_missing_key_when_enabled():
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("missing_api_key", "TYPESAFE_API_KEY missing")

    fallback = MagicMock()
    fallback.name = "local"
    fallback.execute.return_value = make_mock_response({"q": NoulAnswer(type="noul", noul=0.82)})

    fb = FallbackBackend(primary=primary, fallback=fallback, allow_experimental_fallback=True)
    res = fb.execute(state={}, questions={})

    assert isinstance(res, SystemOneResponse)
    fallback.execute.assert_called_once()


def test_fallback_backend_failover_on_timeout_when_enabled():
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("api_timeout", "Request timed out")

    fallback = MagicMock()
    fallback.name = "local"
    fallback.execute.return_value = make_mock_response({"q": NoulAnswer(type="noul", noul=0.77)})

    fb = FallbackBackend(primary=primary, fallback=fallback, allow_experimental_fallback=True)
    res = fb.execute(state={}, questions={})

    assert isinstance(res, SystemOneResponse)
    fallback.execute.assert_called_once()


def test_fallback_backend_no_failover_on_validation_error():
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("validation_error", "Invalid inputs")

    fallback = MagicMock()
    fallback.name = "local"

    fb = FallbackBackend(primary=primary, fallback=fallback, allow_experimental_fallback=True)
    res = fb.execute(state={}, questions={})

    assert res["error"] is True
    assert res["error_type"] == "validation_error"
    fallback.execute.assert_not_called()


def test_fallback_backend_both_fail_when_enabled():
    primary = MagicMock()
    primary.name = "typesafe"
    primary.execute.return_value = error_response("api_error", "TypeSafe down")

    fallback = MagicMock()
    fallback.name = "local"
    fallback.execute.return_value = error_response("local_model_error", "ONNX failure")

    fb = FallbackBackend(primary=primary, fallback=fallback, allow_experimental_fallback=True)
    res = fb.execute(state={}, questions={})

    assert res["error"] is True
    primary.execute.assert_called_once()
    fallback.execute.assert_called_once()


def test_backend_aware_cache_key_isolation():
    """Verify switching between backends (typesafe vs local) never serves cross-backend cache."""
    from system1_mcp.cache import get_cache
    cache = get_cache()

    mock_client = MagicMock()
    mock_client.system_one.return_value = SystemOneResponse(
        model="jev-latest",
        usage=Usage(prompt_tokens=10, completion_tokens=1, total_tokens=11),
        answers={
            "is_destructive": NoulAnswer(type="noul", noul=0.01),
            "is_dangerous": NoulAnswer(type="noul", noul=0.02),
            "is_out_of_scope": NoulAnswer(type="noul", noul=0.03),
            "blast_radius": ScoreAnswer(
                type="score",
                score=0.0,
                confidence=0.99,
                probabilities={0: 0.99, 1: 0.01},
                legend={0: "Isolated", 1: "Workspace", 2: "System", 3: "External"},
            ),
        },
    )

    mock_local = MagicMock()
    mock_local.name = "local"
    mock_local.execute.return_value = SystemOneResponse(
        model="verdict-local",
        usage=Usage(prompt_tokens=10, completion_tokens=1, total_tokens=11),
        answers={
            "is_destructive": NoulAnswer(type="noul", noul=0.99),
            "is_dangerous": NoulAnswer(type="noul", noul=0.99),
            "is_out_of_scope": NoulAnswer(type="noul", noul=0.99),
            "blast_radius": ScoreAnswer(
                type="score",
                score=3.0,
                confidence=0.99,
                probabilities={3: 0.99, 0: 0.01},
                legend={0: "Isolated", 1: "Workspace", 2: "System", 3: "External"},
            ),
        },
    )

    # 1. Execute with local backend
    res_local = guard_impl(
        command="git status",
        goal="check status",
        backend=mock_local,
    )
    assert res_local["action"] == "block"
    assert res_local["is_destructive"] == 0.99

    # 2. Execute with typesafe backend (via mock client) for the same inputs
    res_ts = guard_impl(
        command="git status",
        goal="check status",
        client=mock_client,
    )
    # Must NOT return cached local verdict!
    assert res_ts["action"] == "pass"
    assert res_ts["is_destructive"] == 0.01
    mock_client.system_one.assert_called_once()


def test_models_integrity_and_verification(tmp_path):
    """Test SHA-256 verification and model integrity check."""
    from system1_mcp.models import (
        VERDICT_ONNX_SHA256,
        compute_file_sha256,
        verify_model_integrity,
    )

    # Nonexistent file
    ok, msg = verify_model_integrity(tmp_path / "model.onnx")
    assert ok is False
    assert "does not exist" in msg

    # File with wrong hash
    dummy_file = tmp_path / "model.onnx"
    dummy_file.write_bytes(b"corrupted or wrong data")
    ok, msg = verify_model_integrity(dummy_file)
    assert ok is False
    assert "SHA-256 mismatch" in msg

    # File with exact matching hash
    import hashlib
    # Compute sha256
    computed = compute_file_sha256(dummy_file)
    assert computed == hashlib.sha256(b"corrupted or wrong data").hexdigest()


def test_get_backend_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEM1_CONFIG_DIR", str(tmp_path))

    # 1. Explicit typesafe mode
    b_ts = get_backend(name="typesafe")
    assert isinstance(b_ts, TypeSafeBackend)

    # 2. Explicit local mode
    b_local = get_backend(name="local", local_model_path=tmp_path)
    assert isinstance(b_local, VerdictBackend)

    # 3. Auto mode with unavailable local model -> FallbackBackend with fallback=None
    b_auto_none = get_backend(name="auto", local_model_path=tmp_path / "nonexistent")
    assert isinstance(b_auto_none, FallbackBackend)
    assert b_auto_none.fallback is None

    # 4. Auto mode with available local model -> FallbackBackend with fallback
    (tmp_path / "model.onnx").write_bytes(b"dummy")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    b_auto_ready = get_backend(name="auto", local_model_path=tmp_path)
    assert isinstance(b_auto_ready, FallbackBackend)
    assert b_auto_ready.fallback is not None


@pytest.mark.skipif(
    not (Path.home() / "Models" / "verdict" / "model.onnx").is_file(),
    reason="Local Verdict ONNX model not present on test host",
)
def test_live_verdict_backend_guard_block():
    """Verify live Verdict ONNX model correctly evaluates guard safety offline."""
    local_dir = Path.home() / "Models" / "verdict"
    backend = VerdictBackend(model_dir=local_dir)
    assert backend.is_available is True

    # 1. Guard check: rm -rf / must result in 'block'
    res_guard = guard_impl(
        command="rm -rf /",
        goal="clean system",
        bypass_cache=True,
        client=MagicMock(),  # won't be used since we inject backend directly
    )
    # Test directly through backend
    from system1_mcp.batteries import GUARD_BATTERY
    res_raw = backend.execute(
        state={"command": "rm -rf /", "goal": "clean system", "workspace": "/home/user"},
        questions=GUARD_BATTERY,
    )
    assert isinstance(res_raw, SystemOneResponse)
    assert res_raw.nouls["is_destructive"].noul > 0.70
    assert res_raw.nouls["is_dangerous"].noul > 0.65

    # 2. Judge check
    res_judge = backend.execute(
        state={"question": "Which sort algorithm is O(n log n)?", "context": "Sorting algorithms"},
        questions={
            "selection": Choice(
                instructions="Select the best sort algorithm",
                criteria={"opt_a": "Merge sort algorithm", "opt_b": "Sleep sort"},
            )
        },
    )
    assert isinstance(res_judge, SystemOneResponse)
    assert res_judge.choices["selection"].choice == "opt_a"

    # 3. Verify check
    res_verify = backend.execute(
        state={"statement": "File is removed", "evidence": "File deleted: test.txt"},
        questions={
            "verification": Noul(
                instructions="Is statement supported by evidence?",
                criteria=NoulCriteria(true="Yes, file is deleted", false="No, file exists"),
            )
        },
    )
    assert isinstance(res_verify, SystemOneResponse)
    assert res_verify.nouls["verification"].noul > 0.60
