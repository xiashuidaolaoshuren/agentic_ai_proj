"""Gradio UI tests for source toggles, examples, and streaming."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ai_news_agent.app import gradio_app
from ai_news_agent.app.gradio_app import _EXAMPLE_ROWS, _build_service, create_app
from ai_news_agent.chat import ChatService
from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.models import (
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    SourceKind,
)
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore


def _save_minimal_digest(store: DigestStore) -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe=None,
    )
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)


async def _collect_stream(service: ChatService, message: str, **kwargs) -> list[str]:  # noqa: ANN003
    chunks: list[str] = []
    async for chunk in service.handle_message_streaming_async(
        message, chunk_delay_s=0, **kwargs
    ):
        chunks.append(chunk)
    return chunks


def test_gradio_fake_tool_agent_streaming_emits_progress_then_ephemeral_final(
    tmp_path,
) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "gradio-tool-stream.db")
    store = service._store  # noqa: SLF001
    _save_minimal_digest(store)

    chunks = asyncio.run(
        _collect_stream(
            service,
            "Why does this repo matter?",
            chunk_size=12,
        )
    )

    assert any("Calling load_latest_digest" in chunk for chunk in chunks)
    assert chunks[-1] == gradio_app._FAKE_TOOL_AGENT_REPLY
    assert "Calling" not in chunks[-1]


def test_gradio_build_service_digest_stream_ephemeral_final(tmp_path) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "gradio-digest-stream.db")

    chunks = asyncio.run(
        _collect_stream(
            service,
            "Give me today's AI digest",
            session_connector_names=["github"],
            chunk_size=8,
        )
    )

    assert any("Parsing request" in chunk or "Collecting from sources" in chunk for chunk in chunks)
    assert chunks[-1]
    assert "Parsing request" not in chunks[-1]
    assert "Collecting from sources" not in chunks[-1]


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
    assert "Collecting from sources" not in stream_chunks[-1]


def test_create_app_chat_interface_fn_is_async_generator(tmp_path) -> None:
    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("unused")

    store = DigestStore(tmp_path / "gradio-fn.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)
    demo = create_app(svc)
    assert demo is not None
    assert demo.mode == "blocks"


def test_build_service_fake_mode_passes_no_interface_router(tmp_path) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "fake-interface-router.db")

    assert getattr(service, "_interface_router", None) is None
    assert getattr(service, "_tool_agent_runner", None) is not None


def test_build_service_live_mode_wires_interface_tool_router(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router_calls: list[dict] = []
    fake_router = MagicMock(name="InterfaceToolRouter")

    def spy_build_interface_tool_router(**kwargs):
        router_calls.append(kwargs)
        return fake_router

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
        "build_interface_tool_router",
        spy_build_interface_tool_router,
        raising=False,
    )
    registry_called = False
    agent_called = False

    def fail_build_tool_registry(**_kwargs):
        nonlocal registry_called
        registry_called = True
        raise AssertionError("build_tool_registry should not run at service construction")

    def fail_build_tool_agent_runner(**_kwargs):
        nonlocal agent_called
        agent_called = True
        raise AssertionError("build_tool_agent_runner should not run at service construction")

    monkeypatch.setattr(
        gradio_app,
        "build_tool_registry",
        fail_build_tool_registry,
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_tool_agent_runner",
        fail_build_tool_agent_runner,
        raising=False,
    )

    service = _build_service(fake=False, db_path=tmp_path / "live-interface-router.db")

    assert len(router_calls) == 1
    assert router_calls[0]["interface_name"] == "gradio"
    assert router_calls[0]["tool_model"] is not None
    assert router_calls[0]["digest_model"] is not None
    assert callable(router_calls[0]["build_connectors_fn"])
    assert callable(router_calls[0]["workflow_runner"])
    assert callable(router_calls[0]["streaming_workflow_runner"])
    assert getattr(service, "_interface_router", None) is fake_router
    assert not registry_called
    assert not agent_called


def test_build_service_fake_mode_injects_tool_agent_runner(tmp_path) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "fake-tool-agent.db")

    assert getattr(service, "_tool_agent_runner", None) is not None
