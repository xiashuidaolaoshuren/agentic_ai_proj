"""Tests for OpenClaw adapter normalization and CLI argv construction."""

from __future__ import annotations

import pytest

from ai_news_agent.adapters.openclaw import (
    build_digest_cli_argv,
    normalize_source_hint,
    normalize_timeframe_hint,
    normalize_topic_hint,
)


def test_normalize_source_hint_empty_defaults_to_canonical_sources() -> None:
    assert normalize_source_hint(None) == ["github", "bilibili"]
    assert normalize_source_hint("") == ["github", "bilibili"]


def test_normalize_source_hint_parses_csv_sources() -> None:
    assert normalize_source_hint("github") == ["github"]
    assert normalize_source_hint(" GitHub , bilibili ") == ["github", "bilibili"]


def test_normalize_source_hint_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source"):
        normalize_source_hint("arxiv")


def test_normalize_timeframe_hint_empty_defaults_to_today() -> None:
    assert normalize_timeframe_hint(None) == "today"
    assert normalize_timeframe_hint("") == "today"


def test_normalize_timeframe_hint_maps_aliases() -> None:
    assert normalize_timeframe_hint("daily") == "today"
    assert normalize_timeframe_hint("week") == "last_7_days"
    assert normalize_timeframe_hint("last7") == "last_7_days"


def test_normalize_timeframe_hint_preserves_canonical_values() -> None:
    assert normalize_timeframe_hint("today") == "today"
    assert normalize_timeframe_hint("last_7_days") == "last_7_days"


def test_normalize_topic_hint_empty_returns_none() -> None:
    assert normalize_topic_hint(None) is None
    assert normalize_topic_hint("") is None
    assert normalize_topic_hint("  ,  ") is None


def test_normalize_topic_hint_parses_csv_preserving_order() -> None:
    assert normalize_topic_hint("RAG, agents") == ["RAG", "agents"]
    assert normalize_topic_hint(" RAG , , agents ") == ["RAG", "agents"]


def test_build_digest_cli_argv_returns_token_list_with_defaults() -> None:
    argv = build_digest_cli_argv()

    assert isinstance(argv, list)
    assert all(isinstance(token, str) for token in argv)
    assert argv == [
        "digest",
        "--timeframe",
        "today",
        "--sources",
        "github,bilibili",
    ]


def test_build_digest_cli_argv_includes_normalized_options() -> None:
    argv = build_digest_cli_argv(
        timeframe_hint="week",
        sources_hint="github",
        topics_hint="RAG, agents",
    )

    assert argv == [
        "digest",
        "--timeframe",
        "last_7_days",
        "--sources",
        "github",
        "--topics",
        "RAG,agents",
    ]


def test_build_digest_cli_argv_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source"):
        build_digest_cli_argv(sources_hint="arxiv")
