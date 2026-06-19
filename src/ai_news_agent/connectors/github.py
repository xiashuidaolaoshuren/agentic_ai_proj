"""GitHub REST connector: repository search + optional README excerpt (Task 5).

HTTP strategy
-------------
- Primary: ``GET /search/repositories`` with query built from request topics and optional
  ``pushed:>=...`` qualifier derived from ``ConnectorRequest.timeframe``.
- Optional enrichment: ``GET /repos/{owner}/{repo}/readme`` with
  ``Accept: application/vnd.github.raw``; failures are ignored per item.
- Headers: ``Accept: application/vnd.github+json`` and a pinned ``X-GitHub-Api-Version``.
- Auth: optional ``GITHUB_TOKEN`` / constructor ``token`` as ``Authorization: Bearer``.

Warning taxonomy
-----------------
- ``no_input`` — no topics, URLs, or channels; no API call.
- ``rate_limited`` — HTTP 429 or 403 with exhausted rate limit headers.
- ``search_failed`` — search HTTP error not classified as rate limit.
- ``invalid_search_response`` — unreadable search JSON or unexpected shape.
- ``incomplete_results`` — search payload ``incomplete_results=true``.
- ``skipped_malformed_repo`` — repo row missing ``id``, ``full_name``, or ``html_url``.
- ``juya_rss_unavailable`` — Juya website RSS fetch/parse failed for a targeted Juya URL.
- ``juya_markdown_unavailable`` — per-issue markdown and RSS content fallback both missing.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.connectors.github_juya import (
    fetch_juya_daily_items,
    is_juya_daily_repo,
    is_juya_website_url,
)
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
README_ACCEPT_RAW = "application/vnd.github.raw"
MAX_README_CHARS = 2000
SNIPPET_README_MAX = 650
_GITHUB_REPO_URL = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_RESERVED_GITHUB_PATHS = frozenset(
    {"settings", "pulls", "issues", "actions", "projects", "security", "pulse", "graphs"}
)


class GitHubConnector:
    """Collects GitHub repositories via the public REST search API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            headers = {**DEFAULT_HEADERS, "User-Agent": "ai-news-agent/0.1"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0),
            )

    def name(self) -> str:
        return "github"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        warnings: list[ConnectorWarning] = []
        has_topics = bool(request.topics)
        has_urls = bool(request.github_manual_urls)
        has_channels = bool(request.github_target_channels)
        if not has_topics and not has_urls and not has_channels:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="no_input",
                    message=(
                        "GitHub connector skipped: topics, github_manual_urls, "
                        "and github_target_channels are all empty"
                    ),
                )
            )
            return ConnectorResult(items=[], warnings=warnings, raw_count=0)

        by_repo_id: dict[str, NewsItem] = {}
        raw_total = 0
        now = datetime.now(UTC)

        for url in request.github_manual_urls:
            ref = parse_github_repo_ref(url)
            is_juya_target = (ref is not None and is_juya_daily_repo(*ref)) or is_juya_website_url(
                url
            )
            if is_juya_target:
                juya_items, n_raw, ws = await fetch_juya_daily_items(
                    self._client,
                    max_items=request.max_items,
                    collected_at=now,
                    connector_name=self.name(),
                )
                raw_total += n_raw
                warnings.extend(ws)
                for item in juya_items:
                    by_repo_id[item.source_id] = item
                continue

            row, n_raw, ws = await self._fetch_repo_by_url(url, warnings)
            raw_total += n_raw
            warnings.extend(ws)
            if row is not None:
                item = await self._row_to_item(row, request.topics, now)
                by_repo_id[item.source_id] = item

        for owner in request.github_target_channels:
            rows, n_raw, ws = await self._fetch_owner_repos(owner, request, warnings)
            raw_total += n_raw
            warnings.extend(ws)
            for row in rows:
                item = await self._row_to_item(row, request.topics, now)
                by_repo_id[item.source_id] = item

        if has_topics:
            search_items, n_raw, ws = await self._collect_topic_search(request, now)
            raw_total += n_raw
            warnings.extend(ws)
            for item in search_items:
                by_repo_id[item.source_id] = item

        merged = list(by_repo_id.values())[: request.max_items]
        return ConnectorResult(items=merged, warnings=warnings, raw_count=raw_total)

    async def _row_to_item(
        self,
        row: dict[str, Any],
        topics: list[str],
        collected_at: datetime,
    ) -> NewsItem:
        excerpt = await _fetch_readme_excerpt(self._client, str(row["full_name"]))
        return _repo_to_news_item(row, topics, excerpt, collected_at)

    async def _fetch_repo_by_url(
        self,
        url: str,
        warnings: list[ConnectorWarning],
    ) -> tuple[dict[str, Any] | None, int, list[ConnectorWarning]]:
        ref = parse_github_repo_ref(url)
        if ref is None:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="invalid_manual_url",
                    message="Could not parse owner/repo from GitHub URL",
                    detail=url[:200],
                )
            )
            return None, 0, warnings
        owner, repo = ref
        return await self._fetch_repo_api(owner, repo, warnings)

    async def _fetch_repo_api(
        self,
        owner: str,
        repo: str,
        warnings: list[ConnectorWarning],
    ) -> tuple[dict[str, Any] | None, int, list[ConnectorWarning]]:
        try:
            resp = await self._client.get(f"/repos/{owner}/{repo}")
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="repo_fetch_failed",
                    message=f"GitHub repo fetch failed for {owner}/{repo}",
                    detail=str(exc),
                )
            )
            return None, 1, warnings

        rate_ws = _warnings_for_rate_limit(resp)
        warnings.extend(rate_ws)
        if resp.status_code != 200:
            if not rate_ws:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="repo_fetch_failed",
                        message=f"GitHub repo fetch HTTP {resp.status_code} for {owner}/{repo}",
                        detail=resp.text[:300] if resp.text else None,
                    )
                )
            return None, 1, warnings

        try:
            row = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="repo_fetch_failed",
                    message=f"GitHub repo response was not valid JSON for {owner}/{repo}",
                    detail=str(exc),
                )
            )
            return None, 1, warnings

        if _missing_required_repo_fields(row):
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="skipped_malformed_repo",
                    message=f"GitHub repo payload missing required fields for {owner}/{repo}",
                )
            )
            return None, 1, warnings

        return row, 1, warnings

    async def _fetch_owner_repos(
        self,
        owner: str,
        request: ConnectorRequest,
        warnings: list[ConnectorWarning],
    ) -> tuple[list[dict[str, Any]], int, list[ConnectorWarning]]:
        owner = str(owner).strip().strip("/")
        if not owner:
            return [], 0, warnings

        per_page = max(1, min(request.max_items, 100))
        rows: list[dict[str, Any]] = []
        for path in (f"/users/{owner}/repos", f"/orgs/{owner}/repos"):
            try:
                resp = await self._client.get(
                    path,
                    params={"sort": "updated", "per_page": per_page},
                )
            except httpx.RequestError as exc:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="owner_repos_failed",
                        message=f"GitHub owner repos request failed for {owner!r}",
                        detail=str(exc),
                    )
                )
                continue

            rate_ws = _warnings_for_rate_limit(resp)
            warnings.extend(rate_ws)
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                if not rate_ws:
                    warnings.append(
                        ConnectorWarning(
                            connector=self.name(),
                            code="owner_repos_failed",
                            message=f"GitHub owner repos HTTP {resp.status_code} for {owner!r}",
                            detail=resp.text[:300] if resp.text else None,
                        )
                    )
                continue

            try:
                data = resp.json()
            except ValueError as exc:
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="owner_repos_failed",
                        message="GitHub owner repos response was not valid JSON",
                        detail=str(exc),
                    )
                )
                continue

            if not isinstance(data, list):
                continue

            for row in data:
                if isinstance(row, dict) and not _missing_required_repo_fields(row):
                    rows.append(row)
            if rows:
                return rows, len(rows), warnings

        if not rows:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="unresolved_channel",
                    message=f"Could not list repositories for GitHub owner/org: {owner!r}",
                )
            )
        return rows, len(rows), warnings

    async def _collect_topic_search(
        self,
        request: ConnectorRequest,
        now: datetime,
    ) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
        warnings: list[ConnectorWarning] = []
        q = _build_search_query(request.topics, request.timeframe)
        per_page = max(1, min(request.max_items, 100))

        try:
            resp = await self._client.get(
                "/search/repositories",
                params={
                    "q": q,
                    "per_page": per_page,
                    "sort": "updated",
                    "order": "desc",
                },
            )
        except httpx.RequestError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="search_failed",
                    message=f"GitHub search request failed: {type(exc).__name__}",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        rate_ws = _warnings_for_rate_limit(resp)
        warnings.extend(rate_ws)

        if resp.status_code != 200:
            if rate_ws:
                return [], 0, warnings
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="search_failed",
                    message=f"GitHub search failed with HTTP {resp.status_code}",
                    detail=resp.text[:512] if resp.text else None,
                )
            )
            return [], 0, warnings

        try:
            data = resp.json()
        except ValueError as exc:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="invalid_search_response",
                    message="GitHub search response was not valid JSON",
                    detail=str(exc),
                )
            )
            return [], 0, warnings

        raw_items = data.get("items")
        if raw_items is None:
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="invalid_search_response",
                    message="GitHub search JSON missing 'items'",
                )
            )
            return [], 0, warnings

        if not isinstance(raw_items, list):
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="invalid_search_response",
                    message="GitHub search 'items' must be a list",
                )
            )
            return [], 0, warnings

        if bool(data.get("incomplete_results")):
            warnings.append(
                ConnectorWarning(
                    connector=self.name(),
                    code="incomplete_results",
                    message="GitHub search returned incomplete_results=true",
                )
            )

        raw_count = len(raw_items)
        valid_rows: list[dict[str, Any]] = []
        for row in raw_items:
            if not isinstance(row, dict):
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_repo",
                        message="Skipped non-object repository entry",
                    )
                )
                continue
            if _missing_required_repo_fields(row):
                warnings.append(
                    ConnectorWarning(
                        connector=self.name(),
                        code="skipped_malformed_repo",
                        message="Skipped repository row missing id, full_name, or html_url",
                        detail=str(row.get("full_name", row.get("id"))),
                    )
                )
                continue
            valid_rows.append(row)

        items: list[NewsItem] = []
        for row in valid_rows:
            items.append(await self._row_to_item(row, request.topics, now))

        return items, raw_count, warnings


