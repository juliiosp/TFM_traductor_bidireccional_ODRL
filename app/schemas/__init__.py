from typing import Any, Literal
from pydantic import BaseModel, Field

class ValidationIssue(BaseModel):
    stage: Literal["json", "shacl"]
    message: str
    path: str | None = None
    focus_node: str | None = None
    value: str | None = None
    severity: str | None = None
    source_constraint: str | None = None
    source_shape: str | None = None

class ValidationResult(BaseModel):
    valid: bool
    stage: Literal["json", "shacl", "complete"]
    message: str
    issues: list[ValidationIssue] = Field(
        default_factory=list
    )
    raw_report: str | None = None

    def to_display_text(self) -> str:
        if self.valid:
            return f"✅ {self.message}"

        text = f"❌ {self.message}"

        if self.issues:
            text += "\n\nErrors:\n"
            text += "\n".join(
                (
                    f"- [{issue.stage.upper()}]"
                    f"{f' ({issue.path})' if issue.path else ''}: "
                    f"{issue.message}"
                )
                for issue in self.issues
            )

        if self.raw_report and not self.issues:
            text += (
                f"\n\nRaw report:\n"
                f"{self.raw_report}"
            )

        return text

class RepairInput(BaseModel):
    original_text: str
    invalid_policy: dict[str, Any]
    validation_errors: list[str]

class RepairResult(BaseModel):
    repaired_policy: dict[str, Any]
    changes: list[str] = Field(
        default_factory=list
    )
    llm_used: bool = False

class AIEvaluationScores(BaseModel):
    structural_validity: int = Field(
        default=1,
        ge=1,
        le=5,
    )
    semantic_fidelity: int = Field(
        default=1,
        ge=1,
        le=5,
    )
    completeness: int = Field(
        default=1,
        ge=1,
        le=5,
    )
    clarity: int = Field(
        default=1,
        ge=1,
        le=5,
    )
    observations: str = ""

class EvaluationCaseResult(BaseModel):
    id: str
    input_text: str
    expected_rule_type: str
    expected_constraint: str
    expected_policy_type: str = ""
    expected_actions: list[str] = Field(
        default_factory=list
    )
    covered_elements: list[str] = Field(
        default_factory=list
    )
    notes: str = ""

    generated_policy_type: str = ""
    generated_rule_type: str = ""
    generated_actions: list[str] = Field(
        default_factory=list
    )
    generated_constraint_summary: str = ""
    expected_elements_match: bool = False
    expected_mismatches: list[str] = Field(
        default_factory=list
    )

    json_valid: bool = False
    initial_basic_valid: bool = False
    initial_shacl_valid: bool = False
    valid_first_attempt: bool = False
    basic_valid: bool = False
    shacl_valid: bool = False

    repair_attempted: bool = False
    repair_applied: bool = False
    repair_changes: list[str] = Field(
        default_factory=list
    )
    repair_errors_before: list[str] = Field(
        default_factory=list
    )

    raw_model_response: str = ""
    cleaned_model_response: str = ""

    raw_odrl_policy: dict[str, Any] | None = None
    raw_odrl_policy_text: str = ""

    normalized_odrl_policy: (
        dict[str, Any] | None
    ) = None
    normalized_odrl_policy_text: str = ""

    repaired_odrl_policy: (
        dict[str, Any] | None
    ) = None
    repaired_odrl_policy_text: str = ""

    final_policy_stage: str = ""

    odrl_policy: dict[str, Any] | None = None
    odrl_policy_text: str = ""

    odrl_to_nl_explanation: str = ""
    validation_message: str = ""

    ai_scores: AIEvaluationScores | None = None
    ai_error: str | None = None
    error: str | None = None

class EvaluationRunResult(BaseModel):
    total_cases: int
    json_valid_count: int
    first_attempt_valid_count: int
    basic_valid_count: int
    shacl_valid_count: int
    repair_attempted_count: int
    repair_applied_count: int
    results: list[EvaluationCaseResult]