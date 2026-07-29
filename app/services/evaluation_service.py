from collections import defaultdict
import json
from statistics import mean
from typing import Any

import pandas as pd
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from app.evaluation.expectations import compare_expected_elements
from app.evaluation.test_cases import DEFAULT_EVALUATION_CASES, EvaluationTestCase
from app.prompts import SYSTEM_PROMPT_EVALUATE_TRANSLATION
from app.schemas import AIEvaluationScores, EvaluationCaseResult, EvaluationRunResult
from app.services.inference_service import get_langchain_model
from app.services.pipeline_service import run_odrl_pipeline, run_odrl_to_nl_pipeline


AI_PASS_THRESHOLD = 4
AI_SCORE_FIELDS = (
    ("Structural validity", "structural_validity"),
    ("Semantic fidelity", "semantic_fidelity"),
    ("Completeness", "completeness"),
    ("Clarity", "clarity"),
)

_AI_PROMPT = ChatPromptTemplate.from_messages(
    [
        SystemMessage(content=SYSTEM_PROMPT_EVALUATE_TRANSLATION),
        ("human", "{evaluation_input}"),
    ]
)


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _percentage(value: int, total: int) -> str:
    return f"{value / (total or 1) * 100:.1f} %"


def _validation_flags(validation) -> tuple[bool, bool]:
    return validation.valid or validation.stage in {"shacl", "complete"}, validation.valid


def _issue_messages(validation) -> list[str]:
    return [
        (
            f"{issue.path}: {issue.message}"
            if issue.path
            else issue.message
        )
        for issue in validation.issues
    ]


def _initial_result(case: EvaluationTestCase) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        id=case.id,
        input_text=case.natural_language,
        expected_rule_type=case.rule_type,
        expected_constraint=case.main_constraint,
        expected_policy_type=case.policy_type,
        expected_actions=case.expected_actions,
        covered_elements=case.covered_elements,
        notes=case.notes,
    )


def _evaluate_with_ai(
    case: EvaluationTestCase,
    odrl_policy_text: str,
    explanation: str,
    evaluator_model: str | None,
) -> AIEvaluationScores:
    evaluation_input = _dump(
        {
            "case_id": case.id,
            "original_natural_language_policy": case.natural_language,
            "expected_policy_type": case.policy_type,
            "expected_rule_type": case.rule_type,
            "expected_main_constraint": case.main_constraint,
            "expected_actions": case.expected_actions,
            "covered_odrl_subset_elements": case.covered_elements,
            "generated_odrl_json_ld": odrl_policy_text,
            "generated_natural_language_explanation": explanation,
        }
    )

    model = get_langchain_model(
        model=evaluator_model,
        temperature=0.0,
        max_tokens=700,
    ).with_structured_output(AIEvaluationScores)

    response = (_AI_PROMPT | model).invoke({"evaluation_input": evaluation_input})

    if isinstance(response, AIEvaluationScores):
        return response
    if isinstance(response, dict):
        return AIEvaluationScores(**response)
    raise ValueError("The AI evaluator returned an unsupported response type.")


