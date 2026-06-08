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


def test_proxy_connection_error_classified_with_actionable_message() -> None:
    from ai_news_agent.connectors.bilibili import _warning_from_exception

    exc = Exception(
        "Failed to perform, curl: (7) Failed to connect to 127.0.0.1 port 7890 "
        "after 2037 ms: Could not connect to server."
    )
    warning = _warning_from_exception(
        exc,
        operation="uploader videos (mid=285286947)",
        failure_code="space_search_failed",
    )
    assert warning.code == "proxy_connection_failed"
    assert "BILIBILI_PROXY_URL" in warning.message


def test_anti_bot_warning_with_credentials_mentions_network_fingerprint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BILIBILI_SESSDATA", "sess")
    monkeypatch.setenv("BILIBILI_BILI_JCT", "jct")
    monkeypatch.setenv("BILIBILI_BUVID3", "buvid")

    from ai_news_agent.connectors.bilibili import _anti_bot_blocked_warning

    warning = _anti_bot_blocked_warning(
        operation="uploader videos (mid=285286947)",
        detail="status code 412",
    )
    assert warning.code == "anti_bot_blocked"
    assert "appear loaded" in warning.message
    assert "curl_cffi" in warning.message


def test_keyword_search_412_message_includes_network_guidance_when_cookies_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BILIBILI_SESSDATA", "sess")
    monkeypatch.setenv("BILIBILI_BILI_JCT", "jct")
    monkeypatch.setenv("BILIBILI_BUVID3", "buvid")

    async def main() -> None:
        with patch(
            "ai_news_agent.connectors.bilibili.search.search_by_type",
            new=AsyncMock(side_effect=ResponseCodeException(-412, "blocked")),
        ):
            conn = BilibiliConnector()
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        w = next(x for x in out.warnings if x.code == "anti_bot_blocked")
        assert "appear loaded" in w.message
        assert "BILIBILI_PROXY_URL" in w.message

    asyncio.run(main())


def test_bilibili_client_uses_sessdata_env(monkeypatch) -> None:
    monkeypatch.setenv("BILIBILI_SESSDATA", "abc123")

    async def main() -> None:
        conn = BilibiliConnector()
        assert conn._credential is not None
        assert conn._credential.sessdata == "abc123"

    asyncio.run(main())
