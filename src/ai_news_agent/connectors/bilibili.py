"""Bilibili metadata connector (Task 6): keyword search, uploader feeds, manual URLs.

Uses public web-interface JSON endpoints only (metadata-first; no transcript scraping).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

DEFAULT_BASE = "https://api.bilibili.com"
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; ai-news-agent/0.1)",
    "Referer": "https://www.bilibili.com",
}
# Real BV ids are typically 12 chars (e.g. BV1…); allow short test-style ids.
_BVID_IN_TEXT = re.compile(r"(BV[0-9A-Za-z]{8,14})", re.IGNORECASE)


class BilibiliConnector:
    """Fetch Bilibili video metadata via conservative API calls."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(30.0),
        )

    def name(self) -> str:
        return "bilibili"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        warnings: list[ConnectorWarning] = []
        if (
            not request.topics
            and not request.target_channels
            and not request.manual_urls
        ):
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="no_input",
                    message="Bilibili connector skipped: topics, target_channels, and manual_urls are all empty",
                )
            )
            return ConnectorResult(items=[], warnings=warnings, raw_count=0)

        by_bvid: dict[str, NewsItem] = {}
        raw_total = 0
        now = datetime.now(UTC)

        if request.topics:
            items, n_raw, ws = await self._keyword_search(request, now)
            raw_total += n_raw
            warnings.extend(ws)
            for it in items:
                by_bvid[it.source_id] = it

        for channel in request.target_channels:
            items, n_raw, ws = await self._uploader_videos(request, channel, now)
            raw_total += n_raw
            warnings.extend(ws)
            for it in items:
                by_bvid[it.source_id] = it

        for url in request.manual_urls:
            item, n_raw, ws = await self._manual_url_item(url, request.topics, now)
            raw_total += n_raw
            warnings.extend(ws)
            if item is not None:
                by_bvid[item.source_id] = item

        merged = list(by_bvid.values())

        def _sort_key(it: NewsItem) -> float:
            if it.published_at is None:
                return 0.0
            return it.published_at.timestamp()

        merged.sort(key=_sort_key, reverse=True)
        merged = merged[: request.max_items]

        return ConnectorResult(items=merged, warnings=warnings, raw_count=raw_total)

    async def _keyword_search(
        self,
        request: ConnectorRequest,
        collected_at: datetime,
    ) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
        warnings: list[ConnectorWarning] = []
        keyword = " ".join(t.strip() for t in request.topics if t and str(t).strip())
        if not keyword:
            return [], 0, warnings

        try:
            resp = await self._client.get(
                "/x/web-interface/search/type",
                params={
                    "search_type": "video",
                    "keyword": keyword,
                    "page": 1,
                    "page_size": min(request.max_items, 20),
                },
            )
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message="Bilibili keyword search request failed",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        if resp.status_code != 200:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message=f"Bilibili keyword search HTTP {resp.status_code}",
                    detail=resp.text[:300] if resp.text else None,
                )
            )
            return [], 0, warnings

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message="Bilibili keyword search response was not valid JSON",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        if int(payload.get("code", -1)) != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message=f"Bilibili keyword search returned code={payload.get('code')!r}",
                    detail=str(payload.get("message")),
                )
            )
            return [], 0, warnings

        data = payload.get("data") or {}
        note = data.get("note")
        if note:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="metadata_limited",
                    message=str(note),
                )
            )

        rows = data.get("result") or []
        items: list[NewsItem] = []
        raw_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            t = row.get("type")
            if t is not None and t != "video":
                continue
            raw_count += 1
            it = _video_row_to_news_item(row, request.topics, collected_at)
            if it is None:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_video",
                        message="Skipped search row missing bvid or title",
                    )
                )
                continue
            items.append(it)

        return items, raw_count, warnings

    async def _uploader_videos(
        self,
        request: ConnectorRequest,
        channel: str,
        collected_at: datetime,
    ) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
        warnings: list[ConnectorWarning] = []
        channel = str(channel).strip()
        if not channel:
            return [], 0, warnings

        mid = await self._resolve_mid(channel, warnings)
        if mid is None:
            return [], 0, warnings

        try:
            resp = await self._client.get(
                "/x/space/arc/search",
                params={
                    "mid": mid,
                    "pn": 1,
                    "ps": min(request.max_items, 30),
                },
            )
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="space_search_failed",
                    message=f"Bilibili space archive search failed for mid={mid}",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        if resp.status_code != 200:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="space_search_failed",
                    message=f"Bilibili space search HTTP {resp.status_code} for mid={mid}",
                    detail=resp.text[:300] if resp.text else None,
                )
            )
            return [], 0, warnings

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="space_search_failed",
                    message="Bilibili space search response was not valid JSON",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        if int(payload.get("code", -1)) != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="space_search_failed",
                    message=f"Bilibili space search returned code={payload.get('code')!r} for mid={mid}",
                    detail=str(payload.get("message")),
                )
            )
            return [], 0, warnings

        data = payload.get("data") or {}
        vlist = (data.get("list") or {}).get("vlist") or []
        items: list[NewsItem] = []
        raw_count = 0
        for row in vlist:
            if not isinstance(row, dict):
                continue
            raw_count += 1
            it = _video_row_to_news_item(row, request.topics, collected_at)
            if it is None:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_video",
                        message=f"Skipped space row missing bvid or title (mid={mid})",
                    )
                )
                continue
            items.append(it)

        return items, raw_count, warnings

    async def _resolve_mid(
        self,
        channel: str,
        warnings: list[ConnectorWarning],
    ) -> int | None:
        if channel.isdigit():
            return int(channel)

        try:
            resp = await self._client.get(
                "/x/web-interface/search/type",
                params={
                    "search_type": "bili_user",
                    "keyword": channel,
                    "page": 1,
                },
            )
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="user_search_failed",
                    message=f"Bilibili user search failed for {channel!r}",
                    detail=str(exc),
                )
            )
            return None

        if resp.status_code != 200:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="user_search_failed",
                    message=f"Bilibili user search HTTP {resp.status_code} for {channel!r}",
                )
            )
            return None

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="user_search_failed",
                    message="Bilibili user search response was not valid JSON",
                    detail=str(exc),
                )
            )
            return None

        if int(payload.get("code", -1)) != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="user_search_failed",
                    message=f"Bilibili user search returned code={payload.get('code')!r}",
                    detail=str(payload.get("message")),
                )
            )
            return None

        rows = (payload.get("data") or {}).get("result") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("mid") is not None:
                try:
                    return int(row["mid"])
                except (TypeError, ValueError):
                    continue

        warnings.append(
            ConnectorWarning(
                connector=self.name(),
                code="unresolved_channel",
                message=f"Could not resolve Bilibili uploader/channel: {channel!r}",
            )
        )
        return None

    async def _manual_url_item(
        self,
        url: str,
        topics: list[str],
        collected_at: datetime,
    ) -> tuple[NewsItem | None, int, list[ConnectorWarning]]:
        warnings: list[ConnectorWarning] = []
        bvid = _extract_bvid(url)
        if not bvid:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="invalid_manual_url",
                    message="Could not parse a Bilibili BV id from manual URL",
                    detail=url[:200],
                )
            )
            return None, 0, warnings

        try:
            resp = await self._client.get(
                "/x/web-interface/view",
                params={"bvid": bvid},
            )
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="view_fetch_failed",
                    message=f"Bilibili view lookup failed for {bvid}",
                    detail=str(exc),
                )
            )
            return None, 1, warnings

        if resp.status_code != 200:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="view_fetch_failed",
                    message=f"Bilibili view HTTP {resp.status_code} for {bvid}",
                )
            )
            return None, 1, warnings

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="view_fetch_failed",
                    message=f"Bilibili view response was not valid JSON for {bvid}",
                    detail=str(exc),
                )
            )
            return None, 1, warnings

        if int(payload.get("code", -1)) != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="view_fetch_failed",
                    message=f"Bilibili view returned code={payload.get('code')!r} for {bvid}",
                    detail=str(payload.get("message")),
                )
            )
            return None, 1, warnings

        data = payload.get("data") or {}
        it = _view_data_to_news_item(data, topics, collected_at)
        if it is None:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="skipped_malformed_video",
                    message=f"Skipped view payload missing fields for {bvid}",
                )
            )
            return None, 1, warnings

        return it, 1, warnings