def evaluate_single_case(
    case: EvaluationTestCase,
    model: str | None = None,
    evaluator_model: str | None = None,
    repair_enabled: bool = True,
    ai_evaluation_enabled: bool = False,
) -> EvaluationCaseResult:
    result = _initial_result(case)

    try:
        state = run_odrl_pipeline(
            text=case.natural_language,
            model=model,
            repair_enabled=repair_enabled,
        )

        result.raw_model_response = state.get("raw_model_response", "")
        result.cleaned_model_response = state.get("cleaned_model_response", "")
        result.raw_odrl_policy = state.get("raw_policy")
        result.normalized_odrl_policy = state.get("normalized_policy")
        result.json_valid = True

        if result.raw_odrl_policy is not None:
            result.raw_odrl_policy_text = _dump(result.raw_odrl_policy)
        if result.normalized_odrl_policy is not None:
            result.normalized_odrl_policy_text = _dump(result.normalized_odrl_policy)

        policy = state.get("policy")
        validation = state.get("validation_result")
        if policy is None or validation is None:
            raise ValueError("The NL → ODRL pipeline did not return a complete result.")

        history = state.get("validation_history", [])
        if history:
            result.initial_basic_valid, result.initial_shacl_valid = _validation_flags(
                history[0]
            )
            result.valid_first_attempt = history[0].valid

        result.repair_attempted = bool(state.get("repair_attempted"))
        result.repair_applied = bool(state.get("repaired"))
        result.repair_changes = [str(change) for change in state.get("repair_changes", [])]

        if result.repair_attempted and history:
            result.repair_errors_before = _issue_messages(history[0])
            result.repaired_odrl_policy = policy
            result.repaired_odrl_policy_text = _dump(policy)
            result.final_policy_stage = "repaired"
        else:
            result.final_policy_stage = "normalized"

        result.basic_valid, result.shacl_valid = _validation_flags(validation)
        result.validation_message = validation.to_display_text()
        result.odrl_policy = policy
        result.odrl_policy_text = _dump(policy)
        compare_expected_elements(result, policy, case)

        if validation.valid:
            explanation_state = run_odrl_to_nl_pipeline(
                policy_text=result.odrl_policy_text,
                model=model,
            )
            result.odrl_to_nl_explanation = explanation_state.get("explanation") or ""

        if ai_evaluation_enabled:
            try:
                result.ai_scores = _evaluate_with_ai(
                    case,
                    result.odrl_policy_text,
                    result.odrl_to_nl_explanation,
                    evaluator_model or model,
                )
            except Exception as error:
                result.ai_error = f"AI evaluator error: {type(error).__name__}: {error}"

    except Exception as error:
        result.error = str(error)

    return result


def _count(results: list[EvaluationCaseResult], field: str) -> int:
    return sum(bool(getattr(item, field)) for item in results)


def run_default_evaluation(
    model: str | None = None,
    evaluator_model: str | None = None,
    repair_enabled: bool = True,
    ai_evaluation_enabled: bool = False,
) -> EvaluationRunResult:
    results = [
        evaluate_single_case(
            case,
            model,
            evaluator_model,
            repair_enabled,
            ai_evaluation_enabled,
        )
        for case in DEFAULT_EVALUATION_CASES
    ]

    return EvaluationRunResult(
        total_cases=len(results),
        json_valid_count=_count(results, "json_valid"),
        first_attempt_valid_count=_count(results, "valid_first_attempt"),
        basic_valid_count=_count(results, "basic_valid"),
        shacl_valid_count=_count(results, "shacl_valid"),
        repair_attempted_count=_count(results, "repair_attempted"),
        repair_applied_count=_count(results, "repair_applied"),
        results=results,
    )


def _score_average(results: list[EvaluationCaseResult], field: str) -> float | None:
    values = [getattr(item.ai_scores, field) for item in results if item.ai_scores]
    return round(mean(values), 2) if values else None


def _semantically_correct_count(results: list[EvaluationCaseResult]) -> int:
    """Count deterministic matches, additionally enforcing AI thresholds when present."""

    return sum(
        item.expected_elements_match
        and (
            item.ai_scores is None
            or (
                item.ai_scores.semantic_fidelity >= AI_PASS_THRESHOLD
                and item.ai_scores.completeness >= AI_PASS_THRESHOLD
            )
        )
        for item in results
    )


def _case_status(item: EvaluationCaseResult) -> str:
    if item.error:
        return "Error"
    if not item.json_valid:
        return "Incorrect"
    if item.shacl_valid:
        if not item.expected_elements_match or (
            item.ai_scores
            and (
                item.ai_scores.semantic_fidelity < AI_PASS_THRESHOLD
                or item.ai_scores.completeness < AI_PASS_THRESHOLD
            )
        ):
            return "Partially correct"
        return "Correct"
    return "Partially correct" if item.basic_valid else "Incorrect"


