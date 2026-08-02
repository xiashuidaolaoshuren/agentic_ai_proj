"""Tests for Milestone 2 tool registry and connector lifecycle (Task T4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import BaseTool, tool

from pydantic import ValidationError

from ai_news_agent.storage import DigestStore
from ai_news_agent.tools.registry import ToolRegistry, build_tool_registry
from ai_news_agent.tools.schemas import (
    DigestItemRankArgs,
    InterfaceAgentResult,
    InterfaceAgentResultKind,
    RankOrSourceArgs,
    SearchArgs,
    ToolObservation,
    ToolObservationStatus,
)
from test_tools_followup import _seed_full_followup_store


def _sample_tool(*, name: str = "sample_tool", description: str = "Sample tool") -> BaseTool:
    async def stub() -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="ok",
        )

    stub.__name__ = name
    stub.__doc__ = description
    return tool(stub)


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

CAPABILITY_TOOL_NAMES: tuple[str, ...] = (
    "generate_ai_news_digest",
    "list_digest_sources",
    "recommend_digest_item",
    "list_digest_caveats",
    "get_digest_item_by_rank",
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


def _build_capability_registry_for_tests(tmp_path: Path) -> ToolRegistry:
    from ai_news_agent.request import DigestRequest

    store = DigestStore(tmp_path / "capability-registry.db")
    store.init_schema()
    return build_tool_registry(
        store=store,
        github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        bilibili_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        digest_request=DigestRequest(topics=["AI"]),
        connectors=[],
        model=object(),
    )


def test_build_tool_registry_with_capability_deps_exposes_eleven_tools(
    tmp_path: Path,
) -> None:
    registry = _build_capability_registry_for_tests(tmp_path)

    assert len(registry.tool_names()) == 11
    for name in CAPABILITY_TOOL_NAMES:
        assert name in registry.tool_names()


def test_generate_ai_news_digest_invokes_run_digest_once(tmp_path: Path) -> None:
    from ai_news_agent.graph.state import DigestResult
    from ai_news_agent.models import Digest
    from ai_news_agent.request import DigestRequest
    from ai_news_agent.tools.schemas import InterfaceAgentResult

    store = DigestStore(tmp_path / "digest-tool.db")
    store.init_schema()
    trusted_request = DigestRequest(topics=["AI agents"])
    digest = Digest(
        generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
        entries=[],
        topics=["AI agents"],
    )
    digest_result = DigestResult(
        request=trusted_request,
        digest=digest,
        run_id=7,
        markdown="# Digest",
        text="Digest text",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    run_digest_mock = AsyncMock(return_value=digest_result)
    model = object()

    with patch("ai_news_agent.tools.registry.run_digest", run_digest_mock):
        registry = build_tool_registry(
            store=store,
            github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
            bilibili_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
            digest_request=trusted_request,
            connectors=[],
            model=model,
        )
        tool = registry.get_tool("generate_ai_news_digest")
        result = asyncio.run(tool.ainvoke({}))

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.run_id == 7
    assert result.text == "Digest text"
    assert result.digest == digest
    run_digest_mock.assert_awaited_once_with(
        trusted_request,
        connectors=[],
        model=model,
        store=store,
        now_provider=None,
    )


def test_generate_ai_news_digest_has_no_args_schema(tmp_path: Path) -> None:
    from ai_news_agent.graph.state import DigestResult
    from ai_news_agent.models import Digest
    from ai_news_agent.request import DigestRequest

    store = DigestStore(tmp_path / "digest-noargs.db")
    store.init_schema()
    trusted_request = DigestRequest(topics=["AI agents"])
    digest_result = DigestResult(
        request=trusted_request,
        digest=Digest(
            generated_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC),
            entries=[],
            topics=["AI agents"],
        ),
        run_id=1,
        markdown="",
        text="ok",
        ranked_items=[],
        warnings=[],
        errors=[],
        started_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC),
    )
    run_digest_mock = AsyncMock(return_value=digest_result)

    with patch("ai_news_agent.tools.registry.run_digest", run_digest_mock):
        registry = build_tool_registry(
            store=store,
            github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
            bilibili_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
            digest_request=trusted_request,
            connectors=[],
            model=object(),
        )
        tool = registry.get_tool("generate_ai_news_digest")
        assert tool.args_schema is not None
        assert tool.args_schema.model_fields == {}

        asyncio.run(tool.ainvoke({"topics": ["x"]}))

    run_digest_mock.assert_awaited_once_with(
        trusted_request,
        connectors=[],
        model=run_digest_mock.await_args.kwargs["model"],
        store=store,
        now_provider=None,
    )


def _build_seeded_capability_registry(tmp_path: Path) -> tuple[ToolRegistry, DigestStore, int]:
    from ai_news_agent.request import DigestRequest

    store, run_id = _seed_full_followup_store(tmp_path)
    registry = build_tool_registry(
        store=store,
        github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        bilibili_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        digest_request=DigestRequest(topics=["RAG"]),
        connectors=[],
        model=object(),
    )
    return registry, store, run_id


def test_list_digest_sources_returns_exact_formatter_text(tmp_path: Path) -> None:
    from ai_news_agent.followup_structured import format_sources

    registry, store, run_id = _build_seeded_capability_registry(tmp_path)
    ctx = store.get_latest_followup_context()
    result = asyncio.run(registry.get_tool("list_digest_sources").ainvoke({}))

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == format_sources(ctx)
    assert result.run_id == run_id


def test_recommend_digest_item_returns_exact_formatter_text(tmp_path: Path) -> None:
    from ai_news_agent.followup_structured import format_ranking_pick

    registry, store, run_id = _build_seeded_capability_registry(tmp_path)
    ctx = store.get_latest_followup_context()
    result = asyncio.run(registry.get_tool("recommend_digest_item").ainvoke({}))

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == format_ranking_pick(ctx)
    assert result.run_id == run_id


def test_list_digest_caveats_returns_exact_formatter_text(tmp_path: Path) -> None:
    from ai_news_agent.followup_structured import format_caveats

    registry, store, run_id = _build_seeded_capability_registry(tmp_path)
    ctx = store.get_latest_followup_context()
    result = asyncio.run(registry.get_tool("list_digest_caveats").ainvoke({}))

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == format_caveats(ctx)
    assert result.run_id == run_id


def test_get_digest_item_by_rank_uses_digest_item_rank_args(tmp_path: Path) -> None:
    registry, _store, _run_id = _build_seeded_capability_registry(tmp_path)
    tool = registry.get_tool("get_digest_item_by_rank")

    assert tool.args_schema is DigestItemRankArgs

    with pytest.raises(ValidationError):
        DigestItemRankArgs(rank=0)


def test_get_digest_item_by_rank_returns_exact_formatter_text(tmp_path: Path) -> None:
    from ai_news_agent.followup_structured import format_rank_item

    registry, store, run_id = _build_seeded_capability_registry(tmp_path)
    ctx = store.get_latest_followup_context()
    result = asyncio.run(registry.get_tool("get_digest_item_by_rank").ainvoke({"rank": 1}))

    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == format_rank_item(ctx, 1)
    assert result.run_id == run_id


def test_structured_tools_return_no_saved_digest_when_empty(tmp_path: Path) -> None:
    from ai_news_agent.followup_structured import NO_SAVED_DIGEST

    registry = _build_capability_registry_for_tests(tmp_path)
    for name in (
        "list_digest_sources",
        "recommend_digest_item",
        "list_digest_caveats",
        "get_digest_item_by_rank",
    ):
        tool = registry.get_tool(name)
        payload = {"rank": 1} if name == "get_digest_item_by_rank" else {}
        result = asyncio.run(tool.ainvoke(payload))

        assert isinstance(result, InterfaceAgentResult)
        assert result.kind == InterfaceAgentResultKind.STRUCTURED
        assert result.text == NO_SAVED_DIGEST
        assert result.run_id is None


def test_build_tool_registry_exposes_six_stable_tool_names(tmp_path: Path) -> None:
    registry = _build_registry_for_tests(tmp_path)

    assert registry.tool_names() == list(EXPECTED_TOOL_NAMES)
    for tool in registry.all_tools():
        assert isinstance(tool, BaseTool)


def test_build_tool_registry_tools_have_non_empty_descriptions(tmp_path: Path) -> None:
    registry = _build_registry_for_tests(tmp_path)

    for tool in registry.all_tools():
        assert tool.description.strip()


LOAD_LATEST_DIGEST_DESCRIPTION = (
    "Load the latest saved digest with topics, entries, and warnings."
)


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
    assert isinstance(tool, BaseTool)
    assert tool.name == "load_latest_digest"
    assert tool.description == LOAD_LATEST_DIGEST_DESCRIPTION
    observation = asyncio.run(tool.ainvoke({}))

    assert isinstance(observation, ToolObservation)
    assert observation.status is ToolObservationStatus.EMPTY
    assert "no saved digest" in observation.summary.lower()


def test_build_tool_registry_followup_tools_use_rank_or_source_args_schema(
    tmp_path: Path,
) -> None:
    store = DigestStore(tmp_path / "followup-selectors.db")
    store.init_schema()

    class _NonBilibiliConnector:
        def name(self) -> str:
            return "stub"

    registry = build_tool_registry(
        store=store,
        github_factory=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        bilibili_factory=lambda: _NonBilibiliConnector(),
    )

    for name in ("get_digest_item", "get_source_trace", "get_ranking_explanation"):
        tool = registry.get_tool(name)
        assert isinstance(tool, BaseTool), name
        assert tool.args_schema is RankOrSourceArgs, name

    digest_item_obs = asyncio.run(registry.get_tool("get_digest_item").ainvoke({}))
    assert isinstance(digest_item_obs, ToolObservation)
    assert digest_item_obs.status is ToolObservationStatus.EMPTY

    trace_obs = asyncio.run(registry.get_tool("get_source_trace").ainvoke({}))
    assert isinstance(trace_obs, ToolObservation)
    assert trace_obs.status is ToolObservationStatus.EMPTY

    ranking_obs = asyncio.run(registry.get_tool("get_ranking_explanation").ainvoke({}))
    assert isinstance(ranking_obs, ToolObservation)
    assert ranking_obs.status is ToolObservationStatus.EMPTY


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


def test_build_tool_registry_github_search_uses_search_args_and_factory_per_call(
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
    assert isinstance(tool, BaseTool)
    assert tool.args_schema is SearchArgs

    asyncio.run(tool.ainvoke({"query": "AI agents"}))
    asyncio.run(tool.ainvoke({"query": "RAG"}))

    assert github_factory.calls == 2

    calls_before_invalid = github_factory.calls
    with pytest.raises(ValidationError):
        asyncio.run(tool.ainvoke({"query": "AI agents", "max_results": 0}))
    assert github_factory.calls == calls_before_invalid


def test_build_tool_registry_bilibili_search_uses_search_args_and_factory_per_call(
    tmp_path: Path,
) -> None:
    store = DigestStore(tmp_path / "bilibili-factory.db")
    store.init_schema()
    bilibili_factory = _CountingConnectorFactory(name="bilibili")
    registry = build_tool_registry(
        store=store,
        github_factory=_CountingConnectorFactory(name="github"),
        bilibili_factory=bilibili_factory,
    )

    tool = registry.get_tool("search_bilibili_ai_news")
    assert isinstance(tool, BaseTool)
    assert tool.args_schema is SearchArgs

    asyncio.run(tool.ainvoke({"query": "multimodal AI"}))
    asyncio.run(tool.ainvoke({"query": "RAG"}))

    assert bilibili_factory.calls == 2


def test_registry_module_has_no_legacy_tool_definition_or_handwritten_schemas() -> None:
    import ai_news_agent.tools.registry as registry_module

    assert not hasattr(registry_module, "ToolDefinition")
    assert not hasattr(registry_module, "_EMPTY_OBJECT_SCHEMA")
    assert not hasattr(registry_module, "_RANK_OR_SOURCE_SCHEMA")
    assert not hasattr(registry_module, "_SEARCH_SCHEMA")


def test_tools_package_surface_exports_new_schema_and_not_legacy_helpers() -> None:
    import ai_news_agent.tools as tools_package

    with pytest.raises(AttributeError):
        _ = tools_package.ToolDefinition

    assert "ToolDefinition" not in tools_package.__all__
    assert "encode_tool_value" not in tools_package.__all__
    assert "tool_observation_to_dict" not in tools_package.__all__
    assert "RankOrSourceArgs" in tools_package.__all__
    assert "SearchArgs" in tools_package.__all__

    from ai_news_agent.tools import RankOrSourceArgs, SearchArgs

    assert RankOrSourceArgs is not None
    assert SearchArgs is not None


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
