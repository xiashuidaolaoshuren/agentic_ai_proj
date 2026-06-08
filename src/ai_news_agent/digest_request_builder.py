"""Build merged :class:`~ai_news_agent.request.DigestRequest` values for chat/UI entrypoints."""

from __future__ import annotations

from dataclasses import replace

from ai_news_agent.intent import parse_connector_names_from_message, parse_digest_intent
from ai_news_agent.request import DigestRequest
from ai_news_agent.sources import normalize_source_names

_BILIBILI_CHANNEL_DEFAULT_TIMEFRAME = "last_7_days"


def _apply_bilibili_channel_timeframe_default(req: DigestRequest) -> DigestRequest:
    if req.timeframe is not None:
        return req
    has_bilibili_channel = bool(req.bilibili_target_channels or req.target_channels)
    if not has_bilibili_channel:
        return req
    return replace(req, timeframe=_BILIBILI_CHANNEL_DEFAULT_TIMEFRAME)


def resolve_digest_request(
    message: str,
    *,
    session_connector_names: list[str] | None = None,
) -> DigestRequest:
    """Merge parsed intent, session source toggles, and NL source overrides.

    Precedence for ``connector_names``:
    1. Explicit NL phrases in the message (e.g. ``github only``)
    2. Session-sticky UI toggles
    3. ``None`` (run all injected connectors)
    """
    parsed = parse_digest_intent(message)
    if parsed.has_explicit_selectors() or parsed.timeframe is not None:
        base = parsed
    else:
        base = DigestRequest()

    nl_names = parse_connector_names_from_message(message)
    if nl_names is not None:
        connector_names = normalize_source_names(nl_names)
    elif session_connector_names:
        connector_names = normalize_source_names(session_connector_names)
    else:
        connector_names = None

    base = _apply_bilibili_channel_timeframe_default(base)

    if connector_names == base.connector_names:
        return base
    return replace(base, connector_names=connector_names)


__all__ = ["resolve_digest_request"]
