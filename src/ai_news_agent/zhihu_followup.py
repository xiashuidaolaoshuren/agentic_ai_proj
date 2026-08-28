"""Zhihu practitioner-insight card helpers for structured rank follow-up."""

from __future__ import annotations

from ai_news_agent.models import DigestEntry, NewsItem

__all__ = [
    "format_zhihu_practitioner_insight_card",
]

_NO_FRESHNESS_CAVEAT = (
    "搜索相关性是官方搜索相关性，不是热度或时效性指标。"
)
_THIN_EVIDENCE_CAVEAT = (
    "该知乎结果为发现导向；证据较薄，摘要深度可能有限。"
)


def format_zhihu_practitioner_insight_card(
    entry: DigestEntry,
    news_item: NewsItem | None,
    *,
    rank: int,
) -> str:
    """Render a Chinese practitioner-insight card from persisted digest evidence."""
    lines = [
        f"第 {rank} 条：{entry.title}",
        f"链接：{entry.source_url}",
    ]
    if news_item is None:
        lines.append(_THIN_EVIDENCE_CAVEAT)
        return "\n".join(lines).rstrip()
    evidence = news_item.source_evidence
    if not _has_substantive_evidence(news_item, evidence):
        query_lens = evidence.get("query_lens")
        if query_lens:
            lines.append(f"镜头：{query_lens}")
        author_source = _author_source_line(news_item)
        if author_source:
            lines.append(author_source)
        lines.append(_THIN_EVIDENCE_CAVEAT)
        return "\n".join(lines).rstrip()
    query_lens = evidence.get("query_lens")
    if query_lens:
        lines.append(f"镜头：{query_lens}")
    author_source = _author_source_line(news_item)
    if author_source:
        lines.append(author_source)
    relevance = evidence.get("relevance")
    if relevance:
        lines.append(f"搜索相关性：{relevance}")
    if news_item.raw_snippet:
        lines.append(f"原文摘录：{news_item.raw_snippet}")
    if entry.summary:
        lines.append(f"摘要：{entry.summary}")
    if entry.why_it_matters:
        lines.append(f"为什么值得看：{entry.why_it_matters}")
    lines.append(_NO_FRESHNESS_CAVEAT)
    return "\n".join(lines).rstrip()


def _author_source_line(news_item: NewsItem) -> str:
    author = news_item.author
    source_label = news_item.source_evidence.get("source_label")
    if author and source_label:
        return f"作者/来源：{author}（{source_label}）"
    if author:
        return f"作者/来源：{author}"
    if source_label:
        return f"作者/来源：{source_label}"
    return ""


def _has_substantive_evidence(news_item: NewsItem, evidence: dict[str, object]) -> bool:
    if news_item.raw_snippet:
        return True
    if evidence.get("relevance"):
        return True
    return False
