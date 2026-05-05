"""Default AI topic taxonomy and query seeds for connectors."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_TOPICS: tuple[str, ...] = (
    "AI agents",
    "model releases",
    "RAG",
    "multimodal AI",
    "AI developer tools",
    "notable open-source repos",
)


def build_queries(
    topics: Sequence[str] | None,
    timeframe: str | None,
    max_terms: int,
) -> list[str]:
    """Build connector-facing query strings from topics and optional timeframe.

    ``topics=None`` uses :data:`DEFAULT_TOPICS`. An empty sequence yields
    an empty list (explicit "no topics" request).
    """
    if max_terms < 0:
        raise ValueError("max_terms must be non-negative")
    if topics is None:
        base = list(DEFAULT_TOPICS)
    else:
        base = list(topics)
    out: list[str] = []
    for t in base:
        if len(out) >= max_terms:
            break
        if timeframe:
            out.append(f"{t} ({timeframe})")
        else:
            out.append(t)
    return out
