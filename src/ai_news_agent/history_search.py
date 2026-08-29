"""Historical digest search service (Milestone 7D T4)."""

from __future__ import annotations

from typing import Any

from ai_news_agent.history import (
    HISTORY_CANDIDATE_CAP,
    HistoricalItemRef,
    HistorySearchMatch,
    HistorySearchQuery,
    HistorySearchResult,
    digest_topics_match_query,
    extract_historical_excerpt,
    historical_sort_key,
    score_historical_candidate,
)

_EMPTY_ARCHIVE_CAVEAT = "No saved digests to search."


def _format_no_match_caveat(query: HistorySearchQuery) -> str:
    parts: list[str] = []
    if query.text is not None:
        parts.append(f"text={query.text!r}")
    if query.sources:
        parts.append(f"sources={','.join(query.sources)}")
    if query.topics:
        parts.append(f"topics={','.join(query.topics)}")
    if query.since is not None:
        parts.append(f"since={query.since.isoformat()}")
    if query.until is not None:
        parts.append(f"until={query.until.isoformat()}")
    filters = ", ".join(parts)
    return f"No historical digest entries matched {filters}. Try broadening one criterion."


def _truncation_caveat(scanned_count: int) -> str:
    return (
        f"Search scanned the newest {scanned_count} matching entries; "
        "older archive rows were not searched."
    )


def _malformed_caveat(count: int) -> str:
    if count == 1:
        return "Skipped 1 malformed historical row."
    return f"Skipped {count} malformed historical row(s)."


def _candidate_to_match(
    *,
    query: HistorySearchQuery,
    candidate: dict[str, Any],
    score: float,
) -> HistorySearchMatch:
    ref = HistoricalItemRef(
        digest_id=int(candidate["digest_id"]),
        run_id=int(candidate["run_id"]),
        entry_id=int(candidate["entry_id"]),
        rank=int(candidate["rank"]),
    )
    return HistorySearchMatch(
        ref=ref,
        generated_at=candidate["generated_at"],
        source_kind=candidate["source_kind"],
        title=str(candidate["title"]),
        url=str(candidate["source_url"]),
        excerpt=extract_historical_excerpt(query=query, candidate=candidate),
        score=score,
    )


def search_digest_history(
    store: Any,
    query: HistorySearchQuery,
    *,
    cap: int = HISTORY_CANDIDATE_CAP,
) -> HistorySearchResult:
    """Search saved digest entries with topic AND-match and lexical scoring."""
    rows, archive_truncated = store.list_historical_digest_entries(
        sources=query.sources,
        since=query.since,
        until=query.until,
        cap=cap,
    )
    scanned_count = len(rows)
    caveats: list[str] = []

    if not rows:
        probe_rows, _ = store.list_historical_digest_entries(cap=1)
        if not probe_rows:
            return HistorySearchResult(caveats=[_EMPTY_ARCHIVE_CAVEAT])
        return HistorySearchResult(caveats=[_format_no_match_caveat(query)])

    if archive_truncated:
        caveats.append(_truncation_caveat(scanned_count))

    scored: list[tuple[dict[str, Any], float]] = []
    malformed_count = 0

    for row in rows:
        try:
            if query.topics and not digest_topics_match_query(
                query_topics=query.topics,
                digest_topics=row.get("digest_topics") or [],
            ):
                continue
            score = score_historical_candidate(query=query, candidate=row)
            if score is None:
                continue
            scored.append((row, score))
        except (KeyError, TypeError, ValueError):
            malformed_count += 1

    if malformed_count:
        caveats.append(_malformed_caveat(malformed_count))

    if not scored:
        caveats.append(_format_no_match_caveat(query))
        return HistorySearchResult(
            scanned_count=scanned_count,
            archive_truncated=archive_truncated,
            caveats=caveats,
        )

    scored.sort(
        key=lambda item: historical_sort_key(query=query, candidate=item[0]),
        reverse=True,
    )
    limited = scored[: query.limit]

    matches: list[HistorySearchMatch] = []
    for row, score in limited:
        try:
            matches.append(_candidate_to_match(query=query, candidate=row, score=score))
        except (KeyError, TypeError, ValueError):
            malformed_count += 1

    if malformed_count and not any(c.startswith("Skipped") for c in caveats):
        caveats.append(_malformed_caveat(malformed_count))
    elif malformed_count:
        caveats = [c for c in caveats if not c.startswith("Skipped")]
        caveats.append(_malformed_caveat(malformed_count))

    return HistorySearchResult(
        matches=matches,
        scanned_count=scanned_count,
        archive_truncated=archive_truncated,
        caveats=caveats,
    )