def parse_github_repo_ref(text: str) -> tuple[str, str] | None:
    """Parse ``owner/repo`` from a GitHub URL or ``owner/repo`` string."""
    text = text.strip()
    m = _GITHUB_REPO_URL.search(text)
    if m:
        owner, repo = m.group(1), m.group(2)
        if owner.lower() in _RESERVED_GITHUB_PATHS:
            return None
        return owner, repo.rstrip("/")

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) >= 2 and parts[0].lower() not in _RESERVED_GITHUB_PATHS:
            return parts[0], parts[1]

    if "/" in text and " " not in text and not text.startswith("http"):
        owner, _, repo = text.partition("/")
        owner = owner.strip()
        repo = repo.strip().rstrip("/")
        if owner and repo:
            return owner, repo
    return None


def _missing_required_repo_fields(row: dict[str, Any]) -> bool:
    if row.get("id") is None:
        return True
    if not row.get("full_name"):
        return True
    if not row.get("html_url"):
        return True
    return False


def _warnings_for_rate_limit(resp: httpx.Response) -> list[ConnectorWarning]:
    if resp.status_code == 429:
        reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("X-RateLimit-Reset")
        return [
            ConnectorWarning(
                connector="github",
                code="rate_limited",
                message="GitHub API rate limit reached",
                detail=f"reset={reset}" if reset else None,
            )
        ]
    if resp.status_code == 403:
        remaining = resp.headers.get("x-ratelimit-remaining") or resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("X-RateLimit-Reset")
            return [
                ConnectorWarning(
                    connector="github",
                    code="rate_limited",
                    message="GitHub API rate limit exhausted (403)",
                    detail=f"reset={reset}" if reset else None,
                )
            ]
    return []


