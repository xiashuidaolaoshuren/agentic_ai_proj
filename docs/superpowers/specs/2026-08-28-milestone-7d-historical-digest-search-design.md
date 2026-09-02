# Milestone 7D.1: Historical Digest Search

Date: 2026-08-28  
Status: approved design

## Summary

Milestone 7 in the parent spec mixed four independent jobs: quality evaluation, scheduling, deployment, and cross-digest memory. This design is the first memory slice only.

**7D.1** lets a user search saved digest entries by text, source, topic, and date, then reopen one historical item by a stable reference. Search is fully local and deterministic. Opening a hit does not change latest-digest follow-up context.

Domain terms live in `CONTEXT.md`. The scan-versus-memory decision lives in `docs/adr/0007-historical-digest-search-without-vectors.md`. This design amends the Milestone 7 section of `2026-05-02-ai-news-research-agent-design.md`.

## Milestone 7 Decomposition

| Slice | Job | This design |
|-------|-----|-------------|
| 7A | Automated quality evaluation | Deferred |
| 7B | Scheduled daily/weekly digests | Deferred |
| 7C | Deployment / lightweight API | Deferred |
| 7D.1 | Historical digest search and read-only reopen | **In scope** |
| 7D.2+ | Trend synthesis, personalization, conversation memory, FTS, vectors | Deferred |

## Goals

- Find past saved digest entries by optional text plus source, topic, and/or date filters.
- Reopen one historical item by a stable `d<digest_id>:r<rank>` reference without changing which digest is latest.
- Keep search and reopen deterministic, fully local, and free of embeddings or external APIs.
- Expose the same service through CLI commands and Gradio chat (live and fake).
- Reuse existing kind-specific rank-card formatters from persisted evidence only.

## Non-Goals

- Cross-digest synthesis (“what changed in RAG this month”).
- User-interest personalization or feedback memory.
- Conversation / chat-session memory.
- OpenClaw history search or history-show.
- SQLite FTS5, local embeddings, or a vector index.
- Schema migration or new SQLite tables.
- Searching collected-but-unselected `NewsItem` rows.
- Switching latest-digest follow-up context to an older digest.
- Live Hugging Face, Zhihu, or Bilibili enrichment on historical open.
- New structured follow-up phrases for the latest digest.
- Quality evaluation, scheduling, or deployment (7A–7C).

## Chosen Architecture

Keep historical reads off the latest-digest write path.

- `HistorySearchQuery` is the input: optional text, sources, topics, since/until dates, and a bounded limit. At least one of text, sources, topics, since, or until is required.
- `DigestStore` gains historical read methods over existing `runs`, `digests`, and `digest_entries`. `get_latest_followup_context()` and the persist workflow stay unchanged.
- A history-search service applies SQL filters, then deterministic lexical ranking, and returns `HistorySearchResult`. Storage retrieves candidates; the service owns scoring so FTS can replace the scan later without changing callers.
- Each match carries an immutable `HistoricalItemRef` (`digest_id`, `run_id`, `entry_id`, original display rank). User-facing token is `d<digest_id>:r<rank>`.
- History show loads that exact persisted digest and rank and formats it with the existing Juya / Hugging Face / Zhihu / generic rank cards. It never updates latest-digest context and never calls connectors.
- CLI adds `history-search` and `history-show`. Gradio intercepts explicit history commands in `ChatService` before digest routing and before the interface tool router, in both live and fake modes.

Alternatives rejected:

- SQLite FTS5 in 7D.1 — better scale, but needs migration, backfill, and multilingual tokenizer work before archive size has proven the scan insufficient.
- Local or remote embeddings — conflicts with the offline constraint and makes ranking harder to explain.
- Making an opened digest the active follow-up context — silently breaks “latest digest” for later structured phrases.
- Returning a complete card inside every search hit — duplicates rank-card presentation and hides the stable reference contract.

## Search Behavior

Search targets **saved digest entries only**, not unselected collected candidates.

### Query contract

