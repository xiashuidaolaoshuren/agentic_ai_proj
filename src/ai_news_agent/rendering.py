"""Render digests as Markdown or plain text (CLI / UI; decoupled from summarization)."""

from __future__ import annotations

import re
from collections.abc import Callable

from ai_news_agent.models import ConnectorWarning, Digest, DigestEntry, NewsItem, SourceKind

_SECTION_LABELS: dict[SourceKind, str] = {
    SourceKind.JUYA: "Juya",
    SourceKind.HUGGINGFACE: "Hugging Face",
    SourceKind.GITHUB: "GitHub",
    SourceKind.ZHIHU: "Zhihu",
    SourceKind.BILIBILI: "Bilibili",
}

_SECTION_EMOJI: dict[SourceKind, str] = {
    SourceKind.JUYA: "🗞️",
    SourceKind.HUGGINGFACE: "🤗",
    SourceKind.GITHUB: "🐙",
    SourceKind.ZHIHU: "💬",
    SourceKind.BILIBILI: "📺",
}

_DIGEST_TITLE = "📰 AI News Digest"

_META_LABELS_MD: dict[str, str] = {
    "generated": "🕒 Generated",
    "timeframe": "📅 Timeframe",
    "topics": "🏷️ Topics",
}

_META_LABELS_TEXT: dict[str, str] = {
    "generated": "🕒 Generated",
    "timeframe": "📅 Timeframe",
    "topics": "🏷️ Topics",
}

_FIELD_LABELS_MD: dict[str, str] = {
    "source": "📡 Source",
    "link": "🔗 Link",
    "summary": "📝 Summary",
    "why_it_matters": "💡 Why it matters",
    "background": "📚 Background",
    "follow_up": "➡️ Follow-up",
    "confidence": "⚠️ Confidence",
}

_FIELD_LABELS_TEXT: dict[str, str] = {
    "source": "📡 Source",
    "link": "🔗 Link",
    "summary": "📝 Summary",
    "why_it_matters": "💡 Why it matters",
    "background": "📚 Background",
    "follow_up": "➡️ Follow-up",
    "confidence": "⚠️ Confidence",
}

_EDITORIAL_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("模型发布", ("model", "glm", "qwen", "llm", "开源", "release", "模型")),
    ("产品与应用", ("product", "app", "application", "产品", "应用", "邀测", "beta")),
    ("技术与研究", ("research", "paper", "tech", "技术", "研究", "agent", "coding")),
    ("行业动态", ("industry", "收购", "融资", "合作", "政策")),
)
_EDITORIAL_GENERAL = "今日要闻"


def format_connector_warnings_notice(
    warnings: list[ConnectorWarning],
    errors: list[object] | None = None,
) -> str:
    """Build a compact user-facing notice for high-signal connector warnings."""
    del errors
    if not warnings:
        return ""

    priority_codes = ("anti_bot_blocked", "rate_limited")
    lines: list[str] = []
    seen_messages: set[str] = set()

    for code in priority_codes:
        for warning in warnings:
            if warning.connector != "bilibili" or warning.code != code:
                continue
            message = warning.message.strip()
            if not message or message in seen_messages:
                continue
            seen_messages.add(message)
            lines.append(f"⚠ {message}")

    if not lines:
        return ""
    return "\n".join(lines)


def _is_mixed_digest(entries: list[DigestEntry]) -> bool:
    return len({entry.source_kind for entry in entries}) > 1


def _section_display_label(kind: SourceKind) -> str:
    base = _SECTION_LABELS.get(kind, str(kind.value).title())
    emoji = _SECTION_EMOJI.get(kind)
    if emoji:
        return f"{emoji} {base}"
    return base


def _group_entries_by_section(
    entries: list[DigestEntry],
) -> list[tuple[str, list[DigestEntry]]]:
    sections: list[tuple[str, list[DigestEntry]]] = []
    kind_to_index: dict[SourceKind, int] = {}
    for entry in entries:
        kind = entry.source_kind
        if kind not in kind_to_index:
            label = _section_display_label(kind)
            kind_to_index[kind] = len(sections)
            sections.append((label, [entry]))
            continue
        index = kind_to_index[kind]
        label, group = sections[index]
        group.append(entry)
        sections[index] = (label, group)
    return sections


