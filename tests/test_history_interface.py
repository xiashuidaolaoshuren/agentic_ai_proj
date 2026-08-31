"""Tests for Gradio/CLI history command grammar and search chrome (Milestone 7D T6)."""

from __future__ import annotations

from datetime import UTC, date, datetime


def test_non_history_message_returns_none() -> None:
    from ai_news_agent.history_interface import parse_history_chat_message

    assert parse_history_chat_message("give me today's digest") is None


def test_open_history_token_any_case() -> None:
    from ai_news_agent.history_interface import parse_history_chat_message

    cmd = parse_history_chat_message("Open History d12:r3")
    assert cmd is not None
    assert cmd.action == "open"
    assert cmd.token == "d12:r3"
    assert cmd.error is None


def test_open_history_bad_token_is_not_found_not_none() -> None:
    from ai_news_agent.history_interface import HISTORY_NOT_FOUND, parse_history_chat_message

    cmd = parse_history_chat_message("open history bad")
    assert cmd is not None
    assert cmd.error == HISTORY_NOT_FOUND


def test_search_history_for_text_maps_to_query() -> None:
    from ai_news_agent.history_interface import parse_history_chat_message

    cmd = parse_history_chat_message("search history for rag")
    assert cmd is not None
    assert cmd.action == "search"
    assert cmd.error is None
    assert cmd.query is not None
    assert cmd.query.text == "rag"
    assert cmd.query.sources is None
    assert cmd.query.topics is None
    assert cmd.query.since is None
    assert cmd.query.until is None
    assert cmd.query.limit == 10


def test_search_history_spec_example_maps_to_query() -> None:
    from ai_news_agent.history_interface import parse_history_chat_message

    cmd = parse_history_chat_message(
        "search history for RAG agents from huggingface,zhihu since 2026-08-01"
    )
    assert cmd is not None
    assert cmd.action == "search"
    assert cmd.error is None
    assert cmd.query is not None
    assert cmd.query.text == "RAG agents"
    assert cmd.query.sources == ["huggingface", "zhihu"]
    assert cmd.query.topics is None
    assert cmd.query.since == date(2026, 8, 1)
    assert cmd.query.until is None
    assert cmd.query.limit == 10


def test_search_history_lookahead_and_on_until_clauses() -> None:
    from ai_news_agent.history_interface import parse_history_chat_message

    cmd = parse_history_chat_message(
        "Search History for RAG from huggingface on agents, rag until 2026-08-15"
    )
    assert cmd is not None
    assert cmd.action == "search"
    assert cmd.query is not None
    assert cmd.query.text == "RAG"
    assert cmd.query.sources == ["huggingface"]
    assert cmd.query.topics == ["agents", "rag"]
    assert cmd.query.until == date(2026, 8, 15)
    assert cmd.query.since is None


def _assert_search_validation_chrome(message: str) -> None:
    from ai_news_agent.followup_structured import NO_SAVED_DIGEST
    from ai_news_agent.history_interface import parse_history_chat_message

    cmd = parse_history_chat_message(message)
    assert cmd is not None
    assert cmd.action == "search"
    assert cmd.error is not None
    assert cmd.error != NO_SAVED_DIGEST
    assert "Ask for a digest first" not in cmd.error


def test_bare_search_history_sets_error_not_no_saved_digest() -> None:
    _assert_search_validation_chrome("search history")


def test_unknown_source_sets_error_not_no_saved_digest() -> None:
    _assert_search_validation_chrome("search history from not-a-source")


def test_since_after_until_sets_error_not_no_saved_digest() -> None:
    _assert_search_validation_chrome("search history since 2026-08-10 until 2026-08-01")


def test_format_history_search_text_includes_chrome_omits_none_excerpt_appends_caveats() -> None:
    from ai_news_agent.history import (
        HistoricalItemRef,
        HistorySearchMatch,
        HistorySearchResult,
        format_historical_item_ref,
    )
    from ai_news_agent.history_interface import format_history_search_text
    from ai_news_agent.models import SourceKind

    ref = HistoricalItemRef(digest_id=12, run_id=5, entry_id=7, rank=3)
    result = HistorySearchResult(
        matches=[
            HistorySearchMatch(
                ref=ref,
                generated_at=datetime(2026, 8, 1, 15, 30, 0, tzinfo=UTC),
                source_kind=SourceKind.HUGGINGFACE,
                title="RAG Agents Paper",
                url="https://example.com/rag",
                excerpt=None,
                score=1.5,
            )
        ],
        scanned_count=1,
        caveats=["Archive truncated.", "Skipped 1 malformed row."],
    )
    text = format_history_search_text(result)
    assert format_historical_item_ref(ref) in text
    assert "2026-08-01" in text
    assert SourceKind.HUGGINGFACE.value in text
    assert "RAG Agents Paper" in text
    assert "https://example.com/rag" in text
    assert "Archive truncated." in text
    assert "Skipped 1 malformed row." in text
    assert "None" not in text
    assert "1.5" not in text


def test_format_history_search_text_includes_excerpt_when_present() -> None:
    from ai_news_agent.history import HistoricalItemRef, HistorySearchMatch, HistorySearchResult
    from ai_news_agent.history_interface import format_history_search_text
    from ai_news_agent.models import SourceKind

    result = HistorySearchResult(
        matches=[
            HistorySearchMatch(
                ref=HistoricalItemRef(digest_id=1, run_id=1, entry_id=1, rank=1),
                generated_at=datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC),
                source_kind=SourceKind.JUYA,
                title="Titled item",
                url="https://example.com/item",
                excerpt="matching snippet here",
                score=0.0,
            )
        ]
    )
    text = format_history_search_text(result)
    assert "matching snippet here" in text

