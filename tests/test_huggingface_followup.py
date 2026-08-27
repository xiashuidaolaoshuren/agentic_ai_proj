"""Tests for Hugging Face family-card rank follow-up."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.huggingface_followup import format_huggingface_family_card
from ai_news_agent.models import (
    ConfidenceLevel,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    SourceKind,
)

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


def test_format_huggingface_family_card_returns_str() -> None:
    entry = _hf_entry()
    item = _hf_news_item()
    out = format_huggingface_family_card(entry, item, rank=1)
    assert isinstance(out, str)


_EMOJI_CHROME = ("🏆", "🤖", "🔗", "🔥", "⬇️", "👍", "🧩", "➕")


def test_family_card_header_chrome() -> None:
    entry = _hf_entry(title="Qwen3.8-27B", source_id="Qwen/Qwen3.8-27B")
    item = _hf_news_item(
        source_id="Qwen/Qwen3.8-27B",
        title="Qwen3.8-27B",
    )
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Rank 1" in out
    assert "Qwen3.8-27B" in out
    assert "https://huggingface.co/Qwen/Qwen3.8-27B" in out
    for emoji in _EMOJI_CHROME:
        assert emoji not in out


def test_family_card_hub_stats_present() -> None:
    entry = _hf_entry()
    item = _hf_news_item(
        source_evidence={
            "trending_score": 88.0,
            "downloads_30d": 1200,
            "likes": 42,
            "pipeline_tag": "text-generation",
        },
    )
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Trending:" in out
    assert "88" in out
    assert "Downloads (30d):" in out
    assert "1200" in out
    assert "Likes:" in out
    assert "42" in out
    assert "Pipeline:" in out
    assert "text-generation" in out


def test_family_card_hub_stats_omitted_when_empty() -> None:
    entry = _hf_entry()
    item = _hf_news_item(source_evidence={})
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Trending:" not in out
    assert "Downloads (30d):" not in out
    assert "Likes:" not in out
    assert "Pipeline:" not in out


def test_family_card_also_variants() -> None:
    entry = _hf_entry()
    item = _hf_news_item(
        source_evidence={
            "family_variants": [
                {"source_id": "Someone/Qwen3-27B-GGUF", "title": "Qwen3-27B-GGUF"},
                {"source_id": "Other/Qwen3-27B-MLX", "title": "Qwen3-27B-MLX"},
            ],
        },
    )
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Qwen3-27B-GGUF" in out
    assert "Qwen3-27B-MLX" in out


def test_family_card_also_omitted_when_empty() -> None:
    entry = _hf_entry()
    item = _hf_news_item(source_evidence={})
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Also:" not in out
    assert "Also: none" not in out


def test_family_card_publisher_and_snippet_present() -> None:
    entry = _hf_entry()
    item = _hf_news_item(author="Qwen", raw_snippet="Small and fast.")
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Publisher:" in out
    assert "Qwen" in out
    assert "Snippet:" in out
    assert "Small and fast." in out


def test_family_card_publisher_and_snippet_omitted() -> None:
    entry = _hf_entry()
    item = _hf_news_item(author=None, raw_snippet=None)
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Publisher:" not in out
    assert "Snippet:" not in out


def test_family_card_popularity_caveat() -> None:
    entry = _hf_entry()
    item = _hf_news_item(
        source_evidence={
            "trending_score": 88.0,
            "downloads_30d": 1200,
            "likes": 42,
            "pipeline_tag": "text-generation",
        },
        raw_snippet="Small and fast.",
    )
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "popularity, not" in out


def test_family_card_forbidden_fields_omitted() -> None:
    entry = _hf_entry()
    entry = entry.model_copy(
        update={
            "why_it_matters": "Why HF matters.",
            "background_knowledge": "Background HF.",
        },
    )
    item = _hf_news_item(
        source_evidence={
            "trending_score": 88.0,
            "downloads_30d": 1200,
            "downloads_all_time": 2500000,
            "likes": 42,
            "pipeline_tag": "text-generation",
            "library_name": "transformers",
            "gated": False,
            "discovery_mode": "global",
        },
        raw_snippet="Small and fast.",
    )
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Gated:" not in out
    assert "Library:" not in out
    assert "All-time" not in out
    assert "Discovery mode:" not in out
    assert "Why it matters:" not in out
    assert "Background:" not in out
    assert "Follow-up action:" not in out
    assert "2500000" not in out
    assert "False" not in out
    assert "transformers" not in out
    assert "global" not in out


def test_family_card_degraded_missing_news_item() -> None:
    entry = _hf_entry(title="Qwen3.8-27B", source_id="Qwen/Qwen3.8-27B")
    out = format_huggingface_family_card(entry, None, rank=1)
    assert "Rank 1" in out
    assert "Qwen3.8-27B" in out
    assert "https://huggingface.co/Qwen/Qwen3.8-27B" in out
    assert "Trending:" not in out
    assert "Downloads (30d):" not in out
    assert "Likes:" not in out
    assert "Pipeline:" not in out
    assert "Snippet:" not in out
    assert "not available" in out
    assert "1200" not in out
    assert "88" not in out


def test_family_card_degraded_empty_evidence() -> None:
    entry = _hf_entry(title="Qwen3.8-27B", source_id="Qwen/Qwen3.8-27B")
    item = _hf_news_item(source_evidence={}, raw_snippet=None)
    out = format_huggingface_family_card(entry, item, rank=1)
    assert "Qwen3.8-27B" in out
    assert "https://huggingface.co/Qwen/Qwen3.8-27B" in out
    assert "Trending:" not in out
    assert "Downloads (30d):" not in out
    assert "Likes:" not in out
    assert "Pipeline:" not in out
    assert "Snippet:" not in out
    assert "not available" in out
    assert "popularity, not" not in out
    assert "1200" not in out
    assert "88" not in out
