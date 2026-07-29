from app.services.normalization_service import normalize_policy
from app.validator import validate_policy


def _valid_policy() -> dict:
    return {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "@type": "Set",
        "uid": "http://example.com/policy/TestPolicy",
        "permission": [
            {
                "target": "http://example.com/asset/Dataset1",
                "assignee": "http://example.com/party/CompanyA",
                "action": "use",
            }
        ],
    }


def test_normalizer_converts_rule_to_list() -> None:
    policy = _valid_policy()
    policy["permission"] = policy["permission"][0]

    normalized = normalize_policy(policy)

    assert isinstance(normalized["permission"], list)
    assert len(normalized["permission"]) == 1


def test_minimal_policy_passes_validation() -> None:
    result = validate_policy(_valid_policy())

    assert result.valid, result.to_display_text()


def test_policy_without_action_fails_shacl() -> None:
    policy = _valid_policy()
    policy["permission"][0].pop("action")

    result = validate_policy(policy)

    assert not result.valid
    assert result.stage == "shacl"
    assert any(issue.path and issue.path.endswith(".action") for issue in result.issues)


def test_missing_odrl_context_fails_before_shacl() -> None:
    policy = _valid_policy()
    policy.pop("@context")

    result = validate_policy(policy)

    assert not result.valid
    assert result.stage == "json"
