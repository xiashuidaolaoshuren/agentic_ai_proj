"""Tests for Hugging Face model family grouping."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.models import ConfidenceLevel, NewsItem, SourceKind


def _hf_item(
    *,
    source_id: str,
    title: str | None = None,
    trending_score: float = 10.0,
    base_model: str | None = None,
) -> NewsItem:
    evidence: dict[str, object] = {"trending_score": trending_score}
    if base_model is not None:
        evidence["base_model"] = base_model
    return NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id=source_id,
        url=f"https://huggingface.co/{source_id}",
        title=title or source_id.rsplit("/", 1)[-1],
        collected_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        content_confidence=ConfidenceLevel.HIGH,
        source_evidence=evidence,
    )


def test_group_huggingface_families_collapses_format_variants() -> None:
    from ai_news_agent.huggingface_families import group_huggingface_families

    items = [
        _hf_item(source_id="Qwen/Qwen3.8-27B", trending_score=100.0),
        _hf_item(source_id="Someone/Qwen3.8-27B-GGUF", trending_score=50.0),
        _hf_item(source_id="Other/Qwen3.8-27B-Uncensored-MLX", trending_score=30.0),
    ]

    grouped = group_huggingface_families(items, limit=5)

    assert len(grouped) == 1
    assert grouped[0].source_id == "Qwen/Qwen3.8-27B"
    variants = grouped[0].source_evidence["family_variants"]
    assert len(variants) == 2
    variant_ids = {variant["source_id"] for variant in variants}
    assert variant_ids == {
        "Someone/Qwen3.8-27B-GGUF",
        "Other/Qwen3.8-27B-Uncensored-MLX",
    }


def test_group_huggingface_families_keeps_different_sizes_separate() -> None:
    from ai_news_agent.huggingface_families import group_huggingface_families

    items = [
        _hf_item(source_id="Qwen/Qwen3.8-8B", trending_score=90.0),
        _hf_item(source_id="Qwen/Qwen3.8-27B", trending_score=80.0),
    ]

    grouped = group_huggingface_families(items, limit=5)

    assert len(grouped) == 2
    assert {item.source_id for item in grouped} == {
        "Qwen/Qwen3.8-8B",
        "Qwen/Qwen3.8-27B",
    }


def test_group_huggingface_families_keeps_product_skus_separate() -> None:
    from ai_news_agent.huggingface_families import group_huggingface_families

    items = [
        _hf_item(source_id="deepseek-ai/deepseek-v4-pro", trending_score=90.0),
        _hf_item(source_id="deepseek-ai/deepseek-v4-flash", trending_score=80.0),
    ]

    grouped = group_huggingface_families(items, limit=5)

    assert len(grouped) == 2


def test_group_huggingface_families_respects_limit_after_collapse() -> None:
    from ai_news_agent.huggingface_families import group_huggingface_families

    items = [
        _hf_item(source_id="org/a-27B", trending_score=100.0),
        _hf_item(source_id="org/a-27B-GGUF", trending_score=99.0),
        _hf_item(source_id="org/b-27B", trending_score=90.0),
        _hf_item(source_id="org/c-27B", trending_score=80.0),
        _hf_item(source_id="org/d-27B", trending_score=70.0),
        _hf_item(source_id="org/e-27B", trending_score=60.0),
        _hf_item(source_id="org/f-27B", trending_score=50.0),
    ]

    grouped = group_huggingface_families(items, limit=5)

    assert len(grouped) == 5


def test_huggingface_collect_limit_over_fetches_for_family_collapse() -> None:
    from ai_news_agent.huggingface_families import huggingface_collect_limit

    assert huggingface_collect_limit(5) == 20
    assert huggingface_collect_limit(10) == 40


def test_render_search_items_text_includes_also_line_for_family_variants() -> None:
    from ai_news_agent.rendering import render_search_items_text

    item = _hf_item(source_id="Qwen/Qwen3.8-27B", trending_score=100.0)
    item = item.model_copy(
        update={
            "source_evidence": {
                **item.source_evidence,
                "family_variants": [
                    {"source_id": "Someone/Qwen3.8-27B-GGUF", "title": "Qwen3.8-27B-GGUF"},
                ],
            }
        }
    )

    out = render_search_items_text([item])

    assert "Also:" in out
    assert "Qwen3.8-27B-GGUF" in out