def _timeframe_to_pushed_qualifier(timeframe: str | None) -> str | None:
    if not timeframe:
        return None
    key = timeframe.strip().lower().replace("-", "_")
    today = datetime.now(UTC).date()
    if key in ("today", "last_day", "day"):
        start = today - timedelta(days=1)
        return f"pushed:>={start.isoformat()}"
    if key in ("last_7_days", "week", "seven_days"):
        start = today - timedelta(days=7)
        return f"pushed:>={start.isoformat()}"
    if key in ("last_30_days", "month"):
        start = today - timedelta(days=30)
        return f"pushed:>={start.isoformat()}"
    return None


def _build_search_query(topics: list[str], timeframe: str | None) -> str:
    terms: list[str] = []
    for t in topics:
        s = str(t).strip()
        if not s:
            continue
        if any(c in s for c in (" ", ":", "/", '"')):
            terms.append(f'"{s}"')
        else:
            terms.append(s)
    if not terms:
        terms = ["AI"]
    topic_q = " OR ".join(terms)
    q = f"({topic_q}) in:name,description,readme"
    pushed = _timeframe_to_pushed_qualifier(timeframe)
    if pushed:
        q = f"{q} {pushed}"
    return q


def _topic_matches(request_topics: list[str], repo: dict[str, Any]) -> list[str]:
    parts = [
        str(repo.get("name") or ""),
        str(repo.get("description") or ""),
        str(repo.get("full_name") or ""),
    ]
    parts.extend(str(t) for t in (repo.get("topics") or []) if t is not None)
    haystack = " ".join(parts).lower()
    matched: list[str] = []
    for t in request_topics:
        tl = t.strip().lower()
        if not tl:
            continue
        if tl in haystack:
            matched.append(t)
            continue
        hit = False
        for word in tl.split():
            if len(word) > 2 and word in haystack:
                hit = True
                break
        if hit:
            matched.append(t)
    return matched


