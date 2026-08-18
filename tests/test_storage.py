"""SQLite persistence tests (Task 4)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.models import (
    ConfidenceLevel,
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore, FollowupContext


def test_init_schema_creates_tables(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    store = DigestStore(db)
    store.init_schema()
    con = sqlite3.connect(db)
    try:
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row[0] for row in cur.fetchall()}
        assert "runs" in names
        assert "news_items" in names
        assert "ranked_items" in names
        assert "digests" in names
        assert "digest_entries" in names
        assert "connector_warnings" in names
        assert "schema_meta" in names
    finally:
        con.close()


def test_empty_store_latest_queries(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "e.db")
    store.init_schema()
    assert store.get_latest_digest() is None
    ctx = store.get_latest_followup_context()
    assert isinstance(ctx, FollowupContext)
    assert ctx.run_id is None
    assert ctx.digest is None
    assert ctx.news_items == []
    assert ctx.ranked_items == []
    assert ctx.warnings == []


def test_save_news_item_write_json_persists_pydantic_payload(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "write_json.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    published = datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        published_at=published,
        collected_at=collected,
        author="alice",
        stars_or_views=99,
        language="Python",
        metadata_completeness=0.85,
        raw_snippet="desc",
        tags=["t1"],
        topic_matches=["RAG"],
        content_confidence=ConfidenceLevel.HIGH,
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[item], warnings=[], raw_count=1),
    )

    con = sqlite3.connect(tmp_path / "write_json.db")
    try:
        row = con.execute(
            "SELECT raw_payload_json FROM news_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
    finally:
        con.close()

    assert payload == item.model_dump(mode="json")


def test_load_legacy_raw_payload_json_for_news_and_ranked_items(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "legacy.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    published = datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-legacy",
        url="https://github.com/a/b",
        title="a/b",
        published_at=published,
        collected_at=collected,
        author="alice",
        stars_or_views=99,
        language="Python",
        metadata_completeness=0.85,
        raw_snippet="desc",
        tags=["t1"],
        topic_matches=["RAG"],
        content_confidence=ConfidenceLevel.HIGH,
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[item], warnings=[], raw_count=1),
    )
    store.save_ranked_items(
        run_id,
        [
            RankedItem(
                item=item,
                score_total=4.2,
                score_breakdown={"freshness": 2.0},
                selected=True,
                selection_reason="best",
            )
        ],
    )

    legacy_payload = {
        "source": "github",
        "source_id": "repo-legacy",
        "url": "https://github.com/a/b",
        "title": "a/b",
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "collected_at": collected.isoformat().replace("+00:00", "Z"),
        "author": "alice",
        "stars_or_views": 99,
        "language": "Python",
        "metadata_completeness": 0.85,
        "raw_snippet": "desc",
        "tags": None,
        "topic_matches": None,
        "content_confidence": "high",
        "_legacy_field": "ignored",
    }
    expected = NewsItem.model_validate(legacy_payload)

    con = sqlite3.connect(tmp_path / "legacy.db")
    try:
        con.execute(
            "UPDATE news_items SET raw_payload_json = ? WHERE run_id = ?",
            (json.dumps(legacy_payload), run_id),
        )
        con.commit()
    finally:
        con.close()

    ctx = store.get_latest_followup_context()
    assert ctx.run_id == run_id
    assert len(ctx.news_items) == 1
    assert ctx.news_items[0] == expected
    assert len(ctx.ranked_items) == 1
    assert ctx.ranked_items[0].item == expected


def test_load_legacy_payload_without_source_evidence_defaults_to_empty_dict(
    tmp_path: Path,
) -> None:
    store = DigestStore(tmp_path / "legacy_no_evidence.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    legacy_payload = {
        "source": "github",
        "source_id": "repo-legacy",
        "url": "https://github.com/a/b",
        "title": "a/b",
        "published_at": None,
        "collected_at": collected.isoformat().replace("+00:00", "Z"),
        "author": "alice",
        "stars_or_views": 99,
        "language": "Python",
        "metadata_completeness": 0.85,
        "raw_snippet": "desc",
        "tags": ["t1"],
        "topic_matches": ["RAG"],
        "content_confidence": "high",
    }
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    con = sqlite3.connect(tmp_path / "legacy_no_evidence.db")
    try:
        con.execute(
            """
            INSERT INTO news_items (
              run_id, source, source_id, url, title, published_at, collected_at,
              author, stars_or_views, language, metadata_completeness, raw_snippet,
              tags_json, topic_matches_json, content_confidence, raw_payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                "github",
                "repo-legacy",
                "https://github.com/a/b",
                "a/b",
                None,
                collected.isoformat(),
                "alice",
                99,
                "Python",
                0.85,
                "desc",
                json.dumps(["t1"]),
                json.dumps(["RAG"]),
                "high",
                json.dumps(legacy_payload),
            ),
        )
        con.commit()
    finally:
        con.close()

    ctx = store.get_latest_followup_context()
    assert len(ctx.news_items) == 1
    assert ctx.news_items[0].source_evidence == {}