| Field | Rule |
|-------|------|
| `text` | Optional. Unicode NFC, case-folded for matching. Blank text is treated as absent. |
| `sources` | Optional canonical names (`juya`, `huggingface`, `github`, `zhihu`, `bilibili`). Unknown names are a validation error. |
| `topics` | Optional. Every requested topic must equal one of the **digest’s saved topics** after case-fold (AND). Not per-entry `topic_matches`. |
| `since` / `until` | Optional inclusive calendar dates (`YYYY-MM-DD`) applied to `digest.generated_at` in UTC. `since` after `until` is a validation error. |
| `limit` | Default 10, maximum 50, minimum 1. |

Filters combine with **AND**. At least one of text, sources, topics, since, or until must be present.

### Candidate retrieval

SQL applies source, topic, and date filters and returns matching entries newest-first by `generated_at`, then `digest_id` descending, then original display rank ascending.

Original **display rank** is the 1-based index of the entry in that digest’s stored list (`digest_entries` in insert/`id` order). It is not stored as a column.

Scan at most **10,000** matching entries. If more rows match the filters, return the scored top `limit` from those 10,000 newest candidates and set an archive-truncated caveat. Do not silently imply the full archive was searched.

### Lexical scoring

Searchable text for an entry is title, summary, why-it-matters, and background-knowledge.

- Space-delimited queries: every term must appear somewhere in searchable text or in the digest topics; otherwise the entry is not a match.
- An unsegmented query (no whitespace after NFC trim), including typical Chinese queries, matches as a substring of searchable text or of any digest topic.
- Filter-only queries (no text) skip lexical matching; all filter-matching candidates remain eligible.

Score components, all boolean or unit-interval, combined as a total order (higher first):

1. Exact phrase in title
2. Exact phrase in searchable text
3. All terms in title (space-delimited queries only; unsegmented queries treat a title substring as this hit)
4. Any query term equals a digest topic (case-folded)
5. Term coverage: fraction of terms found in searchable text (unsegmented query is 1.0 on a substring hit)
6. Recency: `generated_at` newer first
7. Tie-break: `digest_id` descending, then original display rank ascending

The same query against the same store always returns the same order.

### Result rows

Each match shows:

- reference token `d<digest_id>:r<rank>`
- digest generation date (UTC date of `generated_at`)
- source kind
- title
- source URL
- a short matched excerpt (the first searchable field that contains the phrase or a term; omit when the query is filter-only)
- internal score used only for ordering (not required in CLI/Gradio chrome)

The same URL or `source_id` appearing in two digests remains two rows. Each row is evidence from one historical digest.

## History Show

`history-show` / `open history d12:r3` resolves the reference to one persisted digest and its original **display rank**.

- Load that digest’s entries and the matching `NewsItem` from **that run** (same source_id/URL match as latest-digest rank cards). A missing `NewsItem` still yields the kind-specific degraded card.
- Format with the existing rank-card path: Juya issue deep-dive, Hugging Face family card, Zhihu practitioner-insight card, otherwise generic reprint.
- Historical open is **persist-only for every source kind**. Do not call Hugging Face model-card enrich, Bilibili transcript enrich, or any other connector.
- Do not write to the store.
- Do not change `get_latest_followup_context()`.

A missing digest, missing rank, or malformed token is `not found`. Do not guess a nearest digest or rank.

## Interfaces

### Shared types

- `HistorySearchQuery` — text, sources, topics, since, until, limit
- `HistoricalItemRef` — `digest_id`, `run_id`, `entry_id`, `rank`; token `d<digest_id>:r<rank>`
- `HistorySearchMatch` — ref, generated date, source kind, title, URL, excerpt, score
- `HistorySearchResult` — matches, scanned count, archive-truncated flag, caveats

CLI and Gradio call the same service. No new `InterfaceAgentResultKind` and no new OpenClaw path strings.

### CLI

```text
ai-news-agent history-search [--query TEXT] [--sources CSV] [--topics CSV]
  [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N] [--db-path PATH]

ai-news-agent history-show d<digest_id>:r<rank> [--db-path PATH]
```

`--db-path` matches the digest command (default `./digest.sqlite` in cwd).

Exit codes: `0` for success including zero matches; `2` for validation or not-found reference; `1` for unexpected store/runtime failure.

