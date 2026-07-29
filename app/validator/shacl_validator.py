"""ODRL JSON-LD validation through RDF and SHACL."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from app.schemas import ValidationIssue


SHAPES_PATH = Path(__file__).parent / "shapes" / "odrl_shapes.ttl"

SH = Namespace("http://www.w3.org/ns/shacl#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")

VALIDATION_ROOT = "urn:odrl-validation:policy"


# Local, deterministic replacement for the remote ODRL context. It contains the
# subset used by this prototype and avoids network access during JSON-LD parsing.
LOCAL_CONTEXT = {
    "@version": 1.1,
    "@vocab": "http://www.w3.org/ns/odrl/2/",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "Policy": "odrl:Policy",
    "Set": "odrl:Set",
    "Offer": "odrl:Offer",
    "Agreement": "odrl:Agreement",
    "Request": "odrl:Request",
    "uid": {"@id": "odrl:uid", "@type": "@id"},
    "profile": {"@id": "odrl:profile", "@type": "@id"},
    "inheritFrom": {"@id": "odrl:inheritFrom", "@type": "@id"},
    "target": {"@id": "odrl:target", "@type": "@id"},
    "assigner": {"@id": "odrl:assigner", "@type": "@id"},
    "assignee": {"@id": "odrl:assignee", "@type": "@id"},
    "permission": {"@id": "odrl:permission", "@container": "@set"},
    "prohibition": {"@id": "odrl:prohibition", "@container": "@set"},
    "obligation": {"@id": "odrl:obligation", "@container": "@set"},
    "conflict": {"@id": "odrl:conflict", "@type": "@vocab"},
    "action": {"@id": "odrl:action", "@type": "@vocab"},
    "constraint": {"@id": "odrl:constraint", "@container": "@set"},
    "refinement": {"@id": "odrl:refinement", "@container": "@set"},
    "duty": {"@id": "odrl:duty", "@container": "@set"},
    "consequence": {"@id": "odrl:consequence", "@container": "@set"},
    "remedy": {"@id": "odrl:remedy", "@container": "@set"},
    "leftOperand": {"@id": "odrl:leftOperand", "@type": "@vocab"},
    "operator": {"@id": "odrl:operator", "@type": "@vocab"},
    "rightOperand": {"@id": "odrl:rightOperand"},
    "rightOperandReference": {
        "@id": "odrl:rightOperandReference",
        "@type": "@id",
    },
    "unit": {"@id": "odrl:unit", "@type": "@id"},
    "dataType": {"@id": "odrl:dataType", "@type": "@id"},
    "status": {"@id": "odrl:status"},
}


RULE_KEYS = ("permission", "prohibition", "obligation")
DUTY_KEYS = ("duty", "remedy", "consequence")


class SHACLExecutionError(RuntimeError):
    """Raised when the SHACL engine cannot execute the validation."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _validation_iri(parts: list[str | int]) -> str:
    suffix = ":".join(str(part) for part in parts)
    return f"urn:odrl-validation:{suffix}"


def _assign_validation_ids(
    owner: dict[str, Any],
    owner_path: str,
    owner_parts: list[str | int],
    path_map: dict[str, str],
) -> None:
    """Add deterministic @id values to embedded nodes in a validation copy.

    The IDs make SHACL focus nodes traceable back to JSON-style paths without
    changing the policy returned to the user.
    """

    for constraint_index, constraint in enumerate(_as_list(owner.get("constraint"))):
        if not isinstance(constraint, dict):
            continue
        parts = [*owner_parts, "constraint", constraint_index]
        iri = _validation_iri(parts)
        constraint.setdefault("@id", iri)
        path_map[iri] = f"{owner_path}.constraint[{constraint_index}]"

    for duty_key in DUTY_KEYS:
        for duty_index, duty in enumerate(_as_list(owner.get(duty_key))):
            if not isinstance(duty, dict):
                continue
            parts = [*owner_parts, duty_key, duty_index]
            iri = _validation_iri(parts)
            duty.setdefault("@id", iri)
            duty_path = f"{owner_path}.{duty_key}[{duty_index}]"
            path_map[iri] = duty_path
            _assign_validation_ids(duty, duty_path, parts, path_map)


