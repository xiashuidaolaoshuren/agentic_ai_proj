"""Follow-up chat service over the latest persisted digest (Task T11)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ai_news_agent.digest_request_builder import resolve_digest_request
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.logging_setup import get_logger
from ai_news_agent.models import RankedItem
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore, FollowupContext
from ai_news_agent.streaming import iter_text_chunks

WorkflowRunner = Callable[[DigestRequest], Awaitable[DigestResult]]
StreamingWorkflowRunner = Callable[
    [DigestRequest],
    AsyncIterator[tuple[str, bool, DigestResult | None]],
]

logger = get_logger("chat")

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
        streaming_workflow_runner: StreamingWorkflowRunner | None = None,
        chat_model: Any | None = None,
    ) -> None:
        self._store = store
        self._workflow_runner = workflow_runner
        self._streaming_workflow_runner = streaming_workflow_runner
        self._chat_model = chat_model

    def handle_message(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
    ) -> str:
        """Sync wrapper for UI/CLI callers."""
        return asyncio.run(
            self.handle_message_async(
                message,
                digest_request=digest_request,
                session_connector_names=session_connector_names,
            )
        )

    async def handle_message_async(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
    ) -> str:
        preview = _message_preview(message)
        logger.info("chat message received preview=%r", preview)

        if digest_request is not None or _message_requests_digest(message):
            req = _resolve_digest_request(
                message,
                digest_request=digest_request,
                session_connector_names=session_connector_names,
            )
            t0 = time.perf_counter()
            result = await self._workflow_runner(req)
            elapsed = time.perf_counter() - t0
            _log_digest_result(result, elapsed=elapsed)
            return result.text

        return self._handle_followup_message(message)

    def _handle_followup_message(self, message: str) -> str:
        ctx = self._store.get_latest_followup_context()
        if ctx.run_id is None and ctx.digest is None:
            logger.info("follow-up path=no_saved_digest")
            return _NO_SAVED_DIGEST

        structured = _answer_structured_followup(message, ctx)
        if structured is not None:
            logger.info("follow-up path=structured")
            return structured

        llm_text = _try_llm_followup(self._chat_model, message, ctx)
        if llm_text is not None:
            logger.info("follow-up path=llm")
            return llm_text

        logger.info("follow-up path=guidance_fallback")
        return (
            "I need a configured language model to answer that question. "
            "Try a concrete request like listing sources or asking for caveats."
        )

    async def handle_message_streaming_async(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        chunk_size: int = 80,
        chunk_delay_s: float = 0.02,
    ) -> AsyncIterator[str]:
        preview = _message_preview(message)
        logger.info("chat streaming message received preview=%r", preview)

        if digest_request is not None or _message_requests_digest(message):
            req = _resolve_digest_request(
                message,
                digest_request=digest_request,
                session_connector_names=session_connector_names,
            )
            if self._streaming_workflow_runner is not None:
                t0 = time.perf_counter()
                async for progress, done, result in self._streaming_workflow_runner(req):
                    if not done:
                        if progress:
                            yield progress
                        continue
                    if result is None:
                        continue
                    elapsed = time.perf_counter() - t0
                    _log_digest_result(result, elapsed=elapsed)
                    async for chunk in iter_text_chunks(
                        result.text,
                        chunk_size=chunk_size,
                        delay_s=chunk_delay_s,
                    ):
                        yield chunk
                return

            t0 = time.perf_counter()
            result = await self._workflow_runner(req)
            elapsed = time.perf_counter() - t0
            _log_digest_result(result, elapsed=elapsed)
            async for chunk in iter_text_chunks(
                result.text,
                chunk_size=chunk_size,
                delay_s=chunk_delay_s,
            ):
                yield chunk
            return

        text = self._handle_followup_message(message)
        async for chunk in iter_text_chunks(
            text,
            chunk_size=chunk_size,
            delay_s=chunk_delay_s,
        ):
            yield chunk


def _resolve_digest_request(
    message: str,
    *,
    digest_request: DigestRequest | None,
    session_connector_names: list[str] | None,
) -> DigestRequest:
    if digest_request is not None:
        req = digest_request
        logger.info(
            "digest path=explicit_request topics=%d connector_names=%s",
            len(req.topics),
            req.connector_names,
        )
        return req

    req = resolve_digest_request(message, session_connector_names=session_connector_names)
    logger.info(
        "digest path=resolved_request explicit=%s timeframe=%r connector_names=%s",
        req.has_explicit_selectors(),
        req.timeframe,
        req.connector_names,
    )
    return req


def _log_digest_result(result: DigestResult, *, elapsed: float) -> None:
    logger.info(
        "digest completed run_id=%s entries=%d warnings=%d errors=%d elapsed=%.2fs",
        result.run_id,
        len(result.digest.entries) if result.digest else 0,
        len(result.warnings),
        len(result.errors),
        elapsed,
    )
    if result.warnings:
        for w in result.warnings:
            if w.detail:
                logger.warning(
                    "[%s] %s: %s | detail=%s",
                    w.connector,
                    w.code,
                    w.message,
                    w.detail[:300],
                )
            else:
                logger.warning(
                    "[%s] %s: %s",
                    w.connector,
                    w.code,
                    w.message,
                )
    if result.errors:
        for err in result.errors:
            logger.error(
                "workflow stage=%s: %s",
                err.stage,
                err.message,
            )


def _message_preview(message: str, *, max_len: int = 120) -> str:
    s = " ".join(message.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


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
