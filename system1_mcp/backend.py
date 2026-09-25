"""Pluggable DecisionBackend architecture with local Verdict ONNX fallback.

Supports:
- TypeSafeBackend: live TypeSafe API (Jev models)
- VerdictBackend: offline zero-network local ModernBERT/GLiClass ONNX inference
- FallbackBackend: primary API with automatic seamless fallback to local model
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple, Union

import numpy as np
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
from typesafe_sdk._core.response_types import ChoiceAnswer, NoulAnswer, ScoreAnswer, Usage

from system1_mcp.config import load_config, resolve_api_key, resolve_local_model_path
from system1_mcp.errors import error_response

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 2

# Pinned Verdict model metadata
VERDICT_REPO = "heman10x/rlcd-modernbert-151m"
VERDICT_REVISION = "8af2496eb63c7fa66d7d234e1f62629380030eb4"
VERDICT_ONNX_SHA256 = "4ae01f822538b000fa0e55859d4b3e6b40871d860149397e8784428b2a42ee5e"
INSUFFICIENT_EVIDENCE_ID = "__insufficient_evidence__"
INSUFFICIENT_EVIDENCE_DESC = "insufficient evidence"
PAD_TOKEN_ID = 50283


class DecisionBackend(Protocol):
    """Protocol for System 1 decision backends."""

    @property
    def name(self) -> str:
        """Name of the backend."""
        ...

    def execute(
        self,
        state: Dict[str, Any],
        questions: Mapping[str, Union[Noul, Choice, Score]],
        model: str = DEFAULT_MODEL,
    ) -> Union[SystemOneResponse, Dict[str, Any]]:
        """Execute decision reflex against the backend."""
        ...


class TypeSafeBackend:
    """Live API backend targeting TypeSafe Jev endpoints."""

    def __init__(self, client: Optional[TypeSafeClient] = None):
        self._injected_client = client
        self._client_instance: Optional[TypeSafeClient] = None
        self._client_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "typesafe"

    def get_client(self) -> TypeSafeClient:
        if self._injected_client is not None:
            return self._injected_client
        import system1_mcp.client
        return system1_mcp.client.get_client()


    def execute(
        self,
        state: Dict[str, Any],
        questions: Mapping[str, Union[Noul, Choice, Score]],
        model: str = DEFAULT_MODEL,
    ) -> Union[SystemOneResponse, Dict[str, Any]]:
        from system1_mcp.client import _sanitize_error_message

        try:
            client = self.get_client()
            return client.system_one(state=state, questions=questions, model=model)
        except ValueError as e:
            clean_msg = _sanitize_error_message(str(e))
            if "TYPESAFE_API_KEY" in clean_msg:
                return error_response("missing_api_key", clean_msg)
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


class VerdictBackend:
    """Local offline backend executing Verdict Open-Jev (ModernBERT-151M) via CPU ONNX Runtime.

    Translates typed battery queries (Noul, Choice, Score) into zero-shot classification
    prompts conforming to the GLiClass contract, evaluates them on CPU without PyTorch,
    and returns canonical SystemOneResponse objects.
    """

    def __init__(self, model_dir: Optional[Union[str, Path]] = None):
        self.model_dir: Optional[Path] = resolve_local_model_path(model_dir)
        self._session = None
        self._tokenizer = None
        self._calibrator: Dict[str, Any] = {}
        self._load_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "local"

    @property
    def is_available(self) -> bool:
        """Check if local model files and runtime dependencies are available."""
        if not self.model_dir or not self.model_dir.is_dir():
            return False
        if not (self.model_dir / "model.onnx").is_file() or not (self.model_dir / "tokenizer.json").is_file():
            return False
        try:
            import onnxruntime  # noqa: F401
            import tokenizers  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_loaded(self) -> None:
        """Lazy load ONNX session, tokenizer, and temperature calibrator."""
        if self._session is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._session is not None and self._tokenizer is not None:
                return

            if not self.model_dir or not self.model_dir.is_dir():
                raise FileNotFoundError(
                    f"Verdict local model directory not found. Please place model.onnx and "
                    f"tokenizer.json in ~/.system1/models/verdict or configure local_model_path."
                )

            model_file = self.model_dir / "model.onnx"
            tokenizer_file = self.model_dir / "tokenizer.json"
            calibrator_file = self.model_dir / "calibrator.json"

            if not model_file.is_file():
                raise FileNotFoundError(f"Missing ONNX model file: {model_file}")
            if not tokenizer_file.is_file():
                raise FileNotFoundError(f"Missing tokenizer file: {tokenizer_file}")

            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer
            except ImportError as e:
                raise ImportError(
                    f"Required local backend dependencies missing: {e}. "
                    "Install with: pip install onnxruntime tokenizers numpy"
                )

            # Initialize CPU ONNX session
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = max(1, os.cpu_count() or 1)
            self._session = ort.InferenceSession(
                str(model_file),
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )

            # Initialize Rust tokenizer
            self._tokenizer = Tokenizer.from_file(str(tokenizer_file))

            # Load calibrator temperature if available
            if calibrator_file.is_file():
                try:
                    with open(calibrator_file, "r", encoding="utf-8") as f:
                        self._calibrator = json.load(f)
                except Exception as e:
                    logger.warning("Failed to load Verdict calibrator: %s", e)
                    self._calibrator = {}

    def execute(
        self,
        state: Dict[str, Any],
        questions: Mapping[str, Union[Noul, Choice, Score]],
        model: str = "verdict-openjev-151m",
    ) -> Union[SystemOneResponse, Dict[str, Any]]:
        try:
            self._ensure_loaded()
        except Exception as e:
            return error_response(
                "local_model_unavailable",
                f"Local Verdict backend unavailable: {e}",
            )

        # 1. Format context from state
        if isinstance(state, dict):
            context_lines = []
            for k, v in state.items():
                if v is not None and v != "":
                    context_lines.append(f"{k}: {v}")
            context = "\n".join(context_lines)
        else:
            context = str(state)

        prompts: List[str] = []
        specs: List[Tuple[str, str, List[Any], Dict[str, Any]]] = []

        for q_key, q in questions.items():
            criteria = getattr(q, "criteria", None)
            instructions = getattr(q, "instructions", "") or getattr(q, "question", "")

            # A. Noul proposition query
            if getattr(q, "type", None) == "noul" or (isinstance(criteria, dict) and "true" in criteria):
                true_desc = criteria["true"] if isinstance(criteria, dict) else getattr(criteria, "true", "")
                false_desc = criteria["false"] if isinstance(criteria, dict) else getattr(criteria, "false", "")
                labels = [true_desc, false_desc, INSUFFICIENT_EVIDENCE_DESC]
                ids = ["true", "false", INSUFFICIENT_EVIDENCE_ID]
                label_prefix = "".join(f"<<LABEL>>{lbl}" for lbl in labels)
                text = f"Question: {instructions}\n\nContext:\n{context}" if instructions else context
                prompts.append(f"{label_prefix}<<SEP>>{text}")
                specs.append(("noul", q_key, ids, {}))

            # B. Categorical Choice query
            elif getattr(q, "type", None) == "choice" or (isinstance(criteria, dict) and "true" not in criteria):
                opt_items = list(criteria.items())
                labels = [
                    f"It is {desc}" if desc else f"It is {opt_id}"
                    for opt_id, desc in opt_items
                ] + [INSUFFICIENT_EVIDENCE_DESC]
                ids = [opt_id for opt_id, desc in opt_items] + [INSUFFICIENT_EVIDENCE_ID]
                label_prefix = "".join(f"<<LABEL>>{lbl}" for lbl in labels)
                text = f"Question: {instructions}\n\nContext:\n{context}" if instructions else context
                prompts.append(f"{label_prefix}<<SEP>>{text}")
                specs.append(("choice", q_key, ids, {}))

            # C. Ordinal Score query
            elif getattr(q, "type", None) == "score" or isinstance(criteria, list):
                levels = list(criteria)
                labels = [
                    f"{desc} (Value: {i})" for i, desc in enumerate(levels)
                ] + [INSUFFICIENT_EVIDENCE_DESC]
                ids = [i for i in range(len(levels))] + [INSUFFICIENT_EVIDENCE_ID]
                legend = {i: desc for i, desc in enumerate(levels)}
                label_prefix = "".join(f"<<LABEL>>{lbl}" for lbl in labels)
                text = f"Question: {instructions}\n\nContext:\n{context}" if instructions else context
                prompts.append(f"{label_prefix}<<SEP>>{text}")
                specs.append(("score", q_key, ids, {"legend": legend, "levels": levels}))

        if not prompts:
            return error_response("validation_error", "No valid questions supplied for evaluation.")

        # 2. Tokenize prompt batch
        encodings = [self._tokenizer.encode(p) for p in prompts]
        max_len = max(len(e.ids) for e in encodings)
        total_tokens = sum(len(e.ids) for e in encodings)
        batch_size = len(prompts)

        input_ids = np.zeros((batch_size, max_len), dtype=np.int64)
        attention_mask = np.zeros((batch_size, max_len), dtype=np.int64)

        for i, enc in enumerate(encodings):
            l = len(enc.ids)
            input_ids[i, :l] = enc.ids
            input_ids[i, l:] = PAD_TOKEN_ID
            attention_mask[i, :l] = enc.attention_mask

        # 3. ONNX forward pass
        try:
            logits = self._session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})[0]
        except Exception as e:
            return error_response("local_model_error", f"ONNX inference failure: {e}")

        # 4. Calibration & result normalization
        per_k = self._calibrator.get("per_k", {}) if isinstance(self._calibrator, dict) else {}
        answers: Dict[str, Any] = {}

        for i, (q_type, q_key, ids, meta) in enumerate(specs):
            num_candidates = len(ids)
            cand_logits = logits[i, :num_candidates]

            # Temperature scaling
            temp = float(per_k.get(str(num_candidates), self._calibrator.get("temperature", 1.0)))
            if temp <= 0:
                temp = 1.0
            cal_logits = cand_logits / temp

            # Numerically stable softmax
            exp_logits = np.exp(cal_logits - np.max(cal_logits))
            probs = exp_logits / np.sum(exp_logits)
            prob_map = dict(zip(ids, probs))

            if q_type == "noul":
                sub_mass = prob_map.get("true", 0.0) + prob_map.get("false", 0.0)
                p_true_cond = float(prob_map.get("true", 0.0) / sub_mass) if sub_mass > 0 else 0.5
                answers[q_key] = NoulAnswer(type="noul", noul=p_true_cond)

            elif q_type == "choice":
                sub_opts = [opt_id for opt_id in ids if opt_id != INSUFFICIENT_EVIDENCE_ID]
                sub_mass = sum(prob_map.get(opt_id, 0.0) for opt_id in sub_opts)
                norm_probs = {
                    opt_id: float(prob_map.get(opt_id, 0.0) / sub_mass) if sub_mass > 0 else (1.0 / len(sub_opts))
                    for opt_id in sub_opts
                }
                best_opt = max(norm_probs.keys(), key=lambda k: norm_probs[k])
                answers[q_key] = ChoiceAnswer(
                    type="choice",
                    choice=best_opt,
                    confidence=norm_probs[best_opt],
                    probabilities=norm_probs,
                )

            elif q_type == "score":
                levels = meta["levels"]
                legend = meta["legend"]
                sub_opts = [lvl_idx for lvl_idx in range(len(levels))]
                sub_mass = sum(prob_map.get(lvl_idx, 0.0) for lvl_idx in sub_opts)
                norm_probs = {
                    lvl_idx: float(prob_map.get(lvl_idx, 0.0) / sub_mass) if sub_mass > 0 else (1.0 / len(levels))
                    for lvl_idx in sub_opts
                }
                expected_score = sum(lvl_idx * norm_probs[lvl_idx] for lvl_idx in sub_opts)
                best_level = max(norm_probs.keys(), key=lambda k: norm_probs[k])
                answers[q_key] = ScoreAnswer(
                    type="score",
                    score=float(round(expected_score, 2)),
                    confidence=float(round(norm_probs[best_level], 4)),
                    legend=legend,
                    probabilities={lvl_idx: float(round(norm_probs[lvl_idx], 4)) for lvl_idx in sub_opts},
                )

        return SystemOneResponse(
            model=model,
            usage=Usage(
                prompt_tokens=total_tokens,
                completion_tokens=len(answers),
                total_tokens=total_tokens + len(answers),
            ),
            answers=answers,
        )


class FallbackBackend:
    """Backend chain that routes requests to primary backend and falls back to local model on network/auth failure."""

    def __init__(
        self,
        primary: DecisionBackend,
        fallback: Optional[DecisionBackend] = None,
    ):
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"{self.primary.name}+fallback" if self.fallback else self.primary.name

    def execute(
        self,
        state: Dict[str, Any],
        questions: Mapping[str, Union[Noul, Choice, Score]],
        model: str = DEFAULT_MODEL,
    ) -> Union[SystemOneResponse, Dict[str, Any]]:
        # 1. Attempt primary backend
        res = self.primary.execute(state=state, questions=questions, model=model)

        # 2. Check if primary succeeded
        if isinstance(res, SystemOneResponse):
            return res

        # 3. Check if primary returned a fallback-eligible error
        if isinstance(res, dict) and res.get("error"):
            code = res.get("error_type") or res.get("code")
            # Fallback eligible error codes: missing key, network connection error, or timeout
            if code in ("missing_api_key", "api_error", "api_timeout"):
                if self.fallback is not None:
                    logger.info(
                        "Primary backend (%s) returned '%s'; failing over to fallback backend (%s)",
                        self.primary.name,
                        code,
                        self.fallback.name,
                    )
                    fallback_res = self.fallback.execute(state=state, questions=questions, model="verdict-local")
                    if isinstance(fallback_res, SystemOneResponse):
                        return fallback_res
                    logger.warning(
                        "Fallback backend (%s) also failed: %s",
                        self.fallback.name,
                        fallback_res.get("message") if isinstance(fallback_res, dict) else fallback_res,
                    )

        return res


def get_backend(
    name: Optional[str] = None,
    client: Optional[TypeSafeClient] = None,
    local_model_path: Optional[Union[str, Path]] = None,
) -> DecisionBackend:
    """Factory creating configured decision backend (typesafe, local, or auto).

    Args:
        name: Explicit backend mode ("typesafe", "local", or "auto"). Defaults to config.backend.
        client: Optional injected TypeSafeClient for testing/mocking.
        local_model_path: Optional path to local ONNX model directory.
    """
    config = load_config()
    mode = (name or config.backend or "auto").lower().strip()

    if mode == "typesafe":
        return TypeSafeBackend(client=client)

    if mode == "local":
        return VerdictBackend(model_dir=local_model_path or config.local_model_path)

    # auto mode: TypeSafe primary with Verdict local fallback if available
    primary = TypeSafeBackend(client=client)
    local_backend = VerdictBackend(model_dir=local_model_path or config.local_model_path)
    fallback = local_backend if local_backend.is_available else None

    return FallbackBackend(primary=primary, fallback=fallback)
