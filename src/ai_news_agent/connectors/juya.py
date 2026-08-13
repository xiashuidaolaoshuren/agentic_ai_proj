"""Dedicated Juya bulletin connector (Milestone 5 T1)."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from ai_news_agent.connectors.base import ConnectorRequest, ConnectorResult
from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

JUYA_OWNER = "jujuyaya"
JUYA_REPO = "juya-ai-daily"
JUYA_CANONICAL_GITHUB_URL = f"https://github.com/{JUYA_OWNER}/{JUYA_REPO}"
JUYA_WEBSITE_BASE = "https://daily.juya.uk"
JUYA_WEBSITE_RSS_URL = f"{JUYA_WEBSITE_BASE}/rss.xml"
JUYA_RSS_MAX_ENTRIES = 10
_SNIPPET_MAX = 650
_CONTENT_MAX = 6000
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_JUYA_WEBSITE_URL = re.compile(r"https?://(?:www\.)?daily\.juya\.uk", re.IGNORECASE)
_CONTENT_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
_GITHUB_REPO_URL = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ParsedJuyaRssRow:
    item: NewsItem
    content_encoded: str | None = None


def is_juya_daily_repo(owner: str, repo: str) -> bool:
    return owner.lower() == JUYA_OWNER.lower() and repo.lower() == JUYA_REPO.lower()


def is_juya_website_url(url: str) -> bool:
    return bool(_JUYA_WEBSITE_URL.search(url or ""))


def is_juya_target_url(url: str) -> bool:
    if is_juya_website_url(url):
        return True
    match = _GITHUB_REPO_URL.search(url or "")
    if match is None:
        return False
    return is_juya_daily_repo(match.group(1), match.group(2))


def markdown_url_for_issue(title: str, link: str) -> str | None:
    """Derive website markdown URL from issue title or link."""
    for candidate in (title, link):
        match = _DATE_RE.search(candidate or "")
        if match:
            return f"{JUYA_WEBSITE_BASE}/markdown/{match.group(0)}.md"
    return None


def clean_issue_markdown(text: str) -> str:
    """Flatten issue markdown into bounded plain evidence text."""
    parts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = re.sub(r"^#+\s*", "", stripped)
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        parts.append(stripped)
    plain = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if not plain:
        return ""
    return plain[:_CONTENT_MAX]


def clean_encoded_html(text: str | None) -> str:
    """Flatten RSS content:encoded HTML into bounded evidence text."""
    if not text:
        return ""
    unescaped = html.unescape(text)
    plain = _TAG_RE.sub(" ", unescaped)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""
    return plain[:_CONTENT_MAX]


def parse_juya_rss_entries(
    xml_text: str,
    *,
    max_items: int,
    collected_at: datetime | None = None,
) -> list[NewsItem]:
    """Parse website RSS/Atom XML into NewsItem rows (snippet only)."""
    rows = parse_juya_rss_rows(xml_text, max_items=max_items, collected_at=collected_at)
    return [row.item for row in rows]


def parse_juya_rss_rows(
    xml_text: str,
    *,
    max_items: int,
    collected_at: datetime | None = None,
) -> list[_ParsedJuyaRssRow]:
    when = collected_at or datetime.now(UTC)
    root = ET.fromstring(xml_text)
    rows: list[_ParsedJuyaRssRow] = []

    channel = root.find("channel")
    if channel is not None:
        for item_el in channel.findall("item"):
            parsed = _rss_item_element_to_row(item_el, collected_at=when)
            if parsed is not None:
                rows.append(parsed)
            if len(rows) >= max_items:
                break
        return rows

    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", atom_ns):
        parsed = _atom_entry_to_row(entry, atom_ns, collected_at=when)
        if parsed is not None:
            rows.append(parsed)
        if len(rows) >= max_items:
            break
    return rows


# Backward-compatible aliases used by older tests/modules.
backup_path_for_entry = markdown_url_for_issue
clean_backup_markdown = clean_issue_markdown


class JuyaConnector:
    """Collects Juya daily bulletin items from website RSS + markdown enrichment."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": "ai-news-agent/0.1"},
                timeout=httpx.Timeout(30.0),
            )

    def name(self) -> str:
        return "juya"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        now = datetime.now(UTC)
        items, raw_count, warnings = await fetch_juya_daily_items(
            self._client,
            max_items=request.max_items,
            collected_at=now,
            connector_name=self.name(),
        )
        return ConnectorResult(items=items, warnings=warnings, raw_count=raw_count)


async def fetch_juya_daily_items(
    client: httpx.AsyncClient,
    *,
    max_items: int,
    collected_at: datetime,
    connector_name: str = "juya",
) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
    warnings: list[ConnectorWarning] = []
    bounded = max(1, min(max_items, JUYA_RSS_MAX_ENTRIES))

    try:
        resp = await client.get(JUYA_WEBSITE_RSS_URL)
    except httpx.RequestError as exc:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya website RSS fetch failed",
                detail=str(exc),
            )
        )
        return [], 0, warnings

    if resp.status_code != 200:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message=(
                    f"Juya website RSS unavailable (HTTP {resp.status_code})"
                ),
                detail=resp.text[:300] if resp.text else None,
            )
        )
        return [], 0, warnings

    xml_text = resp.text
    if not xml_text.strip():
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya website RSS response was empty",
            )
        )
        return [], 0, warnings

    try:
        rows = parse_juya_rss_rows(xml_text, max_items=bounded, collected_at=collected_at)
    except ET.ParseError as exc:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya website RSS XML parse failed",
                detail=str(exc),
            )
        )
        return [], 0, warnings

    if not rows:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya website RSS contained no usable entries",
            )
        )
        return [], 0, warnings

    enriched, enrich_warnings = await enrich_juya_items_with_markdown(
        client,
        rows,
        connector_name=connector_name,
    )
    warnings.extend(enrich_warnings)
    return enriched, len(enriched), warnings


