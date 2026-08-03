from copy import deepcopy
from itertools import product
from uuid import uuid4


RULE_KEYS = ("permission", "prohibition", "obligation")
NESTED_KEYS = ("constraint", "duty", "remedy", "consequence")
DUTY_KEYS = ("duty", "remedy", "consequence")
ATOMIC_FIELDS = ("target", "assigner", "assignee", "action")


def ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _listify(container: dict, key: str) -> None:
    if isinstance(container.get(key), dict):
        container[key] = [container[key]]


def normalize_policy(policy: dict) -> dict:
    for rule_key in RULE_KEYS:
        _listify(policy, rule_key)

        rules = policy.get(rule_key)
        if not isinstance(rules, list):
            continue

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            for key in NESTED_KEYS:
                _listify(rule, key)

            for key in DUTY_KEYS:
                for duty in ensure_list(rule.get(key)):
                    if isinstance(duty, dict):
                        _listify(duty, "constraint")

    return policy


def ensure_policy_uid(policy: dict) -> dict:
    policy.setdefault("uid", f"http://example.com/policy/{uuid4()}")
    return policy


def _contains(policy: dict, key: str) -> bool:
    if policy.get(key):
        return True
    return any(
        isinstance(rule, dict) and rule.get(key)
        for rule_key in RULE_KEYS
        for rule in ensure_list(policy.get(rule_key))
    )


def infer_policy_type(policy: dict) -> dict:
    if policy.get("@type"):
        return policy

    has_assigner = _contains(policy, "assigner")
    has_assignee = _contains(policy, "assignee")

    if has_assigner and has_assignee:
        policy["@type"] = "Agreement"
    elif has_assigner:
        policy["@type"] = "Offer"
    else:
        policy["@type"] = "Set"

    return policy


def expand_compact_policy(policy: dict) -> dict:
    """Move policy-level target/assigner/assignee/action into each rule."""

    shared = {key: policy[key] for key in ATOMIC_FIELDS if key in policy}

    for rule_key in RULE_KEYS:
        for rule in ensure_list(policy.get(rule_key)):
            if isinstance(rule, dict):
                for key, value in shared.items():
                    rule.setdefault(key, value)

    for key in shared:
        policy.pop(key)

    return policy


def atomicize_rule(rule: dict) -> list[dict]:
    """Expand a rule with list-valued fields into one rule per combination."""

    values = [ensure_list(rule[field]) if field in rule else [None] for field in ATOMIC_FIELDS]

    atomic_rules = []
    for combination in product(*values):
        atomic_rule = deepcopy(rule)
        for field, value in zip(ATOMIC_FIELDS, combination, strict=True):
            if value is None:
                atomic_rule.pop(field, None)
            else:
                atomic_rule[field] = value
        atomic_rules.append(atomic_rule)

    return atomic_rules


def atomicize_policy_rules(policy: dict) -> dict:
    for rule_key in RULE_KEYS:
        rules = policy.get(rule_key)
        if isinstance(rules, list):
            policy[rule_key] = [
                atomic_rule
                for rule in rules
                if isinstance(rule, dict)
                for atomic_rule in atomicize_rule(rule)
            ]

    return policy


def repair_policy_deterministically(policy: dict) -> tuple[dict, list[str]]:
    changes = []
    missing_uid = not policy.get("uid")
    missing_type = not policy.get("@type")
    compact_fields = [key for key in ATOMIC_FIELDS if key in policy]

    normalize_policy(policy)

    if missing_uid:
        ensure_policy_uid(policy)
        changes.append("Added missing policy uid.")

    if missing_type:
        infer_policy_type(policy)
        changes.append("Inferred missing policy @type.")

    if compact_fields:
        expand_compact_policy(policy)
        changes.append(
            "Expanded compact policy-level properties into each rule: " + ", ".join(compact_fields)
        )

    atomicize_policy_rules(policy)
    normalize_policy(policy)

    changes.extend(coerce_typed_right_operands(policy))

    return policy, changes


def normalize_odrl_policy(policy: dict) -> dict:
    return normalize_policy(policy)


_DATATYPE_SIBLINGS = ("datatype", "dataType")


_TYPED_OPERANDS = {
    "dateTime": "xsd:dateTime",
    "elapsedTime": "xsd:duration",
    "count": "xsd:integer",
}


def _local_name(value) -> str:
    text = str(value or "").strip()
    return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1]


def _iter_constraints(policy: dict):
    for rule_key in RULE_KEYS:
        for rule in ensure_list(policy.get(rule_key)):
            if not isinstance(rule, dict):
                continue
            for constraint in ensure_list(rule.get("constraint")):
                if isinstance(constraint, dict):
                    yield constraint
            for duty_key in DUTY_KEYS:
                for duty in ensure_list(rule.get(duty_key)):
                    if isinstance(duty, dict):
                        for constraint in ensure_list(duty.get("constraint")):
                            if isinstance(constraint, dict):
                                yield constraint


def _coerce_constraint_operand(constraint: dict) -> str | None:
    """Garantiza que un rightOperand tipado por el perfil llegue tipado al grafo RDF.

    El perfil restringe por tipo de dato el operando derecho de las restricciones
    de count, dateTime y elapsedTime. En JSON-LD eso exige un nodo de valor
    @type/@value: un literal simple se interpreta como xsd:string y la restricción
    se rechaza aunque el valor sea correcto. Una propiedad hermana que declare el
    tipo tampoco sirve, porque no tipa el literal.
    """
    left = _local_name(constraint.get("leftOperand"))
    expected_type = _TYPED_OPERANDS.get(left)
    if expected_type is None:
        return None

    stray = [key for key in _DATATYPE_SIBLINGS if key in constraint]
    for key in stray:
        constraint.pop(key)

    value = constraint.get("rightOperand")

    # Ya es un nodo de valor, o no hay operando: solo procedía limpiar la hermana.
    if value is None or isinstance(value, dict):
        return (
            f"Removed stray '{stray[0]}' property from a {left} constraint."
            if stray
            else None
        )

    if left == "count" and isinstance(value, int) and not isinstance(value, bool):
        return None  # JSON-LD ya lo interpreta como xsd:integer.

    text = str(value)
    if left == "dateTime":
        expected_type = "xsd:dateTime" if "T" in text else "xsd:date"

    constraint["rightOperand"] = {"@type": expected_type, "@value": text}
    return f"Typed the rightOperand of a {left} constraint as {expected_type}."


def coerce_typed_right_operands(policy: dict) -> list[str]:
    changes = []
    for constraint in _iter_constraints(policy):
        change = _coerce_constraint_operand(constraint)
        if change:
            changes.append(change)
    return changes