"""Tests for rank deep-dive dispatch in format_rank_item."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.followup_structured import format_rank_item
from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore

_FIXTURE_DT = datetime(2026, 5, 7, 10, 0, tzinfo=UTC)


def _hf_entry(
    *,
    title: str = "Qwen3.8-27B",
    source_id: str = "Qwen/Qwen3.8-27B",
) -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.HUGGINGFACE,
        source_id=source_id,
        title=title,
        source_name="Hugging Face",
        source_url=f"https://huggingface.co/{source_id}",
        summary="HF summary.",
        why_it_matters="Why HF.",
        background_knowledge="BG HF.",
        follow_up_action=FollowUpAction.READ,
    )


def _hf_news_item(
    *,
    source_id: str = "Qwen/Qwen3.8-27B",
    title: str = "Qwen3.8-27B",
    author: str | None = None,
    raw_snippet: str | None = None,
    source_evidence: dict[str, object] | None = None,
) -> NewsItem:
    return NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id=source_id,
        url=f"https://huggingface.co/{source_id}",
        title=title,
        collected_at=_FIXTURE_DT,
        author=author,
        raw_snippet=raw_snippet,
        content_confidence=ConfidenceLevel.HIGH,
        source_evidence=source_evidence or {},
    )


def _seed_hf_digest_store(store: DigestStore) -> int:
    item = _hf_news_item(
        raw_snippet="Small and fast.",
        source_evidence={
            "trending_score": 88.0,
            "downloads_30d": 1200,
            "likes": 42,
            "pipeline_tag": "text-generation",
        },
    )
    entry = _hf_entry()
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["huggingface"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=4.0, selected=True)],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["AI"],
            timeframe="today",
        ),
    )
    return run_id


def test_rank_deep_dive_hf_dispatches_family_card(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "hf-dispatch.db")
    store.init_schema()
    _seed_hf_digest_store(store)
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert "Rank 1" in out
    assert "Qwen3.8-27B" in out
    assert "https://huggingface.co/Qwen/Qwen3.8-27B" in out
    assert "Trending:" in out
    assert "Digest item 1:" not in out


def test_rank_deep_dive_hf_degraded_missing_news_item(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "hf-degraded.db")
    store.init_schema()
    entry = _hf_entry()
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["huggingface"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["AI"],
            timeframe="today",
        ),
    )
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert "Rank 1" in out
    assert "Qwen3.8-27B" in out
    assert "https://huggingface.co/Qwen/Qwen3.8-27B" in out
    assert "not available" in out
    assert "Digest item 1:" not in out
    assert "1200" not in out
    assert "88" not in out


def _zh_entry(
    *,
    title: str = "RAG 部署踩坑",
    source_id: str = "zh-1",
    summary: str = "Zhihu summary.",
    why_it_matters: str = "Why Zhihu.",
) -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.ZHIHU,
        source_id=source_id,
        title=title,
        source_name="Zhihu",
        source_url=f"https://www.zhihu.com/question/{source_id}",
        summary=summary,
        why_it_matters=why_it_matters,
        background_knowledge="BG Zhihu.",
        follow_up_action=FollowUpAction.READ,
    )


def _zh_news_item(
    *,
    source_id: str = "zh-1",
    title: str = "RAG 部署踩坑",
    author: str | None = None,
    raw_snippet: str | None = None,
    source_evidence: dict[str, object] | None = None,
) -> NewsItem:
    return NewsItem(
        source=SourceKind.ZHIHU,
        source_id=source_id,
        url=f"https://www.zhihu.com/question/{source_id}",
        title=title,
        collected_at=_FIXTURE_DT,
        author=author,
        raw_snippet=raw_snippet,
        content_confidence=ConfidenceLevel.MEDIUM,
        source_evidence=source_evidence or {},
    )


def _seed_zhihu_digest_store(store: DigestStore) -> int:
    item = _zh_news_item(
        author="实践者A",
        raw_snippet="部署时要小心显存。",
        source_evidence={
            "relevance": 0.92,
            "query_lens": "实战 / 踩坑",
            "source_label": "回答",
        },
    )
    entry = _zh_entry()
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["zhihu"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=4.0, selected=True)],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["AI"],
            timeframe="today",
        ),
    )
    return run_id


def test_rank_deep_dive_zhihu_dispatches_insight_card(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "zh-dispatch.db")
    store.init_schema()
    _seed_zhihu_digest_store(store)
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert "第 1 条" in out
    assert "RAG 部署踩坑" in out
    assert "https://www.zhihu.com/question/zh-1" in out
    assert "原文摘录" in out
    assert "Digest item 1:" not in out


def test_rank_deep_dive_zhihu_degraded_missing_news_item(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "zh-degraded.db")
    store.init_schema()
    entry = _zh_entry()
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["zhihu"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["AI"],
            timeframe="today",
        ),
    )
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert "第 1 条" in out
    assert "RAG 部署踩坑" in out
    assert "https://www.zhihu.com/question/zh-1" in out
    assert "证据" in out or "摘要深度" in out
    assert "Digest item 1:" not in out
    assert "0.92" not in out


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _juya_backup_snippet() -> str:
    from ai_news_agent.connectors.juya import clean_backup_markdown

    raw = (FIXTURES / "juya_backup_2026-06-16_sample.md").read_text(encoding="utf-8")
    return clean_backup_markdown(raw)


def _juya_news_item(*, source_id: str, title: str, url: str, snippet: str) -> NewsItem:
    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=url,
        title=title,
        collected_at=_FIXTURE_DT,
        raw_snippet=snippet,
        tags=["github", "juya-daily", "juya-backup"],
    )


def _seed_juya_digest_store(store: DigestStore) -> int:
    snippet = _juya_backup_snippet()
    item = _juya_news_item(
        source_id="juya-rss-issue5",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet=snippet,
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="juya-rss-issue5",
        title="2026-06-16",
        source_name="jujuyaya",
        source_url=item.url,
        summary="SpaceX 收购 Cursor；智谱 GLM-5.2 开源",
        why_it_matters="模型发布与行业动态",
        background_knowledge="",
        follow_up_action=FollowUpAction.READ,
    )
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=0.95, selected=True)],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["AI"],
            timeframe="today",
        ),
    )
    return run_id


def test_rank_deep_dive_juya_heuristic_wins(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "juya-wins.db")
    store.init_schema()
    _seed_juya_digest_store(store)
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert "第 1 条" in out
    assert "daily.juya.uk/issue-5" in out
    assert "GLM-5.2" in out or "SpaceX" in out
    assert "Digest item 1:" not in out
    assert "Rank 1" not in out


def _seed_github_digest_store(store: DigestStore) -> int:
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        collected_at=_FIXTURE_DT,
        author="alice",
        raw_snippet="desc",
        content_confidence=ConfidenceLevel.HIGH,
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="a/b",
        source_name="GitHub",
        source_url=item.url,
        summary="S",
        why_it_matters="W",
        background_knowledge="B",
        follow_up_action=FollowUpAction.READ,
        confidence_caveat="caveat",
    )
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=4.2, selected=True, selection_reason="best")],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["RAG"],
            timeframe="today",
        ),
    )
    return run_id


def test_rank_deep_dive_github_generic_unchanged(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "github-generic.db")
    store.init_schema()
    _seed_github_digest_store(store)
    ctx = store.get_latest_followup_context()
    out = format_rank_item(ctx, 1)
    assert out == (
        "Digest item 1: a/b\n"
        "- URL: https://github.com/a/b\n"
        "- Summary: S\n"
        "- Why it matters: W\n"
        "- Confidence caveat: caveat"
    )


def _seed_mixed_digest_store(store: DigestStore) -> int:
    juya_item = _juya_news_item(
        source_id="juya-rss-mixed",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-mixed/",
        snippet=_juya_backup_snippet(),
    )
    hf_item = _hf_news_item(
        source_id="Qwen/Qwen3.8-27B",
        title="Qwen3.8-27B",
        raw_snippet="Small and fast.",
        source_evidence={
            "trending_score": 88.0,
            "downloads_30d": 1200,
            "likes": 42,
            "pipeline_tag": "text-generation",
        },
    )
    gh_item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="gh-mixed-1",
        url="https://github.com/o/repo",
        title="GitHub repo",
        collected_at=_FIXTURE_DT,
        raw_snippet="readme",
        content_confidence=ConfidenceLevel.HIGH,
    )
    zh_item = _zh_news_item(
        source_id="zh-mixed-1",
        title="Zhihu post",
        author="实践者A",
        raw_snippet="部署时要小心显存。",
        source_evidence={
            "relevance": 0.92,
            "query_lens": "实战 / 踩坑",
            "source_label": "回答",
        },
    )
    entries = [
        DigestEntry(
            source_kind=SourceKind.GITHUB,
            source_id="juya-rss-mixed",
            title="2026-06-16",
            source_name="jujuyaya",
            source_url=juya_item.url,
            summary="Juya summary",
            why_it_matters="Juya why",
            background_knowledge="",
            follow_up_action=FollowUpAction.READ,
        ),
        _hf_entry(title="Qwen3.8-27B", source_id="Qwen/Qwen3.8-27B"),
        DigestEntry(
            source_kind=SourceKind.GITHUB,
            source_id="gh-mixed-1",
            title="GitHub repo",
            source_name="GitHub",
            source_url=gh_item.url,
            summary="GH summary",
            why_it_matters="GH why",
            background_knowledge="",
            follow_up_action=FollowUpAction.READ,
        ),
        _zh_entry(title="Zhihu post", source_id="zh-mixed-1"),
    ]
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["AI"],
        connector_names=["github", "huggingface", "zhihu"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=[juya_item, hf_item, gh_item, zh_item], warnings=[]),
    )
    store.save_ranked_items(
        run_id,
        [
            RankedItem(item=juya_item, score_total=5.0, selected=True),
            RankedItem(item=hf_item, score_total=8.0, selected=True),
            RankedItem(item=gh_item, score_total=9.0, selected=True),
            RankedItem(item=zh_item, score_total=6.0, selected=True),
        ],
    )
    store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=entries,
            topics=["AI"],
            timeframe="today",
        ),
    )
    return run_id


def test_rank_deep_dive_mixed_digest_display_rank(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "mixed-rank.db")
    store.init_schema()
    _seed_mixed_digest_store(store)
    ctx = store.get_latest_followup_context()
    hf_out = format_rank_item(ctx, 2)
    zh_out = format_rank_item(ctx, 4)
    assert "Rank 2" in hf_out
    assert "Qwen3.8-27B" in hf_out
    assert "Digest item 2:" not in hf_out
    assert "第 4 条" in zh_out
    assert "Zhihu post" in zh_out
    assert "Digest item 4:" not in zh_out


