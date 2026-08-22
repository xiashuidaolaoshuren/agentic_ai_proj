"""Tests for Milestone 2 connector tool wrappers (Task T3)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind
from ai_news_agent.tools.connectors import (
    search_bilibili_ai_news,
    search_github_ai_news,
    search_huggingface_trending_models,
    search_juya_ai_news,
    search_zhihu_practitioner_insights,
)
from ai_news_agent.tools.schemas import HuggingFaceSearchArgs, SearchQueryInput, ToolObservationStatus, ZhihuSearchArgs


class _FakeConnector:
    def __init__(
        self,
        *,
        name: str,
        items: list[NewsItem] | None = None,
        warnings: list[ConnectorWarning] | None = None,
        raw_count: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self._name = name
        self._items = list(items or [])
        self._warnings = list(warnings or [])
        self._raw_count = raw_count if raw_count is not None else len(self._items)
        self._error = error
        self.calls = 0
        self.last_request: ConnectorRequest | None = None

    def name(self) -> str:
        return self._name

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        self.calls += 1
        self.last_request = request
        if self._error is not None:
            raise self._error
        return ConnectorResult(
            items=list(self._items),
            warnings=list(self._warnings),
            raw_count=self._raw_count,
        )


def _sample_item(*, source: SourceKind, source_id: str, title: str) -> NewsItem:
    return NewsItem(
        source=source,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        title=title,
        collected_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        author="alice",
        stars_or_views=42,
        language="en",
        metadata_completeness=0.8,
        raw_snippet="snippet",
        tags=["ai"],
        topic_matches=["AI agents"],
        content_confidence=ConfidenceLevel.HIGH,
    )


def test_search_juya_ai_news_ok_serializes_items() -> None:
    item = _sample_item(source=SourceKind.JUYA, source_id="juya-1", title="Juya Bulletin")
    connector = _FakeConnector(name="juya", items=[item], raw_count=2)

    obs = asyncio.run(
        search_juya_ai_news(
            connector=connector,
            search=SearchQueryInput(query="AI agents", max_results=5),
            timeframe="today",
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["connector"] == "juya"
    assert obs.data["query"] == "AI agents"
    assert obs.data["item_count"] == 1
    assert obs.data["raw_count"] == 2
    assert obs.data["items"][0]["source"] == "juya"
    assert obs.data["items"][0] == item.model_dump(mode="json")
    json.dumps(obs.model_dump(mode="json"))


def test_search_github_ai_news_ok_serializes_items() -> None:
    item = _sample_item(source=SourceKind.GITHUB, source_id="repo-1", title="Repo One")
    connector = _FakeConnector(name="github", items=[item], raw_count=3)

    obs = asyncio.run(
        search_github_ai_news(
            connector=connector,
            search=SearchQueryInput(query="AI agents", max_results=4),
            timeframe="last_7_days",
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["connector"] == "github"
    assert obs.data["query"] == "AI agents"
    assert obs.data["item_count"] == 1
    assert obs.data["raw_count"] == 3
    assert obs.data["items"][0]["source_id"] == "repo-1"
    assert obs.data["items"][0]["url"] == "https://example.com/repo-1"
    assert obs.data["items"][0] == item.model_dump(mode="json")
    json.dumps(obs.model_dump(mode="json"))


def test_search_github_ai_news_delegates_connector_request() -> None:
    connector = _FakeConnector(name="github")

    asyncio.run(
        search_github_ai_news(
            connector=connector,
            search=SearchQueryInput(query="RAG", max_results=2),
            timeframe="today",
        )
    )

    assert connector.calls == 1
    assert connector.last_request is not None
    assert connector.last_request.topics == ["RAG"]
    assert connector.last_request.max_items == 2
    assert connector.last_request.timeframe == "today"


def test_search_bilibili_ai_news_ok_serializes_items() -> None:
    item = _sample_item(source=SourceKind.BILIBILI, source_id="BV1", title="Video One")
    connector = _FakeConnector(name="bilibili", items=[item])

    obs = asyncio.run(
        search_bilibili_ai_news(
            connector=connector,
            search=SearchQueryInput(query="multimodal AI"),
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["connector"] == "bilibili"
    assert obs.data["query"] == "multimodal AI"
    assert obs.data["item_count"] == 1
    assert obs.data["items"][0]["source"] == "bilibili"
    assert obs.data["items"][0] == item.model_dump(mode="json")
    json.dumps(obs.model_dump(mode="json"))


def test_search_bilibili_ai_news_delegates_connector_request() -> None:
    connector = _FakeConnector(name="bilibili")

    asyncio.run(
        search_bilibili_ai_news(
            connector=connector,
            search=SearchQueryInput(query="model releases", max_results=3),
        )
    )

    assert connector.calls == 1
    assert connector.last_request is not None
    assert connector.last_request.topics == ["model releases"]
    assert connector.last_request.max_items == 3


def test_search_github_ai_news_includes_warnings_in_data_and_caveats() -> None:
    item = _sample_item(source=SourceKind.GITHUB, source_id="repo-1", title="Repo One")
    warning = ConnectorWarning(connector="github", code="rate_limited", message="Slow down")
    connector = _FakeConnector(name="github", items=[item], warnings=[warning])

    obs = asyncio.run(
        search_github_ai_news(
            connector=connector,
            search=SearchQueryInput(query="AI agents"),
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["warnings"][0]["code"] == "rate_limited"
    assert obs.data["warnings"][0] == warning.model_dump(mode="json")
    assert any("github:rate_limited" in caveat for caveat in obs.caveats)
    json.dumps(obs.model_dump(mode="json"))


def test_search_bilibili_ai_news_empty_items_with_warning() -> None:
    warning = ConnectorWarning(connector="bilibili", code="no_input", message="Nothing to search")
    connector = _FakeConnector(name="bilibili", items=[], warnings=[warning])

    obs = asyncio.run(
        search_bilibili_ai_news(
            connector=connector,
            search=SearchQueryInput(query="RAG"),
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["item_count"] == 0
    assert obs.data["warnings"][0]["code"] == "no_input"
    assert any("bilibili:no_input" in caveat for caveat in obs.caveats)


def test_search_github_ai_news_connector_raises_becomes_error_caveat() -> None:
    connector = _FakeConnector(name="github", error=RuntimeError("boom"))

    obs = asyncio.run(
        search_github_ai_news(
            connector=connector,
            search=SearchQueryInput(query="AI agents"),
        )
    )

    assert obs.status is ToolObservationStatus.ERROR
    assert obs.data["connector"] == "github"
    assert obs.data["query"] == "AI agents"
    assert any("boom" in caveat for caveat in obs.caveats)


def test_search_bilibili_ai_news_connector_raises_becomes_error_caveat() -> None:
    connector = _FakeConnector(name="bilibili", error=RuntimeError("network down"))

    obs = asyncio.run(
        search_bilibili_ai_news(
            connector=connector,
            search=SearchQueryInput(query="multimodal AI"),
        )
    )

    assert obs.status is ToolObservationStatus.ERROR
    assert obs.data["connector"] == "bilibili"
    assert any("network down" in caveat for caveat in obs.caveats)


def test_search_huggingface_trending_models_maps_filtered_discovery_fields() -> None:
    connector = _FakeConnector(name="huggingface")

    asyncio.run(
        search_huggingface_trending_models(
            connector=connector,
            args=HuggingFaceSearchArgs(
                discovery_mode="filtered",
                search="RAG",
                pipeline_tag="text-generation",
                max_results=3,
            ),
        )
    )

    assert connector.calls == 1
    assert connector.last_request is not None
    assert connector.last_request.huggingface_discovery_mode == "filtered"
    assert connector.last_request.huggingface_search == "RAG"
    assert connector.last_request.huggingface_pipeline_tag == "text-generation"
    assert connector.last_request.max_items == 3


def test_search_huggingface_trending_models_ok_is_json_safe() -> None:
    item = _sample_item(
        source=SourceKind.HUGGINGFACE,
        source_id="org/model",
        title="Trending Model",
    )
    connector = _FakeConnector(name="huggingface", items=[item], raw_count=4)

    obs = asyncio.run(
        search_huggingface_trending_models(
            connector=connector,
            args=HuggingFaceSearchArgs(
                discovery_mode="filtered",
                search="agents",
                pipeline_tag="text-generation",
                max_results=5,
            ),
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["connector"] == "huggingface"
    assert obs.data["item_count"] == 1
    assert obs.data["raw_count"] == 4
    assert obs.data["items"][0] == item.model_dump(mode="json")
    json.dumps(obs.model_dump(mode="json"))


def test_search_huggingface_trending_models_connector_raises_becomes_error() -> None:
    connector = _FakeConnector(name="huggingface", error=RuntimeError("hf down"))

    obs = asyncio.run(
        search_huggingface_trending_models(
            connector=connector,
            args=HuggingFaceSearchArgs(discovery_mode="filtered", search="RAG"),
        )
    )

    assert obs.status is ToolObservationStatus.ERROR
    assert obs.data["connector"] == "huggingface"
    assert any("hf down" in caveat for caveat in obs.caveats)


def test_search_zhihu_practitioner_insights_sets_raw_topics_and_max_items() -> None:
    connector = _FakeConnector(name="zhihu")

    asyncio.run(
        search_zhihu_practitioner_insights(
            connector=connector,
            args=ZhihuSearchArgs(topics=["RAG"], max_results=4),
        )
    )

    assert connector.calls == 1
    assert connector.last_request is not None
    assert connector.last_request.topics == ["RAG"]
    assert connector.last_request.max_items == 4
    assert connector.last_request.timeframe is None
    assert connector.last_request.huggingface_discovery_mode is None
    assert connector.last_request.huggingface_search is None
    assert connector.last_request.huggingface_pipeline_tag is None


def test_search_zhihu_practitioner_insights_ok_is_json_safe() -> None:
    item = _sample_item(source=SourceKind.ZHIHU, source_id="zh-1", title="RAG in production")
    connector = _FakeConnector(name="zhihu", items=[item], raw_count=2)

    obs = asyncio.run(
        search_zhihu_practitioner_insights(
            connector=connector,
            args=ZhihuSearchArgs(topics=["RAG"], max_results=5),
        )
    )

    assert obs.status is ToolObservationStatus.OK
    assert obs.data["connector"] == "zhihu"
    assert obs.data["item_count"] == 1
    assert obs.data["raw_count"] == 2
    assert obs.data["items"][0] == item.model_dump(mode="json")
    json.dumps(obs.model_dump(mode="json"))


def test_search_zhihu_practitioner_insights_connector_raises_becomes_error() -> None:
    connector = _FakeConnector(name="zhihu", error=RuntimeError("zhihu down"))

    obs = asyncio.run(
        search_zhihu_practitioner_insights(
            connector=connector,
            args=ZhihuSearchArgs(topics=["RAG"]),
        )
    )

    assert obs.status is ToolObservationStatus.ERROR
    assert obs.data["connector"] == "zhihu"
    assert any("zhihu down" in caveat for caveat in obs.caveats)
