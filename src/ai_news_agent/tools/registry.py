"""Tool registry with dependency injection for Milestone 2 (T4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.connectors import search_bilibili_ai_news, search_github_ai_news
from ai_news_agent.tools.followup import (
    get_digest_item,
    get_ranking_explanation,
    get_source_trace,
    load_latest_digest,
)
from ai_news_agent.tools.schemas import SearchQueryInput, ToolObservation

ConnectorFactory = Callable[[], SourceConnector]

_EMPTY_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}

_RANK_OR_SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rank": {"type": "integer", "minimum": 1},
        "source_id": {"type": "string"},
    },
}

_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "default": 5},
        "timeframe": {"type": "string"},
    },
    "required": ["query"],
}


@dataclass
class ToolDefinition:
    """Stable tool metadata plus an injected async executor."""

    name: str
    description: str
    args_schema: dict[str, Any]
    execute: Callable[..., Any]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")


class ToolRegistry:
    """Lookup table for registered tool definitions."""

    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name!r}")
            self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(name) from exc

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def all_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())


def build_tool_registry(
    *,
    store: DigestStore,
    github_factory: ConnectorFactory,
    bilibili_factory: ConnectorFactory,
) -> ToolRegistry:
    """Assemble tool definitions with injected store and connector factories."""

    async def _load_latest_digest_execute() -> ToolObservation:
        return load_latest_digest(store=store)

    async def _get_digest_item_execute(
        *,
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        return get_digest_item(store=store, rank=rank, source_id=source_id)

    async def _get_source_trace_execute(
        *,
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        from ai_news_agent.connectors.bilibili import BilibiliConnector

        connector = bilibili_factory()
        bilibili = connector if isinstance(connector, BilibiliConnector) else None
        return await get_source_trace(
            store=store,
            rank=rank,
            source_id=source_id,
            bilibili_connector=bilibili,
        )

    async def _get_ranking_explanation_execute(
        *,
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        return get_ranking_explanation(store=store, rank=rank, source_id=source_id)

    async def _search_github_execute(
        *,
        query: str,
        max_results: int = 5,
        timeframe: str | None = None,
    ) -> ToolObservation:
        connector = github_factory()
        return await search_github_ai_news(
            connector=connector,
            search=SearchQueryInput(query=query, max_results=max_results),
            timeframe=timeframe,
        )

    async def _search_bilibili_execute(
        *,
        query: str,
        max_results: int = 5,
        timeframe: str | None = None,
    ) -> ToolObservation:
        connector = bilibili_factory()
        return await search_bilibili_ai_news(
            connector=connector,
            search=SearchQueryInput(query=query, max_results=max_results),
            timeframe=timeframe,
        )

    tools = [
        ToolDefinition(
            name="load_latest_digest",
            description="Load the latest saved digest with topics, entries, and warnings.",
            args_schema=_EMPTY_OBJECT_SCHEMA,
            execute=_load_latest_digest_execute,
        ),
        ToolDefinition(
            name="get_digest_item",
            description="Fetch one digest entry by rank or source_id from the latest digest.",
            args_schema=_RANK_OR_SOURCE_SCHEMA,
            execute=_get_digest_item_execute,
        ),
        ToolDefinition(
            name="get_source_trace",
            description="Show source metadata and connector warnings for a digest item.",
            args_schema=_RANK_OR_SOURCE_SCHEMA,
            execute=_get_source_trace_execute,
        ),
        ToolDefinition(
            name="get_ranking_explanation",
            description="Explain why an item was ranked or selected for the latest digest.",
            args_schema=_RANK_OR_SOURCE_SCHEMA,
            execute=_get_ranking_explanation_execute,
        ),
        ToolDefinition(
            name="search_github_ai_news",
            description="Search GitHub for AI-related repositories through the GitHub connector.",
            args_schema=_SEARCH_SCHEMA,
            execute=_search_github_execute,
        ),
        ToolDefinition(
            name="search_bilibili_ai_news",
            description="Search Bilibili for AI-related videos through the Bilibili connector.",
            args_schema=_SEARCH_SCHEMA,
            execute=_search_bilibili_execute,
        ),
    ]
    return ToolRegistry(tools)
