"""Gradio UI tests for source toggles, examples, and streaming."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ai_news_agent.app import gradio_app
from ai_news_agent.app.gradio_app import (
    _EMPTY_SOURCES_MESSAGE,
    _EXAMPLE_ROWS,
    _SOURCE_TOGGLE_CHOICES,
    _build_service,
    create_app,
)
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
from ai_news_agent.sources import DEFAULT_SOURCE_NAMES
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


def test_gradio_source_toggle_choices_include_all_allowed_sources() -> None:
    assert list(_SOURCE_TOGGLE_CHOICES) == [
        "juya",
        "huggingface",
        "github",
        "zhihu",
        "bilibili",
    ]


def test_gradio_default_source_toggle_value_is_juya_only() -> None:
    assert list(DEFAULT_SOURCE_NAMES) == ["juya"]


def test_gradio_empty_sources_message_mentions_juya() -> None:
    assert "Juya" in _EMPTY_SOURCES_MESSAGE
    assert "GitHub" in _EMPTY_SOURCES_MESSAGE
    assert "Bilibili" in _EMPTY_SOURCES_MESSAGE
    assert "Hugging Face" in _EMPTY_SOURCES_MESSAGE
    assert "Zhihu" in _EMPTY_SOURCES_MESSAGE


def test_gradio_examples_include_daily_juya_url() -> None:
    assert any("daily.juya.uk" in row[0] for row in _EXAMPLE_ROWS)


def test_gradio_examples_include_huggingface_trending_prompt() -> None:
    assert any(
        "hugging face" in row[0].lower() and "trending" in row[0].lower()
        for row in _EXAMPLE_ROWS
    )


def test_gradio_examples_include_zhihu_practitioner_prompt() -> None:
    assert any(
        "zhihu" in row[0].lower() and "practitioner" in row[0].lower()
        for row in _EXAMPLE_ROWS
    )


_HISTORY_SEARCH_PROMPT = (
    "search history for RAG agents from huggingface,zhihu since 2026-08-01"
)
_HISTORY_OPEN_PROMPT = "open history d12:r3"


def test_gradio_examples_include_history_prompts() -> None:
    prompts = [row[0] for row in _EXAMPLE_ROWS]
    assert len(_EXAMPLE_ROWS) == 10
    assert _HISTORY_SEARCH_PROMPT in prompts
    assert _HISTORY_OPEN_PROMPT in prompts


def test_gradio_examples_map_prompts_to_matching_source_toggles() -> None:
    by_prompt = {row[0]: list(row[1]) for row in _EXAMPLE_ROWS}

    assert by_prompt["Give me today's AI digest"] == ["juya"]
    assert by_prompt["Digest https://daily.juya.uk/"] == ["juya"]
    assert by_prompt["Give me today's AI digest from github only"] == ["github"]
    assert by_prompt["Digest https://github.com/langchain-ai/langgraph"] == ["github"]
    assert by_prompt["Digest bilibili channel 285286947"] == ["bilibili"]
    assert by_prompt["Show Hugging Face trending models"] == ["huggingface"]
    assert by_prompt["Find Zhihu practitioner insights on RAG"] == ["zhihu"]
    assert by_prompt["follow up on item 1"] == ["juya"]
    assert by_prompt[_HISTORY_SEARCH_PROMPT] == ["huggingface", "zhihu"]
    assert by_prompt[_HISTORY_OPEN_PROMPT] == ["juya"]

    assert not any("/issues/" in row[0] for row in _EXAMPLE_ROWS)


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
    assert len(_EXAMPLE_ROWS) == 10

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
        lambda **kw: MagicMock(name=f"ConnectorFactory-{kw.get('name')}"),
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
    assert "juya_factory" in router_calls[0]
    assert "huggingface_factory" in router_calls[0]
    assert "zhihu_factory" in router_calls[0]
    assert getattr(service, "_interface_router", None) is fake_router
    assert not registry_called
    assert not agent_called


def test_build_service_live_mode_passes_juya_factory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory_calls: list[dict[str, object]] = []
    router_calls: list[dict] = []

    def recording_build_connector_factory(**kwargs):
        factory_calls.append(dict(kwargs))
        return MagicMock(name=f"ConnectorFactory-{kwargs.get('name')}")

    def spy_build_interface_tool_router(**kwargs):
        router_calls.append(kwargs)
        return MagicMock(name="InterfaceToolRouter")

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
        recording_build_connector_factory,
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_interface_tool_router",
        spy_build_interface_tool_router,
        raising=False,
    )

    _build_service(fake=False, db_path=tmp_path / "live-juya-factory.db")

    assert any(call.get("name") == "juya" for call in factory_calls)
    assert any(call.get("name") == "huggingface" for call in factory_calls)
    assert any(call.get("name") == "zhihu" for call in factory_calls)
    assert len(router_calls) == 1
    assert router_calls[0]["juya_factory"] is not None
    assert router_calls[0]["huggingface_factory"] is not None
    assert router_calls[0]["zhihu_factory"] is not None


def test_build_service_live_closures_respect_connector_names(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router_calls: list[dict] = []
    connector_name_calls: list[list[str]] = []
    original_build_connectors = gradio_app.build_connectors

    def recording_build_connectors(*, fake: bool, names: list[str]):
        connector_name_calls.append(list(names))
        return original_build_connectors(fake=fake, names=names)

    async def fake_run_digest_async(
        req: DigestRequest,
        *,
        store: DigestStore,
        connectors,
        model,
        on_stage=None,
    ) -> DigestResult:
        del store, connectors, model, on_stage
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

    async def fake_run_digest_streaming_async(
        req: DigestRequest,
        *,
        store: DigestStore,
        connectors,
        model,
        on_stage=None,
    ):
        del store, connectors, model, on_stage
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        yield "", True, DigestResult(
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

    def spy_build_interface_tool_router(**kwargs):
        router_calls.append(kwargs)
        return MagicMock(name="InterfaceToolRouter")

    monkeypatch.setattr(gradio_app, "build_connectors", recording_build_connectors)
    monkeypatch.setattr(gradio_app, "_run_digest_async", fake_run_digest_async)
    monkeypatch.setattr(
        gradio_app,
        "_run_digest_streaming_async",
        fake_run_digest_streaming_async,
    )
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
        lambda **kw: MagicMock(name=f"ConnectorFactory-{kw.get('name')}"),
        raising=False,
    )
    monkeypatch.setattr(
        gradio_app,
        "build_interface_tool_router",
        spy_build_interface_tool_router,
        raising=False,
    )
    monkeypatch.setattr(gradio_app, "load_local_env", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(
        gradio_app,
        "configure_bilibili_network_from_env",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    _build_service(fake=False, db_path=tmp_path / "live-connector-names.db")

    assert len(router_calls) == 1
    build_connectors_fn = router_calls[0]["build_connectors_fn"]
    workflow_runner = router_calls[0]["workflow_runner"]
    streaming_workflow_runner = router_calls[0]["streaming_workflow_runner"]

    connector_name_calls.clear()
    build_connectors_fn(DigestRequest(connector_names=["github"]))
    assert connector_name_calls[-1] == ["github"]

    connector_name_calls.clear()
    asyncio.run(workflow_runner(DigestRequest(connector_names=["bilibili"])))
    assert connector_name_calls[-1] == ["bilibili"]

    connector_name_calls.clear()

    async def consume_stream() -> None:
        async for _ in streaming_workflow_runner(
            DigestRequest(connector_names=["github"])
        ):
            pass

    asyncio.run(consume_stream())
    assert connector_name_calls[-1] == ["github"]

    connector_name_calls.clear()
    build_connectors_fn(DigestRequest())
    assert connector_name_calls[-1] == list(DEFAULT_SOURCE_NAMES)


def test_build_service_fake_mode_injects_tool_agent_runner(tmp_path) -> None:
    service = _build_service(fake=True, db_path=tmp_path / "fake-tool-agent.db")

    assert getattr(service, "_tool_agent_runner", None) is not None


def test_create_app_exposes_items_per_source_number_control(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    original_number = gradio_app.gr.Number
    original_chat_interface = gradio_app.gr.ChatInterface

    def spy_number(**kwargs):
        captured["number"] = dict(kwargs)
        return original_number(**kwargs)

    def spy_chat_interface(**kwargs):
        captured["chat_interface"] = dict(kwargs)
        return original_chat_interface(**kwargs)

    monkeypatch.setattr(gradio_app.gr, "Number", spy_number)
    monkeypatch.setattr(gradio_app.gr, "ChatInterface", spy_chat_interface)

    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("unused")

    store = DigestStore(tmp_path / "gradio-items-per-source.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)
    create_app(svc)

    number_kwargs = captured["number"]
    assert number_kwargs["value"] == 5
    assert number_kwargs["minimum"] == 1
    assert number_kwargs["maximum"] == 20

    additional_inputs = captured["chat_interface"]["additional_inputs"]
    assert len(additional_inputs) == 2


def test_respond_stream_passes_session_items_per_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream_kwargs: list[dict[str, object]] = []
    captured_fn: dict[str, object] = {}
    original_chat_interface = gradio_app.gr.ChatInterface

    def spy_chat_interface(**kwargs):
        captured_fn["fn"] = kwargs["fn"]
        return original_chat_interface(**kwargs)

    monkeypatch.setattr(gradio_app.gr, "ChatInterface", spy_chat_interface)

    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("unused")

    store = DigestStore(tmp_path / "gradio-respond-stream-n.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    async def recording_stream(message: str, **kwargs):  # noqa: ANN003
        stream_kwargs.append({"message": message, **kwargs})
        yield "ok\n"

    svc.handle_message_streaming_async = recording_stream  # type: ignore[method-assign]

    create_app(svc)
    respond_stream = captured_fn["fn"]

    async def collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in respond_stream(
            "Give me today's AI digest",
            [],
            ["juya", "huggingface"],
            5,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert chunks == ["ok\n"]
    assert len(stream_kwargs) == 1
    assert stream_kwargs[0]["session_items_per_source"] == 5
    assert stream_kwargs[0]["session_connector_names"] == ["juya", "huggingface"]
