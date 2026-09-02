"""Tests for historical digest search types and validation (Milestone 7D T1)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import BaseModel

from ai_news_agent.history import (
    HISTORY_CANDIDATE_CAP,
    HistoricalItemRef,
    HistorySearchMatch,
    HistorySearchQuery,
    HistorySearchResult,
    format_historical_item_ref,
    extract_historical_excerpt,
    historical_sort_key,
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


def test_filter_only_query_scores_zero() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(sources=["juya"]),
        candidate={},
    )
    assert score == 0.0


def _candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "",
        "summary": "",
        "why_it_matters": "",
        "background_knowledge": "",
        "digest_topics": [],
        "generated_at": None,
        "digest_id": 1,
        "rank": 1,
    }
    base.update(overrides)
    return base


def test_gate_all_terms_miss_returns_none() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="alpha beta"),
        candidate=_candidate(title="alpha only"),
    )
    assert score is None


def test_gate_hit_in_summary() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="transformer"),
        candidate=_candidate(summary="Large transformer models"),
    )
    assert score is not None


def test_gate_hit_via_digest_topics_only() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="agents"),
        candidate=_candidate(digest_topics=["AI Agents"]),
    )
    assert score is not None


def test_gate_nfc_nfd_e_accent_match() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="caf\u00e9"),
        candidate=_candidate(title="Best caf\u0065\u0301 in town"),
    )
    assert score is not None


def test_gate_casefold_cafe() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="CAF\u00c9"),
        candidate=_candidate(summary="Visit the caf\u00e9 district"),
    )
    assert score is not None


def test_gate_chinese_unsegmented_substring() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="大模型"),
        candidate=_candidate(summary="国产大模型进展"),
    )
    assert score is not None


def test_phrase_in_title_outranks_phrase_in_text() -> None:
    query = HistorySearchQuery(text="large language model")
    title_score = score_historical_candidate(
        query=query,
        candidate=_candidate(title="Large Language Model release"),
    )
    summary_score = score_historical_candidate(
        query=query,
        candidate=_candidate(summary="A large language model update"),
    )
    assert title_score is not None
    assert summary_score is not None
    assert title_score > summary_score


def test_all_terms_in_title_outranks_terms_only_in_body() -> None:
    query = HistorySearchQuery(text="machine learning safety")
    title_score = score_historical_candidate(
        query=query,
        candidate=_candidate(title="Machine safety for learning systems"),
    )
    summary_score = score_historical_candidate(
        query=query,
        candidate=_candidate(summary="Learning about machine safety practices"),
    )
    assert title_score is not None
    assert summary_score is not None
    assert title_score > summary_score


def test_unsegmented_title_substring_counts_as_title_terms() -> None:
    score = score_historical_candidate(
        query=HistorySearchQuery(text="大模型"),
        candidate=_candidate(title="国产大模型发布"),
    )
    assert score is not None
    assert score >= 4.0


def test_topic_equality_boosts_score() -> None:
    query = HistorySearchQuery(text="agents")
    topic_score = score_historical_candidate(
        query=query,
        candidate=_candidate(
            summary="agents update",
            digest_topics=["Agents"],
        ),
    )
    text_score = score_historical_candidate(
        query=query,
        candidate=_candidate(summary="agents update"),
    )
    assert topic_score is not None
    assert text_score is not None
    assert topic_score > text_score


def test_term_coverage_fraction_and_unsegmented_is_one() -> None:
    query = HistorySearchQuery(text="open source")
    full_text_score = score_historical_candidate(
        query=query,
        candidate=_candidate(summary="Open platforms and source releases"),
    )
    partial_topic_score = score_historical_candidate(
        query=query,
        candidate=_candidate(
            summary="Open platforms overview",
            digest_topics=["open source archive"],
        ),
    )
    assert full_text_score is not None
    assert partial_topic_score is not None
    assert full_text_score > partial_topic_score

    unsegmented_score = score_historical_candidate(
        query=HistorySearchQuery(text="大模型"),
        candidate=_candidate(summary="国产大模型进展"),
    )
    assert unsegmented_score is not None
    assert unsegmented_score >= 1.0


def test_sort_key_recency_digest_id_rank() -> None:
    query = HistorySearchQuery(text="agents")
    newer = _candidate(
        summary="agents update",
        generated_at=datetime(2026, 8, 2, 12, 0, 0),
        digest_id=20,
        rank=2,
    )
    older = _candidate(
        summary="agents update",
        generated_at=datetime(2026, 8, 1, 12, 0, 0),
        digest_id=10,
        rank=1,
    )
    same_day_higher_digest = _candidate(
        summary="agents update",
        generated_at=datetime(2026, 8, 2, 12, 0, 0),
        digest_id=30,
        rank=3,
    )
    ordered = sorted(
        [older, same_day_higher_digest, newer],
        key=lambda candidate: historical_sort_key(query=query, candidate=candidate),
        reverse=True,
    )
    assert ordered == [same_day_higher_digest, newer, older]


def test_excerpt_filter_only_returns_none() -> None:
    excerpt = extract_historical_excerpt(
        query=HistorySearchQuery(sources=["juya"]),
        candidate=_candidate(title="Alpha title"),
    )
    assert excerpt is None


def test_excerpt_prefers_first_matching_field_order() -> None:
    candidate = _candidate(
        title="Alpha title",
        summary="Beta summary with alpha",
        why_it_matters="Gamma why alpha",
    )
    excerpt = extract_historical_excerpt(
        query=HistorySearchQuery(text="alpha"),
        candidate=candidate,
    )
    assert excerpt == "Alpha title"


def test_excerpt_skips_to_summary_when_title_misses() -> None:
    excerpt = extract_historical_excerpt(
        query=HistorySearchQuery(text="alpha"),
        candidate=_candidate(
            title="Beta title",
            summary="Alpha summary line",
        ),
    )
    assert excerpt == "Alpha summary line"


def test_excerpt_topic_only_hit_returns_none() -> None:
    excerpt = extract_historical_excerpt(
        query=HistorySearchQuery(text="agents"),
        candidate=_candidate(digest_topics=["Agents"]),
    )
    assert excerpt is None


def test_excerpt_truncates_long_field_to_160_chars_with_match() -> None:
    prefix = "x" * 120
    suffix = "y" * 200
    field = f"{prefix}alpha{suffix}"
    excerpt = extract_historical_excerpt(
        query=HistorySearchQuery(text="alpha"),
        candidate=_candidate(summary=field),
    )
    assert excerpt is not None
    assert len(excerpt) == 160
    assert "alpha" in excerpt.lower()


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


def test_query_normalizes_source_names_to_lowercase() -> None:
    query = HistorySearchQuery(sources=["JUYA", "HuggingFace"])
    assert query.sources == ["juya", "huggingface"]


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
