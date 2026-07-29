"""Gradio interface for the ODRL translator prototype."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import gradio as gr

APP_THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="teal",
    neutral_hue="slate",
    radius_size="lg",
    font=[
        gr.themes.GoogleFont("Inter"),
        "Arial",
        "sans-serif",
    ],
)

CUSTOM_CSS = """
    body {
        background: linear-gradient(135deg, #f8fafc, #eef4ff, #f5f3ff);
    }

    .gradio-container {
        max-width: 1200px !important;
        margin: auto !important;
    }

    .main-header {
        padding: 35px 20px;
        margin-bottom: 25px;
        border-radius: 25px;
        text-align: center;
        color: white;
        background: linear-gradient(135deg, #0f172a, #1e40af, #14b8a6);
        box-shadow: 0 18px 45px rgba(37, 99, 235, 0.22);
    }

    .main-header h1 {
        margin: 0 0 8px;
        color: white !important;
        font-size: 44px;
    }

    .main-header p {
        margin: 0;
        color: #e0f2fe !important;
    }

    .info-card,
    .metric-card {
        padding: 18px;
        border: 1px solid #cbd5e1;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.95);
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
    }

    .metric-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 14px;
        margin: 18px 0;
    }

    .metric-label {
        color: #475569;
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
    }

    .metric-value {
        color: #0f172a;
        font-size: 30px;
        font-weight: 800;
    }

    .metric-caption,
    .footer {
        color: #64748b;
        font-size: 13px;
    }

    .footer {
        margin-top: 25px;
        text-align: center;
    }

    .empty-dashboard {
        padding: 24px;
        border: 1px dashed #94a3b8;
        border-radius: 18px;
        text-align: center;
        color: #64748b;
        background: white;
    }

    button {
        border-radius: 12px !important;
        font-weight: 700 !important;
    }

    textarea,
    .cm-editor {
        border-radius: 14px !important;
    }
    """

from app.services.evaluation_service import (
    evaluation_ai_scores_dataframe,
    evaluation_case_choices,
    evaluation_case_detail,
    evaluation_cases_dataframe,
    evaluation_coverage_dataframe,
    evaluation_global_metrics_dataframe,
    evaluation_metrics_cards_html,
    evaluation_policy_type_dataframe,
    evaluation_review_dataframe,
    evaluation_rule_type_dataframe,
)
from app.services.api_client import (
    clear_translation_history,
    load_translation_history,
    run_evaluation as run_evaluation_via_api,
    translate_natural_language_to_odrl,
    translate_to_natural_language,
    validate_odrl_text,
)

AVAILABLE_MODELS = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"]
DEFAULT_GENERATION_MODEL = "gpt-4.1-mini"
DEFAULT_EVALUATOR_MODEL = "gpt-4.1"

EXAMPLE_ODRL_POLICY = """{
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "uid": "http://example.com/policy/ExamplePolicy",
    "permission": [
        {
            "target": "http://example.com/asset/Dataset1",
            "assignee": "http://example.com/party/CompanyA",
            "action": "use",
            "constraint": [
                {
                    "leftOperand": "purpose",
                    "operator": "eq",
                    "rightOperand": "research"
                }
            ]
        }
    ]
}"""


# ---------------------------------------------------------------------------
# Interface callback functions
# ---------------------------------------------------------------------------


def nl_to_odrl_interface(text: str, model: str, repair_enabled: bool):
    """Handle Natural Language → ODRL generation from the first tab."""

    output, validation_message = translate_natural_language_to_odrl(
        text=text,
        model=model,
        repair_enabled=repair_enabled,
    )
    return output, validation_message, load_translation_history()


def odrl_to_nl_interface(policy_text: str, model: str):
    """Handle ODRL → Natural Language generation from the second tab."""

    explanation = translate_to_natural_language(policy_text, model=model)
    return explanation, load_translation_history()


def validate_odrl_text_interface(policy_text: str):
    """Validate pasted ODRL JSON-LD without calling the LLM."""

    return validate_odrl_text(policy_text)


def _json_cell(value) -> str:
    """Serialize nested values safely for a CSV cell."""

    return json.dumps(value, ensure_ascii=False) if value not in (None, "") else ""


def _create_evaluation_exports(
    run_result,
    model: str,
    evaluator_model: str,
    repair_enabled: bool,
    ai_evaluation_enabled: bool,
) -> tuple[str, str]:
    """Create JSON and CSV files from the completed evaluation result."""

    exported_at = datetime.now(timezone.utc).isoformat()
    execution = {
        "exported_at": exported_at,
        "generation_model": model,
        "evaluator_model": evaluator_model if ai_evaluation_enabled else None,
        "repair_enabled": repair_enabled,
        "ai_evaluation_enabled": ai_evaluation_enabled,
        "temperature": 0.0,
        "total_cases": run_result.total_cases,
    }
    result_data = run_result.model_dump(mode="json")
    payload = {
        "execution": execution,
        "summary": {
            key: value
            for key, value in result_data.items()
            if key != "results"
        },
        "results": result_data["results"],
    }

    export_dir = Path(tempfile.gettempdir()) / "odrl_translator_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    json_path = export_dir / f"evaluation_results_{suffix}.json"
    csv_path = export_dir / f"evaluation_results_{suffix}.csv"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    rows = []
    for item in result_data["results"]:
        ai_scores = item.get("ai_scores") or {}
        rows.append(
            {
                "exported_at": exported_at,
                "generation_model": model,
                "evaluator_model": evaluator_model if ai_evaluation_enabled else "",
                "repair_enabled": repair_enabled,
                "ai_evaluation_enabled": ai_evaluation_enabled,
                "case_id": item["id"],
                "input_text": item["input_text"],
                "expected_policy_type": item["expected_policy_type"],
                "expected_rule_type": item["expected_rule_type"],
                "expected_constraint": item["expected_constraint"],
                "expected_actions": _json_cell(item["expected_actions"]),
                "covered_elements": _json_cell(item["covered_elements"]),
                "notes": item["notes"],
                "raw_model_response": item["raw_model_response"],
                "cleaned_model_response": item["cleaned_model_response"],
                "raw_odrl_policy": _json_cell(item["raw_odrl_policy"]),
                "normalized_odrl_policy": _json_cell(item["normalized_odrl_policy"]),
                "repaired_odrl_policy": _json_cell(item["repaired_odrl_policy"]),
                "final_policy_stage": item["final_policy_stage"],
                "final_odrl_policy": _json_cell(item["odrl_policy"]),
                "json_valid": item["json_valid"],
                "initial_basic_valid": item["initial_basic_valid"],
                "initial_shacl_valid": item["initial_shacl_valid"],
                "valid_first_attempt": item["valid_first_attempt"],
                "basic_valid": item["basic_valid"],
                "shacl_valid": item["shacl_valid"],
                "validation_message": item["validation_message"],
                "repair_attempted": item["repair_attempted"],
                "repair_applied": item["repair_applied"],
                "repair_changes": _json_cell(item["repair_changes"]),
                "repair_errors_before": _json_cell(item["repair_errors_before"]),
                "generated_policy_type": item["generated_policy_type"],
                "generated_rule_type": item["generated_rule_type"],
                "generated_actions": _json_cell(item["generated_actions"]),
                "generated_constraint_summary": item["generated_constraint_summary"],
                "expected_elements_match": item["expected_elements_match"],
                "expected_mismatches": _json_cell(item["expected_mismatches"]),
                "odrl_to_nl_explanation": item["odrl_to_nl_explanation"],
                "ai_structural_validity": ai_scores.get("structural_validity", ""),
                "ai_semantic_fidelity": ai_scores.get("semantic_fidelity", ""),
                "ai_completeness": ai_scores.get("completeness", ""),
                "ai_clarity": ai_scores.get("clarity", ""),
                "ai_observations": ai_scores.get("observations", ""),
                "ai_error": item.get("ai_error") or "",
                "error": item.get("error") or "",
            }
        )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return str(json_path), str(csv_path)


def run_evaluation_interface(
    model: str,
    evaluator_model: str,
    repair_enabled: bool,
    ai_evaluation_enabled: bool,
):
    """Run the 20-case evaluation and prepare case details, charts and tables."""

    run_result = run_evaluation_via_api(
        model=model,
        evaluator_model=evaluator_model,
        repair_enabled=repair_enabled,
        ai_evaluation_enabled=ai_evaluation_enabled,
    )

    choices = evaluation_case_choices(run_result)
    first_choice = choices[0] if choices else None
    detail_markdown, detail_policy, detail_explanation, detail_validation = evaluation_case_detail(
        run_result,
        first_choice,
    )

    global_metrics = evaluation_global_metrics_dataframe(run_result)
    rule_type_metrics = evaluation_rule_type_dataframe(run_result)
    policy_type_metrics = evaluation_policy_type_dataframe(run_result)
    coverage_metrics = evaluation_coverage_dataframe(run_result)
    ai_score_metrics = evaluation_ai_scores_dataframe(run_result)
    json_export, csv_export = _create_evaluation_exports(
        run_result,
        model,
        evaluator_model,
        repair_enabled,
        ai_evaluation_enabled,
    )

    return (
        run_result,

        # Evaluation tab: show the first case as soon as the run finishes.
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(choices=choices, value=first_choice, visible=True),
        gr.update(value=detail_markdown, visible=True),
        '<style>#case-output-tabs { display: block !important; }</style>',
        gr.update(value=detail_policy, visible=True),
        gr.update(value=detail_explanation, visible=True),
        gr.update(value=detail_validation, visible=True),

        # Stats tab: reveal cards, charts and generated tables.
        gr.update(visible=False),
        gr.update(value=evaluation_metrics_cards_html(run_result), visible=True),
        gr.update(value=global_metrics, visible=True),
        gr.update(value=rule_type_metrics, visible=True),
        gr.update(value=policy_type_metrics, visible=True),
        gr.update(value=coverage_metrics, visible=True),
        gr.update(value=ai_score_metrics, visible=ai_evaluation_enabled),
        gr.update(value=global_metrics, visible=True),
        gr.update(value=rule_type_metrics, visible=True),
        gr.update(value=policy_type_metrics, visible=True),
        gr.update(value=coverage_metrics, visible=True),
        gr.update(value=ai_score_metrics, visible=ai_evaluation_enabled),
        gr.update(value=evaluation_cases_dataframe(run_result), visible=True),
        gr.update(value=evaluation_review_dataframe(run_result), visible=True),

        # Evaluation exports: available only after the run completes.
        gr.update(value=json_export, visible=True),
        gr.update(value=csv_export, visible=True),
    )


def update_evaluation_case_detail(run_result, selected_case: str):
    """Refresh detail panels when the user selects another evaluation case."""

    return evaluation_case_detail(run_result, selected_case)


# ---------------------------------------------------------------------------
# Small UI factories to avoid repeating Gradio component configuration
# ---------------------------------------------------------------------------


def model_dropdown(label: str, default_model: str = DEFAULT_GENERATION_MODEL) -> gr.Dropdown:
    """Create a model selector with the same options everywhere."""

    return gr.Dropdown(
        label=label,
        choices=AVAILABLE_MODELS,
        value=default_model,
        interactive=True,
    )


def validation_box(label: str = "Validation result") -> gr.Textbox:
    """Create the validation output textbox used in both translation tabs."""

    return gr.Textbox(
        label=label,
        lines=8,
        max_lines=16,
        placeholder="The validation result will appear here...",
    )


# ---------------------------------------------------------------------------
# Gradio application layout
# ---------------------------------------------------------------------------


with gr.Blocks(title="ODRL Translator", theme=APP_THEME, css=CUSTOM_CSS) as demo:
    gr.HTML(
        """
        <div class="main-header">
            <h1>ODRL Translator</h1>
            <p>Bidirectional translation between natural language and ODRL JSON-LD policies</p>
        </div>
        """
    )

    # Introductory cards explaining the two main workflows.
    with gr.Row():
        with gr.Column(scale=1):
            gr.HTML(
                """
                <div class="info-card">
                    <h3>Natural Language → ODRL</h3>
                    <p>
                        Write a policy in plain English and generate a structured ODRL policy
                        serialized as JSON-LD. The generated policy can be validated and
                        automatically repaired if inconsistencies are detected.
                    </p>
                </div>
                """
            )
        with gr.Column(scale=1):
            gr.HTML(
                """
                <div class="info-card">
                    <h3>ODRL → Natural Language</h3>
                    <p>
                        Paste an ODRL JSON-LD policy and obtain a clear natural language
                        explanation of its meaning.
                    </p>
                </div>
                """
            )

    with gr.Tabs():
        # -------------------------------------------------------------------
        # Tab 1: Natural language to ODRL
        # -------------------------------------------------------------------
        with gr.Tab("Natural Language → ODRL"):
            with gr.Row():
                with gr.Column(scale=1):
                    nl_input = gr.Textbox(
                        label="Natural language policy",
                        lines=10,
                        placeholder="Allow CompanyA to use Dataset1 for research purposes.",
                    )
                    nl_model_selector = model_dropdown("LLM model")
                    repair_checkbox = gr.Checkbox(
                        label="Enable automatic repair with LangChain",
                        value=True,
                        interactive=True,
                    )
                    nl_button = gr.Button("Generate ODRL JSON-LD", variant="primary")

                with gr.Column(scale=1):
                    nl_output = gr.Code(
                        label="Generated ODRL JSON-LD",
                        language="json",
                        lines=18,
                    )
                    validation_output = validation_box()

        # -------------------------------------------------------------------
        # Tab 2: ODRL to natural language and manual validation
        # -------------------------------------------------------------------
        with gr.Tab("ODRL → Natural Language"):
            with gr.Row():
                with gr.Column(scale=1):
                    odrl_input = gr.Code(
                        label="ODRL JSON-LD policy",
                        language="json",
                        lines=22,
                        value=EXAMPLE_ODRL_POLICY,
                    )
                    odrl_model_selector = model_dropdown("LLM model")
                    odrl_button = gr.Button("Generate Explanation", variant="primary")
                    validate_odrl_button = gr.Button("Validate ODRL JSON-LD", variant="secondary")

                with gr.Column(scale=1):
                    odrl_output = gr.Textbox(
                        label="Natural language explanation",
                        lines=16,
                        max_lines=22,
                        placeholder="The explanation will appear here...",
                        interactive=False,
                    )
                    odrl_validation_output = validation_box()

        # -------------------------------------------------------------------
        # Tab 3: 20-case evaluation and per-case inspection
        # -------------------------------------------------------------------
        with gr.Tab("Evaluation"):
            evaluation_state = gr.State(value=None)

            with gr.Row():
                with gr.Column(scale=1):
                    evaluation_model_selector = model_dropdown("Generation model")
                    evaluator_model_selector = model_dropdown(
                        "Evaluator model",
                        default_model=DEFAULT_EVALUATOR_MODEL,
                    )
                with gr.Column(scale=1):
                    evaluation_repair_checkbox = gr.Checkbox(
                        label="Enable automatic repair",
                        value=True,
                        interactive=True,
                    )
                    ai_evaluation_checkbox = gr.Checkbox(
                        label="Enable AI evaluator scores",
                        value=False,
                        interactive=True,
                    )
                    evaluation_button = gr.Button("Run 20-case evaluation", variant="primary")

            evaluation_empty_message = gr.HTML(
                value=(
                    '<div class="empty-dashboard">'
                    'Run the evaluation to inspect the cases. Charts and tables will be generated in the Stats tab.'
                    '</div>'
                ),
                visible=True,
            )

            with gr.Row():
                evaluation_json_export = gr.File(
                    label="Evaluation results (JSON)",
                    interactive=False,
                    visible=False,
                )
                evaluation_csv_export = gr.File(
                    label="Evaluation results (CSV)",
                    interactive=False,
                    visible=False,
                )

            case_detail_title = gr.Markdown("### Case detail", visible=False)

            case_selector = gr.Dropdown(
                label="Select a case",
                choices=[],
                interactive=True,
                visible=False,
            )

            case_tabs_visibility_css = gr.HTML(
                value='<style>#case-output-tabs { display: none !important; }</style>'
            )

            with gr.Row():
                with gr.Column(scale=1):
                    case_detail_markdown = gr.Markdown(
                        value="Select a case to inspect it.",
                        label="Case summary",
                        visible=False,
                    )
                with gr.Column(scale=1):
                    with gr.Tabs(elem_id="case-output-tabs"):
                        with gr.Tab("Generated ODRL"):
                            case_policy_code = gr.Code(
                                label="Generated ODRL JSON-LD",
                                language="json",
                                lines=24,
                                visible=False,
                            )
                            case_validation_message = gr.Textbox(
                                label="Validation message",
                                lines=8,
                                max_lines=14,
                                interactive=False,
                                visible=False,
                            )
                        with gr.Tab("ODRL → NL explanation"):
                            case_explanation_text = gr.Textbox(
                                label="Generated explanation",
                                lines=18,
                                max_lines=24,
                                interactive=False,
                                visible=False,
                            )

        # -------------------------------------------------------------------
        # Tab 4: statistics generated by the 20-case evaluation
        # -------------------------------------------------------------------
        with gr.Tab("Stats"):
            stats_empty_message = gr.HTML(
                value=(
                    '<div class="empty-dashboard">'
                    'Run the 20-case evaluation from the Evaluation tab to generate statistics.'
                    '</div>'
                ),
                visible=True,
            )

            evaluation_metrics_html = gr.HTML(label="Key metrics", visible=False)

            gr.Markdown("### Charts")
            with gr.Row():
                global_metrics_plot = gr.BarPlot(
                    label="Global validation results",
                    x="Metric",
                    y="Percentage",
                    y_lim=[0, 100],
                    y_axis_format=".1f",
                    x_title="Metric",
                    y_title="Percentage",
                    x_label_angle=20,
                    height=340,
                    visible=False,
                )
                rule_type_plot = gr.BarPlot(
                    label="SHACL by rule type",
                    x="Type",
                    y="% SHACL",
                    y_lim=[0, 100],
                    y_axis_format=".1f",
                    x_title="Rule type",
                    y_title="Percentage",
                    x_label_angle=20,
                    height=340,
                    visible=False,
                )

            with gr.Row():
                policy_type_plot = gr.BarPlot(
                    label="SHACL by policy type",
                    x="Policy type",
                    y="% SHACL",
                    y_lim=[0, 100],
                    y_axis_format=".1f",
                    x_title="Policy type",
                    y_title="Percentage",
                    height=320,
                    visible=False,
                )
                coverage_plot = gr.BarPlot(
                    label="Expected ODRL subset coverage",
                    x="Expected ODRL element",
                    y="Cases",
                    x_title="Expected ODRL element",
                    y_title="Number of cases",
                    x_label_angle=45,
                    height=360,
                    visible=False,
                )

            ai_scores_plot = gr.BarPlot(
                label="AI evaluator score averages",
                x="Criterion",
                y="Average",
                y_lim=[0, 5],
                y_axis_format=".1f",
                x_title="Criterion",
                y_title="Average score",
                height=320,
                visible=False,
            )

            gr.Markdown("### Generated tables")
            with gr.Tabs():
                with gr.Tab("Global metrics"):
                    global_metrics_table = gr.Dataframe(
                        label="Global metrics",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("By rule type"):
                    rule_type_table = gr.Dataframe(
                        label="Metrics by rule type",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("By policy type"):
                    policy_type_table = gr.Dataframe(
                        label="Metrics by policy type",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("ODRL coverage"):
                    coverage_table = gr.Dataframe(
                        label="Expected ODRL subset coverage",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("AI scores"):
                    ai_scores_table = gr.Dataframe(
                        label="AI evaluator score averages",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("All cases"):
                    cases_table = gr.Dataframe(
                        label="Results for all evaluation cases",
                        interactive=False,
                        visible=False,
                    )
                with gr.Tab("Cases requiring review"):
                    review_table = gr.Dataframe(
                        label="Cases requiring manual review",
                        interactive=False,
                        visible=False,
                    )

        # -------------------------------------------------------------------
        # Tab 5: persistent history provided by the API
        # -------------------------------------------------------------------
        with gr.Tab("Translation History"):
            history_output = gr.Markdown(
                value=load_translation_history(),
                label="Recent translations",
            )
            with gr.Row():
                refresh_history_button = gr.Button("Refresh History", variant="secondary")
                clear_history_button = gr.Button("Clear history", variant="stop")

    # -----------------------------------------------------------------------
    # Event wiring: connects buttons/dropdowns to callback functions.
    # -----------------------------------------------------------------------
    nl_button.click(
        fn=nl_to_odrl_interface,
        inputs=[nl_input, nl_model_selector, repair_checkbox],
        outputs=[nl_output, validation_output, history_output],
    )

    odrl_button.click(
        fn=odrl_to_nl_interface,
        inputs=[odrl_input, odrl_model_selector],
        outputs=[odrl_output, history_output],
    )

    validate_odrl_button.click(
        fn=validate_odrl_text_interface,
        inputs=odrl_input,
        outputs=odrl_validation_output,
    )

    evaluation_button.click(
        fn=run_evaluation_interface,
        inputs=[
            evaluation_model_selector,
            evaluator_model_selector,
            evaluation_repair_checkbox,
            ai_evaluation_checkbox,
        ],
        outputs=[
            evaluation_state,
            evaluation_empty_message,
            case_detail_title,
            case_selector,
            case_detail_markdown,
            case_tabs_visibility_css,
            case_policy_code,
            case_explanation_text,
            case_validation_message,
            stats_empty_message,
            evaluation_metrics_html,
            global_metrics_plot,
            rule_type_plot,
            policy_type_plot,
            coverage_plot,
            ai_scores_plot,
            global_metrics_table,
            rule_type_table,
            policy_type_table,
            coverage_table,
            ai_scores_table,
            cases_table,
            review_table,
            evaluation_json_export,
            evaluation_csv_export,
        ],
    )

    case_selector.change(
        fn=update_evaluation_case_detail,
        inputs=[evaluation_state, case_selector],
        outputs=[
            case_detail_markdown,
            case_policy_code,
            case_explanation_text,
            case_validation_message,
        ],
    )

    refresh_history_button.click(
        fn=load_translation_history,
        inputs=None,
        outputs=history_output,
    )

    clear_history_button.click(
        fn=clear_translation_history,
        inputs=None,
        outputs=history_output,
    )

    gr.HTML(
        """
        <div class="footer">
            <strong>TFM Julio Sánchez-Pajares Aliseda 2026</strong>
            · Prototype developed for semantic policy translation using LLMs, ODRL, JSON-LD, SHACL and LangChain.
        </div>
        """
    )


if __name__ == "__main__":
    demo.launch()