"""Contract tests for digest workflow state and requests (Task T10a)."""

from __future__ import annotations

from datetime import UTC, datetime
from operator import add

import pytest

from ai_news_agent.graph.state import (
    DigestGraphState,
    WorkflowError,
    initial_state,
    state_to_result,
)
from ai_news_agent.models import (
    ConnectorWarning,
    Digest,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.request import DigestRequest
from ai_news_agent import topics


def test_digest_request_defaults_and_validation() -> None:
    req = DigestRequest()
    assert req.topics == list(topics.DEFAULT_TOPICS)
    assert req.timeframe is None
    assert req.max_items_per_source == 20
    assert req.top_n == 5
    assert req.language_hint is None
    assert req.target_channels == []
    assert req.manual_urls == []
    assert req.connector_names is None

    with pytest.raises(ValueError, match="top_n"):
        DigestRequest(top_n=-1)

    with pytest.raises(ValueError, match="max_items_per_source"):
        DigestRequest(max_items_per_source=0)

    stripped = DigestRequest(topics=["  a  ", "", "  ", "b"])
    assert stripped.topics == ["a", "b"]

    empty = DigestRequest(topics=[])
    assert empty.topics == []


def test_initial_state_shape() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    state = initial_state(req, now=now)
    assert state["request"] is req
    assert state["started_at"] == now
    assert state["finished_at"] is None
    assert state["collected_items"] == []
    assert state["warnings"] == []
    assert state["errors"] == []


def test_state_reducers_accumulate_lists() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    i1 = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://example.com/1",
        title="One",
        collected_at=now,
    )
    i2 = NewsItem(
        source=SourceKind.GITHUB,
        source_id="2",
        url="https://example.com/2",
        title="Two",
        collected_at=now,
    )
    w1 = ConnectorWarning(connector="github", code="a", message="m1")
    w2 = ConnectorWarning(connector="bilibili", code="b", message="m2")
    e1 = WorkflowError(stage="collect", message="e1")
    e2 = WorkflowError(stage="rank", message="e2")

    merged_items = add([i1], [i2])
    assert len(merged_items) == 2
    assert merged_items[0].source_id == "1"
    assert merged_items[1].source_id == "2"

    merged_warnings = add([w1], [w2])
    assert merged_warnings == [w1, w2]

    merged_errors = add([e1], [e2])
    assert merged_errors == [e1, e2]


def test_state_single_writer_fields_replace() -> None:
    """Last dict update wins for non-reducer keys (LangGraph merge semantics)."""
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    d1 = Digest(
        generated_at=now,
        entries=[],
        topics=["a"],
        timeframe=None,
    )
    d2 = Digest(
        generated_at=now,
        entries=[],
        topics=["b"],
        timeframe=None,
    )
    partial: DigestGraphState = {}
    partial.update({"digest": d1})
    partial.update({"digest": d2})
    assert partial["digest"] is d2

    partial2: DigestGraphState = {}
    partial2.update({"run_id": 1})
    partial2.update({"run_id": 2})
    assert partial2["run_id"] == 2


def test_state_to_result_happy_path() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    end = datetime(2026, 5, 16, 12, 5, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://example.com/r",
        title="Repo",
        collected_at=now,
    )
    ranked = [
        RankedItem(
            item=item,
            score_total=1.0,
            score_breakdown={"x": 1.0},
            selected=True,
            selection_reason="top",
        )
    ]
    digest = Digest(generated_at=end, entries=[], topics=["RAG"], timeframe=None)
    w = ConnectorWarning(connector="github", code="c", message="note")

    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "finished_at": end,
        "collected_items": [],
        "warnings": [w],
        "errors": [],
        "ranked_items": ranked,
        "digest": digest,
        "run_id": 42,
        "markdown": "# hi\n",
        "text": "hi\n",
    }

    result = state_to_result(state)
    assert result.request is req
    assert result.digest is digest
    assert result.run_id == 42
    assert result.markdown == "# hi\n"
    assert result.text == "hi\n"
    assert result.ranked_items == ranked
    assert result.warnings == [w]
    assert result.errors == []
    assert result.started_at == now
    assert result.finished_at == end

    expected_ranked = list(ranked)
    result.warnings.clear()
    assert state["warnings"] == [w]

    state["ranked_items"].clear()
    assert result.ranked_items == expected_ranked


def test_state_to_result_handles_empty_run() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=[])
    state = initial_state(req, now=now)
    result = state_to_result(state)
    assert result.digest is None
    assert result.run_id is None
    assert result.markdown == ""
    assert result.text == ""
    assert result.ranked_items == []
    assert result.warnings == []
    assert result.errors == []
    assert result.started_at == now
    assert result.finished_at == now
