"""Shared live-mode interface router for Gradio and OpenClaw (Milestone 4 T12)."""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from ai_news_agent.chat import _message_requests_digest
from ai_news_agent.digest_request_builder import resolve_digest_request
from ai_news_agent.followup_structured import (
    NO_SAVED_DIGEST,
    OPENCLAW_GUIDANCE_FALLBACK,
    answer_structured_followup,
    is_structured_followup,
)
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.logging_setup import get_logger
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.agent import ToolAgentRunner, _DEFAULT_FALLBACK, build_tool_agent_runner
from ai_news_agent.tools.registry import ConnectorFactory, build_tool_registry
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
)

logger = get_logger("interface_router")

_OPEN_ENDED_GUIDANCE = (
    "I need a configured language model to answer that question. "
    "Try a concrete request like listing sources or asking for caveats."
)

_UNSAFE_DIGEST_TEXT = (
    "Unable to complete the digest safely after a partial agent run. "
    "Please try again."
)


class _RouteIntent(enum.Enum):
    DIGEST = "digest"
    STRUCTURED_FOLLOWUP = "structured_followup"
    OPEN_ENDED_FOLLOWUP = "open_ended_followup"
    NO_SAVED_DIGEST = "no_saved_digest"


WorkflowRunner = Callable[[DigestRequest], Awaitable[DigestResult]]
StreamingWorkflowRunner = Callable[
    [DigestRequest],
    AsyncIterator[tuple[str, bool, DigestResult | None]],
]
BuildConnectorsFn = Callable[[DigestRequest], Sequence[Any]]


