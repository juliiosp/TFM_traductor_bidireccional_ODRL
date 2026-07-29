import json

from app.schemas import ValidationIssue, ValidationResult
from app.validator.json_validator import validate_jsonld_document
from app.validator.shacl_validator import SHACLExecutionError, validate_with_shacl


def validate_policy(policy: dict) -> ValidationResult:
    """Validate a JSON-LD document and then its RDF graph with SHACL."""

    jsonld_valid, errors = validate_jsonld_document(policy)

    if not jsonld_valid:
        return ValidationResult(
            valid=False,
            stage="json",
            message="The input is not a processable ODRL JSON-LD document.",
            issues=[
                ValidationIssue(stage="json", message=error)
                for error in errors
            ],
        )

    try:
        conforms, issues, report = validate_with_shacl(policy)
    except SHACLExecutionError as error:
        return ValidationResult(
            valid=False,
            stage="shacl",
            message="The SHACL validation engine could not execute the validation.",
            issues=[
                ValidationIssue(stage="shacl", message=str(error))
            ],
        )

    if conforms:
        return ValidationResult(
            valid=True,
            stage="complete",
            message="Policy is valid according to JSON-LD and the prototype SHACL profile.",
        )

    return ValidationResult(
        valid=False,
        stage="shacl",
        message="Policy does not conform to the prototype SHACL profile.",
        issues=issues
        or [
            ValidationIssue(
                stage="shacl",
                message="SHACL validation failed without a detailed result.",
            )
        ],
        raw_report=report,
    )


def validate_odrl_text(policy_text: str) -> str:
    """Validate ODRL JSON-LD entered in the interface."""

    if not policy_text.strip():
        return "Please enter an ODRL JSON-LD policy."

    try:
        policy = json.loads(policy_text)
        return validate_policy(policy).to_display_text()

    except json.JSONDecodeError as error:
        return f"❌ The input is not valid JSON: {error.msg}."

    except Exception as error:
        return f"❌ Validation error: {error}"
