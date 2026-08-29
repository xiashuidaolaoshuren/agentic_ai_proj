"""Tests for historical digest search types and validation (Milestone 7D T1)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel

from ai_news_agent.history import (
    HISTORY_CANDIDATE_CAP,
    HistoricalItemRef,
    HistorySearchMatch,
    HistorySearchQuery,
    HistorySearchResult,
    format_historical_item_ref,
    parse_historical_item_ref,
    score_historical_candidate,
    validate_history_search_query,
)


def test_history_stubs_module_importable_and_types_are_basemodels() -> None:
    for cls in (
        HistoricalItemRef,
        HistorySearchQuery,
        HistorySearchMatch,
        HistorySearchResult,
    ):
        assert issubclass(cls, BaseModel), f"{cls.__name__} should be a Pydantic BaseModel"
    assert HISTORY_CANDIDATE_CAP == 10_000


def test_history_stubs_functions_raise_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        score_historical_candidate(query=HistorySearchQuery(sources=["juya"]), candidate={})


def test_format_and_parse_token_round_trip() -> None:
    ref = HistoricalItemRef(digest_id=12, run_id=5, entry_id=7, rank=3)
    assert format_historical_item_ref(ref) == "d12:r3"
    parsed = parse_historical_item_ref("d12:r3")
    assert parsed.digest_id == 12
    assert parsed.rank == 3


@pytest.mark.parametrize("token", ["bad", "d12", "12:r3"])
def test_parse_token_rejects_malformed(token: str) -> None:
    with pytest.raises(ValueError):
        parse_historical_item_ref(token)


def test_query_defaults_blank_text_absent_and_limit_default() -> None:
    query = HistorySearchQuery(text="   ", sources=["juya"])
    assert query.text is None
    assert HistorySearchQuery(sources=["juya"]).limit == 10


def test_query_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source"):
        HistorySearchQuery(sources=["bad"])


def test_query_limit_bounds() -> None:
    with pytest.raises(ValueError):
        HistorySearchQuery(sources=["juya"], limit=0)
    with pytest.raises(ValueError):
        HistorySearchQuery(sources=["juya"], limit=51)
    assert HistorySearchQuery(sources=["juya"], limit=1).limit == 1
    assert HistorySearchQuery(sources=["juya"], limit=50).limit == 50


def test_query_rejects_since_after_until() -> None:
    with pytest.raises(ValueError, match="since must not be after until"):
        HistorySearchQuery(
            since=date(2026, 8, 2),
            until=date(2026, 8, 1),
        )


def test_query_requires_at_least_one_criterion() -> None:
    with pytest.raises(ValueError, match="at least one search criterion"):
        HistorySearchQuery()
    query = validate_history_search_query(sources=["juya"])
    assert isinstance(query, HistorySearchQuery)
    assert query.sources == ["juya"]
