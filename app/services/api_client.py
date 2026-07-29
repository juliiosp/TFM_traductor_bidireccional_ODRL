"""HTTP client used by the Gradio interface.

The interface is intentionally decoupled from the translation services and the
persistence layer. In both Docker Compose and Kubernetes it communicates only
with the FastAPI service through this module.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.api.models import TranslationHistoryItem
from app.schemas import EvaluationRunResult, ValidationResult
from app.services.history_service import format_translation_history

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("API_REQUEST_TIMEOUT", "300"))
EVALUATION_TIMEOUT = float(os.getenv("API_EVALUATION_TIMEOUT", "3600"))


class APIClientError(RuntimeError):
    """Raised when the FastAPI service cannot complete a request."""


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    detail = payload.get("detail") if isinstance(payload, dict) else payload
    return str(detail or payload)


def _request(
    method: str,
    path: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
    **kwargs: Any,
) -> Any:
    try:
        response = httpx.request(
            method,
            f"{API_BASE_URL}{path}",
            timeout=timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response.json() if response.content else None
    except httpx.HTTPStatusError as error:
        raise APIClientError(_error_detail(error.response)) from error
    except httpx.HTTPError as error:
        raise APIClientError(
            f"The API is not available at {API_BASE_URL}: {error}"
        ) from error


def _repair_message(
    validation: ValidationResult,
    repair: dict[str, Any],
) -> str:
    attempted = bool(repair.get("attempted"))
    applied = bool(repair.get("applied"))

    if not attempted:
        return validation.to_display_text()

    header = (
        "✅ Policy was automatically repaired."
        if applied
        else "⚠️ Automatic repair was attempted, but the policy is still invalid."
    )
    details: list[str] = []

    attempts = int(repair.get("attempts", 0))
    if attempts:
        details.append(f"**Repair attempts:** {attempts}")

    stopped_reason = repair.get("stopped_reason")
    if stopped_reason:
        details.append(f"**Repair result:** {stopped_reason}")

    changes = repair.get("changes") or []
    if changes:
        details.append(
            "🔧 Repair changes applied:\n"
            + "\n".join(f"- {change}" for change in changes)
        )

    return "\n\n".join([header, *details, validation.to_display_text()])


def translate_natural_language_to_odrl(
    text: str,
    model: str | None,
    repair_enabled: bool,
) -> tuple[str, str]:
    if not text.strip():
        return "", "Please enter a natural language policy."

    try:
        payload = _request(
            "POST",
            "/api/v1/translate/nl-to-odrl",
            json={
                "text": text,
                "model": model,
                "repair_enabled": repair_enabled,
            },
        )
        validation = ValidationResult.model_validate(payload["validation"])
        output = json.dumps(payload["policy"], indent=4, ensure_ascii=False)
        return output, _repair_message(validation, payload["repair"])
    except APIClientError as error:
        return "", f"❌ Translation error: {error}"


def translate_to_natural_language(
    policy_text: str,
    model: str | None,
) -> str:
    if not policy_text.strip():
        return "Please enter an ODRL JSON-LD policy."

    try:
        policy = json.loads(policy_text)
    except json.JSONDecodeError as error:
        return f"❌ Invalid JSON: {error}"

    if not isinstance(policy, dict):
        return "❌ The ODRL policy must be represented by a JSON object."

    try:
        payload = _request(
            "POST",
            "/api/v1/translate/odrl-to-nl",
            json={"policy": policy, "model": model},
        )
    except APIClientError as error:
        return f"❌ Translation error: {error}"

    if payload.get("parse_error"):
        return f"❌ {payload['parse_error']}"

    validation_payload = payload.get("validation")
    if validation_payload:
        validation = ValidationResult.model_validate(validation_payload)
        if not validation.valid:
            return (
                "❌ The policy did not pass validation and was not sent to "
                "the LLM.\n\n" + validation.to_display_text()
            )

    return payload.get("explanation") or "❌ The API returned no explanation."


def validate_odrl_text(policy_text: str) -> str:
    if not policy_text.strip():
        return "Please enter an ODRL JSON-LD policy."

    try:
        policy = json.loads(policy_text)
    except json.JSONDecodeError as error:
        return f"❌ Invalid JSON: {error}"

    if not isinstance(policy, dict):
        return "❌ The ODRL policy must be represented by a JSON object."

    try:
        payload = _request(
            "POST",
            "/api/v1/validate",
            json={"policy": policy},
        )
        return ValidationResult.model_validate(
            payload["validation"]
        ).to_display_text()
    except APIClientError as error:
        return f"❌ Validation error: {error}"


def run_evaluation(
    model: str | None,
    evaluator_model: str | None,
    repair_enabled: bool,
    ai_evaluation_enabled: bool,
) -> EvaluationRunResult:
    payload = _request(
        "POST",
        "/api/v1/evaluation/run",
        timeout=EVALUATION_TIMEOUT,
        json={
            "model": model,
            "evaluator_model": evaluator_model,
            "repair_enabled": repair_enabled,
            "ai_evaluation_enabled": ai_evaluation_enabled,
        },
    )
    return EvaluationRunResult.model_validate(payload)


def load_translation_history() -> str:
    try:
        payload = _request("GET", "/api/v1/history")
        items = [
            TranslationHistoryItem.model_validate(item)
            for item in payload.get("items", [])
        ]
        return format_translation_history(items)
    except APIClientError as error:
        return f"Error loading history: {error}"


def clear_translation_history() -> str:
    try:
        payload = _request("DELETE", "/api/v1/history")
        deleted = int(payload.get("deleted", 0))
        return (
            f"History cleared successfully. Deleted records: {deleted}."
            if deleted
            else "No translations were stored in the history."
        )
    except APIClientError as error:
        return f"Error clearing history: {error}"