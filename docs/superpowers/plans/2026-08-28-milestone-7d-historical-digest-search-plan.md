# Implementation Plan: Milestone 7D.1 Historical Digest Search

**Spec:** `docs/superpowers/specs/2026-08-28-milestone-7d-historical-digest-search-design.md`  
**Parent spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**ADR:** `docs/adr/0007-historical-digest-search-without-vectors.md`  
**Created:** 2026-08-29  
**Subsystem scope:** Milestone 7D.1 only — local lexical **historical digest search** and persist-only **history show** by `dN:rN`. No FTS, vectors, OpenClaw history, schema migration, or 7A–7C.

## Summary

Ship deterministic recall of **saved digest entries** (not unselected `NewsItem` rows) through a shared search service, CLI `history-search` / `history-show`, and Gradio intercepts (`search history …`, `open history d12:r3`). Opening a hit formats that run’s rank card and must not change latest-digest follow-up context or live-enrich Hugging Face / Bilibili.

Out of scope: 7A quality evaluation, 7B scheduling, 7C deployment, 7D.2+ trend synthesis / personalization / conversation memory / FTS / vectors, OpenClaw history commands, new registry tools, `InterfaceAgentResultKind` values, OpenClaw `/followup` path strings.

## Multi-subsystem gate

One history-search subsystem. Candidate load, scoring, show, CLI, and Gradio intercept are sequenced parts of the same seam (search without show, or CLI without Gradio, would leave the spec half-shipped). 7A / 7B / 7C / 7D.2+ are separate specs. Use one type-1 plan.

## Discovery notes

- Reuse: existing `runs` / `digests` / `digest_entries` / `news_items` schema (`SCHEMA_VERSION` stays `"1"`). `DigestStore._digest_from_row`, `_load_news_items`, `_load_warnings` already rebuild a `FollowupContext` for **one** run — history show should load **that digest’s run**, not invent a second matcher.
- Reuse: `format_rank_item` in `followup_structured.py` is persist-only (Juya / HF family card / Zhihu insight card / generic). History show must call this, **not** `answer_structured_followup_live` / `enrich_huggingface_for_rank` (those upsert and then `get_latest_followup_context()`, which would mix latest context and Hub I/O).
- Reuse: `match_news_item_for_digest_entry` in `juya_followup.py` for pairing entry ↔ `NewsItem` on the show path.
- Reuse: `ALLOWED_SOURCES` / `parse_sources_csv` for source-name validation. Do **not** call `normalize_source_names` on an empty optional filter (it requires at least one source).
- Reuse: CLI `--db-path` default (`./digest.sqlite` in cwd) and exit-code style (`0` success, `2` validation, `1` unexpected).
- Reuse: `ChatService` already has `store`; intercept must run **before** `interface_router` in both `handle_message_async` and `handle_message_streaming_async` (live Gradio otherwise never sees history commands).
- Constraints: search rows are `digest_entries` only. Display rank = 1-based index in that digest’s `digest_entries` `id` order. Duplicate URLs across digests stay separate rows. Token `d<digest_id>:r<rank>`.
- Constraints: topic AND-match is case-folded equality against **digest** `topics_json`, not entry `topic_matches`. Unicode NFC + case-fold for text; SQLite `lower()` is not a substitute — apply topic + lexical filters in the history service after SQL source/date bounding.
- Constraints: candidate cap **10,000** (injectable in tests; do not insert 10k rows in CI). Truncation caveat when more filter-matching rows exist.
- Constraints: Gradio grammar is explicit (`search history` / `open history`); do not overload `intent.py` digest parsing. Fake and live modes share the intercept (no LLM / fake tool agent).
- Anti-goals: FTS5 / embeddings / new tables / schema bump; history tools in `tools/registry.py`; OpenClaw history; switching latest context; live enrich on show; ranking or result chrome inside `storage.py`; drive-by ChatService / CLI refactors.

## File map

### Subsystem: Historical digest search

