"""Tests for Milestone 2 tool schema foundation (Task T1)."""

from __future__ import annotations

import json

import pytest

from ai_news_agent.models import ConnectorWarning, connector_warning_to_dict
from ai_news_agent.tools.schemas import (
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
    encode_tool_value,
    tool_observation_to_dict,
)


def test_tool_observation_defaults() -> None:
    obs = ToolObservation(status=ToolObservationStatus.OK, summary="Found latest digest")
    assert obs.data == {}
    assert obs.caveats == []


def test_tool_observation_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="Invalid status"):
        ToolObservation(status="not-a-status", summary="x")  # type: ignore[arg-type]


def test_tool_observation_to_dict_is_json_safe() -> None:
    obs = ToolObservation(
        status=ToolObservationStatus.NOT_FOUND,
        summary="No item at rank 3",
        data={"rank": 3},
        caveats=["Try a lower rank"],
    )
    encoded = tool_observation_to_dict(obs)
    json.dumps(encoded)
    assert encoded == {
        "status": "not_found",
        "summary": "No item at rank 3",
        "data": {"rank": 3},
        "caveats": ["Try a lower rank"],
    }


def test_encode_tool_value_reuses_domain_encoding() -> None:
    warning = ConnectorWarning(connector="github", code="rate_limit", message="Slow down")
    encoded = encode_tool_value({"warnings": [connector_warning_to_dict(warning)]})
    json.dumps(encoded)
    assert encoded["warnings"][0]["connector"] == "github"


def test_search_query_input_defaults_and_validation() -> None:
    query = SearchQueryInput(query="AI agents")
    assert query.max_results == 5

    with pytest.raises(ValueError, match="query must not be empty"):
        SearchQueryInput(query="   ")

    with pytest.raises(ValueError, match="max_results must be at least 1"):
        SearchQueryInput(query="RAG", max_results=0)


def test_tools_package_exports_build_tool_registry() -> None:
    from ai_news_agent.tools import build_tool_registry

    with pytest.raises(TypeError):
        build_tool_registry()
