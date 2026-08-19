"""Build merged :class:`~ai_news_agent.request.DigestRequest` values for chat/UI entrypoints."""

from __future__ import annotations

from dataclasses import replace

from ai_news_agent.intent import parse_connector_names_from_message, parse_digest_intent
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import normalize_source_names, resolve_connector_names

_BILIBILI_CHANNEL_DEFAULT_TIMEFRAME = "last_7_days"


def _apply_bilibili_channel_timeframe_default(req: DigestRequest) -> DigestRequest:
    if req.timeframe is not None:
        return req
    has_bilibili_channel = bool(req.bilibili_target_channels or req.target_channels)
    if not has_bilibili_channel:
        return req
    return replace(req, timeframe=_BILIBILI_CHANNEL_DEFAULT_TIMEFRAME)


def _infer_connector_names_from_selectors(req: DigestRequest) -> list[str] | None:
    """Infer connector scope from explicit URL/channel selectors (no DEFAULT fallback).

    Returns names in canonical discovery order (github, bilibili, juya) or ``None``
    when no platform selector is present. Mixed selectors produce a union, never
    :data:`~ai_news_agent.sources.DEFAULT_SOURCE_NAMES`.
    """
    implied: list[str] = []
    if req.github_manual_urls or req.github_target_channels:
        implied.append("github")
    if (
        req.bilibili_manual_urls
        or req.bilibili_target_channels
        or req.manual_urls
        or req.target_channels
    ):
        implied.append("bilibili")
    if req.juya_manual_urls:
        implied.append("juya")
    return implied if implied else None


def _parsed_has_digest_fields(parsed: DigestRequest) -> bool:
    return (
        parsed.has_explicit_selectors()
        or parsed.timeframe is not None
        or parsed.huggingface_discovery_mode is not None
        or parsed.huggingface_search is not None
        or parsed.huggingface_pipeline_tag is not None
    )


def resolve_digest_request(
    message: str,
    *,
    session_connector_names: list[str] | None = None,
) -> DigestRequest:
    """Merge parsed intent, session source toggles, and NL source overrides.

    Precedence for ``connector_names``:
    1. Explicit NL phrases in the message (e.g. ``github only``, ``trending repos``)
    2. Platform/target inference from explicit selectors (replaces Juya default)
    3. Session-sticky UI toggles (only when the message has no platform cue)
    4. ``resolve_connector_names(None)`` → :data:`~ai_news_agent.sources.DEFAULT_SOURCE_NAMES`

    ``primary_source`` is set to the first resolved connector name for downstream
    ranking/rendering (T5).
    """
    parsed = parse_digest_intent(message)
    if _parsed_has_digest_fields(parsed):
        base = parsed
    else:
        base = DigestRequest()

    nl_names = parse_connector_names_from_message(message)
    if nl_names is not None:
        connector_names = normalize_source_names(nl_names)
    else:
        inferred = _infer_connector_names_from_selectors(base)
        if inferred is not None:
            connector_names = list(inferred)
        elif session_connector_names:
            connector_names = normalize_source_names(session_connector_names)
        else:
            connector_names = resolve_connector_names(None)

    base = _apply_bilibili_channel_timeframe_default(base)

    primary_source = connector_names[0] if connector_names else None

    if connector_names == base.connector_names and primary_source == base.primary_source:
        return base
    return replace(base, connector_names=connector_names, primary_source=primary_source)


__all__ = ["resolve_digest_request"]
