"""OpenClaw adapter package exports."""

from __future__ import annotations

from ai_news_agent.adapters.openclaw import (
    build_digest_cli_argv,
    build_digest_request_from_hints,
    normalize_output_language_hint,
    normalize_output_style_hint,
    normalize_source_hint,
    normalize_timeframe_hint,
    normalize_topic_hint,
    resolve_openclaw_digest_request,
    validate_source_selector_consistency,
)

__all__ = [
    "build_digest_cli_argv",
    "build_digest_request_from_hints",
    "normalize_output_language_hint",
    "normalize_output_style_hint",
    "normalize_source_hint",
    "normalize_timeframe_hint",
    "normalize_topic_hint",
    "resolve_openclaw_digest_request",
    "validate_source_selector_consistency",
]
