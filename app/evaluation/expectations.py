"""Deterministic semantic expectations for the fixed evaluation suite."""

from typing import Any

from app.evaluation.test_cases import EvaluationTestCase
from app.schemas import EvaluationCaseResult

RULE_KEYS = ("permission", "prohibition", "obligation")

def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _local_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("@id") or value.get("uid") or value.get("@value") or value.get("value")
    text = str(value or "").strip()
    return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1]


def _semantic_value(value: Any, left_operand: str = "") -> str:
    """Return a stable value for deterministic semantic comparison."""

    if isinstance(value, dict):
        value = value.get("@value", value.get("@id", value.get("uid", value.get("value"))))
    if isinstance(value, bool):
        return str(value).lower()

    text = str(value if value is not None else "").strip()
    if left_operand.casefold() == "datetime" and len(text) >= 10:
        # The suite evaluates the calendar boundary and the operator separately.
        return text[:10]
    if text.startswith(("http://", "https://", "urn:")):
        text = _local_name(text)
    normalized = " ".join(text.split()).casefold()
    if left_operand.casefold() == "purpose":
        for suffix in (" purposes", " purpose"):
            if normalized.endswith(suffix):
                normalized = normalized.removesuffix(suffix).strip()
    return normalized


def _rules(policy: dict):
    for key in RULE_KEYS:
        for rule in _as_list(policy.get(key)):
            if isinstance(rule, dict):
                yield key, rule


def _action_values(value: Any) -> list[str]:
    actions: list[str] = []
    for item in _as_list(value):
        action = _local_name(item)
        if action and action not in actions:
            actions.append(action)
    return actions


def _generated_rule_type(policy: dict) -> str:
    has_permission = bool(policy.get("permission"))
    has_prohibition = bool(policy.get("prohibition"))
    has_obligation = bool(policy.get("obligation"))
    has_duty = any(
        rule.get("duty")
        for rule in _as_list(policy.get("permission"))
        if isinstance(rule, dict)
    )

    if has_permission and has_prohibition:
        return "Permission and prohibition"
    if has_permission and has_duty:
        return "Permission with duty"
    if has_permission:
        return "Permission"
    if has_prohibition:
        return "Prohibition"
    if has_obligation:
        return "Obligation"
    return "Not detected"


def _generated_actions(policy: dict) -> list[str]:
    actions: list[str] = []
    for _, rule in _rules(policy):
        for action in _action_values(rule.get("action")):
            if action not in actions:
                actions.append(action)
        for duty in _as_list(rule.get("duty")):
            if isinstance(duty, dict):
                for action in _action_values(duty.get("action")):
                    if action not in actions:
                        actions.append(action)
    return actions


def _constraint_tuples(rule: dict) -> list[tuple[str, str, str]]:
    constraints: list[tuple[str, str, str]] = []
    for constraint in _as_list(rule.get("constraint")):
        if not isinstance(constraint, dict):
            continue
        left = _local_name(constraint.get("leftOperand"))
        operator = _local_name(constraint.get("operator"))
        right = _semantic_value(
            constraint.get("rightOperand", constraint.get("rightOperandReference")),
            left,
        )
        constraints.append((left.casefold(), operator.casefold(), right))
    return constraints


def _generated_constraint_summary(policy: dict) -> str:
    parts = []
    for _, rule in _rules(policy):
        for left, operator, right in _constraint_tuples(rule):
            value = f"{left} {operator} {right}".strip()
            if value not in parts:
                parts.append(value)
    return ", ".join(parts) if parts else "No constraint detected"


