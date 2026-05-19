"""Tests for BilibiliConnector (Milestone 1 Task 6)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector
from ai_news_agent.models import ConfidenceLevel, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _make_keyword_transport(search_json: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/search/type" in request.url.path:
            st = request.url.params.get("search_type")
            if st == "video":
                return httpx.Response(200, json=search_json)
        return httpx.Response(404, json={"code": -1, "message": "not found"})

    return httpx.MockTransport(handler)


def test_collect_keyword_search_maps_fixture() -> None:
    data = _load_fixture("bilibili_search_sample.json")

    async def main() -> None:
        transport = _make_keyword_transport(data)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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
        transport = httpx.MockTransport(
            lambda r: httpx.Response(404, json={"code": -1}),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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
    space_payload = {
        "code": 0,
        "data": {
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
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/space/arc/search" in request.url.path:
            return httpx.Response(200, json=space_payload)
        return httpx.Response(404, json={"code": -1})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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
    space_payload = {
        "code": 0,
        "data": {
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
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/search/type" in request.url.path:
            if request.url.params.get("search_type") == "bili_user":
                return httpx.Response(200, json=user_search)
        if "/x/space/arc/search" in request.url.path:
            return httpx.Response(200, json=space_payload)
        return httpx.Response(404, json={"code": -1})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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
    view_payload = {
        "code": 0,
        "data": {
            "bvid": "BVmanual01",
            "title": "Manual video title",
            "desc": "Manual description",
            "pubdate": 1715012345,
            "owner": {"name": "OwnerX", "mid": 1},
            "stat": {"view": 9999},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/view" in request.url.path:
            assert request.url.params.get("bvid") == "BVmanual01"
            return httpx.Response(200, json=view_payload)
        return httpx.Response(404, json={"code": -1})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    manual_urls=["https://www.bilibili.com/video/BVmanual01"],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert out.items[0].title == "Manual video title"
        assert out.items[0].raw_snippet is not None
        assert "Manual description" in (out.items[0].raw_snippet or "")

    asyncio.run(main())


def test_collect_manual_url_invalid_emits_warning() -> None:

    async def main() -> None:
        transport = httpx.MockTransport(
            lambda r: httpx.Response(404, json={"code": -1}),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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


def test_collect_search_http_failure_warns() -> None:

    async def main() -> None:
        transport = httpx.MockTransport(
            lambda r: httpx.Response(503, text="unavailable"),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
            out = await conn.collect(
                ConnectorRequest(topics=["AI"], max_items=5),
            )
        assert out.items == []
        assert any(
            w.code in ("keyword_search_failed", "http_error") for w in out.warnings
        )

    asyncio.run(main())


def test_bilibili_connector_name() -> None:

    async def main() -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            assert BilibiliConnector(client=client).name() == "bilibili"

    asyncio.run(main())


def test_collect_dedupes_bvid_across_paths() -> None:
    overlap = _load_fixture("bilibili_search_sample.json")
    view_dup = {
        "code": 0,
        "data": {
            "bvid": "BV1demo0001",
            "title": "Dup from view",
            "desc": "x",
            "pubdate": 1715012345,
            "owner": {"name": "O", "mid": 1},
            "stat": {"view": 1},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/search/type" in request.url.path:
            if request.url.params.get("search_type") == "video":
                return httpx.Response(200, json=overlap)
        if "/x/web-interface/view" in request.url.path:
            return httpx.Response(200, json=view_dup)
        return httpx.Response(404, json={"code": -1})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
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