def _combine_snippet(description: str | None, readme_excerpt: str | None) -> str | None:
    desc = (description or "").strip()
    excerpt = (readme_excerpt or "").strip()[:SNIPPET_README_MAX]
    if desc and excerpt:
        return f"{desc}\n\n--- README ---\n{excerpt}"
    if desc:
        return desc
    if excerpt:
        return excerpt
    return None


def _metadata_completeness(
    repo: dict[str, Any],
    *,
    has_readme_excerpt: bool,
) -> float:
    score = 0.35
    if repo.get("description"):
        score += 0.3
    if repo.get("stargazers_count") is not None:
        score += 0.1
    if repo.get("language"):
        score += 0.1
    topics = repo.get("topics") or []
    if isinstance(topics, list) and topics:
        score += 0.05
    if has_readme_excerpt:
        score += 0.1
    return min(score, 1.0)


def _repo_to_news_item(
    row: dict[str, Any],
    request_topics: list[str],
    readme_excerpt: str | None,
    collected_at: datetime,
) -> NewsItem:
    repo_id = str(row["id"])
    full_name = str(row["full_name"])
    url = str(row["html_url"])
    desc = row.get("description")
    if desc is not None:
        desc = str(desc).strip() or None

    stars = row.get("stargazers_count")
    owner = (row.get("owner") or {}).get("login") if isinstance(row.get("owner"), dict) else None
    pushed = row.get("pushed_at") or row.get("updated_at")
    published_at: datetime | None = None
    if isinstance(pushed, str):
        try:
            published_at = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    excerpt_for_item = readme_excerpt
    raw_snippet = _combine_snippet(desc, excerpt_for_item)
    has_readme = bool(excerpt_for_item and excerpt_for_item.strip())

    lang = row.get("language")
    if lang is not None:
        lang = str(lang)

    gh_topics = row.get("topics")
    tags = ["github", "repository"]
    if isinstance(gh_topics, list):
        tags.extend(str(t) for t in gh_topics if t is not None)

    topic_matches = _topic_matches(request_topics, row)

    completeness = _metadata_completeness(row, has_readme_excerpt=has_readme)
    if desc or has_readme:
        content_confidence = ConfidenceLevel.MEDIUM
    else:
        content_confidence = ConfidenceLevel.LOW

    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=repo_id,
        url=url,
        title=full_name,
        published_at=published_at,
        collected_at=collected_at,
        author=str(owner) if owner else None,
        stars_or_views=int(stars) if stars is not None else None,
        language=lang,
        metadata_completeness=completeness,
        raw_snippet=raw_snippet,
        tags=tags,
        topic_matches=topic_matches,
        content_confidence=content_confidence,
    )


async def _fetch_readme_excerpt(client: httpx.AsyncClient, full_name: str) -> str | None:
    part = full_name.partition("/")
    if not part[1]:
        return None
    owner, _, repo_name = part
    if not owner or not repo_name:
        return None
    path = f"/repos/{owner}/{repo_name}/readme"
    headers = dict(client.headers)
    headers["Accept"] = README_ACCEPT_RAW
    try:
        resp = await client.get(path, headers=headers)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text.strip()[:MAX_README_CHARS]
    if not text:
        return None
    return text
