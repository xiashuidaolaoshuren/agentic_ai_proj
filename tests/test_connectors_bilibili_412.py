"""Tests for Bilibili anti-bot handling via bilibili-api-python exceptions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from bilibili_api.exceptions import NetworkException, ResponseCodeException

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector


def test_keyword_search_412_emits_anti_bot_warning() -> None:
    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(side_effect=ResponseCodeException(-412, "blocked")),
        ) as mock_search:
            conn = BilibiliConnector()
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert mock_search.await_count >= 1
        assert out.items == []
        assert any(w.code == "anti_bot_blocked" for w in out.warnings)

    asyncio.run(main())


def test_keyword_search_recovers_after_412_retry() -> None:
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

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(
                side_effect=[
                    ResponseCodeException(-412, "blocked"),
                    payload,
                ],
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(
                ConnectorRequest(topics=["RAG", "ML"], max_items=5),
            )

        assert len(out.items) == 1
        assert out.items[0].source_id == "BVretry001"

    asyncio.run(main())


def test_keyword_search_html_payload_classified_as_anti_bot() -> None:
    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(
                side_effect=NetworkException(
                    200,
                    "invalid payload; content-type=text/html; body='<html>blocked</html>'",
                ),
            ),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert out.items == []
        assert any(w.code == "anti_bot_blocked" for w in out.warnings)
        w = next(x for x in out.warnings if x.code == "anti_bot_blocked")
        assert w.detail

    asyncio.run(main())


def test_bilibili_client_uses_cookie_env(monkeypatch) -> None:
    monkeypatch.setenv("BILIBILI_COOKIE", "SESSDATA=abc123")

    async def main() -> None:
        conn = BilibiliConnector()
        assert conn._credential is not None
        assert conn._credential.sessdata == "abc123"

    asyncio.run(main())
