"""Tests for persist-only history show (Milestone 7D T5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_agent.connectors.base import ConnectorResult
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


def _seed_single_github_digest(store: DigestStore) -> int:
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        collected_at=_FIXTURE_DT,
        content_confidence=ConfidenceLevel.HIGH,
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="a/b",
        source_name="GitHub",
        source_url=item.url,
        summary="Summary",
        why_it_matters="Why",
        background_knowledge="Background",
        follow_up_action=FollowUpAction.READ,
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
        [RankedItem(item=item, score_total=1.0, selected=True, selection_reason="best")],
    )
    return store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["RAG"],
            timeframe="today",
        ),
    )


def test_show_historical_item_not_found_cases(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "notfound.db")
    store.init_schema()
    digest_id = _seed_single_github_digest(store)
    from ai_news_agent.history_search import show_historical_item

    assert show_historical_item(store, "bad-token") is None
    assert show_historical_item(store, "d9999:r1") is None
    assert show_historical_item(store, f"d{digest_id}:r2") is None

    r1_card = "Digest item 1: a/b"
    out = show_historical_item(store, f"d{digest_id}:r2")
    assert out is None
    assert out != r1_card


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _juya_backup_snippet() -> str:
    from ai_news_agent.connectors.juya import clean_backup_markdown

    raw = (FIXTURES / "juya_backup_2026-06-16_sample.md").read_text(encoding="utf-8")
    return clean_backup_markdown(raw)


def _seed_digest(
    store: DigestStore,
    *,
    generated_at: datetime,
    entries: list[DigestEntry],
    news_items: list[NewsItem],
    topics: list[str] | None = None,
) -> int:
    run_id = store.save_run(
        requested_at=generated_at,
        timeframe="today",
        topics=topics or ["AI"],
        connector_names=sorted({item.source.value for item in news_items}),
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=news_items, warnings=[], raw_count=len(news_items)),
    )
    store.save_ranked_items(
        run_id,
        [
            RankedItem(item=item, score_total=1.0, selected=True, selection_reason="best")
            for item in news_items
        ],
    )
    return store.save_digest(
        run_id,
        Digest(
            generated_at=generated_at,
            entries=entries,
            topics=topics or ["AI"],
            timeframe="today",
        ),
    )


def _seed_hf_digest(store: DigestStore, *, include_news_item: bool = True) -> int:
    source_id = "Qwen/Qwen3.8-27B"
    entry = DigestEntry(
        source_kind=SourceKind.HUGGINGFACE,
        source_id=source_id,
        title="Qwen3.8-27B",
        source_name="Hugging Face",
        source_url=f"https://huggingface.co/{source_id}",
        summary="HF summary.",
        why_it_matters="Why HF.",
        background_knowledge="BG HF.",
        follow_up_action=FollowUpAction.READ,
    )
    items: list[NewsItem] = []
    if include_news_item:
        items.append(
            NewsItem(
                source=SourceKind.HUGGINGFACE,
                source_id=source_id,
                url=f"https://huggingface.co/{source_id}",
                title="Qwen3.8-27B",
                collected_at=_FIXTURE_DT,
                raw_snippet="Small and fast.",
                content_confidence=ConfidenceLevel.HIGH,
                source_evidence={
                    "trending_score": 88.0,
                    "downloads_30d": 1200,
                    "likes": 42,
                    "pipeline_tag": "text-generation",
                },
            )
        )
    return _seed_digest(store, generated_at=_FIXTURE_DT, entries=[entry], news_items=items)


def _seed_zhihu_digest(store: DigestStore) -> int:
    entry = DigestEntry(
        source_kind=SourceKind.ZHIHU,
        source_id="zh-1",
        title="RAG 部署踩坑",
        source_name="Zhihu",
        source_url="https://www.zhihu.com/question/zh-1",
        summary="Zhihu summary.",
        why_it_matters="Why Zhihu.",
        background_knowledge="BG Zhihu.",
        follow_up_action=FollowUpAction.READ,
    )
    item = NewsItem(
        source=SourceKind.ZHIHU,
        source_id="zh-1",
        url="https://www.zhihu.com/question/zh-1",
        title="RAG 部署踩坑",
        collected_at=_FIXTURE_DT,
        author="实践者A",
        raw_snippet="部署时要小心显存。",
        content_confidence=ConfidenceLevel.MEDIUM,
        source_evidence={
            "relevance": 0.92,
            "query_lens": "实战 / 踩坑",
            "source_label": "回答",
        },
    )
    return _seed_digest(store, generated_at=_FIXTURE_DT, entries=[entry], news_items=[item])


def _seed_juya_digest(store: DigestStore) -> int:
    snippet = _juya_backup_snippet()
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="juya-rss-issue5",
        url="https://daily.juya.uk/issue-5/",
        title="2026-06-16",
        collected_at=_FIXTURE_DT,
        raw_snippet=snippet,
        tags=["github", "juya-daily", "juya-backup"],
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
    return _seed_digest(store, generated_at=_FIXTURE_DT, entries=[entry], news_items=[item])


def _seed_bilibili_digest(store: DigestStore) -> int:
    item = NewsItem(
        source=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        url="https://www.bilibili.com/video/BV1demo00001",
        title="Bilibili video",
        collected_at=_FIXTURE_DT,
        author="Uploader",
        raw_snippet="thin search description",
        tags=["bilibili", "video"],
        content_confidence=ConfidenceLevel.LOW,
    )
    entry = DigestEntry(
        source_kind=SourceKind.BILIBILI,
        source_id="BV1demo00001",
        title="Bilibili video",
        source_name="Bilibili",
        source_url=item.url,
        summary="S",
        why_it_matters="W",
        background_knowledge="B",
        follow_up_action=FollowUpAction.WATCH,
    )
    return _seed_digest(store, generated_at=_FIXTURE_DT, entries=[entry], news_items=[item])


def test_show_historical_item_matches_format_rank_item(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "format-parity.db")
    store.init_schema()
    digest_id = _seed_single_github_digest(store)
    ctx = store.get_followup_context_for_digest(digest_id)
    from ai_news_agent.followup_structured import format_rank_item
    from ai_news_agent.history_search import show_historical_item

    expected = format_rank_item(ctx, 1)
    assert show_historical_item(store, f"d{digest_id}:r1") == expected


def test_show_historical_item_juya_card(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "juya.db")
    store.init_schema()
    digest_id = _seed_juya_digest(store)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert "第 1 条" in out
    assert "来源" in out
    assert "Digest item 1:" not in out


def test_show_historical_item_hf_card(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "hf.db")
    store.init_schema()
    digest_id = _seed_hf_digest(store)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert "Rank 1" in out
    assert "Trending —" in out
    assert "Digest item 1:" not in out


def test_show_historical_item_zhihu_card(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "zhihu.db")
    store.init_schema()
    digest_id = _seed_zhihu_digest(store)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert "第 1 条" in out
    assert "链接" in out
    assert "Digest item 1:" not in out


def test_show_historical_item_github_generic(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "github.db")
    store.init_schema()
    digest_id = _seed_single_github_digest(store)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert out.startswith("Digest item 1: a/b")


def test_show_historical_item_bilibili_generic(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "bilibili.db")
    store.init_schema()
    digest_id = _seed_bilibili_digest(store)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert out.startswith("Digest item 1: Bilibili video")


def test_show_historical_item_hf_degraded_missing_news_item(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "hf-degraded.db")
    store.init_schema()
    digest_id = _seed_hf_digest(store, include_news_item=False)
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert "Rank 1" in out
    assert "not available" in out
    assert "Digest item 1:" not in out


def test_show_historical_item_does_not_change_latest_context(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "latest.db")
    store.init_schema()
    older_id = _seed_single_github_digest(store)
    newer_id = _seed_digest(
        store,
        generated_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="repo-new",
                title="newest/repo",
                source_name="GitHub",
                source_url="https://github.com/newest/repo",
                summary="New summary",
                why_it_matters="New why",
                background_knowledge="New bg",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        news_items=[
            NewsItem(
                source=SourceKind.GITHUB,
                source_id="repo-new",
                url="https://github.com/newest/repo",
                title="newest/repo",
                collected_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
                content_confidence=ConfidenceLevel.HIGH,
            )
        ],
    )
    from ai_news_agent.history_search import show_historical_item

    out = show_historical_item(store, f"d{older_id}:r1")
    assert out is not None
    assert "a/b" in out
    latest = store.get_latest_followup_context()
    assert latest.digest is not None
    assert latest.digest.entries[0].title == "newest/repo"
    assert newer_id > older_id


def test_show_historical_item_no_live_enrich_or_store_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DigestStore(tmp_path / "no-enrich.db")
    store.init_schema()
    digest_id = _seed_hf_digest(store)

    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("live enrich or store write must not run on history show")

    import ai_news_agent.followup_enrich as followup_enrich
    import ai_news_agent.followup_structured as followup_structured
    import ai_news_agent.history_search as history_search

    monkeypatch.setattr(followup_enrich, "enrich_huggingface_for_rank", _fail)
    monkeypatch.setattr(followup_structured, "answer_structured_followup_live", _fail)
    monkeypatch.setattr(store, "save_run", _fail)
    monkeypatch.setattr(store, "save_digest", _fail)
    monkeypatch.setattr(store, "save_connector_result", _fail)
    monkeypatch.setattr(store, "save_ranked_items", _fail)

    out = history_search.show_historical_item(store, f"d{digest_id}:r1")
    assert out is not None
    assert "Rank 1" in out
    assert "Trending —" in out
