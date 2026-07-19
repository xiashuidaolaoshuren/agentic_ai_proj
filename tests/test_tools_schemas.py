"""Tests for Milestone 2 tool schema foundation (Task T1)."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from ai_news_agent.models import ConnectorWarning
from ai_news_agent.tools.schemas import (
    RankOrSourceArgs,
    SearchArgs,
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
    encode_tool_value,
    tool_observation_to_dict,
)


def test_tool_observation_is_pydantic_basemodel() -> None:
    assert issubclass(ToolObservation, BaseModel)


def test_tool_observation_defaults() -> None:
    obs = ToolObservation(status=ToolObservationStatus.OK, summary="Found latest digest")
    assert obs.data == {}
    assert obs.caveats == []


def test_tool_observation_rejects_blank_summary() -> None:
    with pytest.raises(ValidationError):
        ToolObservation(status=ToolObservationStatus.OK, summary="   ")


def test_tool_observation_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
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
    assert encoded == obs.model_dump(mode="json")
    assert encoded == {
        "status": "not_found",
        "summary": "No item at rank 3",
        "data": {"rank": 3},
        "caveats": ["Try a lower rank"],
    }


def test_encode_tool_value_reuses_domain_encoding() -> None:
    warning = ConnectorWarning(connector="github", code="rate_limit", message="Slow down")
    encoded = encode_tool_value({"warnings": [warning.model_dump(mode="json")]})
    json.dumps(encoded)
    assert encoded["warnings"][0]["connector"] == "github"


def test_search_query_input_defaults_and_validation() -> None:
    query = SearchQueryInput(query="AI agents")
    assert query.max_results == 5

    with pytest.raises(ValidationError):
        SearchQueryInput(query="   ")

    with pytest.raises(ValidationError):
        SearchQueryInput(query="RAG", max_results=0)


def test_rank_or_source_args_matches_registry_contract() -> None:
    args = RankOrSourceArgs()
    assert args.rank is None
    assert args.source_id is None

    args_with_source = RankOrSourceArgs(source_id="repo-1")
    assert args_with_source.source_id == "repo-1"

    with pytest.raises(ValidationError):
        RankOrSourceArgs(rank=0)


def test_search_args_matches_registry_contract() -> None:
    args = SearchArgs(query="AI agents")
    assert args.max_results == 5
    assert args.timeframe is None

    args_with_timeframe = SearchArgs(query="RAG", timeframe="last_7_days")
    assert args_with_timeframe.timeframe == "last_7_days"

    with pytest.raises(ValidationError):
        SearchArgs(query="RAG", max_results=0)


def test_tools_schemas_module_imports_without_eager_broken_helpers() -> None:
    from ai_news_agent.tools.schemas import (
        SearchQueryInput,
        ToolObservation,
        ToolObservationStatus,
        encode_tool_value,
        tool_observation_to_dict,
    )

    assert ToolObservation is not None
    assert SearchQueryInput is not None
    assert ToolObservationStatus.OK.value == "ok"
    assert callable(encode_tool_value)
    assert callable(tool_observation_to_dict)
