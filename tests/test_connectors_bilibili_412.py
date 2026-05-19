"""Tests for Bilibili anti-bot handling (HTTP 412 retries and warnings)."""

from __future__ import annotations

import asyncio

import httpx

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector


def test_keyword_search_412_emits_anti_bot_warning() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "/x/web-interface/search/type" in request.url.path:
            return httpx.Response(412, text="blocked")
        return httpx.Response(404)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert out.items == []
        assert calls["n"] >= 1
        assert any(w.code == "anti_bot_blocked" for w in out.warnings)

    asyncio.run(main())


def test_keyword_search_recovers_after_412_retry() -> None:
    attempts = {"n": 0}
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "type": "video",
                    "bvid": "BVretry001",
                    "title": "Recovered",
                    "author": "U",
                    "play": 1,
                    "description": "d",
                    "created": 1715000000,
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/search/type" not in request.url.path:
            return httpx.Response(404)
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(412, text="blocked")
        return httpx.Response(200, json=payload)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert len(out.items) == 1
        assert out.items[0].source_id == "BVretry001"

    asyncio.run(main())


def test_keyword_search_html_payload_classified_as_anti_bot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/x/web-interface/search/type" in request.url.path:
            return httpx.Response(
                200,
                text="<html>blocked</html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.bilibili.com",
        ) as client:
            conn = BilibiliConnector(client=client)
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert out.items == []
        assert any(w.code == "anti_bot_blocked" for w in out.warnings)
        w = next(x for x in out.warnings if x.code == "anti_bot_blocked")
        assert w.detail and "content-type" in w.detail

    asyncio.run(main())


def test_bilibili_client_uses_cookie_env(monkeypatch) -> None:
    monkeypatch.setenv("BILIBILI_COOKIE", "SESSDATA=abc123")

    async def main() -> None:
        conn = BilibiliConnector()
        try:
            assert conn._client.cookies is not None
            assert conn._client.cookies.get("SESSDATA") == "abc123"
        finally:
            await conn.aclose()

    asyncio.run(main())
