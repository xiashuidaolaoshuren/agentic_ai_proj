"""Bilibili metadata connector: keyword search, uploader feeds, manual URLs.

Uses public web-interface JSON endpoints (metadata-first; no transcript scraping).
Includes retry/backoff for anti-bot HTTP 412 and optional session cookies.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.env import get_bilibili_cookie
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

DEFAULT_BASE = "https://api.bilibili.com"
_RETRYABLE_STATUS = frozenset({412, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
# Real BV ids are typically 12 chars (e.g. BV1…); allow short test-style ids.
_BVID_IN_TEXT = re.compile(r"(BV[0-9A-Za-z]{8,14})", re.IGNORECASE)


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _cookie_raw_to_dict(raw: str) -> dict[str, str]:
    s = raw.strip()
    if not s:
        return {}
    if "=" not in s:
        return {"SESSDATA": s}
    out: dict[str, str] = {}
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def _http_warning_code(status: int) -> str:
    if status == 412:
        return "anti_bot_blocked"
    if status == 429:
        return "rate_limited"
    return "http_error"


def _dedupe_warnings(warnings: list[ConnectorWarning]) -> list[ConnectorWarning]:
    seen: set[tuple[str, str, str, str | None]] = set()
    out: list[ConnectorWarning] = []
    for w in warnings:
        key = (w.connector, w.code, w.message, w.detail)
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _json_parse_detail(resp: httpx.Response, exc: ValueError) -> str:
    content_type = resp.headers.get("content-type") or resp.headers.get("Content-Type") or ""
    snippet = (resp.text or "").strip()[:200]
    return f"{exc}; content-type={content_type!r}; body={snippet!r}"


def _warning_for_invalid_json(
    resp: httpx.Response,
    *,
    operation: str,
    failure_code: str,
    exc: ValueError,
) -> ConnectorWarning:
    content_type = (resp.headers.get("content-type") or "").lower()
    snippet = (resp.text or "").lstrip()
    if "text/html" in content_type or snippet.startswith("<"):
        return ConnectorWarning(
            connector="bilibili",
            code="anti_bot_blocked",
            message=(
                f"Bilibili {operation} returned non-JSON (likely HTML challenge). "
                "Set BILIBILI_COOKIE or use video URLs/channels."
            ),
            detail=_json_parse_detail(resp, exc),
        )
    return ConnectorWarning(
        connector="bilibili",
        code="invalid_payload",
        message=f"Bilibili {operation} response was not valid JSON",
        detail=_json_parse_detail(resp, exc),
    )


def _http_warning_message(operation: str, status: int) -> str:
    if status == 412:
        return (
            f"Bilibili {operation} blocked with HTTP 412 (anti-bot). "
            "Set BILIBILI_COOKIE or BILIBILI_SESSDATA in .env, or use video URLs/channels."
        )
    return f"Bilibili {operation} HTTP {status}"


class BilibiliConnector:
    """Fetch Bilibili video metadata via conservative API calls."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE,
        cookie: str | None = None,
    ) -> None:
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            cookie_raw = cookie if cookie is not None else get_bilibili_cookie()
            cookies = _cookie_raw_to_dict(cookie_raw) if cookie_raw else None
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers=_browser_headers(),
                cookies=cookies,
                timeout=httpx.Timeout(30.0),
            )

    def name(self) -> str:
        return "bilibili"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        warnings: list[ConnectorWarning] = []
        bili_urls = list(request.bilibili_manual_urls) or list(request.manual_urls)
        bili_channels = list(request.bilibili_target_channels) or list(request.target_channels)
        if (
            not request.topics
            and not bili_channels
            and not bili_urls
        ):
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="no_input",
                    message=(
                        "Bilibili connector skipped: topics, bilibili_target_channels, "
                        "and bilibili_manual_urls are all empty"
                    ),
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

        for channel in bili_channels:
            items, n_raw, ws = await self._uploader_videos(request, channel, now)
            raw_total += n_raw
            warnings.extend(ws)
            for it in items:
                by_bvid[it.source_id] = it

        for url in bili_urls:
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

        return ConnectorResult(
            items=merged,
            warnings=_dedupe_warnings(warnings),
            raw_count=raw_total,
        )

    async def _api_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        warnings: list[ConnectorWarning],
        operation: str,
        failure_code: str,
    ) -> httpx.Response | None:
        last_resp: httpx.Response | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code=failure_code,
                        message=f"Bilibili {operation} request failed",
                        detail=str(exc),
                    )
                )
                return None

            if resp.status_code == 200:
                return resp

            last_resp = resp
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            break

        if last_resp is None:
            return None

        status = last_resp.status_code
        code = _http_warning_code(status) if status in _RETRYABLE_STATUS else failure_code
        detail = last_resp.text[:300] if last_resp.text else None
        warnings.append(
            ConnectorWarning(
                connector=self.name(),
                code=code,
                message=_http_warning_message(operation, status),
                detail=detail,
            )
        )
        return last_resp

    async def _keyword_search(
        self,
        request: ConnectorRequest,
        collected_at: datetime,
    ) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
        warnings: list[ConnectorWarning] = []
        topics = [t.strip() for t in request.topics if t and str(t).strip()]
        if not topics:
            return [], 0, warnings

        combined = " ".join(topics)
        items, n_raw, ws = await self._keyword_search_once(
            request, collected_at, combined
        )
        warnings.extend(ws)
        if items:
            return items, n_raw, warnings

        if len(topics) <= 1:
            return items, n_raw, warnings

        by_bvid: dict[str, NewsItem] = {}
        total_raw = 0
        for topic in topics:
            part_items, part_raw, part_ws = await self._keyword_search_once(
                request, collected_at, topic
            )
            total_raw += part_raw
            warnings.extend(part_ws)
            for it in part_items:
                by_bvid[it.source_id] = it

        if by_bvid:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_fallback",
                    message="Used per-topic Bilibili keyword search after combined query failed",
                )
            )
        return list(by_bvid.values()), total_raw, warnings

    async def _keyword_search_once(
        self,
        request: ConnectorRequest,
        collected_at: datetime,
        keyword: str,
    ) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
        local_warnings: list[ConnectorWarning] = []
        resp = await self._api_get(
            "/x/web-interface/search/type",
            params={
                "search_type": "video",
                "keyword": keyword,
                "page": 1,
                "page_size": min(request.max_items, 20),
            },
            warnings=local_warnings,
            operation="keyword search",
            failure_code="keyword_search_failed",
        )
        if resp is None or resp.status_code != 200:
            return [], 0, list(local_warnings)

        try:
            payload = resp.json()
        except ValueError as exc:
            local_warnings.append(
                _warning_for_invalid_json(
                    resp,
                    operation="keyword search",
                    failure_code="keyword_search_failed",
                    exc=exc,
                )
            )
            return [], 0, local_warnings

        if int(payload.get("code", -1)) != 0:
            local_warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message=f"Bilibili keyword search returned code={payload.get('code')!r}",
                    detail=str(payload.get("message")),
                )
            )
            return [], 0, local_warnings

        data = payload.get("data") or {}
        note = data.get("note")
        if note:
            local_warnings.append(
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
                local_warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_video",
                        message="Skipped search row missing bvid or title",
                    )
                )
                continue
            items.append(it)

        return items, raw_count, local_warnings

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

        local_warnings: list[ConnectorWarning] = []
        resp = await self._api_get(
            "/x/space/arc/search",
            params={
                "mid": mid,
                "pn": 1,
                "ps": min(request.max_items, 30),
            },
            warnings=local_warnings,
            operation=f"space search (mid={mid})",
            failure_code="space_search_failed",
        )
        warnings.extend(local_warnings)
        if resp is None or resp.status_code != 200:
            return [], 0, warnings

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                _warning_for_invalid_json(
                    resp,
                    operation=f"space search (mid={mid})",
                    failure_code="space_search_failed",
                    exc=exc,
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

        local_warnings: list[ConnectorWarning] = []
        resp = await self._api_get(
            "/x/web-interface/search/type",
            params={
                "search_type": "bili_user",
                "keyword": channel,
                "page": 1,
            },
            warnings=local_warnings,
            operation=f"user search ({channel!r})",
            failure_code="user_search_failed",
        )
        warnings.extend(local_warnings)
        if resp is None or resp.status_code != 200:
            return None

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                _warning_for_invalid_json(
                    resp,
                    operation=f"user search ({channel!r})",
                    failure_code="user_search_failed",
                    exc=exc,
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
        bvid = extract_bvid(url)
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

        local_warnings: list[ConnectorWarning] = []
        resp = await self._api_get(
            "/x/web-interface/view",
            params={"bvid": bvid},
            warnings=local_warnings,
            operation=f"view ({bvid})",
            failure_code="view_fetch_failed",
        )
        warnings.extend(local_warnings)
        if resp is None or resp.status_code != 200:
            return None, 1, warnings

        try:
            payload = resp.json()
        except ValueError as exc:
            warnings.append(
                _warning_for_invalid_json(
                    resp,
                    operation=f"view ({bvid})",
                    failure_code="view_fetch_failed",
                    exc=exc,
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


def extract_bvid(text: str) -> str | None:
    text = text.strip()
    m = _BVID_IN_TEXT.search(text)
    if m:
        return m.group(1)
    return None


def _extract_bvid(text: str) -> str | None:
    """Backward-compatible alias."""
    return extract_bvid(text)


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
