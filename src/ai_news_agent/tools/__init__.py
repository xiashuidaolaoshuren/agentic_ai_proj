"""LLM-callable tool layer for Milestone 2 follow-up and connector exploration."""

from __future__ import annotations

from typing import Any

from ai_news_agent.tools.schemas import (
    RankOrSourceArgs,
    SearchArgs,
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
)

__all__ = [
    "RankOrSourceArgs",
    "SearchArgs",
    "SearchQueryInput",
    "ToolObservation",
    "ToolObservationStatus",
    "ToolRegistry",
    "ToolAgentRunner",
    "InterfaceToolRouter",
    "build_interface_tool_router",
    "build_tool_agent_runner",
    "build_tool_registry",
    "get_digest_item",
    "get_ranking_explanation",
    "get_source_trace",
    "load_latest_digest",
    "search_bilibili_ai_news",
    "search_github_ai_news",
    "search_juya_ai_news",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ToolRegistry": ("ai_news_agent.tools.registry", "ToolRegistry"),
    "build_tool_registry": ("ai_news_agent.tools.registry", "build_tool_registry"),
    "ToolAgentRunner": ("ai_news_agent.tools.agent", "ToolAgentRunner"),
    "build_tool_agent_runner": ("ai_news_agent.tools.agent", "build_tool_agent_runner"),
    "InterfaceToolRouter": ("ai_news_agent.tools.interface_router", "InterfaceToolRouter"),
    "build_interface_tool_router": (
        "ai_news_agent.tools.interface_router",
        "build_interface_tool_router",
    ),
    "get_digest_item": ("ai_news_agent.tools.followup", "get_digest_item"),
    "get_ranking_explanation": ("ai_news_agent.tools.followup", "get_ranking_explanation"),
    "get_source_trace": ("ai_news_agent.tools.followup", "get_source_trace"),
    "load_latest_digest": ("ai_news_agent.tools.followup", "load_latest_digest"),
    "search_bilibili_ai_news": ("ai_news_agent.tools.connectors", "search_bilibili_ai_news"),
    "search_github_ai_news": ("ai_news_agent.tools.connectors", "search_github_ai_news"),
    "search_juya_ai_news": ("ai_news_agent.tools.connectors", "search_juya_ai_news"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