class InterfaceToolRouter:
    """Routes live interface messages through the bounded tool agent with fallback."""

    def __init__(
        self,
        *,
        store: DigestStore,
        workflow_runner: WorkflowRunner,
        streaming_workflow_runner: StreamingWorkflowRunner | None,
        tool_model: Any,
        digest_model: Any,
        github_factory: ConnectorFactory,
        bilibili_factory: ConnectorFactory,
        build_connectors_fn: BuildConnectorsFn,
        now_provider: Callable[[], datetime] | None = None,
        interface_name: str,
        fallback_text: str = _DEFAULT_FALLBACK,
    ) -> None:
        self._store = store
        self._workflow_runner = workflow_runner
        self._streaming_workflow_runner = streaming_workflow_runner
        self._tool_model = tool_model
        self._digest_model = digest_model
        self._github_factory = github_factory
        self._bilibili_factory = bilibili_factory
        self._build_connectors_fn = build_connectors_fn
        self._now_provider = now_provider
        self._interface_name = interface_name
        self._fallback_text = fallback_text

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> InterfaceAgentResult:
        intent, req = self._detect_intent(
            message,
            digest_request=digest_request,
            session_connector_names=session_connector_names,
        )
        logger.info(
            "interface route intent=%s interface=%s correlation_id=%s",
            intent.value,
            self._interface_name,
            correlation_id,
        )

        if intent is _RouteIntent.NO_SAVED_DIGEST:
            return self._with_correlation(
                InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.CONVERSATIONAL,
                    text=NO_SAVED_DIGEST,
                ),
                correlation_id,
            )

        runner = self._build_runner(
            intent=intent,
            digest_request=req,
            on_stage=on_stage,
        )
        try:
            agent_result = await runner.run(message)
        except Exception as exc:
            logger.error(
                "interface agent model_failure interface=%s correlation_id=%s error=%r",
                self._interface_name,
                correlation_id,
                exc,
            )
            return self._with_correlation(
                await self._deterministic_fallback(
                    intent=intent,
                    message=message,
                    digest_request=req,
                    agent_result=None,
                    fallback_reason="model_failure",
                ),
                correlation_id,
            )

        agent_result = self._with_correlation(agent_result, correlation_id)
        if self._agent_result_matches_intent(intent, agent_result):
            self._log_agent_success(intent, agent_result, correlation_id)
            return agent_result

        logger.info(
            "interface agent mismatch intent=%s kind=%s fallback_reason=%s "
            "interface=%s correlation_id=%s",
            intent.value,
            agent_result.kind.value,
            agent_result.fallback_reason,
            self._interface_name,
            correlation_id,
        )
        return await self._deterministic_fallback(
            intent=intent,
            message=message,
            digest_request=req,
            agent_result=agent_result,
            fallback_reason=agent_result.fallback_reason or "agent_mismatch",
        )

    async def route_streaming(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> AsyncIterator[tuple[str, bool, InterfaceAgentResult | None]]:
        intent, req = self._detect_intent(
            message,
            digest_request=digest_request,
            session_connector_names=session_connector_names,
        )

        if intent is _RouteIntent.NO_SAVED_DIGEST:
            yield "", True, self._with_correlation(
                InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.CONVERSATIONAL,
                    text=NO_SAVED_DIGEST,
                ),
                correlation_id,
            )
            return

        runner = self._build_runner(
            intent=intent,
            digest_request=req,
            on_stage=on_stage,
        )
        final_state: InterfaceAgentResult | None = None
        try:
            async for progress, done, payload in runner.run_streaming(message):
                if not done:
                    if progress:
                        yield progress, False, None
                    continue
                final_state = payload
        except Exception as exc:
            logger.error(
                "interface streaming model_failure interface=%s correlation_id=%s error=%r",
                self._interface_name,
                correlation_id,
                exc,
            )
            final_state = await self._deterministic_fallback(
                intent=intent,
                message=message,
                digest_request=req,
                agent_result=None,
                fallback_reason="model_failure",
            )

        if final_state is None:
            final_state = await self._deterministic_fallback(
                intent=intent,
                message=message,
                digest_request=req,
                agent_result=None,
                fallback_reason="iteration_cap_exceeded",
            )
        elif not self._agent_result_matches_intent(intent, final_state):
            final_state = await self._deterministic_fallback(
                intent=intent,
                message=message,
                digest_request=req,
                agent_result=final_state,
                fallback_reason=final_state.fallback_reason or "agent_mismatch",
            )

        yield "", True, self._with_correlation(final_state, correlation_id)

    def _detect_intent(
        self,
        message: str,
        *,
        digest_request: DigestRequest | None,
        session_connector_names: list[str] | None,
    ) -> tuple[_RouteIntent, DigestRequest | None]:
        if digest_request is not None:
            return _RouteIntent.DIGEST, digest_request

        ctx = self._store.get_latest_followup_context()
        has_saved = ctx.run_id is not None or ctx.digest is not None
        if has_saved:
            if is_structured_followup(message):
                return _RouteIntent.STRUCTURED_FOLLOWUP, None
            if _message_requests_digest(message):
                req = resolve_digest_request(
                    message,
                    session_connector_names=session_connector_names,
                )
                return _RouteIntent.DIGEST, req
            return _RouteIntent.OPEN_ENDED_FOLLOWUP, None

        if _message_requests_digest(message):
            req = resolve_digest_request(
                message,
                session_connector_names=session_connector_names,
            )
            return _RouteIntent.DIGEST, req
        return _RouteIntent.NO_SAVED_DIGEST, None

    def _build_runner(
        self,
        *,
        intent: _RouteIntent,
        digest_request: DigestRequest | None,
        on_stage: Callable[[str], None] | None = None,
    ) -> ToolAgentRunner:
        if intent is _RouteIntent.DIGEST:
            assert digest_request is not None
            registry = build_tool_registry(
                store=self._store,
                github_factory=self._github_factory,
                bilibili_factory=self._bilibili_factory,
                digest_request=digest_request,
                connectors=self._build_connectors_fn(digest_request),
                model=self._digest_model,
                now_provider=self._now_provider,
                on_stage=on_stage,
            )
        elif intent is _RouteIntent.STRUCTURED_FOLLOWUP:
            registry = build_tool_registry(
                store=self._store,
                github_factory=self._github_factory,
                bilibili_factory=self._bilibili_factory,
                register_structured_tools=True,
            )
        else:
            registry = build_tool_registry(
                store=self._store,
                github_factory=self._github_factory,
                bilibili_factory=self._bilibili_factory,
            )
        return build_tool_agent_runner(
            registry=registry,
            model=self._tool_model,
            fallback_text=self._fallback_text,
        )

    def _agent_result_matches_intent(
        self,
        intent: _RouteIntent,
        result: InterfaceAgentResult,
    ) -> bool:
        if intent is _RouteIntent.DIGEST:
            return result.kind is InterfaceAgentResultKind.DIGEST
        if intent is _RouteIntent.STRUCTURED_FOLLOWUP:
            return result.kind is InterfaceAgentResultKind.STRUCTURED
        if intent is _RouteIntent.OPEN_ENDED_FOLLOWUP:
            return result.kind is InterfaceAgentResultKind.CONVERSATIONAL
        return False

    async def _deterministic_fallback(
        self,
        *,
        intent: _RouteIntent,
        message: str,
        digest_request: DigestRequest | None,
        agent_result: InterfaceAgentResult | None,
        fallback_reason: str,
    ) -> InterfaceAgentResult:
        logger.info(
            "interface deterministic_fallback intent=%s reason=%s interface=%s",
            intent.value,
            fallback_reason,
            self._interface_name,
        )
        if intent is _RouteIntent.DIGEST:
            if agent_result is not None and (
                agent_result.run_id is not None or agent_result.digest is not None
            ):
                progress_lines = list(agent_result.progress_lines or [])
                return InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.FALLBACK,
                    text=_UNSAFE_DIGEST_TEXT,
                    fallback_reason="unsafe_digest_completion",
                    progress_lines=progress_lines,
                    run_id=agent_result.run_id,
                    digest=agent_result.digest,
                )
            assert digest_request is not None
            digest_result = await self._workflow_runner(digest_request)
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.DIGEST,
                text=digest_result.text,
                run_id=digest_result.run_id,
                digest=digest_result.digest,
            )

        if intent is _RouteIntent.STRUCTURED_FOLLOWUP:
            ctx = self._store.get_latest_followup_context()
            structured = answer_structured_followup(message, ctx)
            if structured is not None:
                return InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.STRUCTURED,
                    text=structured,
                    run_id=ctx.run_id,
                )
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.FALLBACK,
                text=OPENCLAW_GUIDANCE_FALLBACK,
                fallback_reason=fallback_reason,
                run_id=ctx.run_id,
            )

        progress_lines = (
            list(agent_result.progress_lines or []) if agent_result is not None else []
        )
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.FALLBACK,
            text=_OPEN_ENDED_GUIDANCE,
            fallback_reason=fallback_reason,
            progress_lines=progress_lines,
        )

    def _with_correlation(
        self,
        result: InterfaceAgentResult,
        correlation_id: str | None,
    ) -> InterfaceAgentResult:
        if correlation_id is None:
            return result
        return result.model_copy(update={"correlation_id": correlation_id})

    def _log_agent_success(
        self,
        intent: _RouteIntent,
        result: InterfaceAgentResult,
        correlation_id: str | None,
    ) -> None:
        logger.info(
            "interface agent success intent=%s kind=%s run_id=%s interface=%s correlation_id=%s",
            intent.value,
            result.kind.value,
            result.run_id,
            self._interface_name,
            correlation_id,
        )


def build_interface_tool_router(
    *,
    store: DigestStore,
    workflow_runner: WorkflowRunner,
    streaming_workflow_runner: StreamingWorkflowRunner | None = None,
    tool_model: Any,
    digest_model: Any,
    github_factory: ConnectorFactory,
    bilibili_factory: ConnectorFactory,
    build_connectors_fn: BuildConnectorsFn,
    now_provider: Callable[[], datetime] | None = None,
    interface_name: str,
    fallback_text: str = _DEFAULT_FALLBACK,
) -> InterfaceToolRouter:
    """Construct a shared interface router for live Gradio/OpenClaw paths."""
    return InterfaceToolRouter(
        store=store,
        workflow_runner=workflow_runner,
        streaming_workflow_runner=streaming_workflow_runner,
        tool_model=tool_model,
        digest_model=digest_model,
        github_factory=github_factory,
        bilibili_factory=bilibili_factory,
        build_connectors_fn=build_connectors_fn,
        now_provider=now_provider,
        interface_name=interface_name,
        fallback_text=fallback_text,
    )


__all__ = ["InterfaceToolRouter", "build_interface_tool_router"]
