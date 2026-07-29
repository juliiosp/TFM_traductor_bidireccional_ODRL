from app.services.normalization_service import (
    atomicize_policy_rules,
    expand_compact_policy,
    infer_policy_type,
    repair_policy_deterministically,
)


def test_infer_policy_types_from_parties() -> None:
    agreement = {"permission": [{"assigner": "a", "assignee": "b"}]}
    offer = {"permission": [{"assigner": "a"}]}
    policy_set = {"permission": [{"assignee": "b"}]}

    assert infer_policy_type(agreement)["@type"] == "Agreement"
    assert infer_policy_type(offer)["@type"] == "Offer"
    assert infer_policy_type(policy_set)["@type"] == "Set"


def test_expand_compact_policy_moves_shared_fields_into_rules() -> None:
    policy = {
        "target": "asset",
        "assignee": "party",
        "permission": [{"action": "use"}],
    }

    expand_compact_policy(policy)

    assert "target" not in policy
    assert "assignee" not in policy
    assert policy["permission"][0]["target"] == "asset"
    assert policy["permission"][0]["assignee"] == "party"


def test_atomicize_rule_values() -> None:
    policy = {
        "permission": [
            {
                "target": ["asset1", "asset2"],
                "action": ["read", "use"],
            }
        ]
    }

    atomicize_policy_rules(policy)

    assert len(policy["permission"]) == 4
    assert all(not isinstance(rule["target"], list) for rule in policy["permission"])
    assert all(not isinstance(rule["action"], list) for rule in policy["permission"])


def test_deterministic_repair_types_count_operand() -> None:
    policy = {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "permission": [
            {
                "target": "http://example.com/asset/A",
                "action": "print",
                "constraint": {
                    "leftOperand": "count",
                    "operator": "lteq",
                    "rightOperand": "5",
                },
            }
        ],
    }

    repaired, changes = repair_policy_deterministically(policy)

    operand = repaired["permission"][0]["constraint"][0]["rightOperand"]
    assert operand == {"@type": "xsd:integer", "@value": "5"}
    assert any("Typed the rightOperand" in change for change in changes)
