"""Tests for jujuyaya/juya-ai-daily RSS ingestion in GitHubConnector."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.connectors.github_juya import (
    is_juya_daily_repo,
    parse_juya_rss_entries,
)
from ai_news_agent.models import SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JUYA_URL = "https://github.com/jujuyaya/juya-ai-daily"


def _rss_fixture_text() -> str:
    return (FIXTURES / "juya_rss_sample.xml").read_text(encoding="utf-8")


def test_is_juya_daily_repo() -> None:
    assert is_juya_daily_repo("jujuyaya", "juya-ai-daily")
    assert not is_juya_daily_repo("acme", "widget")


def test_parse_juya_rss_entries_maps_items() -> None:
    items = parse_juya_rss_entries(_rss_fixture_text(), max_items=5)
    assert len(items) == 2
    assert items[0].title == "2026-06-16"
    assert items[0].url == "https://daily.juya.uk/2026/06/16/"
    assert "GLM-5.2" in (items[0].raw_snippet or "")
    assert items[0].source is SourceKind.GITHUB
    assert items[0].tags == ["github", "juya-daily", "rss"]


def test_collect_juya_repo_uses_rss_items() -> None:
    rss_b64 = base64.b64encode(_rss_fixture_text().encode("utf-8")).decode("ascii")
    repo_payload = {
        "id": 999,
        "full_name": "jujuyaya/juya-ai-daily",
        "html_url": JUYA_URL,
        "description": "橘鸦AI早报",
        "pushed_at": "2026-06-16T00:00:00Z",
        "stargazers_count": 33,
        "owner": {"login": "jujuyaya"},
        "language": "Python",
        "topics": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/jujuyaya/juya-ai-daily/contents/rss.xml":
            return httpx.Response(
                200,
                json={"content": rss_b64, "encoding": "base64"},
            )
        if path == "/repos/jujuyaya/juya-ai-daily":
            return httpx.Response(200, json=repo_payload)
        return httpx.Response(404, json={"message": "not found"})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_URL],
                    max_items=5,
                ),
            )
        assert len(out.items) == 2
        assert out.items[0].title == "2026-06-16"
        assert "daily.juya.uk" in out.items[0].url
        assert not any(w.code == "juya_rss_unavailable" for w in out.warnings)

    asyncio.run(main())


def test_collect_juya_repo_falls_back_when_rss_missing() -> None:
    repo_payload = {
        "id": 999,
        "full_name": "jujuyaya/juya-ai-daily",
        "html_url": JUYA_URL,
        "description": "橘鸦AI早报",
        "pushed_at": "2026-06-16T00:00:00Z",
        "stargazers_count": 33,
        "owner": {"login": "jujuyaya"},
        "language": "Python",
        "topics": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/jujuyaya/juya-ai-daily/contents/rss.xml":
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/jujuyaya/juya-ai-daily":
            return httpx.Response(200, json=repo_payload)
        if path.endswith("/readme"):
            return httpx.Response(404)
        return httpx.Response(404, json={"message": "not found"})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_URL],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert out.items[0].title == "jujuyaya/juya-ai-daily"
        assert any(w.code == "juya_rss_unavailable" for w in out.warnings)

    asyncio.run(main())


def test_collect_non_juya_repo_unchanged() -> None:
    repo_payload = {
        "id": 42,
        "full_name": "acme/widget",
        "html_url": "https://github.com/acme/widget",
        "description": "A widget",
        "pushed_at": "2026-05-01T00:00:00Z",
        "stargazers_count": 10,
        "owner": {"login": "acme"},
        "language": "Python",
        "topics": [],
    }
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/repos/acme/widget":
            return httpx.Response(200, json=repo_payload)
        if request.url.path.endswith("/readme"):
            return httpx.Response(404)
        return httpx.Response(404, json={"message": "not found"})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=["https://github.com/acme/widget"],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert out.items[0].title == "acme/widget"
        assert not any("/contents/rss.xml" in p for p in requested_paths)

    asyncio.run(main())
