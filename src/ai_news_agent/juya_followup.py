"""Juya-specific issue deep-dive helpers for structured follow-up."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_news_agent.models import DigestEntry, NewsItem

_JUYA_SECTION_MARKERS: tuple[str, ...] = (
    "今日要闻",
    "模型发布",
    "产品与应用",
    "技术与研究",
    "行业动态",
)

_BULLET_SPLIT_RE = re.compile(r"\s+[—\-]\s+")


@dataclass(frozen=True)
class JuyaSubNews:
    """One extracted sub-story within a Juya daily issue."""

    title: str
    detail: str
    section: str | None = None


def is_juya_news_item(item: NewsItem) -> bool:
    """Return True when a collected item looks like a Juya daily issue row."""
    tags = {t.lower() for t in (item.tags or [])}
    if "juya-daily" in tags or "juya-backup" in tags:
        return True
    url = (item.url or "").lower()
    if "daily.juya.uk" in url:
        return True
    return item.source_id.startswith("juya-rss-")


def match_news_item_for_digest_entry(
    entry: DigestEntry,
    news_items: list[NewsItem],
) -> NewsItem | None:
    """Resolve the persisted NewsItem backing a digest entry."""
    for item in news_items:
        if item.source_id == entry.source_id:
            return item
    for item in news_items:
        if item.url == entry.source_url:
            return item
    return None


def parse_juya_sub_news(raw_snippet: str) -> list[JuyaSubNews]:
    """Split flattened Juya BACKUP evidence into sub-news blocks."""
    text = raw_snippet.strip()
    if not text:
        return []

    section_spans = _locate_sections(text)
    if not section_spans:
        return _split_sentences_as_sub_news(text, section=None)

    items: list[JuyaSubNews] = []
    for section, body in section_spans:
        items.extend(_extract_section_items(body, section))
    return items


def format_juya_issue_deep_dive(
    entry: DigestEntry,
    news_item: NewsItem,
    *,
    rank: int,
) -> str:
    """Render a Chinese issue-level deep dive with extracted sub-news."""
    lines = [
        f"第 {rank} 条：{entry.title}",
        f"来源：{entry.source_url}",
        "",
        "本期子新闻：",
    ]

    sub_items = parse_juya_sub_news(news_item.raw_snippet or "")
    if sub_items:
        for index, sub in enumerate(sub_items, start=1):
            lines.append(f"{index}. {sub.title}")
            if sub.detail and sub.detail != sub.title:
                lines.append(f"   {sub.detail}")
            lines.append("")
    else:
        lines.append(f"1. {entry.summary}")
        lines.append("")

    if entry.summary:
        lines.append(f"摘要：{entry.summary}")
    if entry.why_it_matters:
        lines.append(f"要点：{entry.why_it_matters}")
    if entry.confidence_caveat:
        lines.append(f"注意：{entry.confidence_caveat}")

    lines.append("")
    lines.append("想深入某一条子新闻，可以说编号或关键词。")
    return "\n".join(lines).rstrip()


def _locate_sections(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[int, str]] = []
    for marker in _JUYA_SECTION_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            hits.append((idx, marker))
    if not hits:
        return []

    hits.sort(key=lambda pair: pair[0])
    spans: list[tuple[str, str]] = []
    for i, (start, marker) in enumerate(hits):
        body_start = start + len(marker)
        body_end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            spans.append((marker, body))
    return spans


def _extract_section_items(body: str, section: str) -> list[JuyaSubNews]:
    if section == "今日要闻":
        return _split_sentences_as_sub_news(body, section=section)

    if " — " in body or " - " in body:
        chunks = re.split(r"(?<=[\u4e00-\u9fff\)])\s+(?=[A-Za-z0-9\u4e00-\u9fff])", body)
        items: list[JuyaSubNews] = []
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            if _BULLET_SPLIT_RE.search(chunk):
                title, detail = _BULLET_SPLIT_RE.split(chunk, maxsplit=1)
                items.append(
                    JuyaSubNews(
                        title=title.strip(),
                        detail=detail.strip(),
                        section=section,
                    )
                )
            else:
                items.append(JuyaSubNews(title=chunk[:80], detail=chunk, section=section))
        return items

    return [JuyaSubNews(title=body[:80], detail=body, section=section)]


def _split_sentences_as_sub_news(
    body: str,
    *,
    section: str | None,
) -> list[JuyaSubNews]:
    items: list[JuyaSubNews] = []
    for part in re.split(r"[。；]", body):
        sentence = part.strip()
        if len(sentence) < 8:
            continue
        items.append(
            JuyaSubNews(
                title=sentence[:80],
                detail=sentence,
                section=section,
            )
        )
    return items


__all__ = [
    "JuyaSubNews",
    "format_juya_issue_deep_dive",
    "is_juya_news_item",
    "match_news_item_for_digest_entry",
    "parse_juya_sub_news",
]
