"""Zhihu official search connector: practitioner insights (Milestone 6 T3)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.env import get_zhihu_access_secret
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

DEFAULT_BASE_URL = "https://developer.zhihu.com"
SNIPPET_MAX = 650
THIN_SNIPPET_MAX = 80

PRACTITIONER_LENSES: tuple[str, ...] = (
    "实战 / 踩坑",
    "部署 / 成本",
    "评测 / 对比",
)


class ZhihuConnector:
    """Collects Zhihu practitioner insights via the official search API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._token = token if token is not None else get_zhihu_access_secret()
        self._owns_client = client is None
        self._client = client
        self._base_url = base_url

    def name(self) -> str:
        return "zhihu"

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        warnings: list[ConnectorWarning] = []
        if request.timeframe:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="unsupported_timeframe",
                    message=(
                        "Zhihu search is relevance-based and does not filter "
                        "to the requested timeframe"
                    ),
                    detail=request.timeframe,
                )
            )
        if not self._token:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="auth_missing",
                    message="Zhihu connector skipped: ZHIHU_ACCESS_SECRET is not set",
                )
            )
            return ConnectorResult(items=[], warnings=warnings, raw_count=0)

        queries = expand_zhihu_queries(request.topics)
        count = min(max(request.max_items, 1), 10)
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
            )
            self._owns_client = True
        client = self._client

        collected_at = datetime.now(UTC)
        by_key: dict[str, NewsItem] = {}
        raw_count = 0
        for query, lens in queries:
            try:
                resp = await client.get(
                    "/api/v1/content/zhihu_search",
                    params={"Query": query, "Count": count},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "X-Request-Timestamp": str(int(time.time())),
                    },
                )
            except httpx.RequestError as exc:
                warnings.append(
                    _zhihu_warning(
                        "request_failed",
                        f"Zhihu search request failed: {type(exc).__name__}",
                        str(exc)[:300],
                    )
                )
                return ConnectorResult(items=[], warnings=warnings, raw_count=raw_count)

            status_warning = _warning_for_http_status(resp)
            if status_warning is not None:
                warnings.append(status_warning)
                return ConnectorResult(items=[], warnings=warnings, raw_count=raw_count)

            try:
                data = resp.json()
            except ValueError as exc:
                warnings.append(
                    _zhihu_warning(
                        "invalid_search_response",
                        "Zhihu search response was not valid JSON",
                        str(exc)[:300],
                    )
                )
                return ConnectorResult(items=[], warnings=warnings, raw_count=raw_count)

            envelope_warning, rows = _parse_search_envelope(data)
            if envelope_warning is not None:
                warnings.append(envelope_warning)
                return ConnectorResult(items=[], warnings=warnings, raw_count=raw_count)

            for row in rows:
                if not isinstance(row, dict):
                    warnings.append(
                        _zhihu_warning(
                            "skipped_malformed_result",
                            "Skipped non-object Zhihu search row",
                        )
                    )
                    raw_count += 1
                    continue
                raw_count += 1
                title = str(row.get("Title") or "").strip()
                url = str(row.get("Url") or "").strip()
                if not title or not url:
                    warnings.append(
                        _zhihu_warning(
                            "skipped_malformed_result",
                            "Skipped Zhihu search row missing title or URL",
                            str(row.get("ContentID") or url or None),
                        )
                    )
                    continue
                key = _dedupe_key(row)
                if key in by_key:
                    continue
                item = _row_to_news_item(row, lens, request.topics, collected_at)
                if item.content_confidence is ConfidenceLevel.LOW:
                    warnings.append(
                        _zhihu_warning(
                            "thin_evidence",
                            "Zhihu result kept with thin returned text; discovery-only",
                            item.source_id,
                        )
                    )
                by_key[key] = item
        items = list(by_key.values())[: request.max_items]
        return ConnectorResult(items=items, warnings=warnings, raw_count=raw_count)


def _zhihu_warning(code: str, message: str, detail: str | None = None) -> ConnectorWarning:
    return ConnectorWarning(
        connector="zhihu",
        code=code,
        message=message,
        detail=detail,
    )


def _is_quota_envelope(code: Any, message: str) -> bool:
    lowered = message.lower()
    if "quota" in lowered or "限流" in message or "频率" in message:
        return True
    try:
        return int(code) == 429
    except (TypeError, ValueError):
        return False


