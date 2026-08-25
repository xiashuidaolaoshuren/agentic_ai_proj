"""Contract tests for digest workflow state and requests (Task T10a)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from operator import add
from pathlib import Path

import pytest

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.graph.state import (
    DigestGraphState,
    WorkflowError,
    initial_state,
    state_to_result,
)
from ai_news_agent.graph.nodes import (
    make_collect_sources_node,
    make_persist_results_node,
    make_rank_items_node,
    make_render_digest_node,
    make_summarize_items_node,
    parse_request_node,
)
from ai_news_agent.models import (
    ConfidenceLevel,
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.rendering import render_digest_markdown, render_digest_text
from ai_news_agent.request import DigestRequest
from ai_news_agent.storage import DigestStore
from ai_news_agent import topics
from ai_news_agent.graph.workflow import run_digest


def _news_item(source_id: str) -> NewsItem:
    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        title=f"item-{source_id}",
        collected_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
    )


class _FakeConnector:
    def __init__(
        self,
        *,
        name: str,
        items: list[NewsItem] | None = None,
        warnings: list[ConnectorWarning] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._name = name
        self._items = list(items or [])
        self._warnings = list(warnings or [])
        self._error = error
        self.calls = 0

    def name(self) -> str:
        return self._name

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return ConnectorResult(items=list(self._items), warnings=list(self._warnings))


class _FakeDigestModel:
    def generate_entry_fields(self, context: dict) -> dict:  # noqa: ARG002
        return {
            "summary": "Test summary",
            "why_it_matters": "Because",
            "background_knowledge": "Bg",
            "follow_up_action": "read",
        }


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


def test_digest_request_huggingface_fields_round_trip() -> None:
    req = DigestRequest(
        huggingface_discovery_mode="filtered",
        huggingface_search="RAG",
        huggingface_pipeline_tag="text-generation",
    )
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_search == "RAG"
    assert req.huggingface_pipeline_tag == "text-generation"


def test_digest_request_huggingface_fields_default_none() -> None:
    req = DigestRequest()
    assert req.huggingface_discovery_mode is None
    assert req.huggingface_search is None
    assert req.huggingface_pipeline_tag is None


def test_digest_request_items_per_source_round_trip_and_validation() -> None:
    req = DigestRequest(items_per_source=3)
    assert req.items_per_source == 3
    assert DigestRequest().items_per_source is None

    with pytest.raises(ValueError, match="items_per_source"):
        DigestRequest(items_per_source=0)


def test_rank_items_node_forwards_items_per_source(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _spy_rank_items(items, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        from ai_news_agent.ranking import rank_items

        return rank_items(items, **kwargs)

    monkeypatch.setattr("ai_news_agent.graph.nodes.rank.rank_items", _spy_rank_items)

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], top_n=5, items_per_source=3)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh-1",
        url="https://github.com/o/r1",
        title="Repo",
        collected_at=now,
        metadata_completeness=0.8,
    )
    node = make_rank_items_node(now_provider=lambda: now)
    node({"request": req, "started_at": now, "collected_items": [item]})

    assert captured.get("items_per_source") == 3


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


def test_parse_request_node_maps_required_fields() -> None:
    req = DigestRequest(
        topics=["RAG"],
        timeframe="last_7_days",
        max_items_per_source=10,
        language_hint="zh",
        target_channels=["a"],
        manual_urls=["u"],
    )
    out = parse_request_node({"request": req})
    cr = out["connector_request"]
    assert cr.topics == ["RAG"]
    assert cr.timeframe == "last_7_days"
    assert cr.max_items == 10
    assert cr.language_hint == "zh"
    assert cr.target_channels == ["a"]
    assert cr.manual_urls == ["u"]


def test_parse_request_node_maps_juya_manual_urls() -> None:
    req = DigestRequest(
        topics=["RAG"],
        juya_manual_urls=["https://daily.juya.uk/", "https://daily.juya.uk/markdown/2026-08-11.md"],
    )
    out = parse_request_node({"request": req})
    cr = out["connector_request"]
    assert cr.juya_manual_urls == req.juya_manual_urls


def test_parse_request_node_maps_huggingface_fields() -> None:
    req = DigestRequest(
        topics=["RAG"],
        huggingface_discovery_mode="filtered",
        huggingface_search="RAG",
        huggingface_pipeline_tag="text-generation",
    )
    out = parse_request_node({"request": req})
    cr = out["connector_request"]
    assert cr.huggingface_discovery_mode == "filtered"
    assert cr.huggingface_search == "RAG"
    assert cr.huggingface_pipeline_tag == "text-generation"


def test_parse_request_node_missing_request_emits_error() -> None:
    out = parse_request_node({})
    assert "connector_request" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "parse"
    assert "missing DigestRequest" in err.message


def test_collect_sources_node_accumulates_items_and_warnings() -> None:
    conn_a = _FakeConnector(
        name="a",
        items=[_news_item("a1")],
        warnings=[ConnectorWarning(connector="a", code="warn", message="w")],
    )
    conn_b = _FakeConnector(
        name="b",
        items=[_news_item("b1"), _news_item("b2")],
    )
    req = DigestRequest(topics=["RAG"], connector_names=["a", "b"])
    state: DigestGraphState = {"request": req, "connector_request": parse_request_node({"request": req})["connector_request"]}
    node = make_collect_sources_node([conn_a, conn_b])

    out = asyncio.run(node(state))

    assert len(out["collected_items"]) == 3
    assert len(out["warnings"]) == 1


def test_collect_sources_node_emits_per_source_progress_lines() -> None:
    conn_juya = _FakeConnector(
        name="juya",
        items=[_news_item("j1"), _news_item("j2")],
    )
    conn_hf = _FakeConnector(
        name="huggingface",
        items=[_news_item("hf1")],
    )
    progress: list[str] = []
    req = DigestRequest(topics=["RAG"], connector_names=["juya", "huggingface"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node(
        [conn_juya, conn_hf],
        on_progress=progress.append,
    )

    asyncio.run(node(state))

    assert progress == [
        "Collecting from sources…",
        "Calling juya…",
        "Calling huggingface…",
        "Done juya: Found 2 juya results.",
        "Done huggingface: Found 1 huggingface result.",
    ]


def test_collect_sources_node_filters_by_connector_names() -> None:
    conn_a = _FakeConnector(
        name="a",
        items=[_news_item("a1")],
    )
    conn_b = _FakeConnector(
        name="b",
        items=[_news_item("b1"), _news_item("b2")],
    )
    req = DigestRequest(topics=["RAG"], connector_names=["b"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node([conn_a, conn_b])

    out = asyncio.run(node(state))

    assert len(out["collected_items"]) == 2
    assert conn_a.calls == 0
    assert conn_b.calls == 1


def test_collect_sources_node_filters_huggingface_and_zhihu_only() -> None:
    conn_juya = _FakeConnector(name="juya", items=[_news_item("juya1")])
    conn_github = _FakeConnector(name="github", items=[_news_item("gh1")])
    conn_bilibili = _FakeConnector(name="bilibili", items=[_news_item("bili1")])
    conn_huggingface = _FakeConnector(name="huggingface", items=[_news_item("hf1")])
    conn_zhihu = _FakeConnector(name="zhihu", items=[_news_item("zh1")])
    req = DigestRequest(topics=["RAG"], connector_names=["huggingface", "zhihu"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node(
        [conn_juya, conn_github, conn_bilibili, conn_huggingface, conn_zhihu]
    )

    out = asyncio.run(node(state))

    assert len(out["collected_items"]) == 2
    assert conn_juya.calls == 0
    assert conn_github.calls == 0
    assert conn_bilibili.calls == 0
    assert conn_huggingface.calls == 1
    assert conn_zhihu.calls == 1


def test_collect_sources_node_catches_connector_exceptions() -> None:
    conn_a = _FakeConnector(name="a", error=RuntimeError("boom"))
    conn_b = _FakeConnector(
        name="b",
        items=[_news_item("b1")],
    )
    req = DigestRequest(topics=["RAG"], connector_names=["a", "b"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node([conn_a, conn_b])

    out = asyncio.run(node(state))

    assert len(out["collected_items"]) == 1
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "collect"
    assert "RuntimeError" in err.message
    assert "boom" in (err.detail or "")


def test_collect_sources_node_missing_connector_request_emits_error() -> None:
    req = DigestRequest(topics=["RAG"])
    state: DigestGraphState = {"request": req}
    node = make_collect_sources_node([_FakeConnector(name="a")])

    out = asyncio.run(node(state))

    assert "collected_items" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "collect"
    assert "missing ConnectorRequest" in err.message


def test_collect_sources_node_unmatched_filter_emits_error() -> None:
    conn_a = _FakeConnector(name="a", items=[_news_item("a1")])
    req = DigestRequest(topics=["RAG"], connector_names=["unknown"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node([conn_a])

    out = asyncio.run(node(state))

    assert "collected_items" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "collect"
    assert err.message == "no matching connectors"
    assert err.detail == "unknown"
    assert conn_a.calls == 0


def test_collect_sources_node_defaults_to_juya_when_none() -> None:
    conn_github = _FakeConnector(name="github", items=[_news_item("gh1")])
    conn_bilibili = _FakeConnector(name="bilibili", items=[_news_item("bili1")])
    conn_juya = _FakeConnector(name="juya", items=[_news_item("juya1")])
    req = DigestRequest(topics=["RAG"])
    state: DigestGraphState = {
        "request": req,
        "connector_request": parse_request_node({"request": req})["connector_request"],
    }
    node = make_collect_sources_node([conn_github, conn_bilibili, conn_juya])

    out = asyncio.run(node(state))

    assert conn_github.calls == 0
    assert conn_bilibili.calls == 0
    assert conn_juya.calls == 1
    assert len(out["collected_items"]) == 1


def test_rank_items_node_uses_top_n_and_populates_ranked_items() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    low = NewsItem(
        source=SourceKind.GITHUB,
        source_id="low",
        url="https://example.com/low",
        title="Low engagement",
        collected_at=now,
        stars_or_views=10,
        metadata_completeness=0.5,
    )
    high = NewsItem(
        source=SourceKind.GITHUB,
        source_id="high",
        url="https://example.com/high",
        title="High engagement",
        collected_at=now,
        stars_or_views=50_000,
        metadata_completeness=0.9,
    )
    req = DigestRequest(topics=["RAG"], top_n=1)
    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "collected_items": [low, high],
    }
    node = make_rank_items_node(now_provider=lambda: now)
    out = node(state)

    ranked = out["ranked_items"]
    assert len(ranked) == 2
    selected = [r for r in ranked if r.selected]
    assert len(selected) == 1
    assert selected[0].item.source_id == "high"
    assert selected[0].score_breakdown
    assert selected[0].selection_reason


def test_rank_items_node_guarantees_newest_bilibili_when_timeframe_set() -> None:
    from datetime import timedelta

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVworkflownew",
        url="https://www.bilibili.com/video/BVworkflownew",
        title="Workflow newest",
        published_at=now - timedelta(hours=1),
        collected_at=now,
        metadata_completeness=0.25,
        topic_matches=[],
        content_confidence=ConfidenceLevel.LOW,
        stars_or_views=1,
        raw_snippet=None,
    )
    github_items = [
        NewsItem(
            source=SourceKind.GITHUB,
            source_id=f"wfgh{i}",
            url=f"https://github.com/o/wfgh{i}",
            title=f"wfgh{i}",
            published_at=now - timedelta(days=i + 1),
            collected_at=now,
            metadata_completeness=0.95,
            topic_matches=["AI", "LLM"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=8000 + i,
            raw_snippet="readme",
        )
        for i in range(5)
    ]
    req = DigestRequest(
        topics=[],
        top_n=5,
        timeframe="last_7_days",
        bilibili_target_channels=["123456789"],
    )
    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "collected_items": github_items + [bilibili_newest],
    }
    node = make_rank_items_node(now_provider=lambda: now)
    out = node(state)

    selected_ids = {r.item.source_id for r in out["ranked_items"] if r.selected}
    assert "BVworkflownew" in selected_ids
    assert len(selected_ids) == 5


def test_rank_items_node_handles_empty_collected_items() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], top_n=3)
    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "collected_items": [],
    }
    node = make_rank_items_node(now_provider=lambda: now)
    out = node(state)
    assert out == {"ranked_items": []}


def test_rank_items_node_missing_request_emits_error() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    state: DigestGraphState = {
        "started_at": now,
        "collected_items": [_news_item("a1")],
    }
    node = make_rank_items_node(now_provider=lambda: now)
    out = node(state)
    assert "ranked_items" not in out
    assert len(out["errors"]) == 1
    assert out["errors"][0].stage == "rank"
    assert "missing DigestRequest" in out["errors"][0].message


def test_summarize_items_node_builds_digest_with_fake_model() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
        content_confidence=ConfidenceLevel.LOW,
        raw_snippet=None,
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
    req = DigestRequest(topics=["RAG"], timeframe="last_7_days")
    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "ranked_items": ranked,
    }
    node = make_summarize_items_node(_FakeDigestModel())
    out = node(state)
    digest = out["digest"]
    assert isinstance(digest, Digest)
    assert digest.generated_at == now
    assert digest.topics == ["RAG"]
    assert digest.timeframe == "last_7_days"
    assert len(digest.entries) == 1
    entry = digest.entries[0]
    assert entry.summary == "Test summary"
    assert entry.why_it_matters == "Because"
    assert entry.confidence_caveat
    assert "low-confidence" in entry.confidence_caveat.lower()


def test_summarize_items_node_forwards_primary_source() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    juya = NewsItem(
        source=SourceKind.JUYA,
        source_id="juya-1",
        url="https://daily.juya.uk/2026/05/16",
        title="Juya bulletin",
        collected_at=now,
        author="jujuyaya",
        raw_snippet="bulletin",
        content_confidence=ConfidenceLevel.HIGH,
    )
    bilibili = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1",
        url="https://www.bilibili.com/video/BV1",
        title="Bilibili video",
        collected_at=now,
        raw_snippet="video",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    ranked = [
        RankedItem(item=juya, score_total=9.0, selected=True),
        RankedItem(item=bilibili, score_total=1.0, selected=True),
    ]
    req = DigestRequest(topics=["AI"], primary_source="bilibili")
    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "ranked_items": ranked,
    }
    node = make_summarize_items_node(_FakeDigestModel())
    out = node(state)
    digest = out["digest"]
    assert [entry.source_kind for entry in digest.entries] == [
        SourceKind.BILIBILI,
        SourceKind.JUYA,
    ]


def test_summarize_items_node_handles_empty_ranked_items() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    state: DigestGraphState = {"request": req, "started_at": now, "ranked_items": []}
    node = make_summarize_items_node(_FakeDigestModel())
    out = node(state)
    digest = out["digest"]
    assert digest.entries == []
    assert "errors" not in out


def test_summarize_items_node_missing_request_emits_error() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    state: DigestGraphState = {
        "started_at": now,
        "ranked_items": [],
    }
    node = make_summarize_items_node(_FakeDigestModel())
    out = node(state)
    assert "digest" not in out
    assert len(out["errors"]) == 1
    assert out["errors"][0].stage == "summarize"
    assert "missing DigestRequest" in out["errors"][0].message


def test_summarize_items_node_catches_summarizer_failure() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    ranked = [
        RankedItem(
            item=item,
            score_total=1.0,
            selected=True,
            selection_reason="top",
        )
    ]
    req = DigestRequest(topics=["RAG"])
    state: DigestGraphState = {"request": req, "started_at": now, "ranked_items": ranked}
    node = make_summarize_items_node(None)
    out = node(state)
    assert "digest" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "summarize"
    assert "summarization failed" in err.message
    assert "ValueError" in err.message


# --- Task T10d: persist + render workflow nodes --------------------------------


class _BrokenDigestStore(DigestStore):
    """Used to verify persist node catches unexpected storage failures."""

    def save_run(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


def test_persist_results_node_happy_path_saves_round_trip(tmp_path) -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], timeframe="last_7_days", connector_names=["github"])
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    w = ConnectorWarning(connector="github", code="rate", message="slow")
    ranked = [
        RankedItem(
            item=item,
            score_total=2.5,
            score_breakdown={"k": 1.0},
            selected=True,
            selection_reason="top",
        )
    ]
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe="last_7_days",
    )

    db = tmp_path / "t10d.db"
    store = DigestStore(db)
    store.init_schema()
    node = make_persist_results_node(store)

    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "collected_items": [item],
        "warnings": [w],
        "ranked_items": ranked,
        "digest": digest,
    }
    before_keys = sorted(state.keys())
    out = node(state)

    assert out["run_id"] == 1
    assert sorted(state.keys()) == before_keys

    ctx = store.get_latest_followup_context()
    assert ctx.run_id == 1
    assert ctx.digest == digest
    assert ctx.ranked_items == ranked
    assert ctx.news_items == [item]
    assert ctx.warnings == [w]


def test_persist_results_node_missing_request_emits_error(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "miss_req.db")
    store.init_schema()
    node = make_persist_results_node(store)
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    digest = Digest(generated_at=now, entries=[], topics=[], timeframe=None)
    out = node({"started_at": now, "digest": digest})

    assert "run_id" not in out
    assert len(out["errors"]) == 1
    assert out["errors"][0].stage == "store"
    assert "missing DigestRequest" in out["errors"][0].message


def test_persist_results_node_missing_digest_emits_error(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "miss_digest.db")
    store.init_schema()
    node = make_persist_results_node(store)
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    out = node({"request": req, "started_at": now})

    assert "run_id" not in out
    assert len(out["errors"]) == 1
    assert out["errors"][0].stage == "store"
    assert "missing Digest" in out["errors"][0].message


def test_persist_results_node_catches_storage_errors(tmp_path) -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    digest = Digest(generated_at=now, entries=[], topics=["RAG"], timeframe=None)
    store = _BrokenDigestStore(tmp_path / "x.db")
    store.init_schema()
    node = make_persist_results_node(store)
    out = node({"request": req, "started_at": now, "digest": digest})

    assert "run_id" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "store"
    assert "RuntimeError" in err.message
    assert "boom" in (err.detail or "")


def test_persist_records_resolved_default_connector_names(tmp_path) -> None:
    import json
    import sqlite3

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    # Bare run: connector_names is None. Mixed items/warnings would today be
    # inferred from item.source.value / warning.connector, but the resolved
    # default must be recorded instead.
    req = DigestRequest(topics=["RAG"])
    github_item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh1",
        url="https://example.com/gh1",
        title="GitHub item",
        collected_at=now,
    )
    bilibili_warning = ConnectorWarning(
        connector="bilibili", code="rate", message="slow"
    )
    digest = Digest(generated_at=now, entries=[], topics=["RAG"], timeframe=None)

    store = DigestStore(tmp_path / "persist_default.db")
    store.init_schema()
    node = make_persist_results_node(store)

    state: DigestGraphState = {
        "request": req,
        "started_at": now,
        "collected_items": [github_item],
        "warnings": [bilibili_warning],
        "ranked_items": [],
        "digest": digest,
    }
    out = node(state)
    assert out["run_id"] == 1

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT connector_names_json FROM runs WHERE id = 1"
        ).fetchone()
    persisted = json.loads(row["connector_names_json"])
    assert persisted == ["juya"]


def test_render_digest_node_populates_markdown_and_text() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    digest = Digest(
        generated_at=now,
        entries=[],
        topics=["RAG"],
        timeframe=None,
    )
    node = make_render_digest_node()
    state: DigestGraphState = {"digest": digest}
    before_keys = sorted(state.keys())
    out = node(state)

    assert out["markdown"] == render_digest_markdown(digest)
    assert out["text"] == render_digest_text(digest)
    assert sorted(state.keys()) == before_keys


def test_render_digest_node_missing_digest_emits_error() -> None:
    node = make_render_digest_node()
    out = node({})
    assert "markdown" not in out
    assert "text" not in out
    assert len(out["errors"]) == 1
    assert out["errors"][0].stage == "render"
    assert "missing Digest" in out["errors"][0].message


def test_render_digest_node_catches_renderer_failure() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    digest = Digest(generated_at=now, entries=[], topics=[], timeframe=None)

    def _boom(_: Digest, **kwargs: object) -> str:
        del kwargs
        raise ValueError("bad render")

    node = make_render_digest_node(render_markdown=_boom, render_text=render_digest_text)
    out = node({"digest": digest})

    assert "markdown" not in out
    assert len(out["errors"]) == 1
    err = out["errors"][0]
    assert err.stage == "render"
    assert "ValueError" in err.message
    assert "bad render" in (err.detail or "")


def test_t10d_persist_render_state_to_result_integration(tmp_path) -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"])
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=now,
    )
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe=None,
    )
    ranked = [
        RankedItem(
            item=item,
            score_total=1.0,
            selected=True,
            selection_reason="top",
        )
    ]

    db = tmp_path / "e2e.db"
    store = DigestStore(db)
    store.init_schema()
    persist = make_persist_results_node(store)
    render = make_render_digest_node()

    base: DigestGraphState = {
        "request": req,
        "started_at": now,
        "finished_at": now,
        "collected_items": [item],
        "warnings": [],
        "errors": [],
        "ranked_items": ranked,
        "digest": digest,
    }

    merged: DigestGraphState = {**base, **persist(base)}
    merged2: DigestGraphState = {**merged, **render(merged)}

    result = state_to_result(merged2)
    assert result.run_id == 1
    assert result.markdown == render_digest_markdown(digest)
    assert result.text == render_digest_text(digest)
    assert result.digest is digest


# --- Task T10e: graph assembly + end-to-end workflow --------------------------


def test_build_digest_graph_returns_invokable_compiled_graph(tmp_path: Path) -> None:
    from ai_news_agent.graph.workflow import build_digest_graph

    db = tmp_path / "t10e-compile.db"
    store = DigestStore(db)
    store.init_schema()
    graph = build_digest_graph(connectors=[], model=_FakeDigestModel(), store=store)

    assert hasattr(graph, "ainvoke")


def test_run_digest_happy_path_returns_digest_and_persists_run(tmp_path: Path) -> None:
    from ai_news_agent.graph.workflow import run_digest

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    connector = _FakeConnector(name="github", items=[_news_item("a1"), _news_item("a2")])
    req = DigestRequest(topics=["RAG"], connector_names=["github"])

    db = tmp_path / "t10e-happy.db"
    store = DigestStore(db)
    store.init_schema()

    result = asyncio.run(
        run_digest(
            req,
            connectors=[connector],
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        )
    )

    assert result.run_id == 1
    assert result.digest is not None
    assert len(result.digest.entries) > 0
    assert result.markdown
    assert result.text
    assert result.errors == []
    assert store.get_latest_digest() == result.digest


def test_run_digest_with_no_items_returns_empty_digest_no_errors(tmp_path: Path) -> None:
    from ai_news_agent.graph.workflow import run_digest

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    connector = _FakeConnector(name="github", items=[])
    req = DigestRequest(topics=["RAG"], connector_names=["github"])

    db = tmp_path / "t10e-empty.db"
    store = DigestStore(db)
    store.init_schema()

    result = asyncio.run(
        run_digest(
            req,
            connectors=[connector],
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        )
    )

    assert result.run_id == 1
    assert result.digest is not None
    assert result.digest.entries == []
    assert result.markdown
    assert result.errors == []


def test_run_digest_propagates_connector_warnings_into_result(tmp_path: Path) -> None:
    from ai_news_agent.graph.workflow import run_digest

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    warning = ConnectorWarning(connector="github", code="rate_limit", message="slow")
    connector = _FakeConnector(
        name="github",
        items=[_news_item("w1")],
        warnings=[warning],
    )
    req = DigestRequest(topics=["RAG"], connector_names=["github"])

    db = tmp_path / "t10e-warnings.db"
    store = DigestStore(db)
    store.init_schema()

    result = asyncio.run(
        run_digest(
            req,
            connectors=[connector],
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        )
    )

    assert result.errors == []
    assert result.warnings == [warning]
    assert store.get_latest_followup_context().warnings == [warning]


def test_run_digest_continues_when_one_connector_raises(tmp_path: Path) -> None:
    from ai_news_agent.graph.workflow import run_digest

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    broken = _FakeConnector(name="broken", error=RuntimeError("boom"))
    healthy = _FakeConnector(name="healthy", items=[_news_item("ok1")])
    req = DigestRequest(topics=["RAG"], connector_names=["broken", "healthy"])

    db = tmp_path / "t10e-nonfatal.db"
    store = DigestStore(db)
    store.init_schema()

    result = asyncio.run(
        run_digest(
            req,
            connectors=[broken, healthy],
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        )
    )

    assert result.run_id == 1
    assert result.digest is not None
    assert len(result.digest.entries) == 1
    assert len(result.errors) == 1
    assert result.errors[0].stage == "collect"
    assert "RuntimeError" in result.errors[0].message


def test_graph_package_reexports_workflow_helpers() -> None:
    from ai_news_agent.graph import (
        build_digest_graph,
        make_persist_results_node,
        make_render_digest_node,
        run_digest,
    )

    assert callable(build_digest_graph)
    assert callable(run_digest)
    assert callable(make_persist_results_node)
    assert callable(make_render_digest_node)


def test_run_digest_streaming_emits_stage_labels_and_final_result(tmp_path) -> None:
    from ai_news_agent.graph.workflow import run_digest, run_digest_streaming

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], connector_names=["github"])
    store = DigestStore(tmp_path / "stream.db")
    store.init_schema()
    connectors = [
        _FakeConnector(name="github", items=[_news_item("r1")]),
    ]

    async def collect():
        events: list[tuple[str, bool, object | None]] = []
        async for event in run_digest_streaming(
            req,
            connectors=connectors,
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())
    progress = [text for text, done, _ in events if not done]
    finals = [result for _, done, result in events if done]

    assert progress
    assert progress[0] == "Parsing request…"
    assert all("\n" not in line for line in progress)
    assert any("Collecting from sources" in line for line in progress)
    assert progress[-1] == "Rendering digest…"
    assert len(finals) == 1

    store_compare = DigestStore(tmp_path / "stream-compare.db")
    store_compare.init_schema()
    expected = asyncio.run(
        run_digest(
            req,
            connectors=connectors,
            model=_FakeDigestModel(),
            store=store_compare,
            now_provider=lambda: now,
        )
    )
    assert finals[0].text == expected.text


def test_run_digest_streaming_emits_per_source_collect_progress(tmp_path) -> None:
    from ai_news_agent.graph.workflow import run_digest_streaming

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], connector_names=["juya", "huggingface"])
    store = DigestStore(tmp_path / "stream-per-source.db")
    store.init_schema()
    connectors = [
        _FakeConnector(name="juya", items=[_news_item("j1"), _news_item("j2")]),
        _FakeConnector(name="huggingface", items=[_news_item("hf1")]),
    ]

    async def collect():
        events: list[tuple[str, bool, object | None]] = []
        async for event in run_digest_streaming(
            req,
            connectors=connectors,
            model=_FakeDigestModel(),
            store=store,
            now_provider=lambda: now,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())
    progress = [text for text, done, _ in events if not done]

    assert "Parsing request…" in progress
    assert "Collecting from sources…" in progress
    assert "Calling juya…" in progress
    assert "Done juya: Found 2 juya results." in progress
    assert "Calling huggingface…" in progress
    assert "Done huggingface: Found 1 huggingface result." in progress
    assert "Ranking candidates…" in progress


def test_run_digest_streaming_raises_when_workflow_node_raises(tmp_path) -> None:
    from unittest.mock import MagicMock, patch

    from ai_news_agent.graph.workflow import run_digest_streaming

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    req = DigestRequest(topics=["RAG"], connector_names=["github"])
    store = DigestStore(tmp_path / "stream-error.db")
    store.init_schema()
    connectors = [
        _FakeConnector(name="github", items=[_news_item("r1")]),
    ]

    async def failing_astream(*_args, **_kwargs):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover - makes this an async generator

    mock_graph = MagicMock()
    mock_graph.astream = failing_astream

    async def collect() -> list[tuple[str, bool, object | None]]:
        events: list[tuple[str, bool, object | None]] = []
        with patch(
            "ai_news_agent.graph.workflow.build_digest_graph",
            return_value=mock_graph,
        ):
            async for event in run_digest_streaming(
                req,
                connectors=connectors,
                model=_FakeDigestModel(),
                store=store,
                now_provider=lambda: now,
            ):
                events.append(event)
        return events

    with pytest.raises(RuntimeError, match="stream failed"):
        asyncio.run(asyncio.wait_for(collect(), timeout=5))
