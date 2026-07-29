"""Lightweight JSON-LD pre-validation for ODRL policies.

Structural and ODRL model constraints belong to SHACL. This module only checks
conditions that cannot be expressed reliably after JSON-LD has been converted
to RDF, such as the presence of the expected JSON-LD context.
"""

from __future__ import annotations

import json
from typing import Any


ODRL_CONTEXT = "http://www.w3.org/ns/odrl.jsonld"


def _contains_odrl_context(context: Any) -> bool:
    """Return whether a JSON-LD context includes the official ODRL context."""

    if context == ODRL_CONTEXT:
        return True

    if isinstance(context, list):
        return any(_contains_odrl_context(item) for item in context)

    return False


def validate_jsonld_document(policy: object) -> tuple[bool, list[str]]:
    """Validate only the JSON/JSON-LD envelope required before RDF parsing.

    ODRL cardinalities, node kinds, allowed values and policy-type requirements
    are intentionally delegated to the SHACL shapes graph.
    """

    errors: list[str] = []

    if not isinstance(policy, dict):
        return False, ["The policy must be represented as a JSON object."]

    if not _contains_odrl_context(policy.get("@context")):
        errors.append(
            'Missing or invalid @context. The policy must include '
            f'"{ODRL_CONTEXT}".'
        )

    try:
        json.dumps(policy, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        errors.append(f"The policy cannot be serialized as JSON: {error}")

    return len(errors) == 0, errors


# Backward-compatible name used by the existing application.
def validate_basic_odrl(policy: object) -> tuple[bool, list[str]]:
    """Alias for the lightweight JSON-LD envelope validation."""

    return validate_jsonld_document(policy)