def test_save_news_item_with_source_evidence_persists_mapping(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "evidence.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    evidence = {
        "relevance": 0.92,
        "query_lens": ["实战 / 踩坑"],
        "source_label": "知乎",
        "evidence_text_length": 120,
    }
    item = NewsItem(
        source=SourceKind.ZHIHU,
        source_id="zhihu-123",
        url="https://www.zhihu.com/question/1/answer/2",
        title="部署经验",
        collected_at=collected,
        language="zh",
        source_evidence=evidence,
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG"],
        connector_names=["zhihu"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[item], warnings=[], raw_count=1),
    )

    ctx = store.get_latest_followup_context()
    assert len(ctx.news_items) == 1
    assert ctx.news_items[0].source_evidence == evidence

    con = sqlite3.connect(tmp_path / "evidence.db")
    try:
        row = con.execute(
            "SELECT raw_payload_json FROM news_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
    finally:
        con.close()

    assert payload["source_evidence"] == evidence


def test_full_run_round_trip(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "full.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    published = datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        published_at=published,
        collected_at=collected,
        author="alice",
        stars_or_views=99,
        language="Python",
        metadata_completeness=0.85,
        raw_snippet="desc",
        tags=["t1"],
        topic_matches=["RAG"],
        content_confidence=ConfidenceLevel.HIGH,
    )
    result = ConnectorResult(
        items=[item],
        warnings=[
            ConnectorWarning(connector="github", code="rate", message="slow", detail="x")
        ],
        raw_count=1,
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG", "agents"],
        connector_names=["github"],
    )
    assert run_id == 1
    store.save_connector_result(run_id, result)

    ranked = [
        RankedItem(
            item=item,
            score_total=4.2,
            score_breakdown={"freshness": 2.0, "quality": 2.2},
            selected=True,
            selection_reason="best",
        )
    ]
    store.save_ranked_items(run_id, ranked)

    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="repo-1",
                title="a/b",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
                confidence_caveat="caveat",
            )
        ],
        topics=["RAG"],
        timeframe="today",
    )
    store.save_digest(run_id, digest)

    loaded_digest = store.get_latest_digest()
    assert loaded_digest is not None
    assert loaded_digest == digest

    ctx = store.get_latest_followup_context()
    assert ctx.run_id == run_id
    assert ctx.digest == digest
    assert len(ctx.news_items) == 1
    assert ctx.news_items[0] == item
    assert len(ctx.ranked_items) == 1
    assert ctx.ranked_items[0].item == item
    assert ctx.ranked_items[0].score_total == 4.2
    assert ctx.ranked_items[0].score_breakdown == {"freshness": 2.0, "quality": 2.2}
    assert ctx.ranked_items[0].selected is True
    assert ctx.ranked_items[0].selection_reason == "best"
    assert len(ctx.warnings) == 1
    assert ctx.warnings[0].connector == "github"
    assert ctx.warnings[0].code == "rate"


def test_save_connector_warnings_separate(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "w.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=None,
        timeframe=None,
        topics=["x"],
        connector_names=[],
    )
    store.save_connector_warnings(
        run_id,
        [ConnectorWarning(connector="bilibili", code="c", message="m")],
    )
    ctx = store.get_latest_followup_context()
    assert ctx.run_id == run_id
    assert len(ctx.warnings) == 1
    assert ctx.warnings[0].code == "c"


def test_latest_digest_picks_most_recent_run(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "multi.db")
    store.init_schema()
    collected = datetime(2026, 5, 7, 9, 0, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1x",
        url="https://bilibili.com/video/BV1x",
        title="v",
        collected_at=collected,
    )

    r1 = store.save_run(
        requested_at=collected,
        timeframe="t1",
        topics=["a"],
        connector_names=["bilibili"],
    )
    store.save_connector_result(r1, ConnectorResult(items=[item], warnings=[], raw_count=1))
    d1 = Digest(
        generated_at=datetime(2026, 5, 7, 9, 30, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.BILIBILI,
                source_id="BV1x",
                title="v",
                source_name="Bilibili",
                source_url=item.url,
                summary="s1",
                why_it_matters="w1",
                background_knowledge="b1",
                follow_up_action=FollowUpAction.WATCH,
            )
        ],
        topics=["a"],
        timeframe="t1",
    )
    store.save_digest(r1, d1)

    r2 = store.save_run(
        requested_at=collected,
        timeframe="t2",
        topics=["b"],
        connector_names=["bilibili"],
    )
    store.save_connector_result(r2, ConnectorResult(items=[item], warnings=[], raw_count=1))
    d2 = Digest(
        generated_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.BILIBILI,
                source_id="BV1x",
                title="v2",
                source_name="Bilibili",
                source_url=item.url,
                summary="s2",
                why_it_matters="w2",
                background_knowledge="b2",
                follow_up_action=FollowUpAction.WATCH,
            )
        ],
        topics=["b"],
        timeframe="t2",
    )
    store.save_digest(r2, d2)

    assert store.get_latest_digest() == d2
