"""Render digests as Markdown or plain text (CLI / UI; decoupled from summarization)."""

from __future__ import annotations

import re
from collections.abc import Callable

from ai_news_agent.models import ConnectorWarning, Digest, DigestEntry, SourceKind

_SECTION_LABELS: dict[SourceKind, str] = {
    SourceKind.JUYA: "Juya",
    SourceKind.GITHUB: "GitHub",
    SourceKind.BILIBILI: "Bilibili",
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


def _group_entries_by_section(
    entries: list[DigestEntry],
) -> list[tuple[str, list[DigestEntry]]]:
    sections: list[tuple[str, list[DigestEntry]]] = []
    kind_to_index: dict[SourceKind, int] = {}
    for entry in entries:
        kind = entry.source_kind
        if kind not in kind_to_index:
            label = _SECTION_LABELS.get(kind, str(kind.value).title())
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
    lines = ["# AI News Digest", ""]
    meta: list[str] = [f"- **Generated:** {digest.generated_at.isoformat()}"]
    if digest.timeframe is not None:
        meta.append(f"- **Timeframe:** {digest.timeframe}")
    if digest.topics:
        meta.append(f"- **Topics:** {', '.join(digest.topics)}")
    lines.append("\n".join(meta))
    return "\n".join(lines)


def _render_entry_markdown(entry: DigestEntry, *, heading_level: int = 2) -> str:
    hashes = "#" * heading_level
    parts = [
        f"{hashes} {_escape_markdown_inline(entry.title)}",
        "",
        f"- **Source:** {entry.source_name} (`{entry.source_kind.value}`)",
        f"- **Link:** <{entry.source_url}>",
        f"- **Summary:** {_escape_markdown_inline(entry.summary)}",
        f"- **Why it matters:** {_escape_markdown_inline(entry.why_it_matters)}",
        f"- **Background:** {_escape_markdown_inline(entry.background_knowledge)}",
        f"- **Follow-up:** {entry.follow_up_action.value}",
    ]
    if entry.confidence_caveat:
        parts.append(f"- **Confidence:** {_escape_markdown_inline(entry.confidence_caveat)}")
    return "\n".join(parts)


def _render_mixed_entries_markdown(entries: list[DigestEntry]) -> str:
    blocks: list[str] = []
    for label, group in _group_entries_by_section(entries):
        blocks.extend([f"## {label}", ""])
        blocks.append("\n\n".join(_render_entry_markdown(entry, heading_level=3) for entry in group))
    return "\n\n".join(blocks)


def render_digest_markdown(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
) -> str:
    notice = format_connector_warnings_notice(warnings or [], [])
    blocks: list[str] = []
    if notice:
        blocks.extend([notice, ""])
    blocks.extend([_render_header_markdown(digest), ""])
    if not digest.entries:
        blocks.append("*No entries in this digest.*")
    elif _is_mixed_digest(digest.entries):
        blocks.append(_render_mixed_entries_markdown(digest.entries))
    else:
        blocks.append("\n\n".join(_render_entry_markdown(e) for e in digest.entries))
    return "\n".join(blocks).rstrip() + "\n"


def _render_header_text(digest: Digest) -> str:
    lines = ["AI News Digest", ""]
    lines.append(f"Generated: {digest.generated_at.isoformat()}")
    if digest.timeframe is not None:
        lines.append(f"Timeframe: {digest.timeframe}")
    if digest.topics:
        lines.append(f"Topics: {', '.join(digest.topics)}")
    return "\n".join(lines)


def _render_entry_text(entry: DigestEntry) -> str:
    lines = [
        entry.title,
        "",
        f"Source: {entry.source_name} ({entry.source_kind.value})",
        f"Link: {entry.source_url}",
        f"Summary: {entry.summary}",
        f"Why it matters: {entry.why_it_matters}",
        f"Background: {entry.background_knowledge}",
        f"Follow-up: {entry.follow_up_action.value}",
    ]
    if entry.confidence_caveat:
        lines.append(f"Confidence: {entry.confidence_caveat}")
    return "\n".join(lines)


def _render_mixed_entries_text(entries: list[DigestEntry]) -> str:
    blocks: list[str] = []
    for label, group in _group_entries_by_section(entries):
        blocks.append(label)
        blocks.append("")
        blocks.append("\n\n---\n\n".join(_render_entry_text(entry) for entry in group))
    return "\n\n---\n\n".join(blocks)


def render_digest_text(
    digest: Digest,
    *,
    warnings: list[ConnectorWarning] | None = None,
) -> str:
    notice = format_connector_warnings_notice(warnings or [], [])
    parts: list[str] = []
    if notice:
        parts.extend([notice, ""])
    parts.extend([_render_header_text(digest), ""])
    if not digest.entries:
        parts.append("No entries in this digest.")
    elif _is_mixed_digest(digest.entries):
        parts.append(_render_mixed_entries_text(digest.entries))
    else:
        parts.append("\n\n---\n\n".join(_render_entry_text(e) for e in digest.entries))
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
