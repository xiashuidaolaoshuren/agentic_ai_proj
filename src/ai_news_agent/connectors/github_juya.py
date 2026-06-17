"""RSS-first ingestion helpers for jujuyaya/juya-ai-daily (repo-specific)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from ai_news_agent.models import ConfidenceLevel, ConnectorWarning, NewsItem, SourceKind

JUYA_OWNER = "jujuyaya"
JUYA_REPO = "juya-ai-daily"
JUYA_RSS_MAX_ENTRIES = 10
JUYA_RSS_PATH = f"/repos/{JUYA_OWNER}/{JUYA_REPO}/contents/rss.xml"
_SNIPPET_MAX = 650
_TAG_RE = re.compile(r"<[^>]+>")


def is_juya_daily_repo(owner: str, repo: str) -> bool:
    return owner.lower() == JUYA_OWNER.lower() and repo.lower() == JUYA_REPO.lower()


def decode_github_base64_content(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    encoding = str(payload.get("encoding") or "base64").lower()
    if encoding != "base64":
        return None
    try:
        raw = base64.b64decode(content, validate=False)
    except (ValueError, binascii.Error):
        return None
    return raw.decode("utf-8", errors="replace")


def parse_juya_rss_entries(
    xml_text: str,
    *,
    max_items: int,
    collected_at: datetime | None = None,
) -> list[NewsItem]:
    when = collected_at or datetime.now(UTC)
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []

    channel = root.find("channel")
    if channel is not None:
        for item_el in channel.findall("item"):
            parsed = _rss_item_element_to_news_item(item_el, collected_at=when)
            if parsed is not None:
                items.append(parsed)
            if len(items) >= max_items:
                break
        return items

    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", atom_ns):
        parsed = _atom_entry_to_news_item(entry, atom_ns, collected_at=when)
        if parsed is not None:
            items.append(parsed)
        if len(items) >= max_items:
            break
    return items


async def fetch_juya_daily_items(
    client: httpx.AsyncClient,
    *,
    max_items: int,
    collected_at: datetime,
    connector_name: str = "github",
) -> tuple[list[NewsItem], int, list[ConnectorWarning]]:
    warnings: list[ConnectorWarning] = []
    bounded = max(1, min(max_items, JUYA_RSS_MAX_ENTRIES))

    try:
        resp = await client.get(JUYA_RSS_PATH)
    except httpx.RequestError as exc:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS fetch failed; falling back to repo metadata",
                detail=str(exc),
            )
        )
        return [], 1, warnings

    if resp.status_code != 200:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message=(
                    f"Juya daily RSS unavailable (HTTP {resp.status_code}); "
                    "falling back to repo metadata"
                ),
                detail=resp.text[:300] if resp.text else None,
            )
        )
        return [], 1, warnings

    try:
        payload = resp.json()
    except ValueError as exc:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS response was not valid JSON",
                detail=str(exc),
            )
        )
        return [], 1, warnings

    if not isinstance(payload, dict):
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS response had unexpected shape",
            )
        )
        return [], 1, warnings

    xml_text = decode_github_base64_content(payload)
    if not xml_text:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS content could not be decoded",
            )
        )
        return [], 1, warnings

    try:
        items = parse_juya_rss_entries(xml_text, max_items=bounded, collected_at=collected_at)
    except ET.ParseError as exc:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS XML parse failed",
                detail=str(exc),
            )
        )
        return [], 1, warnings

    if not items:
        warnings.append(
            ConnectorWarning(
                connector=connector_name,
                code="juya_rss_unavailable",
                message="Juya daily RSS contained no usable entries",
            )
        )
        return [], 1, warnings

    return items, len(items), warnings


def _rss_item_element_to_news_item(
    item_el: ET.Element,
    *,
    collected_at: datetime,
) -> NewsItem | None:
    title = _element_text(item_el.find("title"))
    link = _element_text(item_el.find("link"))
    if not title or not link:
        return None

    description = _element_text(item_el.find("description"))
    pub_raw = _element_text(item_el.find("pubDate"))
    published_at = _parse_rss_datetime(pub_raw)

    snippet = _clean_snippet(description)
    source_id = _stable_source_id(link)

    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=link,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=JUYA_OWNER,
        metadata_completeness=0.75 if snippet else 0.55,
        raw_snippet=snippet,
        tags=["github", "juya-daily", "rss"],
        content_confidence=ConfidenceLevel.MEDIUM if snippet else ConfidenceLevel.LOW,
    )


def _atom_entry_to_news_item(
    entry: ET.Element,
    ns: dict[str, str],
    *,
    collected_at: datetime,
) -> NewsItem | None:
    title = _element_text(entry.find("atom:title", ns))
    link_el = entry.find("atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns)
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

    return NewsItem(
        source=SourceKind.GITHUB,
        source_id=source_id,
        url=link,
        title=title,
        published_at=published_at,
        collected_at=collected_at,
        author=JUYA_OWNER,
        metadata_completeness=0.75 if snippet else 0.55,
        raw_snippet=snippet,
        tags=["github", "juya-daily", "rss"],
        content_confidence=ConfidenceLevel.MEDIUM if snippet else ConfidenceLevel.LOW,
    )


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
