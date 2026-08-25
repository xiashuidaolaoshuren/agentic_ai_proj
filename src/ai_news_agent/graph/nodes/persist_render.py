"""Persist workflow outputs and render digest text (Task T10d)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.graph.state import DigestGraphState, WorkflowError
from ai_news_agent.models import ConnectorWarning, Digest, NewsItem
from ai_news_agent.rendering import (
    render_digest_editorial_markdown,
    render_digest_editorial_text,
    render_digest_markdown,
    render_digest_text,
)
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import resolve_connector_names
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

    return resolve_connector_names(req.connector_names)


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

    md_default = render_markdown or render_digest_markdown
    txt_default = render_text or render_digest_text

    def render_digest_node(state: DigestGraphState) -> dict[str, object]:
        digest = state.get("digest")
        if digest is None:
            return {
                "errors": [
                    WorkflowError(stage="render", message="missing Digest in state")
                ]
            }
        req = state.get("request")
        style = req.output_style if req is not None else None
        language = req.output_language if req is not None else None
        warnings = list(state.get("warnings") or [])
        news_items = list(state.get("collected_items") or [])
        try:
            if render_markdown is not None:
                markdown = render_markdown(digest, warnings=warnings)
            elif style == "editorial":
                markdown = render_digest_editorial_markdown(
                    digest,
                    warnings=warnings,
                    output_language=language,
                )
            else:
                markdown = md_default(digest, warnings=warnings, news_items=news_items)

            if render_text is not None:
                text = render_text(digest, warnings=warnings)
            elif style == "editorial":
                text = render_digest_editorial_text(
                    digest,
                    warnings=warnings,
                    output_language=language,
                )
            else:
                text = txt_default(digest, warnings=warnings, news_items=news_items)

            return {"markdown": markdown, "text": text}
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
