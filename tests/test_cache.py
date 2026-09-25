"""Unit tests for response caching, TTL expiration, and cross-process statistics."""

import hashlib
import json
import time
from unittest.mock import MagicMock
import pytest
from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer

from system1_mcp.cache import (
    ResponseCache,
    clear_cache,
    get_cache,
    get_cache_stats,
    reset_cache_stats,
    set_cache,
)
from system1_mcp.tools import guard_impl, judge_impl, score_impl, verify_impl
from tests.test_tools import make_mock_system_one_response


def _mock_score_answer(score: float = 0.1, legend=None) -> ScoreAnswer:
    return ScoreAnswer(
        score=score,
        confidence=0.90,
        legend=legend or {0: "Isolated", 1: "Workspace", 2: "System", 3: "External"},
        probabilities={0: 0.8, 1: 0.1, 2: 0.05, 3: 0.05},
    )


@pytest.fixture(autouse=True)
def clean_cache_state():
    """Reset global cache and persistent stats before each test."""
    clear_cache()
    reset_cache_stats()
    yield
    clear_cache()
    reset_cache_stats()


def test_cache_key_sha256_canonical_format():
    """Verify cache key format matches canonical JSON SHA-256 specification."""
    cache = ResponseCache()
    tool = "fast_guard"
    inputs = {"command": "git status", "goal": "check repo", "workspace": "/repo"}
    model = "jev-latest"
    thresholds = {"block_threshold": 0.8, "review_threshold": 0.4}

    # Expected key according to canonical specification (including backend)
    expected_payload = {
        "backend": "typesafe",
        "inputs": inputs,
        "model": model,
        "thresholds": thresholds,
        "tool": tool,
    }
    expected_str = json.dumps(expected_payload, sort_keys=True)
    expected_hash = hashlib.sha256(expected_str.encode("utf-8")).hexdigest()

    computed_key = cache.compute_key(tool=tool, inputs=inputs, model=model, thresholds=thresholds)
    assert computed_key == expected_hash
    assert len(computed_key) == 64


def test_cache_handles_nested_dict_inputs_without_unhashable_error():
    """Ensure dict inputs (judge options, verify evidence) do not raise unhashable dict errors."""
    cache = ResponseCache()
    nested_inputs = {
        "options": {"opt_a": "First candidate", "opt_b": "Second candidate"},
        "nested_evidence": {"logs": ["line 1", "line 2"], "exit_code": 0},
    }
    # Must not raise TypeError: unhashable type: 'dict'
    key = cache.compute_key(
        tool="fast_judge",
        inputs=nested_inputs,
        model="jev-latest",
        thresholds={"confidence_floor": 0.60},
    )
    assert isinstance(key, str)
    assert len(key) == 64


def test_guard_impl_cache_hit_and_miss():
    """Verify first guard_impl call is a cache miss and second is an instant cache hit."""
    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "is_destructive": NoulAnswer(noul=0.02),
        "is_dangerous": NoulAnswer(noul=0.01),
        "is_out_of_scope": NoulAnswer(noul=0.03),
        "blast_radius": _mock_score_answer(score=0.1),
    })

    # Call 1: Miss
    res1 = guard_impl(command="git status", goal="check repo", client=mock_client)
    assert res1["action"] == "pass"
    assert res1["cache_hit"] is False
    assert mock_client.system_one.call_count == 1

    # Call 2: Hit
    res2 = guard_impl(command="git status", goal="check repo", client=mock_client)
    assert res2["action"] == "pass"
    assert res2["cache_hit"] is True
    # mock_client must NOT have been called again
    assert mock_client.system_one.call_count == 1


def test_cache_miss_on_different_thresholds():
    """Verify that changing thresholds creates a different cache key (no stale hit)."""
    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "is_destructive": NoulAnswer(noul=0.75),
        "is_dangerous": NoulAnswer(noul=0.05),
        "is_out_of_scope": NoulAnswer(noul=0.10),
        "blast_radius": _mock_score_answer(score=1.5),
    })

    # Call with standard block_threshold 0.80 -> action is review
    res1 = guard_impl(command="npm prune", goal="clean dependencies", block_threshold=0.80, client=mock_client)
    assert res1["action"] == "review"
    assert res1["cache_hit"] is False
    assert mock_client.system_one.call_count == 1

    # Call with stricter block_threshold 0.70 -> should be cache MISS and evaluate to block
    res2 = guard_impl(command="npm prune", goal="clean dependencies", block_threshold=0.70, client=mock_client)
    assert res2["action"] == "block"
    assert res2["cache_hit"] is False
    assert mock_client.system_one.call_count == 2


