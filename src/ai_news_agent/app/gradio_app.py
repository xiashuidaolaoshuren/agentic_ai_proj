"""Local Gradio chat UI delegating to :class:`~ai_news_agent.chat.ChatService` (Task T13)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import gradio as gr

from ai_news_agent.chat import ChatService
from ai_news_agent.env import load_local_env
from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.graph.workflow import run_digest
from ai_news_agent.llm import build_chat_model
from ai_news_agent.logging_setup import configure_logging, get_logger
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    FakeDigestModel,
    build_connectors,
)
from ai_news_agent.storage import DigestStore

_UI_ERROR_MESSAGE = (
    "Something went wrong while processing your request. "
    "Please check the terminal or log file for details and try again."
)

logger = get_logger("gradio")


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


def _build_service(*, fake: bool, db_path: Path) -> ChatService:
    store = DigestStore(db_path)
    store.init_schema()

    if fake:
        model: Any = FakeDigestModel()
    else:
        model = build_chat_model()

    async def workflow_runner(req: DigestRequest) -> DigestResult:
        connectors = build_connectors(fake=fake, names=DEFAULT_SOURCE_NAMES)
        return await _run_digest_async(req, store=store, connectors=connectors, model=model)

    return ChatService(
        store=store,
        workflow_runner=workflow_runner,
        chat_model=model,
    )


def create_app(service: ChatService) -> gr.Blocks:
    """Build a thin Gradio chat UI with session-sticky source toggles."""

    async def respond(message: str, _history: list, enabled_sources: list[str]) -> str:
        if not enabled_sources:
            return "Please enable at least one source (GitHub or Bilibili)."
        try:
            return await service.handle_message_async(
                message,
                session_connector_names=enabled_sources,
            )
        except Exception:
            logger.exception("gradio request failed")
            return _UI_ERROR_MESSAGE

    with gr.Blocks(title="AI News Research Agent") as demo:
        gr.Markdown(
            "# AI News Research Agent\n"
            'Ask for an AI news digest (e.g. mention "digest"). Include GitHub repo URLs, '
            "Bilibili video URLs, or channel hints in the same message for targeted runs. "
            'Follow up with "show sources", ranking hints, or "show caveats".'
        )
        source_toggles = gr.CheckboxGroup(
            choices=list(DEFAULT_SOURCE_NAMES),
            value=list(DEFAULT_SOURCE_NAMES),
            label="Sources",
            info=(
                "Session filters for digest runs. Override one request with phrases like "
                "'github only' or 'bilibili only'."
            ),
        )
        default_sources = list(DEFAULT_SOURCE_NAMES)
        gr.ChatInterface(
            fn=respond,
            additional_inputs=[source_toggles],
            examples=[
                ["Give me today's AI digest", default_sources],
                ["Give me today's AI digest from github only", default_sources],
                [
                    "Digest https://github.com/langchain-ai/langgraph",
                    default_sources,
                ],
                ["Digest bilibili channel 123456789", default_sources],
                ["show sources", default_sources],
            ],
        )

    return demo


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

    load_local_env()
    configure_logging()
    logger.info(
        "starting gradio fake=%s db_path=%s port=%s",
        ns.fake,
        ns.db_path,
        ns.port,
    )

    try:
        service = _build_service(fake=ns.fake, db_path=ns.db_path)
    except ValueError as e:
        logger.exception("failed to build service")
        print(str(e), file=sys.stderr)
        return 2

    demo = create_app(service)
    logger.info("gradio launch on port=%s", ns.port)
    demo.launch(server_port=ns.port)
    return 0


__all__ = ["create_app", "main", "_UI_ERROR_MESSAGE"]

if __name__ == "__main__":
    raise SystemExit(main())