def _digest_has_juya(entries: list[DigestEntry]) -> bool:
    return any(entry.source_kind is SourceKind.JUYA for entry in entries)


def _escape_markdown_inline(text: str) -> str:
    """Escape minimal Markdown special characters in user/LLM text."""
    out: list[str] = []
    for ch in text:
        if ch in "\\*_[]":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _render_header_markdown(digest: Digest) -> str:
    lines = [f"# {_DIGEST_TITLE}", ""]
    meta: list[str] = [
        f"- **{_META_LABELS_MD['generated']}:** {digest.generated_at.isoformat()}"
    ]
    if digest.timeframe is not None:
        meta.append(f"- **{_META_LABELS_MD['timeframe']}:** {digest.timeframe}")
    if digest.topics:
        meta.append(f"- **{_META_LABELS_MD['topics']}:** {', '.join(digest.topics)}")
    lines.append("\n".join(meta))
    return "\n".join(lines)


def _entry_display_ranks(entries: list[DigestEntry]) -> dict[tuple[SourceKind, str], int]:
    return {
        (entry.source_kind, entry.source_id): index
        for index, entry in enumerate(entries, start=1)
    }


def _format_display_rank_prefix(display_rank: int | None) -> str:
    if display_rank is None:
        return ""
    return f"{display_rank}. "


def _is_huggingface_only(entries: list[DigestEntry]) -> bool:
    return bool(entries) and all(
        entry.source_kind is SourceKind.HUGGINGFACE for entry in entries
    )


def _news_items_by_key(
    news_items: list[NewsItem] | None,
) -> dict[tuple[SourceKind, str], NewsItem]:
    if not news_items:
        return {}
    return {(item.source, item.source_id): item for item in news_items}


def _format_table_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _also_column(item: NewsItem | None) -> str:
    if item is None:
        return ""
    variants = item.source_evidence.get("family_variants")
    if not isinstance(variants, list):
        return ""
    titles: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        title = str(variant.get("title", variant.get("source_id", ""))).strip()
        if title:
            titles.append(title)
    return ", ".join(titles)


def _hf_table_header_lines() -> tuple[str, str]:
    header = (
        "| 🏆 Rank | 🤖 Model | 🔗 Link | 🔥 Trending | ⬇️ Downloads | "
        "👍 Likes | 🧩 Pipeline | ➕ Also |"
    )
    separator = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    return header, separator


def _hf_table_row_line(
    *,
    rank: int,
    title: str,
    url: str,
    evidence: dict[str, object],
    also: str,
    escape_markdown: bool,
) -> str:
    model_name = _escape_markdown_inline(title) if escape_markdown else title
    if escape_markdown:
        also = _escape_markdown_inline(also)
    link = f"<{url}>" if escape_markdown else url
    return (
        "| "
        + " | ".join(
            [
                str(rank),
                model_name,
                link,
                _format_table_cell(evidence.get("trending_score")),
                _format_table_cell(evidence.get("downloads_30d")),
                _format_table_cell(evidence.get("likes")),
                _format_table_cell(evidence.get("pipeline_tag")),
                also,
            ]
        )
        + " |"
    )


def _render_huggingface_comparison_table_from_items(
    items: list[NewsItem],
    *,
    escape_markdown: bool,
) -> str:
    header, separator = _hf_table_header_lines()
    rows: list[str] = [header, separator]
    for rank, item in enumerate(items, start=1):
        rows.append(
            _hf_table_row_line(
                rank=rank,
                title=item.title,
                url=item.url,
                evidence=item.source_evidence,
                also=_also_column(item),
                escape_markdown=escape_markdown,
            )
        )
    rows.extend(["", f"Note: {_HF_POPULARITY_CAVEAT}"])
    return "\n".join(rows)


def _render_huggingface_comparison_table(
    entries: list[DigestEntry],
    *,
    ranks: dict[tuple[SourceKind, str], int],
    news_items: list[NewsItem] | None = None,
    escape_markdown: bool,
) -> str:
    lookup = _news_items_by_key(news_items)
    header, separator = _hf_table_header_lines()
    rows: list[str] = [header, separator]
    for entry in entries:
        item = lookup.get((entry.source_kind, entry.source_id))
        evidence = item.source_evidence if item is not None else {}
        rank = ranks[(entry.source_kind, entry.source_id)]
        rows.append(
            _hf_table_row_line(
                rank=rank,
                title=entry.title,
                url=entry.source_url,
                evidence=evidence,
                also=_also_column(item),
                escape_markdown=escape_markdown,
            )
        )
    rows.extend(["", f"Note: {_HF_POPULARITY_CAVEAT}"])
    return "\n".join(rows)


