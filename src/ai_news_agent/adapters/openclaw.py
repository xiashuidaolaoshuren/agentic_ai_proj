"""OpenClaw-facing helpers for safe digest CLI argument shaping."""

from __future__ import annotations

from dataclasses import replace

from ai_news_agent.digest_request_builder import resolve_digest_request
from ai_news_agent.intent import parse_connector_names_from_message
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import (
    DEFAULT_SOURCE_NAMES,
    normalize_source_names,
    parse_sources_csv,
)

_TIMEFRAME_ALIASES: dict[str, str] = {
    "daily": "today",
    "week": "last_7_days",
    "last7": "last_7_days",
}

_OUTPUT_STYLE_ALIASES: dict[str, str] = {
    "newsletter": "editorial",
    "bulletin": "bulletin",
}

_OUTPUT_LANGUAGE_ALIASES: dict[str, str] = {
    "chinese": "zh-CN",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
}


def normalize_source_hint(hint: str | None) -> list[str]:
    """Normalize an OpenClaw source hint into validated connector names."""
    if hint is None or hint.strip() == "":
        return list(DEFAULT_SOURCE_NAMES)
    parsed = parse_sources_csv(hint)
    if not parsed:
        return list(DEFAULT_SOURCE_NAMES)
    return normalize_source_names(parsed)


def normalize_timeframe_hint(hint: str | None) -> str:
    """Normalize an OpenClaw timeframe hint into a canonical CLI value."""
    if hint is None or hint.strip() == "":
        return "today"
    key = hint.strip().lower()
    return _TIMEFRAME_ALIASES.get(key, key)


def normalize_topic_hint(hint: str | None) -> list[str] | None:
    """Normalize an OpenClaw topic hint into a trimmed list, or ``None`` when absent."""
    if hint is None or hint.strip() == "":
        return None
    topics = [part.strip() for part in hint.split(",") if part.strip()]
    if not topics:
        return None
    return topics


def normalize_output_style_hint(hint: str | None) -> str | None:
    """Normalize output style hints; ``None`` preserves the default bulletin renderer."""
    if hint is None or hint.strip() == "":
        return None
    key = hint.strip().lower()
    return _OUTPUT_STYLE_ALIASES.get(key, key)


def normalize_output_language_hint(hint: str | None) -> str | None:
    """Normalize BCP-47 language hints such as ``zh-CN``."""
    if hint is None or hint.strip() == "":
        return None
    key = hint.strip().lower()
    return _OUTPUT_LANGUAGE_ALIASES.get(key, hint.strip())


def _infer_connector_names_from_selectors(req: DigestRequest) -> list[str] | None:
    """Infer connector scope from explicit URL/channel selectors when unset."""
    has_github = bool(req.github_manual_urls or req.github_target_channels)
    has_bilibili = bool(
        req.bilibili_manual_urls
        or req.bilibili_target_channels
        or req.manual_urls
        or req.target_channels
    )
    if has_github and has_bilibili:
        return list(DEFAULT_SOURCE_NAMES)
    if has_github:
        return ["github"]
    if has_bilibili:
        return ["bilibili"]
    return None


def validate_source_selector_consistency(req: DigestRequest) -> None:
    """Reject contradictory source toggles vs explicit URL/channel selectors."""
    names = list(req.connector_names or [])
    if not names:
        return

    has_bilibili_selector = bool(
        req.bilibili_manual_urls
        or req.bilibili_target_channels
        or req.manual_urls
        or req.target_channels
    )
    has_github_selector = bool(req.github_manual_urls or req.github_target_channels)

    if names == ["github"] and has_bilibili_selector:
        raise ValueError(
            "Source selection is 'github only' but the request includes Bilibili "
            "video/channel selectors. Remove the conflicting source toggle or selector."
        )
    if names == ["bilibili"] and has_github_selector:
        raise ValueError(
            "Source selection is 'bilibili only' but the request includes GitHub "
            "repo/channel selectors. Remove the conflicting source toggle or selector."
        )


def resolve_openclaw_digest_request(
    *,
    message: str | None = None,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
) -> DigestRequest:
    """Build a digest request from NL message and/or structured OpenClaw hints."""
    style = normalize_output_style_hint(output_style_hint)
    language = normalize_output_language_hint(output_language_hint)
    style_kw: dict[str, object] = {}
    if style is not None:
        style_kw["output_style"] = style
    if language is not None:
        style_kw["output_language"] = language

    if message is not None and message.strip():
        req = resolve_digest_request(message.strip())
        nl_sources = parse_connector_names_from_message(message)
        if nl_sources is not None:
            req = replace(req, connector_names=normalize_source_names(nl_sources))
        elif sources_hint is not None and sources_hint.strip():
            req = replace(
                req,
                connector_names=normalize_source_hint(sources_hint),
            )
        elif req.connector_names is None:
            inferred = _infer_connector_names_from_selectors(req)
            if inferred is not None:
                req = replace(req, connector_names=inferred)
        if style_kw:
            req = replace(req, **style_kw)
        validate_source_selector_consistency(req)
        return req

    kw: dict[str, object] = {
        "connector_names": normalize_source_hint(sources_hint),
        **style_kw,
    }
    if timeframe_hint is not None and timeframe_hint.strip():
        kw["timeframe"] = normalize_timeframe_hint(timeframe_hint)
    topics = normalize_topic_hint(topics_hint)
    if topics is not None:
        kw["topics"] = topics
    req = DigestRequest(**kw)
    validate_source_selector_consistency(req)
    return req


def build_digest_cli_argv(
    *,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
) -> list[str]:
    """Build a safe argv token list for ``ai-news-agent digest`` (no shell interpolation)."""
    timeframe = normalize_timeframe_hint(timeframe_hint)
    sources = normalize_source_hint(sources_hint)
    topics = normalize_topic_hint(topics_hint)
    output_style = normalize_output_style_hint(output_style_hint)
    output_language = normalize_output_language_hint(output_language_hint)

    argv: list[str] = [
        "digest",
        "--timeframe",
        timeframe,
        "--sources",
        ",".join(sources),
    ]
    if topics is not None:
        argv.extend(["--topics", ",".join(topics)])
    if output_style is not None:
        argv.extend(["--output-style", output_style])
    if output_language is not None:
        argv.extend(["--output-language", output_language])
    return argv


def build_digest_request_from_hints(
    *,
    timeframe_hint: str | None = None,
    sources_hint: str | None = None,
    topics_hint: str | None = None,
    output_style_hint: str | None = None,
    output_language_hint: str | None = None,
) -> DigestRequest:
    """Build a :class:`~ai_news_agent.request.DigestRequest` from OpenClaw hints."""
    timeframe = normalize_timeframe_hint(timeframe_hint)
    sources = normalize_source_hint(sources_hint)
    topics = normalize_topic_hint(topics_hint)
    output_style = normalize_output_style_hint(output_style_hint)
    output_language = normalize_output_language_hint(output_language_hint)
    kw: dict[str, object] = {
        "timeframe": timeframe,
        "connector_names": sources,
    }
    if topics is not None:
        kw["topics"] = topics
    if output_style is not None:
        kw["output_style"] = output_style
    if output_language is not None:
        kw["output_language"] = output_language
    return DigestRequest(**kw)


__all__ = [
    "build_digest_cli_argv",
    "build_digest_request_from_hints",
    "normalize_output_language_hint",
    "normalize_output_style_hint",
    "normalize_source_hint",
    "normalize_timeframe_hint",
    "normalize_topic_hint",
    "resolve_openclaw_digest_request",
    "validate_source_selector_consistency",
]