def _case_comment(item: EvaluationCaseResult) -> str:
    if item.error:
        return f"An error occurred during the evaluation: {item.error}"
    if item.repair_attempted and not item.repair_applied:
        return (
            "Automatic repair was attempted, but the final policy did not pass "
            "all validations."
        )

    parts = [
        (
            "The generated policy was valid JSON, passed the basic ODRL checks "
            "and satisfied the SHACL shapes."
            if item.shacl_valid
            else "The generated policy did not satisfy all validation stages."
        ),
        (
            "Automatic repair was applied successfully."
            if item.repair_applied
            else "No automatic repair was required."
        ),
        (
            "However, the final policy does not fully match the expected core "
            "ODRL elements: " + " ".join(item.expected_mismatches)
            if item.expected_mismatches
            else "The generated core ODRL elements match the predefined "
            "expectations for the case."
        ),
    ]

    if item.ai_scores:
        passed = (
            item.ai_scores.semantic_fidelity >= AI_PASS_THRESHOLD
            and item.ai_scores.completeness >= AI_PASS_THRESHOLD
        )
        parts.append(
            "It also met the configured AI quality threshold."
            if passed
            else "It did not meet the configured AI quality threshold in all "
            "required criteria."
        )
    elif item.ai_error:
        parts.append(f"The AI evaluator could not score this case: {item.ai_error}")

    return " ".join(parts)


def _group_results(
    results: list[EvaluationCaseResult],
    field: str,
    default: str = "Not specified",
) -> dict[str, list[EvaluationCaseResult]]:
    grouped = defaultdict(list)
    for item in results:
        grouped[getattr(item, field) or default].append(item)
    return dict(grouped)


def _coverage_counts(results: list[EvaluationCaseResult]) -> dict[str, int]:
    counts = defaultdict(int)
    for item in results:
        for element in item.covered_elements:
            counts[element] += 1
    return dict(sorted(counts.items(), key=lambda pair: pair[0].lower()))


def _metric_row(label: str, count: int, total: int) -> dict[str, int | float | str]:
    return {
        "Metric": label,
        "Cases": count,
        "Percentage": round(count / (total or 1) * 100, 1),
    }


def evaluation_metrics_cards_html(run_result: EvaluationRunResult) -> str:
    total = run_result.total_cases
    semantic = _semantically_correct_count(run_result.results)
    cards = [
        ("Cases", str(total), "Fixed evaluation suite"),
        ("Valid JSON", f"{run_result.json_valid_count}/{total}",
            _percentage(run_result.json_valid_count, total)),
        ("JSON-LD pre-validation", f"{run_result.basic_valid_count}/{total}",
            _percentage(run_result.basic_valid_count, total)),
        ("Valid on first attempt", f"{run_result.first_attempt_valid_count}/{total}",   
            _percentage(run_result.first_attempt_valid_count, total)),
        ("SHACL validation", f"{run_result.shacl_valid_count}/{total}",
            _percentage(run_result.shacl_valid_count, total)),
        ("Repairs", f"{run_result.repair_applied_count}/{run_result.repair_attempted_count}",
            "applied / attempted"),
        ("Semantic match", f"{semantic}/{total}",
            "deterministic expectations; AI threshold when enabled"),
    ]
    content = "".join(
        f'<div class="metric-card"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-caption">{caption}</div></div>'
        for label, value, caption in cards
    )
    return f'<div class="metric-grid">{content}</div>'


def evaluation_global_metrics_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    total = run_result.total_cases
    rows = [
        _metric_row("Valid JSON", run_result.json_valid_count, total),
        _metric_row("JSON-LD pre-validation", run_result.basic_valid_count, total),
        _metric_row("Valid on first attempt", run_result.first_attempt_valid_count, total),  
        _metric_row("Repair required", run_result.repair_attempted_count, total),
        _metric_row("Repair applied", run_result.repair_applied_count, total),
        _metric_row("SHACL validation", run_result.shacl_valid_count, total),   
    ]
    semantic = _semantically_correct_count(run_result.results)
    rows.append(_metric_row("Semantic match", semantic, total))
    return pd.DataFrame(rows)


