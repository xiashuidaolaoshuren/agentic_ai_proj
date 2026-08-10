"""Local Gradio chat UI delegating to :class:`~ai_news_agent.chat.ChatService` (Task T13)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

import gradio as gr

from ai_news_agent.chat import ChatService
from ai_news_agent.env import (
    configure_bilibili_network_from_env,
    load_local_env,
    log_bilibili_env_diagnostics,
)
from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.graph.workflow import run_digest, run_digest_streaming
from ai_news_agent.llm import build_chat_model, build_tool_chat_model
from ai_news_agent.logging_setup import configure_logging, get_logger
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    FakeDigestModel,
    build_connector_factory,
    build_connectors,
)
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools import build_interface_tool_router

_UI_ERROR_MESSAGE = (
    "Something went wrong while processing your request. "
    "Please check the terminal or log file for details and try again."
)

_EXAMPLE_ROWS: list[list] = [
    ["Give me today's AI digest", list(DEFAULT_SOURCE_NAMES)],
    ["Give me today's AI digest from github only", list(DEFAULT_SOURCE_NAMES)],
    ["Digest https://github.com/langchain-ai/langgraph", list(DEFAULT_SOURCE_NAMES)],
    ["Digest bilibili channel 285286947", list(DEFAULT_SOURCE_NAMES)],
    ["show sources", list(DEFAULT_SOURCE_NAMES)],
]

logger = get_logger("gradio")

_FAKE_TOOL_AGENT_REPLY = (
    "Offline fake tool agent: use structured prompts like "
    '"show sources", "study first", or "show caveats".'
)


class _FakeToolAgentRunner:
    """Deterministic tool agent for Gradio --fake mode (no tool-calling model)."""

    async def run(self, question: str) -> str:  # noqa: ARG002
        return _FAKE_TOOL_AGENT_REPLY

    async def run_streaming(
        self, question: str
    ) -> AsyncIterator[tuple[str, bool, str | None]]:
        del question
        yield "Calling load_latest_digest…", False, None
        yield "Done load_latest_digest: Loaded latest digest.", False, None
        yield "", True, _FAKE_TOOL_AGENT_REPLY


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
    on_stage: Callable[[str], None] | None = None,
) -> DigestResult:
    del on_stage
    try:
        return await run_digest(
            req,
            connectors=list(connectors),
            model=model,
            store=store,
        )
    finally:
        await _aclose_connectors(connectors)


async def _run_digest_streaming_async(
    req: DigestRequest,
    *,
    store: DigestStore,
    connectors: Sequence[SourceConnector],
    model: Any,
    on_stage: Callable[[str], None] | None = None,
) -> AsyncIterator[tuple[str, bool, DigestResult | None]]:
    del on_stage
    try:
        async for event in run_digest_streaming(
            req,
            connectors=list(connectors),
            model=model,
            store=store,
        ):
            yield event
    finally:
        await _aclose_connectors(connectors)


def _build_service(*, fake: bool, db_path: Path) -> ChatService:
    store = DigestStore(db_path)
    store.init_schema()

    if fake:
        model: Any = FakeDigestModel()
        tool_agent_runner: Any = _FakeToolAgentRunner()
        interface_router: Any = None
    else:
        model = build_chat_model()
        tool_model = build_tool_chat_model()
        tool_agent_runner = None
        interface_router = None  # set after workflow closures are defined

    def _names_from(req: DigestRequest) -> list[str]:
        return (
            list(req.connector_names)
            if req.connector_names is not None
            else list(DEFAULT_SOURCE_NAMES)
        )

    def build_connectors_fn(req: DigestRequest) -> Sequence[SourceConnector]:
        return build_connectors(fake=fake, names=_names_from(req))

    async def workflow_runner(
        req: DigestRequest,
        on_stage: Callable[[str], None] | None = None,
    ) -> DigestResult:
        if not fake:
            load_local_env(force_reload=True)
            configure_bilibili_network_from_env(logger)
        connectors = build_connectors(fake=fake, names=_names_from(req))
        return await _run_digest_async(
            req,
            store=store,
            connectors=connectors,
            model=model,
            on_stage=on_stage,
        )

    async def streaming_workflow_runner(
        req: DigestRequest,
        on_stage: Callable[[str], None] | None = None,
    ) -> AsyncIterator[tuple[str, bool, DigestResult | None]]:
        if not fake:
            load_local_env(force_reload=True)
            configure_bilibili_network_from_env(logger)
        connectors = build_connectors(fake=fake, names=_names_from(req))
        async for event in _run_digest_streaming_async(
            req,
            store=store,
            connectors=connectors,
            model=model,
            on_stage=on_stage,
        ):
            yield event

    if not fake:
        interface_router = build_interface_tool_router(
            store=store,
            workflow_runner=workflow_runner,
            streaming_workflow_runner=streaming_workflow_runner,
            tool_model=tool_model,
            digest_model=model,
            github_factory=build_connector_factory(fake=fake, name="github"),
            bilibili_factory=build_connector_factory(fake=fake, name="bilibili"),
            build_connectors_fn=build_connectors_fn,
            interface_name="gradio",
        )

    return ChatService(
        store=store,
        workflow_runner=workflow_runner,
        streaming_workflow_runner=streaming_workflow_runner,
        chat_model=model,
        tool_agent_runner=tool_agent_runner,
        interface_router=interface_router,
    )


def create_app(service: ChatService) -> gr.Blocks:
    """Build a Gradio chat UI with session-sticky source toggles and streaming."""

    async def respond_stream(
        message: str,
        _history: list,
        enabled_sources: list[str],
    ) -> AsyncIterator[str]:
        if not enabled_sources:
            yield "Please enable at least one source (GitHub or Bilibili)."
            return
        try:
            async for partial in service.handle_message_streaming_async(
                message,
                session_connector_names=enabled_sources,
            ):
                yield partial
        except Exception:
            logger.exception("gradio request failed")
            yield _UI_ERROR_MESSAGE

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
        chat = gr.ChatInterface(
            fn=respond_stream,
            additional_inputs=[source_toggles],
            examples=None,
        )
        with gr.Accordion("Example prompts", open=False):
            gr.Examples(
                examples=_EXAMPLE_ROWS,
                inputs=[chat.textbox, source_toggles],
                outputs=chat.chatbot,
                fn=respond_stream,
                cache_examples=False,
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
    if not ns.fake:
        log_bilibili_env_diagnostics(logger)
        configure_bilibili_network_from_env(logger)

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
