"""Gradio UI tests for source toggles and request wiring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ai_news_agent.app.gradio_app import create_app
from ai_news_agent.chat import ChatService
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore


def test_create_app_builds_checkbox_group_and_respond_uses_session_sources(tmp_path) -> None:
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

    store = DigestStore(tmp_path / "gradio.db")
    store.init_schema()
    svc = ChatService(store=store, workflow_runner=fake_runner)
    demo = create_app(svc)

    assert demo is not None

    reply = asyncio.run(
        svc.handle_message_async(
            "Give me today's AI digest",
            session_connector_names=["bilibili"],
        )
    )
    assert reply == "ok\n"
    assert captured[0].connector_names == ["bilibili"]
