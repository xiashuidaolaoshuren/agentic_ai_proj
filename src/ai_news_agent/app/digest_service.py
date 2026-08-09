"""Persistent local HTTP digest service for OpenClaw (warm model + workflow)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

from ai_news_agent.adapters.openclaw import (
    normalize_output_language_hint,
    normalize_output_style_hint,
    normalize_source_hint,
    normalize_timeframe_hint,
    normalize_topic_hint,
    resolve_openclaw_digest_request,
)
from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.env import configure_bilibili_network_from_env, load_local_env
from ai_news_agent.followup_structured import (
    NO_SAVED_DIGEST,
    OPENCLAW_GUIDANCE_FALLBACK,
    handle_openclaw_structured_followup,
)
from ai_news_agent.graph.state import DigestResult
from ai_news_agent.graph.workflow import run_digest_instrumented
from ai_news_agent.llm import build_chat_model, build_tool_chat_model
from ai_news_agent.logging_setup import configure_logging, get_logger
from ai_news_agent.models import utcnow
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    FakeDigestModel,
    build_connector_factory,
    build_connectors,
)
from ai_news_agent.storage import DigestStore
from ai_news_agent.telemetry import DigestStageTimer, new_correlation_id
from ai_news_agent.tools import build_interface_tool_router
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
)

logger = get_logger("digest_service")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765


def build_digest_request_payload(
    *,
    message: str | None = None,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
) -> dict[str, Any]:
    """Serialize OpenClaw hints into a JSON-friendly digest request body."""
    style = normalize_output_style_hint(output_style_hint)
    language = normalize_output_language_hint(output_language_hint)
    style_fields: dict[str, str] = {}
    if style is not None:
        style_fields["output_style"] = style
    if language is not None:
        style_fields["output_language"] = language

    if message is not None and message.strip():
        return {"message": message.strip(), **style_fields}

    payload: dict[str, Any] = {
        "timeframe": normalize_timeframe_hint(timeframe_hint),
        "sources": ",".join(normalize_source_hint(sources_hint)),
        **style_fields,
    }
    topics = normalize_topic_hint(topics_hint)
    if topics is not None:
        payload["topics"] = topics
    return payload


def _style_hints_from_body(body: dict[str, Any]) -> dict[str, str | None]:
    output_style = body.get("output_style")
    output_language = body.get("output_language")
    return {
        "output_style_hint": str(output_style) if output_style is not None else None,
        "output_language_hint": (
            str(output_language) if output_language is not None else None
        ),
    }


def _digest_request_from_json(body: dict[str, Any]) -> DigestRequest:
    style_hints = _style_hints_from_body(body)
    message = body.get("message")
    if message is not None and str(message).strip():
        sources = body.get("sources")
        sources_hint = str(sources) if sources is not None else None
        return resolve_openclaw_digest_request(
            message=str(message).strip(),
            sources_hint=sources_hint,
            **style_hints,
        )

    sources = body.get("sources")
    sources_hint = str(sources) if sources is not None else None
    topics = body.get("topics")
    topics_hint: str | None
    if topics is None:
        topics_hint = None
    elif isinstance(topics, list):
        topics_hint = ",".join(str(t) for t in topics)
    else:
        topics_hint = str(topics)
    timeframe = body.get("timeframe")
    timeframe_hint = str(timeframe) if timeframe is not None else None
    return resolve_openclaw_digest_request(
        timeframe_hint=timeframe_hint,
        sources_hint=sources_hint,
        topics_hint=topics_hint,
        **style_hints,
    )


async def _aclose_connectors(connectors: Sequence[SourceConnector]) -> None:
    for connector in connectors:
        closer = getattr(connector, "aclose", None)
        if closer is not None:
            await closer()


def _digest_result_from_interface(
    agent_result: InterfaceAgentResult,
    request: DigestRequest,
) -> DigestResult:
    now = utcnow()
    return DigestResult(
        request=request,
        digest=agent_result.digest,
        run_id=agent_result.run_id,
        markdown=agent_result.text,
        text=agent_result.text,
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=now,
        finished_at=now,
    )


def _interface_result_to_followup_outcome(
    result: InterfaceAgentResult,
) -> dict[str, object]:
    if result.text == NO_SAVED_DIGEST:
        return {
            "text": NO_SAVED_DIGEST,
            "run_id": None,
            "path": "no_digest",
        }
    if result.kind is InterfaceAgentResultKind.STRUCTURED:
        return {
            "text": result.text,
            "run_id": result.run_id,
            "path": "structured",
        }
    if result.kind in (
        InterfaceAgentResultKind.CONVERSATIONAL,
        InterfaceAgentResultKind.FALLBACK,
    ):
        return {
            "text": OPENCLAW_GUIDANCE_FALLBACK,
            "run_id": result.run_id,
            "path": "guidance",
        }
    return {
        "text": OPENCLAW_GUIDANCE_FALLBACK,
        "run_id": result.run_id,
        "path": "guidance",
    }


def build_followup_request_payload(*, message: str) -> dict[str, Any]:
    """Serialize an OpenClaw structured follow-up request body."""
    return {"message": message.strip()}


class DigestServiceRuntime:
    """Warm digest runtime: store schema, model, and connector factory."""

    def __init__(
        self,
        *,
        fake: bool,
        db_path: Path,
        interface_router: Any | None = None,
    ) -> None:
        self.fake = fake
        self.db_path = db_path
        self._store = DigestStore(db_path)
        self._store.init_schema()
        self._active_on_stage: Callable[[str], None] | None = None
        self._active_correlation_id: str | None = None
        self._interface_router: Any | None = None
        self._workflow_runner: Any = None
        if fake:
            self._model: Any = FakeDigestModel()
        else:
            self._model = build_chat_model()
            tool_model = build_tool_chat_model()

            def build_connectors_fn(req: DigestRequest) -> Sequence[SourceConnector]:
                names = (
                    list(req.connector_names)
                    if req.connector_names is not None
                    else list(DEFAULT_SOURCE_NAMES)
                )
                return build_connectors(fake=False, names=names)

            async def workflow_runner(req: DigestRequest) -> DigestResult:
                load_local_env(force_reload=True)
                configure_bilibili_network_from_env(logger)
                names = (
                    list(req.connector_names)
                    if req.connector_names is not None
                    else list(DEFAULT_SOURCE_NAMES)
                )
                connectors = build_connectors(fake=False, names=names)
                try:
                    result = await run_digest_instrumented(
                        req,
                        connectors=list(connectors),
                        model=self._model,
                        store=self._store,
                        on_stage=self._active_on_stage,
                    )
                finally:
                    await _aclose_connectors(connectors)
                return result

            self._workflow_runner = workflow_runner
            if interface_router is not None:
                self._interface_router = interface_router
            else:
                self._interface_router = build_interface_tool_router(
                    store=self._store,
                    workflow_runner=workflow_runner,
                    streaming_workflow_runner=None,
                    tool_model=tool_model,
                    digest_model=self._model,
                    github_factory=build_connector_factory(fake=False, name="github"),
                    bilibili_factory=build_connector_factory(
                        fake=False,
                        name="bilibili",
                    ),
                    build_connectors_fn=build_connectors_fn,
                    interface_name="openclaw",
                )
        logger.info(
            "digest service runtime ready fake=%s db_path=%s",
            fake,
            db_path,
        )

    async def run_digest(
        self,
        request: DigestRequest,
        *,
        correlation_id: str,
        message: str = "",
    ) -> tuple[DigestResult, dict[str, float], float]:
        if self.fake:
            names = (
                list(request.connector_names)
                if request.connector_names is not None
                else list(DEFAULT_SOURCE_NAMES)
            )
            connectors = build_connectors(fake=self.fake, names=names)
            t0 = time.perf_counter()

            with DigestStageTimer(correlation_id, logger_name="digest_service") as timer:
                try:
                    result = await run_digest_instrumented(
                        request,
                        connectors=list(connectors),
                        model=self._model,
                        store=self._store,
                        on_stage=timer.mark,
                    )
                finally:
                    await _aclose_connectors(connectors)

            elapsed = time.perf_counter() - t0
            logger.info(
                "digest_service completed correlation_id=%s run_id=%s elapsed_s=%.2f",
                correlation_id,
                result.run_id,
                elapsed,
            )
            return result, dict(timer.stages), elapsed

        load_local_env(force_reload=True)
        configure_bilibili_network_from_env(logger)
        self._active_correlation_id = correlation_id
        t0 = time.perf_counter()
        with DigestStageTimer(correlation_id, logger_name="digest_service") as timer:
            self._active_on_stage = timer.mark
            agent_result = await self._interface_router.route(
                message=message,
                digest_request=request,
                correlation_id=correlation_id,
                on_stage=timer.mark,
            )
        elapsed = time.perf_counter() - t0
        result = _digest_result_from_interface(agent_result, request)
        logger.info(
            "digest_service completed correlation_id=%s run_id=%s elapsed_s=%.2f",
            correlation_id,
            result.run_id,
            elapsed,
        )
        return result, dict(timer.stages), elapsed

    def run_followup(
        self,
        *,
        message: str,
        correlation_id: str,
    ) -> dict[str, object]:
        if self.fake:
            outcome = handle_openclaw_structured_followup(
                message=message,
                store=self._store,
            )
        else:
            outcome = asyncio.run(
                self._run_followup_live(
                    message=message,
                    correlation_id=correlation_id,
                )
            )
        logger.info(
            "followup_service completed correlation_id=%s run_id=%s path=%s",
            correlation_id,
            outcome.get("run_id"),
            outcome.get("path"),
        )
        return outcome

    async def _run_followup_live(
        self,
        *,
        message: str,
        correlation_id: str,
    ) -> dict[str, object]:
        agent_result = await self._interface_router.route(
            message=message,
            correlation_id=correlation_id,
        )
        return _interface_result_to_followup_outcome(agent_result)


class DigestServiceServer:
    """Threaded HTTP server exposing ``/health``, ``/digest``, and ``/followup``."""

    def __init__(
        self,
        *,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        db_path: Path,
        fake: bool = False,
        interface_router: Any | None = None,
    ) -> None:
        self.host = host
        self.port: int | None = port if port != 0 else None
        self.db_path = db_path
        self.fake = fake
        self._runtime = DigestServiceRuntime(
            fake=fake,
            db_path=db_path,
            interface_router=interface_router,
        )
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def serve_forever(self) -> None:
        handler = _make_handler(self._runtime)
        bind_port = self.port if self.port is not None else 0
        self._httpd = ThreadingHTTPServer((self.host, bind_port), handler)
        self.port = int(self._httpd.server_address[1])
        logger.info("digest service listening on http://%s:%s", self.host, self.port)
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _make_handler(runtime: DigestServiceRuntime) -> type[BaseHTTPRequestHandler]:
    class DigestServiceHandler(BaseHTTPRequestHandler):
        server_version = "DigestService/1.0"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            logger.debug("http " + format, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._json_response(
                    200,
                    {"status": "ok", "fake": runtime.fake},
                )
                return
            self._json_response(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.rstrip("/")
            if path == "/followup":
                self._handle_followup_post()
                return
            if path != "/digest":
                self._json_response(404, {"error": "not found"})
                return

            self._handle_digest_post()

        def _handle_digest_post(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid JSON body"})
                return

            correlation_id = str(body.get("correlation_id") or new_correlation_id())
            use_fake = bool(body.get("fake", runtime.fake))
            if use_fake != runtime.fake:
                self._json_response(
                    400,
                    {
                        "error": (
                            f"service fake={runtime.fake} but request fake={use_fake}; "
                            "restart service with matching mode"
                        ),
                    },
                )
                return

            try:
                request = _digest_request_from_json(body)
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
                return

            message = str(body.get("message") or "").strip()
            try:
                result, stages, elapsed = asyncio.run(
                    runtime.run_digest(
                        request,
                        correlation_id=correlation_id,
                        message=message,
                    )
                )
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "digest_service failed correlation_id=%s",
                    correlation_id,
                )
                self._json_response(
                    500,
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "correlation_id": correlation_id,
                    },
                )
                return

            text = result.text
            self._json_response(
                200,
                {
                    "text": text,
                    "run_id": result.run_id,
                    "correlation_id": correlation_id,
                    "elapsed_s": round(elapsed, 3),
                    "stages": stages,
                },
            )

        def _handle_followup_post(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid JSON body"})
                return

            message = body.get("message")
            if message is None or not str(message).strip():
                self._json_response(400, {"error": "message is required"})
                return

            correlation_id = str(body.get("correlation_id") or new_correlation_id())
            outcome = runtime.run_followup(
                message=str(message).strip(),
                correlation_id=correlation_id,
            )
            self._json_response(
                200,
                {
                    "text": outcome["text"],
                    "run_id": outcome["run_id"],
                    "path": outcome["path"],
                    "correlation_id": correlation_id,
                },
            )

        def _json_response(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DigestServiceHandler


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """CLI entry: ``python -m ai_news_agent.app.digest_service`` or ``ai-news-agent service``."""
    del stdout
    load_local_env()
    configure_bilibili_network_from_env(logger)
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="ai-news-agent service",
        description="Run the persistent local digest HTTP service.",
    )
    parser.add_argument("--host", default=_DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Bind port (default: {_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.cwd() / "digest.sqlite",
        help="SQLite path for DigestStore",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Offline deterministic mode (no network, no OpenAI key)",
    )

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    server = DigestServiceServer(
        host=ns.host,
        port=ns.port,
        db_path=ns.db_path,
        fake=ns.fake,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("digest service shutting down")
        server.shutdown()
    return 0


__all__ = [
    "DigestServiceRuntime",
    "DigestServiceServer",
    "build_digest_request_payload",
    "build_followup_request_payload",
    "main",
]