def _extract_bvid(text: str) -> str | None:
    text = text.strip()
    m = _BVID_IN_TEXT.search(text)
    if m:
        return m.group(1)
    return None


def _topic_matches(request_topics: list[str], title: str, snippet: str, author: str) -> list[str]:
    hay = f"{title} {snippet} {author}".lower()
    matched: list[str] = []
    for t in request_topics:
        tl = t.strip().lower()
        if not tl:
            continue
        if tl in hay:
            matched.append(t)
            continue
        for w in tl.split():
            if len(w) > 2 and w in hay:
                matched.append(t)
                break
    return matched


def _video_row_to_news_item(
    row: dict[str, Any],
    request_topics: list[str],
    collected_at: datetime,
) -> NewsItem | None:
    bvid = row.get("bvid")
    title = row.get("title")
    if not bvid or not title:
        return None
    bvid = str(bvid)
    title = str(title).strip()
    url = f"https://www.bilibili.com/video/{bvid}"

    desc = row.get("description")
    if desc is not None:
        desc = str(desc).strip() or None

    author = row.get("author")
    if author is not None:
        author = str(author)

    views = row.get("play")
    try:
        stars = int(views) if views is not None else None
    except (TypeError, ValueError):
        stars = None

    published_at: datetime | None = None
    ct = row.get("created") or row.get("pubdate")
    if isinstance(ct, (int, float)):
        published_at = datetime.fromtimestamp(float(ct), tz=UTC)

    completeness = 0.5 if desc else 0.25
    topic_matches = _topic_matches(request_topics, title, desc or "", author or "")

    return NewsItem(
        source=SourceKind.BILIBILI,
        source_id=bvid,
        url=url,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=author,
        stars_or_views=stars,
        language=None,
        metadata_completeness=completeness,
        raw_snippet=desc,
        tags=["bilibili", "video"],
        topic_matches=topic_matches,
        content_confidence=ConfidenceLevel.LOW,
    )


