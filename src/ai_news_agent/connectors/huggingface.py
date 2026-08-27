"""Hugging Face Hub connector: trending model listing (Milestone 6 T2)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.huggingface_families import group_huggingface_families, huggingface_collect_limit
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

if TYPE_CHECKING:
    from huggingface_hub import HfApi


class HuggingFaceConnector:
    """Collects trending Hugging Face models via ``HfApi.list_models``."""

    def __init__(
        self,
        *,
        api: HfApi | None = None,
        token: str | None = None,
    ) -> None:
        self._token = token if token is not None else os.environ.get("HUGGINGFACE_TOKEN") or None
        self._api = api

    def name(self) -> str:
        return "huggingface"

    def _get_api(self) -> HfApi:
        if self._api is None:
            from huggingface_hub import HfApi

            self._api = HfApi(token=self._token)
        return self._api

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        mode = request.huggingface_discovery_mode or "global"
        display_limit = request.max_items
        collect_limit = huggingface_collect_limit(display_limit)
        if mode == "filtered":
            discovery_mode = "filtered"
            list_kwargs: dict[str, Any] = {
                "sort": "trending_score",
                "limit": collect_limit,
                "cardData": True,
            }
            if request.huggingface_search:
                list_kwargs["search"] = request.huggingface_search
            if request.huggingface_pipeline_tag:
                list_kwargs["pipeline_tag"] = request.huggingface_pipeline_tag
        else:
            discovery_mode = "global"
            list_kwargs = {
                "sort": "trending_score",
                "limit": collect_limit,
                "cardData": True,
            }

        api = self._get_api()

        def _fetch_models() -> list[Any]:
            return list(api.list_models(**list_kwargs))

        try:
            models = await asyncio.to_thread(_fetch_models)
        except Exception as exc:
            warning = _warning_for_request_exception(exc)
            return ConnectorResult(items=[], warnings=[warning], raw_count=0)

        collected_at = datetime.now(UTC)
        items: list[NewsItem] = []
        warnings: list[ConnectorWarning] = []
        for model in models:
            if _missing_required_model_fields(model):
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_model",
                        message="Skipped Hugging Face model row missing id",
                        detail=str(getattr(model, "id", None)),
                    )
                )
                continue
            if model.trending_score is None:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="missing_trend_evidence",
                        message=(
                            "Hugging Face model missing native trending_score; "
                            "ranking confidence lowered"
                        ),
                        detail=str(model.id),
                    )
                )
            items.append(_model_to_news_item(model, discovery_mode, collected_at, request.topics))

        grouped_items = group_huggingface_families(items, limit=display_limit)
        return ConnectorResult(items=grouped_items, warnings=warnings, raw_count=len(models))


def _missing_required_model_fields(model: Any) -> bool:
    model_id = getattr(model, "id", None)
    return model_id is None or not str(model_id).strip()


def _warning_for_request_exception(exc: Exception) -> ConnectorWarning:
    message = str(exc).lower()
    status_code = getattr(exc, "response", None)
    if status_code is not None:
        status_code = getattr(status_code, "status_code", None)
    if status_code == 429 or "429" in message or "rate limit" in message:
        return ConnectorWarning(
            connector="huggingface",
            code="rate_limited",
            message="Hugging Face Hub rate limit reached",
            detail=str(exc)[:300],
        )
    return ConnectorWarning(
        connector="huggingface",
        code="request_failed",
        message="Hugging Face list_models request failed",
        detail=str(exc)[:300],
    )


def _model_to_news_item(
    model: Any,
    discovery_mode: str,
    collected_at: datetime,
    request_topics: list[str],
) -> NewsItem:
    model_id = str(model.id)
    title = model_id.rsplit("/", 1)[-1] if "/" in model_id else model_id
    raw_snippet = _card_summary(model)
    tags = ["huggingface", "model"]
    if model.tags:
        tags.extend(str(t) for t in model.tags if t is not None)

    topic_matches = _topic_matches(request_topics, model)
    completeness = _metadata_completeness(model, has_snippet=bool(raw_snippet))
    content_confidence = ConfidenceLevel.MEDIUM if raw_snippet else ConfidenceLevel.LOW
    base_model = _card_base_model(model)

    return NewsItem(
        source=SourceKind.HUGGINGFACE,
        source_id=model_id,
        url=f"https://huggingface.co/{model_id}",
        title=title,
        published_at=model.last_modified,
        collected_at=collected_at,
        author=model.author,
        stars_or_views=None,
        language=None,
        metadata_completeness=completeness,
        raw_snippet=raw_snippet,
        tags=tags,
        topic_matches=topic_matches,
        content_confidence=content_confidence,
        source_evidence={
            "trending_score": model.trending_score,
            "downloads_30d": model.downloads,
            "downloads_all_time": model.downloads_all_time,
            "likes": model.likes,
            "pipeline_tag": model.pipeline_tag,
            "library_name": model.library_name,
            "gated": model.gated,
            "discovery_mode": discovery_mode,
            **({"base_model": base_model} if base_model else {}),
        },
    )


def _card_base_model(model: Any) -> str | None:
    card_data = model.card_data
    if card_data is None:
        return None
    value = getattr(card_data, "base_model", None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _card_summary(model: Any) -> str | None:
    card_data = model.card_data
    if card_data is None:
        return None
    for attr in ("summary", "description"):
        value = getattr(card_data, attr, None)
        if value is not None:
            text = str(value).strip()
            if text:
                return text[:650]
    return None


def _topic_matches(request_topics: list[str], model: Any) -> list[str]:
    parts = [str(model.id or "")]
    if model.pipeline_tag:
        parts.append(str(model.pipeline_tag))
    if model.tags:
        parts.extend(str(t) for t in model.tags if t is not None)
    haystack = " ".join(parts).lower()
    matched: list[str] = []
    for topic in request_topics:
        tl = topic.strip().lower()
        if not tl:
            continue
        if tl in haystack:
            matched.append(topic)
    return matched


def _metadata_completeness(model: Any, *, has_snippet: bool) -> float:
    score = 0.35
    if model.pipeline_tag:
        score += 0.2
    if model.library_name:
        score += 0.15
    if model.trending_score is not None:
        score += 0.15
    if model.downloads is not None:
        score += 0.1
    if has_snippet:
        score += 0.05
    return min(score, 1.0)
