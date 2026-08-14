"""Tool registry with dependency injection for Milestone 2 (T4)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from langchain_core.tools import BaseTool, tool

from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.env import configure_bilibili_network_from_env, load_local_env
from ai_news_agent.followup_structured import (
    NO_SAVED_DIGEST,
    format_caveats,
    format_rank_item,
    format_ranking_pick,
    format_sources,
)
from ai_news_agent.graph.workflow import run_digest_instrumented
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.connectors import (
    search_bilibili_ai_news as _search_bilibili_ai_news_pure,
    search_github_ai_news as _search_github_ai_news_pure,
    search_juya_ai_news as _search_juya_ai_news_pure,
)
from ai_news_agent.tools.followup import (
    get_digest_item as _get_digest_item_pure,
    get_ranking_explanation as _get_ranking_explanation_pure,
    get_source_trace as _get_source_trace_pure,
    load_latest_digest as _load_latest_digest_pure,
)
from ai_news_agent.tools.schemas import (
    DigestItemRankArgs,
    InterfaceAgentResult,
    InterfaceAgentResultKind,
    RankOrSourceArgs,
    SearchArgs,
    SearchQueryInput,
    ToolObservation,
)

ConnectorFactory = Callable[[], SourceConnector]


def _empty_structured_result() -> InterfaceAgentResult:
    return InterfaceAgentResult(
        kind=InterfaceAgentResultKind.STRUCTURED,
        text=NO_SAVED_DIGEST,
        run_id=None,
    )


def _structured_terminal_result(store: DigestStore, text: str) -> InterfaceAgentResult:
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return _empty_structured_result()
    return InterfaceAgentResult(
        kind=InterfaceAgentResultKind.STRUCTURED,
        text=text,
        run_id=ctx.run_id,
    )


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
    juya_factory: ConnectorFactory,
    digest_request: DigestRequest | None = None,
    register_structured_tools: bool = False,
    connectors: Sequence[SourceConnector] | None = None,
    model: Any = None,
    now_provider: Callable[[], datetime] | None = None,
    on_stage: Callable[[str], None] | None = None,
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

    @tool(args_schema=SearchArgs)
    async def search_juya_ai_news(
        query: str,
        max_results: int = 5,
        timeframe: str | None = None,
    ) -> ToolObservation:
        """Search Juya AI bulletins through the Juya connector."""
        connector = juya_factory()
        return await _search_juya_ai_news_pure(
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
        search_juya_ai_news,
    ]

    include_structured_tools = register_structured_tools or digest_request is not None

    if digest_request is not None:
        digest_invoked = False

        @tool
        async def generate_ai_news_digest() -> InterfaceAgentResult:
            """Generate the AI news digest for this request. Use this for any new digest request."""
            nonlocal digest_invoked
            if digest_invoked:
                raise RuntimeError(
                    "generate_ai_news_digest already invoked for this request"
                )
            digest_invoked = True
            result = await run_digest_instrumented(
                digest_request,
                connectors=connectors or [],
                model=model,
                store=store,
                on_stage=on_stage,
                now_provider=now_provider,
            )
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.DIGEST,
                text=result.text,
                run_id=result.run_id,
                digest=result.digest,
            )

        tools.append(generate_ai_news_digest)

    if include_structured_tools:
        @tool
        async def list_digest_sources() -> InterfaceAgentResult:
            """List source URLs from the latest saved digest."""
            ctx = store.get_latest_followup_context()
            if ctx.run_id is None and ctx.digest is None:
                return _empty_structured_result()
            return _structured_terminal_result(store, format_sources(ctx))

        @tool
        async def recommend_digest_item() -> InterfaceAgentResult:
            """Recommend which digest item to study first based on ranking."""
            ctx = store.get_latest_followup_context()
            if ctx.run_id is None and ctx.digest is None:
                return _empty_structured_result()
            return _structured_terminal_result(store, format_ranking_pick(ctx))

        @tool
        async def list_digest_caveats() -> InterfaceAgentResult:
            """List connector warnings and confidence caveats for the latest digest."""
            ctx = store.get_latest_followup_context()
            if ctx.run_id is None and ctx.digest is None:
                return _empty_structured_result()
            return _structured_terminal_result(store, format_caveats(ctx))

        @tool(args_schema=DigestItemRankArgs)
        async def get_digest_item_by_rank(rank: int) -> InterfaceAgentResult:
            """Show details for one digest item by its 1-based rank."""
            ctx = store.get_latest_followup_context()
            if ctx.run_id is None and ctx.digest is None:
                return _empty_structured_result()
            return _structured_terminal_result(store, format_rank_item(ctx, rank))

        tools.extend(
            [
                list_digest_sources,
                recommend_digest_item,
                list_digest_caveats,
                get_digest_item_by_rank,
            ]
        )

    return ToolRegistry(tools)
