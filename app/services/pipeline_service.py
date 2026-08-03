"""Orchestrates the two translation flows: NL -> ODRL and ODRL -> NL.

Each flow calls the LLM, then validates and (for NL -> ODRL) repairs the
result if needed. Both entry points return a plain dict with everything the
API and the evaluation service need to report on a translation.
"""

from copy import deepcopy
import json
from time import perf_counter
from typing import Any

from app.config import settings
from app.schemas import ValidationResult
from app.services.inference_service import (
    explain_odrl_policy,
    generate_odrl_policy,
    repair_odrl_policy,
)
from app.services.normalization_service import (
    normalize_odrl_policy,
    repair_policy_deterministically,
)
from app.validator import validate_policy

# Token budgets per task.
_GENERATION_MAX_TOKENS = 800
_REPAIR_MAX_TOKENS = 1500
_EXPLANATION_MAX_TOKENS = 800


def _validation_errors(result: ValidationResult) -> list[str]:
    return [f"{issue.path}: {issue.message}" if issue.path else issue.message for issue in result.issues]


def _policy_signature(policy: dict[str, Any]) -> str:
    return json.dumps(policy, sort_keys=True, ensure_ascii=False)


def _repair_once(
    original_text: str,
    policy: dict[str, Any],
    previous_errors: list[str],
    model: str | None,
) -> tuple[dict[str, Any], bool, list[str]]:
    """One repair attempt: try a deterministic fix first, then ask the LLM if needed."""

    policy, changes = repair_policy_deterministically(deepcopy(policy))
    validation = validate_policy(policy)
    if validation.valid:
        return policy, False, changes

    user_prompt = json.dumps(
        {
            "original_text": original_text,
            "invalid_policy": policy,
            "validation_errors": _validation_errors(validation) or previous_errors,
        },
        indent=2,
        ensure_ascii=False,
    )
    _, response = repair_odrl_policy(user_prompt, model, _REPAIR_MAX_TOKENS)

    repaired_policy = response.get("repaired_policy")
    if not isinstance(repaired_policy, dict):
        raise ValueError("The repair response must contain 'repaired_policy' as a JSON object.")

    previous_uid = policy.get("uid")
    if previous_uid:
        repaired_policy["uid"] = previous_uid

    repaired_policy, final_changes = repair_policy_deterministically(normalize_odrl_policy(repaired_policy))

    llm_changes = response.get("changes", [])
    if not isinstance(llm_changes, list):
        llm_changes = [str(llm_changes)]

    all_changes = list(dict.fromkeys([*changes, *(str(c) for c in llm_changes), *final_changes]))
    return repaired_policy, True, all_changes


def run_odrl_pipeline(
    text: str,
    model: str | None = None,
    repair_enabled: bool = True,
) -> dict[str, Any]:
    """Generate an ODRL policy from natural language, then validate and repair it."""

    start = perf_counter()

    raw_response, raw_policy = generate_odrl_policy(text, model, _GENERATION_MAX_TOKENS)
    normalized_policy = normalize_odrl_policy(deepcopy(raw_policy))
    policy = deepcopy(normalized_policy)
    llm_calls = 1

    validation = validate_policy(policy)
    validation_history = [validation]

    repair_attempted = False
    repaired = False
    repair_attempts = 0
    repair_changes: list[str] = []
    repair_stopped_reason: str | None = None
    original_policy_before_repair: dict[str, Any] | None = None

    if not validation.valid and not repair_enabled:
        repair_stopped_reason = "Automatic repair is disabled."

    elif not validation.valid:
        original_policy_before_repair = deepcopy(policy)
        max_attempts = max(1, int(settings.MAX_REPAIR_ATTEMPTS))

        for attempt in range(1, max_attempts + 1):
            repair_attempted = True
            repair_attempts = attempt
            previous_signature = _policy_signature(policy)

            policy, used_llm, changes = _repair_once(text, policy, _validation_errors(validation), model)
            llm_calls += int(used_llm)
            repair_changes.extend(f"Attempt {attempt}: {change}" for change in changes)

            if _policy_signature(policy) == previous_signature:
                repair_stopped_reason = (
                    "The repair process produced the same policy and no further progress could be made."
                )
                break

            validation = validate_policy(policy)
            validation_history.append(validation)

            if validation.valid:
                repaired = True
                repair_stopped_reason = f"The policy passed validation after {attempt} repair attempt(s)."
                break
        else:
            repair_stopped_reason = "The maximum number of automatic repair attempts was reached."

    return {
        "text": text,
        "model": model,
        "repair_enabled": repair_enabled,
        "raw_model_response": raw_response,
        "cleaned_model_response": raw_response,
        "raw_policy": raw_policy,
        "normalized_policy": normalized_policy,
        "policy": policy,
        "validation_result": validation,
        "validation_history": validation_history,
        "repair_attempted": repair_attempted,
        "repaired": repaired,
        "repair_attempts": repair_attempts,
        "repair_changes": repair_changes,
        "repair_stopped_reason": repair_stopped_reason,
        "original_policy_before_repair": original_policy_before_repair,
        "llm_calls": llm_calls,
        "duration_seconds": round(perf_counter() - start, 3),
    }


def run_odrl_to_nl_pipeline(policy_text: str, model: str | None = None) -> dict[str, Any]:
    """Parse an ODRL JSON-LD policy, validate it, and explain it in plain language."""

    start = perf_counter()
    state: dict[str, Any] = {
        "policy_text": policy_text,
        "model": model,
        "policy": None,
        "parse_error": None,
        "validation_result": None,
        "explanation": None,
        "llm_calls": 0,
    }

    try:
        policy = json.loads(policy_text)
    except json.JSONDecodeError:
        state["parse_error"] = "The input is not valid JSON. Please correct it before generating an explanation."
        state["duration_seconds"] = round(perf_counter() - start, 3)
        return state

    if not isinstance(policy, dict):
        state["parse_error"] = "The ODRL JSON-LD policy must be represented as a JSON object."
        state["duration_seconds"] = round(perf_counter() - start, 3)
        return state

    state["policy"] = policy
    validation = validate_policy(policy)
    state["validation_result"] = validation

    if validation.valid:
        state["explanation"] = explain_odrl_policy(
            json.dumps(policy, indent=2, ensure_ascii=False), model, _EXPLANATION_MAX_TOKENS
        )
        state["llm_calls"] = 1

    state["duration_seconds"] = round(perf_counter() - start, 3)
    return state
