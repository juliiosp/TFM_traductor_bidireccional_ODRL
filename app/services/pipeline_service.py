"""LangChain orchestration of the ODRL translation flows.

Both flows (natural language -> ODRL and ODRL -> natural language) are assembled
as LangChain Expression Language (LCEL) pipelines. Every stage is a
``RunnableLambda`` and the control flow between stages -- deciding whether a
policy must be repaired, or whether an explanation must be produced -- is
expressed with ``RunnableBranch`` rather than with imperative branching outside
the pipeline. Each LLM interaction is delegated to the chains defined in
``inference_service`` (``prompt -> model -> parser``), so LangChain acts as the
composition and orchestration layer of the application.
"""

from copy import deepcopy
from functools import lru_cache
import json
from time import perf_counter
from typing import Any, TypedDict

from langchain_core.runnables import (
    Runnable,
    RunnableBranch,
    RunnableLambda,
    RunnablePassthrough,
)

from app.config import settings
from app.schemas import RepairResult, ValidationResult
from app.services.inference_service import (
    build_explanation_chain,
    build_generation_chain,
    build_repair_chain,
    llm_config,
)
from app.services.normalization_service import (
    normalize_odrl_policy,
    repair_policy_deterministically,
)
from app.validator import validate_policy


# LCEL chains are created lazily. This lets the API start and answer health or
# validation requests even when the model credential has not been configured.
@lru_cache(maxsize=1)
def _generation_chain() -> Runnable:
    return build_generation_chain()


@lru_cache(maxsize=1)
def _repair_chain() -> Runnable:
    return build_repair_chain()


@lru_cache(maxsize=1)
def _explanation_chain() -> Runnable:
    return build_explanation_chain()


# Token budgets per task (previously hard-coded at each call site).
_GENERATION_MAX_TOKENS = 800
_REPAIR_MAX_TOKENS = 1500
_EXPLANATION_MAX_TOKENS = 800


class ODRLPipelineState(TypedDict, total=False):
    text: str
    model: str | None
    repair_enabled: bool

    llm_calls: int
    duration_seconds: float

    raw_model_response: str
    cleaned_model_response: str
    raw_policy: dict[str, Any]
    normalized_policy: dict[str, Any]
    policy: dict[str, Any]

    validation_result: ValidationResult
    validation_history: list[ValidationResult]

    repair_attempted: bool
    repaired: bool
    repair_attempts: int
    repair_changes: list[str]
    repair_stopped_reason: str | None
    original_policy_before_repair: dict[str, Any] | None


class ODRLToNLPipelineState(TypedDict, total=False):
    policy_text: str
    model: str | None

    llm_calls: int
    duration_seconds: float

    policy: dict[str, Any] | None
    parse_error: str | None
    validation_result: ValidationResult | None
    explanation: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validation_errors(result: ValidationResult) -> list[str]:
    return [
        f"{issue.path}: {issue.message}" if issue.path else issue.message
        for issue in result.issues
    ]


