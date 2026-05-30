"""Gradio UI tests for source toggles, examples, and streaming."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ai_news_agent.app import gradio_app
from ai_news_agent.app.gradio_app import _EXAMPLE_ROWS, _build_service, create_app
from ai_news_agent.chat import ChatService
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore


def test_create_app_builds_with_foldable_examples_and_streaming_handler(tmp_path) -> None:
    captured: list[DigestRequest] = []

    async def fake_runner(req: DigestRequest) -> DigestResult:
        captured.append(req)
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        return DigestResult(
            request=req,
            digest=None,
            run_id=None,
            markdown="",
            text="ok\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    async def fake_streaming_runner(req: DigestRequest):
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        yield "Collecting from sources…", False, None
        yield "", True, DigestResult(
            request=req,
            digest=None,
            run_id=1,
            markdown="",
            text="ok\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "gradio.db")
    store.init_schema()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        streaming_workflow_runner=fake_streaming_runner,
    )
    demo = create_app(svc)

    assert demo is not None
    assert len(_EXAMPLE_ROWS) == 5

    reply = asyncio.run(
        svc.handle_message_async(
            "Give me today's AI digest",
            session_connector_names=["bilibili"],
        )
    )
    assert reply == "ok\n"
    assert captured[0].connector_names == ["bilibili"]

    async def collect_stream() -> list[str]:
        chunks: list[str] = []
        async for chunk in svc.handle_message_streaming_async(
            "Give me today's AI digest",
            session_connector_names=["bilibili"],
            chunk_delay_s=0,
        ):
            chunks.append(chunk)
        return chunks

    stream_chunks = asyncio.run(collect_stream())
    assert stream_chunks[0] == "Collecting from sources…"
    assert stream_chunks[-1] == "ok\n"


def test_create_app_chat_interface_fn_is_async_generator(tmp_path) -> None:
    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("unused")

    store = DigestStore(tmp_path / "gradio-fn.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)
    demo = create_app(svc)
    assert demo is not None
    assert demo.mode == "blocks"


def test_build_service_fake_mode_injects_tool_agent_runner(tmp_path) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "fake-tool-agent.db")

    assert getattr(service, "_tool_agent_runner", None) is not None


def test_build_service_live_mode_wires_tool_registry_and_agent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry_calls: list[dict] = []
    agent_calls: list[dict] = []
    fake_registry = MagicMock(name="ToolRegistry")
    fake_runner = MagicMock(name="ToolAgentRunner")

    def spy_build_tool_registry(**kwargs):
        registry_calls.append(kwargs)
        return fake_registry

    def spy_build_tool_agent_runner(**kwargs):
        agent_calls.append(kwargs)
        return fake_runner

    monkeypatch.setattr(gradio_app, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        gradio_app,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_tool_registry",
        spy_build_tool_registry,
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_tool_agent_runner",
        spy_build_tool_agent_runner,
        raising=False,
    )

    service = _build_service(fake=False, db_path=tmp_path / "live-tool-agent.db")

    assert len(registry_calls) == 1
    assert len(agent_calls) == 1
    assert agent_calls[0]["registry"] is fake_registry
    assert getattr(service, "_tool_agent_runner", None) is fake_runner
