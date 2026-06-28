"""LangGraph assembly and runner helpers for digest workflow (Task T10e)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.graph.nodes import (
    make_collect_sources_node,
    make_persist_results_node,
    make_rank_items_node,
    make_render_digest_node,
    make_summarize_items_node,
    parse_request_node,
)
from ai_news_agent.graph.state import (
    DigestGraphState,
    DigestResult,
    initial_state,
    state_to_result,
)
from ai_news_agent.models import utcnow
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore

_STAGE_LABELS: dict[str, str] = {
    "parse_request": "Parsing request…",
    "collect_sources": "Collecting from sources…",
    "rank_items": "Ranking candidates…",
    "summarize_items": "Summarizing entries…",
    "persist_results": "Saving run…",
    "render_digest": "Rendering digest…",
}


def _make_finalize_run_node(*, now_provider: Callable[[], datetime] | None = None):
    def finalize_run_node(_: DigestGraphState) -> dict[str, object]:
        ts = now_provider() if now_provider is not None else utcnow()
        return {"finished_at": ts}

    return finalize_run_node


def build_digest_graph(
    *,
    connectors: Sequence[SourceConnector],
    model: Any,
    store: DigestStore,
    now_provider: Callable[[], datetime] | None = None,
):
    """Build the compiled LangGraph digest workflow."""
    builder = StateGraph(DigestGraphState)
    builder.add_node("parse_request", parse_request_node)
    builder.add_node("collect_sources", make_collect_sources_node(connectors))
    builder.add_node("rank_items", make_rank_items_node(now_provider=now_provider))
    builder.add_node("summarize_items", make_summarize_items_node(model))
    builder.add_node("persist_results", make_persist_results_node(store))
    builder.add_node("render_digest", make_render_digest_node())
    builder.add_node("finalize_run", _make_finalize_run_node(now_provider=now_provider))

    builder.add_edge(START, "parse_request")
    builder.add_edge("parse_request", "collect_sources")
    builder.add_edge("collect_sources", "rank_items")
    builder.add_edge("rank_items", "summarize_items")
    builder.add_edge("summarize_items", "persist_results")
    builder.add_edge("persist_results", "render_digest")
    builder.add_edge("render_digest", "finalize_run")
    builder.add_edge("finalize_run", END)

    return builder.compile()


async def run_digest(
    request: DigestRequest,
    *,
    connectors: Sequence[SourceConnector],
    model: Any,
    store: DigestStore,
    now_provider: Callable[[], datetime] | None = None,
) -> DigestResult:
    """Run the full digest graph and return the final user-facing result."""
    graph = build_digest_graph(
        connectors=connectors,
        model=model,
        store=store,
        now_provider=now_provider,
    )
    start_ts = now_provider() if now_provider is not None else utcnow()
    final_state = await graph.ainvoke(initial_state(request, now=start_ts))
    return state_to_result(final_state)


async def run_digest_streaming(
    request: DigestRequest,
    *,
    connectors: Sequence[SourceConnector],
    model: Any,
    store: DigestStore,
    now_provider: Callable[[], datetime] | None = None,
) -> AsyncIterator[tuple[str, bool, DigestResult | None]]:
    """Run the digest graph, yielding progress text then the final result."""
    graph = build_digest_graph(
        connectors=connectors,
        model=model,
        store=store,
        now_provider=now_provider,
    )
    start_ts = now_provider() if now_provider is not None else utcnow()
    seen_nodes: set[str] = set()
    final_state: DigestGraphState | None = None

    async for mode, chunk in graph.astream(
        initial_state(request, now=start_ts),
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            final_state = chunk
            continue
        for node_name in chunk:
            if node_name not in _STAGE_LABELS or node_name in seen_nodes:
                continue
            seen_nodes.add(node_name)
            yield _STAGE_LABELS[node_name], False, None

    if final_state is None:
        return

    result = state_to_result(final_state)
    yield "", True, result


async def run_digest_instrumented(
    request: DigestRequest,
    *,
    connectors: Sequence[SourceConnector],
    model: Any,
    store: DigestStore,
    on_stage: Callable[[str], None] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> DigestResult:
    """Run the digest graph, optionally invoking ``on_stage`` per completed node."""
    graph = build_digest_graph(
        connectors=connectors,
        model=model,
        store=store,
        now_provider=now_provider,
    )
    start_ts = now_provider() if now_provider is not None else utcnow()
    seen_nodes: set[str] = set()
    final_state: DigestGraphState | None = None

    async for mode, chunk in graph.astream(
        initial_state(request, now=start_ts),
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            final_state = chunk
            continue
        if on_stage is None:
            continue
        for node_name in chunk:
            if node_name in seen_nodes:
                continue
            seen_nodes.add(node_name)
            on_stage(node_name)

    if final_state is None:
        raise RuntimeError("digest workflow produced no final state")

    return state_to_result(final_state)


__all__ = [
    "build_digest_graph",
    "run_digest",
    "run_digest_instrumented",
    "run_digest_streaming",
]
