"""Tests for the shared source registry."""

from __future__ import annotations

import asyncio

import pytest

from ai_news_agent.models import SourceKind
from ai_news_agent.connectors.huggingface import HuggingFaceConnector
from ai_news_agent.connectors.juya import JuyaConnector
from ai_news_agent.connectors.zhihu import ZhihuConnector
from ai_news_agent.sources import (
    ALLOWED_SOURCES,
    DEFAULT_SOURCE_NAMES,
    FakeHuggingFaceConnector,
    FakeJuyaConnector,
    FakeZhihuConnector,
    build_connector_factory,
    build_connectors,
    normalize_source_names,
    parse_sources_csv,
    resolve_connector_names,
)


def test_default_sources_are_juya_only() -> None:
    assert DEFAULT_SOURCE_NAMES == ("juya",)
    assert "juya" in ALLOWED_SOURCES
    assert set(DEFAULT_SOURCE_NAMES) <= ALLOWED_SOURCES


def test_allowed_sources_include_huggingface_and_zhihu() -> None:
    assert "huggingface" in ALLOWED_SOURCES
    assert "zhihu" in ALLOWED_SOURCES
    assert DEFAULT_SOURCE_NAMES == ("juya",)
    assert normalize_source_names(["huggingface", "zhihu"]) == ["huggingface", "zhihu"]


def test_normalize_source_names_rejects_arxiv_only() -> None:
    with pytest.raises(ValueError, match="Unknown source 'arxiv'"):
        normalize_source_names(["arxiv"])


def test_fake_juya_connector() -> None:
    connector = FakeJuyaConnector()
    assert connector.name() == "juya"

    async def _collect() -> None:
        result = await connector.collect(None)  # noqa: ARG002
        assert len(result.items) == 1
        assert result.items[0].source is SourceKind.JUYA

    asyncio.run(_collect())


def test_fake_huggingface_connector() -> None:
    connector = FakeHuggingFaceConnector()
    assert connector.name() == "huggingface"

    async def _collect() -> None:
        result = await connector.collect(None)  # noqa: ARG002
        assert len(result.items) == 1
        assert result.items[0].source is SourceKind.HUGGINGFACE

    asyncio.run(_collect())


def test_fake_zhihu_connector() -> None:
    connector = FakeZhihuConnector()
    assert connector.name() == "zhihu"

    async def _collect() -> None:
        result = await connector.collect(None)  # noqa: ARG002
        assert len(result.items) == 1
        assert result.items[0].source is SourceKind.ZHIHU

    asyncio.run(_collect())


def test_build_connectors_includes_juya() -> None:
    fake_connectors = build_connectors(fake=True, names=["juya"])
    assert fake_connectors[0].name() == "juya"

    real_connectors = build_connectors(fake=False, names=["juya"])
    assert isinstance(real_connectors[0], JuyaConnector)


def test_build_connectors_includes_huggingface_and_zhihu() -> None:
    fake_connectors = build_connectors(fake=True, names=["huggingface", "zhihu"])
    assert [c.name() for c in fake_connectors] == ["huggingface", "zhihu"]

    real_connectors = build_connectors(fake=False, names=["huggingface", "zhihu"])
    assert isinstance(real_connectors[0], HuggingFaceConnector)
    assert isinstance(real_connectors[1], ZhihuConnector)


def test_resolve_connector_names() -> None:
    assert resolve_connector_names(None) == ["juya"]
    assert resolve_connector_names(["github", "bilibili"]) == ["github", "bilibili"]


def test_parse_sources_csv_normalizes_case_and_whitespace() -> None:
    assert parse_sources_csv(" GitHub , bilibili ") == ["github", "bilibili"]


def test_normalize_source_names_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown source 'arxiv'"):
        normalize_source_names(["github", "arxiv"])


def test_normalize_source_names_requires_at_least_one() -> None:
    with pytest.raises(ValueError, match="At least one source"):
        normalize_source_names([])


def test_build_connectors_returns_requested_order() -> None:
    connectors = build_connectors(fake=True, names=["bilibili", "github"])
    assert [c.name() for c in connectors] == ["bilibili", "github"]


def test_build_connector_factory_returns_callable() -> None:
    factory = build_connector_factory(fake=True, name="github")

    assert callable(factory)
    connector = factory()
    assert connector.name() == "github"


def test_build_connector_factory_huggingface_and_zhihu() -> None:
    hf_factory = build_connector_factory(fake=True, name="huggingface")
    zhihu_factory = build_connector_factory(fake=True, name="zhihu")

    assert hf_factory().name() == "huggingface"
    assert zhihu_factory().name() == "zhihu"


def test_build_connector_factory_returns_fresh_connector_per_call() -> None:
    factory = build_connector_factory(fake=True, name="github")

    first = factory()
    second = factory()

    assert first is not second
    assert first.name() == second.name() == "github"


def test_build_connector_factory_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source 'arxiv'"):
        build_connector_factory(fake=True, name="arxiv")
