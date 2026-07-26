"""Tool registry with dependency injection for Milestone 2 (T4)."""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.tools import BaseTool, tool

from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.env import configure_bilibili_network_from_env, load_local_env
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.connectors import (
    search_bilibili_ai_news as _search_bilibili_ai_news_pure,
    search_github_ai_news as _search_github_ai_news_pure,
)
from ai_news_agent.tools.followup import (
    get_digest_item as _get_digest_item_pure,
    get_ranking_explanation as _get_ranking_explanation_pure,
    get_source_trace as _get_source_trace_pure,
    load_latest_digest as _load_latest_digest_pure,
)
from ai_news_agent.tools.schemas import RankOrSourceArgs, SearchArgs, SearchQueryInput, ToolObservation

ConnectorFactory = Callable[[], SourceConnector]


class ToolRegistry:
    """Lookup table for registered LangChain tools."""

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool_entry in tools:
            if tool_entry.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool_entry.name!r}")
            self._tools[tool_entry.name] = tool_entry

    def get_tool(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(name) from exc

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())


def build_tool_registry(
    *,
    store: DigestStore,
    github_factory: ConnectorFactory,
    bilibili_factory: ConnectorFactory,
) -> ToolRegistry:
    """Assemble LangChain tools with injected store and connector factories."""

    @tool
    async def load_latest_digest() -> ToolObservation:
        """Load the latest saved digest with topics, entries, and warnings."""
        return _load_latest_digest_pure(store=store)

    @tool(args_schema=RankOrSourceArgs)
    async def get_digest_item(
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        """Fetch one digest entry by rank or source_id from the latest digest."""
        return _get_digest_item_pure(store=store, rank=rank, source_id=source_id)

    @tool(args_schema=RankOrSourceArgs)
    async def get_source_trace(
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        """Show source metadata and connector warnings for a digest item."""
        from ai_news_agent.connectors.bilibili import BilibiliConnector

        load_local_env(force_reload=True)
        configure_bilibili_network_from_env()
        connector = bilibili_factory()
        bilibili = connector if isinstance(connector, BilibiliConnector) else None
        return await _get_source_trace_pure(
            store=store,
            rank=rank,
            source_id=source_id,
            bilibili_connector=bilibili,
        )

    @tool(args_schema=RankOrSourceArgs)
    async def get_ranking_explanation(
        rank: int | None = None,
        source_id: str | None = None,
    ) -> ToolObservation:
        """Explain why an item was ranked or selected for the latest digest."""
        return _get_ranking_explanation_pure(store=store, rank=rank, source_id=source_id)

    @tool(args_schema=SearchArgs)
    async def search_github_ai_news(
        query: str,
        max_results: int = 5,
        timeframe: str | None = None,
    ) -> ToolObservation:
        """Search GitHub for AI-related repositories through the GitHub connector."""
        connector = github_factory()
        return await _search_github_ai_news_pure(
            connector=connector,
            search=SearchQueryInput(query=query, max_results=max_results),
            timeframe=timeframe,
        )

    @tool(args_schema=SearchArgs)
    async def search_bilibili_ai_news(
        query: str,
        max_results: int = 5,
        timeframe: str | None = None,
    ) -> ToolObservation:
        """Search Bilibili for AI-related videos through the Bilibili connector."""
        load_local_env(force_reload=True)
        configure_bilibili_network_from_env()
        connector = bilibili_factory()
        return await _search_bilibili_ai_news_pure(
            connector=connector,
            search=SearchQueryInput(query=query, max_results=max_results),
            timeframe=timeframe,
        )

    tools = [
        load_latest_digest,
        get_digest_item,
        get_source_trace,
        get_ranking_explanation,
        search_github_ai_news,
        search_bilibili_ai_news,
    ]
    return ToolRegistry(tools)
