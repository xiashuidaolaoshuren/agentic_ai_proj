"""Tests for follow-up chat service (Task T11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_agent.chat import ChatService
from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.followup_structured import NO_SAVED_DIGEST
from ai_news_agent.models import (
    ConfidenceLevel,
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
)


class _FakeInterfaceRouter:
    def __init__(
        self,
        *,
        result: InterfaceAgentResult | None = None,
        stream_events: list[tuple[str, bool, InterfaceAgentResult | None]] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._result = result or InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="unused",
        )
        self._stream_events = stream_events

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        session_items_per_source: int | None = None,
        correlation_id: str | None = None,
    ) -> InterfaceAgentResult:
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "session_connector_names": session_connector_names,
                "session_items_per_source": session_items_per_source,
                "correlation_id": correlation_id,
            }
        )
        return self._result

    async def route_streaming(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        session_items_per_source: int | None = None,
        correlation_id: str | None = None,
    ):
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "session_connector_names": session_connector_names,
                "session_items_per_source": session_items_per_source,
                "correlation_id": correlation_id,
                "streaming": True,
            }
        )
        if self._stream_events is not None:
            for event in self._stream_events:
                yield event
            return
        yield "", True, self._result


def test_chat_with_interface_router_routes_digest_through_router(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called directly by ChatService")

    store = DigestStore(tmp_path / "router-digest.db")
    store.init_schema()
    incoming = DigestRequest(topics=["RAG"])
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="digest text",
            run_id=7,
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    reply = asyncio.run(
        svc.handle_message_async("ignored message body", digest_request=incoming)
    )

    assert reply == "digest text"
    assert len(router.calls) == 1
    assert router.calls[0]["digest_request"] is incoming
    assert router.calls[0]["message"] == "ignored message body"


def test_chat_maps_interface_digest_result_with_warnings_notice(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called")

    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    digest = Digest(
        generated_at=now,
        entries=[],
        topics=["RAG"],
        timeframe=None,
    )
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="digest body",
            run_id=7,
            digest=digest,
        )
    )
    store = DigestStore(tmp_path / "router-warnings.db")
    store.init_schema()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    monkeypatch.setattr(
        "ai_news_agent.chat.format_connector_warnings_notice",
        lambda _warnings, _errors: "Notice:",
    )

    reply = asyncio.run(
        svc.handle_message_async("digest please", digest_request=DigestRequest(topics=["RAG"]))
    )

    assert reply == "Notice:\n\ndigest body"


def test_chat_with_interface_router_routes_structured_followup_through_router(
    tmp_path,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "router-structured.db")
    store.init_schema()
    _save_minimal_digest(store)

    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.STRUCTURED,
            text="Sources: https://example.com/r1",
            run_id=1,
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "ai_news_agent.chat.answer_structured_followup",
            lambda _message, _ctx: (_ for _ in ()).throw(
                AssertionError("answer_structured_followup must not be called")
            ),
        )
        reply = asyncio.run(svc.handle_message_async("show sources"))

    assert reply == "Sources: https://example.com/r1"
    assert len(router.calls) == 1
    assert router.calls[0]["message"] == "show sources"


def test_chat_with_interface_router_routes_open_ended_followup_through_router(
    tmp_path,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "router-open.db")
    store.init_schema()
    _save_minimal_digest(store)

    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="answer",
        )
    )
    runner = _FakeToolAgentRunner()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async("what trends do you see?"))

    assert reply == "answer"
    assert runner.calls == []
    assert len(router.calls) == 1


def test_chat_with_interface_router_no_saved_digest_returns_router_text(tmp_path) -> None:
    from ai_news_agent.followup_structured import NO_SAVED_DIGEST

    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "router-no-digest.db")
    store.init_schema()
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text=NO_SAVED_DIGEST,
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async("show sources"))

    assert reply == NO_SAVED_DIGEST
    assert len(router.calls) == 1


def test_chat_streaming_via_interface_router_yields_progress_then_chunked_text(
    tmp_path,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "router-stream.db")
    store.init_schema()
    router = _FakeInterfaceRouter(
        stream_events=[
            ("Calling generate_ai_news_digest…", False, None),
            (
                "",
                True,
                InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.DIGEST,
                    text="1234567890",
                    run_id=7,
                ),
            ),
        ]
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    chunks = asyncio.run(
        _collect_streaming(
            svc,
            "Generate digest.",
            digest_request=DigestRequest(topics=["AI"]),
            chunk_size=4,
            chunk_delay_s=0,
        )
    )

    assert chunks[0] == "Calling generate_ai_news_digest…"
    assert chunks[-1] == "1234567890"
    assert len(chunks) > 2
    assert "Calling" not in chunks[-1]


def test_chat_routes_explicit_digest_request_through_workflow_runner(tmp_path) -> None:
    captured: list[DigestRequest] = []

    async def fake_runner(req: DigestRequest) -> DigestResult:
        captured.append(req)
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        dr = DigestRequest(topics=["x"])
        return DigestResult(
            request=dr,
            digest=None,
            run_id=None,
            markdown="# md\n",
            text="digest-text-output\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "c.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    incoming = DigestRequest(topics=["RAG"])
    reply = asyncio.run(
        svc.handle_message_async(
            "ignored message body",
            digest_request=incoming,
        )
    )

    assert reply == "digest-text-output\n"
    assert len(captured) == 1
    assert captured[0] is incoming


def test_chat_follow_up_without_saved_digest_returns_guidance(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run for generic follow-up")

    store = DigestStore(tmp_path / "empty.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    reply = asyncio.run(svc.handle_message_async("What does item 2 mean?"))

    assert "No saved digest" in reply


def test_chat_structured_sources_lists_digest_urls(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

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

    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    svc = ChatService(store=store, workflow_runner=fake_runner)
    reply = asyncio.run(svc.handle_message_async("Please show sources"))

    assert "https://example.com/r1" in reply
    assert "Repo" in reply


def test_chat_structured_rank_item_returns_entry_detail(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

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
                summary="Digest summary",
                why_it_matters="Because it matters",
                background_knowledge="Background",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe=None,
    )

    store = DigestStore(tmp_path / "rank-item.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    svc = ChatService(store=store, workflow_runner=fake_runner)
    reply = asyncio.run(svc.handle_message_async("follow up on item 1"))

    assert "Digest item 1: Repo" in reply
    assert "Digest summary" in reply
    assert "Because it matters" in reply


def test_chat_structured_ranking_recommends_top_selected(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    low = NewsItem(
        source=SourceKind.GITHUB,
        source_id="low",
        url="https://example.com/low",
        title="Low",
        collected_at=now,
    )
    high = NewsItem(
        source=SourceKind.GITHUB,
        source_id="high",
        url="https://example.com/high",
        title="High",
        collected_at=now,
    )
    digest = Digest(generated_at=now, entries=[], topics=["RAG"], timeframe=None)

    store = DigestStore(tmp_path / "rank.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[low, high], warnings=[]),
    )
    ranked = [
        RankedItem(
            item=low,
            score_total=1.0,
            selected=False,
            selection_reason="skip",
        ),
        RankedItem(
            item=high,
            score_total=9.0,
            selected=True,
            selection_reason="best engagement",
        ),
    ]
    store.save_ranked_items(run_id, ranked)
    store.save_digest(run_id, digest)

    svc = ChatService(store=store, workflow_runner=fake_runner)
    reply = asyncio.run(svc.handle_message_async("Which item should I study first?"))

    assert "High" in reply
    assert "https://example.com/high" in reply
    assert "best engagement" in reply


def test_chat_structured_caveats_lists_warnings_and_entry_notes(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    w = ConnectorWarning(connector="github", code="rate", message="slow")
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
                confidence_caveat="Metadata only",
            )
        ],
        topics=["RAG"],
        timeframe=None,
    )

    store = DigestStore(tmp_path / "warn.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[w]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    svc = ChatService(store=store, workflow_runner=fake_runner)
    reply = asyncio.run(svc.handle_message_async("Any confidence caveats?"))

    assert "rate" in reply
    assert "Metadata only" in reply


class _FakeFollowUpModel:
    def generate_followup_reply(self, *, question: str, grounding: dict) -> str:
        assert "digest" in grounding
        assert grounding["digest"]["topics"] == ["RAG"]
        return f"ECHO:{question.strip()}"


def test_chat_open_ended_uses_llm_when_model_configured(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

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

    store = DigestStore(tmp_path / "llm.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        chat_model=_FakeFollowUpModel(),
    )
    reply = asyncio.run(svc.handle_message_async("Why does this repo matter?"))

    assert reply == "ECHO:Why does this repo matter?"


def test_chat_open_ended_without_model_returns_fallback(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

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

    store = DigestStore(tmp_path / "nofm.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    svc = ChatService(store=store, workflow_runner=fake_runner, chat_model=None)
    reply = asyncio.run(svc.handle_message_async("Explain the tradeoffs abstractly"))

    assert "language model" in reply.lower()


def test_chat_digest_with_url_passes_parsed_request(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "intent.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    msg = "Digest https://github.com/acme/widget"
    reply = asyncio.run(svc.handle_message_async(msg))

    assert reply == "ok\n"
    assert len(captured) == 1
    assert captured[0].topics == []
    assert any("acme/widget" in u for u in captured[0].github_manual_urls)
    assert captured[0].github_target_channels == []


def test_chat_digest_single_github_repo_url_stays_focused(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "gh-repo.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    msg = "Digest https://github.com/langchain-ai/langgraph"
    asyncio.run(svc.handle_message_async(msg))

    assert len(captured) == 1
    assert captured[0].topics == []
    assert any("langchain-ai/langgraph" in u for u in captured[0].github_manual_urls)
    assert captured[0].github_target_channels == []


@pytest.mark.parametrize(
    "message",
    [
        "Show Hugging Face trending models",
        "huggingface trending models",
        "trending repos",
        "Find Zhihu practitioner insights on RAG",
    ],
)
def test_message_requests_digest_true_for_source_browse_phrases(message: str) -> None:
    from ai_news_agent.chat import _message_requests_digest

    assert _message_requests_digest(message) is True


def test_chat_message_digest_keyword_triggers_workflow(tmp_path) -> None:
    seen: list[DigestRequest] = []

    async def fake_runner(req: DigestRequest) -> DigestResult:
        seen.append(req)
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        return DigestResult(
            request=req,
            digest=None,
            run_id=None,
            markdown="",
            text="from-workflow\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "trig.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    reply = asyncio.run(svc.handle_message_async("Give me today's AI digest"))

    assert reply == "from-workflow\n"
    assert len(seen) == 1


def test_chat_session_source_toggles_apply_connector_names(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "session.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    asyncio.run(
        svc.handle_message_async(
            "Give me today's AI digest",
            session_connector_names=["github"],
        )
    )

    assert captured[0].connector_names == ["github"]


def test_chat_session_items_per_source_applies_to_digest_request(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "items-per-source.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    asyncio.run(
        svc.handle_message_async(
            "Give me today's AI digest",
            session_connector_names=["juya", "huggingface"],
            session_items_per_source=5,
        )
    )

    req = captured[0]
    assert req.connector_names == ["juya", "huggingface"]
    assert req.items_per_source == 5
    assert req.max_items_per_source >= 5


def test_chat_nl_source_phrase_overrides_session_toggles(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "override.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    asyncio.run(
        svc.handle_message_async(
            "Give me today's AI digest from bilibili only",
            session_connector_names=["github"],
        )
    )

    assert captured[0].connector_names == ["bilibili"]


async def _collect_streaming(service: ChatService, message: str, **kwargs) -> list[str]:  # noqa: ANN003
    chunks: list[str] = []
    async for chunk in service.handle_message_streaming_async(message, **kwargs):
        chunks.append(chunk)
    return chunks


class _DigestStreamFakeConnector:
    def __init__(self, *, name: str, items: list[NewsItem]) -> None:
        self._name = name
        self._items = items

    def name(self) -> str:
        return self._name

    async def collect(self, _request: ConnectorRequest) -> ConnectorResult:
        return ConnectorResult(items=list(self._items), warnings=[])


class _DigestStreamFakeModel:
    def generate_entry_fields(self, context: dict) -> dict:  # noqa: ARG002
        return {
            "summary": "Test summary",
            "why_it_matters": "Because",
            "background_knowledge": "Bg",
            "follow_up_action": "read",
        }


def _digest_stream_news_item(source_id: str) -> NewsItem:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        title=f"item-{source_id}",
        collected_at=now,
    )


def test_chat_digest_stream_each_progress_is_single_stage_not_cumulative(
    tmp_path,
) -> None:
    from ai_news_agent.graph.workflow import run_digest_streaming

    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    store = DigestStore(tmp_path / "digest-stream-ephemeral.db")
    store.init_schema()
    connectors = [
        _DigestStreamFakeConnector(
            name="github",
            items=[_digest_stream_news_item("r1")],
        )
    ]

    async def collect_progress() -> list[str]:
        lines: list[str] = []
        async for progress, done, _result in run_digest_streaming(
            req,
            connectors=connectors,
            model=_DigestStreamFakeModel(),
            store=store,
            now_provider=lambda: now,
        ):
            if not done and progress:
                lines.append(progress)
        return lines

    progress_lines = asyncio.run(collect_progress())

    assert progress_lines
    for line in progress_lines:
        assert "\n" not in line
    assert progress_lines[0] == "Parsing request…"
    assert "Parsing request" not in progress_lines[-1]


def _bilibili_anti_bot_warning() -> ConnectorWarning:
    return ConnectorWarning(
        connector="bilibili",
        code="anti_bot_blocked",
        message=(
            "Bilibili keyword search blocked (anti-bot). "
            "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 "
            "in .env, or use video URLs/channels."
        ),
    )


def test_chat_digest_sync_includes_anti_bot_warning(tmp_path) -> None:
    warning = _bilibili_anti_bot_warning()

    async def fake_runner(req: DigestRequest) -> DigestResult:
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        return DigestResult(
            request=req,
            digest=None,
            run_id=None,
            markdown="",
            text="digest-body\n",
            ranked_items=[],
            warnings=[warning],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "anti-bot-sync.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    reply = asyncio.run(
        svc.handle_message_async(
            "ignored",
            digest_request=DigestRequest(topics=["AI"]),
        )
    )

    assert "BILIBILI_SESSDATA" in reply
    assert "digest-body" in reply
    assert reply.index("BILIBILI_SESSDATA") < reply.index("digest-body")


def test_chat_digest_streaming_includes_anti_bot_warning(tmp_path) -> None:
    warning = _bilibili_anti_bot_warning()
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    async def fake_streaming_runner(req: DigestRequest):
        yield "Collecting…", False, None
        yield "", True, DigestResult(
            request=req,
            digest=None,
            run_id=1,
            markdown="",
            text="digest-body",
            ranked_items=[],
            warnings=[warning],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("sync runner should not be used")

    store = DigestStore(tmp_path / "anti-bot-stream.db")
    store.init_schema()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        streaming_workflow_runner=fake_streaming_runner,
    )

    chunks = asyncio.run(
        _collect_streaming(
            svc,
            "Give me today's AI digest",
            chunk_size=80,
            chunk_delay_s=0,
        )
    )

    full = "".join(chunks)
    assert "BILIBILI_SESSDATA" in full
    assert "digest-body" in full
    assert full.index("BILIBILI_SESSDATA") < full.index("digest-body")


def test_chat_digest_warning_banner_absent_without_warnings(tmp_path) -> None:
    async def fake_runner(req: DigestRequest) -> DigestResult:
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        return DigestResult(
            request=req,
            digest=None,
            run_id=None,
            markdown="",
            text="digest-body\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "no-warning-banner.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)

    reply = asyncio.run(
        svc.handle_message_async(
            "ignored",
            digest_request=DigestRequest(topics=["AI"]),
        )
    )

    assert reply == "digest-body\n"
    assert "BILIBILI_SESSDATA" not in reply


def test_chat_streaming_digest_yields_progress_then_chunks(tmp_path) -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    async def fake_streaming_runner(req: DigestRequest):
        yield "Parsing request…", False, None
        yield "", True, DigestResult(
            request=req,
            digest=None,
            run_id=1,
            markdown="",
            text="ABCDEFGHIJ",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("workflow runner should not be used")

    store = DigestStore(tmp_path / "stream-chat.db")
    store.init_schema()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        streaming_workflow_runner=fake_streaming_runner,
    )

    chunks = asyncio.run(
        _collect_streaming(
            svc,
            "Give me today's AI digest",
            chunk_size=4,
            chunk_delay_s=0,
        )
    )

    assert chunks[0] == "Parsing request…"
    assert chunks[-1] == "ABCDEFGHIJ"
    assert "Parsing request" not in chunks[-1]
    assert len(chunks) > 2


def test_chat_streaming_follow_up_yields_multiple_chunks(tmp_path) -> None:
    async def fake_runner(_req: DigestRequest) -> DigestResult:
        raise AssertionError("workflow runner should not be used")

    store = DigestStore(tmp_path / "stream-follow.db")
    store.init_schema()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
    )

    chunks = asyncio.run(
        _collect_streaming(
            svc,
            "What does item 2 mean?",
            chunk_size=10,
            chunk_delay_s=0,
        )
    )

    assert len(chunks) >= 2
    assert chunks[-1].startswith("No saved digest")


class _FakeToolAgentRunner:
    def __init__(self, reply: str = "AGENT_SAYS") -> None:
        self.calls: list[str] = []
        self._reply = reply

    async def run(self, question: str) -> str:
        self.calls.append(question)
        return self._reply


class _StreamingFakeToolAgentRunner(_FakeToolAgentRunner):
    async def run_streaming(self, question: str):  # noqa: ANN201
        self.calls.append(question)
        yield "Calling load_latest_digest…", False, None
        yield "Done load_latest_digest: Loaded digest with 1 entry.", False, None
        yield "", True, self._reply


def test_chat_tool_agent_runner_accepted_as_constructor_arg(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-init.db")
    store.init_schema()
    runner = _FakeToolAgentRunner()

    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    assert svc is not None


def _save_minimal_digest(store: DigestStore, *, db_name: str = "ctx") -> None:
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


def test_chat_open_ended_follow_up_routes_to_tool_agent_when_configured(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-route.db")
    store.init_schema()
    _save_minimal_digest(store)

    runner = _FakeToolAgentRunner(reply="Grounded tool answer.")
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    question = "Why does this repo matter?"
    reply = asyncio.run(svc.handle_message_async(question))

    assert runner.calls == [question]
    assert reply == "Grounded tool answer."


class _InterfaceResultToolAgentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, question: str) -> InterfaceAgentResult:
        self.calls.append(question)
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.STRUCTURED,
            text="Grounded answer",
        )


def test_chat_tool_agent_runner_interface_result_normalized_to_text(
    tmp_path: Path,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-interface-result.db")
    store.init_schema()
    _save_minimal_digest(store)

    runner = _InterfaceResultToolAgentRunner()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    question = "Why does this matter?"
    reply = asyncio.run(svc.handle_message_async(question))

    assert runner.calls == [question]
    assert reply == "Grounded answer"
    assert isinstance(reply, str)


def test_chat_streaming_follow_up_uses_tool_agent_when_configured(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-stream.db")
    store.init_schema()
    _save_minimal_digest(store)

    runner = _FakeToolAgentRunner(reply="Streaming tool answer.")
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    question = "Explain the tradeoffs abstractly"
    chunks = asyncio.run(
        _collect_streaming(
            svc,
            question,
            chunk_size=10,
            chunk_delay_s=0,
        )
    )

    assert runner.calls == [question]
    assert chunks[-1] == "Streaming tool answer."


def test_chat_streaming_follow_up_emits_tool_progress_then_ephemeral_final_answer(
    tmp_path,
) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-stream-ephemeral.db")
    store.init_schema()
    _save_minimal_digest(store)

    runner = _StreamingFakeToolAgentRunner(reply="Final grounded answer only.")
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    question = "Why does this repo matter?"
    chunks = asyncio.run(
        _collect_streaming(
            svc,
            question,
            chunk_size=12,
            chunk_delay_s=0,
        )
    )

    assert runner.calls == [question]
    assert any("Calling load_latest_digest" in chunk for chunk in chunks)
    assert chunks[-1] == "Final grounded answer only."
    assert "Calling" not in chunks[-1]
    assert "Done load_latest_digest" not in chunks[-1]


def test_chat_tool_agent_not_called_for_structured_followup(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow should not run")

    store = DigestStore(tmp_path / "tool-agent-structured.db")
    store.init_schema()
    _save_minimal_digest(store)

    runner = _FakeToolAgentRunner()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    reply = asyncio.run(svc.handle_message_async("Please show sources"))

    assert "https://example.com/r1" in reply
    assert runner.calls == []


def test_chat_tool_agent_not_called_for_digest_request(tmp_path) -> None:
    captured: list[DigestRequest] = []

    async def fake_runner(req: DigestRequest) -> DigestResult:
        captured.append(req)
        now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
        return DigestResult(
            request=req,
            digest=None,
            run_id=None,
            markdown="",
            text="from-workflow\n",
            ranked_items=[],
            warnings=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )

    store = DigestStore(tmp_path / "tool-agent-digest.db")
    store.init_schema()
    runner = _FakeToolAgentRunner()
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        tool_agent_runner=runner,
    )

    reply = asyncio.run(svc.handle_message_async("Give me today's AI digest"))

    assert reply == "from-workflow\n"
    assert len(captured) == 1
    assert runner.calls == []


def test_resolve_digest_request_timeframe_defaults_last_7_days_for_bilibili_channel() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest bilibili channel 285286947")

    assert req.bilibili_target_channels == ["285286947"]
    assert req.timeframe == "last_7_days"


def test_resolve_digest_request_preserves_explicit_timeframe_for_bilibili_channel() -> (
    None
):
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest bilibili channel 285286947 last 30 days")

    assert req.timeframe == "last_30_days"


def test_resolve_digest_request_no_timeframe_default_for_github_channel() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest github user acme")

    assert req.github_target_channels == ["acme"]
    assert req.timeframe is None


def test_history_intercept_stub_raises_even_with_fake_router(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called for history intercept stub")

    store = DigestStore(tmp_path / "history-stub.db")
    store.init_schema()
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="router should not run",
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async("search history for rag"))
    assert "No saved digests to search." in reply
    assert router.calls == []


_HISTORY_FIXTURE_DT = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


def _seed_history_github_digest(store: DigestStore) -> int:
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        collected_at=_HISTORY_FIXTURE_DT,
        content_confidence=ConfidenceLevel.HIGH,
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="a/b",
        source_name="GitHub",
        source_url=item.url,
        summary="Summary about transformers",
        why_it_matters="Why",
        background_knowledge="Background",
        follow_up_action=FollowUpAction.READ,
    )
    run_id = store.save_run(
        requested_at=_HISTORY_FIXTURE_DT,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[item], warnings=[], raw_count=1),
    )
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=1.0, selected=True, selection_reason="best")],
    )
    return store.save_digest(
        run_id,
        Digest(
            generated_at=_HISTORY_FIXTURE_DT,
            entries=[entry],
            topics=["RAG"],
            timeframe="today",
        ),
    )


def test_history_search_intercept_before_router(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called")

    store = DigestStore(tmp_path / "history-search.db")
    store.init_schema()
    digest_id = _seed_history_github_digest(store)
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="router should not run",
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async("search history for transformer"))
    assert f"d{digest_id}:r1" in reply
    assert "a/b" in reply
    assert router.calls == []

    routed = asyncio.run(svc.handle_message_async("show sources"))
    assert routed == "router should not run"
    assert len(router.calls) == 1


def test_history_open_intercept_before_router(tmp_path) -> None:
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called")

    store = DigestStore(tmp_path / "history-open.db")
    store.init_schema()
    digest_id = _seed_history_github_digest(store)
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="router should not run",
        )
    )
    svc = ChatService(
        store=store,
        workflow_runner=fake_runner,
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async(f"open history d{digest_id}:r1"))
    assert reply.startswith("Digest item 1: a/b")
    assert router.calls == []


def test_history_open_not_found_not_no_saved_digest(tmp_path) -> None:
    store = DigestStore(tmp_path / "history-open-miss.db")
    store.init_schema()
    _seed_history_github_digest(store)
    router = _FakeInterfaceRouter()
    svc = ChatService(
        store=store,
        workflow_runner=_unused_runner(),
        interface_router=router,
    )

    reply = asyncio.run(svc.handle_message_async("open history d9999:r1"))
    assert reply == "not found"
    assert NO_SAVED_DIGEST not in reply
    assert router.calls == []


def test_history_validation_errors_before_router(tmp_path) -> None:
    store = DigestStore(tmp_path / "history-validation.db")
    store.init_schema()
    router = _FakeInterfaceRouter()
    svc = ChatService(
        store=store,
        workflow_runner=_unused_runner(),
        interface_router=router,
    )

    bare = asyncio.run(svc.handle_message_async("search history"))
    assert "at least one search criterion" in bare
    assert NO_SAVED_DIGEST not in bare
    assert router.calls == []

    bad_source = asyncio.run(
        svc.handle_message_async("search history from arxiv")
    )
    assert "Unknown source" in bad_source
    assert NO_SAVED_DIGEST not in bad_source
    assert router.calls == []


def _unused_runner():
    async def fake_runner(_: DigestRequest) -> DigestResult:
        raise AssertionError("workflow_runner should not be called")

    return fake_runner


def test_history_streaming_search_before_router(tmp_path) -> None:
    store = DigestStore(tmp_path / "history-stream-search.db")
    store.init_schema()
    digest_id = _seed_history_github_digest(store)
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="router should not run",
        ),
        stream_events=[("", True, InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="router should not run",
        ))],
    )
    svc = ChatService(
        store=store,
        workflow_runner=_unused_runner(),
        interface_router=router,
    )

    chunks = asyncio.run(
        _collect_streaming(svc, "search history for transformer")
    )
    joined = "".join(chunks)
    assert f"d{digest_id}:r1" in joined
    assert router.calls == []


def test_history_streaming_open_before_router(tmp_path) -> None:
    store = DigestStore(tmp_path / "history-stream-open.db")
    store.init_schema()
    digest_id = _seed_history_github_digest(store)
    router = _FakeInterfaceRouter()
    svc = ChatService(
        store=store,
        workflow_runner=_unused_runner(),
        interface_router=router,
    )

    chunks = asyncio.run(
        _collect_streaming(svc, f"open history d{digest_id}:r1")
    )
    joined = "".join(chunks)
    assert "Digest item 1: a/b" in joined
    assert router.calls == []


def test_non_history_streaming_still_routes_through_router(tmp_path) -> None:
    store = DigestStore(tmp_path / "history-stream-route.db")
    store.init_schema()
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="stream routed",
        ),
        stream_events=[("", True, InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="stream routed",
        ))],
    )
    svc = ChatService(
        store=store,
        workflow_runner=_unused_runner(),
        interface_router=router,
    )

    chunks = asyncio.run(_collect_streaming(svc, "what trends do you see?"))
    assert "".join(chunks) == "stream routed"
    assert len(router.calls) == 1

