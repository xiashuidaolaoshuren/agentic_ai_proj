"""LLM-callable tool layer for Milestone 2 follow-up and connector exploration."""

from __future__ import annotations

from typing import Any

from ai_news_agent.tools.followup import (
    get_digest_item,
    get_ranking_explanation,
    get_source_trace,
    load_latest_digest,
)
from ai_news_agent.tools.schemas import (
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
    encode_tool_value,
    tool_observation_to_dict,
)

__all__ = [
    "SearchQueryInput",
    "ToolObservation",
    "ToolObservationStatus",
    "build_tool_registry",
    "encode_tool_value",
    "get_digest_item",
    "get_ranking_explanation",
    "get_source_trace",
    "load_latest_digest",
    "tool_observation_to_dict",
]


def build_tool_registry(*args: Any, **kwargs: Any) -> Any:
    """Assemble tool definitions with injected dependencies (implemented in T4)."""
    raise NotImplementedError("build_tool_registry is implemented in Milestone 2 T4")
