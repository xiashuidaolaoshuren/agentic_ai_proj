"""Persist workflow outputs and render digest text (Task T10d)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.graph.state import DigestGraphState, WorkflowError
from ai_news_agent.models import ConnectorWarning, Digest, NewsItem
from ai_news_agent.rendering import render_digest_markdown, render_digest_text
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore


def _connector_names_for_run(
    req: DigestRequest,
    *,
    items: Iterable[NewsItem],
    warnings: Iterable[ConnectorWarning],
) -> list[str]:
    connector_names = req.connector_names
    if connector_names:
        return list(connector_names)

    source_values: set[str] = {item.source.value for item in items}

    connector_ids: set[str] = set()
    for w in warnings:
        connector_ids.add(w.connector)

    connector_ids.discard("")

    return sorted(source_values | connector_ids)


def make_persist_results_node(store: DigestStore):
    """Build a node that writes run metadata, connector output, ranking, and digest."""

    def persist_results_node(state: DigestGraphState) -> dict[str, object]:
        req = state.get("request")
        if req is None:
            return {
                "errors": [
                    WorkflowError(stage="store", message="missing DigestRequest in state")
                ]
            }

        digest = state.get("digest")
        if digest is None:
            return {
                "errors": [WorkflowError(stage="store", message="missing Digest in state")]
            }

        items = list(state.get("collected_items") or [])
        warnings = list(state.get("warnings") or [])
        ranked = list(state.get("ranked_items") or [])

        try:
            run_id = store.save_run(
                requested_at=state.get("started_at"),
                timeframe=req.timeframe,
                topics=list(req.topics),
                connector_names=_connector_names_for_run(req, items=items, warnings=warnings),
            )
            store.save_connector_result(
                run_id,
                ConnectorResult(
                    items=items,
                    warnings=warnings,
                    raw_count=len(items),
                ),
            )
            store.save_ranked_items(run_id, ranked)
            store.save_digest(run_id, digest)
        except Exception as exc:  # noqa: BLE001 - surface as workflow error
            return {
                "errors": [
                    WorkflowError(
                        stage="store",
                        message=f"persistence failed: {type(exc).__name__}",
                        detail=str(exc),
                    )
                ]
            }

        return {"run_id": run_id}

    return persist_results_node


def make_render_digest_node(
    *,
    render_markdown: Callable[[Digest], str] | None = None,
    render_text: Callable[[Digest], str] | None = None,
):
    """Build a node that fills ``markdown`` / ``text`` from the current ``digest``."""

    md_fn = render_markdown or render_digest_markdown
    txt_fn = render_text or render_digest_text

    def render_digest_node(state: DigestGraphState) -> dict[str, object]:
        digest = state.get("digest")
        if digest is None:
            return {
                "errors": [
                    WorkflowError(stage="render", message="missing Digest in state")
                ]
            }
        try:
            return {"markdown": md_fn(digest), "text": txt_fn(digest)}
        except Exception as exc:  # noqa: BLE001 - surface as workflow error
            return {
                "errors": [
                    WorkflowError(
                        stage="render",
                        message=f"digest rendering failed: {type(exc).__name__}",
                        detail=str(exc),
                    )
                ]
            }

    return render_digest_node


__all__ = ["make_persist_results_node", "make_render_digest_node"]
