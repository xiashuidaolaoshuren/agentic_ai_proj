"""Hugging Face model family grouping for search and digest selection."""

from __future__ import annotations

import re

from ai_news_agent.models import NewsItem, SourceKind

_SUFFIX_TOKENS: frozenset[str] = frozenset(
    {
        "gguf",
        "mlx",
        "awq",
        "gptq",
        "uncensored",
        "instruct",
        "chat",
        "safetensors",
        "onnx",
        "fp8",
        "fp16",
        "fp4",
        "4bit",
        "8bit",
        "quant",
        "quantized",
    }
)
_SKU_TOKENS: frozenset[str] = frozenset(
    {"pro", "flash", "lite", "mini", "coder", "base", "plus", "max"}
)
_SIZE_TOKEN_RE = re.compile(r"^\d+[bB]$")


def huggingface_collect_limit(display_limit: int) -> int:
    """How many Hub rows to fetch before collapsing to ``display_limit`` families."""
    if display_limit < 1:
        return 20
    return min(40, max(20, 4 * display_limit))


def family_key(item: NewsItem) -> str:
    """Stable key for version + size + SKU, ignoring publisher and packaging."""
    base_model = item.source_evidence.get("base_model")
    if isinstance(base_model, str) and base_model.strip():
        return _normalize_model_id(base_model.strip())
    return _normalize_model_id(item.source_id)


def group_huggingface_families(items: list[NewsItem], *, limit: int) -> list[NewsItem]:
    """Collapse HF packaging variants and return up to ``limit`` family representatives."""
    if limit < 1:
        return []

    families: dict[str, list[NewsItem]] = {}
    order: list[str] = []
    for item in items:
        if item.source is not SourceKind.HUGGINGFACE:
            continue
        key = family_key(item)
        if key not in families:
            families[key] = []
            order.append(key)
        families[key].append(item)

    grouped: list[NewsItem] = []
    for key in order:
        if len(grouped) >= limit:
            break
        members = families[key]
        representative = max(members, key=_trending_score)
        siblings = [member for member in members if member.source_id != representative.source_id]
        if siblings:
            evidence = dict(representative.source_evidence)
            evidence["family_variants"] = [
                {"source_id": sibling.source_id, "title": sibling.title}
                for sibling in siblings
            ]
            representative = representative.model_copy(update={"source_evidence": evidence})
        grouped.append(representative)
    return grouped


def _normalize_model_id(model_id: str) -> str:
    repo_name = model_id.rsplit("/", 1)[-1]
    parts = repo_name.split("-")
    kept: list[str] = []
    for part in parts:
        if not part:
            continue
        lower = part.lower()
        if _SIZE_TOKEN_RE.match(part):
            kept.append(lower)
            continue
        if lower in _SKU_TOKENS:
            kept.append(lower)
            continue
        if lower in _SUFFIX_TOKENS:
            continue
        kept.append(lower)
    return "-".join(kept) if kept else repo_name.lower()


def _trending_score(item: NewsItem) -> float:
    value = item.source_evidence.get("trending_score")
    if isinstance(value, (int, float)):
        return float(value)
    return float("-inf")
