"""Milestone 1 acceptance smoke tests (Task T14).

Fast, deterministic checks that mirror offline CLI + chat UX without live APIs or Gradio imports.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ai_news_agent.chat import ChatService
from ai_news_agent.cli import (
    main as cli_main,
)
from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.graph.workflow import run_digest
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import DEFAULT_SOURCE_NAMES, FakeDigestModel, build_connectors
from ai_news_agent.storage import DigestStore


async def _aclose_connectors(connectors: Sequence[SourceConnector]) -> None:
    for c in connectors:
        closer = getattr(c, "aclose", None)
        if closer is not None:
            await closer()


async def _run_digest_async(
    req: DigestRequest,
    *,
    store: DigestStore,
    connectors: Sequence[SourceConnector],
    model: Any,
) -> DigestResult:
    try:
        return await run_digest(
            req,
            connectors=list(connectors),
            model=model,
            store=store,
        )
    finally:
        await _aclose_connectors(connectors)


def _build_fake_chat_service(db_path: Path) -> ChatService:
    """Mirror offline wiring used by Gradio ``--fake`` (without importing ``gradio_app``)."""
    store = DigestStore(db_path)
    store.init_schema()
    model: Any = FakeDigestModel()

    async def workflow_runner(req: DigestRequest) -> DigestResult:
        connectors: list[SourceConnector] = build_connectors(
            fake=True,
            names=list(DEFAULT_SOURCE_NAMES),
        )
        return await _run_digest_async(req, store=store, connectors=connectors, model=model)

    return ChatService(store=store, workflow_runner=workflow_runner, chat_model=model)


def test_mvp_smoke_chat_digest_then_sources(tmp_path: Path) -> None:
    svc = _build_fake_chat_service(tmp_path / "mvp_chat.db")

    digest_reply = asyncio.run(svc.handle_message_async("Give me today's AI digest"))
    assert "AI News Digest" in digest_reply
    assert "Fake Juya bulletin" in digest_reply

    sources_reply = asyncio.run(svc.handle_message_async("show sources"))
    assert "Sources from the latest digest" in sources_reply
    assert "https://daily.juya.uk/fake-juya" in sources_reply


def test_mvp_smoke_cli_fake_digest(tmp_path: Path) -> None:
    buf = io.StringIO()
    code = cli_main(
        [
            "digest",
            "--fake",
            "--db-path",
            str(tmp_path / "mvp_cli.db"),
            "--sources",
            "github,bilibili",
            "--topics",
            "RAG",
        ],
        stdout=buf,
    )
    out = buf.getvalue()
    assert code == 0
    assert "AI News Digest" in out
    assert "Fake GitHub repo" in out
