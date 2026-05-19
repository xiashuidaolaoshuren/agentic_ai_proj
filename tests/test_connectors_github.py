"""Tests for GitHubConnector (Milestone 1 Task 5)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.models import ConfidenceLevel, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _make_transport(
    *,
    search_json: dict | None = None,
    search_status: int = 200,
    search_headers: dict[str, str] | None = None,
    readme_by_repo: dict[str, str] | None = None,
    readme_status: int = 200,
) -> httpx.MockTransport:
    """Route GitHub API paths to canned responses."""

    readme_by_repo = readme_by_repo or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/repositories":
            return httpx.Response(
                search_status,
                json=search_json if search_json is not None else {"items": []},
                headers=search_headers or {},
            )
        if path.startswith("/repos/") and path.endswith("/readme"):
            # /repos/{owner}/{repo}/readme
            parts = path.strip("/").split("/")
            if len(parts) >= 4:
                owner, repo = parts[1], parts[2]
                key = f"{owner}/{repo}"
                if key in readme_by_repo:
                    return httpx.Response(readme_status, text=readme_by_repo[key])
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(404, json={"message": "unexpected path", "path": path})

    return httpx.MockTransport(handler)


def test_collect_maps_fixture_and_incomplete_results_warning() -> None:
    data = _load_fixture("github_search_sample.json")

    async def main() -> None:
        transport = _make_transport(search_json=data)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            req = ConnectorRequest(topics=["RAG", "agents"], max_items=10)
            out = await conn.collect(req)
        assert out.raw_count == len(data["items"])
        assert len(out.items) == out.raw_count
        assert all(i.source is SourceKind.GITHUB for i in out.items)
        assert any(w.code == "incomplete_results" for w in out.warnings)
        first = out.items[0]
        assert first.source_id == "9001"
        assert first.title == "demo-org/awesome-agents"
        assert first.url == "https://github.com/demo-org/awesome-agents"
        assert first.author == "demo-org"
        assert first.stars_or_views == 1280
        assert first.language == "Python"
        assert first.published_at == datetime(2026, 5, 1, 8, 30, 0, tzinfo=UTC)
        assert "agents" in first.tags or "llm" in first.tags
        assert first.content_confidence is ConfidenceLevel.MEDIUM
        second = out.items[1]
        assert second.raw_snippet is None
        assert second.content_confidence is ConfidenceLevel.LOW
        assert second.metadata_completeness <= 0.65

    asyncio.run(main())


def test_collect_skips_repo_missing_required_without_failing_whole_batch() -> None:
    sparse = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "id": 1,
                "full_name": "a/ok",
                "html_url": "https://github.com/a/ok",
                "description": "ok",
                "pushed_at": "2026-05-01T00:00:00Z",
            },
            {"description": "missing id"},
        ],
    }

    async def main() -> None:
        transport = _make_transport(search_json=sparse)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=10))

        assert out.raw_count == 2
        assert len(out.items) == 1
        assert out.items[0].source_id == "1"
        assert any(w.code == "skipped_malformed_repo" for w in out.warnings)

    asyncio.run(main())


def test_collect_adds_readme_excerpt_when_available() -> None:
    data = _load_fixture("github_search_sample.json")
    readme_by = {
        "demo-org/awesome-agents": "# Awesome\n\nFirst paragraph of README body here.",
    }

    async def main() -> None:
        transport = _make_transport(search_json=data, readme_by_repo=readme_by)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        first = out.items[0]
        assert first.raw_snippet is not None
        assert "Curated list" in first.raw_snippet
        assert "README" in first.raw_snippet or "First paragraph" in first.raw_snippet

    asyncio.run(main())


def test_collect_rate_limited_emits_warning() -> None:

    async def main() -> None:
        transport = _make_transport(
            search_json={"message": "API rate limit exceeded"},
            search_status=429,
            search_headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1710000000",
            },
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert out.items == []
        assert out.raw_count == 0
        assert any(w.code == "rate_limited" for w in out.warnings)

    asyncio.run(main())


def test_collect_search_http_error_emits_warning() -> None:

    async def main() -> None:
        transport = _make_transport(
            search_json={"message": "Server Error"},
            search_status=503,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(ConnectorRequest(topics=["AI"], max_items=5))

        assert out.items == []
        assert any(w.code == "search_failed" for w in out.warnings)

    asyncio.run(main())


def test_collect_returns_empty_when_no_input() -> None:

    async def main() -> None:
        transport = _make_transport(search_json={"items": []})
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            conn = GitHubConnector(token=None, client=client)
            out = await conn.collect(
                ConnectorRequest(topics=[], max_items=5),
            )
        assert out.items == []
        assert out.raw_count == 0
        assert any(w.code == "no_input" for w in out.warnings)

    asyncio.run(main())


def test_collect_manual_repo_url() -> None:
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

    def handler(request: httpx.Request) -> httpx.Response:
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

    asyncio.run(main())


def test_collect_owner_repos_channel() -> None:
    repos = [
        {
            "id": 1,
            "full_name": "acme/a",
            "html_url": "https://github.com/acme/a",
            "description": "a",
            "pushed_at": "2026-05-02T00:00:00Z",
            "stargazers_count": 1,
            "owner": {"login": "acme"},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/acme/repos":
            return httpx.Response(200, json=repos)
        if request.url.path.endswith("/readme"):
            return httpx.Response(404)
        return httpx.Response(404)

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
                    github_target_channels=["acme"],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert out.items[0].source_id == "1"

    asyncio.run(main())


def test_parse_github_repo_ref() -> None:
    from ai_news_agent.connectors.github import parse_github_repo_ref

    assert parse_github_repo_ref("https://github.com/o/r") == ("o", "r")
    assert parse_github_repo_ref("o/r") == ("o", "r")


def test_github_connector_name() -> None:

    async def main() -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            assert GitHubConnector(client=client).name() == "github"

    asyncio.run(main())
