"""Parse natural-language digest prompts into :class:`~ai_news_agent.request.DigestRequest`."""

from __future__ import annotations

import re

from ai_news_agent.connectors.bilibili import extract_bvid
from ai_news_agent.connectors.github import parse_github_repo_ref
from ai_news_agent.connectors.juya import is_juya_daily_repo
from ai_news_agent.request import DigestRequest

_GITHUB_REPO_URL = re.compile(
    r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)
_BILIBILI_VIDEO_URL = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+",
    re.IGNORECASE,
)
_URL_TOKEN = re.compile(r"https?://\S+", re.IGNORECASE)
_JUYA_WEBSITE_URL = re.compile(
    r"https?://(?:www\.)?daily\.juya\.uk(?:/[^\s]*)?",
    re.IGNORECASE,
)

# Owner/org channels only from explicit phrasing — not from bare github.com/owner in a repo URL.
_GITHUB_CHANNEL = re.compile(
    r"(?:github\s+(?:user|org|channel|owner)\s+([A-Za-z0-9_.-]+)"
    r"|from\s+([A-Za-z0-9_.-]+)\s+on\s+github)",
    re.IGNORECASE,
)
_BILIBILI_CHANNEL = re.compile(
    r"(?:bilibili\s+channel\s+([A-Za-z0-9_.-]+)"
    r"|bilibili\s+uploader\s+([A-Za-z0-9_.-]+)"
    r"|from\s+([A-Za-z0-9_.-]+)\s+on\s+bilibili"
    r"|space\.bilibili\.com/(\d+))",
    re.IGNORECASE,
)

_TIMEFRAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\btoday(?:'s)?\b", re.I), "today"),
    (re.compile(r"\blast\s*7\s*days?\b", re.I), "last_7_days"),
    (re.compile(r"\blast\s*30\s*days?\b", re.I), "last_30_days"),
    (re.compile(r"\bthis\s+week\b", re.I), "last_7_days"),
)

_TOPICS_PREFIX = re.compile(r"\btopics?\s*:\s*(.+)$", re.I | re.MULTILINE)


def parse_connector_names_from_message(text: str) -> list[str] | None:
    """Return explicit source-only phrases from a message, or ``None`` if absent.

    Recognized phrases (deterministic regex, no LLM):
    - ``use X and Y`` where X, Y are in {juya, github, bilibili} → [X, Y] in order
    - ``(from )?X only`` where X is in {juya, github, bilibili} → [X, ...]
    - trending-repo cues (``trending repos``, ``github trending``) → ["github"]
    """
    low = text.strip().lower()
    if not low:
        return None

    use_match = re.search(
        r"\buse\s+(juya|github|bilibili)\s+and\s+(juya|github|bilibili)\b",
        low,
    )
    if use_match:
        names = [use_match.group(1), use_match.group(2)]
        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    found: list[str] = []
    for match in re.finditer(
        r"\b(?:from\s+)?(juya|github|bilibili)\s+only\b",
        low,
    ):
        name = match.group(1).lower()
        if name not in found:
            found.append(name)
    if found:
        return found

    if re.search(r"\btrending\s+(?:github\s+)?repos?\b", low) or re.search(
        r"\bgithub\s+trending\b", low
    ):
        return ["github"]

    return None


def parse_digest_intent(message: str) -> DigestRequest:
    """Build a digest request from a free-form user message.

    When explicit URLs/channels are detected, topic keyword search is skipped
    (``topics=[]``) unless the user also supplies a ``topics:`` line.
    """
    text = message.strip()
    if not text:
        return DigestRequest()

    github_urls: list[str] = []
    github_channels: list[str] = []
    bilibili_urls: list[str] = []
    bilibili_channels: list[str] = []
    juya_urls: list[str] = []

    seen_gh_url: set[str] = set()
    seen_juya_url: set[str] = set()
    for m in _GITHUB_REPO_URL.finditer(text):
        url = m.group(0).rstrip(").,;]")
        ref = parse_github_repo_ref(url)
        if ref is not None and is_juya_daily_repo(ref[0], ref[1]):
            raise ValueError(
                "The GitHub repo 'jujuyaya/juya-ai-daily' is the legacy source "
                "for Juya. Use the website instead: https://daily.juya.uk/"
            )
        if url not in seen_gh_url:
            seen_gh_url.add(url)
            github_urls.append(url)

    for token in _URL_TOKEN.findall(text):
        token = token.rstrip(").,;]")
        if _BILIBILI_VIDEO_URL.search(token) or extract_bvid(token):
            if token not in bilibili_urls:
                bilibili_urls.append(token)
            continue
        if _JUYA_WEBSITE_URL.match(token):
            if token not in seen_juya_url:
                seen_juya_url.add(token)
                juya_urls.append(token)
            continue
        ref = parse_github_repo_ref(token)
        if ref and token not in seen_gh_url:
            seen_gh_url.add(token)
            github_urls.append(token)

    for bvid_m in re.finditer(r"\b(BV[0-9A-Za-z]{8,14})\b", text, re.I):
        bvid = bvid_m.group(1)
        url = f"https://www.bilibili.com/video/{bvid}"
        if url not in bilibili_urls:
            bilibili_urls.append(url)

    for pat in _GITHUB_CHANNEL.finditer(text):
        for g in pat.groups():
            if g and g not in github_channels:
                github_channels.append(g)

    for pat in _BILIBILI_CHANNEL.finditer(text):
        for g in pat.groups():
            if g and g not in bilibili_channels:
                bilibili_channels.append(g)

    explicit = bool(
        github_urls
        or github_channels
        or bilibili_urls
        or bilibili_channels
        or juya_urls
    )

    topics: list[str] | None = None
    topics_match = _TOPICS_PREFIX.search(text)
    if topics_match:
        topics = [t.strip() for t in topics_match.group(1).split(",") if t.strip()]
    elif explicit:
        topics = []

    timeframe: str | None = None
    for pattern, label in _TIMEFRAME_PATTERNS:
        if pattern.search(text):
            timeframe = label
            break

    if not explicit and topics is None and timeframe is None:
        return DigestRequest()

    return DigestRequest(
        topics=topics,
        timeframe=timeframe,
        github_manual_urls=github_urls,
        github_target_channels=github_channels,
        bilibili_manual_urls=bilibili_urls,
        bilibili_target_channels=bilibili_channels,
        juya_manual_urls=juya_urls,
    )


__all__ = ["parse_connector_names_from_message", "parse_digest_intent"]