def _warning_for_http_status(resp: httpx.Response) -> ConnectorWarning | None:
    if resp.status_code in (401, 403):
        return _zhihu_warning(
            "auth_rejected",
            f"Zhihu search rejected authentication (HTTP {resp.status_code})",
            (resp.text or "")[:300] or None,
        )
    if resp.status_code == 429:
        return _zhihu_warning(
            "quota_exhausted",
            "Zhihu search quota exhausted",
            (resp.text or "")[:300] or None,
        )
    if resp.status_code != 200:
        return _zhihu_warning(
            "request_failed",
            f"Zhihu search failed with HTTP {resp.status_code}",
            (resp.text or "")[:300] or None,
        )
    return None


def _parse_search_envelope(
    data: Any,
) -> tuple[ConnectorWarning | None, list[Any]]:
    if not isinstance(data, dict):
        return (
            _zhihu_warning(
                "invalid_search_response",
                "Zhihu search JSON was not an object",
            ),
            [],
        )
    code = data.get("Code", 0)
    message = str(data.get("Message") or "")
    if code not in (0, "0", None):
        if _is_quota_envelope(code, message):
            return (
                _zhihu_warning(
                    "quota_exhausted",
                    "Zhihu search quota exhausted",
                    message[:300] or None,
                ),
                [],
            )
        return (
            _zhihu_warning(
                "invalid_search_response",
                f"Zhihu search envelope Code={code}",
                message[:300] or None,
            ),
            [],
        )
    payload = data.get("Data")
    if not isinstance(payload, dict):
        return (
            _zhihu_warning(
                "invalid_search_response",
                "Zhihu search JSON missing object Data",
            ),
            [],
        )
    rows = payload.get("Items")
    if not isinstance(rows, list):
        return (
            _zhihu_warning(
                "invalid_search_response",
                "Zhihu search JSON missing list Data.Items",
            ),
            [],
        )
    return None, rows


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    scheme = (parsed.scheme or "https").lower()
    return f"{scheme}://{host}{path}"


def _dedupe_key(row: dict[str, Any]) -> str:
    content_id = str(row.get("ContentID") or "").strip()
    if content_id:
        return f"id:{content_id}"
    return f"url:{_canonical_url(str(row.get('Url') or ''))}"


def expand_zhihu_queries(topics: list[str]) -> list[tuple[str, str]]:
    first = next((topic.strip() for topic in topics if topic and topic.strip()), None)
    if first is None:
        return []
    return [(f"{first} {lens.replace(' / ', ' ')}", lens) for lens in PRACTITIONER_LENSES]


def _row_to_news_item(
    row: dict[str, Any],
    query_lens: str,
    request_topics: list[str],
    collected_at: datetime,
) -> NewsItem:
    content_id = str(row.get("ContentID") or "").strip()
    url = str(row.get("Url") or "").strip()
    title = str(row.get("Title") or "").strip()
    content_text = str(row.get("ContentText") or "")
    content_type = str(row.get("ContentType") or "").strip()
    author = str(row.get("AuthorName") or "").strip() or None
    relevance = row.get("Relevance")
    snippet = content_text.strip()[:SNIPPET_MAX] or None
    tags = ["zhihu"]
    if content_type:
        tags.append(content_type)
    haystack = f"{title} {content_text}".lower()
    topic_matches = [
        topic
        for topic in request_topics
        if topic.strip() and topic.strip().lower() in haystack
    ]
    confidence = (
        ConfidenceLevel.MEDIUM
        if len(content_text.strip()) >= THIN_SNIPPET_MAX
        else ConfidenceLevel.LOW
    )
    return NewsItem(
        source=SourceKind.ZHIHU,
        source_id=content_id if content_id else url,
        url=url,
        title=title,
        collected_at=collected_at,
        author=author,
        stars_or_views=None,
        language="zh",
        raw_snippet=snippet,
        tags=tags,
        topic_matches=topic_matches,
        content_confidence=confidence,
        source_evidence={
            "relevance": relevance,
            "query_lens": query_lens,
            "source_label": content_type or None,
            "evidence_text_length": len(content_text),
        },
    )