def _render_entry_markdown(
    entry: DigestEntry,
    *,
    heading_level: int = 2,
    display_rank: int | None = None,
) -> str:
    hashes = "#" * heading_level
    title = f"{_format_display_rank_prefix(display_rank)}{_escape_markdown_inline(entry.title)}"
    parts = [
        f"{hashes} {title}",
        "",
        f"- **{_FIELD_LABELS_MD['source']}:** {entry.source_name} (`{entry.source_kind.value}`)",
        f"- **{_FIELD_LABELS_MD['link']}:** <{entry.source_url}>",
        f"- **{_FIELD_LABELS_MD['summary']}:** {_escape_markdown_inline(entry.summary)}",
        f"- **{_FIELD_LABELS_MD['why_it_matters']}:** {_escape_markdown_inline(entry.why_it_matters)}",
        f"- **{_FIELD_LABELS_MD['background']}:** {_escape_markdown_inline(entry.background_knowledge)}",
        f"- **{_FIELD_LABELS_MD['follow_up']}:** {entry.follow_up_action.value}",
    ]
    if entry.confidence_caveat:
        parts.append(
            f"- **{_FIELD_LABELS_MD['confidence']}:** "
            f"{_escape_markdown_inline(entry.confidence_caveat)}"
        )
    return "\n".join(parts)


def _render_mixed_entries_markdown(
    entries: list[DigestEntry],
    *,
    news_items: list[NewsItem] | None = None,
) -> str:
    ranks = _entry_display_ranks(entries)
    blocks: list[str] = []
    for label, group in _group_entries_by_section(entries):
        blocks.extend([f"## {label}", ""])
        if group and group[0].source_kind is SourceKind.HUGGINGFACE:
            blocks.append(
                _render_huggingface_comparison_table(
                    group,
                    ranks=ranks,
                    news_items=news_items,
                    escape_markdown=True,
                )
            )
            continue
        blocks.append(
            "\n\n".join(
                _render_entry_markdown(
                    entry,
                    heading_level=3,
                    display_rank=ranks[(entry.source_kind, entry.source_id)],
                )
                for entry in group
            )
        )
    return "\n\n".join(blocks)


def render_digest_markdown(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
    news_items: list[NewsItem] | None = None,
) -> str:
    notice = format_connector_warnings_notice(warnings or [], [])
    blocks: list[str] = []
    if notice:
        blocks.extend([notice, ""])
    blocks.extend([_render_header_markdown(digest), ""])
    if not digest.entries:
        blocks.append("*No entries in this digest.*")
    elif _is_huggingface_only(digest.entries):
        ranks = _entry_display_ranks(digest.entries)
        blocks.append(
            _render_huggingface_comparison_table(
                digest.entries,
                ranks=ranks,
                news_items=news_items,
                escape_markdown=True,
            )
        )
    elif _is_mixed_digest(digest.entries):
        blocks.append(
            _render_mixed_entries_markdown(digest.entries, news_items=news_items)
        )
    else:
        blocks.append(
            "\n\n".join(
                _render_entry_markdown(entry, display_rank=index)
                for index, entry in enumerate(digest.entries, start=1)
            )
        )
    return "\n".join(blocks).rstrip() + "\n"


def _render_header_text(digest: Digest) -> str:
    lines = [_DIGEST_TITLE, ""]
    lines.append(
        f"{_META_LABELS_TEXT['generated']}: {digest.generated_at.isoformat()}"
    )
    if digest.timeframe is not None:
        lines.append(f"{_META_LABELS_TEXT['timeframe']}: {digest.timeframe}")
    if digest.topics:
        lines.append(f"{_META_LABELS_TEXT['topics']}: {', '.join(digest.topics)}")
    return "\n".join(lines)


