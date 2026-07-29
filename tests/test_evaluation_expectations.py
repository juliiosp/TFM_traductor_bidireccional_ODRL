from app.evaluation.test_cases import DEFAULT_EVALUATION_CASES
from app.evaluation.expectations import compare_expected_elements
from app.schemas import EvaluationCaseResult


def _case(case_id: str):
    return next(case for case in DEFAULT_EVALUATION_CASES if case.id == case_id)


def test_deterministic_expectation_accepts_complete_rule() -> None:
    case = _case("P09")
    policy = {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "@type": "Set",
        "uid": "http://example.com/policy/Test",
        "permission": [
            {
                "target": "http://example.com/asset/Document2",
                "assignee": "http://example.com/party/CompanyF",
                "action": "print",
                "constraint": [
                    {
                        "leftOperand": "count",
                        "operator": "lt",
                        "rightOperand": {"@type": "xsd:integer", "@value": 5},
                    }
                ],
            }
        ],
    }
    result = EvaluationCaseResult(
        id=case.id,
        input_text=case.natural_language,
        expected_rule_type=case.rule_type,
        expected_constraint=case.main_constraint,
        expected_policy_type=case.policy_type,
        expected_actions=case.expected_actions,
        covered_elements=case.covered_elements,
    )

    compare_expected_elements(result, policy, case)

    assert result.expected_elements_match
    assert result.expected_mismatches == []


def test_deterministic_expectation_rejects_wrong_constraint() -> None:
    case = _case("P09")
    policy = {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "@type": "Set",
        "uid": "http://example.com/policy/Test",
        "permission": [
            {
                "target": "http://example.com/asset/Document2",
                "assignee": "http://example.com/party/CompanyF",
                "action": "print",
                "constraint": [
                    {
                        "leftOperand": "purpose",
                        "operator": "eq",
                        "rightOperand": "research",
                    }
                ],
            }
        ],
    }
    result = EvaluationCaseResult(
        id=case.id,
        input_text=case.natural_language,
        expected_rule_type=case.rule_type,
        expected_constraint=case.main_constraint,
        expected_policy_type=case.policy_type,
        expected_actions=case.expected_actions,
        covered_elements=case.covered_elements,
    )

    compare_expected_elements(result, policy, case)

    assert not result.expected_elements_match
    assert any("constraints" in mismatch for mismatch in result.expected_mismatches)


def test_deterministic_expectation_checks_each_mixed_rule() -> None:
    case = _case("P18")
    policy = {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "@type": "Agreement",
        "uid": "http://example.com/policy/Test",
        "permission": [
            {
                "target": "http://example.com/asset/Dataset11",
                "assigner": "http://example.com/party/DataProviderE",
                "assignee": "http://example.com/party/CompanyM",
                "action": "read",
            }
        ],
        "prohibition": [
            {
                "target": "http://example.com/asset/WrongDataset",
                "assigner": "http://example.com/party/DataProviderE",
                "assignee": "http://example.com/party/CompanyM",
                "action": "distribute",
            }
        ],
    }
    result = EvaluationCaseResult(
        id=case.id,
        input_text=case.natural_language,
        expected_rule_type=case.rule_type,
        expected_constraint=case.main_constraint,
        expected_policy_type=case.policy_type,
        expected_actions=case.expected_actions,
        covered_elements=case.covered_elements,
    )

    compare_expected_elements(result, policy, case)

    assert not result.expected_elements_match
    assert any("target" in mismatch for mismatch in result.expected_mismatches)