def test_judge_and_verify_and_score_cache_hits():
    """Verify cache hits on judge_impl, verify_impl, and score_impl."""
    mock_client = MagicMock()
    mock_client.system_one.side_effect = [
        make_mock_system_one_response({
            "selection": ChoiceAnswer(choice="a.py", confidence=0.88, probabilities={"a.py": 0.88, "b.py": 0.12})
        }),
        make_mock_system_one_response({
            "verification": NoulAnswer(noul=0.95)
        }),
        make_mock_system_one_response({
            "scoring": ScoreAnswer(score=2.5, confidence=0.85, legend={0: "Low", 1: "Med", 2: "High", 3: "Crit"}, probabilities={0: 0.1, 1: 0.2, 2: 0.6, 3: 0.1})
        }),
    ]

    # Judge
    j1 = judge_impl("Which file?", {"a.py": None, "b.py": None}, client=mock_client)
    assert j1["cache_hit"] is False
    j2 = judge_impl("Which file?", {"a.py": None, "b.py": None}, client=mock_client)
    assert j2["cache_hit"] is True

    # Verify
    v1 = verify_impl("Tests passed", {"exit_code": 0}, client=mock_client)
    assert v1["cache_hit"] is False
    v2 = verify_impl("Tests passed", {"exit_code": 0}, client=mock_client)
    assert v2["cache_hit"] is True

    # Score
    s1 = score_impl("Severity?", ["Low", "Med", "High", "Crit"], "System down", client=mock_client)
    assert s1["cache_hit"] is False
    s2 = score_impl("Severity?", ["Low", "Med", "High", "Crit"], "System down", client=mock_client)
    assert s2["cache_hit"] is True

    # Exactly 3 network calls were made across the 6 invocations
    assert mock_client.system_one.call_count == 3


def test_cache_ttl_expiration():
    """Verify cache entries expire and re-query after TTL elapses."""
    custom_cache = ResponseCache(ttl_seconds=0.05)
    set_cache(custom_cache)

    mock_client = MagicMock()
    mock_client.system_one.return_value = make_mock_system_one_response({
        "is_destructive": NoulAnswer(noul=0.01),
        "is_dangerous": NoulAnswer(noul=0.01),
        "is_out_of_scope": NoulAnswer(noul=0.01),
        "blast_radius": _mock_score_answer(score=0.0),
    })

    # Call 1
    r1 = guard_impl(command="ls", goal="list", client=mock_client)
    assert r1["cache_hit"] is False
    assert mock_client.system_one.call_count == 1

    # Immediate Call 2 (before 0.05s) -> Hit
    r2 = guard_impl(command="ls", goal="list", client=mock_client)
    assert r2["cache_hit"] is True
    assert mock_client.system_one.call_count == 1

    # Wait for TTL to expire
    time.sleep(0.07)

    # Call 3 (after 0.05s) -> Miss and re-query
    r3 = guard_impl(command="ls", goal="list", client=mock_client)
    assert r3["cache_hit"] is False
    assert mock_client.system_one.call_count == 2


def test_persistent_stats_file_for_doctor():
    """Verify rolling hits and misses persist to cache_stats.json for doctor."""
    cache = get_cache()
    key = cache.compute_key("test", {"x": 1}, "jev-latest", {})

    # Initial state
    stats0 = get_cache_stats()
    assert stats0.get("hits", 0) == 0

    # Miss
    cache.get(key)
    cache.flush_stats()
    stats1 = get_cache_stats()
    assert stats1["misses"] >= 1

    # Populate and hit
    cache.set(key, {"action": "pass"})
    cache.get(key)
    cache.flush_stats()
    stats2 = get_cache_stats()
    assert stats2["hits"] >= 1


def test_cache_bounded_eviction():
    """Verify LRU/oldest eviction when cache reaches max capacity."""
    bounded_cache = ResponseCache(ttl_seconds=60.0, maxsize=2)
    bounded_cache.set("k1", {"val": 1})
    bounded_cache.set("k2", {"val": 2})

    # Store has 2 items
    assert bounded_cache.get("k1") is not None
    assert bounded_cache.get("k2") is not None

    # Adding 3rd item should evict oldest (k1 was accessed before k2, so k1 is older)
    bounded_cache.set("k3", {"val": 3})
    assert bounded_cache.get("k3") is not None
    assert bounded_cache.get("k1") is None  # evicted!
    assert bounded_cache.get("k2") is not None