def _grouped_validation_dataframe(
    run_result: EvaluationRunResult,
    field: str,
    label: str,
    include_ai: bool = False,
) -> pd.DataFrame:
    rows = []
    for group, items in _group_results(run_result.results, field).items():
        shacl = _count(items, "shacl_valid")
        row = {
            label: group,
            "Cases": len(items),
            "Valid JSON": _count(items, "json_valid"),
            "Valid SHACL": shacl,
            "Repair required": _count(items, "repair_attempted"),
            "% SHACL": round(shacl / (len(items) or 1) * 100, 1),
        }
        if include_ai:
            row["Average AI fidelity"] = _score_average(items, "semantic_fidelity") or 0
        rows.append(row)
    return pd.DataFrame(rows)


def evaluation_rule_type_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    return _grouped_validation_dataframe(
        run_result,
        "expected_rule_type",
        "Type",
        include_ai=True,
    )


def evaluation_policy_type_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    return _grouped_validation_dataframe(
        run_result,
        "expected_policy_type",
        "Policy type",
    )


def evaluation_coverage_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    counts = _coverage_counts(run_result.results)
    return pd.DataFrame(
        ({"Expected ODRL element": element, "Cases": count} for element, count in counts.items())
        if counts
        else [{"Expected ODRL element": "No data", "Cases": 0}]
    )


def evaluation_ai_scores_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    rows = [
        {"Criterion": label, "Average": average}
        for label, field in AI_SCORE_FIELDS
        if (average := _score_average(run_result.results, field)) is not None
    ]
    return pd.DataFrame(
        rows or [{"Criterion": "AI evaluator not enabled", "Average": 0}]
    )


def evaluation_cases_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ID": item.id,
            "Status": _case_status(item),
            "Policy type": item.expected_policy_type,
            "Rule type": item.expected_rule_type,
            "Constraint": item.expected_constraint,
            "Expected actions": ", ".join(item.expected_actions),
            "Covered elements": ", ".join(item.covered_elements),
            "JSON": _yes_no(item.json_valid),
            "JSON-LD": _yes_no(item.basic_valid),
            "First try": _yes_no(item.valid_first_attempt),      
            "SHACL": _yes_no(item.shacl_valid),
            "Repair": _yes_no(item.repair_attempted),
            "AI fidelity": item.ai_scores.semantic_fidelity if item.ai_scores else "-",
            "AI completeness": item.ai_scores.completeness if item.ai_scores else "-",
            "Input": item.input_text,
        }
        for item in run_result.results
    )


def _case_needs_review(item: EvaluationCaseResult) -> bool:
    return bool(
        item.ai_error
        or not item.shacl_valid
        or item.repair_attempted
        or not item.expected_elements_match
        or (
            item.ai_scores
            and (
                item.ai_scores.semantic_fidelity < AI_PASS_THRESHOLD
                or item.ai_scores.completeness < AI_PASS_THRESHOLD
            )
        )
    )


def evaluation_review_dataframe(run_result: EvaluationRunResult) -> pd.DataFrame:
    rows = [
        {
            "ID": item.id,
            "Status": _case_status(item),
            "Policy type": item.expected_policy_type,
            "Rule type": item.expected_rule_type,
            "Reason": _case_comment(item),
        }
        for item in run_result.results
        if _case_needs_review(item)
    ]
    return pd.DataFrame(
        rows
        or [
            {
                "ID": "-",
                "Status": "OK",
                "Policy type": "-",
                "Rule type": "-",
                "Reason": "No cases requiring review were detected.",
            }
        ]
    )


def _repair_marker(item: EvaluationCaseResult) -> str:
    if item.repair_applied:
        return "repair applied"
    if item.repair_attempted:
        return "⚠️ repair unsuccessful"
    return "repair not required"


def evaluation_case_choices(run_result: EvaluationRunResult) -> list[str]:
    return [
        f"{item.id} · {_repair_marker(item)} · {_case_status(item)}"
        for item in run_result.results
    ]


def _find_case(
    run_result: EvaluationRunResult,
    selected_case: str | None,
) -> EvaluationCaseResult | None:
    if not run_result.results:
        return None
    selected_id = (selected_case or "").split(" · ", 1)[0].strip()
    return next(
        (item for item in run_result.results if item.id == selected_id),
        run_result.results[0],
    )