def _render_entry_text(entry: DigestEntry, *, display_rank: int | None = None) -> str:
    lines = [
        f"{_format_display_rank_prefix(display_rank)}{entry.title}",
        "",
        f"{_FIELD_LABELS_TEXT['source']}: {entry.source_name} ({entry.source_kind.value})",
        f"{_FIELD_LABELS_TEXT['link']}: {entry.source_url}",
        f"{_FIELD_LABELS_TEXT['summary']}: {entry.summary}",
        f"{_FIELD_LABELS_TEXT['why_it_matters']}: {entry.why_it_matters}",
        f"{_FIELD_LABELS_TEXT['background']}: {entry.background_knowledge}",
        f"{_FIELD_LABELS_TEXT['follow_up']}: {entry.follow_up_action.value}",
    ]
    if entry.confidence_caveat:
        lines.append(f"{_FIELD_LABELS_TEXT['confidence']}: {entry.confidence_caveat}")
    return "\n".join(lines)


_HF_POPULARITY_CAVEAT = (
    "Hub trending reflects popularity, not model quality or fitness for your use case."
)


def render_search_items_text(items: list[NewsItem]) -> str:
    """Render connector search hits as a deterministic plain-text list or HF table."""
    if items and all(item.source is SourceKind.HUGGINGFACE for item in items):
        return _render_huggingface_comparison_table_from_items(items, escape_markdown=False)

    blocks: list[str] = []
    for rank, item in enumerate(items, start=1):
        source_name = _SECTION_LABELS.get(item.source, item.source.value)
        lines = [
            f"{rank}. {item.title}",
            "",
            f"Source: {source_name} ({item.source.value})",
            f"Link: {item.url}",
        ]
        if item.raw_snippet:
            lines.append(f"Snippet: {item.raw_snippet}")
        if item.source is SourceKind.HUGGINGFACE:
            evidence = item.source_evidence
            hub_parts: list[str] = []
            trending_score = evidence.get("trending_score")
            if trending_score is not None:
                hub_parts.append(f"trending_score={trending_score}")
            downloads = evidence.get("downloads_30d")
            if downloads is not None:
                hub_parts.append(f"downloads={downloads}")
            likes = evidence.get("likes")
            if likes is not None:
                hub_parts.append(f"likes={likes}")
            if hub_parts:
                lines.append(f"Hub: {', '.join(hub_parts)}")
            variants = evidence.get("family_variants")
            if isinstance(variants, list) and variants:
                also_titles = [
                    str(variant.get("title", variant.get("source_id", ""))).strip()
                    for variant in variants
                    if isinstance(variant, dict)
                ]
                also_titles = [title for title in also_titles if title]
                if also_titles:
                    lines.append(f"Also: {', '.join(also_titles)}")
        blocks.append("\n".join(lines))

    text = "\n\n---\n\n".join(blocks)
    if any(item.source is SourceKind.HUGGINGFACE for item in items):
        text = f"{text}\n\nNote: {_HF_POPULARITY_CAVEAT}" if text else f"Note: {_HF_POPULARITY_CAVEAT}"
    return text


def _render_mixed_entries_text(
    entries: list[DigestEntry],
    *,
    news_items: list[NewsItem] | None = None,
) -> str:
    ranks = _entry_display_ranks(entries)
    blocks: list[str] = []
    for label, group in _group_entries_by_section(entries):
        blocks.append(label)
        blocks.append("")
        if group and group[0].source_kind is SourceKind.HUGGINGFACE:
            blocks.append(
                _render_huggingface_comparison_table(
                    group,
                    ranks=ranks,
                    news_items=news_items,
                    escape_markdown=False,
                )
            )
            continue
        blocks.append(
            "\n\n---\n\n".join(
                _render_entry_text(
                    entry,
                    display_rank=ranks[(entry.source_kind, entry.source_id)],
                )
                for entry in group
            )
        )
    return "\n\n---\n\n".join(blocks)


def render_digest_text(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
    news_items: list[NewsItem] | None = None,
) -> str:
    notice = format_connector_warnings_notice(warnings or [], [])
    parts: list[str] = []
    if notice:
        parts.extend([notice, ""])
    parts.extend([_render_header_text(digest), ""])
    if not digest.entries:
        parts.append("No entries in this digest.")
    elif _is_huggingface_only(digest.entries):
        ranks = _entry_display_ranks(digest.entries)
        parts.append(
            _render_huggingface_comparison_table(
                digest.entries,
                ranks=ranks,
                news_items=news_items,
                escape_markdown=False,
            )
        )
    elif _is_mixed_digest(digest.entries):
        parts.append(
            _render_mixed_entries_text(digest.entries, news_items=news_items)
        )
    else:
        parts.append(
            "\n\n---\n\n".join(
                _render_entry_text(entry, display_rank=index)
                for index, entry in enumerate(digest.entries, start=1)
            )
        )
    return "\n".join(parts).rstrip() + "\n"


