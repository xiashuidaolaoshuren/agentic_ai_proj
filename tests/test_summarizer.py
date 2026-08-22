"""Tests for LLM-backed summarization (Milestone 1 Task 8)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)


def _fixed_now() -> datetime:
    return datetime(2026, 5, 13, 4, 0, 0, tzinfo=UTC)


def test_summarize_ranked_items_returns_digest_when_no_candidates() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    digest = summarize_ranked_items(
        [],
        generated_at=_fixed_now(),
        topics=["AI"],
        timeframe="today",
    )
    assert digest.entries == []
    assert digest.generated_at == _fixed_now()
    assert digest.topics == ["AI"]
    assert digest.timeframe == "today"


def test_summarize_skips_unselected_ranked_items() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://example.com",
        title="t",
        collected_at=_fixed_now(),
    )
    ranked = [RankedItem(item=ni, score_total=1.0, selected=False)]
    digest = summarize_ranked_items(ranked, generated_at=_fixed_now(), topics=["x"])
    assert digest.entries == []


class FakeChatModel:
    """Deterministic substitute for LLM-backed JSON generation in tests."""

    _DEFAULT = {
        "summary": "Brief summary.",
        "why_it_matters": "Why.",
        "background_knowledge": "Background.",
        "follow_up_action": "read",
    }

    def __init__(
        self,
        *,
        default: dict | None = None,
        per_source: dict[tuple[SourceKind, str, str], dict] | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._default = dict(self._DEFAULT if default is None else default)
        self._per_source = dict(per_source or {})

    def generate_entry_fields(self, context: dict) -> dict:
        self.calls.append(context)
        key = (
            SourceKind(context["source_kind"]),
            str(context["source_id"]),
            str(context["title"]),
        )
        if key in self._per_source:
            return dict(self._per_source[key])
        return dict(self._default)


def test_summarize_one_selected_requires_model() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s1",
        url="https://github.com/org/repo",
        title="org/repo",
        collected_at=_fixed_now(),
        author="alice",
        raw_snippet="description",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    ranked = [RankedItem(item=ni, score_total=2.0, selected=True)]
    try:
        summarize_ranked_items(ranked, generated_at=_fixed_now(), topics=["AI"])
    except ValueError as exc:
        assert "model" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_summarize_one_selected_uses_fake_model_output() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s1",
        url="https://github.com/org/repo",
        title="org/repo",
        collected_at=_fixed_now(),
        author="alice",
        raw_snippet="Rust agent toolkit.",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    fake = FakeChatModel()
    ranked = [RankedItem(item=ni, score_total=2.0, selected=True, selection_reason="rank #1")]
    digest = summarize_ranked_items(
        ranked,
        generated_at=_fixed_now(),
        topics=["agents"],
        timeframe="today",
        model=fake,
    )
    assert len(digest.entries) == 1
    e = digest.entries[0]
    assert e.source_kind is SourceKind.GITHUB
    assert e.source_id == "s1"
    assert e.source_url == ni.url
    assert e.title == ni.title
    assert e.summary == "Brief summary."
    assert e.why_it_matters == "Why."
    assert e.background_knowledge == "Background."
    assert e.follow_up_action is FollowUpAction.READ
    assert fake.calls and fake.calls[0]["url"] == ni.url


def test_summarize_keeps_selected_order_aligned_with_input_rank_list() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    n1 = NewsItem(
        source=SourceKind.GITHUB,
        source_id="g1",
        url="https://github.com/o/one",
        title="one",
        collected_at=_fixed_now(),
        raw_snippet="a",
        content_confidence=ConfidenceLevel.HIGH,
    )
    n2 = NewsItem(
        source=SourceKind.GITHUB,
        source_id="g2",
        url="https://github.com/o/two",
        title="two",
        collected_at=_fixed_now(),
        raw_snippet="b",
        content_confidence=ConfidenceLevel.HIGH,
    )
    ranked = [
        RankedItem(item=n1, score_total=3.0, selected=True),
        RankedItem(item=n2, score_total=2.0, selected=True),
    ]

    outs = {
        (SourceKind.GITHUB, "g1", "one"): {
            "summary": "S-A",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "read",
        },
        (SourceKind.GITHUB, "g2", "two"): {
            "summary": "S-B",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "try",
        },
    }
    fake = FakeChatModel(per_source=outs)
    digest = summarize_ranked_items(ranked, generated_at=_fixed_now(), topics=["t"], model=fake)
    assert [x.summary for x in digest.entries] == ["S-A", "S-B"]
    assert digest.entries[0].follow_up_action is FollowUpAction.READ
    assert digest.entries[1].follow_up_action is FollowUpAction.TRY


def test_summarize_order_places_newest_in_window_bilibili_first() -> None:
    from datetime import timedelta

    from ai_news_agent.summarizer import summarize_ranked_items

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    github = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh1",
        url="https://github.com/o/gh1",
        title="GitHub top score",
        published_at=now - timedelta(days=2),
        collected_at=now,
        raw_snippet="readme",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    bilibili_older = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVolder",
        url="https://www.bilibili.com/video/BVolder",
        title="Older Bilibili",
        published_at=now - timedelta(days=3),
        collected_at=now,
        raw_snippet="old",
        content_confidence=ConfidenceLevel.LOW,
    )
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVnewest",
        url="https://www.bilibili.com/video/BVnewest",
        title="Newest Bilibili",
        published_at=now - timedelta(hours=2),
        collected_at=now,
        raw_snippet="new",
        content_confidence=ConfidenceLevel.LOW,
    )
    ranked = [
        RankedItem(item=github, score_total=9.0, selected=True),
        RankedItem(item=bilibili_older, score_total=8.0, selected=True),
        RankedItem(item=bilibili_newest, score_total=1.0, selected=True),
    ]
    outs = {
        (SourceKind.GITHUB, "gh1", "GitHub top score"): {
            "summary": "GH",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "read",
        },
        (SourceKind.BILIBILI, "BVolder", "Older Bilibili"): {
            "summary": "OLD",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "watch",
        },
        (SourceKind.BILIBILI, "BVnewest", "Newest Bilibili"): {
            "summary": "NEW",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "watch",
        },
    }
    fake = FakeChatModel(per_source=outs)
    digest = summarize_ranked_items(
        ranked,
        generated_at=now,
        topics=["AI"],
        timeframe="last_7_days",
        model=fake,
    )

    assert [e.source_id for e in digest.entries] == ["gh1", "BVnewest", "BVolder"]
    assert [e.source_kind for e in digest.entries] == [
        SourceKind.GITHUB,
        SourceKind.BILIBILI,
        SourceKind.BILIBILI,
    ]


def test_summarize_juya_entry_uses_juya_source_display_name() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.JUYA,
        source_id="juya-1",
        url="https://daily.juya.uk/2026/05/13",
        title="Juya bulletin",
        collected_at=_fixed_now(),
        author="jujuyaya",
        raw_snippet="Daily AI news bulletin.",
        content_confidence=ConfidenceLevel.HIGH,
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    assert len(digest.entries) == 1
    assert digest.entries[0].source_name == "Juya"


def test_summarize_huggingface_entry_uses_brand_source_display_name() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id="hf-1",
        url="https://huggingface.co/models/hf-1",
        title="Trending model",
        collected_at=_fixed_now(),
        author="meta-llama",
        raw_snippet="Model card excerpt.",
        content_confidence=ConfidenceLevel.HIGH,
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    assert digest.entries[0].source_name == "Hugging Face"


def test_summarize_zhihu_entry_uses_brand_source_display_name() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.ZHIHU,
        source_id="zh-1",
        url="https://www.zhihu.com/question/1",
        title="Practitioner insight",
        collected_at=_fixed_now(),
        author="some-author",
        raw_snippet="Trade-off discussion.",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    assert digest.entries[0].source_name == "Zhihu"


def test_summarize_huggingface_context_includes_source_evidence() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id="hf-ctx",
        url="https://huggingface.co/models/hf-ctx",
        title="Context model",
        collected_at=_fixed_now(),
        raw_snippet="Model card excerpt.",
        content_confidence=ConfidenceLevel.HIGH,
        source_evidence={"trending_score": 42.0, "downloads_30d": 1000},
    )
    fake = FakeChatModel()
    summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    ctx = fake.calls[0]
    assert "source_evidence" in ctx
    assert ctx["source_evidence"]["trending_score"] == 42.0


def test_summarize_huggingface_entry_adds_popularity_not_quality_caveat() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id="hf-caveat",
        url="https://huggingface.co/models/hf-caveat",
        title="Popular model",
        collected_at=_fixed_now(),
        raw_snippet="Model card excerpt.",
        content_confidence=ConfidenceLevel.HIGH,
        source_evidence={"trending_score": 999.0},
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    caveat = digest.entries[0].confidence_caveat or ""
    assert "popularity" in caveat.lower()
    assert "quality" in caveat.lower()


def test_summarize_zhihu_thin_evidence_adds_discovery_caveat() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.ZHIHU,
        source_id="zh-thin",
        url="https://www.zhihu.com/question/thin",
        title="Thin Zhihu post",
        collected_at=_fixed_now(),
        raw_snippet="Short.",
        content_confidence=ConfidenceLevel.LOW,
        source_evidence={"evidence_text_length": 30, "relevance": 0.5},
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
    )
    caveat = digest.entries[0].confidence_caveat or ""
    assert "discovery" in caveat.lower() or "thin" in caveat.lower()


def test_summarize_ranked_items_primary_source_bilibili_first() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    github = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh1",
        url="https://github.com/o/gh1",
        title="GitHub repo",
        collected_at=_fixed_now(),
        raw_snippet="readme",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    bilibili = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1",
        url="https://www.bilibili.com/video/BV1",
        title="Bilibili video",
        collected_at=_fixed_now(),
        raw_snippet="video",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    ranked = [
        RankedItem(item=github, score_total=9.0, selected=True),
        RankedItem(item=bilibili, score_total=1.0, selected=True),
    ]
    outs = {
        (SourceKind.GITHUB, "gh1", "GitHub repo"): {
            "summary": "GH",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "read",
        },
        (SourceKind.BILIBILI, "BV1", "Bilibili video"): {
            "summary": "BILI",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "watch",
        },
    }
    fake = FakeChatModel(per_source=outs)
    digest = summarize_ranked_items(
        ranked,
        generated_at=_fixed_now(),
        topics=["AI"],
        model=fake,
        primary_source="bilibili",
    )
    assert [e.source_kind for e in digest.entries] == [
        SourceKind.BILIBILI,
        SourceKind.GITHUB,
    ]


def test_summarize_order_no_reorder_without_timeframe() -> None:
    from datetime import timedelta

    from ai_news_agent.summarizer import summarize_ranked_items

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    github = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh1",
        url="https://github.com/o/gh1",
        title="GitHub first",
        published_at=now - timedelta(days=1),
        collected_at=now,
        raw_snippet="readme",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVnewest",
        url="https://www.bilibili.com/video/BVnewest",
        title="Newest Bilibili",
        published_at=now - timedelta(hours=1),
        collected_at=now,
        raw_snippet="new",
        content_confidence=ConfidenceLevel.LOW,
    )
    ranked = [
        RankedItem(item=github, score_total=9.0, selected=True),
        RankedItem(item=bilibili_newest, score_total=1.0, selected=True),
    ]
    outs = {
        (SourceKind.GITHUB, "gh1", "GitHub first"): {
            "summary": "GH",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "read",
        },
        (SourceKind.BILIBILI, "BVnewest", "Newest Bilibili"): {
            "summary": "NEW",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "watch",
        },
    }
    fake = FakeChatModel(per_source=outs)
    digest = summarize_ranked_items(
        ranked,
        generated_at=now,
        topics=["AI"],
        timeframe=None,
        model=fake,
    )

    assert [e.source_id for e in digest.entries] == ["gh1", "BVnewest"]


def test_low_confidence_adds_caveat_even_if_model_omits() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="low1",
        url="https://github.com/x/y",
        title="y",
        collected_at=_fixed_now(),
        raw_snippet="meta only",
        content_confidence=ConfidenceLevel.LOW,
    )
    fake = FakeChatModel(
        default={
            "summary": "S",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "read",
        }
    )
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["t"],
        model=fake,
    )
    e = digest.entries[0]
    assert e.confidence_caveat
    assert "low-confidence" in e.confidence_caveat.lower()


def test_invalid_follow_up_action_defaults_to_read_with_note() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="bad",
        url="https://github.com/x/z",
        title="z",
        collected_at=_fixed_now(),
        raw_snippet="snippet",
        content_confidence=ConfidenceLevel.HIGH,
    )
    fake = FakeChatModel(
        default={
            "summary": "S",
            "why_it_matters": "W",
            "background_knowledge": "B",
            "follow_up_action": "surf-the-web",
        }
    )
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["t"],
        model=fake,
    )
    e = digest.entries[0]
    assert e.follow_up_action is FollowUpAction.READ
    assert e.confidence_caveat
    assert "Unrecognized follow_up_action" in e.confidence_caveat


def test_missing_raw_snippet_triggers_metadata_only_caveat() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="ms",
        url="https://github.com/x/m",
        title="m",
        collected_at=_fixed_now(),
        raw_snippet=None,
        content_confidence=ConfidenceLevel.HIGH,
    )
    fake = FakeChatModel()
    digest = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["t"],
        model=fake,
    )
    assert "metadata-only" in (digest.entries[0].confidence_caveat or "").lower()


def test_digest_round_trips_through_models_codec() -> None:
    from ai_news_agent.summarizer import summarize_ranked_items

    ni = NewsItem(
        source=SourceKind.GITHUB,
        source_id="rt",
        url="https://github.com/x/r",
        title="r",
        collected_at=_fixed_now(),
        raw_snippet="z",
        content_confidence=ConfidenceLevel.MEDIUM,
    )
    d0 = summarize_ranked_items(
        [RankedItem(item=ni, score_total=1.0, selected=True)],
        generated_at=_fixed_now(),
        topics=["a"],
        timeframe="week",
        model=FakeChatModel(),
    )
    d1 = Digest.model_validate(d0.model_dump(mode="json"))
    assert len(d1.entries) == 1
    assert d1.entries[0].summary == d0.entries[0].summary


def test_build_chat_model_requires_api_key_when_unset() -> None:
    from ai_news_agent.llm import build_chat_model

    backup = os.environ.pop("OPENAI_API_KEY", None)
    try:
        try:
            build_chat_model()
        except ValueError as exc:
            assert "OPENAI_API_KEY" in str(exc)
        else:
            raise AssertionError("expected ValueError")
    finally:
        if backup is not None:
            os.environ["OPENAI_API_KEY"] = backup


def test_build_tool_chat_model_importable() -> None:
    from ai_news_agent.llm import build_tool_chat_model  # noqa: F401


def test_build_tool_chat_model_requires_api_key_when_unset() -> None:
    from ai_news_agent.llm import build_tool_chat_model

    backup = os.environ.pop("OPENAI_API_KEY", None)
    try:
        try:
            build_tool_chat_model()
        except ValueError as exc:
            assert "OPENAI_API_KEY" in str(exc)
        else:
            raise AssertionError("expected ValueError")
    finally:
        if backup is not None:
            os.environ["OPENAI_API_KEY"] = backup


def test_build_tool_chat_model_satisfies_tool_call_model_protocol() -> None:
    from ai_news_agent.llm import build_tool_chat_model
    from ai_news_agent.tools.agent import ToolCallModel

    result = build_tool_chat_model(api_key="fake-key-for-protocol-check")
    assert isinstance(result, ToolCallModel)
