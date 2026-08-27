"""Tests for HuggingFaceConnector (Milestone 6 T2)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.huggingface import HuggingFaceConnector
from ai_news_agent.models import SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> Any:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass
class FakeHfApi:
    """Test double for huggingface_hub.HfApi."""

    models: list[Any] = field(default_factory=list)
    error: Exception | None = None
    list_models_calls: list[dict[str, Any]] = field(default_factory=list)
    list_datasets_called: bool = False
    list_spaces_called: bool = False

    def list_models(self, **kwargs: Any) -> list[Any]:
        self.list_models_calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return list(self.models)

    def list_datasets(self, **kwargs: Any) -> list[Any]:
        self.list_datasets_called = True
        return []

    def list_spaces(self, **kwargs: Any) -> list[Any]:
        self.list_spaces_called = True
        return []


def _model_info_from_dict(data: dict[str, Any]) -> Any:
    from huggingface_hub.hf_api import ModelInfo

    return ModelInfo(
        id=data.get("id"),
        author=data.get("author"),
        downloads=data.get("downloads"),
        downloads_all_time=data.get("downloads_all_time"),
        likes=data.get("likes"),
        last_modified=data.get("last_modified"),
        pipeline_tag=data.get("pipeline_tag"),
        library_name=data.get("library_name"),
        gated=data.get("gated"),
        tags=data.get("tags"),
        trending_score=data.get("trending_score"),
        card_data=data.get("card_data"),
    )


def test_huggingface_connector_stub_name() -> None:
    conn = HuggingFaceConnector(api=FakeHfApi())
    assert conn.name() == "huggingface"


def test_connector_request_has_huggingface_fields() -> None:
    req = ConnectorRequest(
        topics=["RAG"],
        huggingface_discovery_mode="filtered",
        huggingface_search="RAG",
        huggingface_pipeline_tag="text-generation",
    )
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_search == "RAG"
    assert req.huggingface_pipeline_tag == "text-generation"


def test_collect_global_trending_maps_models_to_news_items() -> None:
    raw = _load_fixture("huggingface_models_sample.json")
    models = [_model_info_from_dict(row) for row in raw]
    api = FakeHfApi(models=models)

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=10,
                huggingface_discovery_mode="global",
            )
        )
        assert out.raw_count == 2
        assert len(out.items) == 2
        assert all(i.source is SourceKind.HUGGINGFACE for i in out.items)
        assert api.list_models_calls == [
            {"sort": "trending_score", "limit": 40, "cardData": True}
        ]
        assert api.list_datasets_called is False
        assert api.list_spaces_called is False

        first = out.items[0]
        assert first.source_id == "meta-llama/Llama-3.1-8B"
        assert first.url == "https://huggingface.co/meta-llama/Llama-3.1-8B"
        assert first.author == "meta-llama"
        assert first.stars_or_views is None
        assert first.published_at == datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
        assert first.source_evidence == {
            "trending_score": 88,
            "downloads_30d": 150000,
            "downloads_all_time": 2500000,
            "likes": 420,
            "pipeline_tag": "text-generation",
            "library_name": "transformers",
            "gated": False,
            "discovery_mode": "global",
        }

        second = out.items[1]
        assert second.source_id == "mistralai/Mistral-7B-v0.1"
        assert second.source_evidence["discovery_mode"] == "global"
        assert second.source_evidence["trending_score"] == 72

    asyncio.run(main())


def test_collect_filtered_search_passes_search_and_records_discovery_mode() -> None:
    raw = _load_fixture("huggingface_models_sample.json")
    models = [_model_info_from_dict(row) for row in raw[:1]]
    api = FakeHfApi(models=models)

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["RAG"],
                max_items=5,
                huggingface_discovery_mode="filtered",
                huggingface_search="RAG",
            )
        )
        assert len(out.items) == 1
        assert out.items[0].source_evidence["discovery_mode"] == "filtered"
        assert api.list_models_calls == [
            {"sort": "trending_score", "limit": 20, "search": "RAG", "cardData": True}
        ]

    asyncio.run(main())


def test_collect_filtered_pipeline_tag_passes_pipeline_tag() -> None:
    raw = _load_fixture("huggingface_models_sample.json")
    models = [_model_info_from_dict(row) for row in raw[:1]]
    api = FakeHfApi(models=models)

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=5,
                huggingface_discovery_mode="filtered",
                huggingface_pipeline_tag="text-generation",
            )
        )
        assert len(out.items) == 1
        assert out.items[0].source_evidence["discovery_mode"] == "filtered"
        assert api.list_models_calls == [
            {
                "sort": "trending_score",
                "limit": 20,
                "pipeline_tag": "text-generation",
                "cardData": True,
            }
        ]

    asyncio.run(main())


def test_collect_maps_card_summary_to_raw_snippet() -> None:
    model = _model_info_from_dict(
        {
            "id": "org/demo-model",
            "author": "org",
            "downloads": 1000,
            "likes": 10,
            "trending_score": 50,
            "pipeline_tag": "text-generation",
            "card_data": SimpleNamespace(
                summary="  A compact instruction-tuned model for demos.  "
            ),
        }
    )
    api = FakeHfApi(models=[model])

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=5,
                huggingface_discovery_mode="global",
            )
        )
        assert len(out.items) == 1
        assert out.items[0].raw_snippet == "A compact instruction-tuned model for demos."

    asyncio.run(main())


def test_collect_skips_malformed_model_missing_id() -> None:
    valid = _model_info_from_dict(_load_fixture("huggingface_models_sample.json")[0])
    malformed = _model_info_from_dict(
        {
            "id": None,
            "author": "broken",
            "downloads": 1,
            "likes": 0,
            "trending_score": 1,
        }
    )
    api = FakeHfApi(models=[valid, malformed])

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=10,
                huggingface_discovery_mode="global",
            )
        )
        assert out.raw_count == 2
        assert len(out.items) == 1
        assert out.items[0].source_id == "meta-llama/Llama-3.1-8B"
        assert any(w.code == "skipped_malformed_model" for w in out.warnings)

    asyncio.run(main())


def test_collect_missing_trend_evidence_keeps_item_with_warning() -> None:
    model = _model_info_from_dict(
        {
            "id": "org/no-trend",
            "author": "org",
            "downloads": 10,
            "likes": 1,
            "trending_score": None,
            "pipeline_tag": "text-generation",
        }
    )
    api = FakeHfApi(models=[model])

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=5,
                huggingface_discovery_mode="global",
            )
        )
        assert len(out.items) == 1
        assert out.items[0].source_id == "org/no-trend"
        assert out.items[0].source_evidence["trending_score"] is None
        assert any(w.code == "missing_trend_evidence" for w in out.warnings)

    asyncio.run(main())


def test_collect_request_failure_emits_warning_and_empty_items() -> None:
    api = FakeHfApi(error=RuntimeError("hub unavailable"))

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=5,
                huggingface_discovery_mode="global",
            )
        )
        assert out.items == []
        assert out.raw_count == 0
        assert any(w.code == "request_failed" for w in out.warnings)

    asyncio.run(main())


def test_collect_rate_limited_emits_warning() -> None:
    api = FakeHfApi(error=Exception("429 rate limit exceeded"))

    async def main() -> None:
        conn = HuggingFaceConnector(api=api)
        out = await conn.collect(
            ConnectorRequest(
                topics=["model releases"],
                max_items=5,
                huggingface_discovery_mode="global",
            )
        )
        assert out.items == []
        assert any(w.code == "rate_limited" for w in out.warnings)

    asyncio.run(main())
