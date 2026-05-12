"""Tests for deterministic ranking and deduplication (Milestone 1 Task 7)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.models import ConfidenceLevel, NewsItem, SourceKind

# Baseline contract: empty input and single candidate (TDD red batch 1).


def _fixed_ts() -> datetime:
    return datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)


def test_rank_items_empty_returns_empty_list() -> None:
    from ai_news_agent.ranking import rank_items

    assert rank_items([], top_n=5, now=_fixed_ts()) == []


def test_rank_items_single_item_is_selected_with_reason() -> None:
    from ai_news_agent.ranking import rank_items

    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://github.com/a/b",
        title="a/b",
        published_at=_fixed_ts(),
        collected_at=_fixed_ts(),
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="hello",
    )
    ranked = rank_items([item], top_n=3, now=_fixed_ts())
    assert len(ranked) == 1
    r0 = ranked[0]
    assert r0.item is item
    assert r0.selected is True
    assert r0.score_total > 0
    assert r0.selection_reason
    assert isinstance(r0.score_breakdown, dict)
    assert r0.score_breakdown


def test_fresher_candidate_outranks_stale() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    stale = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s1",
        url="https://github.com/o/s1",
        title="stale",
        published_at=now - timedelta(days=60),
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    fresh = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s2",
        url="https://github.com/o/s2",
        title="fresh",
        published_at=now - timedelta(days=1),
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    ranked = rank_items([stale, fresh], top_n=5, now=now)
    assert ranked[0].item.source_id == "s2"


def test_topic_matches_increase_relevance_component() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    base = dict(
        source=SourceKind.GITHUB,
        url="https://github.com/x/1",
        title="t1",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.5,
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=10,
        raw_snippet="d",
    )
    no_topics = NewsItem(source_id="a", topic_matches=[], **base)
    with_topics = NewsItem(source_id="b", topic_matches=["AI", "LLM"], **base)
    ra = rank_items([no_topics], top_n=1, now=now)[0]
    rb = rank_items([with_topics], top_n=1, now=now)[0]
    assert rb.score_breakdown["relevance"] > ra.score_breakdown["relevance"]


def test_low_confidence_reduces_score_vs_medium() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    kwargs = dict(
        source=SourceKind.GITHUB,
        url="https://github.com/x/1",
        title="t",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.6,
        topic_matches=["x"],
        stars_or_views=5,
        raw_snippet="d",
    )
    low = NewsItem(source_id="l", content_confidence=ConfidenceLevel.LOW, **kwargs)
    med = NewsItem(source_id="m", content_confidence=ConfidenceLevel.MEDIUM, **kwargs)
    rl = rank_items([low], top_n=1, now=now)[0]
    rm = rank_items([med], top_n=1, now=now)[0]
    assert rl.score_total < rm.score_total


def test_higher_engagement_increases_engagement_component() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    kwargs = dict(
        source=SourceKind.BILIBILI,
        published_at=now,
        collected_at=now,
        metadata_completeness=0.5,
        topic_matches=["v"],
        content_confidence=ConfidenceLevel.MEDIUM,
        raw_snippet="d",
    )
    low_views = NewsItem(
        source_id="lv",
        url="https://www.bilibili.com/video/BV1lowviewsaa",
        title="low",
        stars_or_views=5,
        **kwargs,
    )
    high_views = NewsItem(
        source_id="hv",
        url="https://www.bilibili.com/video/BV1highviewss",
        title="high",
        stars_or_views=500_000,
        **kwargs,
    )
    r_lo = rank_items([low_views], top_n=1, now=now)[0]
    r_hi = rank_items([high_views], top_n=1, now=now)[0]
    assert r_hi.score_breakdown["engagement"] > r_lo.score_breakdown["engagement"]


# Deduplication and top-N (TDD red batch 3)


def test_dedupe_keeps_higher_preference_on_same_source_id() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    strong = NewsItem(
        source=SourceKind.GITHUB,
        source_id="dup",
        url="https://github.com/o/strong",
        title="strong",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.95,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    weak = NewsItem(
        source=SourceKind.GITHUB,
        source_id="dup",
        url="https://github.com/o/weak",
        title="weak title",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.2,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    ranked = rank_items([weak, strong], top_n=5, now=now)
    assert len(ranked) == 1
    assert ranked[0].item is strong


def test_dedupe_same_normalized_url_keeps_stronger_candidate() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    a = NewsItem(
        source=SourceKind.GITHUB,
        source_id="g1",
        url="https://github.com/a/B/",
        title="alpha",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.9,
        topic_matches=["t"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=50,
        raw_snippet="z",
    )
    b = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1xyz00001",
        url="https://github.com/a/b",
        title="beta",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.3,
        topic_matches=["t"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=50,
        raw_snippet="z",
    )
    ranked = rank_items([b, a], top_n=5, now=now)
    assert len(ranked) == 1
    assert ranked[0].item is a


def test_top_n_marks_only_first_n_selected() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    items = [
        NewsItem(
            source=SourceKind.GITHUB,
            source_id=f"id{i}",
            url=f"https://github.com/o/r{i}",
            title=f"r{i}",
            published_at=now - timedelta(days=i),
            collected_at=now,
            metadata_completeness=0.7,
            topic_matches=["AI"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=10 + i,
            raw_snippet="s",
        )
        for i in range(4)
    ]
    ranked = rank_items(items, top_n=2, now=now)
    assert len(ranked) == 4
    assert sum(1 for r in ranked if r.selected) == 2
    assert ranked[0].selected and ranked[1].selected
    assert not ranked[2].selected


def test_tie_breaker_uses_source_id_when_scores_equal() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    common = dict(
        source=SourceKind.GITHUB,
        published_at=now,
        collected_at=now,
        metadata_completeness=0.75,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=42,
        raw_snippet="body",
    )
    second = NewsItem(
        source_id="b",
        url="https://github.com/acme/b",
        title="Project B",
        **common,
    )
    first = NewsItem(
        source_id="a",
        url="https://github.com/acme/a",
        title="Project A",
        **common,
    )
    ranked = rank_items([second, first], top_n=5, now=now)
    assert ranked[0].item.source_id == "a"
    assert ranked[0].score_total == ranked[1].score_total