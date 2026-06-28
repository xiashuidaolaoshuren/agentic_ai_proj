"""Thin HTTP client for the local digest service (OpenClaw skill delegation)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TextIO

import httpx

from ai_news_agent.adapters.openclaw import build_digest_cli_argv
from ai_news_agent.app.digest_service import build_digest_request_payload, build_followup_request_payload
from ai_news_agent.logging_setup import configure_logging, get_logger
from ai_news_agent.telemetry import new_correlation_id

logger = get_logger("openclaw_client")

_DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"
_ENV_SERVICE_URL = "AI_NEWS_AGENT_SERVICE_URL"


def resolve_service_url(explicit: str | None = None) -> str:
    """Resolve digest service base URL from arg, env, or default."""
    if explicit is not None and explicit.strip():
        return explicit.strip().rstrip("/")
    env = os.environ.get(_ENV_SERVICE_URL, "").strip()
    if env:
        return env.rstrip("/")
    return _DEFAULT_SERVICE_URL


def request_digest_markdown(
    service_url: str,
    *,
    message: str | None = None,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
    fake: bool = False,
    correlation_id: str | None = None,
    timeout_s: float = 600.0,
) -> str:
    """POST digest request to the local service and return markdown text."""
    cid = correlation_id or new_correlation_id()
    payload = build_digest_request_payload(
        message=message,
        timeframe_hint=timeframe_hint,
        sources_hint=sources_hint,
        topics_hint=topics_hint,
        output_style_hint=output_style_hint,
        output_language_hint=output_language_hint,
    )
    payload["fake"] = fake
    payload["correlation_id"] = cid

    url = f"{service_url.rstrip('/')}/digest"
    logger.info(
        "openclaw_client request_start correlation_id=%s url=%s fake=%s",
        cid,
        url,
        fake,
    )
    t0 = httpx.Timeout(timeout_s)
    with httpx.Client(timeout=t0) as client:
        response = client.post(url, json=payload)

    if response.status_code != 200:
        detail = response.text[:500]
        try:
            body = response.json()
            detail = str(body.get("error", detail))
        except ValueError:
            pass
        raise RuntimeError(
            f"digest service returned HTTP {response.status_code}: {detail}"
        )

    data = response.json()
    text = str(data.get("text", ""))
    logger.info(
        "openclaw_client request_done correlation_id=%s service_elapsed_s=%s",
        data.get("correlation_id", cid),
        data.get("elapsed_s"),
    )
    return text


def request_followup_text(
    service_url: str,
    *,
    message: str,
    correlation_id: str | None = None,
    timeout_s: float = 60.0,
) -> str:
    """POST structured follow-up request to the local service and return reply text."""
    cid = correlation_id or new_correlation_id()
    payload = build_followup_request_payload(message=message)
    payload["correlation_id"] = cid

    url = f"{service_url.rstrip('/')}/followup"
    logger.info(
        "openclaw_client followup_start correlation_id=%s url=%s",
        cid,
        url,
    )
    with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
        response = client.post(url, json=payload)

    if response.status_code != 200:
        detail = response.text[:500]
        try:
            body = response.json()
            detail = str(body.get("error", detail))
        except ValueError:
            pass
        raise RuntimeError(
            f"digest service returned HTTP {response.status_code}: {detail}"
        )

    data = response.json()
    text = str(data.get("text", ""))
    logger.info(
        "openclaw_client followup_done correlation_id=%s path=%s",
        data.get("correlation_id", cid),
        data.get("path"),
    )
    return text


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """CLI: ``ai-news-agent openclaw-digest`` — prints markdown digest to stdout."""
    configure_logging()
    out = stdout or sys.stdout

    parser = argparse.ArgumentParser(
        prog="ai-news-agent openclaw-digest",
        description="Request a digest from the local warm digest service.",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Natural-language digest request (targeted URL/BV/channel or broad digest)",
    )
    parser.add_argument(
        "--timeframe",
        default=None,
        help="Timeframe hint (today, last_7_days, …)",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated sources (github, bilibili)",
    )
    parser.add_argument(
        "--topics",
        default=None,
        help="Comma-separated topics; omit for built-in defaults",
    )
    parser.add_argument(
        "--output-style",
        default=None,
        help="Digest output style (editorial/newsletter or default bulletin)",
    )
    parser.add_argument(
        "--output-language",
        default=None,
        help="BCP-47 output language hint (e.g. zh-CN)",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Request fake/offline digest from service",
    )
    parser.add_argument(
        "--service-url",
        default=None,
        help=f"Digest service base URL (default: env {_ENV_SERVICE_URL} or {_DEFAULT_SERVICE_URL})",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="Optional correlation id for latency tracing",
    )

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    service_url = resolve_service_url(ns.service_url)

    try:
        text = request_digest_markdown(
            service_url,
            message=ns.message,
            timeframe_hint=ns.timeframe,
            sources_hint=ns.sources,
            topics_hint=ns.topics,
            output_style_hint=ns.output_style,
            output_language_hint=ns.output_language,
            fake=ns.fake,
            correlation_id=ns.correlation_id,
        )
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("openclaw_client failed")
        print(str(exc), file=sys.stderr)
        return 1

    if not text.endswith("\n"):
        text += "\n"
    out.write(text)
    return 0


def followup_main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """CLI: ``ai-news-agent openclaw-followup`` — prints structured follow-up text."""
    configure_logging()
    out = stdout or sys.stdout

    parser = argparse.ArgumentParser(
        prog="ai-news-agent openclaw-followup",
        description="Request structured follow-up from the local warm digest service.",
    )
    parser.add_argument(
        "--message",
        required=True,
        help="Structured follow-up phrase (show sources, study first, show caveats)",
    )
    parser.add_argument(
        "--service-url",
        default=None,
        help=f"Digest service base URL (default: env {_ENV_SERVICE_URL} or {_DEFAULT_SERVICE_URL})",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="Optional correlation id for latency tracing",
    )

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    service_url = resolve_service_url(ns.service_url)

    try:
        text = request_followup_text(
            service_url,
            message=ns.message,
            correlation_id=ns.correlation_id,
        )
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("openclaw_followup failed")
        print(str(exc), file=sys.stderr)
        return 1

    if not text.endswith("\n"):
        text += "\n"
    out.write(text)
    return 0


def build_openclaw_digest_argv(
    *,
    message: str | None = None,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
    fake: bool = False,
) -> list[str]:
    """Build argv for ``openclaw-digest`` mirroring digest CLI flag shapes."""
    if message is not None and message.strip():
        argv = ["openclaw-digest", "--message", message.strip()]
        if output_style_hint:
            argv.extend(["--output-style", output_style_hint])
        if output_language_hint:
            argv.extend(["--output-language", output_language_hint])
        if fake:
            argv.append("--fake")
        return argv

    argv = ["openclaw-digest"]
    digest_argv = build_digest_cli_argv(
        timeframe_hint=timeframe_hint,
        sources_hint=sources_hint,
        topics_hint=topics_hint,
        output_style_hint=output_style_hint,
        output_language_hint=output_language_hint,
    )
    idx = 0
    while idx < len(digest_argv):
        token = digest_argv[idx]
        if token.startswith("--") and idx + 1 < len(digest_argv):
            argv.extend([token, digest_argv[idx + 1]])
            idx += 2
            continue
        idx += 1
    if fake:
        argv.append("--fake")
    return argv


def build_openclaw_followup_argv(*, message: str) -> list[str]:
    """Build argv for ``openclaw-followup`` with a quoted user message token."""
    return ["openclaw-followup", "--message", message.strip()]


__all__ = [
    "build_openclaw_digest_argv",
    "build_openclaw_followup_argv",
    "followup_main",
    "main",
    "request_digest_markdown",
    "request_followup_text",
    "resolve_service_url",
]
