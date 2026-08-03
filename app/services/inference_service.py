"""Calls to the OpenAI chat model through LangChain."""

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings
from app.prompts import (
    SYSTEM_PROMPT_NL_TO_ODRL,
    SYSTEM_PROMPT_ODRL_TO_NL,
    SYSTEM_PROMPT_REPAIR_ODRL,
)

JSON_RESPONSE_FORMAT = {"type": "json_object"}

# Placeholders, not literal text: the system prompts contain JSON examples with
# "{" and "}", so the real values are injected at invoke time instead of being
# formatted into the template itself.
_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", "{user_prompt}"),
    ]
)


def get_langchain_model(
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> ChatOpenAI:
    """Build a ChatOpenAI client configured for one call."""

    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured.")

    extra = {"model_kwargs": {"response_format": response_format}} if response_format else {}

    return ChatOpenAI(
        model=model or settings.OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=settings.OPENAI_API_KEY,
        timeout=timeout or settings.OPENAI_TIMEOUT,
        **extra,
    )


def _ask_model(
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    max_tokens: int,
    json_mode: bool,
) -> str:
    """Send a system/user prompt pair to the model and return the raw text reply."""

    llm = get_langchain_model(
        model=model,
        max_tokens=max_tokens,
        response_format=JSON_RESPONSE_FORMAT if json_mode else None,
    )
    chain = _PROMPT | llm
    response = chain.invoke({"system_prompt": system_prompt, "user_prompt": user_prompt})
    return response.content


def generate_odrl_policy(user_prompt: str, model: str | None, max_tokens: int) -> tuple[str, dict]:
    """Ask the model to translate a natural language policy into ODRL JSON-LD."""

    raw = _ask_model(SYSTEM_PROMPT_NL_TO_ODRL, user_prompt, model, max_tokens, json_mode=True)
    return raw, json_loads(raw, "The generated policy must be a JSON object.")


def repair_odrl_policy(user_prompt: str, model: str | None, max_tokens: int) -> tuple[str, dict]:
    """Ask the model to repair an invalid ODRL JSON-LD policy."""

    raw = _ask_model(SYSTEM_PROMPT_REPAIR_ODRL, user_prompt, model, max_tokens, json_mode=True)
    return raw, json_loads(raw, "The repair response must be a JSON object.")


def explain_odrl_policy(user_prompt: str, model: str | None, max_tokens: int) -> str:
    """Ask the model to explain an ODRL JSON-LD policy in plain language."""

    explanation = _ask_model(SYSTEM_PROMPT_ODRL_TO_NL, user_prompt, model, max_tokens, json_mode=False)
    return explanation.strip() if explanation else explanation


def json_loads(raw: str, error_message: str) -> dict:
    """Parse the model's JSON reply, failing clearly if it is not an object."""

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(error_message)
    return data
