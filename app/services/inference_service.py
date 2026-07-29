"""LangChain integration layer.

This module builds the reusable LangChain Expression Language (LCEL) chains
that connect the application with the language model. Each chain follows the
same shape ``prompt -> model -> output parser`` so that every interaction with
the LLM is expressed and composed with LangChain primitives instead of raw API
calls. The model, token budget and response format are selected at invocation
time through LangChain's runtime configuration mechanism (``configurable_fields``),
which lets a single chain serve requests that use different models.
"""

from typing import Any

from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    ConfigurableField,
    Runnable,
    RunnableParallel,
)
from langchain_openai import ChatOpenAI

from app.config import settings
from app.prompts import (
    SYSTEM_PROMPT_NL_TO_ODRL,
    SYSTEM_PROMPT_ODRL_TO_NL,
    SYSTEM_PROMPT_REPAIR_ODRL,
)


# Shared prompt template: a system instruction plus the user payload. Each chain
# fills in its own ``system_prompt`` and receives the ``user_prompt`` at runtime.
_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", "{user_prompt}"),
    ]
)

JSON_RESPONSE_FORMAT = {"type": "json_object"}


def _require_api_key() -> None:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured.")


def build_configurable_model() -> Runnable:
    """Return a ChatOpenAI runnable whose model, token budget and response
    format are configurable at invocation time.

    Exposing these as configurable fields keeps a single reusable runnable while
    still allowing every pipeline step to choose its own model and decoding
    parameters through :func:`llm_config`.
    """

    _require_api_key()

    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.0,
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT,
    ).configurable_fields(
        model_name=ConfigurableField(id="model_name"),
        max_tokens=ConfigurableField(id="max_tokens"),
        model_kwargs=ConfigurableField(id="model_kwargs"),
    )


def llm_config(
    model: str | None,
    max_tokens: int,
    *,
    json_mode: bool,
) -> dict[str, Any]:
    """Build the ``config`` passed to a chain invocation to select the model,
    the token budget and whether the model must return a JSON object."""

    return {
        "configurable": {
            "model_name": model or settings.OPENAI_MODEL,
            "max_tokens": max_tokens,
            "model_kwargs": (
                {"response_format": JSON_RESPONSE_FORMAT} if json_mode else {}
            ),
        }
    }


def _json_generation_chain(system_prompt: str) -> Runnable:
    """Build a ``prompt -> model -> {raw, data}`` LCEL chain.

    ``RunnableParallel`` runs two parsers over the same model output so that the
    chain returns both the raw textual response (kept for traceability) and the
    parsed JSON policy in a single composed expression.
    """

    generation = _PROMPT.partial(system_prompt=system_prompt) | build_configurable_model()

    return generation | RunnableParallel(
        raw=StrOutputParser(),
        data=JsonOutputParser(),
    )


def build_generation_chain() -> Runnable:
    """LCEL chain for natural language -> ODRL JSON-LD generation."""

    return _json_generation_chain(SYSTEM_PROMPT_NL_TO_ODRL)


def build_repair_chain() -> Runnable:
    """LCEL chain for the assisted repair of an invalid ODRL policy."""

    return _json_generation_chain(SYSTEM_PROMPT_REPAIR_ODRL)


def build_explanation_chain() -> Runnable:
    """LCEL chain for ODRL JSON-LD -> natural language explanation."""

    return (
        _PROMPT.partial(system_prompt=SYSTEM_PROMPT_ODRL_TO_NL)
        | build_configurable_model()
        | StrOutputParser()
    )


# ---------------------------------------------------------------------------
# Backwards-compatible helpers.
#
# The chains above supersede the manual request/parse cycle, but these helpers
# are kept so that other modules (for example the AI evaluator) and any external
# code can keep building a plain model or a single call as before.
# ---------------------------------------------------------------------------
def get_langchain_model(
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> ChatOpenAI:
    _require_api_key()

    extra = (
        {"model_kwargs": {"response_format": response_format}}
        if response_format
        else {}
    )

    return ChatOpenAI(
        model=model or settings.OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=settings.OPENAI_API_KEY,
        timeout=timeout or settings.OPENAI_TIMEOUT,
        **extra,
    )