| Path | Create/Modify | Single responsibility | Public surface |
|------|---------------|----------------------|----------------|
| `src/ai_news_agent/history.py` | create | History types, `dN:rN` token parse/format, query validation, lexical score / excerpt / total order (no SQLite) | `HistorySearchQuery`, `HistoricalItemRef`, `HistorySearchMatch`, `HistorySearchResult`, `HISTORY_CANDIDATE_CAP`, `parse_historical_item_ref`, `format_historical_item_ref`, `validate_history_search_query`, `score_historical_candidate` |
| `src/ai_news_agent/history_search.py` | create | Orchestrate store load + topic/lexical filter + cap caveat + persist-only show | `search_digest_history`, `show_historical_item` |
| `src/ai_news_agent/history_interface.py` | create | Gradio command grammar and user-facing search/show chrome (not scoring) | `parse_history_chat_message`, `format_history_search_text`, history validation/not-found strings |
| `src/ai_news_agent/storage.py` | modify | SQL source + date filter, newest-first bounded candidate rows, load `FollowupContext` for a digest id; **no** scoring | `list_historical_digest_entries`, `get_followup_context_for_digest`; `get_latest_followup_context` unchanged |
| `src/ai_news_agent/followup_structured.py` | unmodified expected | Persist-only `format_rank_item` reused by show | existing exports |
| `src/ai_news_agent/cli.py` | modify | `history-search` / `history-show` subcommands, thin dispatch | new parsers + handlers; `digest` / OpenClaw commands unchanged |
| `src/ai_news_agent/chat.py` | modify | Intercept history commands before digest routing and before `interface_router` (sync + streaming) | `ChatService` message handlers |
| `src/ai_news_agent/app/gradio_app.py` | modify | Example prompt rows for search/open history | `_EXAMPLE_ROWS` |
| `tests/test_history.py` | create | Tokens, query validation, NFC/case-fold, scoring order, Chinese substring, excerpts | pytest |
| `tests/test_history_store.py` | create | Historical SQL reads, display rank, entries-only, latest context unchanged, cap/truncation flag | pytest |
| `tests/test_history_search.py` | create | Service AND filters, duplicates, empty archive, no-match, malformed skip, injectable cap | pytest |
| `tests/test_history_show.py` | create | Show by ref for Juya/HF/Zhihu/GitHub/Bilibili; no connector calls; latest unchanged; not-found | pytest |
| `tests/test_history_interface.py` | create | Gradio grammar, chrome, validation errors do not look like latest-digest follow-up | pytest |
| `tests/test_cli.py` | modify | `history-search` / `history-show` argv, stdout, exit codes `0`/`2`/`1` | pytest |
| `tests/test_chat.py` | modify | Intercept before fake router (sync + streaming); non-history messages still route | pytest |
| `tests/test_gradio_app.py` | modify | Example-row count and history prompts | pytest |
| `tests/test_openclaw_followup.py` | unmodified expected | Path taxonomy unchanged | existing |
| `README.md` | modify | CLI + Gradio history usage; OpenClaw still has no history | user-facing docs |

### Blast radius

| Path / boundary | Why sensitive | Existing behavior to preserve | Plan mode |
|-----------------|---------------|-------------------------------|-----------|
| `storage.py` | Latest digest + persist path for every interface | `SCHEMA_VERSION` `"1"`; `get_latest_followup_context()` still latest-only; no new tables; no ranking in this module | high |
| `chat.py` | Live Gradio sends **all** messages through `interface_router` today | Digest, structured latest follow-up, open-ended tool agent, and no-saved-digest paths unchanged when the message is not a history command | high |
| `cli.py` | Global entrypoint | `digest` / `service` / `openclaw-*` parse and exit codes unchanged | medium |
| `followup_structured.py` / enrich | Easy to “reuse” live rank follow-up for show | History show never calls `enrich_huggingface_for_rank` or upserts | skip unless a test proves drift |
| `tools/registry.py`, OpenClaw adapters | Easy to add a history tool or `/followup` path | No new tools; `no_digest` / `structured` / `guidance` only | skip |
| README / Gradio examples | Operators copy prompts | Do not document OpenClaw history or live enrich on open | skip |

## Workflow (for implementers)

1. **writing-plans** produced this file (type-1 decomposition only).
2. For each subtask: **Plan mode** + **planning-subtasks** skill → type-2 plan (`.cursor/plans/*.plan.md`) when **Plan mode** priority warrants it.
3. **Agent mode**: **test-driven-development** when `TDD suitable: yes`. New modules: first GREEN is types + stubs only (`NotImplementedError` / empty defaults), no ChatService/CLI wiring in that GREEN.
4. Update this document if reality diverges; add a **Plan changelog** row.

## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 — History types, tokens, and query validation

- [ ] **Do:** Add `history.py` with `HistorySearchQuery`, `HistoricalItemRef`, match/result types, `d<digest_id>:r<rank>` parse/format, and validation (at least one criterion; blank text absent; sources in `ALLOWED_SOURCES`; `since` ≤ `until`; limit 1–50 default 10). First GREEN is types + stubs only.

- **Blocked by:** —
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history.py -q -k "ref or validat or query"`

### T2 — Lexical scoring and excerpts

- [ ] **Do:** Implement NFC/case-fold scoring and excerpt extraction on in-memory candidates: space-delimited all-terms (term may hit searchable text **or** digest topics), unsegmented/Chinese substring, filter-only skip lexical match, total order (phrase-in-title, phrase-in-text, title terms, topic equality, term coverage, recency, `digest_id` desc, rank asc). No SQLite in this module.

- **Blocked by:** T1
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history.py -q`

### T3 — DigestStore historical reads

