"""Follow-up chat service over the latest persisted digest (Task T11)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from ai_news_agent.digest_request_builder import resolve_digest_request
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.logging_setup import get_logger
from ai_news_agent.followup_structured import NO_SAVED_DIGEST, answer_structured_followup
from ai_news_agent.rendering import format_connector_warnings_notice
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore, FollowupContext
from ai_news_agent.streaming import iter_text_chunks
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
)

WorkflowRunner = Callable[[DigestRequest], Awaitable[DigestResult]]
StreamingWorkflowRunner = Callable[
    [DigestRequest],
    AsyncIterator[tuple[str, bool, DigestResult | None]],
]

logger = get_logger("chat")

_StreamPayloadT = TypeVar("_StreamPayloadT")

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
        tool_agent_runner: Any | None = None,
        interface_router: Any | None = None,
    ) -> None:
        self._store = store
        self._workflow_runner = workflow_runner
        self._streaming_workflow_runner = streaming_workflow_runner
        self._chat_model = chat_model
        self._tool_agent_runner = tool_agent_runner
        self._interface_router = interface_router

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

        if self._interface_router is not None:
            result = await self._interface_router.route(
                message=message,
                digest_request=digest_request,
                session_connector_names=session_connector_names,
            )
            return _interface_result_to_text(result, store=self._store)

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
            return _user_facing_digest_text(result)

        return await self._handle_followup_message_async(message)

    async def _handle_followup_message_async(self, message: str) -> str:
        ctx = self._store.get_latest_followup_context()
        if ctx.run_id is None and ctx.digest is None:
            logger.info("follow-up path=no_saved_digest")
            return NO_SAVED_DIGEST

        structured = answer_structured_followup(message, ctx)
        if structured is not None:
            logger.info("follow-up path=structured")
            return structured

        if self._tool_agent_runner is not None:
            logger.info("follow-up path=tool_agent")
            result = await self._tool_agent_runner.run(message)
            return _tool_agent_result_to_text(result, store=self._store)

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

        if self._interface_router is not None:
            async def _router_events() -> AsyncIterator[
                tuple[str, bool, InterfaceAgentResult | None]
            ]:
                async for progress, done, payload in self._interface_router.route_streaming(
                    message=message,
                    digest_request=digest_request,
                    session_connector_names=session_connector_names,
                ):
                    yield progress, done, payload

            async for chunk in _stream_ephemeral_progress_then_chunks(
                _router_events(),
                chunk_size=chunk_size,
                chunk_delay_s=chunk_delay_s,
                extract_final_text=lambda result: _interface_result_to_text(
                    result, store=self._store
                ),
            ):
                yield chunk
            return

        if digest_request is not None or _message_requests_digest(message):
            req = _resolve_digest_request(
                message,
                digest_request=digest_request,
                session_connector_names=session_connector_names,
            )
            if self._streaming_workflow_runner is not None:
                t0 = time.perf_counter()
                final_result: DigestResult | None = None

                async def _digest_events() -> AsyncIterator[
                    tuple[str, bool, DigestResult | None]
                ]:
                    nonlocal final_result
                    async for progress, done, result in self._streaming_workflow_runner(
                        req
                    ):
                        if done and result is not None:
                            final_result = result
                        yield progress, done, result

                async for chunk in _stream_ephemeral_progress_then_chunks(
                    _digest_events(),
                    chunk_size=chunk_size,
                    chunk_delay_s=chunk_delay_s,
                    extract_final_text=_user_facing_digest_text,
                ):
                    yield chunk
                if final_result is not None:
                    _log_digest_result(
                        final_result, elapsed=time.perf_counter() - t0
                    )
                return

            t0 = time.perf_counter()
            result = await self._workflow_runner(req)
            elapsed = time.perf_counter() - t0
            _log_digest_result(result, elapsed=elapsed)
            async for chunk in iter_text_chunks(
                _user_facing_digest_text(result),
                chunk_size=chunk_size,
                delay_s=chunk_delay_s,
            ):
                yield chunk
            return

        if self._tool_agent_runner is not None:
            async for chunk in self._stream_followup_tool_agent_async(
                message,
                chunk_size=chunk_size,
                chunk_delay_s=chunk_delay_s,
            ):
                yield chunk
            return

        text = await self._handle_followup_message_async(message)
        async for chunk in iter_text_chunks(
            text,
            chunk_size=chunk_size,
            delay_s=chunk_delay_s,
        ):
            yield chunk

    async def _stream_followup_tool_agent_async(
        self,
        message: str,
        *,
        chunk_size: int,
        chunk_delay_s: float,
    ) -> AsyncIterator[str]:
        ctx = self._store.get_latest_followup_context()
        if ctx.run_id is None and ctx.digest is None:
            logger.info("follow-up path=no_saved_digest")
            yield NO_SAVED_DIGEST
            return

        structured = answer_structured_followup(message, ctx)
        if structured is not None:
            logger.info("follow-up path=structured")
            async for chunk in iter_text_chunks(
                structured,
                chunk_size=chunk_size,
                delay_s=chunk_delay_s,
            ):
                yield chunk
            return

        logger.info("follow-up path=tool_agent")
        runner = self._tool_agent_runner
        run_streaming = getattr(runner, "run_streaming", None)
        if callable(run_streaming):
            async for chunk in _stream_ephemeral_progress_then_chunks(
                run_streaming(message),
                chunk_size=chunk_size,
                chunk_delay_s=chunk_delay_s,
                extract_final_text=lambda result: _tool_agent_result_to_text(
                    result,
                    store=self._store,
                ),
            ):
                yield chunk
            return

        text = _tool_agent_result_to_text(
            await runner.run(message),
            store=self._store,
        )
        async for chunk in iter_text_chunks(
            text,
            chunk_size=chunk_size,
            delay_s=chunk_delay_s,
        ):
            yield chunk


async def _stream_ephemeral_progress_then_chunks(
    events: AsyncIterator[tuple[str, bool, _StreamPayloadT | None]],
    *,
    chunk_size: int,
    chunk_delay_s: float,
    extract_final_text: Callable[[_StreamPayloadT], str],
) -> AsyncIterator[str]:
    """Yield ephemeral progress lines, then chunked final text without progress."""
    async for progress, done, payload in events:
        if not done:
            if progress:
                yield progress
            continue
        if payload is None:
            continue
        text = extract_final_text(payload)
        async for chunk in iter_text_chunks(
            text,
            chunk_size=chunk_size,
            delay_s=chunk_delay_s,
        ):
            yield chunk


def _tool_agent_result_to_text(result: Any, *, store: DigestStore | None = None) -> str:
    if isinstance(result, InterfaceAgentResult):
        return _interface_result_to_text(result, store=store)
    return str(result)


def _interface_result_to_text(
    result: InterfaceAgentResult,
    *,
    store: DigestStore | None = None,
) -> str:
    if result.kind is InterfaceAgentResultKind.DIGEST:
        warnings: list = []
        errors: list = []
        if store is not None and result.run_id is not None:
            ctx = store.get_latest_followup_context()
            if ctx.run_id == result.run_id:
                warnings = ctx.warnings
        notice = format_connector_warnings_notice(warnings, errors)
        if not notice:
            return result.text
        if notice in result.text:
            return result.text
        return f"{notice}\n\n{result.text}"
    return result.text


def _user_facing_digest_text(result: DigestResult) -> str:
    notice = format_connector_warnings_notice(result.warnings, result.errors)
    if not notice:
        return result.text
    if notice in result.text:
        return result.text
    return f"{notice}\n\n{result.text}"


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
