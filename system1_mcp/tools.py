"""Core System 1 reflex tool implementations using TypeSafe Jev models."""

import math
from typing import Any, Dict, List, Optional, Union
from typesafe_sdk import Choice, Noul, NoulCriteria, Score, SystemOneResponse

from system1_mcp.batteries import GUARD_BATTERY
from system1_mcp.client import execute_system_one
from system1_mcp.errors import error_response

# Maximum payload size in characters for single string inputs to prevent memory exhaustion / DoS
MAX_INPUT_LENGTH = 128_000
MAX_OPTIONS_COUNT = 100


def _is_valid_probability(val: Any) -> bool:
    """Check if a value is a valid finite float between 0.0 and 1.0."""
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return 0.0 <= val <= 1.0


CANONICAL_BLAST_LEGEND: Dict[int, str] = {
    0: "Isolated: Read-only check, single temporary file, or no persistent side effects.",
    1: "Workspace: Modifies multiple files, dependencies, or build artifacts within the local project directory.",
    2: "System-wide: Modifies system configuration, global packages, root directories, or OS settings.",
    3: "External: Impacts remote servers, production databases, external APIs, or network resources.",
}


DEFAULT_BLOCK_THRESHOLD: float = 0.80
DEFAULT_REVIEW_THRESHOLD: float = 0.40
DEFAULT_DESTRUCT_BLOCK_THRESHOLD: float = 0.80
DEFAULT_DANGER_BLOCK_THRESHOLD: float = 0.70
DEFAULT_SCOPE_REVIEW_THRESHOLD: float = 0.40


