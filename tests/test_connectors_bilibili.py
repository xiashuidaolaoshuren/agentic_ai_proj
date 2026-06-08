"""Tests for BilibiliConnector (Milestone 1 Task 6)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bilibili_api.exceptions import ArgsException, NetworkException, ResponseCodeException
from bilibili_api.search import SearchObjectType

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector
from ai_news_agent.models import ConfidenceLevel, NewsItem, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _mock_ass_subtitle_object(segments: list[dict] | None = None) -> MagicMock:
    obj = MagicMock()
    obj.to_simple_json.return_value = segments or []
    return obj


def _load_fixture(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def test_collect_keyword_search_maps_fixture() -> None:
    data = _load_fixture("bilibili_search_sample.json")

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(return_value=data),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=["RAG", "agents"], max_items=10),
            )
        assert out.raw_count == len(data["data"]["result"])
        assert len(out.items) == out.raw_count
        assert all(i.source is SourceKind.BILIBILI for i in out.items)
        assert all(i.content_confidence is ConfidenceLevel.LOW for i in out.items)
        assert any(w.code == "metadata_limited" for w in out.warnings)
        by_id = {i.source_id: i for i in out.items}
        first = by_id["BV1demo0001"]
        assert "Multimodal" in first.title
        assert first.url == "https://www.bilibili.com/video/BV1demo0001"
        assert first.author == "AILabChannel"

    asyncio.run(main())


def test_collect_empty_inputs_returns_warning() -> None:

    async def main() -> None:
        conn = BilibiliConnector()
        out = await conn.collect(
            ConnectorRequest(
                topics=[],
                target_channels=[],
                manual_urls=[],
            ),
        )
        assert out.items == []
        assert out.raw_count == 0
        assert any(w.code == "no_input" for w in out.warnings)

    asyncio.run(main())


def test_channel_collect_filters_videos_outside_last_7_days() -> None:
    recent_ts = int(datetime(2026, 6, 1, 12, 0, tzinfo=UTC).timestamp())
    old_ts = int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp())
    feed_data = {
        "list": {
            "vlist": [
                {
                    "bvid": "BVoldfeed",
                    "title": "Old upload",
                    "author": "Uploader",
                    "play": 1,
                    "created": old_ts,
                },
                {
                    "bvid": "BVnewfeed",
                    "title": "Recent upload",
                    "author": "Uploader",
                    "play": 2,
                    "created": recent_ts,
                },
            ]
        }
    }

    async def main() -> None:
        mock_user = MagicMock()
        mock_user.get_videos = AsyncMock(return_value=feed_data)
        with (
            patch(
                "ai_news_agent.connectors.bilibili.datetime",
                wraps=datetime,
            ) as mock_dt,
            patch(
                "ai_news_agent.connectors.bilibili.user.User",
                return_value=mock_user,
            ),
        ):
            mock_dt.now.return_value = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    target_channels=["123456789"],
                    timeframe="last_7_days",
                    max_items=10,
                ),
            )
        assert [i.source_id for i in out.items] == ["BVnewfeed"]

    asyncio.run(main())


def test_channel_manual_url_filters_video_outside_last_7_days() -> None:
    old_ts = int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp())
    view_data = {
        "bvid": "BVmanualold",
        "title": "Old manual video",
        "desc": "x",
        "pubdate": old_ts,
        "owner": {"name": "OwnerX", "mid": 1},
        "stat": {"view": 1},
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value=view_data)
        with (
            patch(
                "ai_news_agent.connectors.bilibili.datetime",
                wraps=datetime,
            ) as mock_dt,
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
        ):
            mock_dt.now.return_value = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    manual_urls=["https://www.bilibili.com/video/BVmanualold"],
                    timeframe="last_7_days",
                    max_items=5,
                ),
            )
        assert out.items == []

    asyncio.run(main())


def test_collect_target_channel_space_list() -> None:
    feed_data = {
        "list": {
            "vlist": [
                {
                    "bvid": "BVspace001",
                    "title": "From uploader feed",
                    "author": "UploaderName",
                    "play": 100,
                    "description": "desc",
                    "created": 1715000000,
                }
            ]
        }
    }

    async def main() -> None:
        mock_user = MagicMock()
        mock_user.get_videos = AsyncMock(return_value=feed_data)
        with patch(
            "ai_news_agent.connectors.bilibili.user.User",
            return_value=mock_user,
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=[], target_channels=["123456789"], max_items=5),
            )
        assert len(out.items) == 1
        assert out.items[0].source_id == "BVspace001"
        assert out.items[0].author == "UploaderName"
        assert out.raw_count >= 1

    asyncio.run(main())


def test_collect_target_channel_name_resolved_via_user_search() -> None:
    user_search = {
        "code": 0,
        "data": {
            "result": [
                {
                    "type": "bili_user",
                    "mid": 424242,
                }
            ]
        },
    }
    feed_data = {
        "list": {
            "vlist": [
                {
                    "bvid": "BVaftersearch",
                    "title": "Resolved uploader",
                    "author": "Resolved",
                    "play": 1,
                    "description": None,
                }
            ]
        }
    }

    async def search_side_effect(**kwargs: object) -> dict:
        if kwargs.get("search_type") == SearchObjectType.USER:
            return user_search
        return {"code": -1, "data": {}}

    async def main() -> None:
        mock_user = MagicMock()
        mock_user.get_videos = AsyncMock(return_value=feed_data)
        with (
            patch(
                "ai_news_agent.connectors.bilibili.search.search_by_type",
                new=AsyncMock(side_effect=search_side_effect),
            ),
            patch(
                "ai_news_agent.connectors.bilibili.user.User",
                return_value=mock_user,
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    target_channels=["MyFavoriteUP"],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert out.items[0].source_id == "BVaftersearch"

    asyncio.run(main())


def test_collect_does_not_bulk_enrich_keyword_items() -> None:
    data = _load_fixture("bilibili_search_sample.json")
    data = {
        **data,
        "data": {
            **data["data"],
            "result": [
                {
                    **data["data"]["result"][0],
                    "bvid": "BV1demo00001",
                },
                *data["data"]["result"][1:],
            ],
        },
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_tags = AsyncMock()
        with (
            patch(
                "ai_news_agent.connectors.bilibili.search.search_by_type",
                new=AsyncMock(return_value=data),
            ),
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=["RAG"], max_items=10),
            )

        item = next(i for i in out.items if i.source_id == "BV1demo00001")
        assert item.content_confidence is ConfidenceLevel.LOW
        assert "Tags:" not in (item.raw_snippet or "")
        mock_video.get_tags.assert_not_called()

    asyncio.run(main())


def test_enrich_news_item_adds_tags_pages_related_snippet() -> None:
    data = _load_fixture("bilibili_search_sample.json")
    data = {
        **data,
        "data": {
            **data["data"],
            "result": [
                {
                    **data["data"]["result"][0],
                    "bvid": "BV1demo00001",
                },
                *data["data"]["result"][1:],
            ],
        },
    }
    view_info = {
        "bvid": "BV1demo00001",
        "title": "Multimodal RAG in 15 minutes",
        "desc": "Full video description from view API.",
        "owner": {"name": "AILabChannel", "mid": 99},
        "stat": {"view": 20000},
        "pubdate": 1715000000,
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value=view_info)
        mock_video.get_tags = AsyncMock(
            return_value=[
                {"tag_name": "RAG"},
                {"tag_name": "Multimodal"},
            ]
        )
        mock_video.get_pages = AsyncMock(
            return_value=[
                {"page": 1, "part": "Intro", "cid": 111, "duration": 120},
                {"page": 2, "part": "Demo", "cid": 222, "duration": 300},
            ]
        )
        mock_video.get_related = AsyncMock(
            return_value=[
                {"title": "Related agent video", "bvid": "BVrelated01"},
            ]
        )
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="Multimodal RAG in 15 minutes",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="Overview of retrieval patterns for multimodal inputs.",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector()
            enriched, warnings = await conn.enrich_news_item(baseline, ["RAG"])

        assert not warnings
        assert enriched.metadata_completeness >= 0.55
        assert enriched.content_confidence is ConfidenceLevel.MEDIUM
        assert "RAG" in enriched.tags
        assert "Multimodal" in enriched.tags
        snippet = enriched.raw_snippet or ""
        assert "Tags:" in snippet
        assert "Parts:" in snippet
        assert "Related:" in snippet
        assert "Full video description" in snippet

    asyncio.run(main())


def test_enrich_partial_failure_still_returns_item_with_warning() -> None:
    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(
            side_effect=NetworkException(503, "service unavailable")
        )
        mock_video.get_tags = AsyncMock(side_effect=NetworkException(503, "tags down"))
        mock_video.get_pages = AsyncMock(return_value=[])
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector()
            item, warnings = await conn.enrich_news_item(baseline, ["RAG"])

        assert item.source_id == "BV1demo00001"
        assert any(w.code == "enrichment_partial" for w in warnings)

    asyncio.run(main())


def test_enrich_full_transcript_populates_snippet() -> None:
    segments = [
        {"cnt": 1, "start_time": 0.0, "end_time": 2.0, "content": "OpenAI Codex plugins"},
        {"cnt": 2, "start_time": 2.0, "end_time": 5.0, "content": "GitHub Copilot and Claude Code"},
    ]

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="AI news roundup",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="Short desc",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(segments),
            ),
        ):
            conn = BilibiliConnector()
            enriched, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert not warnings
        snippet = enriched.raw_snippet or ""
        assert "GitHub Copilot and Claude Code" in snippet
        assert "Transcript:" in snippet
        assert enriched.metadata_completeness >= 0.75

    asyncio.run(main())


def test_enrich_ai_conclusion_populates_snippet() -> None:
    ai_payload = {
        "data": {
            "model_result": {
                "summary": "Covers Codex plugins and knowledge-work report.",
                "outline": [
                    {
                        "title": "Codex update",
                        "part_outline": [{"content": "Six business plugins"}],
                    },
                ],
            }
        }
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value=ai_payload)

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="AI news roundup",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="Short desc",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector()
            enriched, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert not warnings
        snippet = enriched.raw_snippet or ""
        assert "Covers Codex plugins and knowledge-work report" in snippet
        assert "AI summary:" in snippet
        assert "Six business plugins" in snippet

    asyncio.run(main())


def test_pick_subtitle_track_url_supports_subtitles_key() -> None:
    from ai_news_agent.connectors.bilibili import _pick_subtitle_track_url

    url = _pick_subtitle_track_url(
        {
            "subtitles": [
                {"lan": "ai-zh", "subtitle_url": "//example.com/sub.json"},
            ]
        }
    )
    assert url == "https://example.com/sub.json"


def test_enrich_subtitle_api_failure_graceful() -> None:
    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[{"tag_name": "AI"}])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(return_value={"subtitles": []})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=NetworkException(503, "subtitle down"),
            ),
        ):
            conn = BilibiliConnector()
            item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert item.source_id == "BV1demo00001"
        assert any(w.code == "subtitle_unavailable" for w in warnings)
        assert "Tags:" in (item.raw_snippet or "")

    asyncio.run(main())


def test_enriched_snippet_is_length_bounded() -> None:
    long_desc = "x" * 5000

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(
            return_value={
                "bvid": "BV0000000001",
                "title": "Long desc video",
                "desc": long_desc,
                "owner": {"name": "Author"},
                "stat": {"view": 1},
            }
        )
        mock_video.get_tags = AsyncMock(return_value=[{"tag_name": "AI"}])
        mock_video.get_pages = AsyncMock(return_value=[])
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV0000000001",
            url="https://www.bilibili.com/video/BV0000000001",
            title="Long desc video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet=long_desc,
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector()
            item, _warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert item.raw_snippet is not None
        assert len(item.raw_snippet) <= 6000

    asyncio.run(main())




def test_enrich_subtitle_auth_required_maps_to_auth_required_code() -> None:
    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(return_value={"list": []})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1aJ7z6yEad",
            url="https://www.bilibili.com/video/BV1aJ7z6yEad",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=ArgsException("Credential missing sessdata"),
            ),
        ):
            conn = BilibiliConnector(credential=None)
            item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert item.source_id == "BV1aJ7z6yEad"
        assert any(w.code == "auth_required_missing" for w in warnings)

    asyncio.run(main())


def test_enrich_subtitle_fallback_without_cookies_uses_track_url() -> None:
    body = [{"from": 0.0, "to": 2.0, "content": "GitHub Copilot and Claude Code"}]

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(
            return_value={
                "list": [
                    {
                        "lan": "ai-zh",
                        "subtitle_url": "//example.com/sub.json",
                    }
                ]
            }
        )

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1aJ7z6yEad",
            url="https://www.bilibili.com/video/BV1aJ7z6yEad",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=ArgsException("Credential missing sessdata"),
            ),
            patch(
                "ai_news_agent.connectors.bilibili.Api",
            ) as mock_api_cls,
        ):
            mock_api = MagicMock()
            mock_api.request = AsyncMock(return_value={"body": body})
            mock_api_cls.return_value = mock_api
            conn = BilibiliConnector(credential=None)
            item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert not any(w.code.startswith("auth_required") for w in warnings)
        assert "GitHub Copilot and Claude Code" in (item.raw_snippet or "")

    asyncio.run(main())


def test_enrich_subtitle_fallback_uses_subtitles_key() -> None:
    body = [{"from": 0.0, "to": 2.0, "content": "NVIDIA Nemotron release notes"}]

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(
            return_value={
                "subtitles": [
                    {
                        "lan": "ai-zh",
                        "subtitle_url": "//example.com/sub.json",
                    }
                ]
            }
        )

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1aJ7z6yEad",
            url="https://www.bilibili.com/video/BV1aJ7z6yEad",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=ArgsException("没有找到指定字幕"),
            ),
            patch("ai_news_agent.connectors.bilibili.Api") as mock_api_cls,
        ):
            mock_api = MagicMock()
            mock_api.request = AsyncMock(return_value={"body": body})
            mock_api_cls.return_value = mock_api
            conn = BilibiliConnector(credential=None)
            item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert "NVIDIA Nemotron release notes" in (item.raw_snippet or "")
        assert not any(w.code == "subtitle_unavailable" for w in warnings)

    asyncio.run(main())


def test_enrich_subtitle_unavailable_when_no_tracks() -> None:
    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(return_value={"subtitles": []})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1Wu7m6WEQ6",
            url="https://www.bilibili.com/video/BV1Wu7m6WEQ6",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=ArgsException("没有找到指定字幕"),
            ),
        ):
            conn = BilibiliConnector()
            _item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert any(w.code == "subtitle_unavailable" for w in warnings)
        assert not any(w.code == "enrichment_partial" for w in warnings)

    asyncio.run(main())


def test_enrich_subtitle_fetch_failed_when_tracks_present() -> None:
    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={})
        mock_video.get_subtitle = AsyncMock(
            return_value={
                "subtitles": [
                    {"lan": "ai-zh", "subtitle_url": "//example.com/sub.json"},
                ]
            }
        )

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1demo00001",
            url="https://www.bilibili.com/video/BV1demo00001",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                side_effect=NetworkException(503, "subtitle down"),
            ),
            patch("ai_news_agent.connectors.bilibili.Api") as mock_api_cls,
        ):
            mock_api = MagicMock()
            mock_api.request = AsyncMock(side_effect=NetworkException(503, "download failed"))
            mock_api_cls.return_value = mock_api
            conn = BilibiliConnector()
            _item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert any(w.code == "subtitle_fetch_failed" for w in warnings)

    asyncio.run(main())


def test_enrich_ai_conclusion_auth_required_from_response_code(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BILIBILI_SESSDATA", raising=False)
    monkeypatch.delenv("BILIBILI_BILI_JCT", raising=False)
    monkeypatch.delenv("BILIBILI_BUVID3", raising=False)

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={"code": -101, "message": "未登录"})
        mock_video.get_subtitle = AsyncMock(return_value={"list": []})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1aJ7z6yEad",
            url="https://www.bilibili.com/video/BV1aJ7z6yEad",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        with (
            patch("ai_news_agent.connectors.bilibili.video.Video", return_value=mock_video),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector(credential=None)
            _item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert any(w.code == "auth_required_missing" for w in warnings)

    asyncio.run(main())


def test_enrich_ai_conclusion_rejected_when_credential_present() -> None:
    from bilibili_api import Credential

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value={})
        mock_video.get_tags = AsyncMock(return_value=[])
        mock_video.get_pages = AsyncMock(
            return_value=[{"page": 1, "part": "Main", "cid": 111, "duration": 600}]
        )
        mock_video.get_related = AsyncMock(return_value=[])
        mock_video.get_ai_conclusion = AsyncMock(return_value={"code": -101, "message": "未登录"})

        baseline = NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1aJ7z6yEad",
            url="https://www.bilibili.com/video/BV1aJ7z6yEad",
            title="Video",
            collected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_snippet="thin",
            tags=["bilibili", "video"],
            content_confidence=ConfidenceLevel.LOW,
        )
        cred = Credential(sessdata="s", bili_jct="j", buvid3="b")
        with (
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
            patch(
                "ai_news_agent.connectors.bilibili.ass.request_subtitle",
                new_callable=AsyncMock,
                return_value=_mock_ass_subtitle_object(),
            ),
        ):
            conn = BilibiliConnector(credential=cred)
            _item, warnings = await conn.enrich_news_item(baseline, ["AI"])

        assert any(w.code == "auth_required_rejected" for w in warnings)

    asyncio.run(main())


def test_collect_manual_urls_uses_view_api() -> None:
    view_data = {
        "bvid": "BVmanual01",
        "title": "Manual video title",
        "desc": "Manual description",
        "pubdate": 1715012345,
        "owner": {"name": "OwnerX", "mid": 1},
        "stat": {"view": 9999},
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value=view_data)
        with patch(
            "ai_news_agent.connectors.bilibili.video.Video",
            return_value=mock_video,
        ) as VideoCls:
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    manual_urls=["https://www.bilibili.com/video/BVmanual01"],
                    max_items=5,
                ),
            )
        assert VideoCls.call_count >= 1
        assert VideoCls.call_args.kwargs.get("bvid") == "BVmanual01"
        assert len(out.items) == 1
        assert out.items[0].title == "Manual video title"
        assert out.items[0].raw_snippet is not None
        assert "Manual description" in (out.items[0].raw_snippet or "")

    asyncio.run(main())


def test_collect_manual_url_invalid_emits_warning() -> None:

    async def main() -> None:
        conn = BilibiliConnector()
        out = await conn.collect(
            ConnectorRequest(
                topics=[],
                manual_urls=["https://example.com/not-bilibili"],
                max_items=5,
            ),
        )
        assert out.items == []
        assert any(w.code == "invalid_manual_url" for w in out.warnings)

    asyncio.run(main())


def test_keyword_fallback_does_not_duplicate_invalid_json_warnings() -> None:
    blocked = ResponseCodeException(-412, "blocked")

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(side_effect=blocked),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=["AI", "ML"], max_items=5),
            )

        json_warnings = [
            w for w in out.warnings if w.code in ("anti_bot_blocked", "invalid_payload")
        ]
        assert len(json_warnings) <= 3
        assert len(out.warnings) < 10

    asyncio.run(main())


def test_invalid_json_warning_includes_payload_context() -> None:
    html_detail = "content-type='text/html'; body='<!DOCTYPE html><title>verify</title>'"

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(
                side_effect=NetworkException(
                    200,
                    f"invalid json; {html_detail}",
                ),
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        w = next(x for x in out.warnings if x.code == "anti_bot_blocked")
        assert w.detail is not None
        assert "content-type" in w.detail.lower() or "html" in w.detail.lower()

    asyncio.run(main())


def test_collect_search_http_failure_warns() -> None:

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(side_effect=NetworkException(503, "service unavailable")),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=["AI"], max_items=5),
            )
        assert out.items == []
        assert any(
            w.code in ("keyword_search_failed", "http_error") for w in out.warnings
        )

    asyncio.run(main())


def test_timeframe_last_7_days_maps_to_date_window() -> None:
    from datetime import UTC, datetime, timedelta

    from ai_news_agent.connectors.bilibili import _timeframe_to_dates

    fixed_today = datetime(2026, 6, 2, 12, 0, tzinfo=UTC).date()
    with patch(
        "ai_news_agent.connectors.bilibili.datetime",
        wraps=datetime,
    ) as mock_dt:
        mock_dt.now.return_value = datetime(
            2026, 6, 2, 12, 0, tzinfo=UTC
        )
        start, end = _timeframe_to_dates("last_7_days")

    assert start == (fixed_today - timedelta(days=7)).isoformat()
    assert end == fixed_today.isoformat()


def test_timeframe_last_30_days_maps_to_date_window() -> None:
    from datetime import UTC, datetime, timedelta

    from ai_news_agent.connectors.bilibili import _timeframe_to_dates

    fixed_today = datetime(2026, 6, 2, 12, 0, tzinfo=UTC).date()
    with patch(
        "ai_news_agent.connectors.bilibili.datetime",
        wraps=datetime,
    ) as mock_dt:
        mock_dt.now.return_value = datetime(
            2026, 6, 2, 12, 0, tzinfo=UTC
        )
        start, end = _timeframe_to_dates("last_30_days")

    assert start == (fixed_today - timedelta(days=30)).isoformat()
    assert end == fixed_today.isoformat()


def test_video_row_timestamp_parses_ctime_field() -> None:
    from ai_news_agent.connectors.bilibili import _video_row_to_news_item

    ts = int(datetime(2026, 6, 2, 8, 0, tzinfo=UTC).timestamp())
    row = {
        "bvid": "BVctime01",
        "title": "Uses ctime",
        "ctime": ts,
    }
    item = _video_row_to_news_item(row, [], datetime(2026, 6, 2, 12, 0, tzinfo=UTC))

    assert item is not None
    assert item.published_at is not None
    assert item.published_at == datetime.fromtimestamp(ts, tz=UTC)


def test_video_row_timestamp_parses_numeric_string_pubdate() -> None:
    from ai_news_agent.connectors.bilibili import _video_row_to_news_item

    ts = int(datetime(2026, 6, 2, 9, 0, tzinfo=UTC).timestamp())
    row = {
        "bvid": "BVstrts01",
        "title": "String epoch",
        "pubdate": str(ts),
    }
    item = _video_row_to_news_item(row, [], datetime(2026, 6, 2, 12, 0, tzinfo=UTC))

    assert item is not None
    assert item.published_at is not None
    assert item.published_at == datetime.fromtimestamp(ts, tz=UTC)


def test_view_data_timestamp_parses_ctime_fallback() -> None:
    from ai_news_agent.connectors.bilibili import _view_data_to_news_item

    ts = int(datetime(2026, 6, 2, 10, 0, tzinfo=UTC).timestamp())
    data = {
        "bvid": "BVview01",
        "title": "View ctime",
        "ctime": ts,
        "owner": {"name": "Owner"},
        "stat": {"view": 1},
    }
    item = _view_data_to_news_item(data, [], datetime(2026, 6, 2, 12, 0, tzinfo=UTC))

    assert item is not None
    assert item.published_at is not None
    assert item.published_at == datetime.fromtimestamp(ts, tz=UTC)


def test_timeframe_today_start_before_end() -> None:
    from ai_news_agent.connectors.bilibili import _timeframe_to_dates

    start, end = _timeframe_to_dates("today")
    assert start is not None
    assert end is not None
    assert start < end


def test_keyword_search_today_passes_dates_to_library() -> None:
    from ai_news_agent.connectors.bilibili import _timeframe_to_dates

    captured: dict[str, str | None] = {}

    async def capture_search(**kwargs: object) -> dict:
        captured["time_start"] = kwargs.get("time_start")  # type: ignore[assignment]
        captured["time_end"] = kwargs.get("time_end")  # type: ignore[assignment]
        return {"result": []}

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(side_effect=capture_search),
        ):
            conn = BilibiliConnector()
            await conn.collect(
                ConnectorRequest(topics=["AI"], timeframe="today", max_items=5),
            )

        start, end = _timeframe_to_dates("today")
        assert captured["time_start"] == start
        assert captured["time_end"] == end
        assert captured["time_start"] != captured["time_end"]

    asyncio.run(main())


def test_bilibili_connector_name() -> None:
    assert BilibiliConnector().name() == "bilibili"


def test_sort_channel_collect_orders_newest_first_missing_timestamp_last() -> None:
    ts_new = int(datetime(2026, 6, 1, 12, 0, tzinfo=UTC).timestamp())
    ts_old = int(datetime(2026, 5, 20, 12, 0, tzinfo=UTC).timestamp())
    feed_data = {
        "list": {
            "vlist": [
                {
                    "bvid": "BVnotimestamp",
                    "title": "No timestamp",
                    "author": "U",
                    "play": 1,
                },
                {
                    "bvid": "BVolder",
                    "title": "Older",
                    "author": "U",
                    "play": 1,
                    "created": ts_old,
                },
                {
                    "bvid": "BVnewer",
                    "title": "Newer",
                    "author": "U",
                    "play": 2,
                    "created": ts_new,
                },
            ]
        }
    }

    async def main() -> None:
        mock_user = MagicMock()
        mock_user.get_videos = AsyncMock(return_value=feed_data)
        with patch(
            "ai_news_agent.connectors.bilibili.user.User",
            return_value=mock_user,
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    target_channels=["999"],
                    max_items=10,
                ),
            )
        assert [i.source_id for i in out.items] == [
            "BVnewer",
            "BVolder",
            "BVnotimestamp",
        ]

    asyncio.run(main())


def test_sort_dedupe_keeps_published_at_when_channel_row_lacks_timestamp() -> None:
    search_data = _load_fixture("bilibili_search_sample.json")
    search_data["data"]["result"][0]["pubdate"] = int(
        datetime(2026, 6, 1, 12, 0, tzinfo=UTC).timestamp()
    )
    feed_data = {
        "list": {
            "vlist": [
                {
                    "bvid": "BV1demo0001",
                    "title": "Channel row without date",
                    "author": "Uploader",
                    "play": 1,
                }
            ]
        }
    }

    async def main() -> None:
        mock_user = MagicMock()
        mock_user.get_videos = AsyncMock(return_value=feed_data)
        with (
            patch(
                "ai_news_agent.connectors.bilibili.search.search_by_type",
                new=AsyncMock(return_value=search_data),
            ),
            patch(
                "ai_news_agent.connectors.bilibili.user.User",
                return_value=mock_user,
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=["RAG"],
                    target_channels=["123456789"],
                    max_items=10,
                ),
            )
        item = next(i for i in out.items if i.source_id == "BV1demo0001")
        assert item.published_at is not None

    asyncio.run(main())


def test_collect_dedupes_bvid_across_paths() -> None:
    overlap = _load_fixture("bilibili_search_sample.json")
    view_data = {
        "bvid": "BV1demo0001",
        "title": "Dup from view",
        "desc": "x",
        "pubdate": 1715012345,
        "owner": {"name": "O", "mid": 1},
        "stat": {"view": 1},
    }

    async def main() -> None:
        mock_video = MagicMock()
        mock_video.get_info = AsyncMock(return_value=view_data)
        with (
            patch(
                "ai_news_agent.connectors.bilibili.search.search_by_type",
                new=AsyncMock(return_value=overlap),
            ),
            patch(
                "ai_news_agent.connectors.bilibili.video.Video",
                return_value=mock_video,
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(
                    topics=["RAG"],
                    manual_urls=["https://www.bilibili.com/video/BV1demo0001"],
                    max_items=20,
                ),
            )
        bvids = [i.source_id for i in out.items]
        assert bvids.count("BV1demo0001") == 1

    asyncio.run(main())