def _policy_signature(policy: dict[str, Any]) -> str:
    return json.dumps(policy, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Natural language -> ODRL stages
# ---------------------------------------------------------------------------
def _generate_and_normalize_step(state: ODRLPipelineState) -> ODRLPipelineState:
    """Invoke the generation chain and normalize its output."""

    result = _generation_chain().invoke(
        {"user_prompt": state["text"]},
        config=llm_config(state.get("model"), _GENERATION_MAX_TOKENS, json_mode=True),
    )

    raw_response = result["raw"]
    raw_policy = result["data"]

    if not isinstance(raw_policy, dict):
        raise ValueError("The generated policy must be a JSON object.")

    normalized_policy = normalize_odrl_policy(deepcopy(raw_policy))

    return {
        **state,
        "raw_model_response": raw_response,
        "cleaned_model_response": raw_response,
        "raw_policy": raw_policy,
        "normalized_policy": normalized_policy,
        "policy": deepcopy(normalized_policy),
        "llm_calls": 1,
        "duration_seconds": 0.0,
        "validation_history": [],
        "repair_attempted": False,
        "repaired": False,
        "repair_attempts": 0,
        "repair_changes": [],
        "repair_stopped_reason": None,
        "original_policy_before_repair": None,
    }


def _validate_step(state: ODRLPipelineState) -> ODRLPipelineState:
    policy = state.get("policy")

    if policy is None:
        raise ValueError("No generated policy is available.")

    result = validate_policy(policy)

    return {
        **state,
        "validation_result": result,
        "validation_history": [*state.get("validation_history", []), result],
    }


# ---- Assisted repair, expressed as an LCEL sub-pipeline --------------------
def _deterministic_stage(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the deterministic repair and re-validate before considering the LLM."""

    policy, initial_changes = repair_policy_deterministically(
        deepcopy(payload["policy"])
    )
    validation = validate_policy(policy)

    return {
        **payload,
        "policy": policy,
        "initial_changes": initial_changes,
        "det_valid": validation.valid,
        "det_validation": validation,
    }


def _short_circuit_repair(payload: dict[str, Any]) -> RepairResult:
    """Deterministic repair already produced a valid policy: no LLM needed."""

    return RepairResult(
        repaired_policy=payload["policy"],
        changes=payload["initial_changes"],
        llm_used=False,
    )


def _build_repair_input(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload["det_validation"]
    errors = _validation_errors(validation) or payload["validation_errors"]

    user_prompt = json.dumps(
        {
            "original_text": payload["original_text"],
            "invalid_policy": payload["policy"],
            "validation_errors": errors,
        },
        indent=2,
        ensure_ascii=False,
    )

    return {**payload, "user_prompt": user_prompt}

def _finalize_llm_repair(payload: dict[str, Any]) -> RepairResult:
    result = payload["_llm"]["data"]

    if not isinstance(result, dict):
        raise ValueError("The repair response must be a JSON object.")

    repaired_policy = result.get("repaired_policy")

    if not isinstance(repaired_policy, dict):
        raise ValueError(
            "The repair response must contain 'repaired_policy' as a JSON object."
        )

    previous_uid = payload["policy"].get("uid")
    if previous_uid:
        repaired_policy["uid"] = previous_uid

    repaired_policy, final_changes = repair_policy_deterministically(
        normalize_odrl_policy(repaired_policy)
    )

    changes = result.get("changes", [])
    if not isinstance(changes, list):
        changes = [str(changes)]

    return RepairResult(
        repaired_policy=repaired_policy,
        changes=list(
            dict.fromkeys(
                payload["initial_changes"]
                + [str(change) for change in changes]
                + final_changes
            )
        ),
        llm_used=True,
    )


# The LLM branch is itself an LCEL chain: build the prompt payload, run the
# repair chain (merging its output into the payload with ``assign``), then turn
# the response into a RepairResult.
_LLM_REPAIR: Runnable = (
    RunnableLambda(_build_repair_input)
    | RunnablePassthrough.assign(
        _llm=lambda payload: _repair_chain().invoke(
            {"user_prompt": payload["user_prompt"]},
            config=llm_config(
                payload.get("model"), _REPAIR_MAX_TOKENS, json_mode=True
            ),
        )
    )
    | RunnableLambda(_finalize_llm_repair)
)


# A single repair attempt: deterministic stage, then branch between the
# short-circuit (already valid) and the assisted LLM repair.
_REPAIR_ONCE: Runnable = RunnableLambda(_deterministic_stage) | RunnableBranch(
    (lambda payload: payload["det_valid"], RunnableLambda(_short_circuit_repair)),
    _LLM_REPAIR,
)


def _repair_iteratively_step(state: ODRLPipelineState) -> ODRLPipelineState:
    """Bounded controller that drives the LCEL repair attempt until the policy
    is valid, no progress is made, or the configured attempt limit is reached."""

    validation = state["validation_result"]
    policy = state["policy"]
    original_policy = deepcopy(policy)

    history = list(state.get("validation_history", []))
    changes: list[str] = []
    attempts = 0
    llm_calls = state.get("llm_calls", 1)

    max_attempts = max(1, int(settings.MAX_REPAIR_ATTEMPTS))
    stop_reason: str | None = None

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        previous_signature = _policy_signature(policy)

        repair: RepairResult = _REPAIR_ONCE.invoke(
            {
                "original_text": state["text"],
                "policy": policy,
                "validation_errors": _validation_errors(validation),
                "model": state.get("model"),
            }
        )

        llm_calls += int(repair.llm_used)
        candidate = repair.repaired_policy

        changes.extend(
            f"Attempt {attempt}: {change}" for change in repair.changes
        )

        if _policy_signature(candidate) == previous_signature:
            stop_reason = (
                "The repair process produced the same policy and no further "
                "progress could be made."
            )
            break

        policy = candidate
        validation = validate_policy(policy)
        history.append(validation)

        if validation.valid:
            stop_reason = (
                f"The policy passed validation after {attempt} repair attempt(s)."
            )
            break
    else:
        stop_reason = "The maximum number of automatic repair attempts was reached."

    return {
        **state,
        "policy": policy,
        "validation_result": validation,
        "validation_history": history,
        "llm_calls": llm_calls,
        "repair_attempted": bool(attempts),
        "repaired": validation.valid,
        "repair_attempts": attempts,
        "repair_changes": changes,
        "repair_stopped_reason": stop_reason,
        "original_policy_before_repair": original_policy,
    }


def _repair_disabled_step(state: ODRLPipelineState) -> ODRLPipelineState:
    return {**state, "repair_stopped_reason": "Automatic repair is disabled."}


# ---------------------------------------------------------------------------
# ODRL -> natural language stages
# ---------------------------------------------------------------------------
def _parse_policy_step(state: ODRLToNLPipelineState) -> ODRLToNLPipelineState:
    base = {
        **state,
        "validation_result": None,
        "explanation": None,
        "llm_calls": 0,
        "duration_seconds": 0.0,
    }

    try:
        policy = json.loads(state["policy_text"])
    except json.JSONDecodeError:
        return {
            **base,
            "policy": None,
            "parse_error": (
                "The input is not valid JSON. Please correct it before "
                "generating an explanation."
            ),
        }

    if not isinstance(policy, dict):
        return {
            **base,
            "policy": None,
            "parse_error": (
                "The ODRL JSON-LD policy must be represented as a JSON object."
            ),
        }

    return {**base, "policy": policy, "parse_error": None}


def _validate_policy_step(state: ODRLToNLPipelineState) -> ODRLToNLPipelineState:
    policy = state.get("policy")

    if policy is None:
        raise ValueError("No parsed policy is available.")

    return {**state, "validation_result": validate_policy(policy)}


def _generate_explanation_step(
    state: ODRLToNLPipelineState,
) -> ODRLToNLPipelineState:
    policy = state.get("policy")

    if policy is None:
        raise ValueError("No policy is available.")

    explanation = _explanation_chain().invoke(
        {"user_prompt": json.dumps(policy, indent=2, ensure_ascii=False)},
        config=llm_config(
            state.get("model"), _EXPLANATION_MAX_TOKENS, json_mode=False
        ),
    )

    return {
        **state,
        "explanation": explanation.strip() if explanation else explanation,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# ---------------------------------------------------------------------------
# Runnable steps
# ---------------------------------------------------------------------------
def _step(function, name: str) -> Runnable:
    return RunnableLambda(function).with_config({"run_name": name})


_GENERATION_STEP = _step(_generate_and_normalize_step, "generate_and_normalize_odrl")
_VALIDATION_STEP = _step(_validate_step, "validate_generated_odrl")
_REPAIR_STEP = _step(_repair_iteratively_step, "repair_odrl_iteratively")
_REPAIR_DISABLED_STEP = _step(_repair_disabled_step, "repair_disabled")
_PARSE_STEP = _step(_parse_policy_step, "parse_odrl_json_ld")
_INPUT_VALIDATION_STEP = _step(_validate_policy_step, "validate_input_odrl")
_EXPLANATION_STEP = _step(
    _generate_explanation_step, "generate_natural_language_explanation"
)


# ---------------------------------------------------------------------------
# Control-flow predicates
# ---------------------------------------------------------------------------
def _is_valid(state: ODRLPipelineState) -> bool:
    return bool(state["validation_result"].valid)


def _repair_enabled(state: ODRLPipelineState) -> bool:
    return bool(state.get("repair_enabled", True))


def _has_parse_error(state: ODRLToNLPipelineState) -> bool:
    return bool(state.get("parse_error"))


def _input_is_valid(state: ODRLToNLPipelineState) -> bool:
    validation = state.get("validation_result")
    return validation is not None and validation.valid


# ---------------------------------------------------------------------------
# Pipelines (LCEL)
# ---------------------------------------------------------------------------
# Generation followed by validation, without repair.
_INITIAL_ODRL_PIPELINE: Runnable = _GENERATION_STEP | _VALIDATION_STEP

# After validation, branch: valid -> done; invalid & repair enabled -> repair;
# invalid & repair disabled -> record the reason.
_REPAIR_ROUTER: Runnable = RunnableBranch(
    (_is_valid, RunnablePassthrough()),
    (_repair_enabled, _REPAIR_STEP),
    _REPAIR_DISABLED_STEP,
)

_ODRL_PIPELINE: Runnable = _INITIAL_ODRL_PIPELINE | _REPAIR_ROUTER

# ODRL -> NL: parse, then (only when parsing succeeds) validate and, if valid,
# explain. Each decision is a branch in the pipeline.
_VALIDATE_AND_EXPLAIN: Runnable = _INPUT_VALIDATION_STEP | RunnableBranch(
    (_input_is_valid, _EXPLANATION_STEP),
    RunnablePassthrough(),
)

_ODRL_TO_NL_PIPELINE: Runnable = _PARSE_STEP | RunnableBranch(
    (_has_parse_error, RunnablePassthrough()),
    _VALIDATE_AND_EXPLAIN,
)


def build_initial_odrl_pipeline() -> Runnable:
    return _INITIAL_ODRL_PIPELINE


def build_odrl_pipeline() -> Runnable:
    return _ODRL_PIPELINE


def build_odrl_to_nl_pipeline() -> Runnable:
    return _ODRL_TO_NL_PIPELINE


# ---------------------------------------------------------------------------
# Timed entry points (public API, unchanged signatures)
# ---------------------------------------------------------------------------
def _run_timed(pipeline: Runnable, values: dict) -> dict:
    start = perf_counter()
    result = pipeline.invoke(values)
    result["duration_seconds"] = round(perf_counter() - start, 3)
    return result


def run_initial_odrl_pipeline(
    text: str,
    model: str | None = None,
) -> ODRLPipelineState:
    return _run_timed(
        _INITIAL_ODRL_PIPELINE,
        {"text": text, "model": model, "repair_enabled": False},
    )


def run_odrl_pipeline(
    text: str,
    model: str | None = None,
    repair_enabled: bool = True,
) -> ODRLPipelineState:
    return _run_timed(
        _ODRL_PIPELINE,
        {"text": text, "model": model, "repair_enabled": repair_enabled},
    )


def run_odrl_to_nl_pipeline(
    policy_text: str,
    model: str | None = None,
) -> ODRLToNLPipelineState:
    return _run_timed(
        _ODRL_TO_NL_PIPELINE,
        {"policy_text": policy_text, "model": model},
    )