- [ ] **Do:** Add `list_historical_digest_entries` (source + `generated_at` UTC date range, newest-first, cap+1 to detect truncation, digest topics and entry fields, original display rank from per-digest `id` order) and `get_followup_context_for_digest`. Prove unselected `news_items` are not listed, `get_latest_followup_context()` is unchanged, schema version stays `"1"`. No scoring in `storage.py`.

- **Blocked by:** T1
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history_store.py tests/test_storage.py -q`

### T4 — History search service

- [ ] **Do:** Add `search_digest_history` that loads bounded rows, applies topic AND-match and lexical scoring, returns matches with tokens, scanned count, archive-truncated flag, and caveats (empty archive, no matches with filters named, malformed rows skipped, cap hit). Same URL in two digests → two rows. Default cap `HISTORY_CANDIDATE_CAP = 10_000`; tests inject a small cap.

- **Blocked by:** T2, T3
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history_search.py tests/test_history.py tests/test_history_store.py -q`

### T5 — Persist-only history show

- [ ] **Do:** Add `show_historical_item` that parses/resolves `dN:rN`, loads that digest’s `FollowupContext` (entries + that run’s `NewsItem`s), and returns `format_rank_item` text. Missing/malformed ref → not-found, no nearest guess. Prove Juya / Hugging Face / Zhihu / GitHub / Bilibili cards, degraded missing `NewsItem`, **no** connector/HTTP, **no** store writes, latest context still the newest digest.

- **Blocked by:** T3
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history_show.py tests/test_huggingface_followup.py tests/test_zhihu_followup.py tests/test_juya_followup.py tests/test_rank_deep_dive.py -q`

### T6 — Gradio/CLI history chrome and grammar

- [ ] **Do:** Add `history_interface.py` to parse `search history[ for …][ from …][ on …][ since …][ until …]` and `open history dN:rN` (case-insensitive keywords), and to render search result chrome (token, date, source, title, URL, excerpt, caveats). Bare `search history` is a validation error. Do not fall through to latest-digest phrasing.

- **Blocked by:** T1
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_history_interface.py -q`

### T7 — CLI `history-search` and `history-show`

- [ ] **Do:** Wire thin subcommands to the search/show service: flags per spec, `--db-path` like digest, exit `0` on success including zero matches, `2` on validation or not-found ref, `1` on unexpected store failure. Do not add OpenClaw commands.

- **Blocked by:** T4, T5, T6
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_cli.py -q`

### T8 — ChatService history intercept

- [ ] **Do:** Handle parsed history commands in `ChatService` **before** digest detection and **before** `interface_router` (sync + streaming). Live and fake: never call the tool runner / fake tool agent. Non-history messages keep current routing. Prove a fake router is not invoked for `search history` / `open history`.

- **Blocked by:** T4, T5, T6
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_chat.py tests/test_history_interface.py tests/test_history_search.py tests/test_history_show.py -q`

### T9 — README and Gradio example prompts

- [ ] **Do:** Document CLI and Gradio history usage in `README.md` (offline, persist-only open, latest-digest unchanged, OpenClaw out of scope). Add Gradio example rows for search/open; update `tests/test_gradio_app.py` example count/mappings.

- **Blocked by:** T7, T8
- **Plan mode:** skip
- **TDD suitable:** partial
- **TDD suitable reason:** Gradio `_EXAMPLE_ROWS` contracts are assertable; README prose is static docs with no runtime behavior.
- **Verification:** `uv run pytest tests/test_gradio_app.py -q`; review README for `history-search` / `open history` and no OpenClaw history or live-enrich-on-open instructions

### T10 — Milestone-level regression

- [ ] **Do:** Run the full automated suite. Confirm OpenClaw `path` remains `no_digest` / `structured` / `guidance`, latest-digest structured wording tests still pass, no schema migration, no new registry tools. Update this plan’s changelog if verification exposes a missing file or extra subtask.

- **Blocked by:** T1, T2, T3, T4, T5, T6, T7, T8, T9
- **Plan mode:** medium
- **TDD suitable:** no
- **TDD suitable reason:** verification-only integration pass; production behavior was already driven test-first in T1–T8.
- **Verification:** `uv run pytest -q`; confirm `test_public_format_helpers_preserve_wording` still exact-matches; OpenClaw follow-up paths unchanged; `SCHEMA_VERSION == "1"`

## TDD note (Agent mode)

Per subtask, obey `TDD suitable`: `yes` means strict **test-driven-development** (red/green/refactor); `partial` applies it only to the testable slice; `no` means do not force test-first—still satisfy **Verification**. New modules start GREEN with types and stubs only. Type-2 planning → **planning-subtasks** skill.

## Plan changelog

| Date | Change |
|------|--------|
| 2026-08-29 | Created from the accepted Milestone 7D.1 spec and ADR-0007. |
