"""Tests for Juya issue deep-dive follow-up and sub-news extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.connectors.juya import clean_backup_markdown
from ai_news_agent.followup_structured import (
    answer_structured_followup,
    parse_rank_from_message,
)
from ai_news_agent.juya_followup import (
    format_juya_issue_deep_dive,
    is_juya_news_item,
    match_news_item_for_digest_entry,
    parse_juya_sub_news,
)
from ai_news_agent.models import (
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.rendering import render_digest_editorial_text
from ai_news_agent.storage import DigestStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _juya_backup_snippet() -> str:
    raw = (FIXTURES / "juya_backup_2026-06-16_sample.md").read_text(encoding="utf-8")
    return clean_backup_markdown(raw)


def _juya_news_item(*, source_id: str, title: str, url: str, snippet: str) -> NewsItem:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=url,
        title=title,
        collected_at=now,
        raw_snippet=snippet,
        tags=["github", "juya-daily", "juya-backup"],
    )


def test_parse_rank_from_message_digest_the_first_news() -> None:
    assert parse_rank_from_message("Digest the first news") == 1
    assert parse_rank_from_message("the first news") == 1
    assert parse_rank_from_message("first juya news") == 1


def test_parse_juya_sub_news_extracts_multiple_items() -> None:
    items = parse_juya_sub_news(_juya_backup_snippet())
    titles = " ".join(item.title for item in items)
    assert "GLM-5.2" in titles or any("GLM" in i.title for i in items)
    assert "SpaceX" in titles or any("SpaceX" in i.title for i in items)
    assert len(items) >= 3


def test_is_juya_news_item_detects_tags_and_url() -> None:
    item = _juya_news_item(
        source_id="juya-rss-1",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet="x",
    )
    assert is_juya_news_item(item) is True


def test_is_juya_news_item_prefers_source_kind_juya() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.JUYA,
        source_id="other-source-1",
        url="https://example.com/not-juya",
        title="2026-06-16",
        collected_at=now,
        raw_snippet="x",
        tags=[],
    )
    assert is_juya_news_item(item) is True


def test_is_juya_news_item_keeps_historical_github_tagged_rows() -> None:
    item = _juya_news_item(
        source_id="juya-rss-historical",
        title="2026-06-16",
        url="https://example.com/not-juya",
        snippet="x",
    )
    assert item.source is SourceKind.GITHUB
    assert is_juya_news_item(item) is True


def test_format_juya_issue_deep_dive_lists_sub_news() -> None:
    item = _juya_news_item(
        source_id="juya-rss-1",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet=_juya_backup_snippet(),
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="juya-rss-1",
        title="2026-06-16",
        source_name="GitHub",
        source_url=item.url,
        summary="橘鸦早报摘要",
        why_it_matters="模型与产品动态",
        background_knowledge="",
        follow_up_action=FollowUpAction.READ,
    )
    out = format_juya_issue_deep_dive(entry, item, rank=1)
    assert "第 1 条" in out
    assert "daily.juya.uk/issue-5" in out
    assert "🔖 要闻" in out or "🔖 今日要闻" in out
    assert "🧠 模型发布" in out
    assert "#1 " in out
    assert "GLM-5.2" in out or "SpaceX" in out


def test_format_juya_issue_deep_dive_uses_global_numbering_across_sections() -> None:
    item = _juya_news_item(
        source_id="juya-rss-1",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet=_juya_backup_snippet(),
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="juya-rss-1",
        title="2026-06-16",
        source_name="GitHub",
        source_url=item.url,
        summary="橘鸦早报摘要",
        why_it_matters="模型与产品动态",
        background_knowledge="",
        follow_up_action=FollowUpAction.READ,
    )
    out = format_juya_issue_deep_dive(entry, item, rank=1)
    first_hash = out.find("#1 ")
    second_hash = out.find("#2 ")
    model_section = out.find("🧠 模型发布")
    assert first_hash != -1 and second_hash != -1
    assert first_hash < model_section < second_hash


def _seed_juya_digest_store(store: DigestStore) -> int:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    snippet = _juya_backup_snippet()
    item = _juya_news_item(
        source_id="juya-rss-issue5",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet=snippet,
    )
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="juya-rss-issue5",
                title="2026-06-16",
                source_name="jujuyaya",
                source_url=item.url,
                summary="SpaceX 收购 Cursor；智谱 GLM-5.2 开源",
                why_it_matters="模型发布与行业动态",
                background_knowledge="",
                follow_up_action=FollowUpAction.READ,
            ),
        ],
        topics=["AI"],
        timeframe="today",
    )
    run_id = store.save_run(
        requested_at=now,
        timeframe="today",
        topics=["AI"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=0.95, selected=True)],
    )
    store.save_digest(run_id, digest)
    return run_id


def test_answer_structured_followup_juya_deep_dive_item_one(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "juya.db")
    store.init_schema()
    _seed_juya_digest_store(store)
    ctx = store.get_latest_followup_context()
    reply = answer_structured_followup("follow up on item 1", ctx)
    assert reply is not None
    assert "子新闻" in reply
    assert "GLM-5.2" in reply or "SpaceX" in reply
    assert "Digest item 1:" not in reply


def test_answer_structured_followup_digest_the_first_news(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "juya.db")
    store.init_schema()
    _seed_juya_digest_store(store)
    ctx = store.get_latest_followup_context()
    reply = answer_structured_followup("Digest the first news", ctx)
    assert reply is not None
    assert "第 1 条" in reply
    assert "daily.juya.uk/issue-5" in reply


def test_match_news_item_for_digest_entry_by_source_id() -> None:
    item = _juya_news_item(
        source_id="juya-rss-issue5",
        title="2026-06-16",
        url="https://daily.juya.uk/issue-5/",
        snippet="x",
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="juya-rss-issue5",
        title="2026-06-16",
        source_name="GitHub",
        source_url=item.url,
        summary="s",
        why_it_matters="w",
        background_knowledge="",
        follow_up_action=FollowUpAction.READ,
    )
    matched = match_news_item_for_digest_entry(entry, [item])
    assert matched is item


def test_render_digest_editorial_text_is_compact_index_not_sections() -> None:
    digest = Digest(
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="juya-rss-1",
                title="2026-06-18",
                source_name="GitHub",
                source_url="https://daily.juya.uk/issue-7/",
                summary="OpenAI 计划任务；Grok Video 1.5",
                why_it_matters="模型发布",
                background_knowledge="",
                follow_up_action=FollowUpAction.READ,
            ),
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="juya-rss-2",
                title="2026-06-17",
                source_name="GitHub",
                source_url="https://daily.juya.uk/issue-6/",
                summary="SpaceX 收购 Cursor",
                why_it_matters="行业动态",
                background_knowledge="",
                follow_up_action=FollowUpAction.READ,
            ),
        ],
        topics=[],
        timeframe="today",
    )
    out = render_digest_editorial_text(digest, output_language="zh-CN")
    assert "1." in out
    assert "2." in out
    assert "\n模型发布\n" not in out
    assert "https://daily.juya.uk/issue-7/" in out
    assert "第一条" in out or "follow up" in out.lower()