### Gradio

Intercept in `ChatService` **before** digest detection, structured latest-digest follow-up, and the interface tool router. Same path in live and fake mode. These commands never invoke the tool-calling model.

Command grammar (case-insensitive keywords; extra surrounding whitespace ignored):

```text
search history[ for <text>][ from <sources>][ on <topics>][ since YYYY-MM-DD][ until YYYY-MM-DD]
open history d<digest_id>:r<rank>
```

Sources and topics in Gradio are comma-separated canonical names / topic strings. `search history` with no `for` / `from` / `on` / `since` / `until` is a validation error.

Example prompts:

- `search history for RAG agents from huggingface,zhihu since 2026-08-01`
- `open history d12:r3`

### OpenClaw

Out of scope for 7D.1. Existing `/digest` and `/followup` contracts stay unchanged.

## Error Handling

| Case | User-facing behavior |
|------|----------------------|
| Empty archive | “No saved digests to search.” |
| Valid search, zero matches | Report the applied filters and suggest broadening one criterion. |
| Invalid source, date, range, limit, or empty criteria | Actionable validation error. Never fall back to latest-digest follow-up. |
| Unknown or malformed reference | `not found`. No nearest-match. |
| Digest or rank no longer present | `not found`. |
| Candidate cap reached | Return ranked partial results plus a visible truncation caveat. |
| Malformed historical row | Skip the row, append a bounded caveat, continue. |
| Store failure | Short CLI/Gradio error; full detail in existing logs. |

Opening history is read-only. Search does not persist anything.

## Module Boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| History query/scoring module | Validate query, score candidates, format tokens | Domain models |
| `DigestStore` historical reads | SQL filter + bounded candidate load; latest-context reads unchanged | Existing schema |
| History interface module | CLI/Gradio command parse and result chrome | History service |
| `ChatService` intercept | History commands before digest / follow-up / tool router | History interface |
| CLI subcommands | Thin flags → service | History interface, store |

Do not grow `storage.py` with ranking or presentation. Do not add history tools to the latest-digest registry in 7D.1.

## Testing And Acceptance

Implementation is TDD-suitable and must follow strict test-first RED/GREEN cycles.

Automated coverage must include:

- Historical reads return only persisted digest entries, preserve original global display rank, and leave `get_latest_followup_context()` unchanged
- Source, date, and topic filters compose with AND; invalid and empty queries are rejected
- Scoring: exact phrase, title hit, topic hit, term coverage, recency tie-break, Unicode case-fold, Chinese substring, filter-only newest-first order
- Duplicate URLs across digests remain separate rows
- Stable references resolve the exact old item; deleted or mismatched references fail without guessing
- History show for Juya, Hugging Face, Zhihu, GitHub, and Bilibili reuses the correct persisted formatter with no connector/network calls
- Hugging Face history show does not live-fetch a model-card README
- Candidate-cap, malformed-row, empty-archive, and no-match caveats are bounded and deterministic
- CLI search/show output and exit codes
- Gradio sync and streaming, live and fake: explicit history commands never call the tool runner
- Regression: latest-digest structured phrases, open-ended follow-up, digest generation, OpenClaw path taxonomy

No default automated test performs a live external request.

Acceptance:

1. With multiple saved digests, a topic/source/date query returns reproducibly ordered matches with `dN:rN` references.
2. Opening a reference renders that old item while latest-digest follow-up still uses the newest digest.
3. Search and open work offline from CLI and Gradio.
4. No schema migration, embedding model, vector store, or external request is introduced.
5. A 10,000-entry archive is exercised locally; truncation is visible when the candidate cap is hit.
6. Cross-digest synthesis, personalization, conversation history, OpenClaw history, FTS, and vectors remain later slices.

## Deferred Work

- 7A quality evaluation, 7B scheduling, 7C deployment
- OpenClaw `history-search` / `history-show`
- SQLite FTS5 if measured scan latency on a real archive requires it
- Local embeddings / vector recall
- Switching follow-up context to a named historical digest
- Searching unselected collected items
- Trend synthesis across matches
- Persisting `output_language` for historical chrome
