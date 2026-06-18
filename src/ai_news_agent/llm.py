"""OpenAI-compatible chat client for digest summarization (Task 8)."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable

from openai import OpenAI


@runtime_checkable
class ChatModel(Protocol):
    """Protocol for models that return structured digest fields as a dict."""

    def generate_entry_fields(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return keys: summary, why_it_matters, background_knowledge, follow_up_action (str)."""


def build_chat_model(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> ChatModel:
    """Construct a client using env ``OPENAI_*`` when args omitted."""
    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is not set and no api_key was provided")
    url = base_url if base_url is not None else os.environ.get("OPENAI_BASE_URL")
    model_name = model if model is not None else os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=key, base_url=url or None)
    return OpenAIChatModel(client=client, model=model_name)


def build_tool_chat_model(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Any:
    from langchain_openai import ChatOpenAI

    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is not set and no api_key was provided")
    url = base_url if base_url is not None else os.environ.get("OPENAI_BASE_URL")
    model_name = model if model is not None else os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return ChatOpenAI(api_key=key, base_url=url or None, model=model_name)


class OpenAIChatModel:
    """Maps digest context to JSON fields via chat completions."""

    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def generate_entry_fields(self, context: dict[str, Any]) -> dict[str, Any]:
        system = _build_summarization_system_prompt(context)
        user = json.dumps(context, ensure_ascii=False)
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "summary": content[:2000],
                "why_it_matters": "",
                "background_knowledge": "",
                "follow_up_action": "read",
            }


def _build_summarization_system_prompt(context: dict[str, Any]) -> str:
    parts = [
        "You output a single JSON object with keys: "
        "summary, why_it_matters, background_knowledge, follow_up_action. "
        "follow_up_action must be one of: read, watch, try, build. "
        "Stay faithful to the provided evidence; do not invent URLs, dates, or authors.",
    ]
    language = str(context.get("output_language") or "").strip()
    style = str(context.get("output_style") or "").strip()
    if language:
        parts.append(f"Write summary and why_it_matters in {language}.")
    if style == "editorial":
        parts.append(
            "Use concise newsletter tone suitable for a daily briefing section. "
            "Prefer the raw_snippet evidence when present."
        )
    return " ".join(parts)
