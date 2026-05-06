"""Contract tests for async source connectors and fixture payloads (Task 3)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.connectors.base import (
    ConnectorRequest,
    ConnectorResult,
    SourceConnector,
)
from ai_news_agent.models import (
    ConfidenceLevel,
    ConnectorWarning,
    NewsItem,
    SourceKind,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_json(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def map_github_fixture_to_news_items(data: dict) -> tuple[list[NewsItem], list[ConnectorWarning], int]:
    """Minimal mapping from GitHub search-like JSON to domain models (T5 will own full logic)."""
    warnings: list[ConnectorWarning] = []
    items: list[NewsItem] = []
    raw_items = data.get("items") or []
    collected = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    for row in raw_items:
        repo_id = str(row["id"])
        full_name = row["full_name"]
        url = row["html_url"]
        title = full_name
        desc = row.get("description")
        stars = row.get("stargazers_count")
        owner = (row.get("owner") or {}).get("login")
        pushed = row.get("pushed_at")
        published_at = datetime.fromisoformat(pushed.replace("Z", "+00:00")) if pushed else None
        completeness = 0.9 if desc else 0.4
        items.append(
            NewsItem(
                source=SourceKind.GITHUB,
                source_id=repo_id,
                url=url,
                title=title,
                published_at=published_at,
                collected_at=collected,
                author=owner,
                stars_or_views=int(stars) if stars is not None else None,
                language=row.get("language"),
                metadata_completeness=completeness,
                raw_snippet=desc,
                tags=["github", "repository"],
                topic_matches=[],
                content_confidence=ConfidenceLevel.MEDIUM if desc else ConfidenceLevel.LOW,
            )
        )
    if data.get("incomplete_results"):
        warnings.append(
            ConnectorWarning(
                connector="github",
                code="incomplete_results",
                message="GitHub search returned incomplete_results=true",
            )
        )
    return items, warnings, len(raw_items)


def map_bilibili_fixture_to_news_items(data: dict) -> tuple[list[NewsItem], list[ConnectorWarning], int]:
    """Minimal mapping from Bilibili-like JSON to domain models (T6 will own full logic)."""
    warnings: list[ConnectorWarning] = []
    items: list[NewsItem] = []
    raw_items = data.get("data", {}).get("result") or []
    collected = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    for row in raw_items:
        bvid = row["bvid"]
        title = row["title"]
        url = f"https://www.bilibili.com/video/{bvid}"
        author = row.get("author")
        views = row.get("play")
        desc = row.get("description")
        completeness = 0.5 if desc else 0.25
        items.append(
            NewsItem(
                source=SourceKind.BILIBILI,
                source_id=bvid,
                url=url,
                title=title,
                published_at=None,
                collected_at=collected,
                author=author,
                stars_or_views=int(views) if views is not None else None,
                language=None,
                metadata_completeness=completeness,
                raw_snippet=desc,
                tags=["bilibili", "video"],
                topic_matches=[],
                content_confidence=ConfidenceLevel.LOW,
            )
        )
    if data.get("data", {}).get("note"):
        warnings.append(
            ConnectorWarning(
                connector="bilibili",
                code="metadata_limited",
                message=str(data["data"]["note"]),
            )
        )
    return items, warnings, len(raw_items)


class _FakeConnector:
    def name(self) -> str:
        return "fake"

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        assert request.topics
        return ConnectorResult(
            items=[
                NewsItem(
                    source=SourceKind.GITHUB,
                    source_id="1",
                    url="https://example.com",
                    title="t",
                    collected_at=datetime(2026, 5, 6, tzinfo=UTC),
                )
            ],
            warnings=[],
            raw_count=1,
        )


def test_source_connector_protocol_with_fake() -> None:
    async def main() -> None:
        c: SourceConnector = _FakeConnector()
        assert isinstance(c, SourceConnector)
        assert c.name() == "fake"
        req = ConnectorRequest(topics=["RAG"], timeframe="today", max_items=5, language_hint="en")
        out = await c.collect(req)
        assert isinstance(out, ConnectorResult)
        assert len(out.items) == 1
        assert out.items[0].source is SourceKind.GITHUB
        assert out.raw_count == 1

    asyncio.run(main())


def test_connector_result_defaults() -> None:
    r = ConnectorResult()
    assert r.items == []
    assert r.warnings == []
    assert r.raw_count == 0


def test_connector_request_fields() -> None:
    r = ConnectorRequest(topics=["a", "b"], timeframe="last_7_days", max_items=3, language_hint="zh")
    assert r.topics == ["a", "b"]
    assert r.timeframe == "last_7_days"
    assert r.max_items == 3
    assert r.language_hint == "zh"


def test_github_fixture_loads_and_maps() -> None:
    data = _load_json("github_search_sample.json")
    assert "items" in data
    assert data["items"]
    first = data["items"][0]
    assert "id" in first and "full_name" in first and "html_url" in first
    items, warnings, raw_count = map_github_fixture_to_news_items(data)
    assert raw_count == len(data["items"])
    assert len(items) == raw_count
    assert all(i.source is SourceKind.GITHUB for i in items)
    assert any(w.code == "incomplete_results" for w in warnings)


def test_bilibili_fixture_loads_and_maps() -> None:
    data = _load_json("bilibili_search_sample.json")
    assert "data" in data
    assert "result" in data["data"]
    first = data["data"]["result"][0]
    assert "bvid" in first and "title" in first
    items, warnings, raw_count = map_bilibili_fixture_to_news_items(data)
    assert raw_count == len(data["data"]["result"])
    assert len(items) == raw_count
    assert all(i.source is SourceKind.BILIBILI for i in items)
    assert items[0].content_confidence is ConfidenceLevel.LOW
    assert any(w.connector == "bilibili" for w in warnings)
