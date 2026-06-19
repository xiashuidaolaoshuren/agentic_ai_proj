"""Tests for jujuyaya/juya-ai-daily website-primary ingestion in GitHubConnector."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.connectors.github_juya import (
    clean_encoded_html,
    is_juya_daily_repo,
    is_juya_target_url,
    is_juya_website_url,
    markdown_url_for_issue,
    parse_juya_rss_entries,
    parse_juya_rss_rows,
)
from ai_news_agent.models import SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JUYA_GITHUB_URL = "https://github.com/jujuyaya/juya-ai-daily"
JUYA_WEBSITE_URL = "https://daily.juya.uk/"


def _rss_fixture_text() -> str:
    return (FIXTURES / "juya_rss_sample.xml").read_text(encoding="utf-8")


def _website_rss_fixture_text() -> str:
    return (FIXTURES / "juya_website_rss_sample.xml").read_text(encoding="utf-8")


def _website_markdown_fixture_text() -> str:
    return (FIXTURES / "juya_website_2026-06-19_sample.md").read_text(encoding="utf-8")


def _juya_website_transport(
  rss_text: str,
  *,
  rss_status: int = 200,
  markdown_by_path: dict[str, str] | None = None,
) -> httpx.MockTransport:
    markdown_by_path = markdown_by_path or {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        path = request.url.path
        if host == "daily.juya.uk":
            if path == "/rss.xml":
                return httpx.Response(rss_status, text=rss_text)
            if path in markdown_by_path:
                return httpx.Response(200, text=markdown_by_path[path])
            return httpx.Response(404, text="not found")
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


def test_is_juya_daily_repo() -> None:
    assert is_juya_daily_repo("jujuyaya", "juya-ai-daily")
    assert not is_juya_daily_repo("acme", "widget")


def test_is_juya_website_and_target_urls() -> None:
    assert is_juya_website_url("https://daily.juya.uk/")
    assert is_juya_website_url("https://daily.juya.uk/issues/2026-06-19/")
    assert not is_juya_website_url("https://github.com/jujuyaya/juya-ai-daily")
    assert is_juya_target_url(JUYA_GITHUB_URL)
    assert is_juya_target_url(JUYA_WEBSITE_URL)


def test_markdown_url_for_issue_from_title_or_link() -> None:
    assert markdown_url_for_issue("2026-06-19", "https://daily.juya.uk/issues/2026-06-19/") == (
        "https://daily.juya.uk/markdown/2026-06-19.md"
    )
    assert markdown_url_for_issue("issue-5", "https://daily.juya.uk/issues/2026-06-18/") == (
        "https://daily.juya.uk/markdown/2026-06-18.md"
    )


def test_parse_juya_rss_entries_maps_items() -> None:
    items = parse_juya_rss_entries(_rss_fixture_text(), max_items=5)
    assert len(items) == 2
    assert items[0].title == "2026-06-16"
    assert items[0].url == "https://daily.juya.uk/2026/06/16/"
    assert "GLM-5.2" in (items[0].raw_snippet or "")
    assert items[0].source is SourceKind.GITHUB
    assert items[0].tags == ["github", "juya-daily", "rss"]


def test_parse_juya_rss_rows_capture_content_encoded() -> None:
    rows = parse_juya_rss_rows(_website_rss_fixture_text(), max_items=5)
    assert len(rows) == 2
    assert rows[0].content_encoded is not None
    assert "DeepSeek" in clean_encoded_html(rows[0].content_encoded)


def test_collect_juya_github_alias_uses_website_rss() -> None:
    markdown = {
        "/markdown/2026-06-16.md": "# 2026-06-16\n\nGLM-5.2 release notes.",
        "/markdown/2026-06-15.md": "# 2026-06-15\n\nPrior day roundup.",
    }

    async def main() -> None:
        transport = _juya_website_transport(_rss_fixture_text(), markdown_by_path=markdown)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_GITHUB_URL],
                    max_items=5,
                ),
            )
        assert len(out.items) == 2
        assert out.items[0].title == "2026-06-16"
        assert "daily.juya.uk" in out.items[0].url
        assert "GLM-5.2" in (out.items[0].raw_snippet or "")
        assert "juya-markdown" in out.items[0].tags
        assert not any(w.code == "juya_rss_unavailable" for w in out.warnings)

    asyncio.run(main())


def test_collect_juya_website_url_uses_same_workflow() -> None:
    markdown = {
        "/markdown/2026-06-19.md": _website_markdown_fixture_text(),
        "/markdown/2026-06-18.md": "# 2026-06-18\n\nFallback issue body.",
    }

    async def main() -> None:
        transport = _juya_website_transport(
            _website_rss_fixture_text(),
            markdown_by_path=markdown,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            out = await GitHubConnector(token=None, client=client).collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_WEBSITE_URL],
                    max_items=5,
                ),
            )
        assert len(out.items) == 2
        assert out.items[0].title == "2026-06-19"
        assert "DeepSeek" in (out.items[0].raw_snippet or "")
        assert out.items[0].url == "https://daily.juya.uk/issues/2026-06-19/"

    asyncio.run(main())


def test_collect_juya_target_returns_warning_without_repo_fallback() -> None:
    async def main() -> None:
        transport = _juya_website_transport(_rss_fixture_text(), rss_status=404)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_GITHUB_URL],
                    max_items=5,
                ),
            )
        assert out.items == []
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
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
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
        assert "daily.juya.uk" not in requested_hosts

    asyncio.run(main())