def _classify_editorial_section(entry: DigestEntry) -> str:
    haystack = " ".join(
        part
        for part in (entry.title, entry.summary, entry.why_it_matters)
        if part
    ).lower()
    for section, keywords in _EDITORIAL_SECTIONS:
        if any(keyword.lower() in haystack for keyword in keywords):
            return section
    return _EDITORIAL_GENERAL


def _group_entries_for_editorial(entries: list[DigestEntry]) -> list[tuple[str, list[DigestEntry]]]:
    buckets: dict[str, list[DigestEntry]] = {}
    order: list[str] = []
    for entry in entries:
        section = _classify_editorial_section(entry)
        if section not in buckets:
            buckets[section] = []
            order.append(section)
        buckets[section].append(entry)

    preferred = [_EDITORIAL_GENERAL, *[name for name, _ in _EDITORIAL_SECTIONS]]
    ordered_names = [name for name in preferred if name in buckets]
    ordered_names.extend(name for name in order if name not in ordered_names)
    return [(name, buckets[name]) for name in ordered_names]


def render_digest_editorial_text(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
    output_language: str | None = None,
) -> str:
    del output_language
    notice = format_connector_warnings_notice(warnings or [], [])
    parts: list[str] = []
    if notice:
        parts.extend([notice, ""])

    header = "橘鸦AI早报" if _digest_has_juya(digest.entries) else "AI 新闻简报"
    parts.append(header)
    parts.append(f"生成时间：{digest.generated_at.isoformat()}")
    if digest.timeframe:
        parts.append(f"时间范围：{digest.timeframe}")
    parts.append("")

    if not digest.entries:
        parts.append("本期暂无条目。")
        return "\n".join(parts).rstrip() + "\n"

    if _is_mixed_digest(digest.entries):
        for label, group in _group_entries_by_section(digest.entries):
            parts.append(label)
            parts.append("")
            for index, entry in enumerate(group, start=1):
                summary_line = entry.summary or entry.title
                parts.append(f"{index}. {entry.title}")
                parts.append(f"   {summary_line}")
                if entry.why_it_matters:
                    parts.append(f"   要点：{entry.why_it_matters}")
                parts.append(f"   来源：{entry.source_url}")
                parts.append("")
    else:
        for index, entry in enumerate(digest.entries, start=1):
            summary_line = entry.summary or entry.title
            parts.append(f"{index}. {entry.title}")
            parts.append(f"   {summary_line}")
            if entry.why_it_matters:
                parts.append(f"   要点：{entry.why_it_matters}")
            parts.append(f"   来源：{entry.source_url}")
            parts.append("")

    parts.append("如需查看某条详情，可以说「第一条 news」或「follow up on item 1」。")
    return "\n".join(parts).rstrip() + "\n"


def render_digest_editorial_markdown(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
    output_language: str | None = None,
) -> str:
    plain = render_digest_editorial_text(
        digest,
        warnings=warnings,
        output_language=output_language,
    )
    source_section_labels = set(_SECTION_LABELS.values())
    lines: list[str] = []
    for line in plain.splitlines():
        if line in {_EDITORIAL_GENERAL, *[name for name, _ in _EDITORIAL_SECTIONS]}:
            lines.append(f"## {line}")
        elif line in source_section_labels:
            lines.append(f"## {line}")
        elif line and not line.startswith(("- ", "生成", "时间", "本期", "橘鸦", "AI ")):
            lines.append(f"# {line}" if not lines else line)
        else:
            lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def select_digest_renderers(
    output_style: str | None,
) -> tuple[
    Callable[..., str],
    Callable[..., str],
]:
    """Return markdown/text render callables for the requested output style."""
    if output_style == "editorial":
        return render_digest_editorial_markdown, render_digest_editorial_text
    return render_digest_markdown, render_digest_text
