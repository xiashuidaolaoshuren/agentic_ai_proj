"""Tests for the shared source registry."""

from __future__ import annotations

import pytest

from ai_news_agent.sources import (
    ALLOWED_SOURCES,
    DEFAULT_SOURCE_NAMES,
    build_connector_factory,
    build_connectors,
    normalize_source_names,
    parse_sources_csv,
)


def test_default_source_names_match_allowed_registry() -> None:
    assert set(DEFAULT_SOURCE_NAMES) == set(ALLOWED_SOURCES)


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


def test_build_connector_factory_returns_fresh_connector_per_call() -> None:
    factory = build_connector_factory(fake=True, name="github")

    first = factory()
    second = factory()

    assert first is not second
    assert first.name() == second.name() == "github"


def test_build_connector_factory_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source 'arxiv'"):
        build_connector_factory(fake=True, name="arxiv")
