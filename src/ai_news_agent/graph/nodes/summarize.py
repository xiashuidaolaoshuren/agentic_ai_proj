"""Summarization node for digest workflow (T10c)."""

from __future__ import annotations

from typing import Any

from ai_news_agent.graph.state import DigestGraphState, WorkflowError
from ai_news_agent.summarizer import summarize_ranked_items


def make_summarize_items_node(model: Any):
    """Build a node that runs :func:`~ai_news_agent.summarizer.summarize_ranked_items`."""

    def summarize_items_node(state: DigestGraphState) -> dict[str, object]:
        req = state.get("request")
        if req is None:
            return {
                "errors": [
                    WorkflowError(
                        stage="summarize", message="missing DigestRequest in state"
                    )
                ]
            }
        ranked = state.get("ranked_items") or []
        try:
            digest = summarize_ranked_items(
                ranked,
                topics=req.topics,
                timeframe=req.timeframe,
                generated_at=state.get("finished_at") or state.get("started_at"),
                primary_source=req.primary_source,
                model=model,
                output_style=req.output_style,
                output_language=req.output_language,
            )
        except Exception as exc:
            return {
                "errors": [
                    WorkflowError(
                        stage="summarize",
                        message=f"summarization failed: {type(exc).__name__}",
                        detail=str(exc),
                    )
                ]
            }
        return {"digest": digest}

    return summarize_items_node