async def enrich_juya_items_with_markdown(
    client: httpx.AsyncClient,
    rows: list[_ParsedJuyaRssRow],
    *,
    connector_name: str = "juya",
) -> tuple[list[NewsItem], list[ConnectorWarning]]:
    """Prefer per-issue markdown; fall back to RSS content:encoded."""
    warnings: list[ConnectorWarning] = []
    enriched: list[NewsItem] = []

    for row in rows:
        item = row.item
        md_url = markdown_url_for_issue(item.title, item.url)
        cleaned = ""
        source_tag = "juya-markdown"

        if md_url:
            raw_md = await _fetch_issue_markdown(client, md_url)
            if raw_md:
                cleaned = clean_issue_markdown(raw_md)

        if not cleaned and row.content_encoded:
            cleaned = clean_encoded_html(row.content_encoded)
            source_tag = "juya-rss-content"

        if not cleaned:
            warnings.append(
                ConnectorWarning(
                    connector=connector_name,
                    code="juya_markdown_unavailable",
                    message=f"Issue content unavailable for {item.title!r}",
                )
            )
            enriched.append(item)
            continue

        enriched.append(
            item.model_copy(
                update={
                    "raw_snippet": cleaned,
                    "content_confidence": ConfidenceLevel.HIGH,
                    "metadata_completeness": max(item.metadata_completeness, 0.9),
                    "tags": [*item.tags, source_tag],
                }
            )
        )
    return enriched, warnings


async def enrich_juya_items_with_backup(
    client: httpx.AsyncClient,
    items: list[NewsItem],
    *,
    connector_name: str = "juya",
) -> tuple[list[NewsItem], list[ConnectorWarning]]:
    rows = [_ParsedJuyaRssRow(item=item) for item in items]
    return await enrich_juya_items_with_markdown(
        client,
        rows,
        connector_name=connector_name,
    )


async def _fetch_issue_markdown(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    return text if text.strip() else None


def _rss_item_element_to_row(
    item_el: ET.Element,
    *,
    collected_at: datetime,
) -> _ParsedJuyaRssRow | None:
    title = _element_text(item_el.find("title"))
    link = _element_text(item_el.find("link"))
    if not title or not link:
        return None

    description = _element_text(item_el.find("description"))
    encoded_el = item_el.find("content:encoded", _CONTENT_NS)
    content_encoded = _element_text(encoded_el)
    pub_raw = _element_text(item_el.find("pubDate"))
    published_at = _parse_rss_datetime(pub_raw)

    snippet = _clean_snippet(description)
    source_id = _stable_source_id(link)

    item = NewsItem(
        source=SourceKind.JUYA,
        source_id=source_id,
        url=link,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=JUYA_OWNER,
        metadata_completeness=0.75 if snippet else 0.55,
        raw_snippet=snippet,
        tags=["juya", "juya-daily", "rss"],
        content_confidence=ConfidenceLevel.MEDIUM if snippet else ConfidenceLevel.LOW,
    )
    return _ParsedJuyaRssRow(item=item, content_encoded=content_encoded)


def _atom_entry_to_row(
    entry: ET.Element,
    ns: dict[str, str],
    *,
    collected_at: datetime,
) -> _ParsedJuyaRssRow | None:
    title = _element_text(entry.find("atom:title", ns))
    link_el = entry.find("atom:link[@rel='alternate']", ns)
    if link_el is None:
        link_el = entry.find("atom:link", ns)
    link = link_el.get("href") if link_el is not None else None
    if not title or not link:
        return None

    summary = _element_text(entry.find("atom:summary", ns)) or _element_text(
        entry.find("atom:content", ns)
    )
    updated = _element_text(entry.find("atom:updated", ns)) or _element_text(
        entry.find("atom:published", ns)
    )
    published_at = _parse_rss_datetime(updated)

    snippet = _clean_snippet(summary)
    source_id = _stable_source_id(link)

    item = NewsItem(
        source=SourceKind.JUYA,
        source_id=source_id,
        url=link,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=JUYA_OWNER,
        metadata_completeness=0.75 if snippet else 0.55,
        raw_snippet=snippet,
        tags=["juya", "juya-daily", "rss"],
        content_confidence=ConfidenceLevel.MEDIUM if snippet else ConfidenceLevel.LOW,
    )
    return _ParsedJuyaRssRow(item=item, content_encoded=summary)


def _element_text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def _clean_snippet(text: str | None) -> str | None:
    if not text:
        return None
    plain = _TAG_RE.sub(" ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return None
    return plain[:_SNIPPET_MAX]


def _parse_rss_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stable_source_id(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"juya-rss-{digest}"
