"""Tests for Zhihu practitioner-insight card rank follow-up."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.zhihu_followup import format_zhihu_practitioner_insight_card
from ai_news_agent.models import (
    ConfidenceLevel,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    SourceKind,
)

_FIXTURE_DT = datetime(2026, 5, 7, 10, 0, tzinfo=UTC)


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


def test_format_zhihu_practitioner_insight_card_returns_str() -> None:
    entry = _zh_entry()
    item = _zh_news_item()
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert isinstance(out, str)


_EMOJI_CHROME = ("💬", "🔗", "🔥", "👍")


def test_insight_card_header_chrome() -> None:
    entry = _zh_entry(title="RAG 部署踩坑", source_id="zh-1")
    item = _zh_news_item(source_id="zh-1", title="RAG 部署踩坑")
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "第 1 条" in out
    assert "RAG 部署踩坑" in out
    assert "https://www.zhihu.com/question/zh-1" in out
    for emoji in _EMOJI_CHROME:
        assert emoji not in out


def test_insight_card_lens_present() -> None:
    entry = _zh_entry()
    item = _zh_news_item(
        raw_snippet="部署时要小心显存。",
        source_evidence={"query_lens": "实战 / 踩坑"},
    )
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "镜头" in out
    assert "实战 / 踩坑" in out


def test_insight_card_lens_omitted_when_empty() -> None:
    entry = _zh_entry()
    item = _zh_news_item(source_evidence={})
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "镜头" not in out


def test_insight_card_author_label_present() -> None:
    entry = _zh_entry()
    item = _zh_news_item(
        author="实践者A",
        raw_snippet="部署时要小心显存。",
        source_evidence={"source_label": "回答"},
    )
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "实践者A" in out
    assert "回答" in out


def test_insight_card_author_label_omitted() -> None:
    entry = _zh_entry()
    item = _zh_news_item(author=None, source_evidence={})
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "作者" not in out
    assert "来源" not in out


def test_insight_card_relevance_present() -> None:
    entry = _zh_entry()
    item = _zh_news_item(source_evidence={"relevance": 0.92})
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "搜索相关性" in out
    assert "0.92" in out
    assert "热度：" not in out


def test_insight_card_relevance_omitted_when_empty() -> None:
    entry = _zh_entry()
    item = _zh_news_item(source_evidence={})
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "搜索相关性" not in out


def test_insight_card_snippet_present() -> None:
    entry = _zh_entry()
    item = _zh_news_item(raw_snippet="部署时要小心显存。")
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "原文摘录" in out
    assert "部署时要小心显存。" in out


def test_insight_card_snippet_omitted_when_empty() -> None:
    entry = _zh_entry()
    item = _zh_news_item(raw_snippet=None)
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "原文摘录" not in out


def test_insight_card_llm_fields_present() -> None:
    entry = _zh_entry(summary="这是摘要。", why_it_matters="这是价值。")
    item = _zh_news_item(raw_snippet="部署时要小心显存。")
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "摘要" in out
    assert "这是摘要。" in out
    assert "为什么值得看" in out
    assert "这是价值。" in out


def test_insight_card_llm_fields_omitted_when_empty() -> None:
    entry = _zh_entry(summary="", why_it_matters="")
    item = _zh_news_item()
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "摘要：" not in out
    assert "为什么值得看" not in out


def test_insight_card_no_freshness_caveat() -> None:
    entry = _zh_entry()
    item = _zh_news_item(
        raw_snippet="部署时要小心显存。",
        source_evidence={
            "relevance": 0.92,
            "query_lens": "实战 / 踩坑",
            "source_label": "回答",
        },
        author="实践者A",
    )
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "不是热度" in out or "不是时效" in out
    assert "thin evidence" not in out.lower()
    assert "discovery-only" not in out.lower()


def test_insight_card_thin_evidence_caveat() -> None:
    entry = _zh_entry(summary="", why_it_matters="")
    item = _zh_news_item(source_evidence={})
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "证据" in out or "摘要深度" in out
    assert "不是热度" not in out
    assert "不是时效" not in out


def test_insight_card_forbidden_fields_omitted() -> None:
    entry = _zh_entry(
        summary="这是摘要。",
        why_it_matters="这是价值。",
    )
    entry = entry.model_copy(update={"background_knowledge": "背景知识。"})
    item = _zh_news_item(
        author="实践者A",
        raw_snippet="部署时要小心显存。",
        source_evidence={
            "relevance": 0.92,
            "query_lens": "实战 / 踩坑",
            "source_label": "回答",
            "evidence_text_length": 120,
        },
    )
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "evidence_text_length" not in out
    assert "120" not in out
    assert "背景" not in out
    assert "Follow-up" not in out
    assert "follow_up" not in out
    assert "confidence" not in out.lower()
    assert "热度：" not in out


def test_insight_card_degraded_missing_news_item() -> None:
    entry = _zh_entry(title="RAG 部署踩坑", source_id="zh-1")
    out = format_zhihu_practitioner_insight_card(entry, None, rank=1)
    assert "第 1 条" in out
    assert "RAG 部署踩坑" in out
    assert "https://www.zhihu.com/question/zh-1" in out
    assert "镜头" not in out
    assert "搜索相关性" not in out
    assert "原文摘录" not in out
    assert "摘要：" not in out
    assert "为什么值得看" not in out
    assert "证据" in out or "摘要深度" in out
    assert "0.92" not in out


def test_insight_card_degraded_empty_evidence() -> None:
    entry = _zh_entry(title="RAG 部署踩坑", source_id="zh-1")
    item = _zh_news_item(source_evidence={}, raw_snippet=None)
    out = format_zhihu_practitioner_insight_card(entry, item, rank=1)
    assert "RAG 部署踩坑" in out
    assert "https://www.zhihu.com/question/zh-1" in out
    assert "镜头" not in out
    assert "搜索相关性" not in out
    assert "原文摘录" not in out
    assert "证据" in out or "摘要深度" in out
    assert "不是热度" not in out
    assert "不是时效" not in out
    assert "0.92" not in out
