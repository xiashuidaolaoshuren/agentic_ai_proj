"""Historical digest search types, tokens, and validation (Milestone 7D T1)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_news_agent.models import SourceKind
from ai_news_agent.sources import ALLOWED_SOURCES

HISTORY_CANDIDATE_CAP = 10_000
_EXCERPT_MAX_LEN = 160

_HISTORICAL_ITEM_REF_PATTERN = re.compile(r"^d(\d+):r(\d+)$")


class HistoricalItemRef(BaseModel):
    """Stable pointer to one saved digest entry."""

    model_config = ConfigDict(extra="ignore")

    digest_id: int
    run_id: int
    entry_id: int
    rank: int


class HistorySearchQuery(BaseModel):
    """Input for historical digest search."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    sources: list[str] | None = None
    topics: list[str] | None = None
    since: date | None = None
    until: date | None = None
    limit: int = Field(default=10)

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_blank_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for name in value:
            key = str(name).strip().lower()
            if not key:
                continue
            if key not in ALLOWED_SOURCES:
                allowed = ", ".join(sorted(ALLOWED_SOURCES))
                raise ValueError(f"Unknown source {key!r}; allowed: {allowed}")
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, value: int) -> int:
        if value < 1 or value > 50:
            raise ValueError("limit must be between 1 and 50")
        return value

    @model_validator(mode="after")
    def _validate_query(self) -> HistorySearchQuery:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must not be after until")
        if not self._has_search_criterion():
            raise ValueError("at least one search criterion is required")
        return self

    def _has_search_criterion(self) -> bool:
        if self.text is not None:
            return True
        if self.sources:
            return True
        if self.topics:
            return True
        if self.since is not None or self.until is not None:
            return True
        return False


class HistorySearchMatch(BaseModel):
    """One ranked historical digest entry match."""

    model_config = ConfigDict(extra="ignore")

    ref: HistoricalItemRef
    generated_at: datetime
    source_kind: SourceKind
    title: str
    url: str
    excerpt: str | None = None
    score: float


class HistorySearchResult(BaseModel):
    """Historical search response envelope."""

    model_config = ConfigDict(extra="ignore")

    matches: list[HistorySearchMatch] = Field(default_factory=list)
    scanned_count: int = 0
    archive_truncated: bool = False
    caveats: list[str] = Field(default_factory=list)


def format_historical_item_ref(ref: HistoricalItemRef) -> str:
    return f"d{ref.digest_id}:r{ref.rank}"


def parse_historical_item_ref(token: str) -> HistoricalItemRef:
    match = _HISTORICAL_ITEM_REF_PATTERN.match(token.strip())
    if match is None:
        raise ValueError(f"Invalid historical item reference token: {token!r}")
    digest_id = int(match.group(1))
    rank = int(match.group(2))
    return HistoricalItemRef(digest_id=digest_id, run_id=0, entry_id=0, rank=rank)


def validate_history_search_query(**kwargs: Any) -> HistorySearchQuery:
    return HistorySearchQuery(**kwargs)


_SEARCHABLE_FIELD_KEYS = ("title", "summary", "why_it_matters", "background_knowledge")


def _normalize_history_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _candidate_searchable_fields(candidate: dict[str, Any]) -> list[str]:
    return [
        _normalize_history_text(str(candidate.get(key, "") or ""))
        for key in _SEARCHABLE_FIELD_KEYS
    ]


def _candidate_digest_topics(candidate: dict[str, Any]) -> list[str]:
    topics = candidate.get("digest_topics") or []
    return [_normalize_history_text(str(topic)) for topic in topics]


def _term_found_in_candidate(term: str, fields: list[str], topics: list[str]) -> bool:
    for field in fields:
        if term in field:
            return True
    for topic in topics:
        if term in topic:
            return True
    return False


def _lexical_match(query_text: str, fields: list[str], topics: list[str]) -> bool:
    stripped = query_text.strip()
    if not stripped:
        return False
    if any(ch.isspace() for ch in stripped):
        terms = [_normalize_history_text(part) for part in stripped.split()]
        return all(_term_found_in_candidate(term, fields, topics) for term in terms)
    phrase = _normalize_history_text(stripped)
    return _term_found_in_candidate(phrase, fields, topics)


def _phrase_in_title(phrase: str, title: str) -> bool:
    return phrase in _normalize_history_text(title)


def _phrase_in_searchable(phrase: str, fields: list[str]) -> bool:
    return any(phrase in field for field in fields)


def _all_terms_in_title(query_text: str, title: str) -> bool:
    stripped = query_text.strip()
    normalized_title = _normalize_history_text(title)
    if any(ch.isspace() for ch in stripped):
        terms = [_normalize_history_text(part) for part in stripped.split()]
        return all(term in normalized_title for term in terms)
    phrase = _normalize_history_text(stripped)
    return phrase in normalized_title


def _topic_equality(query_text: str, topics: list[str]) -> bool:
    stripped = query_text.strip()
    if any(ch.isspace() for ch in stripped):
        terms = [_normalize_history_text(part) for part in stripped.split()]
        topic_set = set(topics)
        return any(term in topic_set for term in terms)
    phrase = _normalize_history_text(stripped)
    return phrase in topics


