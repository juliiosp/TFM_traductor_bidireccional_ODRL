import json

from app.database import delete_all_translations, get_recent_translations


SUCCESS_STATUSES = {"success", "success_repaired"}


def _format_repair_changes(value: str | None) -> str:
    if not value:
        return ""

    try:
        changes = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return str(value)

    if not isinstance(changes, list):
        return str(changes)

    return "\n".join(f"- {change}" for change in changes)


def format_history_item(item) -> str:
    llm_calls = item.llm_calls or 0
    duration = item.duration_seconds or 0.0

    sections = [
        f"### {item.direction} — {item.status}",
        f"**Date:** {item.created_at}" if item.created_at else "",
        f"**Model:** `{item.model}`" if item.model else "",
    ]

    if llm_calls or duration:
        sections.append(
            "\n\n".join(
                [
                    "#### Monitoring",
                    f"**LLM calls:** {llm_calls}",
                    f"**Total duration:** {duration:.3f} seconds",
                ]
            )
        )

    sections.append(f"**Input:**\n```text\n{item.input_text}\n```")

    if item.status in SUCCESS_STATUSES:
        sections.append(f"**Output:**\n```text\n{item.output_text}\n```")
    else:
        sections.append(f"**Error:**\n```text\n{item.error_message or ''}\n```")

    if item.direction == "NL_TO_ODRL":
        repair = [
            "#### Automatic repair",
            f"**Enabled:** {'Yes' if item.repair_enabled else 'No'}",
            f"**Applied successfully:** {'Yes' if item.repair_applied else 'No'}",
            f"**Attempts performed:** {item.repair_attempts or 0}",
        ]

        if item.repair_stopped_reason:
            repair.append(f"**Final result:** {item.repair_stopped_reason}")

        changes = _format_repair_changes(item.repair_changes)
        if changes:
            repair.append(f"**Changes performed:**\n{changes}")

        sections.append("\n\n".join(repair))

    return "\n\n".join(section for section in sections if section) + "\n\n---"


def format_translation_history(items) -> str:
    """Format translation records for the Gradio history panel."""

    if not items:
        return "No translations have been saved yet."
    return "\n\n".join(format_history_item(item) for item in items)
