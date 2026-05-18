"""Follow-up chat service over the latest persisted digest (Task T11)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ai_news_agent.graph.state import DigestResult
from ai_news_agent.models import RankedItem
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore, FollowupContext

WorkflowRunner = Callable[[DigestRequest], Awaitable[DigestResult]]

_NO_SAVED_DIGEST = (
    "No saved digest yet. Ask for a digest first "
    '(for example: "Give me today\'s AI digest").'
)


class ChatService:
    """Hybrid routing: digest workflow vs deterministic vs LLM-grounded follow-ups.

    For open-ended follow-ups, pass ``chat_model`` with::

        def generate_followup_reply(self, *, question: str, grounding: dict) -> str: ...

    Grounding is built only from ``DigestStore.get_latest_followup_context()`` data.
    """

    def __init__(
        self,
        *,
        store: DigestStore,
        workflow_runner: WorkflowRunner,
        chat_model: Any | None = None,
    ) -> None:
        self._store = store
        self._workflow_runner = workflow_runner
        self._chat_model = chat_model

    def handle_message(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None = None,
    ) -> str:
        """Sync wrapper for UI/CLI callers."""
        return asyncio.run(self.handle_message_async(message, digest_request=digest_request))

    async def handle_message_async(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None = None,
    ) -> str:
        if digest_request is not None or _message_requests_digest(message):
            req = digest_request if digest_request is not None else DigestRequest()
            result = await self._workflow_runner(req)
            return result.text

        ctx = self._store.get_latest_followup_context()
        if ctx.run_id is None and ctx.digest is None:
            return _NO_SAVED_DIGEST

        structured = _answer_structured_followup(message, ctx)
        if structured is not None:
            return structured

        llm_text = _try_llm_followup(self._chat_model, message, ctx)
        if llm_text is not None:
            return llm_text

        return (
            "I need a configured language model to answer that question. "
            "Try a concrete request like listing sources or asking for caveats."
        )


def _message_requests_digest(message: str) -> bool:
    low = message.strip().lower()
    if not low:
        return False
    triggers = (
        "digest",
        "today's ai",
        "todays ai",
        "give me today's",
        "give me todays",
        "generate digest",
        "run digest",
        "ai digest",
        "news digest",
    )
    return any(t in low for t in triggers)


def _answer_structured_followup(message: str, ctx: FollowupContext) -> str | None:
    low = message.strip().lower()

    if _mentions_sources(low):
        return _format_sources(ctx)

    if _mentions_ranking(low):
        return _format_ranking_pick(ctx)

    if _mentions_caveats(low):
        return _format_caveats(ctx)

    return None


def _mentions_sources(low: str) -> bool:
    keys = ("show sources", "list sources", "original links", "source links", "urls")
    return any(k in low for k in keys)


def _mentions_ranking(low: str) -> bool:
    keys = ("study first", "where should i start", "top pick", "best item", "priority")
    return any(k in low for k in keys)


def _mentions_caveats(low: str) -> bool:
    keys = ("caveat", "warnings", "confidence", "limitations", "issues")
    return any(k in low for k in keys)


def _format_sources(ctx: FollowupContext) -> str:
    if not ctx.digest or not ctx.digest.entries:
        return "No digest entries are available to list sources for."
    lines: list[str] = ["Sources from the latest digest:"]
    for i, e in enumerate(ctx.digest.entries, start=1):
        lines.append(f"{i}. {e.title} — {e.source_url}")
    return "\n".join(lines)


def _format_ranking_pick(ctx: FollowupContext) -> str:
    ranked = ctx.ranked_items
    if not ranked:
        return "No ranking data is available for the latest digest run."

    selected = [r for r in ranked if r.selected]
    pool: list[RankedItem] = selected if selected else ranked
    best = max(pool, key=lambda r: r.score_total)

    why = best.selection_reason or "highest score_total among candidates"
    return (
        f"Suggested starting point: {best.item.title}\n"
        f"- URL: {best.item.url}\n"
        f"- Score: {best.score_total:.3f}\n"
        f"- Reason: {why}"
    )


def _format_caveats(ctx: FollowupContext) -> str:
    lines: list[str] = []

    if ctx.warnings:
        lines.append("Connector warnings:")
        for w in ctx.warnings:
            lines.append(f"- [{w.connector}] {w.code}: {w.message}")

    caveats: list[str] = []
    if ctx.digest:
        for e in ctx.digest.entries:
            if e.confidence_caveat:
                caveats.append(f"- {e.title}: {e.confidence_caveat}")

    if caveats:
        if lines:
            lines.append("")
        lines.append("Per-entry confidence notes:")
        lines.extend(caveats)

    if not lines:
        return "No warnings or confidence caveats were recorded for the latest digest."

    return "\n".join(lines)


def _try_llm_followup(model: Any | None, question: str, ctx: FollowupContext) -> str | None:
    if model is None:
        return None
    fn = getattr(model, "generate_followup_reply", None)
    if fn is None or not callable(fn):
        return None
    grounding = _build_grounding_context(ctx)
    return str(fn(question=question, grounding=grounding))


def _build_grounding_context(ctx: FollowupContext) -> dict[str, Any]:
    out: dict[str, Any] = {
        "run_id": ctx.run_id,
        "warnings": [
            {
                "connector": w.connector,
                "code": w.code,
                "message": w.message,
                "detail": w.detail,
            }
            for w in ctx.warnings
        ],
    }
    if ctx.digest:
        out["digest"] = {
            "topics": ctx.digest.topics,
            "timeframe": ctx.digest.timeframe,
            "generated_at": ctx.digest.generated_at.isoformat(),
            "entries": [
                {
                    "title": e.title,
                    "source_url": e.source_url,
                    "summary": e.summary,
                    "why_it_matters": e.why_it_matters,
                    "confidence_caveat": e.confidence_caveat,
                }
                for e in ctx.digest.entries
            ],
        }
    out["ranked_items"] = [
        {
            "title": r.item.title,
            "url": r.item.url,
            "score_total": r.score_total,
            "selected": r.selected,
            "selection_reason": r.selection_reason,
        }
        for r in ctx.ranked_items
    ]
    out["news_items"] = [
        {
            "title": n.title,
            "url": n.url,
            "source": n.source.value,
            "source_id": n.source_id,
        }
        for n in ctx.news_items
    ]
    return out


__all__ = ["ChatService"]
