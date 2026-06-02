"""Bilibili metadata connector via bilibili-api-python.

Keyword search, uploader feeds, and manual BV/URL resolution. Metadata-first;
subtitle/transcript hooks reserved for a later milestone.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from bilibili_api import Credential, search, user, video
from bilibili_api.exceptions import ArgsException, NetworkException, ResponseCodeException
from bilibili_api.search import SearchObjectType
from bilibili_api.video_zone import VideoZoneTypes

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.env import get_bilibili_credential
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

# Real BV ids are typically 12 chars (e.g. BV1…); allow short test-style ids.
_BVID_IN_TEXT = re.compile(r"(BV[0-9A-Za-z]{8,14})", re.IGNORECASE)


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


def _timeframe_to_dates(timeframe: str | None) -> tuple[str | None, str | None]:
    """Map digest timeframe to Bilibili search ``time_start`` / ``time_end`` (YYYY-MM-DD)."""
    if not timeframe:
        return None, None
    key = timeframe.strip().lower()
    today = datetime.now(UTC).date()
    end = today.isoformat()
    if key in ("today",):
        start = today.isoformat()
        time_end = (today + timedelta(days=1)).isoformat()
        return start, time_end
    if key in ("this week", "week", "last_7_days"):
        start = (today - timedelta(days=7)).isoformat()
        return start, end
    if key in ("this month", "month", "last_30_days"):
        start = (today - timedelta(days=30)).isoformat()
        return start, end
    return None, None


def _timeframe_bounds(
    timeframe: str | None,
) -> tuple[datetime | None, datetime | None]:
    """Return UTC ``(start_inclusive, end_exclusive)`` for item recency filtering."""
    if not timeframe:
        return None, None
    key = timeframe.strip().lower()
    today = datetime.now(UTC).date()
    if key in ("today",):
        start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        return start, start + timedelta(days=1)
    if key in ("this week", "week", "last_7_days"):
        start_date = today - timedelta(days=7)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_exclusive = datetime.combine(
            today + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        return start, end_exclusive
    if key in ("this month", "month", "last_30_days"):
        start_date = today - timedelta(days=30)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_exclusive = datetime.combine(
            today + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        return start, end_exclusive
    return None, None


def _merge_news_item(existing: NewsItem | None, incoming: NewsItem) -> NewsItem:
    """Prefer the row with a publish time; when both have one, keep the newer."""
    if existing is None:
        return incoming
    if existing.published_at is None:
        return incoming
    if incoming.published_at is None:
        return existing
    if incoming.published_at >= existing.published_at:
        return incoming
    return existing


def _news_item_sort_key(item: NewsItem) -> tuple[float, str]:
    if item.published_at is None:
        return (float("-inf"), item.source_id)
    return (item.published_at.timestamp(), item.source_id)


def _item_within_timeframe(item: NewsItem, timeframe: str | None) -> bool:
    start, end_exclusive = _timeframe_bounds(timeframe)
    if start is None or end_exclusive is None:
        return True
    if item.published_at is None:
        return False
    return start <= item.published_at < end_exclusive


def _unwrap_payload(payload: Any) -> tuple[dict[str, Any], int, str | None]:
    """Normalize library/API dicts to ``(data, code, message)``."""
    if not isinstance(payload, dict):
        return {}, -1, "response was not a dict"
    if "code" in payload and "data" in payload:
        code = int(payload.get("code", -1))
        data = payload.get("data")
        if isinstance(data, dict):
            return data, code, str(payload.get("message")) if payload.get("message") else None
        return {}, code, str(payload.get("message")) if payload.get("message") else None
    return payload, 0, None


def _warning_from_exception(
    exc: BaseException,
    *,
    operation: str,
    failure_code: str,
) -> ConnectorWarning:
    if isinstance(exc, ResponseCodeException):
        code = getattr(exc, "code", None)
        msg = str(getattr(exc, "msg", exc) or exc)
        detail = str(getattr(exc, "raw", "") or "")[:300] or None
        if code in (-412, 412) or "412" in msg:
            return ConnectorWarning(
                connector="bilibili",
                code="anti_bot_blocked",
                message=(
                    f"Bilibili {operation} blocked (anti-bot). "
                    "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 "
                    "in .env, or use video URLs/channels."
                ),
                detail=detail or msg,
            )
        if code in (-429, 429):
            return ConnectorWarning(
                connector="bilibili",
                code="rate_limited",
                message=f"Bilibili {operation} rate limited",
                detail=detail or msg,
            )
        return ConnectorWarning(
            connector="bilibili",
            code=failure_code,
            message=f"Bilibili {operation} returned code={code!r}",
            detail=detail or msg,
        )
    if isinstance(exc, NetworkException):
        text = str(exc)
        lower = text.lower()
        if "html" in lower or text.lstrip().startswith("<"):
            return ConnectorWarning(
                connector="bilibili",
                code="anti_bot_blocked",
                message=(
                    f"Bilibili {operation} returned non-JSON (likely HTML challenge). "
                    "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 "
                    "in .env, or use video URLs/channels."
                ),
                detail=text[:300],
            )
        return ConnectorWarning(
            connector="bilibili",
            code=failure_code,
            message=f"Bilibili {operation} request failed",
            detail=text[:300],
        )
    return ConnectorWarning(
        connector="bilibili",
        code=failure_code,
        message=f"Bilibili {operation} failed",
        detail=str(exc)[:300],
    )


def _warning_for_client_error(
    exc: BaseException,
    *,
    operation: str,
    failure_code: str,
) -> ConnectorWarning:
    return ConnectorWarning(
        connector="bilibili",
        code=failure_code,
        message=f"Bilibili {operation} date range or arguments invalid",
        detail=str(exc)[:300],
    )


class BilibiliConnector:
    """Fetch Bilibili video metadata via bilibili-api-python."""

    def __init__(
        self,
        *,
        credential: Credential | None = None,
    ) -> None:
        self._credential = (
            credential if credential is not None else get_bilibili_credential()
        )

    def name(self) -> str:
        return "bilibili"

    async def aclose(self) -> None:
        """No persistent HTTP client; kept for CLI/workflow symmetry."""

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        warnings: list[ConnectorWarning] = []
        bili_urls = list(request.bilibili_manual_urls) or list(request.manual_urls)
        bili_channels = list(request.bilibili_target_channels) or list(
            request.target_channels
        )
        if not request.topics and not bili_channels and not bili_urls:
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
                by_bvid[it.source_id] = _merge_news_item(by_bvid.get(it.source_id), it)

        for channel in bili_channels:
            items, n_raw, ws = await self._uploader_videos(request, channel, now)
            raw_total += n_raw
            warnings.extend(ws)
            for it in items:
                by_bvid[it.source_id] = _merge_news_item(by_bvid.get(it.source_id), it)

        for url in bili_urls:
            item, n_raw, ws = await self._manual_url_item(
                url, request.topics, now, timeframe=request.timeframe
            )
            raw_total += n_raw
            warnings.extend(ws)
            if item is not None:
                by_bvid[item.source_id] = _merge_news_item(
                    by_bvid.get(item.source_id), item
                )

        merged = list(by_bvid.values())
        merged.sort(key=_news_item_sort_key, reverse=True)
        merged = merged[: request.max_items]

        return ConnectorResult(
            items=merged,
            warnings=_dedupe_warnings(warnings),
            raw_count=raw_total,
        )

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
        time_start, time_end = _timeframe_to_dates(request.timeframe)
        try:
            raw = await search.search_by_type(
                keyword=keyword,
                search_type=SearchObjectType.VIDEO,
                time_start=time_start,
                time_end=time_end,
                video_zone_type=VideoZoneTypes.TECH,
                page=1,
                page_size=min(request.max_items, 20),
            )
        except (ValueError, ArgsException) as exc:
            local_warnings.append(
                _warning_for_client_error(
                    exc,
                    operation="keyword search",
                    failure_code="keyword_search_failed",
                )
            )
            return [], 0, local_warnings
        except (ResponseCodeException, NetworkException) as exc:
            local_warnings.append(
                _warning_from_exception(
                    exc,
                    operation="keyword search",
                    failure_code="keyword_search_failed",
                )
            )
            return [], 0, local_warnings
        except Exception as exc:
            local_warnings.append(
                _warning_from_exception(
                    exc,
                    operation="keyword search",
                    failure_code="keyword_search_failed",
                )
            )
            return [], 0, local_warnings

        data, code, message = _unwrap_payload(raw)
        if code != 0:
            local_warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="keyword_search_failed",
                    message=f"Bilibili keyword search returned code={code!r}",
                    detail=message,
                )
            )
            return [], 0, local_warnings

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
            if _item_within_timeframe(it, request.timeframe):
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

        try:
            uploader = user.User(uid=mid, credential=self._credential)
            raw = await uploader.get_videos(
                pn=1,
                ps=min(request.max_items, 30),
            )
        except (ResponseCodeException, NetworkException) as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"uploader videos (mid={mid})",
                    failure_code="space_search_failed",
                )
            )
            return [], 0, warnings
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"uploader videos (mid={mid})",
                    failure_code="space_search_failed",
                )
            )
            return [], 0, warnings

        data, code, message = _unwrap_payload(raw)
        if code != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="space_search_failed",
                    message=f"Bilibili uploader feed returned code={code!r} for mid={mid}",
                    detail=message,
                )
            )
            return [], 0, warnings

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
            if _item_within_timeframe(it, request.timeframe):
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
            raw = await search.search_by_type(
                keyword=channel,
                search_type=SearchObjectType.USER,
                page=1,
                page_size=5,
            )
        except (ResponseCodeException, NetworkException) as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"user search ({channel!r})",
                    failure_code="user_search_failed",
                )
            )
            return None
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"user search ({channel!r})",
                    failure_code="user_search_failed",
                )
            )
            return None

        data, code, message = _unwrap_payload(raw)
        if code != 0:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="user_search_failed",
                    message=f"Bilibili user search returned code={code!r}",
                    detail=message,
                )
            )
            return None

        rows = data.get("result") or []
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
        *,
        timeframe: str | None = None,
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

        try:
            v = video.Video(bvid=bvid, credential=self._credential)
            data = await v.get_info()
        except (ResponseCodeException, NetworkException) as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"view ({bvid})",
                    failure_code="view_fetch_failed",
                )
            )
            return None, 1, warnings
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"view ({bvid})",
                    failure_code="view_fetch_failed",
                )
            )
            return None, 1, warnings

        if isinstance(data, dict) and "code" in data and "data" in data:
            inner, code, message = _unwrap_payload(data)
            if code != 0:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="view_fetch_failed",
                        message=f"Bilibili view returned code={code!r} for {bvid}",
                        detail=message,
                    )
                )
                return None, 1, warnings
            data = inner

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

        if not _item_within_timeframe(it, timeframe):
            return None, 1, warnings

        return it, 1, warnings

    async def _get_cid(self, bvid: str) -> int | None:
        """Resolve first-page CID for future subtitle/transcript work."""
        try:
            v = video.Video(bvid=bvid, credential=self._credential)
            pages = await v.get_pages()
            if not pages:
                return None
            first = pages[0]
            if isinstance(first, dict) and first.get("cid") is not None:
                return int(first["cid"])
        except Exception:
            return None
        return None


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
