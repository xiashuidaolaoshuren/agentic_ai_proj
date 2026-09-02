"""Tests for historical digest search service (Milestone 7D T4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.history import HistorySearchQuery, format_historical_item_ref
from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore


def _make_news_item(
    *,
    source: SourceKind,
    source_id: str,
    title: str,
    url: str,
) -> NewsItem:
    collected = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    return NewsItem(
        source=source,
        source_id=source_id,
        url=url,
        title=title,
        published_at=collected,
        collected_at=collected,
        metadata_completeness=0.8,
        tags=[],
        topic_matches=[],
        content_confidence=ConfidenceLevel.MEDIUM,
    )


def _make_digest_entry(
    *,
    source_kind: SourceKind,
    source_id: str,
    title: str,
    url: str,
    summary: str = "Summary",
    why_it_matters: str = "Why",
    background_knowledge: str = "Background",
) -> DigestEntry:
    return DigestEntry(
        source_kind=source_kind,
        source_id=source_id,
        title=title,
        source_name=source_kind.value,
        source_url=url,
        summary=summary,
        why_it_matters=why_it_matters,
        background_knowledge=background_knowledge,
        follow_up_action=FollowUpAction.READ,
    )


def _seed_run_with_digest(
    store: DigestStore,
    *,
    generated_at: datetime,
    topics: list[str],
    entries: list[DigestEntry],
    news_items: list[NewsItem] | None = None,
    ranked: list[RankedItem] | None = None,
) -> tuple[int, int]:
    collected = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=topics,
        connector_names=[item.source.value for item in (news_items or [])] or ["github"],
    )
    if news_items:
        store.save_connector_result(
            run_id, ConnectorResult(items=news_items, warnings=[], raw_count=len(news_items))
        )
    if ranked:
        store.save_ranked_items(run_id, ranked)
    digest_id = store.save_digest(
        run_id,
        Digest(
            generated_at=generated_at,
            entries=entries,
            topics=topics,
            timeframe="today",
        ),
    )
    return run_id, digest_id


class _FakeHistoricalStore:
    """Duck-typed store for cap/malformed tests."""

    def __init__(self, rows: list[dict[str, Any]], *, truncated: bool = False) -> None:
        self._rows = rows
        self._truncated = truncated
        self.last_cap: int | None = None

    def list_historical_digest_entries(
        self,
        *,
        sources: list[str] | None = None,
        since: date | None = None,
        until: date | None = None,
        cap: int = 10_000,
    ) -> tuple[list[dict[str, Any]], bool]:
        self.last_cap = cap
        return list(self._rows), self._truncated


def test_empty_archive_returns_no_saved_digests_caveat(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "empty.db")
    store.init_schema()
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(store, HistorySearchQuery(sources=["juya"]))
    assert result.matches == []
    assert result.scanned_count == 0
    assert result.archive_truncated is False
    assert "No saved digests to search." in result.caveats


def test_filter_only_maps_match_token_and_scanned_count(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "map.db")
    store.init_schema()
    entry = _make_digest_entry(
        source_kind=SourceKind.JUYA,
        source_id="j1",
        title="Juya headline",
        url="https://juya.example/item",
    )
    _, digest_id = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[entry],
    )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(store, HistorySearchQuery(sources=["juya"]))
    assert result.scanned_count == 1
    assert len(result.matches) == 1
    match = result.matches[0]
    assert format_historical_item_ref(match.ref) == f"d{digest_id}:r1"
    assert match.ref.run_id > 0
    assert match.ref.entry_id > 0
    assert match.ref.rank == 1
    assert match.url == "https://juya.example/item"
    assert match.excerpt is None
    assert match.score == 0.0


def test_topic_and_match_is_casefold_digest_topics_not_entry_matches(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "topic.db")
    store.init_schema()
    rag_entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="rag-1",
        title="RAG digest item",
        url="https://github.com/a/rag",
        summary="RAG summary",
    )
    agents_entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="agents-1",
        title="Agents digest item",
        url="https://github.com/a/agents",
        summary="Agents summary",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["RAG"],
        entries=[rag_entry],
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[agents_entry],
    )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(store, HistorySearchQuery(topics=["rag"]))
    assert len(result.matches) == 1
    assert result.matches[0].title == "RAG digest item"


def test_lexical_scores_sorts_and_respects_limit(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "lexical.db")
    store.init_schema()
    title_hit = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="title",
        title="Transformer breakthrough",
        url="https://github.com/a/title",
        summary="Unrelated body",
    )
    body_hit = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="body",
        title="Other headline",
        url="https://github.com/a/body",
        summary="Mentions transformer in summary only",
    )
    miss = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="miss",
        title="No match here",
        url="https://github.com/a/miss",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[title_hit, body_hit, miss],
    )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(
        store,
        HistorySearchQuery(text="transformer", limit=1),
    )
    assert len(result.matches) == 1
    assert result.matches[0].title == "Transformer breakthrough"
    assert result.matches[0].score > 0.0


def test_and_filters_and_duplicate_urls_are_two_rows(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "and_dup.db")
    store.init_schema()
    shared_url = "https://example.com/shared"
    first = _make_digest_entry(
        source_kind=SourceKind.JUYA,
        source_id="j1",
        title="First digest shared URL",
        url=shared_url,
    )
    second = _make_digest_entry(
        source_kind=SourceKind.JUYA,
        source_id="j2",
        title="Second digest shared URL",
        url=shared_url,
    )
    wrong_source = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="g1",
        title="GitHub should be filtered out",
        url="https://github.com/a/wrong",
    )
    _, digest_a = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        topics=["RAG"],
        entries=[first, wrong_source],
    )
    _, digest_b = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["RAG"],
        entries=[second],
    )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(
        store,
        HistorySearchQuery(sources=["juya"], topics=["RAG"], text="shared"),
    )
    assert len(result.matches) == 2
    tokens = {format_historical_item_ref(m.ref) for m in result.matches}
    assert tokens == {f"d{digest_a}:r1", f"d{digest_b}:r1"}
    assert all(m.url == shared_url for m in result.matches)


def test_no_match_caveat_names_filters_not_empty_archive(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "nomatch.db")
    store.init_schema()
    entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="g1",
        title="Existing item",
        url="https://github.com/a/exists",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[entry],
    )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(
        store,
        HistorySearchQuery(text="nonexistentqueryterm"),
    )
    assert result.matches == []
    assert "No saved digests to search." not in result.caveats
    joined = " ".join(result.caveats)
    assert "text=" in joined
    assert "Try broadening one criterion." in joined


def test_injectable_cap_sets_truncated_caveat(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "cap.db")
    store.init_schema()
    for idx in range(3):
        _seed_run_with_digest(
            store,
            generated_at=datetime(2026, 8, idx + 1, 12, 0, 0, tzinfo=UTC),
            topics=["agents"],
            entries=[
                _make_digest_entry(
                    source_kind=SourceKind.GITHUB,
                    source_id=f"g{idx}",
                    title=f"Item {idx}",
                    url=f"https://github.com/a/{idx}",
                )
            ],
        )
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(store, HistorySearchQuery(sources=["github"]), cap=2)
    assert result.archive_truncated is True
    assert result.scanned_count == 2
    assert any("older archive rows were not searched" in c for c in result.caveats)


def test_malformed_row_skipped_with_bounded_caveat() -> None:
    good_row = {
        "title": "Good row",
        "summary": "Summary",
        "why_it_matters": "Why",
        "background_knowledge": "Background",
        "digest_topics": ["agents"],
        "generated_at": datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        "digest_id": 1,
        "rank": 1,
        "run_id": 10,
        "entry_id": 100,
        "source_kind": SourceKind.GITHUB,
        "source_id": "g1",
        "source_name": "github",
        "source_url": "https://github.com/a/good",
    }
    bad_row: dict[str, Any] = {
        "summary": "Missing title key",
        "digest_topics": ["agents"],
        "generated_at": datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        "digest_id": 2,
        "rank": 1,
        "run_id": 11,
        "entry_id": 101,
        "source_kind": SourceKind.GITHUB,
        "source_id": "g2",
        "source_name": "github",
        "source_url": "https://github.com/a/bad",
    }
    store = _FakeHistoricalStore([good_row, bad_row])
    from ai_news_agent.history_search import search_digest_history

    result = search_digest_history(store, HistorySearchQuery(sources=["github"]))
    assert len(result.matches) == 1
    assert result.matches[0].title == "Good row"
    assert "Skipped 1 malformed historical row." in result.caveats