def _compare_expected_rule(expected, rule: dict, label: str) -> list[str]:
    mismatches: list[str] = []

    def compare_party(field: str, expected_value: str | None) -> None:
        generated_values = {_local_name(item).casefold() for item in _as_list(rule.get(field)) if _local_name(item)}
        expected_normalized = expected_value.casefold() if expected_value else None
        if expected_normalized and expected_normalized not in generated_values:
            mismatches.append(f"{label} {field}: expected {expected_value}, generated {', '.join(sorted(generated_values)) or 'not detected'}.")
        if not expected_normalized and generated_values:
            mismatches.append(f"{label} {field}: no value expected, generated {', '.join(sorted(generated_values))}.")
        if expected_normalized and generated_values - {expected_normalized}:
            mismatches.append(f"{label} {field}: unexpected values {', '.join(sorted(generated_values - {expected_normalized}))}.")

    targets = {_local_name(item).casefold() for item in _as_list(rule.get("target")) if _local_name(item)}
    if expected.target.casefold() not in targets:
        mismatches.append(f"{label} target: expected {expected.target}, generated {', '.join(sorted(targets)) or 'not detected'}.")
    if targets - {expected.target.casefold()}:
        mismatches.append(f"{label} target: unexpected values {', '.join(sorted(targets - {expected.target.casefold()}))}.")

    compare_party("assigner", expected.assigner)
    compare_party("assignee", expected.assignee)

    generated_constraints = _constraint_tuples(rule)
    expected_constraints = [
        (
            constraint.left_operand.casefold(),
            constraint.operator.casefold(),
            _semantic_value(constraint.right_operand, constraint.left_operand),
        )
        for constraint in expected.constraints
    ]
    missing_constraints = [item for item in expected_constraints if item not in generated_constraints]
    unexpected_constraints = [item for item in generated_constraints if item not in expected_constraints]
    if missing_constraints:
        mismatches.append(
            f"{label} constraints: missing "
            + ", ".join(" ".join(item) for item in missing_constraints)
            + "."
        )
    if unexpected_constraints:
        mismatches.append(
            f"{label} constraints: unexpected "
            + ", ".join(" ".join(item) for item in unexpected_constraints)
            + "."
        )

    generated_duties = {
        action.casefold()
        for duty in _as_list(rule.get("duty"))
        if isinstance(duty, dict)
        for action in _action_values(duty.get("action"))
    }
    expected_duties = {action.casefold() for action in expected.duty_actions}
    if expected_duties - generated_duties:
        mismatches.append(f"{label} duties: missing {', '.join(sorted(expected_duties - generated_duties))}.")
    if generated_duties - expected_duties:
        mismatches.append(f"{label} duties: unexpected {', '.join(sorted(generated_duties - expected_duties))}.")

    return mismatches


def compare_expected_elements(
    result: EvaluationCaseResult,
    policy: dict,
    case: EvaluationTestCase,
) -> None:
    """Compare the complete deterministic expectation for an evaluation case."""

    result.generated_policy_type = _local_name(policy.get("@type")) or "Not detected"
    result.generated_rule_type = _generated_rule_type(policy)
    result.generated_actions = _generated_actions(policy)
    result.generated_constraint_summary = _generated_constraint_summary(policy)

    mismatches: list[str] = []
    if result.generated_policy_type.casefold() != result.expected_policy_type.casefold():
        mismatches.append(
            f"Policy type: expected {result.expected_policy_type}, generated {result.generated_policy_type}."
        )
    if result.generated_rule_type.casefold() != result.expected_rule_type.casefold():
        mismatches.append(
            f"Rule type: expected {result.expected_rule_type}, generated {result.generated_rule_type}."
        )

    generated_rules = [(kind, rule) for kind, rule in _rules(policy)]
    used: set[int] = set()
    for index, expected in enumerate(case.expected_rules, start=1):
        matching_index = next(
            (
                candidate_index
                for candidate_index, (kind, rule) in enumerate(generated_rules)
                if candidate_index not in used
                and kind.casefold() == expected.kind.casefold()
                and expected.action.casefold() in {action.casefold() for action in _action_values(rule.get("action"))}
            ),
            None,
        )
        label = f"Rule {index} ({expected.kind}/{expected.action})"
        if matching_index is None:
            mismatches.append(f"{label}: expected rule not found.")
            continue
        used.add(matching_index)
        kind, rule = generated_rules[matching_index]
        mismatches.extend(_compare_expected_rule(expected, rule, label))

    unexpected_rules = [
        f"{kind}/{','.join(_action_values(rule.get('action'))) or 'no action'}"
        for index, (kind, rule) in enumerate(generated_rules)
        if index not in used
    ]
    if unexpected_rules:
        mismatches.append(f"Unexpected generated rules: {', '.join(unexpected_rules)}.")

    expected = {action.casefold() for action in result.expected_actions}
    generated = {action.casefold() for action in result.generated_actions}
    missing = [action for action in result.expected_actions if action.casefold() not in generated]
    unexpected = [action for action in result.generated_actions if action.casefold() not in expected]
    if missing:
        mismatches.append(f"Missing expected actions: {', '.join(missing)}.")
    if unexpected:
        mismatches.append(f"Unexpected generated actions: {', '.join(unexpected)}.")

    result.expected_mismatches = list(dict.fromkeys(mismatches))
    result.expected_elements_match = not result.expected_mismatches


