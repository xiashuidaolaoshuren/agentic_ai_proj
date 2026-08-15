"""Tests for Milestone 4 shared interface tool router (Task T12)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from ai_news_agent.followup_structured import NO_SAVED_DIGEST, OPENCLAW_GUIDANCE_FALLBACK, format_sources
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.models import Digest
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.agent import build_tool_agent_runner
from ai_news_agent.tools.registry import ToolRegistry, build_tool_registry
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
    ToolObservation,
    ToolObservationStatus,
)
from test_tools_followup import _seed_full_followup_store


class _FakeToolCallModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools: Any) -> "_FakeToolCallModel":
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        msg = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return msg


def _noop_factories() -> tuple[Any, Any, Any]:
    def _factory() -> Any:
        raise AssertionError("connector factory should not run")

    return _factory, _factory, _factory


def _build_router(
    tmp_path: Path,
    *,
    store: DigestStore | None = None,
    workflow_runner: Any | None = None,
    streaming_workflow_runner: Any | None = None,
    tool_model: Any | None = None,
    digest_model: Any = object(),
) -> Any:
    from ai_news_agent.tools.interface_router import build_interface_tool_router

    if store is None:
        store = DigestStore(tmp_path / "router.db")
        store.init_schema()
    gh, bh, jh = _noop_factories()

    async def _default_workflow(
        _req: DigestRequest,
        _on_stage=None,
    ) -> DigestResult:
        raise AssertionError("workflow_runner should not run")

    return build_interface_tool_router(
        store=store,
        workflow_runner=workflow_runner or _default_workflow,
        streaming_workflow_runner=streaming_workflow_runner,
        tool_model=tool_model or _FakeToolCallModel([AIMessage(content="unused")]),
        digest_model=digest_model,
        github_factory=gh,
        bilibili_factory=bh,
        juya_factory=jh,
        build_connectors_fn=lambda _req: [],
        interface_name="test",
    )


def test_route_digest_request_returns_digest_from_agent(tmp_path: Path) -> None:
    from ai_news_agent.tools.interface_router import InterfaceToolRouter

    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=7,
        markdown="# Digest",
        text="Digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-digest",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("deterministic digest must not run on happy path")

    router = _build_router(tmp_path, workflow_runner=_workflow, tool_model=model)

    with patch(
        "ai_news_agent.tools.registry.run_digest_instrumented",
        AsyncMock(return_value=digest_result),
    ):
        result = asyncio.run(
            router.route(
                message="Generate today's digest.",
                digest_request=trusted_request,
                correlation_id="corr-7",
            )
        )

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.text == "Digest text"
    assert result.run_id == 7
    assert result.digest == digest
    assert result.correlation_id == "corr-7"
    assert model._index == 1


def test_route_passes_on_stage_to_registry(tmp_path: Path) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    registry_calls: list[dict[str, object]] = []
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=7,
        markdown="# Digest",
        text="Digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )

    def on_stage(stage: str) -> None:
        del stage

    def spy_build_tool_registry(**kwargs: object):
        registry_calls.append(kwargs)
        return build_tool_registry(**kwargs)

    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-digest",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("workflow must not run")

    router = _build_router(tmp_path, workflow_runner=_workflow, tool_model=model)

    with patch(
        "ai_news_agent.tools.interface_router.build_tool_registry",
        spy_build_tool_registry,
    ), patch(
        "ai_news_agent.tools.registry.run_digest_instrumented",
        AsyncMock(return_value=digest_result),
    ):
        asyncio.run(
            router.route(
                message="Generate digest.",
                digest_request=trusted_request,
                on_stage=on_stage,
            )
        )

    assert len(registry_calls) == 1
    assert registry_calls[0]["on_stage"] is on_stage


def test_interface_router_forwards_juya_factory(tmp_path: Path) -> None:
    from ai_news_agent.tools.interface_router import build_interface_tool_router

    trusted_request = DigestRequest(topics=["AI agents"])
    registry_calls: list[dict[str, object]] = []
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=7,
        markdown="# Digest",
        text="Digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )

    def spy_build_tool_registry(**kwargs: object):
        registry_calls.append(kwargs)
        return build_tool_registry(**kwargs)

    gh, bh, juya_factory = _noop_factories()
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-digest",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("workflow must not run")

    router = build_interface_tool_router(
        store=DigestStore(tmp_path / "juya-factory-router.db"),
        workflow_runner=_workflow,
        streaming_workflow_runner=None,
        tool_model=model,
        digest_model=object(),
        github_factory=gh,
        bilibili_factory=bh,
        juya_factory=juya_factory,
        build_connectors_fn=lambda _req: [],
        interface_name="test",
    )
    router._store.init_schema()

    with patch(
        "ai_news_agent.tools.interface_router.build_tool_registry",
        spy_build_tool_registry,
    ), patch(
        "ai_news_agent.tools.registry.run_digest_instrumented",
        AsyncMock(return_value=digest_result),
    ):
        asyncio.run(
            router.route(
                message="Generate digest.",
                digest_request=trusted_request,
            )
        )

    assert len(registry_calls) == 1
    assert registry_calls[0]["juya_factory"] is juya_factory


def test_intent_precedence_structured_wins_over_digest_keyword(tmp_path: Path) -> None:
    store, _run_id = _seed_full_followup_store(tmp_path)
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_digest_item_by_rank",
                        "args": {"rank": 1},
                        "id": "call-rank",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )
    workflow_calls: list[DigestRequest] = []

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(req)
        raise AssertionError("digest workflow must not run")

    router = _build_router(
        tmp_path,
        store=store,
        workflow_runner=_workflow,
        tool_model=model,
    )

    with patch(
        "ai_news_agent.tools.interface_router.answer_structured_followup",
        side_effect=AssertionError("must not call during intent detection"),
    ):
        result = asyncio.run(
            router.route(message="Digest the first news.")
        )

    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert model._index == 1
    assert workflow_calls == []


def test_digest_agent_fallback_runs_deterministic_workflow(tmp_path: Path) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=9,
        markdown="# Digest",
        text="Fallback digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    model = _FakeToolCallModel([AIMessage(content="Direct answer without tools.")])
    workflow_calls: list[DigestRequest] = []

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(req)
        return digest_result

    router = _build_router(tmp_path, workflow_runner=_workflow, tool_model=model)

    result = asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.text == "Fallback digest text"
    assert result.run_id == 9
    assert len(workflow_calls) == 1
    assert workflow_calls[0] is trusted_request


def test_digest_agent_fallback_with_run_id_does_not_rerun_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    workflow_calls: list[DigestRequest] = []

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(req)
        raise AssertionError("workflow must not run")

    class _FallbackRunner:
        async def run(self, _message: str) -> InterfaceAgentResult:
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.FALLBACK,
                text="Stopped after cap.",
                fallback_reason="iteration_cap_exceeded",
                run_id=7,
            )

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.build_tool_agent_runner",
        lambda **_kwargs: _FallbackRunner(),
    )
    router = _build_router(tmp_path, workflow_runner=_workflow)

    result = asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert result.kind == InterfaceAgentResultKind.FALLBACK
    assert result.fallback_reason == "unsafe_digest_completion"
    assert result.run_id == 7
    assert workflow_calls == []


def test_route_allow_digest_false_skips_digest_intent(tmp_path: Path) -> None:
    store, _run_id = _seed_full_followup_store(tmp_path)
    workflow_calls: list[DigestRequest] = []

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(_req)
        raise AssertionError("workflow must not run")

    router = _build_router(tmp_path, store=store, workflow_runner=_workflow)

    result = asyncio.run(
        router.route(
            message="generate a digest about AI",
            allow_digest=False,
        )
    )

    assert result.kind == InterfaceAgentResultKind.FALLBACK
    assert result.text == OPENCLAW_GUIDANCE_FALLBACK
    assert result.fallback_reason == "digest_not_allowed_on_followup"
    assert workflow_calls == []


def test_digest_mismatch_structured_result_reruns_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=11,
        markdown="# Fallback digest",
        text="Fallback digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    workflow_calls: list[DigestRequest] = []

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(req)
        return digest_result

    class _StructuredRunner:
        async def run(self, _message: str) -> InterfaceAgentResult:
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.STRUCTURED,
                text="Sources: https://example.com/r1",
                run_id=7,
            )

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.build_tool_agent_runner",
        lambda **_kwargs: _StructuredRunner(),
    )
    router = _build_router(tmp_path, workflow_runner=_workflow)

    result = asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.text == "Fallback digest text"
    assert result.run_id == 11
    assert len(workflow_calls) == 1
    assert workflow_calls[0] is trusted_request


class _FakeConnector:
    def __init__(self, closed: list[str], name: str) -> None:
        self._closed = closed
        self._name = name

    async def aclose(self) -> None:
        self._closed.append(self._name)


def test_route_digest_closes_connectors_after_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    closed: list[str] = []

    class _DigestRunner:
        async def run(self, _message: str) -> InterfaceAgentResult:
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.DIGEST,
                text="Digest text",
                run_id=7,
            )

    async def _unused_workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("unused")

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.build_tool_agent_runner",
        lambda **_kwargs: _DigestRunner(),
    )
    router = _build_router(
        tmp_path,
        workflow_runner=_unused_workflow,
    )
    router._build_connectors_fn = lambda _req: [_FakeConnector(closed, "github")]

    asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert closed == ["github"]


def test_route_digest_closes_connectors_on_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    closed: list[str] = []
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=11,
        markdown="# Fallback digest",
        text="Fallback digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        return digest_result

    class _StructuredRunner:
        async def run(self, _message: str) -> InterfaceAgentResult:
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.STRUCTURED,
                text="Sources: https://example.com/r1",
                run_id=7,
            )

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.build_tool_agent_runner",
        lambda **_kwargs: _StructuredRunner(),
    )
    router = _build_router(tmp_path, workflow_runner=_workflow)
    router._build_connectors_fn = lambda _req: [_FakeConnector(closed, "github")]

    asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert closed == ["github"]


def test_route_streaming_digest_fallback_uses_streaming_workflow_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=11,
        markdown="# Fallback digest",
        text="Fallback digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("non-streaming workflow must not run")

    async def _streaming_workflow(
        _req: DigestRequest,
        _on_stage=None,
    ) -> AsyncIterator[tuple[str, bool, DigestResult | None]]:
        yield "Collecting…", False, None
        yield "", True, digest_result

    class _StructuredRunner:
        async def run(self, _message: str) -> InterfaceAgentResult:
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.STRUCTURED,
                text="Sources: https://example.com/r1",
                run_id=7,
            )

        async def run_streaming(
            self, _message: str
        ) -> AsyncIterator[tuple[str, bool, InterfaceAgentResult | None]]:
            yield "", True, InterfaceAgentResult(
                kind=InterfaceAgentResultKind.STRUCTURED,
                text="Sources: https://example.com/r1",
                run_id=7,
            )

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.build_tool_agent_runner",
        lambda **_kwargs: _StructuredRunner(),
    )
    router = _build_router(
        tmp_path,
        workflow_runner=_workflow,
        streaming_workflow_runner=_streaming_workflow,
    )

    async def _collect() -> list[tuple[str, bool, InterfaceAgentResult | None]]:
        events: list[tuple[str, bool, InterfaceAgentResult | None]] = []
        async for progress, done, payload in router.route_streaming(
            message="Generate digest.",
            digest_request=trusted_request,
        ):
            events.append((progress, done, payload))
        return events

    events = asyncio.run(_collect())
    progress_events = [progress for progress, done, _payload in events if not done and progress]
    final = events[-1][2]

    assert "Collecting…" in progress_events
    assert final is not None
    assert final.kind == InterfaceAgentResultKind.DIGEST
    assert final.text == "Fallback digest text"


def test_structured_agent_fallback_uses_answer_structured_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _run_id = _seed_full_followup_store(tmp_path)
    model = _FakeToolCallModel([AIMessage(content="No tool calls.")])
    calls: list[tuple[str, Any]] = []

    def _spy(message: str, ctx: Any) -> str:
        calls.append((message, ctx))
        return format_sources(ctx)

    monkeypatch.setattr(
        "ai_news_agent.tools.interface_router.answer_structured_followup",
        _spy,
    )
    router = _build_router(tmp_path, store=store, tool_model=model)

    result = asyncio.run(router.route(message="show sources"))

    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == "Sources from the latest digest:\n1. a/b — https://github.com/a/b"
    assert len(calls) == 1
    assert calls[0][0] == "show sources"


def _open_ended_conversational_model() -> _FakeToolCallModel:
    return _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "load_latest_digest",
                        "args": {},
                        "id": "call-1",
                    }
                ],
            ),
            AIMessage(content="Grounded open-ended answer."),
        ]
    )


def test_open_ended_agent_conversational_passthrough(tmp_path: Path) -> None:
    store, _run_id = _seed_full_followup_store(tmp_path)

    async def _execute() -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="Loaded digest with 1 entry.",
        )

    @tool
    async def load_latest_digest() -> ToolObservation:
        """Load the latest saved digest."""
        return await _execute()

    registry = ToolRegistry([load_latest_digest])
    runner = build_tool_agent_runner(
        registry=registry,
        model=_open_ended_conversational_model(),
    )

    from ai_news_agent.tools.interface_router import build_interface_tool_router

    gh, bh, jh = _noop_factories()

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("workflow must not run")

    router = build_interface_tool_router(
        store=store,
        workflow_runner=_workflow,
        streaming_workflow_runner=None,
        tool_model=_open_ended_conversational_model(),
        digest_model=object(),
        github_factory=gh,
        bilibili_factory=bh,
        juya_factory=jh,
        build_connectors_fn=lambda _req: [],
        interface_name="test",
    )
    # Exercise open-ended path via the same agent stack the router builds internally.
    result = asyncio.run(runner.run("What trends do you see?"))

    assert result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert result.text == "Grounded open-ended answer."

    router_result = asyncio.run(router.route(message="What trends do you see?"))
    assert router_result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert router_result.text == "Grounded open-ended answer."


def test_open_ended_agent_fallback_returns_guidance(tmp_path: Path) -> None:
    store, _run_id = _seed_full_followup_store(tmp_path)
    model = _FakeToolCallModel([AIMessage(content="Direct answer.")])
    router = _build_router(tmp_path, store=store, tool_model=model)

    result = asyncio.run(router.route(message="what is the meaning of life"))

    assert result.kind == InterfaceAgentResultKind.FALLBACK
    assert result.fallback_reason == "no_first_tool_call"
    assert "Try a concrete request" in result.text


def test_no_saved_digest_returns_message_without_agent(tmp_path: Path) -> None:
    model = _FakeToolCallModel([AIMessage(content="Should not run.")])
    router = _build_router(tmp_path, tool_model=model)

    result = asyncio.run(router.route(message="show sources"))

    assert result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert result.text == NO_SAVED_DIGEST
    assert model._index == 0


def test_model_failure_runs_deterministic_digest_fallback(tmp_path: Path) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=3,
        markdown="# Digest",
        text="Deterministic digest",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )

    class _BoomModel:
        def bind_tools(self, tools: Any) -> "_BoomModel":
            return self

        async def ainvoke(self, messages: Any) -> AIMessage:
            raise RuntimeError("model boom")

    workflow_calls: list[DigestRequest] = []

    async def _workflow(req: DigestRequest, _on_stage=None) -> DigestResult:
        workflow_calls.append(req)
        return digest_result

    router = _build_router(
        tmp_path,
        workflow_runner=_workflow,
        tool_model=_BoomModel(),
    )
    result = asyncio.run(
        router.route(
            message="Generate digest.",
            digest_request=trusted_request,
        )
    )

    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.text == "Deterministic digest"
    assert len(workflow_calls) == 1


async def _collect_stream(router: Any, **kwargs: Any) -> list[tuple[str, bool, Any]]:
    events: list[tuple[str, bool, Any]] = []
    async for event in router.route_streaming(**kwargs):
        events.append(event)
    return events


def test_route_streaming_yields_progress_then_final_result(tmp_path: Path) -> None:
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=7,
        markdown="# Digest",
        text="Digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-digest",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )

    async def _workflow(_req: DigestRequest, _on_stage=None) -> DigestResult:
        raise AssertionError("workflow must not run")

    router = _build_router(tmp_path, workflow_runner=_workflow, tool_model=model)

    with patch(
        "ai_news_agent.tools.registry.run_digest_instrumented",
        AsyncMock(return_value=digest_result),
    ):
        events = asyncio.run(
            _collect_stream(
                router,
                message="Generate digest.",
                digest_request=trusted_request,
                correlation_id="stream-corr",
            )
        )

    progress = [text for text, done, _payload in events if not done and text]
    assert progress == [
        "Calling generate_ai_news_digest…",
        "Done generate_ai_news_digest: Digest text",
    ]
    done_result = events[-1][2]
    assert events[-1][0] == ""
    assert events[-1][1] is True
    assert isinstance(done_result, InterfaceAgentResult)
    assert done_result.kind == InterfaceAgentResultKind.DIGEST
    assert done_result.correlation_id == "stream-corr"


def test_build_interface_tool_router_import_from_tools_package() -> None:
    from ai_news_agent.tools import InterfaceToolRouter as PackageRouter
    from ai_news_agent.tools import build_interface_tool_router as package_build

    assert PackageRouter is not None
    assert package_build is not None
