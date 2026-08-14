"""Deterministic ranking for digest candidate selection (Task 7).

Scoring is weighted; inspect evidence via :attr:`RankedItem.score_breakdown`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from ai_news_agent.models import ConfidenceLevel, NewsItem, RankedItem, SourceKind, utcnow

# --- Weight constants (deterministic MVP) ---
_W_FRESH = 2.0
_W_RELEVANCE = 1.5
_W_METADATA = 1.0
_W_SOURCE = 0.6
_W_ENGAGEMENT = 0.8
_W_CONFIDENCE = 0.4

_GITHUB_BASE = 1.0
_BILIBILI_BASE = 0.88
_JUYA_BASE = 1.05
_MAX_ENGAGEMENT_REF = 50_000.0


def rank_items(
    items: list[NewsItem],
    *,
    top_n: int,
    now: datetime | None = None,
    timeframe: str | None = None,
) -> list[RankedItem]:
    """Score, deduplicate, and mark top-N candidates.

    ``now`` is injected for deterministic tests; defaults to :func:`utcnow`.
    """
    reference = now if now is not None else utcnow()
    reference = _ensure_aware(reference)

    if not items:
        return []

    deduped = _dedupe_by_clusters(items, reference)
    ranked: list[RankedItem] = []
    for it in deduped:
        bd, total = _score_item(it, reference)
        ranked.append(
            RankedItem(
                item=it,
                score_total=round(total, 6),
                score_breakdown=bd,
                selected=False,
                selection_reason="",
            )
        )

    def sort_key(ri: RankedItem) -> tuple[float, float, str]:
        ts = _reference_time(ri.item, reference)
        return (-ri.score_total, -ts.timestamp(), ri.item.source_id)

    ranked.sort(key=sort_key)

    for i, ri in enumerate(ranked):
        if i < top_n:
            ri.selected = True
            ri.selection_reason = f"rank #{i + 1} of {len(ranked)} by score_total"
        else:
            ri.selected = False
            ri.selection_reason = ""

    _apply_newest_bilibili_guarantee(
        ranked,
        top_n=top_n,
        timeframe=timeframe,
        reference=reference,
    )

    return ranked


def _apply_newest_bilibili_guarantee(
    ranked: list[RankedItem],
    *,
    top_n: int,
    timeframe: str | None,
    reference: datetime,
) -> None:
    if top_n <= 0 or not timeframe:
        return
    candidate = find_newest_in_window_bilibili_candidate(
        ranked,
        timeframe=timeframe,
        now=reference,
    )
    if candidate is None or candidate.selected:
        return

    selected = [ri for ri in ranked if ri.selected]
    if not selected:
        candidate.selected = True
        candidate.selection_reason = "guaranteed newest in-window bilibili item"
        return

    replace_target = min(
        selected,
        key=lambda ri: (
            ri.score_total,
            _reference_time(ri.item, reference).timestamp(),
            ri.item.source_id,
        ),
    )
    replace_target.selected = False
    replace_target.selection_reason = ""
    candidate.selected = True
    candidate.selection_reason = "guaranteed newest in-window bilibili item"


def find_newest_in_window_bilibili_candidate(
    ranked: list[RankedItem],
    *,
    timeframe: str | None,
    now: datetime,
) -> RankedItem | None:
    """Return the newest Bilibili item with publish time inside the digest timeframe."""
    if not timeframe:
        return None
    reference = _ensure_aware(now)
    candidates = [
        ri
        for ri in ranked
        if ri.item.source is SourceKind.BILIBILI
        and ri.item.published_at is not None
        and _item_published_within_timeframe(ri.item, timeframe, reference)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda ri: _ensure_aware(ri.item.published_at).timestamp(),  # type: ignore[arg-type]
    )


_FALLBACK_KIND_ORDER: tuple[SourceKind, ...] = (
    SourceKind.JUYA,
    SourceKind.GITHUB,
    SourceKind.BILIBILI,
)


def order_selected_for_digest(
    ranked_items: list[RankedItem],
    *,
    timeframe: str | None,
    now: datetime,
    primary_source: str | None = None,
) -> list[RankedItem]:
    """Return selected rows in digest iteration order.

    Single-kind digests keep relevance order with newest-in-window Bilibili first
    when a timeframe is set. Mixed digests group by source section: primary intent
    first, otherwise Juya → GitHub → Bilibili, omitting empty kinds.
    """
    selected = [r for r in ranked_items if r.selected]
    if not selected:
        return selected

    kinds = {r.item.source for r in selected}
    if len(kinds) < 2:
        if not timeframe:
            return selected
        newest = find_newest_in_window_bilibili_candidate(
            ranked_items,
            timeframe=timeframe,
            now=now,
        )
        if newest is None or not newest.selected:
            return selected
        return [newest] + [r for r in selected if r is not newest]

    kind_to_rows: dict[SourceKind, list[RankedItem]] = {}
    for row in selected:
        kind_to_rows.setdefault(row.item.source, []).append(row)

    ordered: list[RankedItem] = []
    for kind in _digest_section_kind_order(primary_source):
        rows = kind_to_rows.get(kind)
        if not rows:
            continue
        if kind is SourceKind.BILIBILI:
            ordered.extend(_order_bilibili_section(rows, timeframe=timeframe, now=now))
        else:
            ordered.extend(rows)
    return ordered


def _digest_section_kind_order(primary_source: str | None) -> tuple[SourceKind, ...]:
    if primary_source:
        try:
            primary = SourceKind(primary_source)
        except ValueError:
            primary = None
        if primary is not None and primary in _FALLBACK_KIND_ORDER:
            rest = [kind for kind in _FALLBACK_KIND_ORDER if kind != primary]
            return (primary, *rest)
    return _FALLBACK_KIND_ORDER


def _order_bilibili_section(
    rows: list[RankedItem],
    *,
    timeframe: str | None,
    now: datetime,
) -> list[RankedItem]:
    if not timeframe or not rows:
        return rows
    newest = find_newest_in_window_bilibili_candidate(
        rows,
        timeframe=timeframe,
        now=now,
    )
    if newest is None or newest not in rows:
        return rows
    return [newest] + [r for r in rows if r is not newest]


def _timeframe_bounds_at(
    timeframe: str | None,
    reference: datetime,
) -> tuple[datetime | None, datetime | None]:
    if not timeframe:
        return None, None
    key = timeframe.strip().lower()
    today = _ensure_aware(reference).date()
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


def _item_published_within_timeframe(
    item: NewsItem,
    timeframe: str | None,
    reference: datetime,
) -> bool:
    start, end_exclusive = _timeframe_bounds_at(timeframe, reference)
    if start is None or end_exclusive is None:
        return True
    if item.published_at is None:
        return False
    published = _ensure_aware(item.published_at)
    return start <= published < end_exclusive


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _reference_time(item: NewsItem, reference: datetime) -> datetime:
    return _ensure_aware(item.published_at or item.collected_at)


def _pre_score_dedupe(it: NewsItem, reference: datetime) -> float:
    meta = float(it.metadata_completeness)
    eng = math.log1p(max(0, int(it.stars_or_views or 0)))
    fresh = _freshness_raw(it, reference)
    return meta * 5.0 + eng * 0.02 + fresh * 3.0


def _dedupe_by_clusters(items: list[NewsItem], reference: datetime) -> list[NewsItem]:
    """Greedy keep highest pre_score items without key conflicts."""

    order = sorted(items, key=lambda it: _pre_score_dedupe(it, reference), reverse=True)
    taken: set[str] = set()
    kept: list[NewsItem] = []
    for it in order:
        keys = _cluster_keys(it)
        if any(k in taken for k in keys):
            continue
        kept.append(it)
        taken.update(keys)

    # Restore original relative order among survivors (stable UX)
    surv = {id(x) for x in kept}
    return [it for it in items if id(it) in surv]


def _cluster_keys(it: NewsItem) -> list[str]:
    return [
        f"id:{it.source}:{it.source_id}",
        f"url:{_normalize_url(it.url)}",
        f"title:{_normalize_title(it.title)}",
    ]


def _normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    netloc = (p.netloc or "").lower()
    path = ((p.path or "").rstrip("/") or "/").lower()
    scheme = (p.scheme or "https").lower()
    return f"{scheme}://{netloc}{path}"


def _normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


def _score_item(item: NewsItem, reference: datetime) -> tuple[dict[str, float], float]:
    bd: dict[str, float] = {}
    fresh_r = _freshness_raw(item, reference)
    rel = _relevance_raw(item)
    meta = max(0.0, min(1.0, float(item.metadata_completeness)))
    src = _source_base(item.source)
    eng = _engagement_raw(item)
    conf = _confidence_raw(item)

    bd["freshness"] = round(fresh_r * _W_FRESH, 6)
    bd["relevance"] = round(rel * _W_RELEVANCE, 6)
    bd["metadata"] = round(meta * _W_METADATA, 6)
    bd["source_quality"] = round(src * _W_SOURCE, 6)
    if item.source is SourceKind.GITHUB:
        bd["momentum"] = round(eng * fresh_r * _W_ENGAGEMENT, 6)
    elif item.source is SourceKind.JUYA:
        bulletin = 1.0 if item.raw_snippet and str(item.raw_snippet).strip() else 0.4
        bd["bulletin"] = round(bulletin * _W_ENGAGEMENT, 6)
    else:
        bd["engagement"] = round(eng * _W_ENGAGEMENT, 6)
    bd["confidence_adj"] = round(conf * _W_CONFIDENCE, 6)

    if item.raw_snippet is None or not str(item.raw_snippet).strip():
        bd["weak_snippet_penalty"] = -0.35

    return bd, float(sum(bd.values()))


def _source_base(source: SourceKind) -> float:
    if source is SourceKind.GITHUB:
        return _GITHUB_BASE
    if source is SourceKind.JUYA:
        return _JUYA_BASE
    return _BILIBILI_BASE


def _confidence_raw(item: NewsItem) -> float:
    cc = item.content_confidence
    if cc is None:
        return -0.12
    if cc is ConfidenceLevel.HIGH:
        return 0.35
    if cc is ConfidenceLevel.MEDIUM:
        return 0.0
    return -0.35


def _engagement_raw(item: NewsItem) -> float:
    v = int(item.stars_or_views or 0)
    cap = int(_MAX_ENGAGEMENT_REF)
    return math.log1p(min(v, cap)) / math.log1p(cap)


def _relevance_raw(item: NewsItem) -> float:
    n = len(item.topic_matches or [])
    if n == 0:
        return 0.2
    return min(1.0, 0.2 + 0.2 * n)


def _freshness_raw(item: NewsItem, reference: datetime) -> float:
    t = _reference_time(item, reference)
    age_days = (reference - t).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 30:
        return 0.6
    if age_days <= 90:
        return 0.35
    return 0.15


# timedelta import unused - remove