"""Tests for follow-up chat service (Task T11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ai_news_agent.chat import ChatService
from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.models import (
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

    req = resolve_digest_request("Digest bilibili channel 123456789")

    assert req.bilibili_target_channels == ["123456789"]
    assert req.timeframe == "last_7_days"


def test_resolve_digest_request_preserves_explicit_timeframe_for_bilibili_channel() -> (
    None
):
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest bilibili channel 123456789 last 30 days")

    assert req.timeframe == "last_30_days"


def test_resolve_digest_request_no_timeframe_default_for_github_channel() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest github user acme")

    assert req.github_target_channels == ["acme"]
    assert req.timeframe is None
