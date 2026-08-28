"""Hugging Face family-card helpers for structured rank follow-up."""

from __future__ import annotations

from ai_news_agent.models import DigestEntry, NewsItem
from ai_news_agent.rendering import _escape_markdown_inline

__all__ = [
    "format_huggingface_family_card",
]

_FIELD_SEP = " — "

_POPULARITY_CAVEAT = (
    "Hub trending reflects popularity, not model quality or fitness for your use case."
)
_MISSING_EVIDENCE_CAVEAT = (
    "Hub stats and card snippet are not available for this saved item."
)
_LIVE_SNIPPET_CAVEAT = (
    "Snippet is from a live Hub model card fetched after digest time; "
    "Trending, Downloads, and Likes remain digest-time values."
)
_MODEL_CARD_UNAVAILABLE_CAVEAT = (
    "Live Hub model card was unavailable; showing digest-time evidence only."
)


def format_huggingface_family_card(
    entry: DigestEntry,
    news_item: NewsItem | None,
    *,
    rank: int,
    model_card_unavailable: bool = False,
) -> str:
    """Render an English family card from persisted digest evidence."""
    lines = [
        _field_line(f"Rank {rank}", entry.title),
        _field_line("Link", entry.source_url),
    ]
    if news_item is None:
        lines.append(_MISSING_EVIDENCE_CAVEAT)
        return "\n".join(lines).rstrip()
    evidence = news_item.source_evidence
    if not _has_hub_stats_or_snippet(news_item, evidence):
        also = _also_column(evidence)
        if also:
            lines.append(_field_line("Also", also))
        lines.append(_MISSING_EVIDENCE_CAVEAT)
        return "\n".join(lines).rstrip()
    trending = evidence.get("trending_score")
    if trending:
        lines.append(_field_line("Trending", trending))
    downloads_30d = evidence.get("downloads_30d")
    if downloads_30d:
        lines.append(_field_line("Downloads (30d)", downloads_30d))
    likes = evidence.get("likes")
    if likes:
        lines.append(_field_line("Likes", likes))
    pipeline_tag = evidence.get("pipeline_tag")
    if pipeline_tag:
        lines.append(_field_line("Pipeline", pipeline_tag))
    also = _also_column(evidence)
    if also:
        lines.append(_field_line("Also", also))
    if news_item.author:
        lines.append(_field_line("Publisher", news_item.author))
    if news_item.raw_snippet:
        _append_snippet_lines(lines, news_item.raw_snippet)
    if evidence.get("model_card_live_fetched"):
        lines.append(_LIVE_SNIPPET_CAVEAT)
    if model_card_unavailable:
        lines.append(_MODEL_CARD_UNAVAILABLE_CAVEAT)
    if _has_hub_stats_or_snippet(news_item, evidence):
        lines.append(_POPULARITY_CAVEAT)
    return "\n".join(lines).rstrip()


def _field_line(label: str, value: object) -> str:
    return f"{label}{_FIELD_SEP}{_escape_markdown_inline(str(value))}"


def _append_snippet_lines(lines: list[str], raw_snippet: str) -> None:
    body = _display_snippet(raw_snippet)
    if not body:
        return
    lines.append(f"Snippet{_FIELD_SEP}")
    lines.append(body)


def _display_snippet(raw: str) -> str:
    """Return snippet text safe for Gradio markdown (strip YAML frontmatter)."""
    stripped = _strip_yaml_frontmatter(raw.strip())
    return stripped if stripped else raw.strip()


def _strip_yaml_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    rest = text[3:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        return text
    close = rest.find("\n---")
    if close == -1:
        return text
    body = rest[close + 4 :]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    trimmed = body.strip()
    return trimmed if trimmed else text


def _also_column(evidence: dict[str, object]) -> str:
    variants = evidence.get("family_variants")
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


def _has_hub_stats_or_snippet(news_item: NewsItem | None, evidence: dict[str, object]) -> bool:
    if news_item is not None and news_item.raw_snippet:
        return True
    for key in ("trending_score", "downloads_30d", "likes", "pipeline_tag"):
        if evidence.get(key):
            return True
    return False
