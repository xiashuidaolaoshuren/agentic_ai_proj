"""Local Gradio chat UI delegating to :class:`~ai_news_agent.chat.ChatService` (Task T13)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import gradio as gr

from ai_news_agent.chat import ChatService
from ai_news_agent.cli import (
    _FakeBilibiliConnector,
    _FakeDigestModel,
    _FakeGitHubConnector,
)
from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.connectors.bilibili import BilibiliConnector
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.graph.workflow import run_digest
from ai_news_agent.llm import build_chat_model
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore


_DEFAULT_CONNECTORS: tuple[str, ...] = ("github", "bilibili")


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


def _build_connectors(*, fake: bool) -> list[SourceConnector]:
    if fake:
        factories: dict[str, SourceConnector] = {
            "github": _FakeGitHubConnector(),
            "bilibili": _FakeBilibiliConnector(),
        }
    else:
        factories = {
            "github": GitHubConnector(),
            "bilibili": BilibiliConnector(),
        }
    return [factories[name] for name in _DEFAULT_CONNECTORS]


def _build_service(*, fake: bool, db_path: Path) -> ChatService:
    store = DigestStore(db_path)
    store.init_schema()

    if fake:
        model: Any = _FakeDigestModel()
    else:
        model = build_chat_model()

    async def workflow_runner(req: DigestRequest) -> DigestResult:
        # Fresh connectors each run: ``_run_digest_async`` closes HTTP clients in ``finally``.
        connectors = _build_connectors(fake=fake)
        return await _run_digest_async(req, store=store, connectors=connectors, model=model)

    return ChatService(
        store=store,
        workflow_runner=workflow_runner,
        chat_model=model,
    )


def create_app(service: ChatService) -> gr.Blocks:
    """Build a thin Gradio :class:`~gradio.ChatInterface` around ``service``."""

    async def respond(message: str, _history: list) -> str:
        return await service.handle_message_async(message)

    return gr.ChatInterface(
        fn=respond,
        title="AI News Research Agent",
        description=(
            'Ask for an AI news digest (e.g. mention "digest") or follow up with concrete '
            'requests like "show sources", ranking hints, or caveats.'
        ),
        examples=[
            "Give me today's AI digest",
            "show sources",
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_news_agent.app.gradio_app",
        description="Launch the AI News Research Agent Gradio chat UI.",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Offline deterministic mode (fake connectors and summarizer; no API keys).",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.cwd() / "digest.sqlite",
        help="SQLite path for DigestStore (default: ./digest.sqlite in cwd)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="HTTP port for the local server (default: 7860)",
    )

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        service = _build_service(fake=ns.fake, db_path=ns.db_path)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    demo = create_app(service)
    demo.launch(server_port=ns.port)
    return 0


__all__ = ["create_app", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
