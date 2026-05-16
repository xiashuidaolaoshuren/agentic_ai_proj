"""LangGraph workflow state, final result, and helpers (Task T10a).

Propagation rules
-----------------
- Non-fatal connector issues are appended as :class:`~ai_news_agent.models.ConnectorWarning`
  in ``state["warnings"]`` (reducer: concatenate).
- Stage-level problems that should not abort the run are appended as :class:`WorkflowError`
  in ``state["errors"]`` (reducer: concatenate).
- Programmer bugs and unexpected exceptions are raised; the graph driver (T10e) decides
  whether to catch them.
- Empty ``ranked_items`` is valid: summarization can yield a :class:`~ai_news_agent.models.Digest`
  with no entries; rendering still produces output.
- Nodes must not mutate ``state`` in place; they return partial dicts for LangGraph to merge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from operator import add
from typing import Annotated, TypedDict

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.models import ConnectorWarning, Digest, NewsItem, RankedItem, utcnow
from ai_news_agent.request import DigestRequest


@dataclass(frozen=True)
class WorkflowError:
    """Non-fatal workflow stage error surfaced to the UI without stopping the run."""

    stage: str
    message: str
    detail: str | None = None


@dataclass(frozen=True)
class DigestResult:
    """Terminal user-facing output of a digest workflow run."""

    request: DigestRequest
    digest: Digest | None
    run_id: int | None
    markdown: str
    text: str
    ranked_items: list[RankedItem]
    warnings: list[ConnectorWarning]
    errors: list[WorkflowError]
    started_at: datetime
    finished_at: datetime


class DigestGraphState(TypedDict, total=False):
    """LangGraph state for the digest pipeline."""

    request: DigestRequest
    connector_request: ConnectorRequest | None
    started_at: datetime
    finished_at: datetime | None

    collected_items: Annotated[list[NewsItem], add]
    warnings: Annotated[list[ConnectorWarning], add]
    errors: Annotated[list[WorkflowError], add]

    ranked_items: list[RankedItem]
    digest: Digest | None
    run_id: int | None
    markdown: str | None
    text: str | None


def initial_state(request: DigestRequest, *, now: datetime | None = None) -> DigestGraphState:
    """Build starting state with empty list accumulators and ``started_at`` set."""
    ts = now if now is not None else utcnow()
    return {
        "request": request,
        "started_at": ts,
        "finished_at": None,
        "collected_items": [],
        "warnings": [],
        "errors": [],
    }


def state_to_result(state: DigestGraphState) -> DigestResult:
    """Convert terminal graph state into a :class:`DigestResult` for callers."""
    request = state["request"]
    started_at = state["started_at"]
    finished = state.get("finished_at")
    finished_at = finished if finished is not None else started_at

    digest = state.get("digest")
    run_id = state.get("run_id")
    markdown = state.get("markdown") or ""
    text = state.get("text") or ""

    ranked_items = list(state.get("ranked_items") or [])
    warnings = list(state.get("warnings") or [])
    errors = list(state.get("errors") or [])

    return DigestResult(
        request=request,
        digest=digest,
        run_id=run_id,
        markdown=markdown,
        text=text,
        ranked_items=ranked_items,
        warnings=warnings,
        errors=errors,
        started_at=started_at,
        finished_at=finished_at,
    )


__all__ = [
    "DigestGraphState",
    "DigestResult",
    "WorkflowError",
    "initial_state",
    "state_to_result",
]
