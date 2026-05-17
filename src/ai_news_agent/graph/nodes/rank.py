"""Ranking node for digest workflow (T10c)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ai_news_agent.graph.state import DigestGraphState, WorkflowError
from ai_news_agent.ranking import rank_items


def make_rank_items_node(*, now_provider: Callable[[], datetime] | None = None):
    """Build a node that runs :func:`~ai_news_agent.ranking.rank_items` on collected items."""

    def rank_items_node(state: DigestGraphState) -> dict[str, object]:
        req = state.get("request")
        if req is None:
            return {
                "errors": [
                    WorkflowError(
                        stage="rank", message="missing DigestRequest in state"
                    )
                ]
            }
        items = state.get("collected_items") or []
        if not items:
            return {"ranked_items": []}
        if now_provider is not None:
            ranked = rank_items(items, top_n=req.top_n, now=now_provider())
        else:
            ranked = rank_items(items, top_n=req.top_n)
        return {"ranked_items": ranked}

    return rank_items_node
