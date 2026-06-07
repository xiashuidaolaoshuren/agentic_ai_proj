"""Bilibili metadata connector via bilibili-api-python.

Keyword search, uploader feeds, and manual BV/URL resolution. Follow-up
enrichment adds tags, pages, related videos, full transcripts, and AI summaries.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from bilibili_api import Credential, ass, search, user, video
from bilibili_api.exceptions import ArgsException, NetworkException, ResponseCodeException
from bilibili_api.search import SearchObjectType
from bilibili_api.utils.network import Api
from bilibili_api.video_zone import VideoZoneTypes

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.env import get_bilibili_credential
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

# Real BV ids are typically 12 chars (e.g. BV1…); allow short test-style ids.
_BVID_IN_TEXT = re.compile(r"(BV[0-9A-Za-z]{8,14})", re.IGNORECASE)
# bilibili-api-python requires BV + exactly 10 alphanumeric characters (12 total).
_BVID_API_PATTERN = re.compile(r"^BV[0-9A-Za-z]{10}$", re.IGNORECASE)

_RAW_SNIPPET_MAX_LEN = 6000
_TRANSCRIPT_MAX_CHARS = 3000
_BILIBILI_AUTH_ENV_HINT = (
    "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 in .env "
    "(browser cookies from bilibili.com)."
)


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


def _is_auth_required_error(exc: BaseException) -> bool:
    if isinstance(exc, ResponseCodeException):
        code = getattr(exc, "code", None)
        if code in (-101, 101):
            return True
        msg = str(getattr(exc, "msg", exc) or exc)
        if "未登录" in msg or "not login" in msg.lower():
            return True
    if isinstance(exc, ArgsException):
        text = str(exc)
        if "sessdata" in text.lower() or "credential" in text.lower():
            return True
    text = str(exc)
    lower = text.lower()
    return "sessdata" in lower or "未登录" in text or "not login" in lower


def _is_proxy_connection_error(text: str) -> bool:
    lower = text.lower()
    if "failed to connect" not in lower and "could not connect" not in lower:
        return False
    return (
        "proxy" in lower
        or "127.0.0.1" in text
        or "localhost" in lower
        or "curl: (7)" in lower
        or re.search(r"port \d+", lower) is not None
    )


def _proxy_connection_warning(
    *,
    operation: str,
    detail: str | None = None,
) -> ConnectorWarning:
    import os

    proxy = os.environ.get("BILIBILI_PROXY_URL", "").strip()
    proxy_hint = f"Configured BILIBILI_PROXY_URL={proxy!r}. " if proxy else ""
    return ConnectorWarning(
        connector="bilibili",
        code="proxy_connection_failed",
        message=(
            f"Bilibili {operation} could not connect via the HTTP proxy. "
            f"{proxy_hint}"
            "Start your proxy (e.g. Clash/V2Ray on that host:port) or remove "
            "BILIBILI_PROXY_URL from .env and restart Gradio."
        ),
        detail=detail,
    )


def _anti_bot_blocked_warning(
    *,
    operation: str,
    detail: str | None = None,
) -> ConnectorWarning:
    from ai_news_agent.env import bilibili_env_diagnostics

    diag = bilibili_env_diagnostics()
    cred_loaded = bool(diag.get("credential_available"))
    network_hint = (
        "Try BILIBILI_HTTP_CLIENT=curl_cffi, BILIBILI_IMPERSONATE=chrome131, "
        "and/or BILIBILI_PROXY_URL in .env."
    )
    if cred_loaded:
        message = (
            f"Bilibili {operation} hit anti-bot/WAF challenge (HTTP 412 or HTML). "
            "Login cookies appear loaded; this is likely network fingerprint or IP trust. "
            f"{network_hint}"
        )
    else:
        message = (
            f"Bilibili {operation} blocked (anti-bot). "
            "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 in .env, "
            f"or use video URLs/channels. {network_hint}"
        )
    return ConnectorWarning(
        connector="bilibili",
        code="anti_bot_blocked",
        message=message,
        detail=detail,
    )


def _auth_required_warning(
    *,
    operation: str,
    detail: str | None = None,
    missing_cookies: bool,
) -> ConnectorWarning:
    if missing_cookies:
        return ConnectorWarning(
            connector="bilibili",
            code="auth_required_missing",
            message=(
                f"Bilibili {operation} needs login cookies but none were loaded from the "
                f"environment. {_BILIBILI_AUTH_ENV_HINT}"
            ),
            detail=detail,
        )
    return ConnectorWarning(
        connector="bilibili",
        code="auth_required_rejected",
        message=(
            f"Bilibili {operation}: login cookies were loaded but Bilibili rejected the "
            "session (expired, invalid, or not logged in)."
        ),
        detail=detail,
    )


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
            return _anti_bot_blocked_warning(
                operation=operation,
                detail=detail or msg,
            )
        if code in (-429, 429):
            return ConnectorWarning(
                connector="bilibili",
                code="rate_limited",
                message=f"Bilibili {operation} rate limited",
                detail=detail or msg,
            )
        if code in (-101, 101) or "未登录" in msg or "not login" in msg.lower():
            return _auth_required_warning(
                operation=operation,
                detail=detail or msg,
                missing_cookies=False,
            )
        return ConnectorWarning(
            connector="bilibili",
            code=failure_code,
            message=f"Bilibili {operation} returned code={code!r}",
            detail=detail or msg,
        )
    if isinstance(exc, ArgsException) and _is_auth_required_error(exc):
        return _auth_required_warning(
            operation=operation,
            detail=str(exc)[:300],
            missing_cookies=True,
        )
    text = str(exc)
    if _is_proxy_connection_error(text):
        return _proxy_connection_warning(
            operation=operation,
            detail=text[:300],
        )
    if isinstance(exc, NetworkException):
        lower = text.lower()
        if "html" in lower or text.lstrip().startswith("<") or "412" in text:
            return _anti_bot_blocked_warning(
                operation=operation,
                detail=text[:300],
            )
        return ConnectorWarning(
            connector="bilibili",
            code=failure_code,
            message=f"Bilibili {operation} request failed",
            detail=text[:300],
        )
    if _is_auth_required_error(exc):
        return _auth_required_warning(
            operation=operation,
            detail=str(exc)[:300],
            missing_cookies=True,
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
        if self._credential is None:
            from ai_news_agent.env import bilibili_env_diagnostics

            diag = bilibili_env_diagnostics()
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="cookies_not_loaded",
                    message=(
                        "Bilibili login cookies are not loaded from the environment "
                        f"(dotenv_loaded={diag['dotenv_loaded']}, "
                        f"dotenv_path={diag['dotenv_path']!r}, vars={diag['vars']}). "
                        f"{_BILIBILI_AUTH_ENV_HINT}"
                    ),
                )
            )
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

    async def enrich_news_item(
        self,
        item: NewsItem,
        request_topics: list[str] | None = None,
    ) -> tuple[NewsItem, list[ConnectorWarning]]:
        """Hydrate one Bilibili item via Video APIs (for follow-up source trace)."""
        topics = list(request_topics or [])
        return await self._enrich_news_item(item, topics)

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

    async def _enrich_news_item(
        self,
        item: NewsItem,
        request_topics: list[str],
    ) -> tuple[NewsItem, list[ConnectorWarning]]:
        """Best-effort hydration via Video APIs; never raises."""
        warnings: list[ConnectorWarning] = []
        bvid = item.source_id
        if not _bvid_valid_for_video_api(bvid):
            return item, warnings

        try:
            v = video.Video(bvid=bvid, credential=self._credential)
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"enrich init ({bvid})",
                    failure_code="enrichment_partial",
                )
            )
            return item, warnings

        base = item
        info_data: dict[str, Any] | None = None
        try:
            raw_info = await v.get_info()
            if isinstance(raw_info, dict) and "code" in raw_info and "data" in raw_info:
                inner, code, message = _unwrap_payload(raw_info)
                if code != 0:
                    warnings.append(
                        ConnectorWarning(
                            connector=self.name(),
                            code="enrichment_partial",
                            message=f"Bilibili enrich get_info returned code={code!r} for {bvid}",
                            detail=message,
                        )
                    )
                else:
                    info_data = inner
            elif isinstance(raw_info, dict):
                info_data = raw_info
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"enrich info ({bvid})",
                    failure_code="enrichment_partial",
                )
            )

        if info_data:
            upgraded = _view_data_to_news_item(
                info_data,
                request_topics,
                item.collected_at,
            )
            if upgraded is not None:
                base = _merge_news_item(item, upgraded)

        tag_names: list[str] = []
        try:
            raw_tags = await v.get_tags()
            tag_names = _parse_tag_names(raw_tags)
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"enrich tags ({bvid})",
                    failure_code="enrichment_partial",
                )
            )

        pages_summary = ""
        cid: int | None = None
        try:
            pages = await v.get_pages()
            if isinstance(pages, list):
                pages_summary = _format_pages_summary(pages)
                first = pages[0] if pages else None
                if isinstance(first, dict) and first.get("cid") is not None:
                    cid = int(first["cid"])
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"enrich pages ({bvid})",
                    failure_code="enrichment_partial",
                )
            )

        related_summary = ""
        try:
            raw_related = await v.get_related()
            related_summary = _format_related_summary(raw_related)
        except Exception as exc:
            warnings.append(
                _warning_from_exception(
                    exc,
                    operation=f"enrich related ({bvid})",
                    failure_code="enrichment_partial",
                )
            )

        transcript: str | None = None
        if cid is not None:
            transcript, subtitle_warning = await self._fetch_transcript(
                v,
                cid=cid,
                bvid=bvid,
            )
            if subtitle_warning is not None and transcript is None:
                warnings.append(subtitle_warning)

        ai_conclusion: str | None = None
        if cid is not None:
            try:
                raw_ai = await v.get_ai_conclusion(cid=cid)
                if isinstance(raw_ai, dict) and int(raw_ai.get("code", 0)) in (-101, 101):
                    warnings.append(
                        _auth_required_warning(
                            operation=f"enrich ai_conclusion ({bvid})",
                            detail=str(raw_ai.get("message") or raw_ai)[:300],
                            missing_cookies=self._credential is None,
                        )
                    )
                else:
                    ai_conclusion = _extract_ai_conclusion_text(raw_ai)
            except Exception as exc:
                warnings.append(
                    _warning_from_exception(
                        exc,
                        operation=f"enrich ai_conclusion ({bvid})",
                        failure_code="enrichment_partial",
                    )
                )

        enriched_any = bool(
            info_data
            or tag_names
            or pages_summary
            or related_summary
            or transcript
            or ai_conclusion
        )
        if not enriched_any:
            return item, warnings

        snippet = _compose_enriched_snippet(
            base.raw_snippet or "",
            tag_names=tag_names,
            pages_summary=pages_summary,
            related_summary=related_summary,
            transcript=transcript,
            ai_conclusion=ai_conclusion,
        )
        merged_tags = list(dict.fromkeys(["bilibili", "video", *tag_names]))
        completeness, confidence = _enrichment_scores(
            has_desc=bool((base.raw_snippet or "").strip() or snippet),
            tag_count=len(tag_names),
            has_pages=bool(pages_summary),
            has_related=bool(related_summary),
            has_transcript=bool(transcript),
            has_ai_conclusion=bool(ai_conclusion),
        )
        topic_matches = _topic_matches(
            request_topics,
            base.title,
            snippet,
            base.author or "",
        )

        enriched = NewsItem(
            source=base.source,
            source_id=base.source_id,
            url=base.url,
            title=base.title,
            published_at=base.published_at,
            collected_at=base.collected_at,
            author=base.author,
            stars_or_views=base.stars_or_views,
            language=base.language,
            metadata_completeness=completeness,
            raw_snippet=snippet or base.raw_snippet,
            tags=merged_tags,
            topic_matches=topic_matches or base.topic_matches,
            content_confidence=confidence,
        )
        return enriched, warnings

    async def _fetch_transcript(
        self,
        v: video.Video,
        *,
        cid: int,
        bvid: str,
    ) -> tuple[str | None, ConnectorWarning | None]:
        try:
            subtitle_obj = await ass.request_subtitle(
                obj=v,
                cid=cid,
                lan_code="ai-zh",
                credential=self._credential,
            )
            segments = subtitle_obj.to_simple_json()
            if isinstance(segments, list):
                transcript = _extract_transcript_text(segments)
                if transcript:
                    return transcript, None
        except Exception as exc:
            fallback = await _fetch_transcript_from_track_url(v, cid=cid)
            if fallback:
                return fallback, None
            return None, _warning_from_exception(
                exc,
                operation=f"enrich subtitle ({bvid})",
                failure_code="enrichment_partial",
            )

        fallback = await _fetch_transcript_from_track_url(v, cid=cid)
        if fallback:
            return fallback, None
        return None, None

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


def _bvid_valid_for_video_api(bvid: str) -> bool:
    return bool(_BVID_API_PATTERN.match(bvid.strip()))


def extract_bvid(text: str) -> str | None:
    text = text.strip()
    m = _BVID_IN_TEXT.search(text)
    if m:
        return m.group(1)
    return None


def _extract_bvid(text: str) -> str | None:
    """Backward-compatible alias."""
    return extract_bvid(text)


def _parse_publish_timestamp(row: dict[str, Any]) -> datetime | None:
    """Parse Bilibili publish time from common API field variants."""
    for key in ("created", "pubdate", "ctime"):
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                value = float(raw.strip())
            except ValueError:
                continue
        else:
            continue
        if value <= 0:
            continue
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _parse_tag_names(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, dict):
        if "data" in raw_tags:
            return _parse_tag_names(raw_tags["data"])
        if "tags" in raw_tags:
            return _parse_tag_names(raw_tags["tags"])
        return []
    if not isinstance(raw_tags, list):
        return []
    names: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, dict):
            name = tag.get("tag_name") or tag.get("name")
            if name:
                names.append(str(name).strip())
        elif isinstance(tag, str) and tag.strip():
            names.append(tag.strip())
    return names


def _format_pages_summary(pages: list[Any], *, limit: int = 6) -> str:
    parts: list[str] = []
    for page in pages[:limit]:
        if not isinstance(page, dict):
            continue
        title = page.get("part") or page.get("title") or ""
        page_num = page.get("page")
        duration = page.get("duration")
        segment = f"P{page_num}: {title}" if page_num is not None else str(title)
        if duration is not None:
            segment = f"{segment} ({duration}s)"
        segment = segment.strip()
        if segment:
            parts.append(segment)
    return "; ".join(parts)


def _format_related_summary(raw: Any, *, limit: int = 3) -> str:
    videos: list[Any]
    if isinstance(raw, dict):
        if "archives" in raw:
            videos = list(raw.get("archives") or [])
        elif "list" in raw:
            videos = list(raw.get("list") or [])
        elif "data" in raw:
            return _format_related_summary(raw.get("data"), limit=limit)
        else:
            videos = []
    elif isinstance(raw, list):
        videos = raw
    else:
        return ""

    parts: list[str] = []
    for row in videos[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        bvid = str(row.get("bvid") or "").strip()
        if not title:
            continue
        parts.append(f"{title} ({bvid})" if bvid else title)
    return "; ".join(parts)


async def _fetch_transcript_from_track_url(v: video.Video, *, cid: int) -> str | None:
    """Fallback transcript fetch via public subtitle track URL (no login cookies)."""
    try:
        raw_sub = await v.get_subtitle(cid=cid)
    except Exception:
        return None
    subtitle_url = _pick_subtitle_track_url(raw_sub)
    if not subtitle_url:
        return None
    try:
        payload = await Api(url=subtitle_url, method="GET").request(raw=True)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    body = payload.get("body")
    if not isinstance(body, list):
        return None
    return _extract_transcript_text(body)


def _pick_subtitle_track_url(raw_sub: Any) -> str | None:
    if not isinstance(raw_sub, dict):
        return None
    tracks = raw_sub.get("list")
    if not isinstance(tracks, list) or not tracks:
        return None

    preferred_codes = ("ai-zh", "zh-CN", "zh-Hans", "zh")
    chosen: dict[str, Any] | None = None
    for code in preferred_codes:
        for track in tracks:
            if isinstance(track, dict) and track.get("lan") == code:
                chosen = track
                break
        if chosen is not None:
            break
    if chosen is None:
        first = tracks[0]
        chosen = first if isinstance(first, dict) else None
    if chosen is None:
        return None

    url = str(chosen.get("subtitle_url") or "").strip()
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url.lstrip("/")


def _extract_transcript_text(
    segments: list[dict[str, Any]],
    *,
    max_chars: int = _TRANSCRIPT_MAX_CHARS,
) -> str | None:
    lines: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        content = seg.get("content")
        if content:
            lines.append(str(content).strip())
    if not lines:
        return None
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:max_chars]


def _extract_ai_conclusion_text(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None

    data = raw.get("data")
    if not isinstance(data, dict):
        data = raw

    model_result = data.get("model_result")
    if not isinstance(model_result, dict):
        return None

    sections: list[str] = []
    summary = model_result.get("summary")
    if summary:
        sections.append(str(summary).strip())

    outline = model_result.get("outline")
    if isinstance(outline, list):
        for part in outline:
            if not isinstance(part, dict):
                continue
            title = str(part.get("title") or "").strip()
            if title:
                sections.append(title)
            part_outline = part.get("part_outline")
            if isinstance(part_outline, list):
                for entry in part_outline:
                    if not isinstance(entry, dict):
                        continue
                    content = entry.get("content")
                    if content:
                        sections.append(str(content).strip())

    if not sections:
        return None
    text = "\n".join(sections)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[: _TRANSCRIPT_MAX_CHARS] if text else None


def _compose_enriched_snippet(
    base_desc: str,
    *,
    tag_names: list[str],
    pages_summary: str,
    related_summary: str,
    transcript: str | None,
    ai_conclusion: str | None,
) -> str:
    sections: list[str] = []
    if ai_conclusion:
        sections.append("AI summary: " + ai_conclusion)
    if transcript:
        sections.append("Transcript: " + transcript)
    desc = base_desc.strip()
    if desc:
        sections.append(desc)
    if tag_names:
        sections.append("Tags: " + ", ".join(tag_names[:12]))
    if pages_summary:
        sections.append("Parts: " + pages_summary)
    if related_summary:
        sections.append("Related: " + related_summary)
    if not sections:
        return ""
    text = "\n".join(sections)
    if len(text) <= _RAW_SNIPPET_MAX_LEN:
        return text
    return text[: _RAW_SNIPPET_MAX_LEN - 3].rstrip() + "..."


def _enrichment_scores(
    *,
    has_desc: bool,
    tag_count: int,
    has_pages: bool,
    has_related: bool,
    has_transcript: bool,
    has_ai_conclusion: bool,
) -> tuple[float, ConfidenceLevel]:
    score = 0.25
    if has_desc:
        score += 0.15
    if tag_count:
        score += min(0.15, 0.05 * tag_count)
    if has_pages:
        score += 0.1
    if has_related:
        score += 0.1
    if has_transcript:
        score += 0.25
    if has_ai_conclusion:
        score += 0.2
    score = min(score, 1.0)
    if score >= 0.8:
        confidence = ConfidenceLevel.HIGH
    elif score >= 0.55:
        confidence = ConfidenceLevel.MEDIUM
    else:
        confidence = ConfidenceLevel.LOW
    return round(score, 3), confidence


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

    published_at = _parse_publish_timestamp(row)

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

    published_at = _parse_publish_timestamp(data)

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
