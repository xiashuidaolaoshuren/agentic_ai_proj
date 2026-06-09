"""OpenClaw adapter package exports."""

from __future__ import annotations

from ai_news_agent.adapters.openclaw import (
    build_digest_cli_argv,
    normalize_source_hint,
    normalize_timeframe_hint,
    normalize_topic_hint,
)

__all__ = [
    "build_digest_cli_argv",
    "normalize_source_hint",
    "normalize_timeframe_hint",
    "normalize_topic_hint",
]
