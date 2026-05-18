"""Tests for follow-up chat service (Task T11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ai_news_agent.chat import ChatService
from ai_news_agent.connectors.base import ConnectorResult
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
