"""OpenClaw-facing helpers for safe digest CLI argument shaping."""

from __future__ import annotations

from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    normalize_source_names,
    parse_sources_csv,
)

_TIMEFRAME_ALIASES: dict[str, str] = {
    "daily": "today",
    "week": "last_7_days",
    "last7": "last_7_days",
}


def normalize_source_hint(hint: str | None) -> list[str]:
    """Normalize an OpenClaw source hint into validated connector names."""
    if hint is None or hint.strip() == "":
        return list(DEFAULT_SOURCE_NAMES)
    parsed = parse_sources_csv(hint)
    if not parsed:
        return list(DEFAULT_SOURCE_NAMES)
    return normalize_source_names(parsed)


def normalize_timeframe_hint(hint: str | None) -> str:
    """Normalize an OpenClaw timeframe hint into a canonical CLI value."""
    if hint is None or hint.strip() == "":
        return "today"
    key = hint.strip().lower()
    return _TIMEFRAME_ALIASES.get(key, key)


def normalize_topic_hint(hint: str | None) -> list[str] | None:
    """Normalize an OpenClaw topic hint into a trimmed list, or ``None`` when absent."""
    if hint is None or hint.strip() == "":
        return None
    topics = [part.strip() for part in hint.split(",") if part.strip()]
    if not topics:
        return None
    return topics


def build_digest_cli_argv(
    *,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
) -> list[str]:
    """Build a safe argv token list for ``ai-news-agent digest`` (no shell interpolation)."""
    timeframe = normalize_timeframe_hint(timeframe_hint)
    sources = normalize_source_hint(sources_hint)
    topics = normalize_topic_hint(topics_hint)

    argv: list[str] = [
        "digest",
        "--timeframe",
        timeframe,
        "--sources",
        ",".join(sources),
    ]
    if topics is not None:
        argv.extend(["--topics", ",".join(topics)])
    return argv


def build_digest_request_from_hints(
    *,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
) -> DigestRequest:
    """Build a :class:`~ai_news_agent.request.DigestRequest` from OpenClaw hints."""
    timeframe = normalize_timeframe_hint(timeframe_hint)
    sources = normalize_source_hint(sources_hint)
    topics = normalize_topic_hint(topics_hint)
    kw: dict[str, object] = {
        "timeframe": timeframe,
        "connector_names": sources,
    }
    if topics is not None:
        kw["topics"] = topics
    return DigestRequest(**kw)


__all__ = [
    "build_digest_cli_argv",
    "build_digest_request_from_hints",
    "normalize_source_hint",
    "normalize_timeframe_hint",
    "normalize_topic_hint",
]
