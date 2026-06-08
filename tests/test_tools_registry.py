"""Tests for Milestone 2 tool registry and connector lifecycle (Task T4)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.registry import ToolDefinition, ToolRegistry, build_tool_registry
from ai_news_agent.tools.schemas import ToolObservation, ToolObservationStatus


def _sample_tool(*, name: str = "sample_tool", description: str = "Sample tool") -> ToolDefinition:
    async def _execute() -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="ok",
        )

    return ToolDefinition(
        name=name,
        description=description,
        args_schema={"type": "object", "properties": {}},
        execute=_execute,
    )


def test_tool_registry_get_tool_returns_known_tool() -> None:
    tool = _sample_tool(name="known_tool")
    registry = ToolRegistry([tool])

    assert registry.get_tool("known_tool") is tool


def test_tool_registry_get_tool_raises_key_error_for_unknown() -> None:
    registry = ToolRegistry([_sample_tool(name="known_tool")])

    with pytest.raises(KeyError, match="unknown_tool"):
        registry.get_tool("unknown_tool")


def test_tool_registry_raises_value_error_on_duplicate_name() -> None:
    first = _sample_tool(name="duplicate")
    second = _sample_tool(name="duplicate")

    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([first, second])


EXPECTED_TOOL_NAMES: tuple[str, ...] = (
    "load_latest_digest",
    "get_digest_item",
    "get_source_trace",
    "get_ranking_explanation",
    "search_github_ai_news",
    "search_bilibili_ai_news",
)


def _build_registry_for_tests(tmp_path: Path) -> ToolRegistry:
    store = DigestStore(tmp_path / "registry.db")
    store.init_schema()

    def _github_factory() -> Any:
        raise AssertionError("github factory should not run in this test")

    def _bilibili_factory() -> Any:
        raise AssertionError("bilibili factory should not run in this test")

    return build_tool_registry(
        store=store,
        github_factory=_github_factory,
        bilibili_factory=_bilibili_factory,
    )


def test_build_tool_registry_exposes_six_stable_tool_names(tmp_path: Path) -> None:
    registry = _build_registry_for_tests(tmp_path)

    assert registry.tool_names() == list(EXPECTED_TOOL_NAMES)


def test_build_tool_registry_tools_have_non_empty_descriptions(tmp_path: Path) -> None:
    registry = _build_registry_for_tests(tmp_path)

    for tool in registry.all_tools():
        assert tool.description.strip()


def test_build_tool_registry_load_latest_digest_execute_uses_injected_store(
    tmp_path: Path,
) -> None:
    store = DigestStore(tmp_path / "followup-empty.db")
    store.init_schema()
    registry = build_tool_registry(
        store=store,
        github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        bilibili_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
    )

    tool = registry.get_tool("load_latest_digest")
    observation = asyncio.run(tool.execute())

    assert observation.status is ToolObservationStatus.EMPTY
    assert "no saved digest" in observation.summary.lower()


class _CountingConnectorFactory:
    def __init__(self, *, name: str) -> None:
        self.name = name
        self.calls = 0

    def __call__(self) -> _CountingConnector:
        self.calls += 1
        return _CountingConnector(name=self.name)


class _CountingConnector:
    def __init__(self, *, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    async def collect(self, request: Any) -> Any:
        from ai_news_agent.connectors.base import ConnectorResult

        return ConnectorResult(items=[], warnings=[], raw_count=0)


def test_build_tool_registry_connector_execute_calls_factory_per_invocation(
    tmp_path: Path,
) -> None:
    store = DigestStore(tmp_path / "connector-factory.db")
    store.init_schema()
    github_factory = _CountingConnectorFactory(name="github")
    registry = build_tool_registry(
        store=store,
        github_factory=github_factory,
        bilibili_factory=_CountingConnectorFactory(name="bilibili"),
    )

    tool = registry.get_tool("search_github_ai_news")
    asyncio.run(tool.execute(query="AI agents"))
    asyncio.run(tool.execute(query="RAG"))

    assert github_factory.calls == 2


def test_build_tool_registry_import_from_tools_package(tmp_path: Path) -> None:
    from ai_news_agent.tools import build_tool_registry as package_build_tool_registry

    store = DigestStore(tmp_path / "package-import.db")
    store.init_schema()
    registry = package_build_tool_registry(
        store=store,
        github_factory=_CountingConnectorFactory(name="github"),
        bilibili_factory=_CountingConnectorFactory(name="bilibili"),
    )

    assert registry.tool_names() == list(EXPECTED_TOOL_NAMES)
