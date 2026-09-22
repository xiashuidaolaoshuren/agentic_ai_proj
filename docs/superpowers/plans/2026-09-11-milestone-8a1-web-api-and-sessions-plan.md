# Implementation Plan: Milestone 8A.1 Web API and Session-Scoped Chat

**Spec:** `docs/superpowers/specs/2026-09-11-milestone-8a1-web-api-and-sessions-design.md`  
**ADR:** `docs/adr/0008-session-scoped-followup-context-and-web-api.md`  
**Created:** 2026-09-22  
**Subsystem scope:** Milestone 8A.1 only — local FastAPI chat API, durable sessions, and session-scoped follow-up context. No Vue, OpenDesign, vectors, auth, or public deployment.

## Summary

Ship a local `/api/v1` FastAPI surface for durable browser conversations, while CLI, Gradio, and OpenClaw keep working. A browser session owns its transcript, source preferences, and latest successful digest. CLI, Gradio, and OpenClaw follow **shared-interface context**: the latest saved run with `session_id IS NULL`. Historical digest search stays archive-wide and lexical.

Deliver the spec in order: **8A.1a** persistence, **8A.1b** session behavior and `DigestView`, **8A.1c** HTTP, SSE, and OpenClaw route parity. Each slice is independently testable.

**Note — OpenDesign:** Do not build the UI ground truth during 8A.1a or 8A.1b. Start OpenDesign only after **T14, T15, T16, and T17** are green, so the design follows the proven `/api/v1` OpenAPI contract (`DigestView`, SSE, cursor pages, request status, history, and OpenClaw routes). **T17** alone is not that gate: it can finish before the browser routes. **T18** does not change the API and does not block OpenDesign. Milestone **8B** (Vue) starts only after that OpenDesign ground truth, and it consumes the contract rather than changing it.

Out of scope: 8A.2 embeddings and memory RAG, 8B Vue/Vite/Tailwind/shadcn-vue, Gradio removal, accounts, PostgreSQL, public fake backends, new connectors, ranking or rendering-rule changes, and OpenClaw history endpoints.

## Multi-subsystem gate

One web-API subsystem. Persistence, session behavior, and HTTP are sequenced parts of the same contract: the API cannot be proven without the request lifecycle, and the request lifecycle cannot be proven without schema v2. 8A.2 and 8B are separate specs. Use one type-1 plan.

## Discovery notes

- Reuse: `ChatService` already routes digest, structured follow-up, tool agent, and history. Gradio consumes `handle_message_streaming_async`, which flattens progress and text into `AsyncIterator[str]`. Add a typed event stream beside it; keep the string adapter for Gradio.
- Reuse: `DigestStore` (`SCHEMA_VERSION == "1"`), `FollowupContext`, historical reads, and `save_run` / `save_connector_result` / `save_ranked_items` / `save_digest`. `init_schema()` currently rejects any version other than `"1"`.
- Reuse: `get_latest_followup_context()` is “newest digest row, else newest run,” with no session filter (`storage.py` `_latest_digest_row`). Shared-interface context is a query change on that method, not a new CLI concept.
- Reuse: `resolve_digest_request` already prefers explicit message selectors over session connector names. Web sessions must keep that precedence and must not persist the one-shot override.
- Reuse: `format_rank_item` and existing renderers stay the Markdown authority. `Digest` / `DigestEntry` do not carry display rank or Hugging Face family stats; `DigestView` is a new API DTO assembled from the digest plus selected `NewsItem` evidence.
- Reuse: `app/digest_service.py` `/health`, `/digest`, and `/followup` response fields, plus `tests/test_digest_service_parity.py` and `tests/test_digest_service.py`. FastAPI replaces the `http.server` implementation only after those contracts pass.
- Reuse: `DigestStageTimer`, `new_correlation_id`, connector warning formatting, and fake mode (`FakeDigestModel`, fake connectors, no network).
- Constraints: one active Session Request per session; `409 session_busy` for a second request or an active-session delete. Idempotency key is `(session_id, request_id)`. Startup marks leftover `active` requests `interrupted` and does not rerun them.
- Constraints: digest persistence is the cancellation point of no return. The digest bundle (run, items, warnings, rankings, digest, entries, `session_id`, request `run_id`) commits in one SQLite transaction.
- Constraints: browser routes are `/api/v1`. OpenClaw paths stay unversioned. CORS is an explicit loopback allowlist. Pagination is opaque cursors. Session search is lexical, one hit per session, title then user message then assistant message.
- Anti-goals: moving `connectors/`, `graph/` nodes other than the persist seam, `tools/`, `rendering.py`, or `ranking.py`; GraphQL; Django; vectors; auth; deleting Gradio; exposing raw `source_evidence`.