def _term_coverage(query_text: str, fields: list[str]) -> float:
    stripped = query_text.strip()
    if not any(ch.isspace() for ch in stripped):
        phrase = _normalize_history_text(stripped)
        return 1.0 if any(phrase in field for field in fields) else 0.0
    terms = [_normalize_history_text(part) for part in stripped.split()]
    if not terms:
        return 0.0
    found = sum(1 for term in terms if any(term in field for field in fields))
    return found / len(terms)


def _compute_lexical_score(
    query_text: str,
    candidate: dict[str, Any],
    fields: list[str],
    topics: list[str],
) -> float:
    phrase = _normalize_history_text(query_text.strip())
    title = str(candidate.get("title", "") or "")
    phrase_title = 1 if phrase and _phrase_in_title(phrase, title) else 0
    phrase_text = 1 if phrase and _phrase_in_searchable(phrase, fields) else 0
    title_terms = 1 if _all_terms_in_title(query_text, title) else 0
    topic_eq = 1 if _topic_equality(query_text, topics) else 0
    coverage = _term_coverage(query_text, fields)
    return float(
        16 * phrase_title + 8 * phrase_text + 4 * title_terms + 2 * topic_eq + coverage
    )


def score_historical_candidate(*, query: HistorySearchQuery, candidate: dict[str, Any]) -> float | None:
    if query.text is None:
        return 0.0
    fields = _candidate_searchable_fields(candidate)
    topics = _candidate_digest_topics(candidate)
    if not _lexical_match(query.text, fields, topics):
        return None
    return _compute_lexical_score(query.text, candidate, fields, topics)


def historical_sort_key(*, query: HistorySearchQuery, candidate: dict[str, Any]) -> tuple[float, datetime, int, int]:
    score = score_historical_candidate(query=query, candidate=candidate)
    if score is None:
        score = float("-inf")
    generated_at = candidate.get("generated_at")
    if not isinstance(generated_at, datetime):
        generated_at = datetime.min.replace(tzinfo=None)
    digest_id = int(candidate.get("digest_id", 0) or 0)
    rank = int(candidate.get("rank", 0) or 0)
    return (score, generated_at, digest_id, -rank)


def _query_match_terms(query_text: str) -> tuple[str, list[str]]:
    stripped = query_text.strip()
    phrase = _normalize_history_text(stripped)
    if any(ch.isspace() for ch in stripped):
        terms = [_normalize_history_text(part) for part in stripped.split()]
        return phrase, terms
    return phrase, [phrase]


def _field_contains_match(field: str, phrase: str, terms: list[str]) -> bool:
    normalized = _normalize_history_text(field)
    if phrase and phrase in normalized:
        return True
    return any(term in normalized for term in terms)


def _extract_excerpt_from_field(field: str, phrase: str, terms: list[str]) -> str | None:
    field_nfc = unicodedata.normalize("NFC", field)
    normalized = _normalize_history_text(field_nfc)
    match_start = -1
    if phrase and phrase in normalized:
        match_start = normalized.index(phrase)
    else:
        for term in terms:
            if term in normalized:
                match_start = normalized.index(term)
                break
    if match_start < 0:
        return None
    if len(field_nfc) <= _EXCERPT_MAX_LEN:
        return field_nfc
    end = min(len(field_nfc), match_start + _EXCERPT_MAX_LEN)
    return field_nfc[match_start:end]


def digest_topics_match_query(*, query_topics: list[str], digest_topics: list[str]) -> bool:
    """True when every requested topic NFC+case-folds to a digest topic string."""
    normalized_digest = {_normalize_history_text(str(topic)) for topic in digest_topics}
    return all(_normalize_history_text(str(topic)) in normalized_digest for topic in query_topics)


def extract_historical_excerpt(*, query: HistorySearchQuery, candidate: dict[str, Any]) -> str | None:
    if query.text is None:
        return None
    fields = _candidate_searchable_fields(candidate)
    topics = _candidate_digest_topics(candidate)
    if not _lexical_match(query.text, fields, topics):
        return None
    phrase, terms = _query_match_terms(query.text)
    raw_fields = [str(candidate.get(key, "") or "") for key in _SEARCHABLE_FIELD_KEYS]
    if not any(_field_contains_match(raw, phrase, terms) for raw in raw_fields):
        return None
    for raw in raw_fields:
        excerpt = _extract_excerpt_from_field(raw, phrase, terms)
        if excerpt is not None:
            return excerpt
    return None


__all__ = [
    "HISTORY_CANDIDATE_CAP",
    "HistoricalItemRef",
    "HistorySearchMatch",
    "HistorySearchQuery",
    "HistorySearchResult",
    "digest_topics_match_query",
    "format_historical_item_ref",
    "extract_historical_excerpt",
    "historical_sort_key",
    "parse_historical_item_ref",
    "score_historical_candidate",
    "validate_history_search_query",
]