def _policy_trace_markdown(item: EvaluationCaseResult) -> str:
    stage = {
        "normalized": "Normalized generated policy",
        "repaired": "Automatically repaired policy",
    }.get(item.final_policy_stage, item.final_policy_stage or "Not available")

    lines = [
        "### Traceability",
        "",
        f"- Policy version used for evaluation: **{stage}**",
        f"- Raw generated JSON stored: **{_yes_no(bool(item.raw_odrl_policy_text))}**",
        f"- Normalized JSON stored: **{_yes_no(bool(item.normalized_odrl_policy_text))}**",
        f"- Repaired JSON stored: **{_yes_no(bool(item.repaired_odrl_policy_text))}**",
    ]
    if item.repair_changes:
        lines.extend(["", "### Repair changes", "", *(f"- {c}" for c in item.repair_changes)])
    return "\n".join(lines)


def _ai_score_lines(item: EvaluationCaseResult) -> list[str]:
    if item.ai_error:
        return [
        "### AI evaluator scores",
        "",
        f"The AI evaluator could not score this case: {item.ai_error}",
        "",
    ]
    if not item.ai_scores:
        return ["### AI evaluator scores", "", "Not enabled in this run."]

    scores = item.ai_scores
    lines = [
        "### AI evaluator scores",
        "",
        "Scores generated by an LLM evaluator on a scale from 1 to 5.",
        "",
        f"- Structural validity: **{scores.structural_validity}/5**",
        f"- Semantic fidelity: **{scores.semantic_fidelity}/5**",
        f"- Completeness: **{scores.completeness}/5**",
        f"- Clarity: **{scores.clarity}/5**",
    ]
    if scores.observations.strip():
        lines.extend(["", "### AI evaluator observations", "", scores.observations.strip()])
    return lines


def evaluation_case_detail(
    run_result: EvaluationRunResult | None,
    selected_case: str | None,
):
    if run_result is None:
        return "Run the evaluation first to inspect each case.", "{}", "", ""

    item = _find_case(run_result, selected_case)
    if item is None:
        return "No cases available.", "{}", "", ""

    expected_actions = ", ".join(item.expected_actions) or "-"
    generated_actions = ", ".join(item.generated_actions) or "Not detected"
    action_match = not any("action" in mismatch.lower() for mismatch in item.expected_mismatches)

    detail = "\n".join(
        [
            f"## {item.id} · {_case_status(item)}",
            "",
            f"**Input:** {item.input_text}",
            "",
            "### Expected ODRL elements",
            "",
            f"- Policy type: **{item.expected_policy_type}**",
            f"- Rule type: **{item.expected_rule_type}**",
            f"- Main constraint: **{item.expected_constraint}**",
            f"- Expected actions: **{expected_actions}**",
            "",
            "### Expected vs generated",
            "",
            f"- Policy type: **{item.expected_policy_type} → {item.generated_policy_type or 'Not detected'}** "
            f"{'✓' if item.expected_policy_type.casefold() == item.generated_policy_type.casefold() else '⚠'}",
            f"- Rule type: **{item.expected_rule_type} → {item.generated_rule_type or 'Not detected'}** "
            f"{'✓' if item.expected_rule_type.casefold() == item.generated_rule_type.casefold() else '⚠'}",
            f"- Actions: **{expected_actions} → {generated_actions}** {'✓' if action_match else '⚠'}",
            f"- Generated constraint structure: **{item.generated_constraint_summary or 'Not detected'}**",
            "",
            "### Validation",
            "",
            f"- Valid JSON: **{_yes_no(item.json_valid)}**",
            f"- JSON-LD pre-validation: **{_yes_no(item.basic_valid)}**",
            f"- Valid on first attempt: **{_yes_no(item.valid_first_attempt)}**",   
            f"- SHACL validation: **{_yes_no(item.shacl_valid)}**",
            f"- Automatic repair: **{_repair_marker(item)}**",
            "",
            _policy_trace_markdown(item),
            "",
            "### Comment",
            "",
            _case_comment(item),
            "",
            *_ai_score_lines(item),
        ]
    )

    return (
        detail,
        item.odrl_policy_text or _dump(item.odrl_policy or {}),
        item.odrl_to_nl_explanation or "[no explanation generated]",
        item.validation_message or item.error or "No validation message.",
    )