def _view_data_to_news_item(
    data: dict[str, Any],
    request_topics: list[str],
    collected_at: datetime,
) -> NewsItem | None:
    bvid = data.get("bvid")
    title = data.get("title")
    if not bvid or not title:
        return None
    bvid = str(bvid)
    title = str(title).strip()
    url = f"https://www.bilibili.com/video/{bvid}"

    desc = data.get("desc")
    if desc is not None:
        desc = str(desc).strip() or None

    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    author = owner.get("name")
    if author is not None:
        author = str(author)

    stat = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    v = stat.get("view")
    try:
        stars = int(v) if v is not None else None
    except (TypeError, ValueError):
        stars = None

    pub = data.get("pubdate")
    published_at: datetime | None = None
    if isinstance(pub, (int, float)):
        published_at = datetime.fromtimestamp(float(pub), tz=UTC)

    completeness = 0.55 if desc else 0.3
    topic_matches = _topic_matches(request_topics, title, desc or "", author or "")

    return NewsItem(
        source=SourceKind.BILIBILI,
        source_id=bvid,
        url=url,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=author,
        stars_or_views=stars,
        language=None,
        metadata_completeness=completeness,
        raw_snippet=desc,
        tags=["bilibili", "video"],
        topic_matches=topic_matches,
        content_confidence=ConfidenceLevel.LOW,
    )
