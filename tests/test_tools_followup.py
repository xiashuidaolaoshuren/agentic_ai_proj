"""Tests for Milestone 2 follow-up inspection tools (Task T2)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.followup import (
    get_digest_item,
    get_ranking_explanation,
    get_source_trace,
    load_latest_digest,
)
from ai_news_agent.tools.schemas import ToolObservationStatus, tool_observation_to_dict


def _seed_full_followup_store(tmp_path: Path) -> tuple[DigestStore, int]:
    store = DigestStore(tmp_path / "followup.db")
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
        topics=["RAG", "agents"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(
            items=[item],
            warnings=[
                ConnectorWarning(connector="github", code="rate", message="slow", detail="x")
            ],
            raw_count=1,
        ),
    )
    store.save_ranked_items(
        run_id,
        [
            RankedItem(
                item=item,
                score_total=4.2,
                score_breakdown={"freshness": 2.0, "quality": 2.2},
                selected=True,
                selection_reason="best",
            )
        ],
    )
    store.save_digest(
        run_id,
        Digest(
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
        ),
    )
    return store, run_id


def test_load_latest_digest_empty_store(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "empty.db")
    store.init_schema()

    obs = load_latest_digest(store=store)

    assert obs.status is ToolObservationStatus.EMPTY
    assert "no saved digest" in obs.summary.lower()
    assert obs.data == {}
    assert obs.caveats == []
    json.dumps(tool_observation_to_dict(obs))


def test_load_latest_digest_ok_full_context(tmp_path: Path) -> None:
    store, run_id = _seed_full_followup_store(tmp_path)

    obs = load_latest_digest(store=store)

    assert obs.status is ToolObservationStatus.OK
    assert "digest" in obs.summary.lower()
    assert obs.data["run_id"] == run_id
    assert obs.data["topics"] == ["RAG"]
    assert obs.data["timeframe"] == "today"
    assert obs.data["entry_count"] == 1
    assert obs.data["digest"]["entries"][0]["title"] == "a/b"
    assert obs.data["warnings"][0]["code"] == "rate"
    json.dumps(tool_observation_to_dict(obs))


def test_get_digest_item_empty_store(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "item-empty.db")
    store.init_schema()

    obs = get_digest_item(store=store, rank=1)

    assert obs.status is ToolObservationStatus.EMPTY
    json.dumps(tool_observation_to_dict(obs))


def test_get_digest_item_not_found_rank(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = get_digest_item(store=store, rank=3)

    assert obs.status is ToolObservationStatus.NOT_FOUND
    assert obs.data["rank"] == 3
    assert any("Try a lower rank" in caveat for caveat in obs.caveats)
    json.dumps(tool_observation_to_dict(obs))


def test_get_digest_item_ok_by_rank(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = get_digest_item(store=store, rank=1)

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["rank"] == 1
    assert obs.data["entry"]["title"] == "a/b"
    assert obs.data["news_item"]["source_id"] == "repo-1"
    assert obs.data["ranked_item"]["score_total"] == 4.2
    json.dumps(tool_observation_to_dict(obs))


def test_get_digest_item_ok_by_source_id(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = get_digest_item(store=store, source_id="repo-1")

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["entry"]["source_id"] == "repo-1"
    json.dumps(tool_observation_to_dict(obs))


def test_get_digest_item_requires_selector(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = get_digest_item(store=store)

    assert obs.status is ToolObservationStatus.NOT_FOUND
    assert any("rank or source_id" in c for c in obs.caveats)


def test_get_source_trace_not_found_rank(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = asyncio.run(get_source_trace(store=store, rank=5))

    assert obs.status is ToolObservationStatus.NOT_FOUND
    assert obs.data["rank"] == 5


def test_get_source_trace_ok_includes_metadata_and_warnings(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = asyncio.run(get_source_trace(store=store, rank=1))

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["news_item"]["raw_snippet"] == "desc"
    assert obs.data["news_item"]["author"] == "alice"
    assert obs.data["entry"]["confidence_caveat"] == "caveat"
    assert obs.data["warnings"][0]["code"] == "rate"
    assert "caveat" in obs.caveats
    json.dumps(tool_observation_to_dict(obs))


def _seed_bilibili_followup_store(tmp_path: Path) -> tuple[DigestStore, int]:
    store = DigestStore(tmp_path / "bili-followup.db")
    store.init_schema()
    collected = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=collected,
        author="Uploader",
        metadata_completeness=0.25,
        raw_snippet="thin search description",
        tags=["bilibili", "video"],
        content_confidence=ConfidenceLevel.LOW,
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="last_7_days",
        topics=["RAG"],
        connector_names=["bilibili"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [
            RankedItem(
                item=item,
                score_total=3.0,
                score_breakdown={"freshness": 1.0},
                selected=True,
                selection_reason="rank #1",
            )
        ],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=collected,
            entries=[
                DigestEntry(
                    source_kind=SourceKind.BILIBILI,
                    source_id="BV1demo00001",
                    title="Bilibili video",
                    source_name="Bilibili",
                    source_url=item.url,
                    summary="S",
                    why_it_matters="W",
                    background_knowledge="B",
                    follow_up_action=FollowUpAction.WATCH,
                )
            ],
            topics=["RAG"],
            timeframe="last_7_days",
        ),
    )
    return store, run_id


def test_get_source_trace_lazy_enriches_bilibili_item(tmp_path: Path) -> None:
    store, run_id = _seed_bilibili_followup_store(tmp_path)
    enriched = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        author="Uploader",
        metadata_completeness=0.7,
        raw_snippet="thin search description\nTags: RAG, Agents\nParts: P1: Intro",
        tags=["bilibili", "video", "RAG"],
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    mock_connector = MagicMock()
    mock_connector.enrich_news_item = AsyncMock(return_value=(enriched, []))

    obs = asyncio.run(
        get_source_trace(
            store=store,
            source_id="BV1demo00001",
            bilibili_connector=mock_connector,
        )
    )

    mock_connector.enrich_news_item.assert_awaited_once()
    assert obs.status is ToolObservationStatus.OK
    assert "Tags:" in obs.data["news_item"]["raw_snippet"]
    ctx = store.get_latest_followup_context()
    stored = next(i for i in ctx.news_items if i.source_id == "BV1demo00001")
    assert "Tags:" in (stored.raw_snippet or "")
    assert run_id == ctx.run_id


def test_get_source_trace_lazy_enrich_partial_failure_surfaces_caveats(
    tmp_path: Path,
) -> None:
    store, _ = _seed_bilibili_followup_store(tmp_path)
    baseline = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        raw_snippet="thin search description",
        tags=["bilibili", "video"],
        content_confidence=ConfidenceLevel.LOW,
    )
    warning = ConnectorWarning(
        connector="bilibili",
        code="enrichment_partial",
        message="Bilibili enrich tags (BV1demo00001) request failed",
    )
    mock_connector = MagicMock()
    mock_connector.enrich_news_item = AsyncMock(return_value=(baseline, [warning]))

    obs = asyncio.run(
        get_source_trace(
            store=store,
            source_id="BV1demo00001",
            bilibili_connector=mock_connector,
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["news_item"]["raw_snippet"] == "thin search description"
    assert any("enrichment_partial" in c for c in obs.caveats)




def test_get_source_trace_auth_required_caveat_is_actionable(tmp_path: Path) -> None:
    store, _ = _seed_bilibili_followup_store(tmp_path)
    baseline = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        raw_snippet="thin search description",
        tags=["bilibili", "video"],
        content_confidence=ConfidenceLevel.LOW,
    )
    warning = ConnectorWarning(
        connector="bilibili",
        code="auth_required_missing",
        message="Bilibili enrich ai_conclusion (BV1demo00001) needs login cookies but none were loaded.",
    )
    mock_connector = MagicMock()
    mock_connector.enrich_news_item = AsyncMock(return_value=(baseline, [warning]))

    obs = asyncio.run(
        get_source_trace(
            store=store,
            source_id="BV1demo00001",
            bilibili_connector=mock_connector,
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert any("cookies were not loaded from the environment" in c for c in obs.caveats)
    assert any("digest-time metadata only" in c.lower() for c in obs.caveats)


def test_get_source_trace_anti_bot_caveat_is_actionable(tmp_path: Path) -> None:
    store, _ = _seed_bilibili_followup_store(tmp_path)
    baseline = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        raw_snippet="thin search description",
        tags=["bilibili", "video"],
        content_confidence=ConfidenceLevel.LOW,
    )
    warning = ConnectorWarning(
        connector="bilibili",
        code="anti_bot_blocked",
        message=(
            "Bilibili uploader videos hit anti-bot/WAF challenge. "
            "Try BILIBILI_HTTP_CLIENT=curl_cffi and BILIBILI_PROXY_URL."
        ),
    )
    mock_connector = MagicMock()
    mock_connector.enrich_news_item = AsyncMock(return_value=(baseline, [warning]))

    obs = asyncio.run(
        get_source_trace(
            store=store,
            source_id="BV1demo00001",
            bilibili_connector=mock_connector,
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert any("anti-bot/WAF challenge" in c for c in obs.caveats)
    assert any("even when login cookies are configured" in c for c in obs.caveats)


def test_get_ranking_explanation_empty_store(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "rank-empty.db")
    store.init_schema()

    obs = get_ranking_explanation(store=store, source_id="repo-1")

    assert obs.status is ToolObservationStatus.EMPTY


def test_get_ranking_explanation_not_found_without_ranking(tmp_path: Path) -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe=None,
    )
    store = DigestStore(tmp_path / "rank-missing.db")
    store.init_schema()
    run_id = store.save_run(
        requested_at=now,
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)

    obs = get_ranking_explanation(store=store, source_id="r1")

    assert obs.status is ToolObservationStatus.NOT_FOUND
    assert "ranking" in obs.summary.lower()


def test_get_ranking_explanation_ok_by_source_id(tmp_path: Path) -> None:
    store, _ = _seed_full_followup_store(tmp_path)

    obs = get_ranking_explanation(store=store, source_id="repo-1")

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["score_total"] == 4.2
    assert obs.data["score_breakdown"]["freshness"] == 2.0
    assert obs.data["selected"] is True
    assert obs.data["selection_reason"] == "best"
    json.dumps(tool_observation_to_dict(obs))
