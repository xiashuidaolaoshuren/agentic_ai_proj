"""Tests for DigestStore historical digest reads (Milestone 7D T3)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pathlib import Path

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import SCHEMA_VERSION, DigestStore


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
        store.save_connector_result(run_id, ConnectorResult(items=news_items, warnings=[], raw_count=len(news_items)))
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


def _candidate_keys() -> set[str]:
    return {
        "title",
        "summary",
        "why_it_matters",
        "background_knowledge",
        "digest_topics",
        "generated_at",
        "digest_id",
        "rank",
        "run_id",
        "entry_id",
        "source_kind",
        "source_id",
        "source_name",
        "source_url",
    }


def test_historical_read_methods_exist(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "stubs.db")
    store.init_schema()
    rows, truncated = store.list_historical_digest_entries()
    assert rows == []
    assert truncated is False
    assert store.get_followup_context_for_digest(1) is None


def test_empty_archive_returns_no_rows(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "empty.db")
    store.init_schema()
    rows, truncated = store.list_historical_digest_entries()
    assert rows == []
    assert truncated is False


def test_list_returns_digest_entries_not_unselected_news(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "entries.db")
    store.init_schema()
    selected = _make_news_item(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        title="Selected news title",
        url="https://github.com/a/selected",
    )
    unselected = _make_news_item(
        source=SourceKind.GITHUB,
        source_id="repo-2",
        title="Unselected news title",
        url="https://github.com/a/unselected",
    )
    entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="Digest entry title",
        url=selected.url,
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["RAG"],
        entries=[entry],
        news_items=[selected, unselected],
        ranked=[
            RankedItem(item=selected, score_total=1.0, selected=True, selection_reason="best"),
            RankedItem(item=unselected, score_total=0.5, selected=False, selection_reason="skip"),
        ],
    )
    rows, truncated = store.list_historical_digest_entries()
    assert truncated is False
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Digest entry title"
    assert row["title"] != "Unselected news title"
    assert _candidate_keys().issubset(row.keys())
    assert row["digest_topics"] == ["RAG"]
    assert row["rank"] == 1
    assert isinstance(row["generated_at"], datetime)
    assert row["source_kind"] == SourceKind.GITHUB
    assert row["source_url"] == selected.url


def test_display_rank_is_per_digest_id_order(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "rank.db")
    store.init_schema()
    first = _make_digest_entry(
        source_kind=SourceKind.JUYA,
        source_id="j1",
        title="Juya first",
        url="https://juya.example/1",
    )
    second = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="g1",
        title="GitHub second",
        url="https://github.com/a/b",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[first, second],
    )
    rows, _ = store.list_historical_digest_entries(sources=["github"])
    assert len(rows) == 1
    assert rows[0]["title"] == "GitHub second"
    assert rows[0]["rank"] == 2


def test_source_filter_limits_to_requested_kinds(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "source.db")
    store.init_schema()
    juya = _make_digest_entry(
        source_kind=SourceKind.JUYA,
        source_id="j1",
        title="Juya item",
        url="https://juya.example/1",
    )
    github = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="g1",
        title="GitHub item",
        url="https://github.com/a/b",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC),
        topics=["agents"],
        entries=[juya, github],
    )
    rows, _ = store.list_historical_digest_entries(sources=["juya"])
    assert len(rows) == 1
    assert rows[0]["source_kind"] == SourceKind.JUYA


def test_utc_date_range_is_inclusive(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "dates.db")
    store.init_schema()
    for day, title in ((1, "Aug 1"), (2, "Aug 2"), (3, "Aug 3")):
        _seed_run_with_digest(
            store,
            generated_at=datetime(2026, 8, day, 15, 0, 0, tzinfo=UTC),
            topics=["agents"],
            entries=[
                _make_digest_entry(
                    source_kind=SourceKind.GITHUB,
                    source_id=f"g{day}",
                    title=title,
                    url=f"https://github.com/a/{day}",
                )
            ],
        )
    rows, _ = store.list_historical_digest_entries(
        since=date(2026, 8, 2),
        until=date(2026, 8, 2),
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Aug 2"


def test_newest_first_generated_at_then_digest_id_then_rank(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "order.db")
    store.init_schema()
    older_run, _ = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        topics=["old"],
        entries=[
            _make_digest_entry(
                source_kind=SourceKind.GITHUB,
                source_id="old",
                title="Older digest",
                url="https://github.com/old",
            )
        ],
    )
    newer_run, _ = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        topics=["new"],
        entries=[
            _make_digest_entry(
                source_kind=SourceKind.GITHUB,
                source_id="new-1",
                title="Newer rank 1",
                url="https://github.com/new-1",
            ),
            _make_digest_entry(
                source_kind=SourceKind.GITHUB,
                source_id="new-2",
                title="Newer rank 2",
                url="https://github.com/new-2",
            ),
        ],
    )
    assert newer_run > older_run
    rows, _ = store.list_historical_digest_entries()
    titles = [row["title"] for row in rows]
    assert titles == ["Newer rank 1", "Newer rank 2", "Older digest"]
    assert rows[0]["rank"] == 1
    assert rows[1]["rank"] == 2


def test_cap_plus_one_sets_truncated_flag(tmp_path: Path) -> None:
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
    capped, truncated = store.list_historical_digest_entries(cap=2)
    assert len(capped) == 2
    assert truncated is True
    full, truncated_full = store.list_historical_digest_entries(cap=10)
    assert len(full) == 3
    assert truncated_full is False


def test_followup_context_for_digest_loads_that_run(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    selected = _make_news_item(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        title="Selected",
        url="https://github.com/a/selected",
    )
    entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="Digest entry",
        url=selected.url,
    )
    old_run_id, old_digest_id = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        topics=["old"],
        entries=[entry],
        news_items=[selected],
        ranked=[RankedItem(item=selected, score_total=1.0, selected=True, selection_reason="best")],
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        topics=["new"],
        entries=[
            _make_digest_entry(
                source_kind=SourceKind.GITHUB,
                source_id="repo-2",
                title="Newest",
                url="https://github.com/a/new",
            )
        ],
    )
    ctx = store.get_followup_context_for_digest(old_digest_id)
    assert ctx is not None
    assert ctx.run_id == old_run_id
    assert ctx.digest is not None
    assert len(ctx.digest.entries) == 1
    assert ctx.digest.entries[0].title == "Digest entry"
    assert len(ctx.news_items) == 1
    assert ctx.news_items[0].title == "Selected"
    assert store.get_followup_context_for_digest(9999) is None


def test_latest_followup_context_and_schema_unchanged(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "latest.db")
    store.init_schema()
    old_entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="old",
        title="Old digest",
        url="https://github.com/a/old",
    )
    _, old_digest_id = _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        topics=["old"],
        entries=[old_entry],
    )
    newest_entry = _make_digest_entry(
        source_kind=SourceKind.GITHUB,
        source_id="new",
        title="Newest digest",
        url="https://github.com/a/new",
    )
    _seed_run_with_digest(
        store,
        generated_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        topics=["new"],
        entries=[newest_entry],
    )
    store.list_historical_digest_entries()
    store.get_followup_context_for_digest(old_digest_id)
    latest = store.get_latest_followup_context()
    assert latest.digest is not None
    assert latest.digest.entries[0].title == "Newest digest"
    assert SCHEMA_VERSION == "1"
