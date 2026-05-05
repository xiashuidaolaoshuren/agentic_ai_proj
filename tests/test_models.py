"""Tests for domain models and topic defaults (Task 2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_news_agent import topics
from ai_news_agent.models import (
    ConfidenceLevel,
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
    connector_warning_from_dict,
    connector_warning_to_dict,
    digest_from_dict,
    digest_to_dict,
    news_item_from_dict,
    news_item_to_dict,
    ranked_item_from_dict,
    ranked_item_to_dict,
)


def test_default_topics_match_design_taxonomy() -> None:
    assert topics.DEFAULT_TOPICS == (
        "AI agents",
        "model releases",
        "RAG",
        "multimodal AI",
        "AI developer tools",
        "notable open-source repos",
    )


def test_build_queries_uses_defaults_when_topics_none() -> None:
    q = topics.build_queries(None, None, 100)
    assert q == list(topics.DEFAULT_TOPICS)


def test_build_queries_respects_max_terms() -> None:
    custom = ["a", "b", "c", "d"]
    q = topics.build_queries(custom, None, 2)
    assert q == ["a", "b"]


def test_build_queries_appends_timeframe_when_present() -> None:
    q = topics.build_queries(["RAG"], "last_7_days", 5)
    assert q == ["RAG (last_7_days)"]


def test_news_item_required_fields_and_defaults() -> None:
    now = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="42",
        url="https://example.com/r",
        title="Example repo",
        collected_at=now,
    )
    assert item.published_at is None
    assert item.author is None
    assert item.stars_or_views is None
    assert item.language is None
    assert item.metadata_completeness == 0.0
    assert item.raw_snippet is None
    assert item.tags == []
    assert item.topic_matches == []
    assert item.content_confidence is None


def test_ranked_item_wraps_news_item() -> None:
    now = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="bv1",
        url="https://bilibili.com/video/bv1",
        title="Video",
        collected_at=now,
    )
    ri = RankedItem(
        item=item,
        score_total=3.5,
        score_breakdown={"freshness": 2.0, "metadata": 1.5},
        selected=True,
        selection_reason="High learning value",
    )
    assert ri.item.title == "Video"
    assert ri.score_total == 3.5
    assert ri.selected is True


def test_digest_entry_enum_and_digest_container() -> None:
    now = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="99",
        title="Repo",
        source_name="GitHub",
        source_url="https://github.com/x/y",
        summary="Short summary",
        why_it_matters="Because tests",
        background_knowledge="pytest basics",
        follow_up_action=FollowUpAction.READ,
        confidence_caveat="Snippet only",
    )
    digest = Digest(
        generated_at=now,
        entries=[entry],
        topics=["RAG"],
        timeframe="today",
    )
    assert len(digest.entries) == 1
    assert digest.entries[0].follow_up_action is FollowUpAction.READ
    assert digest.timeframe == "today"


def test_connector_warning_optional_detail() -> None:
    w = ConnectorWarning(connector="github", code="rate_limit", message="Slow down")
    assert w.detail is None
    w2 = ConnectorWarning(
        connector="github", code="partial", message="Missing field", detail="description absent"
    )
    assert w2.detail == "description absent"


def test_connector_warning_dict_roundtrip() -> None:
    w = ConnectorWarning(connector="bilibili", code="x", message="m", detail="d")
    d = connector_warning_to_dict(w)
    assert connector_warning_from_dict(d) == w


def test_news_item_and_ranked_item_dict_roundtrip() -> None:
    collected = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    published = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://github.com/a/b",
        title="A/B",
        published_at=published,
        collected_at=collected,
        author="alice",
        stars_or_views=120,
        language="en",
        metadata_completeness=0.8,
        raw_snippet="hello",
        tags=["ml", "agents"],
        topic_matches=["AI agents"],
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    d = news_item_to_dict(item)
    item2 = news_item_from_dict(d)
    assert item2 == item

    ranked = RankedItem(
        item=item,
        score_total=9.0,
        score_breakdown={"x": 1.0},
        selected=False,
        selection_reason="dup",
    )
    rd = ranked_item_to_dict(ranked)
    ranked2 = ranked_item_from_dict(rd)
    assert ranked2 == ranked


def test_digest_dict_roundtrip() -> None:
    now = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.BILIBILI,
                source_id="bv",
                title="T",
                source_name="Bilibili",
                source_url="https://bilibili.com/x",
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.WATCH,
            )
        ],
        topics=["multimodal AI"],
    )
    dd = digest_to_dict(digest)
    digest2 = digest_from_dict(dd)
    assert digest2 == digest


def test_invalid_enum_in_deserialize_raises() -> None:
    d = {
        "source": "not-a-real-source",
        "source_id": "1",
        "url": "https://x",
        "title": "t",
        "published_at": None,
        "collected_at": datetime.now(UTC).isoformat(),
        "author": None,
        "stars_or_views": None,
        "language": None,
        "metadata_completeness": 0.0,
        "raw_snippet": None,
        "tags": [],
        "topic_matches": [],
        "content_confidence": None,
    }
    with pytest.raises(ValueError):
        news_item_from_dict(d)