def prepare_policy_for_validation(
    policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Create a local-context validation copy and a focus-node path map."""

    validation_policy = deepcopy(policy)
    validation_policy["@context"] = LOCAL_CONTEXT
    validation_policy["@id"] = VALIDATION_ROOT

    path_map = {VALIDATION_ROOT: "$"}

    for rule_key in RULE_KEYS:
        for rule_index, rule in enumerate(_as_list(validation_policy.get(rule_key))):
            if not isinstance(rule, dict):
                continue

            parts: list[str | int] = [rule_key, rule_index]
            iri = _validation_iri(parts)
            rule.setdefault("@id", iri)
            rule_path = f"$.{rule_key}[{rule_index}]"
            path_map[iri] = rule_path
            _assign_validation_ids(rule, rule_path, parts, path_map)

    return validation_policy, path_map


def build_data_graph(
    policy: dict[str, Any],
) -> tuple[Graph, dict[str, str]]:
    """Convert an ODRL JSON-LD policy into an RDF graph without network calls."""

    validation_policy, path_map = prepare_policy_for_validation(policy)

    data_graph = Graph()
    data_graph.parse(
        data=json.dumps(validation_policy, ensure_ascii=False),
        format="json-ld",
    )
    return data_graph, path_map


def _term_text(term: URIRef | BNode | Literal | None) -> str | None:
    if term is None:
        return None
    if isinstance(term, Literal):
        return str(term)
    if isinstance(term, URIRef):
        if term == RDF.type:
            return "@type"

        value = str(term)
        if value.startswith(str(ODRL)):
            return value.removeprefix(str(ODRL))
        if value.startswith(str(SH)):
            return value.removeprefix(str(SH))
        return value
    return str(term)


def _friendly_path(
    focus_node: URIRef | BNode | Literal | None,
    result_path: URIRef | BNode | Literal | None,
    path_map: dict[str, str],
) -> str | None:
    base = path_map.get(str(focus_node)) if focus_node is not None else None
    field = _term_text(result_path)

    if base and field:
        return f"{base}.{field}"
    return base or field


def _extract_issues(
    report_graph: Graph,
    path_map: dict[str, str],
) -> list[ValidationIssue]:
    """Convert the RDF SHACL report into structured application issues."""

    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        focus_node = report_graph.value(result, SH.focusNode)
        result_path = report_graph.value(result, SH.resultPath)
        value = report_graph.value(result, SH.value)
        severity = report_graph.value(result, SH.resultSeverity)
        source_component = report_graph.value(result, SH.sourceConstraintComponent)
        source_shape = report_graph.value(result, SH.sourceShape)

        messages = [str(message) for message in report_graph.objects(result, SH.resultMessage)]
        if not messages:
            messages = ["The RDF graph does not conform to the SHACL shape."]

        path = _friendly_path(focus_node, result_path, path_map)

        for message in messages:
            key = (message, path, _term_text(source_component))
            if key in seen:
                continue
            seen.add(key)

            issues.append(
                ValidationIssue(
                    stage="shacl",
                    message=message,
                    path=path,
                    focus_node=_term_text(focus_node),
                    value=_term_text(value),
                    severity=_term_text(severity),
                    source_constraint=_term_text(source_component),
                    source_shape=_term_text(source_shape),
                )
            )

    # pySHACL may emit a generic sh:NodeConstraintComponent result together
    # with the useful nested result. Hide the wrapper when a more specific
    # issue already points to the same node or to one of its properties.
    filtered: list[ValidationIssue] = []
    for issue in issues:
        is_wrapper = (
            issue.source_constraint == "NodeConstraintComponent"
            and issue.message.startswith("Value does not conform to Shape")
        )
        has_specific_issue = any(
            other is not issue
            and other.source_constraint != "NodeConstraintComponent"
            and issue.path is not None
            and other.path is not None
            and (
                other.path == issue.path
                or other.path.startswith(f"{issue.path}.")
            )
            for other in issues
        )

        if not (is_wrapper and has_specific_issue):
            filtered.append(issue)

    return filtered


def validate_with_shacl(
    policy: dict[str, Any],
) -> tuple[bool, list[ValidationIssue], str]:
    """Validate an ODRL JSON-LD policy against the prototype SHACL profile."""

    try:
        from pyshacl import validate

        data_graph, path_map = build_data_graph(policy)

        shapes_graph = Graph()
        shapes_graph.parse(str(SHAPES_PATH), format="turtle")

        conforms, report_graph, report_text = validate(
            data_graph=data_graph,
            shacl_graph=shapes_graph,
            inference="none",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            advanced=False,
            debug=False,
        )

        issues = _extract_issues(report_graph, path_map)
        return bool(conforms), issues, str(report_text)

    except Exception as error:
        raise SHACLExecutionError(
            f"SHACL validation could not be executed: {error}"
        ) from error
