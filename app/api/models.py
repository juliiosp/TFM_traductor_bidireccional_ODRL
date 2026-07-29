"""Request and response models for the HTTP API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import EvaluationRunResult, ValidationResult


class NLToODRLRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="Natural language description of the usage policy.",
        examples=["CompanyA may use Dataset1 only for research purposes."],
    )
    model: str | None = Field(default=None)
    repair_enabled: bool = Field(default=True)


class ODRLToNLRequest(BaseModel):
    policy: dict[str, Any]
    model: str | None = Field(default=None)


class ValidateRequest(BaseModel):
    policy: dict[str, Any]


class EvaluationRequest(BaseModel):
    model: str | None = Field(default=None)
    evaluator_model: str | None = Field(default=None)
    repair_enabled: bool = Field(default=True)
    ai_evaluation_enabled: bool = Field(default=False)


class RepairInfo(BaseModel):
    attempted: bool = False
    applied: bool = False
    attempts: int = 0
    changes: list[str] = Field(default_factory=list)
    stopped_reason: str | None = None


class NLToODRLResponse(BaseModel):
    valid: bool
    policy: dict[str, Any]
    validation: ValidationResult
    repair: RepairInfo
    llm_calls: int = 0
    duration_seconds: float = 0.0


class ODRLToNLResponse(BaseModel):
    explanation: str | None = None
    validation: ValidationResult | None = None
    parse_error: str | None = None
    policy: dict[str, Any] | None = None
    llm_calls: int = 0
    duration_seconds: float = 0.0


class ValidateResponse(BaseModel):
    validation: ValidationResult


class TranslationHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: str
    input_text: str
    output_text: str
    status: str
    error_message: str | None = None
    model: str | None = None
    repair_enabled: bool = False
    repair_applied: bool = False
    repair_changes: str | None = None
    original_policy_before_repair: str | None = None
    repair_attempts: int = 0
    repair_stopped_reason: str | None = None
    llm_calls: int = 0
    duration_seconds: float = 0.0
    validation_report: str | None = None
    created_at: datetime | None = None


class TranslationHistoryResponse(BaseModel):
    items: list[TranslationHistoryItem] = Field(default_factory=list)


class DeleteHistoryResponse(BaseModel):
    deleted: int


class HealthResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    database: str


# Re-exported for API documentation and explicit response typing.
EvaluationResponse = EvaluationRunResult