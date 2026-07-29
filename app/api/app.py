"""FastAPI application.

The API is the application service layer exposed over HTTP. It delegates to
the existing translation, evaluation and validation services; the Gradio
interface consumes these endpoints and does not execute business logic or
access persistence directly.

Concurrency note
----------------
The translation pipelines are synchronous (they build synchronous LangChain
runnables and call ``.invoke``). To keep the async event loop free while a
request waits on the language model, each blocking call is offloaded to the
Starlette thread pool with ``run_in_threadpool``. Combined with multiple
workers and horizontal replicas, this is enough to serve concurrent requests,
which are almost entirely I/O-bound on the model provider. Porting the pipeline
to native ``ainvoke`` is a documented next step, not required for this layer.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.database import (
    SessionLocal,
    delete_all_translations,
    get_recent_translations,
    init_db,
    save_translation,
)
from app.schemas import EvaluationRunResult, ValidationResult
from app.validator import validate_policy

from app.api.models import (
    DeleteHistoryResponse,
    EvaluationRequest,
    HealthResponse,
    NLToODRLRequest,
    NLToODRLResponse,
    ODRLToNLRequest,
    ODRLToNLResponse,
    ReadyResponse,
    TranslationHistoryItem,
    TranslationHistoryResponse,
    RepairInfo,
    ValidateRequest,
    ValidateResponse,
)

logger = logging.getLogger("app.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Idempotent: creates the table if it does not exist yet.
    init_db()
    yield


app = FastAPI(
    title="ODRL Translator API",
    version="1.0.0",
    summary="Bidirectional translation between natural language and ODRL policies.",
    lifespan=lifespan,
)

# CORS is configurable; defaults to permissive for demo/dev. Tighten in prod.
_origins = os.getenv("API_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, indent=4, ensure_ascii=False)


def _nl_status(valid: bool, repaired: bool, attempted: bool) -> str:
    if valid:
        return "success_repaired" if repaired else "success"
    return "repair_failed" if attempted else "validation_error"


# ---------------------------------------------------------------------------
# Blocking workers (executed in the thread pool)
# ---------------------------------------------------------------------------
def _run_nl_to_odrl(text: str, model: str | None, repair_enabled: bool) -> dict:
    """Run the NL -> ODRL pipeline and persist the translation."""

    from app.services.pipeline_service import run_odrl_pipeline

    state = run_odrl_pipeline(
        text=text, model=model, repair_enabled=repair_enabled
    )

    validation: ValidationResult = state["validation_result"]
    repaired = bool(state.get("repaired", False))
    attempted = bool(state.get("repair_attempted", False))
    changes = state.get("repair_changes", [])
    original = state.get("original_policy_before_repair")

    try:
        save_translation(
            direction="NL_TO_ODRL",
            input_text=text,
            output_text=_json_dumps(state["policy"]),
            status=_nl_status(validation.valid, repaired, attempted),
            error_message=None if validation.valid else validation.message,
            model=model,
            repair_enabled=repair_enabled,
            repair_applied=repaired,
            repair_changes=json.dumps(changes, ensure_ascii=False),
            original_policy_before_repair=(
                _json_dumps(original) if original is not None else None
            ),
            repair_attempts=state.get("repair_attempts", 0),
            repair_stopped_reason=state.get("repair_stopped_reason"),
            llm_calls=state.get("llm_calls", 0),
            duration_seconds=state.get("duration_seconds", 0.0),
            validation_report=validation.raw_report,
        )
    except Exception:  # persistence is best-effort; never fail the request
        logger.exception("Failed to persist NL_TO_ODRL translation")

    return state


def _run_odrl_to_nl(policy: dict[str, Any], model: str | None) -> dict:
    """Run the ODRL -> NL pipeline and persist the translation."""

    from app.services.pipeline_service import run_odrl_to_nl_pipeline

    policy_text = _json_dumps(policy)
    state = run_odrl_to_nl_pipeline(policy_text=policy_text, model=model)

    validation: ValidationResult | None = state.get("validation_result")
    explanation = state.get("explanation")
    parse_error = state.get("parse_error")

    if parse_error:
        status, output, error = "validation_error", "", parse_error
    elif validation is not None and not validation.valid:
        status, output, error = "validation_error", "", validation.message
    else:
        status, output, error = "success", explanation or "", None

    try:
        save_translation(
            direction="ODRL_TO_NL",
            input_text=policy_text,
            output_text=output,
            status=status,
            error_message=error,
            model=model,
            llm_calls=state.get("llm_calls", 0),
            duration_seconds=state.get("duration_seconds", 0.0),
            validation_report=(
                validation.raw_report if validation is not None else None
            ),
        )
    except Exception:
        logger.exception("Failed to persist ODRL_TO_NL translation")

    return state


# ---------------------------------------------------------------------------
# Health / readiness (used by Kubernetes probes)
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    """Liveness probe. Does not touch the database or the model provider."""

    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadyResponse, tags=["ops"])
async def ready() -> ReadyResponse:
    """Readiness probe. Verifies the database connection."""

    def _check_db() -> None:
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()

    try:
        await run_in_threadpool(_check_db)
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"Database not ready: {error}"
        ) from error

    return ReadyResponse(status="ok", database="ok")


# ---------------------------------------------------------------------------
# Translation and validation endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/translate/nl-to-odrl",
    response_model=NLToODRLResponse,
    tags=["translation"],
)
async def translate_nl_to_odrl(request: NLToODRLRequest) -> NLToODRLResponse:
    try:
        state = await run_in_threadpool(
            _run_nl_to_odrl,
            request.text,
            request.model,
            request.repair_enabled,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    validation: ValidationResult = state["validation_result"]

    return NLToODRLResponse(
        valid=validation.valid,
        policy=state["policy"],
        validation=validation,
        repair=RepairInfo(
            attempted=bool(state.get("repair_attempted", False)),
            applied=bool(state.get("repaired", False)),
            attempts=int(state.get("repair_attempts", 0)),
            changes=list(state.get("repair_changes", [])),
            stopped_reason=state.get("repair_stopped_reason"),
        ),
        llm_calls=int(state.get("llm_calls", 0)),
        duration_seconds=float(state.get("duration_seconds", 0.0)),
    )


@app.post(
    "/api/v1/translate/odrl-to-nl",
    response_model=ODRLToNLResponse,
    tags=["translation"],
)
async def translate_odrl_to_nl(request: ODRLToNLRequest) -> ODRLToNLResponse:
    try:
        state = await run_in_threadpool(
            _run_odrl_to_nl, request.policy, request.model
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return ODRLToNLResponse(
        explanation=state.get("explanation"),
        validation=state.get("validation_result"),
        parse_error=state.get("parse_error"),
        policy=state.get("policy"),
        llm_calls=int(state.get("llm_calls", 0)),
        duration_seconds=float(state.get("duration_seconds", 0.0)),
    )


@app.post(
    "/api/v1/validate",
    response_model=ValidateResponse,
    tags=["validation"],
)
async def validate(request: ValidateRequest) -> ValidateResponse:
    result = await run_in_threadpool(validate_policy, request.policy)
    return ValidateResponse(validation=result)


@app.post(
    "/api/v1/evaluation/run",
    response_model=EvaluationRunResult,
    tags=["evaluation"],
)
async def run_evaluation(request: EvaluationRequest) -> EvaluationRunResult:
    """Execute the fixed evaluation suite using the same application services."""

    try:
        from app.services.evaluation_service import run_default_evaluation

        return await run_in_threadpool(
            run_default_evaluation,
            request.model,
            request.evaluator_model,
            request.repair_enabled,
            request.ai_evaluation_enabled,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get(
    "/api/v1/history",
    response_model=TranslationHistoryResponse,
    tags=["history"],
)
async def history(limit: int = 10) -> TranslationHistoryResponse:
    """Return the most recent persisted translations."""

    safe_limit = max(1, min(limit, 100))
    items = await run_in_threadpool(get_recent_translations, safe_limit)
    return TranslationHistoryResponse(
        items=[TranslationHistoryItem.model_validate(item) for item in items]
    )


@app.delete(
    "/api/v1/history",
    response_model=DeleteHistoryResponse,
    tags=["history"],
)
async def clear_history() -> DeleteHistoryResponse:
    """Delete every translation stored in the shared database."""

    deleted = await run_in_threadpool(delete_all_translations)
    return DeleteHistoryResponse(deleted=deleted)