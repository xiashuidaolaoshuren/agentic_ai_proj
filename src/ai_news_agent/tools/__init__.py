"""LLM-callable tool layer for Milestone 2 follow-up and connector exploration."""

from __future__ import annotations

from ai_news_agent.tools.agent import ToolAgentRunner, build_tool_agent_runner
from ai_news_agent.tools.connectors import search_bilibili_ai_news, search_github_ai_news
from ai_news_agent.tools.followup import (
    get_digest_item,
    get_ranking_explanation,
    get_source_trace,
    load_latest_digest,
)
from ai_news_agent.tools.registry import ToolDefinition, ToolRegistry, build_tool_registry
from ai_news_agent.tools.schemas import (
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
    encode_tool_value,
    tool_observation_to_dict,
)

__all__ = [
    "SearchQueryInput",
    "ToolDefinition",
    "ToolObservation",
    "ToolObservationStatus",
    "ToolRegistry",
    "ToolAgentRunner",
    "build_tool_agent_runner",
    "build_tool_registry",
    "encode_tool_value",
    "get_digest_item",
    "get_ranking_explanation",
    "get_source_trace",
    "load_latest_digest",
    "search_bilibili_ai_news",
    "search_github_ai_news",
    "tool_observation_to_dict",
]
