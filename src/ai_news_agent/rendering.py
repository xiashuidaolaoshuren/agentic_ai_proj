"""Render digests as Markdown or plain text (CLI / UI; decoupled from summarization)."""

from __future__ import annotations

from ai_news_agent.models import Digest, DigestEntry


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


def _render_entry_markdown(entry: DigestEntry) -> str:
    parts = [
        f"## {_escape_markdown_inline(entry.title)}",
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


def render_digest_markdown(digest: Digest) -> str:
    blocks: list[str] = [_render_header_markdown(digest), ""]
    if not digest.entries:
        blocks.append("*No entries in this digest.*")
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


def render_digest_text(digest: Digest) -> str:
    parts: list[str] = [_render_header_text(digest), ""]
    if not digest.entries:
        parts.append("No entries in this digest.")
    else:
        parts.append("\n\n---\n\n".join(_render_entry_text(e) for e in digest.entries))
    return "\n".join(parts).rstrip() + "\n"
