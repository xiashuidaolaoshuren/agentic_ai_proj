"""Tests for deterministic ranking and deduplication (Milestone 1 Task 7)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.models import ConfidenceLevel, NewsItem, RankedItem, SourceKind

# Baseline contract: empty input and single candidate (TDD red batch 1).


def _fixed_ts() -> datetime:
    return datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)


def test_rank_items_empty_returns_empty_list() -> None:
    from ai_news_agent.ranking import rank_items

    assert rank_items([], top_n=5, now=_fixed_ts()) == []


def test_rank_items_single_item_is_selected_with_reason() -> None:
    from ai_news_agent.ranking import rank_items

    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="1",
        url="https://github.com/a/b",
        title="a/b",
        published_at=_fixed_ts(),
        collected_at=_fixed_ts(),
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="hello",
    )
    ranked = rank_items([item], top_n=3, now=_fixed_ts())
    assert len(ranked) == 1
    r0 = ranked[0]
    assert r0.item is item
    assert r0.selected is True
    assert r0.score_total > 0
    assert r0.selection_reason
    assert isinstance(r0.score_breakdown, dict)
    assert r0.score_breakdown


def test_fresher_candidate_outranks_stale() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    stale = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s1",
        url="https://github.com/o/s1",
        title="stale",
        published_at=now - timedelta(days=60),
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    fresh = NewsItem(
        source=SourceKind.GITHUB,
        source_id="s2",
        url="https://github.com/o/s2",
        title="fresh",
        published_at=now - timedelta(days=1),
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    ranked = rank_items([stale, fresh], top_n=5, now=now)
    assert ranked[0].item.source_id == "s2"


def test_topic_matches_increase_relevance_component() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    base = dict(
        source=SourceKind.GITHUB,
        url="https://github.com/x/1",
        title="t1",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.5,
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=10,
        raw_snippet="d",
    )
    no_topics = NewsItem(source_id="a", topic_matches=[], **base)
    with_topics = NewsItem(source_id="b", topic_matches=["AI", "LLM"], **base)
    ra = rank_items([no_topics], top_n=1, now=now)[0]
    rb = rank_items([with_topics], top_n=1, now=now)[0]
    assert rb.score_breakdown["relevance"] > ra.score_breakdown["relevance"]


def test_low_confidence_reduces_score_vs_medium() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    kwargs = dict(
        source=SourceKind.GITHUB,
        url="https://github.com/x/1",
        title="t",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.6,
        topic_matches=["x"],
        stars_or_views=5,
        raw_snippet="d",
    )
    low = NewsItem(source_id="l", content_confidence=ConfidenceLevel.LOW, **kwargs)
    med = NewsItem(source_id="m", content_confidence=ConfidenceLevel.MEDIUM, **kwargs)
    rl = rank_items([low], top_n=1, now=now)[0]
    rm = rank_items([med], top_n=1, now=now)[0]
    assert rl.score_total < rm.score_total


def test_rank_items_juya_uses_bulletin_source_quality() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    shared = dict(
        published_at=now,
        collected_at=now,
        metadata_completeness=0.75,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        raw_snippet="bulletin excerpt",
    )
    juya = NewsItem(
        source=SourceKind.JUYA,
        source_id="juya-1",
        url="https://daily.juya.uk/issue-1/",
        title="Juya issue",
        **shared,
    )
    bilibili = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVjuya1",
        url="https://www.bilibili.com/video/BVjuya1",
        title="Bilibili video",
        stars_or_views=100,
        **shared,
    )
    r_juya = rank_items([juya], top_n=1, now=now)[0]
    r_bili = rank_items([bilibili], top_n=1, now=now)[0]
    assert r_juya.score_breakdown["source_quality"] != r_bili.score_breakdown["source_quality"]
    assert "bulletin" in r_juya.score_breakdown


def test_higher_engagement_increases_engagement_component() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    kwargs = dict(
        source=SourceKind.BILIBILI,
        published_at=now,
        collected_at=now,
        metadata_completeness=0.5,
        topic_matches=["v"],
        content_confidence=ConfidenceLevel.MEDIUM,
        raw_snippet="d",
    )
    low_views = NewsItem(
        source_id="lv",
        url="https://www.bilibili.com/video/BV1lowviewsaa",
        title="low",
        stars_or_views=5,
        **kwargs,
    )
    high_views = NewsItem(
        source_id="hv",
        url="https://www.bilibili.com/video/BV1highviewss",
        title="high",
        stars_or_views=500_000,
        **kwargs,
    )
    r_lo = rank_items([low_views], top_n=1, now=now)[0]
    r_hi = rank_items([high_views], top_n=1, now=now)[0]
    assert r_hi.score_breakdown["engagement"] > r_lo.score_breakdown["engagement"]


def test_rank_items_github_momentum_stars_times_recency() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    base = dict(
        source=SourceKind.GITHUB,
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        raw_snippet="readme",
    )
    fewer_stars = NewsItem(
        source_id="gh-low",
        url="https://github.com/o/low",
        title="low stars",
        published_at=now - timedelta(days=1),
        stars_or_views=100,
        **base,
    )
    more_stars = NewsItem(
        source_id="gh-high",
        url="https://github.com/o/high",
        title="high stars",
        published_at=now - timedelta(days=1),
        stars_or_views=10_000,
        **base,
    )
    stale = NewsItem(
        source_id="gh-stale",
        url="https://github.com/o/stale",
        title="stale",
        published_at=now - timedelta(days=60),
        stars_or_views=10_000,
        **base,
    )
    fresh = NewsItem(
        source_id="gh-fresh",
        url="https://github.com/o/fresh",
        title="fresh",
        published_at=now - timedelta(days=1),
        stars_or_views=10_000,
        **base,
    )
    r_low = rank_items([fewer_stars], top_n=1, now=now)[0]
    r_high = rank_items([more_stars], top_n=1, now=now)[0]
    r_stale = rank_items([stale], top_n=1, now=now)[0]
    r_fresh = rank_items([fresh], top_n=1, now=now)[0]

    assert "momentum" in r_high.score_breakdown
    assert "stars_gained" not in r_high.score_breakdown
    assert "velocity" not in r_high.score_breakdown
    assert "engagement" not in r_high.score_breakdown
    assert r_high.score_breakdown["momentum"] > r_low.score_breakdown["momentum"]
    assert r_fresh.score_breakdown["momentum"] > r_stale.score_breakdown["momentum"]


# Deduplication and top-N (TDD red batch 3)


def test_dedupe_keeps_higher_preference_on_same_source_id() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    strong = NewsItem(
        source=SourceKind.GITHUB,
        source_id="dup",
        url="https://github.com/o/strong",
        title="strong",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.95,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    weak = NewsItem(
        source=SourceKind.GITHUB,
        source_id="dup",
        url="https://github.com/o/weak",
        title="weak title",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.2,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=100,
        raw_snippet="x",
    )
    ranked = rank_items([weak, strong], top_n=5, now=now)
    assert len(ranked) == 1
    assert ranked[0].item is strong


def test_dedupe_same_normalized_url_keeps_stronger_candidate() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    a = NewsItem(
        source=SourceKind.GITHUB,
        source_id="g1",
        url="https://github.com/a/B/",
        title="alpha",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.9,
        topic_matches=["t"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=50,
        raw_snippet="z",
    )
    b = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1xyz00001",
        url="https://github.com/a/b",
        title="beta",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.3,
        topic_matches=["t"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=50,
        raw_snippet="z",
    )
    ranked = rank_items([b, a], top_n=5, now=now)
    assert len(ranked) == 1
    assert ranked[0].item is a


def test_top_n_marks_only_first_n_selected() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    items = [
        NewsItem(
            source=SourceKind.GITHUB,
            source_id=f"id{i}",
            url=f"https://github.com/o/r{i}",
            title=f"r{i}",
            published_at=now - timedelta(days=i),
            collected_at=now,
            metadata_completeness=0.7,
            topic_matches=["AI"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=10 + i,
            raw_snippet="s",
        )
        for i in range(4)
    ]
    ranked = rank_items(items, top_n=2, now=now)
    assert len(ranked) == 4
    assert sum(1 for r in ranked if r.selected) == 2
    assert ranked[0].selected and ranked[1].selected
    assert not ranked[2].selected


def test_tie_breaker_uses_source_id_when_scores_equal() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    common = dict(
        source=SourceKind.GITHUB,
        published_at=now,
        collected_at=now,
        metadata_completeness=0.75,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=42,
        raw_snippet="body",
    )
    second = NewsItem(
        source_id="b",
        url="https://github.com/acme/b",
        title="Project B",
        **common,
    )
    first = NewsItem(
        source_id="a",
        url="https://github.com/acme/a",
        title="Project A",
        **common,
    )
    ranked = rank_items([second, first], top_n=5, now=now)
    assert ranked[0].item.source_id == "a"
    assert ranked[0].score_total == ranked[1].score_total


def test_newest_in_window_bilibili_candidate_picks_latest_publish_time() -> None:
    from datetime import timedelta

    from ai_news_agent.models import RankedItem
    from ai_news_agent.ranking import find_newest_in_window_bilibili_candidate

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    def _bili(source_id: str, *, hours_ago: int) -> RankedItem:
        item = NewsItem(
            source=SourceKind.BILIBILI,
            source_id=source_id,
            url=f"https://www.bilibili.com/video/{source_id}",
            title=source_id,
            published_at=now - timedelta(hours=hours_ago),
            collected_at=now,
            metadata_completeness=0.4,
            topic_matches=[],
            content_confidence=ConfidenceLevel.LOW,
            stars_or_views=1,
            raw_snippet="x",
        )
        return RankedItem(
            item=item,
            score_total=1.0,
            score_breakdown={},
            selected=False,
            selection_reason="",
        )

    ranked = [
        _bili("BVolder", hours_ago=48),
        _bili("BVnewest", hours_ago=2),
        RankedItem(
            item=NewsItem(
                source=SourceKind.GITHUB,
                source_id="gh1",
                url="https://github.com/o/gh1",
                title="gh1",
                published_at=now - timedelta(hours=1),
                collected_at=now,
                metadata_completeness=0.9,
                topic_matches=["AI"],
                content_confidence=ConfidenceLevel.MEDIUM,
                stars_or_views=100,
                raw_snippet="x",
            ),
            score_total=9.0,
            score_breakdown={},
            selected=True,
            selection_reason="",
        ),
    ]

    candidate = find_newest_in_window_bilibili_candidate(
        ranked,
        timeframe="last_7_days",
        now=now,
    )

    assert candidate is not None
    assert candidate.item.source_id == "BVnewest"


def test_rank_items_bilibili_guarantees_newest_in_window_when_timeframe_set() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVjune2new",
        url="https://www.bilibili.com/video/BVjune2new",
        title="June 2 newest",
        published_at=now - timedelta(hours=2),
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
            source_id=f"gh{i}",
            url=f"https://github.com/o/gh{i}",
            title=f"repo{i}",
            published_at=now - timedelta(days=i + 1),
            collected_at=now,
            metadata_completeness=0.95,
            topic_matches=["AI", "LLM"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=5000 + i,
            raw_snippet="readme body",
        )
        for i in range(6)
    ]

    ranked = rank_items(
        github_items + [bilibili_newest],
        top_n=5,
        now=now,
        timeframe="last_7_days",
    )
    selected_ids = {r.item.source_id for r in ranked if r.selected}

    assert "BVjune2new" in selected_ids
    assert len(selected_ids) == 5


def test_rank_items_without_timeframe_does_not_force_bilibili_inclusion() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVonlybili",
        url="https://www.bilibili.com/video/BVonlybili",
        title="Only bilibili",
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
            source_id=f"gh{i}",
            url=f"https://github.com/o/gh{i}",
            title=f"repo{i}",
            published_at=now - timedelta(days=i + 1),
            collected_at=now,
            metadata_completeness=0.95,
            topic_matches=["AI"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=9000 + i,
            raw_snippet="readme",
        )
        for i in range(5)
    ]

    ranked = rank_items(github_items + [bilibili_newest], top_n=5, now=now)
    selected_ids = {r.item.source_id for r in ranked if r.selected}

    assert "BVonlybili" not in selected_ids


def test_order_selected_for_digest_sections_fallback_and_primary() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import order_selected_for_digest

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    juya = RankedItem(
        item=NewsItem(
            source=SourceKind.JUYA,
            source_id="juya-1",
            url="https://daily.juya.uk/issue-1/",
            title="Juya issue",
            published_at=now - timedelta(days=1),
            collected_at=now,
            raw_snippet="bulletin",
        ),
        score_total=5.0,
        selected=True,
    )
    github = RankedItem(
        item=NewsItem(
            source=SourceKind.GITHUB,
            source_id="gh-1",
            url="https://github.com/o/repo",
            title="GitHub repo",
            published_at=now - timedelta(days=2),
            collected_at=now,
            raw_snippet="readme",
        ),
        score_total=9.0,
        selected=True,
    )
    bili_older = RankedItem(
        item=NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BVold",
            url="https://www.bilibili.com/video/BVold",
            title="Older Bilibili",
            published_at=now - timedelta(days=3),
            collected_at=now,
            raw_snippet="old",
        ),
        score_total=3.0,
        selected=True,
    )
    bili_newest = RankedItem(
        item=NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BVnew",
            url="https://www.bilibili.com/video/BVnew",
            title="Newest Bilibili",
            published_at=now - timedelta(hours=2),
            collected_at=now,
            raw_snippet="new",
        ),
        score_total=1.0,
        selected=True,
    )
    ranked = [github, bili_newest, juya, bili_older]

    fallback = order_selected_for_digest(
        ranked,
        timeframe="last_7_days",
        now=now,
        primary_source=None,
    )
    assert [r.item.source.value for r in fallback] == ["juya", "github", "bilibili", "bilibili"]
    assert fallback[2].item.source_id == "BVnew"
    assert fallback[3].item.source_id == "BVold"

    primary_github = order_selected_for_digest(
        ranked,
        timeframe="last_7_days",
        now=now,
        primary_source="github",
    )
    assert [r.item.source.value for r in primary_github] == [
        "github",
        "juya",
        "bilibili",
        "bilibili",
    ]

    github_only = order_selected_for_digest(
        [github],
        timeframe="last_7_days",
        now=now,
        primary_source=None,
    )
    assert [r.item.source_id for r in github_only] == ["gh-1"]


def test_order_selected_for_digest_includes_huggingface_and_zhihu_sections() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import order_selected_for_digest

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    juya = RankedItem(
        item=NewsItem(
            source=SourceKind.JUYA,
            source_id="juya-1",
            url="https://daily.juya.uk/issue-1/",
            title="Juya issue",
            published_at=now - timedelta(days=1),
            collected_at=now,
            raw_snippet="bulletin",
        ),
        score_total=5.0,
        selected=True,
    )
    huggingface = RankedItem(
        item=NewsItem(
            source=SourceKind.HUGGINGFACE,
            source_id="hf-1",
            url="https://huggingface.co/models/hf-1",
            title="HF model",
            published_at=now - timedelta(days=1),
            collected_at=now,
            raw_snippet="model card",
        ),
        score_total=8.0,
        selected=True,
    )
    github = RankedItem(
        item=NewsItem(
            source=SourceKind.GITHUB,
            source_id="gh-1",
            url="https://github.com/o/repo",
            title="GitHub repo",
            published_at=now - timedelta(days=2),
            collected_at=now,
            raw_snippet="readme",
        ),
        score_total=9.0,
        selected=True,
    )
    zhihu = RankedItem(
        item=NewsItem(
            source=SourceKind.ZHIHU,
            source_id="zh-1",
            url="https://www.zhihu.com/question/1",
            title="Zhihu post",
            published_at=now - timedelta(days=1),
            collected_at=now,
            raw_snippet="insight",
        ),
        score_total=6.0,
        selected=True,
    )
    bili = RankedItem(
        item=NewsItem(
            source=SourceKind.BILIBILI,
            source_id="BV1",
            url="https://www.bilibili.com/video/BV1",
            title="Bilibili video",
            published_at=now - timedelta(hours=2),
            collected_at=now,
            raw_snippet="video",
        ),
        score_total=3.0,
        selected=True,
    )
    ranked = [github, zhihu, bili, huggingface, juya]

    fallback = order_selected_for_digest(
        ranked,
        timeframe="last_7_days",
        now=now,
        primary_source=None,
    )
    assert [r.item.source.value for r in fallback] == [
        "juya",
        "huggingface",
        "github",
        "zhihu",
        "bilibili",
    ]

    primary_hf = order_selected_for_digest(
        ranked,
        timeframe="last_7_days",
        now=now,
        primary_source="huggingface",
    )
    assert primary_hf[0].item.source is SourceKind.HUGGINGFACE

    without_zhihu = order_selected_for_digest(
        [juya, huggingface, github, bili],
        timeframe="last_7_days",
        now=now,
        primary_source=None,
    )
    assert all(r.item.source is not SourceKind.ZHIHU for r in without_zhihu)


def _hf_item(
    *,
    source_id: str = "hf-1",
    trending_score: float = 100.0,
    stars_or_views: int | None = None,
    **extra_evidence: float,
) -> NewsItem:
    now = _fixed_ts()
    evidence: dict[str, float | int] = {"trending_score": trending_score, **extra_evidence}
    return NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id=source_id,
        url=f"https://huggingface.co/models/{source_id}",
        title=f"Model {source_id}",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.8,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=stars_or_views,
        raw_snippet="model card excerpt",
        source_evidence=evidence,
    )


def test_rank_items_huggingface_uses_trending_not_engagement() -> None:
    from ai_news_agent.ranking import rank_items

    item = _hf_item(trending_score=500.0)
    ranked = rank_items([item], top_n=1, now=_fixed_ts())[0]
    bd = ranked.score_breakdown

    assert "trending" in bd
    assert "engagement" not in bd
    assert bd["trending"] > 0


def test_rank_items_huggingface_higher_trending_score_increases_trending() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    low = _hf_item(source_id="hf-low", trending_score=10.0)
    high = _hf_item(source_id="hf-high", trending_score=10_000.0)
    r_low = rank_items([low], top_n=1, now=now)[0]
    r_high = rank_items([high], top_n=1, now=now)[0]

    assert r_high.score_breakdown["trending"] > r_low.score_breakdown["trending"]


def test_rank_items_huggingface_stars_or_views_does_not_affect_total() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    no_stars = _hf_item(source_id="hf-a", trending_score=250.0, stars_or_views=None)
    with_stars = _hf_item(source_id="hf-b", trending_score=250.0, stars_or_views=999_999)
    r_no = rank_items([no_stars], top_n=1, now=now)[0]
    r_with = rank_items([with_stars], top_n=1, now=now)[0]

    assert r_no.score_total == r_with.score_total


def _zhihu_item(
    *,
    source_id: str = "zh-1",
    relevance: float = 0.7,
    query_lens: str | None = "practitioner",
    evidence_text_length: int = 200,
) -> NewsItem:
    now = _fixed_ts()
    return NewsItem(
        source=SourceKind.ZHIHU,
        source_id=source_id,
        url=f"https://www.zhihu.com/question/{source_id}",
        title=f"Zhihu post {source_id}",
        published_at=now,
        collected_at=now,
        metadata_completeness=0.75,
        topic_matches=["AI"],
        content_confidence=ConfidenceLevel.MEDIUM,
        stars_or_views=None,
        raw_snippet="practitioner insight excerpt",
        source_evidence={
            "relevance": relevance,
            "query_lens": query_lens,
            "evidence_text_length": evidence_text_length,
        },
    )


def test_rank_items_zhihu_uses_api_relevance_lens_and_completeness() -> None:
    from ai_news_agent.ranking import rank_items

    item = _zhihu_item()
    ranked = rank_items([item], top_n=1, now=_fixed_ts())[0]
    bd = ranked.score_breakdown

    assert "api_relevance" in bd
    assert "lens_match" in bd
    assert "text_completeness" in bd
    assert "engagement" not in bd
    assert "freshness" not in bd


def test_rank_items_zhihu_higher_api_relevance_increases_api_relevance() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    low = _zhihu_item(source_id="zh-low", relevance=0.2)
    high = _zhihu_item(source_id="zh-high", relevance=0.95)
    r_low = rank_items([low], top_n=1, now=now)[0]
    r_high = rank_items([high], top_n=1, now=now)[0]

    assert r_high.score_breakdown["api_relevance"] > r_low.score_breakdown["api_relevance"]


def test_rank_items_zhihu_longer_evidence_increases_text_completeness() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    thin = _zhihu_item(source_id="zh-thin", evidence_text_length=40)
    rich = _zhihu_item(source_id="zh-rich", evidence_text_length=500)
    r_thin = rank_items([thin], top_n=1, now=now)[0]
    r_rich = rank_items([rich], top_n=1, now=now)[0]

    assert r_rich.score_breakdown["text_completeness"] > r_thin.score_breakdown["text_completeness"]


def _mixed_juya_huggingface_pool(now: datetime) -> list[NewsItem]:
    from datetime import timedelta

    juya_items = [
        NewsItem(
            source=SourceKind.JUYA,
            source_id=f"juya-{i}",
            url=f"https://daily.juya.uk/{i}",
            title=f"Juya {i}",
            published_at=now - timedelta(hours=i),
            collected_at=now,
            metadata_completeness=0.9,
            topic_matches=["AI", "LLM"],
            content_confidence=ConfidenceLevel.MEDIUM,
            raw_snippet="bulletin text here",
        )
        for i in range(4)
    ]
    hf_items = [
        NewsItem(
            source=SourceKind.HUGGINGFACE,
            source_id=f"hf-{i}",
            url=f"https://huggingface.co/m{i}",
            title=f"HF model {i}",
            collected_at=now,
            metadata_completeness=0.5,
            topic_matches=[],
            content_confidence=ConfidenceLevel.MEDIUM,
            source_evidence={"trending_score": max(1, 10 - i)},
        )
        for i in range(4)
    ]
    return juya_items + hf_items


def test_rank_items_items_per_source_selects_n_per_kind_mixed_juya_huggingface() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    ranked = rank_items(
        _mixed_juya_huggingface_pool(now),
        top_n=2,
        items_per_source=2,
        now=now,
    )
    selected = [r for r in ranked if r.selected]
    by_kind: dict[SourceKind, list[RankedItem]] = {}
    for row in selected:
        by_kind.setdefault(row.item.source, []).append(row)

    assert len(by_kind.get(SourceKind.JUYA, [])) == 2
    assert len(by_kind.get(SourceKind.HUGGINGFACE, [])) == 2
    assert len(selected) == 4


def test_rank_items_items_per_source_none_keeps_overall_top_n() -> None:
    from ai_news_agent.ranking import rank_items

    now = _fixed_ts()
    ranked = rank_items(
        _mixed_juya_huggingface_pool(now),
        top_n=2,
        items_per_source=None,
        now=now,
    )

    assert sum(1 for r in ranked if r.selected) == 2


def test_rank_items_items_per_source_bilibili_guarantee_stays_within_quota() -> None:
    from datetime import timedelta

    from ai_news_agent.ranking import rank_items

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bilibili_newest = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BVjune2new",
        url="https://www.bilibili.com/video/BVjune2new",
        title="June 2 newest",
        published_at=now - timedelta(hours=2),
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
            source_id=f"gh{i}",
            url=f"https://github.com/o/gh{i}",
            title=f"repo{i}",
            published_at=now - timedelta(days=i + 1),
            collected_at=now,
            metadata_completeness=0.95,
            topic_matches=["AI", "LLM"],
            content_confidence=ConfidenceLevel.MEDIUM,
            stars_or_views=5000 + i,
            raw_snippet="readme body",
        )
        for i in range(4)
    ]

    ranked = rank_items(
        github_items + [bilibili_newest],
        top_n=5,
        items_per_source=2,
        now=now,
        timeframe="last_7_days",
    )
    selected = [r for r in ranked if r.selected]
    github_selected = [r for r in selected if r.item.source is SourceKind.GITHUB]
    bilibili_selected = [r for r in selected if r.item.source is SourceKind.BILIBILI]

    assert len(github_selected) == 2
    assert len(bilibili_selected) == 1
    assert bilibili_selected[0].item.source_id == "BVjune2new"
    assert len(selected) == 3
