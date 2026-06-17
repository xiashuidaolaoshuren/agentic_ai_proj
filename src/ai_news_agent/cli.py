"""CLI smoke entry point for digest generation (Task T12).

OpenClaw-friendly shape::

    python -m ai_news_agent.cli digest --timeframe today --sources github,bilibili

Use ``--fake`` for deterministic offline runs (tests, CI).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from ai_news_agent.connectors.base import SourceConnector
from ai_news_agent.env import configure_bilibili_network_from_env, load_local_env
from ai_news_agent.graph.workflow import run_digest
from ai_news_agent.llm import build_chat_model
from ai_news_agent.logging_setup import configure_logging, get_logger
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    FakeDigestModel,
    build_connectors,
    normalize_source_names,
    parse_sources_csv,
)
from ai_news_agent.storage import DigestStore

# Backward-compatible aliases for tests and Gradio imports.
from ai_news_agent.sources import (
    FakeBilibiliConnector as _FakeBilibiliConnector,
    FakeDigestModel as _FakeDigestModel,
    FakeGitHubConnector as _FakeGitHubConnector,
)

logger = get_logger("cli")


def _split_csv(value: str | None) -> list[str]:
    if value is None or value.strip() == "":
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def build_digest_request(ns: argparse.Namespace) -> DigestRequest:
    """Build a :class:`~ai_news_agent.request.DigestRequest` from parsed CLI flags."""
    topics_csv = getattr(ns, "topics", None)
    if topics_csv is None:
        topics: list[str] | None = None
    else:
        parts = _split_csv(topics_csv)
        topics = parts

    kw: dict[str, Any] = {}
    if topics is not None:
        kw["topics"] = topics
    if getattr(ns, "timeframe", None) is not None:
        kw["timeframe"] = ns.timeframe
    if getattr(ns, "top_n", None) is not None:
        kw["top_n"] = ns.top_n
    if getattr(ns, "max_items", None) is not None:
        kw["max_items_per_source"] = ns.max_items

    sources = parse_sources_csv(getattr(ns, "sources", "") or "")
    if sources:
        kw["connector_names"] = normalize_source_names(sources)

    return DigestRequest(**kw)


def _resolve_db_path(ns: argparse.Namespace) -> Path:
    raw = getattr(ns, "db_path", None)
    if raw is not None:
        return Path(raw)
    return Path.cwd() / "digest.sqlite"


def _pick_connector_names(ns: argparse.Namespace) -> list[str]:
    """Default to both sources when unspecified."""
    sources = parse_sources_csv(getattr(ns, "sources", "") or "")
    if not sources:
        return list(DEFAULT_SOURCE_NAMES)
    return normalize_source_names(sources)


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
) -> Any:
    """Run digest and always close httpx-backed connectors when present."""
    try:
        return await run_digest(
            req,
            connectors=list(connectors),
            model=model,
            store=store,
        )
    finally:
        await _aclose_connectors(connectors)


def _add_digest_parser(sub: Any) -> argparse.ArgumentParser:
    p = sub.add_parser("digest", help="Generate an AI news digest")
    p.add_argument(
        "--timeframe",
        default=None,
        help="Optional timeframe string passed to connectors (e.g. today, last_7_days)",
    )
    p.add_argument(
        "--topics",
        default=None,
        help="Comma-separated topics; omit for built-in defaults",
    )
    p.add_argument(
        "--sources",
        default="github,bilibili",
        help="Comma-separated connector names (github, bilibili). Default: github,bilibili",
    )
    p.add_argument("--top-n", type=int, default=None, help="Override top_n (default: 5)")
    p.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Override max items per source (default: 20)",
    )
    p.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite path for DigestStore (default: ./digest.sqlite in cwd)",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Offline deterministic run (no network, no OpenAI key)",
    )
    return p


def _add_service_parser(sub: Any) -> argparse.ArgumentParser:
    from ai_news_agent.app.digest_service import main as service_main

    p = sub.add_parser(
        "service",
        help="Run the persistent local digest HTTP service (OpenClaw warm path)",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind host")
    p.add_argument("--port", type=int, default=8765, help="Bind port")
    p.add_argument(
        "--db-path",
        type=Path,
        default=Path.cwd() / "digest.sqlite",
        help="SQLite path for DigestStore",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Offline deterministic mode",
    )
    p.set_defaults(_handler=service_main)
    return p


def _add_openclaw_digest_parser(sub: Any) -> argparse.ArgumentParser:
    from ai_news_agent.adapters.openclaw_client import main as openclaw_main

    p = sub.add_parser(
        "openclaw-digest",
        help="Request digest from local warm service (OpenClaw client)",
    )
    p.add_argument("--message", default=None, help="Natural-language digest request")
    p.add_argument("--timeframe", default=None, help="Timeframe hint")
    p.add_argument(
        "--sources",
        default=None,
        help="Comma-separated sources (github, bilibili)",
    )
    p.add_argument("--topics", default=None, help="Comma-separated topics")
    p.add_argument("--fake", action="store_true", help="Offline fake digest")
    p.add_argument(
        "--service-url",
        default=None,
        help="Service base URL (or AI_NEWS_AGENT_SERVICE_URL)",
    )
    p.add_argument("--correlation-id", default=None, help="Latency correlation id")
    p.set_defaults(_handler=openclaw_main)
    return p


def _add_openclaw_followup_parser(sub: Any) -> argparse.ArgumentParser:
    from ai_news_agent.adapters.openclaw_client import followup_main

    p = sub.add_parser(
        "openclaw-followup",
        help="Request structured follow-up from local warm service (OpenClaw client)",
    )
    p.add_argument(
        "--message",
        required=True,
        help="Structured follow-up phrase (show sources, study first, show caveats)",
    )
    p.add_argument(
        "--service-url",
        default=None,
        help="Service base URL (or AI_NEWS_AGENT_SERVICE_URL)",
    )
    p.add_argument("--correlation-id", default=None, help="Latency correlation id")
    p.set_defaults(_handler=followup_main)
    return p


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-news-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_digest_parser(sub)
    _add_service_parser(sub)
    _add_openclaw_digest_parser(sub)
    _add_openclaw_followup_parser(sub)
    return parser


def _run_digest_command(ns: argparse.Namespace, *, stdout: TextIO) -> int:
    try:
        req = build_digest_request(ns)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    db_path = _resolve_db_path(ns)
    store = DigestStore(db_path)
    store.init_schema()

    try:
        names = _pick_connector_names(ns)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    connectors = build_connectors(fake=ns.fake, names=names)

    try:
        if ns.fake:
            model: Any = FakeDigestModel()
        else:
            model = build_chat_model()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    async def _go():
        return await _run_digest_async(req, store=store, connectors=connectors, model=model)

    logger.info(
        "cli digest start fake=%s sources=%s db_path=%s",
        ns.fake,
        names,
        db_path,
    )
    try:
        result = asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001 - CLI top-level error surface
        logger.exception("cli digest failed")
        print(f"digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "cli digest done run_id=%s warnings=%d errors=%d",
        result.run_id,
        len(result.warnings),
        len(result.errors),
    )

    text = result.text
    if not text.endswith("\n"):
        text += "\n"
    stdout.write(text)
    return 0


def _namespace_to_argv(ns: argparse.Namespace) -> list[str]:
    argv: list[str] = []
    for key, value in sorted(vars(ns).items()):
        if key in ("command", "_handler"):
            continue
        flag = "--" + key.replace("_", "-")
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        argv.extend([flag, str(value)])
    return argv


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """CLI entry. Returns process exit code."""
    load_local_env()
    configure_bilibili_network_from_env()
    configure_logging()
    out = stdout or sys.stdout
    args = argv if argv is not None else sys.argv[1:]
    parser = build_arg_parser()
    try:
        ns = parser.parse_args(args)
    except SystemExit as e:
        code = e.code
        return int(code) if isinstance(code, int) else 2

    if ns.command == "digest":
        return _run_digest_command(ns, stdout=out)

    handler = getattr(ns, "_handler", None)
    if handler is None:
        print(f"Unsupported command: {ns.command}", file=sys.stderr)
        return 2

    if ns.command == "service":
        service_argv = _namespace_to_argv(ns)
        return int(handler(service_argv))

    if ns.command == "openclaw-digest":
        return int(handler(args, stdout=out))

    if ns.command == "openclaw-followup":
        return int(handler(args, stdout=out))

    return int(handler(args, stdout=out))


if __name__ == "__main__":
    raise SystemExit(main())