def guard_impl(
    command: str,
    goal: str,
    workspace: Optional[str] = None,
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    destruct_block_threshold: Optional[float] = None,
    danger_block_threshold: Optional[float] = None,
    scope_review_threshold: Optional[float] = None,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Evaluate pre-execution safety of a command against user goal.

    Advisory check returning risk probabilities and a recommended action (pass/review/block).
    """
    if not isinstance(command, str) or not command.strip():
        return error_response("validation_error", "Command must be a non-empty string.")
    if not isinstance(goal, str) or not goal.strip():
        return error_response("validation_error", "Goal must be a non-empty string.")
    if len(command) > MAX_INPUT_LENGTH or len(goal) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Input exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")

    if workspace and isinstance(workspace, str) and len(workspace) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Workspace exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")

    # Validate thresholds defensively against NaN / Inf / out-of-bounds bypasses
    if not _is_valid_probability(block_threshold):
        return error_response("validation_error", "block_threshold must be a valid float between 0.0 and 1.0.")
    if not _is_valid_probability(review_threshold):
        return error_response("validation_error", "review_threshold must be a valid float between 0.0 and 1.0.")
    if review_threshold > block_threshold:
        return error_response("validation_error", "review_threshold cannot be greater than block_threshold.")

    if destruct_block_threshold is not None and not _is_valid_probability(destruct_block_threshold):
        return error_response("validation_error", "destruct_block_threshold must be a valid float between 0.0 and 1.0.")
    if danger_block_threshold is not None and not _is_valid_probability(danger_block_threshold):
        return error_response("validation_error", "danger_block_threshold must be a valid float between 0.0 and 1.0.")
    if scope_review_threshold is not None and not _is_valid_probability(scope_review_threshold):
        return error_response("validation_error", "scope_review_threshold must be a valid float between 0.0 and 1.0.")

    state = {
        "command": command.strip(),
        "goal": goal.strip(),
        "workspace": (workspace or "").strip() if isinstance(workspace, str) else "",
    }

    res = execute_system_one(state=state, questions=GUARD_BATTERY, client=client)
    if isinstance(res, dict) and res.get("error"):
        return res

    if not isinstance(res, SystemOneResponse):
        return error_response("api_error", "Unexpected response type received from reflex model.")

    try:
        p_destructive = float(res.nouls["is_destructive"].noul)
        p_dangerous = float(res.nouls["is_dangerous"].noul)
        p_out_of_scope = float(res.nouls["is_out_of_scope"].noul)
        blast_score = float(res.scores["blast_radius"].score)
        blast_legend = res.scores["blast_radius"].legend
    except (KeyError, AttributeError, ValueError) as e:
        return error_response("api_error", f"Failed to parse guard reflex answers: {e}")

    # Validate and normalize blast_radius legend against canonical labels
    if not isinstance(blast_legend, dict) or not all(k in blast_legend for k in (0, 1, 2, 3)):
        blast_legend = CANONICAL_BLAST_LEGEND

    # Determine effective per-signal thresholds
    effective_destruct_block = (
        destruct_block_threshold
        if destruct_block_threshold is not None
        else (block_threshold if block_threshold != DEFAULT_BLOCK_THRESHOLD else DEFAULT_DESTRUCT_BLOCK_THRESHOLD)
    )
    effective_danger_block = (
        danger_block_threshold
        if danger_block_threshold is not None
        else (block_threshold if block_threshold != DEFAULT_BLOCK_THRESHOLD else DEFAULT_DANGER_BLOCK_THRESHOLD)
    )
    effective_scope_review = (
        scope_review_threshold
        if scope_review_threshold is not None
        else (review_threshold if review_threshold != DEFAULT_REVIEW_THRESHOLD else DEFAULT_SCOPE_REVIEW_THRESHOLD)
    )

    # 1. Block: high danger, or destructive actions extending beyond workspace,
    # or system-wide/external blast radius (>= 2.0) with moderate danger/destruction
    if p_dangerous >= effective_danger_block:
        action = "block"
    elif p_destructive >= effective_destruct_block:
        # If destruction is strictly workspace-scoped (blast_score <= 1.0), with low danger
        # and aligned with goal, escalate to 'review' rather than catastrophic 'block'
        if blast_score <= 1.0 and p_dangerous < review_threshold and p_out_of_scope < review_threshold:
            action = "review"
        else:
            action = "block"
    elif blast_score >= 2.0 and (p_dangerous >= review_threshold or p_destructive >= review_threshold):
        action = "block"
    # 2. Review: moderate destructive or dangerous risks
    elif p_destructive >= review_threshold or p_dangerous >= review_threshold:
        action = "review"
    # 3. Review: out-of-scope with read-only exemption.
    # Benign exploration (cat, ls, git status) carries blast_score < 1.0 and p_destructive <= 0.15,
    # which remains 'pass' even if goal is divergent.
    elif p_out_of_scope >= effective_scope_review and (blast_score >= 1.0 or p_destructive > 0.15):
        action = "review"
    else:
        action = "pass"

    return {
        "action": action,
        "is_destructive": round(p_destructive, 4),
        "is_dangerous": round(p_dangerous, 4),
        "is_out_of_scope": round(p_out_of_scope, 4),
        "blast_radius": {
            "score": round(blast_score, 2),
            "legend": blast_legend,
        },
    }


def judge_impl(
    question: str,
    options: Dict[str, Optional[str]],
    context: Optional[Union[str, Dict[str, Any]]] = None,
    confidence_floor: float = 0.60,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Select the best option from a set of candidates with probability distribution."""
    if not isinstance(question, str) or not question.strip():
        return error_response("validation_error", "Question must be a non-empty string.")
    if len(question) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Question exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if context is not None and isinstance(context, str) and len(context) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Context exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if not isinstance(options, dict) or len(options) < 2:
        return error_response(
            "validation_error",
            "At least 2 options are required to judge a choice.",
        )
    if len(options) > MAX_OPTIONS_COUNT:
        return error_response(
            "validation_error",
            f"Too many options provided (maximum is {MAX_OPTIONS_COUNT}).",
        )

    # Validate option keys are valid non-empty strings
    sanitized_options: Dict[str, Optional[str]] = {}
    for k, v in options.items():
        if not isinstance(k, str) or not k.strip():
            return error_response("validation_error", "All option keys must be non-empty strings.")
        normalized_key = k.strip()
        if normalized_key in sanitized_options:
            return error_response(
                "validation_error",
                "Option keys must be unique after trimming whitespace.",
            )
        v_str = str(v).strip() if v is not None else None
        if v_str is not None and len(v_str) > MAX_INPUT_LENGTH:
            return error_response("validation_error", f"Option description exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
        sanitized_options[normalized_key] = v_str

    if not _is_valid_probability(confidence_floor):
        return error_response("validation_error", "confidence_floor must be a valid float between 0.0 and 1.0.")

    state = {
        "question": question.strip(),
        "context": context if context is not None else "",
    }

    questions = {
        "selection": Choice(
            instructions="Based on `context` and `question`, select the single best option from the available choices.",
            criteria=sanitized_options,
        )
    }

    res = execute_system_one(state=state, questions=questions, client=client)
    if isinstance(res, dict) and res.get("error"):
        return res

    if not isinstance(res, SystemOneResponse):
        return error_response("api_error", "Unexpected response type received from reflex model.")

    try:
        choice_ans = res.choices["selection"]
        confidence = float(choice_ans.confidence)
        probabilities = {k: round(float(v), 4) for k, v in choice_ans.probabilities.items()}
    except (KeyError, AttributeError, ValueError) as e:
        return error_response("api_error", f"Failed to parse judge reflex answers: {e}")

    return {
        "choice": choice_ans.choice,
        "confidence": round(confidence, 4),
        "probabilities": probabilities,
        "is_confident": confidence >= confidence_floor,
    }


def verify_impl(
    statement: str,
    evidence: Union[str, Dict[str, Any]],
    yes_means: Optional[str] = None,
    no_means: Optional[str] = None,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Check whether a condition is true or a task goal has been met.

    Uses strict state isolation to prevent prompt/instruction injection breakouts.
    """
    if not isinstance(statement, str) or not statement.strip():
        return error_response("validation_error", "Statement must be a non-empty string.")
    if evidence is None or (isinstance(evidence, str) and not evidence.strip()):
        return error_response("validation_error", "Evidence cannot be empty.")
    if len(statement) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Statement exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if isinstance(evidence, str) and len(evidence) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Evidence exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if yes_means and isinstance(yes_means, str) and len(yes_means) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"yes_means exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if no_means and isinstance(no_means, str) and len(no_means) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"no_means exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")

    state = {
        "statement": statement.strip(),
        "evidence": evidence,
    }

    criteria = NoulCriteria(
        true=yes_means.strip() if (isinstance(yes_means, str) and yes_means.strip()) else "The claim in `statement` is accurate and directly supported by `evidence`.",
        false=no_means.strip() if (isinstance(no_means, str) and no_means.strip()) else "The claim in `statement` is unproven, inaccurate, or contradicted by `evidence`.",
    )

    # Secure question definition: statement is strictly isolated in `state`
    questions = {
        "verification": Noul(
            instructions="Based on the information provided in `evidence`, is the claim in `statement` true?",
            criteria=criteria,
        )
    }

    res = execute_system_one(state=state, questions=questions, client=client)
    if isinstance(res, dict) and res.get("error"):
        return res

    if not isinstance(res, SystemOneResponse):
        return error_response("api_error", "Unexpected response type received from reflex model.")

    try:
        p = float(res.nouls["verification"].noul)
    except (KeyError, AttributeError, ValueError) as e:
        return error_response("api_error", f"Failed to parse verify reflex answers: {e}")

    if p >= 0.85:
        assessment = "high_confidence_yes"
    elif p >= 0.60:
        assessment = "likely_yes"
    elif p >= 0.40:
        assessment = "uncertain"
    elif p >= 0.15:
        assessment = "likely_no"
    else:
        assessment = "high_confidence_no"

    return {
        "probability": round(p, 4),
        "is_true": p >= 0.50,
        "assessment": assessment,
    }


def score_impl(
    question: str,
    levels: List[str],
    content: Union[str, Dict[str, Any]],
    confidence_floor: float = 0.60,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Rate content along an ordered multi-level scale."""
    if not isinstance(question, str) or not question.strip():
        return error_response("validation_error", "Question must be a non-empty string.")
    if len(question) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Question exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
    if not isinstance(levels, (list, tuple)) or len(levels) < 2:
        return error_response("validation_error", "At least 2 ordered scale levels are required.")
    if len(levels) > MAX_OPTIONS_COUNT:
        return error_response("validation_error", f"Too many levels provided (maximum is {MAX_OPTIONS_COUNT}).")
    if content is None or (isinstance(content, str) and not content.strip()):
        return error_response("validation_error", "Content to evaluate cannot be empty.")
    if isinstance(content, str) and len(content) > MAX_INPUT_LENGTH:
        return error_response("validation_error", f"Content exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")

    sanitized_levels: List[str] = []
    for lvl in levels:
        if not isinstance(lvl, str) or not lvl.strip():
            return error_response("validation_error", "All level descriptions must be non-empty strings.")
        if len(lvl) > MAX_INPUT_LENGTH:
            return error_response("validation_error", f"Level description exceeds maximum allowed length ({MAX_INPUT_LENGTH} chars).")
        sanitized_levels.append(lvl.strip())

    if not _is_valid_probability(confidence_floor):
        return error_response("validation_error", "confidence_floor must be a valid float between 0.0 and 1.0.")

    state = {
        "question": question.strip(),
        "content": content,
    }

    questions = {
        "scoring": Score(
            instructions="Based on `content` and `question`, rate the content along the ordered scale levels.",
            criteria=sanitized_levels,
        )
    }

    res = execute_system_one(state=state, questions=questions, client=client)
    if isinstance(res, dict) and res.get("error"):
        return res

    if not isinstance(res, SystemOneResponse):
        return error_response("api_error", "Unexpected response type received from reflex model.")

    try:
        score_ans = res.scores["scoring"]
        score_val = float(score_ans.score)
        confidence = float(score_ans.confidence)
        legend = score_ans.legend
        probabilities = {str(k): round(float(v), 4) for k, v in score_ans.probabilities.items()}
    except (KeyError, AttributeError, ValueError) as e:
        return error_response("api_error", f"Failed to parse score reflex answers: {e}")

    return {
        "score": round(score_val, 2),
        "confidence": round(confidence, 4),
        "legend": legend,
        "probabilities": probabilities,
        "is_confident": confidence >= confidence_floor,
    }