## File map



### Subsystem: Web API and session-scoped chat


| Path                                              | Create/Modify | Responsibility                                                                                         | Public surface                                                                                                                              |
| ------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/ai_news_agent/repositories/digest_store.py`  | create        | Relocated `DigestStore`: schema v2, shared-interface and session follow-up reads, atomic digest bundle | `DigestStore`, `FollowupContext`, `SCHEMA_VERSION`, `save_digest_bundle`, `get_latest_followup_context`, `get_followup_context_for_session` |
| `src/ai_news_agent/repositories/session_store.py` | create        | Session, message, and Session Request SQL only                                                         | session CRUD, ordered messages, request insert/status/terminal update, startup interrupt                                                    |
| `src/ai_news_agent/repositories/unit_of_work.py`  | create        | One SQLite connection and transaction for digest plus session writes                                   | `SqliteUnitOfWork`                                                                                                                          |
| `src/ai_news_agent/storage.py`                    | modify        | Behavior-free re-export of the relocated store                                                         | existing import path                                                                                                                        |
| `src/ai_news_agent/services/session_records.py`   | create        | Session, message, and request records plus title truncation                                            | records and `initial_session_title`                                                                                                         |
| `src/ai_news_agent/services/session_service.py`   | create        | Session use cases: preferences, one active request, delete rules, idempotency, cancel, interrupt       | `SessionService`                                                                                                                            |
| `src/ai_news_agent/services/session_search.py`    | create        | Lexical session search scoring and cursor page                                                         | `search_sessions`                                                                                                                           |
| `src/ai_news_agent/services/digest_views.py`      | create        | Map a saved digest plus selected news evidence to `DigestView`                                         | `build_digest_view`                                                                                                                         |
| `src/ai_news_agent/services/chat.py`              | create        | Relocated `ChatService` plus typed session event stream                                                | `ChatService`, `stream_events`                                                                                                              |
| `src/ai_news_agent/chat.py`                       | modify        | Behavior-free re-export                                                                                | existing import path                                                                                                                        |
| `src/ai_news_agent/services/composition.py`       | create        | Single fake/live composition root for Gradio, CLI service, and FastAPI                                 | `build_application`                                                                                                                         |
| `src/ai_news_agent/api/schemas/digests.py`        | create        | `DigestView` discriminated union                                                                       | Pydantic response models                                                                                                                    |
| `src/ai_news_agent/api/schemas/sessions.py`       | create        | Session, message, request, and page DTOs                                                               | Pydantic models                                                                                                                             |
| `src/ai_news_agent/api/schemas/streaming.py`      | create        | SSE event payloads                                                                                     | Pydantic models                                                                                                                             |
| `src/ai_news_agent/api/schemas/history.py`        | create        | HTTP DTOs over existing history results                                                                | Pydantic models                                                                                                                             |
| `src/ai_news_agent/api/sse.py`                    | create        | Encode typed events as SSE frames                                                                      | `encode_sse`                                                                                                                                |
| `src/ai_news_agent/api/app.py`                    | create        | FastAPI factory, lifespan, loopback CORS, router mount                                                 | `create_app`                                                                                                                                |
| `src/ai_news_agent/api/deps.py`                   | create        | Request-scoped access to the composition root                                                          | FastAPI dependencies                                                                                                                        |
| `src/ai_news_agent/api/routers/meta.py`           | create        | `/api/v1/health` and `/api/v1/sources`                                                                 | routes                                                                                                                                      |
| `src/ai_news_agent/api/routers/sessions.py`       | create        | Session CRUD, transcript pages, message SSE, request status, cancel, search                            | routes                                                                                                                                      |
| `src/ai_news_agent/api/routers/history.py`        | create        | Existing history search and show over HTTP                                                             | routes                                                                                                                                      |
| `src/ai_news_agent/api/routers/openclaw.py`       | create        | Unversioned `/health`, `/digest`, `/followup`                                                          | routes                                                                                                                                      |
| `src/ai_news_agent/app/digest_service.py`         | modify        | `ai-news-agent service` starts the FastAPI app; payload helpers stay                                   | `main`, existing payload builders                                                                                                           |
| `src/ai_news_agent/app/gradio_app.py`             | modify        | Build `ChatService` from the composition root                                                          | Gradio UI unchanged                                                                                                                         |
| `src/ai_news_agent/graph/nodes/persist_render.py` | modify        | Workflow persist uses `save_digest_bundle`                                                             | existing node factory                                                                                                                       |
| `src/ai_news_agent/graph/state.py`                | modify        | Optional `session_id` carried into persist                                                             | `DigestGraphState`                                                                                                                          |
| `pyproject.toml`                                  | modify        | Add FastAPI and Uvicorn                                                                                | runtime dependencies                                                                                                                        |
| `tests/test_layer_imports.py`                     | create        | `repositories` do not import `services` or `api`; `services` do not import `api`                       | pytest                                                                                                                                      |
| `tests/test_schema_migration.py`                  | create        | v1 backup, v2 upgrade, failed migration leaves v1                                                      | pytest                                                                                                                                      |
| `tests/test_session_store.py`                     | create        | Sessions, messages, requests, titles, preferences                                                      | pytest                                                                                                                                      |
| `tests/test_followup_context.py`                  | create        | Shared-interface versus session context, interrupted runs                                              | pytest                                                                                                                                      |
| `tests/test_digest_bundle.py`                     | create        | Atomic bundle and rollback                                                                             | pytest                                                                                                                                      |
| `tests/test_session_service.py`                   | create        | Busy session, delete, idempotency, cancel, interrupt                                                   | pytest                                                                                                                                      |
| `tests/test_session_search.py`                    | create        | Weighted lexical search and cursors                                                                    | pytest                                                                                                                                      |
| `tests/test_digest_views.py`                      | create        | Source-kind views, no raw evidence                                                                     | pytest                                                                                                                                      |
| `tests/test_chat.py`                              | modify        | Typed events and Gradio string adapter                                                                 | pytest                                                                                                                                      |
| `tests/test_api_sessions.py`                      | create        | `/api/v1` session, SSE, pagination, status                                                             | pytest                                                                                                                                      |
| `tests/test_api_history.py`                       | create        | History HTTP preserves 7D.1                                                                            | pytest                                                                                                                                      |
| `tests/test_digest_service_parity.py`             | modify        | Same OpenClaw assertions against FastAPI                                                               | pytest                                                                                                                                      |
| `README.md`                                       | modify        | Local API usage; Gradio remains; no public backend                                                     | docs                                                                                                                                        |




### Blast radius


| Path / boundary                             | Why sensitive                          | Existing behavior to preserve                                                                                              | Plan mode |
| ------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --------- |
| `storage.py` / `DigestStore`                | Every persist and follow-up path       | v1 rows survive; historical search unchanged; `get_latest_followup_context()` ignores browser runs after the filter change | high      |
| `graph/nodes/persist_render.py`             | Digest durability for CLI and OpenClaw | A failed bundle leaves no partial run; row shape stays compatible                                                          | high      |
| `chat.py` / `tools/interface_router.py`     | Gradio sends every message here        | Non-session Gradio, structured follow-up, tool agent, and history intercept stay on shared-interface context               | high      |
| `app/digest_service.py`                     | OpenClaw client and parity tests       | `/health`, `/digest`, `/followup` fields and paths                                                                         | high      |
| `cli.py`                                    | Starts `service`                       | `digest`, `history-*`, and `openclaw-*` commands unchanged                                                                 | medium    |
| `rendering.py`, rank cards, history scoring | Easy to “improve” while mapping views  | Markdown and 7D.1 search behavior unchanged                                                                                | skip      |




## Workflow (for implementers)

1. **writing-plans** produced this file (type-1 decomposition only).
2. For each subtask: **Plan mode** + **planning-subtasks** skill → type-2 plan (`.cursor/plans/*.plan.md`) when **Plan mode** priority warrants it.
3. **Agent mode**: **test-driven-development** when `TDD suitable: yes`. New modules: first GREEN is types and stubs only (`NotImplementedError` / empty defaults). Do not wire FastAPI, Gradio, or the graph in that GREEN.
4. Implement **8A.1a (T1–T6)** before **8A.1b (T7–T12)** before **8A.1c (T13–T18)**.
5. Update this document if reality diverges; add a **Plan changelog** row.



## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 — Repository package and store re-export

- [x] **Do:** Move `DigestStore` to `repositories/digest_store.py` and leave `storage.py` as a behavior-free re-export. Add the import-direction test. No schema or query change.

- **Blocked by:** —
- **Plan mode:** high
- **TDD suitable:** partial
- **TDD suitable reason:** the import-boundary check is testable; the relocation itself is wiring-only and is verified by the existing suite.
- **Verification:** `uv run pytest tests/test_layer_imports.py tests/test_storage.py tests/test_history_store.py -q`



### T2 — Schema v2 migration and backup

- [x] **Do:** Upgrade v1 databases in place to sessions, messages, session requests, and nullable `runs.session_id`. Take one sibling SQLite backup before migrating, commit `schema_version` `"2"` last, and leave the original at v1 if migration fails. Do not back up a database that is already v2.

- **Blocked by:** T1
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_schema_migration.py tests/test_storage.py tests/test_history_store.py -q`



### T3 — Session and message repository

- [ ] **Do:** Persist sessions and ordered messages: deterministic 60-character initial titles, user rename, nullable connector defaults, rejection of an empty connector list, and `items_per_source`. Deleting an inactive session removes its messages and nulls `runs.session_id` without deleting digest rows.

- **Blocked by:** T2
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_store.py -q`



### T4 — Session Request repository

- [ ] **Do:** Persist Session Requests keyed by `(session_id, request_id)` with statuses `active`, `succeeded`, `failed`, `cancelled`, and `interrupted`. Store message and run links, correlation ID, and safe terminal error fields. Startup can mark leftover `active` rows `interrupted`.

- **Blocked by:** T3
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_store.py -q -k "request or interrupt"`



### T5 — Shared-interface and session follow-up reads

- [ ] **Do:** Make `get_latest_followup_context()` return the latest run with `session_id IS NULL`. Add `get_followup_context_for_session()` for the latest digest linked to that session’s `succeeded` request. An `interrupted` request’s digest stays in history and does not become session follow-up context.

- **Blocked by:** T4
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_followup_context.py tests/test_chat.py tests/test_openclaw_followup.py -q`



### T6 — Unit of Work and atomic digest bundle

- [ ] **Do:** Add `SqliteUnitOfWork` and `save_digest_bundle`. One transaction writes the run, items, warnings, rankings, digest, entries, optional `session_id`, and request `run_id`. Point the workflow persist node at that operation. A failure leaves no partial run.

- **Blocked by:** T5
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_digest_bundle.py tests/test_workflow.py tests/test_storage.py -q`



### T7 — Session service preferences and deletion

- [ ] **Do:** Add session records and `SessionService` for create, list, get, rename, preference update, and inactive delete. Generate the initial title once. Apply saved sources only as defaults; an explicit message selector overrides one request and does not change the saved preference.

- **Blocked by:** T6
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_service.py -q -k "title or preference or delete"`



### T8 — One active request, idempotency, and interrupt

- [ ] **Do:** Accept one active request per session. Reject a different in-flight request and active-session deletion with `session_busy`. Reuse of a terminal or interrupted request ID returns the stored outcome and does not create another run. Application startup interrupts leftover active requests without rerunning them.

- **Blocked by:** T7
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_service.py -q -k "busy or idempoten or interrupt"`



### T9 — Cancellation point of no return

- [ ] **Do:** Cancellation before the digest-bundle transaction starts ends the request as `cancelled` with a safe assistant message. Cancellation after that transaction has started leaves the successful terminal result unchanged.

- **Blocked by:** T8
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_service.py -q -k "cancel"`



### T10 — Typed chat events and session routing

- [ ] **Do:** Move `ChatService` to `services/chat.py` with a re-export. Add `stream_events()` yielding started, progress, delta, digest, done, and error. Keep `handle_message_streaming_async` as the Gradio string adapter on shared-interface context. Session chat passes `session_id` into digest persist and reads `get_followup_context_for_session()`.

- **Blocked by:** T9
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_chat.py tests/test_gradio_app.py tests/test_interface_router.py -q`



### T11 — DigestView

- [ ] **Do:** Add source-kind-discriminated `DigestView` DTOs and `build_digest_view`. Every entry has `display_rank` and common digest fields. Hugging Face includes family metrics and variants. Do not expose raw `source_evidence`. Markdown remains the renderer output.

- **Blocked by:** T10
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_digest_views.py tests/test_rendering.py -q`



### T12 — Lexical session search

- [ ] **Do:** Search titles and message text, return one hit per session, and rank title, then user message, then assistant message, then recent activity. Include a bounded excerpt and matching message ID. Cursor pagination lives with the result. No embeddings.

- **Blocked by:** T7
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_session_search.py -q`



### T13 — FastAPI application shell

- [ ] **Do:** Add FastAPI and Uvicorn. Create the app factory, loopback CORS allowlist, `/api/v1/health`, and `/api/v1/sources`. No wildcard origins. Composition root supplies fake and live modes.

- **Blocked by:** T6
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_api_sessions.py -q -k "health or sources or cors"`



### T14 — Session HTTP and SSE

- [ ] **Do:** Expose session CRUD, cursor-paginated transcripts, and `POST /api/v1/sessions/{id}/messages` as SSE. Map `session_busy` and validation to the spec status codes. A dropped client still persists the terminal assistant message. Transcript pages include `DigestView` for digest-linked messages.

- **Blocked by:** T11, T13
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_api_sessions.py -q -k "session or sse or page"`



### T15 — Request status, cancel, and search HTTP

- [ ] **Do:** Add request-status GET, cancel POST, and cursor-paginated `GET /api/v1/sessions/search`. Status supports reconnect without reattaching to a byte stream. Cancel returns 202 only before persistence and 204 afterward.

- **Blocked by:** T12, T14
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_api_sessions.py -q -k "status or cancel or search"`



### T16 — History HTTP

- [ ] **Do:** Adapt existing history search and show to `/api/v1/history`. Preserve 7D.1 validation, empty-result success, persist-only show, and `dN:rN` tokens. Do not add OpenClaw history routes.

- **Blocked by:** T13
- **Plan mode:** medium
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_api_history.py tests/test_history_search.py tests/test_history_show.py -q`



### T17 — OpenClaw-compatible FastAPI service

- [ ] **Do:** Serve `/health`, `/digest`, and `/followup` from FastAPI with the current response fields. `ai-news-agent service` starts that app through the composition root. Remove the hand-written `http.server` handler only after parity passes. Gradio uses the same composition root.

- **Blocked by:** T10, T13
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_digest_service.py tests/test_digest_service_parity.py tests/test_openclaw_client.py tests/test_gradio_app.py -q`



### T18 — Operator docs and full regression

- [ ] **Do:** Document local `/api/v1` startup, fake mode, SSE, and the unchanged Gradio and OpenClaw commands. State that 8A.1 is local-only. Run the default suite.

- **Blocked by:** T15, T16, T17
- **Plan mode:** skip
- **TDD suitable:** no
- **TDD suitable reason:** user-facing documentation has no new runtime behavior; the suite is the verification.
- **Verification:** `uv run pytest -q`



## TDD note (Agent mode)

Per subtask, obey `TDD suitable`. `yes` means strict **test-driven-development**. `partial` applies it only to the testable slice. `no` means do not force test-first; still satisfy **Verification**. New-module first GREEN is types and stubs only.

## Plan changelog


| Date       | Change                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 2026-09-22 | Initial plan from the reviewed 8A.1 spec and ADR-0008.                                                                        |
| 2026-09-22 | Note: OpenDesign starts after T14–T17, not during 8A.1a/8A.1b; T18 does not block it; 8B follows the OpenDesign ground truth. |


