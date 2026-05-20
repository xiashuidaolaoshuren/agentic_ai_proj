"""Tests for BilibiliConnector (Milestone 1 Task 6)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bilibili_api.exceptions import NetworkException, ResponseCodeException
from bilibili_api.search import SearchObjectType

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector
from ai_news_agent.models import ConfidenceLevel, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


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
        first = out.items[0]
        assert first.source_id == "BV1demo0001"
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
        VideoCls.assert_called_once()
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
