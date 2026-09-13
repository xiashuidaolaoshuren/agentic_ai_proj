# Milestone 8A.1: Web API and Session-Scoped Chat

Date: 2026-09-11
Status: approved design

## Summary

Milestone 8 turns the local Gradio interface into a full-stack web application in staged backend and frontend work:

- **8A.1a:** establish the durable SQLite foundation: session and request lifecycle, safe migration, shared-interface context, and atomic digest persistence.
- **8A.1b:** add session chat behavior: isolation, cancellation/crash rules, typed stream events, and rich digest views.
- **8A.1c:** expose the stable FastAPI REST/SSE API, preserve OpenClaw HTTP compatibility, and prove the generated-client contract.
- **8A.2 (later):** add optional semantic session search and long-term memory behind the 8A.1 API contract.
- **8B (later):** build the Vue 3 + Vite + Tailwind CSS + shadcn-vue web interface from the stable 8A.1 contract. OpenDesign is used to create the UI design after 8A.1 is complete.

The project remains local-first and single-user in 8A.1. A user may have multiple browser conversations at once, but one conversation runs only one request at a time. Each conversation owns its transcript and follow-up context. 8A.1 is local-only: public demonstration isolation, quotas, and rate limiting are deferred rather than treating fake mode or CORS as access control.

This design supersedes the hand-written HTTP implementation in `app/digest_service.py` as the web-service implementation, while retaining its `/health`, `/digest`, and `/followup` contracts for OpenClaw.

## Goals

- Expose the agent through a documented FastAPI REST API with streamed chat responses.
- Add durable chat sessions and messages, so concurrent browser conversations do not overwrite one another's follow-up context.
- Make request retries, terminal replay, cancellation, and crash recovery durable and deterministic.
- Keep existing CLI, Gradio, and OpenClaw behavior working during the transition.
- Return both existing server-rendered markdown and structured digest data, allowing the future Vue UI to render rich components without duplicating the authoritative text renderer.
- Provide a bounded, typed API view of source-specific digest evidence rather than exposing connector internals.
- Establish visible, enforceable presentation, application, and data-access boundaries without moving unrelated mature modules.
- Preserve local, deterministic fake-mode tests and demos.
- Freeze a paginated session-search endpoint contract now, while leaving its initial implementation lexical and SQLite-backed.

## Non-Goals

- Vue, Vite, Tailwind, shadcn-vue, or OpenDesign-generated production UI work (Milestone 8B).
- Removing Gradio before the Vue interface has shipped.
- User accounts, authorization, multi-tenancy, or public live-backend access.
- Any public shared fake backend; fake mode protects provider credentials but does not isolate browser data.
- PostgreSQL, managed cloud databases, or a deployment platform selection.
- Vector storage, embedding generation, semantic ranking, long-term-memory RAG, or changing historical digest search.
- New source connectors, ranking changes, changes to digest rendering rules, or OpenClaw history endpoints.
- A full repository-wide physical relocation of all existing modules.
- Replacing the CLI or OpenClaw adapter.

## Decisions

| Concern | Decision |
|---|---|
| Backend framework | FastAPI |
| Architecture | `api` → `services` → `repositories`, with one-way imports |
| Chat transport | REST request plus SSE response; cancellation is a separate REST endpoint |
| Digest payload | Structured JSON and authoritative rendered markdown together |
| Session ownership | A session owns its messages, source settings, request lifecycle, and latest digest context |
| Existing shared context | CLI, Gradio, and OpenClaw use only the latest non-session run; browser runs never alter it |
| Persistence | SQLite remains the system of record |
| Atomicity | A SQLite Unit of Work persists a complete digest bundle and its session-request association atomically |
| API versioning | Browser API is `/api/v1`; OpenClaw compatibility paths remain unversioned |
| Public demo | 8A.1 is local-only; public visitor isolation and abuse controls are a later deployment decision |
| Semantic memory | Deferred to 8A.2 behind the API contract |

ADR-0008 records the FastAPI and session-context decisions. Existing historical digest search remains governed by ADR-0007: it searches saved digest entries lexically and is not conversation memory.

## Architecture

### Layer boundaries

The new API-related modules use this direction:

```text
api  →  services  →  repositories
```

`api` translates HTTP, SSE, and Pydantic API contracts into service calls. It contains no SQL, connector construction, graph execution, or rendering rules.

`services` implements application use cases: session and request lifecycle, chat routing, streaming event translation, and cancellation coordination. It depends on repository interfaces and existing domain/workflow modules, but not on FastAPI request or response objects.

`repositories` owns SQLite schema migration and queries. A connection-scoped SQLite Unit of Work creates focused repositories bound to one transaction for cross-repository writes. Repositories return domain data or repository records and contain no routing, Markdown rendering, SSE encoding, or lexical/semantic scoring policy.

Existing `connectors/`, `graph/`, `tools/`, `models.py`, `rendering.py`, `ranking.py`, and follow-up formatters remain where they are. The package relocation is intentionally limited to the API-facing units; imports and module documentation identify their conceptual layer. An import-boundary test or linter rule enforces that `repositories` never imports `services` or `api`, and `services` never imports `api`.

### New and moved modules

```text
src/ai_news_agent/
  api/
    app.py                 # FastAPI application factory, lifespan, CORS
    deps.py                # dependencies backed by the composition root
    sse.py                 # SSE event encoding only
    schemas/
      digests.py           # DigestView and source-kind-discriminated entry views
      sessions.py          # session and message request/response DTOs
      streaming.py         # event envelope DTOs
      history.py           # HTTP DTOs for existing history service
    routers/
      meta.py              # API health and canonical source metadata
      sessions.py          # session lifecycle, transcript, stream, cancel
      history.py           # existing history search and show
      openclaw.py          # compatibility routes for existing service users
  services/
    composition.py         # single application composition root
    chat.py                # relocated ChatService and event-stream seam
    session_service.py     # session and message use cases
  repositories/
    digest_store.py        # relocated DigestStore
    session_store.py       # session/message SQLite queries
    unit_of_work.py        # one SQLite connection and transaction scope
```

Compatibility re-export modules may remain temporarily at the old `chat.py` and `storage.py` import paths if they keep CLI, Gradio, tools, and tests stable while callers migrate. They must contain no behavior.

### Single composition root

`services/composition.py` is the only place that constructs the Unit of Work factory, digest and session repositories, LLMs, connector factories, workflow runner, interface tool router, and chat service. It accepts `fake` and `db_path` configuration.

Gradio, CLI/service startup, and FastAPI all obtain services from this composition root. This removes the currently duplicated construction in Gradio and the warm digest service and prevents a third divergent FastAPI implementation.

### Why FastAPI

The existing workflow and streaming code are asynchronous, and domain/tool schemas already use Pydantic v2. FastAPI exposes these naturally and produces an OpenAPI document from which 8B can generate a typed TypeScript client. Django's ORM, admin, template system, and built-in authentication are not needed in 8A.1; Django plus DRF or Django Ninja would add adaptation around the async stream without solving a current problem.

## Session and Message Model

### Ownership rules

A **session** is a durable conversation thread. It owns:

- ordered user and assistant messages;
- session-sticky connector selections and `items_per_source`;
- durable session-request lifecycle records;
- the session's latest digest run, derived from the latest successful request associated with that session.

One session has at most one active request. A second submission, and deletion of that session, return `409 session_busy`. Separate sessions may run concurrently.

Digest runs remain global persisted records. Historical digest search continues to search the whole saved digest archive, not only one session.

The **shared-interface context** is the latest saved run whose `session_id` is `NULL`. CLI, Gradio, and OpenClaw use it. Browser sessions use `get_followup_context_for_session(session_id)`, which selects only that session's latest digest linked to a `succeeded` Session Request. A digest bundle committed before a crash remains in archive history but cannot become session follow-up context when its request is later marked `interrupted`. Browser runs never alter shared-interface context. Within a session, structured follow-ups always inspect its latest digest; an older digest must be opened by its stable `dN:rN` historical reference and does not switch active context.

### Schema changes

SQLite remains authoritative in 8A.1:

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY NOT NULL,
  title TEXT,
  connector_names TEXT,
  items_per_source INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE session_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  UNIQUE (session_id, sequence)
);

CREATE TABLE session_requests (
  id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (
    status IN ('active', 'succeeded', 'failed', 'cancelled', 'interrupted')
  ),
  user_message_id INTEGER NOT NULL REFERENCES session_messages(id) ON DELETE RESTRICT,
  assistant_message_id INTEGER REFERENCES session_messages(id) ON DELETE RESTRICT,
  run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
  correlation_id TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  PRIMARY KEY (session_id, id)
);

ALTER TABLE runs ADD COLUMN session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL;
CREATE INDEX idx_runs_session_id_id ON runs(session_id, id DESC);
CREATE INDEX idx_session_messages_session_sequence
  ON session_messages(session_id, sequence);
CREATE INDEX idx_session_requests_session_started
  ON session_requests(session_id, started_at DESC);
```

Session and request identifiers are UUIDs. A session title is nullable at creation and is generated once from the first nonblank user-message line by whitespace normalization and 60-Unicode-character truncation; it is never regenerated and remains user-editable. Empty sessions display `New conversation`.

`connector_names` is the canonical source-name JSON array or `NULL`; `NULL` preserves existing default source resolution. A persisted empty source list is invalid. `items_per_source` is `NULL` until the user chooses a session preference. Session preferences are defaults: explicit natural-language source selection or platform-targeted URLs override them for one request without mutating the stored preferences.

Existing databases are upgraded in place. Before a v1-to-v2 migration, the application creates one sibling SQLite backup with SQLite's backup API. Migration runs in one transaction and increments `SCHEMA_VERSION` from `"1"` to `"2"` only as the last transaction operation. A failed migration rolls back the original database and retains the backup; normal v2 startup creates no backup. The migration is idempotent and preserves all v1 rows. Preexisting runs have `session_id = NULL` and remain reachable through shared-interface context and history behavior.

### Transaction model

The application creates the user message and an `active` session request before work begins. `SessionRequest.id` is the durable idempotency key scoped to its session.

Digest persistence is the cancellation point of no return. One Unit of Work transaction writes the run (including `session_id`), collected items, connector warnings, ranked items, digest, digest entries, and `SessionRequest.run_id`. It either commits the complete bundle or rolls it back. Once that transaction starts, a later cancellation request has no effect on the terminal result.

Rendering and final assistant-message persistence happen after the complete digest bundle exists. The terminal update records the assistant message, terminal request status, and safe error fields in one Unit of Work transaction. If the process stops while a request is `active`, application startup changes it to `interrupted`. Reusing that request ID returns its stable interruption outcome and never reruns provider work automatically; a user must send a new request ID.

### Message durability

The service persists the user message before beginning work. It collects streamed assistant text server-side and persists the final assistant message with its associated run ID when terminal processing completes. Persistence continues if the HTTP/SSE client disconnects; reconnecting clients can load the completed transcript. A failed or cancelled run persists a safe terminal assistant message when there is user-facing output, but it never stores raw exception detail.

Cancellation is cooperative only before the digest-persistence transaction begins. A winning cancellation marks the request `cancelled` and produces a safe terminal assistant message. Once persistence has begun, completion wins and cancellation responds without changing the request outcome.

The initial release does not resume a partially consumed SSE byte stream. A client that reconnects checks durable request status and loads persisted messages, then replays a terminal outcome when available. This avoids claiming resumability that a `fetch`-based POST SSE client cannot provide.

## API Contract

The FastAPI application serves the browser API under `/api/v1` and unversioned OpenClaw compatibility routes. It produces OpenAPI at the normal FastAPI OpenAPI endpoint; 8B treats that document as the client-contract source. Additive fields are compatible within v1; incompatible changes require a new path version.

### Browser API

| Method and path | Purpose |
|---|---|
| `GET /api/v1/health` | Web API health and mode (`fake`) |
| `GET /api/v1/sources` | Canonical sources, defaults, and opt-in metadata |
| `POST /api/v1/sessions` | Create a session |
| `GET /api/v1/sessions` | List sessions, newest activity first, with cursor pagination |
| `GET /api/v1/sessions/{session_id}` | Get session metadata |
| `PATCH /api/v1/sessions/{session_id}` | Rename a session or update sticky source preferences |
| `DELETE /api/v1/sessions/{session_id}` | Delete an inactive session and its transcript; unlink, but do not delete, global digest runs |
| `GET /api/v1/sessions/{session_id}/messages` | Return cursor-paginated durable transcript, including persisted digest views for digest-linked assistant messages |
| `POST /api/v1/sessions/{session_id}/messages` | Persist user input and return an SSE response when no request is active |
| `GET /api/v1/sessions/{session_id}/requests/{request_id}` | Return durable request status and terminal references |
| `POST /api/v1/sessions/{session_id}/requests/{request_id}/cancel` | Ask the active request to cancel |
| `GET /api/v1/sessions/search?q=` | Cursor-paginated session search; lexical in 8A.1, semantic in 8A.2 |
| `GET /api/v1/history/search` | Existing historical digest search, using its established filters |
| `GET /api/v1/history/{historical_item_ref}` | Existing read-only historical item open |

`POST /api/v1/sessions/{session_id}/messages` accepts:

```json
{
  "content": "Give me today's AI digest",
  "client_request_id": "optional-uuid"
}
```

The server creates a request UUID when `client_request_id` is absent. Reusing the same ID for the same session is idempotent: it must not create a duplicate user message or rerun terminal work. A duplicate active request returns `409 request_in_progress`; a duplicate terminal request returns its stored outcome as a normal SSE replay (`started`, persisted `delta` text, optional `digest`, then terminal `done` or `error`). A different request ID while a session has active work returns `409 session_busy`.

`GET /api/v1/sessions/{session_id}/requests/{request_id}` returns the durable request status, the user and assistant message IDs when present, run ID when present, and safe terminal error fields. After an SSE disconnect, a client polls this resource and then reloads messages or requests the terminal replay; it never reattaches to a prior byte stream.

### SSE event contract

The messages endpoint responds with `Content-Type: text/event-stream`. Events are JSON payloads and appear in this order:

| Event | Payload | Meaning |
|---|---|---|
| `started` | `request_id`, `user_message_id` | The user message is durable and the request can now be cancelled |
| `progress` | `stage` | Ephemeral workflow or tool progress |
| `delta` | `text` | Incremental rendered Markdown |
| `digest` | `run_id`, `digest`, `markdown`, `warnings`, `errors` | Final structured digest data; emitted only for a digest result |
| `done` | `request_id`, `message_id`, `run_id`, `path` | Terminal success and durable assistant-message reference |
| `error` | `request_id`, `code`, `message`, `correlation_id` | Terminal failure after stream start |

`markdown` is the existing renderer's authoritative output. `digest` is an API-specific `DigestView`, not the internal `Digest` domain model. Its entries are a bounded Pydantic discriminated union on `source_kind`: every entry has `display_rank` and common digest fields, while each source-kind view exposes only the evidence required for rich presentation. For example, the Hugging Face view contains model-family metrics and variants; no raw `NewsItem.source_evidence` crosses the API boundary. `GET /api/v1/sessions/{session_id}/messages` includes the same digest view for an assistant message linked to a digest run, so a refreshed UI retains rich rendering. Vue may render rich digest components from `digest` but must fall back to `markdown` for tool-agent, structured-follow-up, history, and guidance responses.

The browser consumes the POST stream with `fetch` and a `ReadableStream` reader; native `EventSource` only supports GET and is not applicable to this request shape.

Cancellation is cooperative. Before digest persistence begins, the service records cancellation and stops at a safe await boundary; a winning cancellation emits terminal `error` with stable `cancelled` code rather than pretending a partial digest succeeded. After persistence has started, completion wins. The cancel endpoint returns `202 Accepted` only when a cancellation can still win and `204 No Content` for terminal, unknown, or post-persistence requests.

### Cursor pagination

Session lists use an opaque cursor derived from `(updated_at, id)` in descending order. Transcript pages retrieve newest messages first using `sequence`, then return each page in chronological display order. Session search returns at most one match per session and uses a bounded `limit` plus opaque continuation cursor. Search ranks title matches first, then user-message matches, then assistant-message matches, with most-recent session activity as the tie-breaker. Each match contains a bounded excerpt and its matching message ID.

### OpenClaw compatibility API

The following paths and successful response fields preserve the current local-service contract:

```text
GET  /health
POST /digest
POST /followup
```

`/digest` retains `text`, `run_id`, `correlation_id`, `elapsed_s`, and `stages`; `/followup` retains `text`, `run_id`, `path`, and `correlation_id`. The compatibility router delegates to the same composition root as the browser API. The CLI `ai-news-agent service` starts the FastAPI-compatible service rather than a second HTTP server.

## Data Flow

### Session chat

1. The client creates or selects a session and loads its newest transcript page.
2. It posts a message to an inactive session with a client request UUID.
3. The session service validates the request, persists the user message and `active` Session Request, then emits `started`.
4. Chat routing applies session preferences only as defaults and uses `get_followup_context_for_session()`. A digest run is written with the current `session_id`; structured follow-up selects that session's latest successful digest.
5. The service translates typed chat events into `progress` and `delta` SSE events. The existing Gradio string-stream adapter preserves its current behavior over the same event seam and retains shared-interface context.
6. The Unit of Work commits a complete digest bundle before rendering terminal success. It then persists the assistant message and terminal request record, emits `digest` when relevant, and emits `done`.
7. After disconnect, the Vue client checks Session Request status, then reloads a transcript page or receives terminal replay. It never resumes a partial stream.

### History

The history router adapts the established `HistorySearchQuery`, `HistorySearchResult`, and historical-item formatter to HTTP. It does not alter history scoring, storage, reference semantics, latest-digest context, or OpenClaw capabilities.

### CORS and deployment

The API uses an explicit loopback-development allowlist from configuration for browser origins, methods, and headers. Wildcard origins are not used. CORS is a browser policy, not access control. A public backend—including fake mode—requires visitor isolation, expiry, quotas, and rate limiting, and is deferred. The frontend must not proxy streaming requests through a Vercel function: digest streaming needs a long-lived backend process and SQLite needs persistent storage.

## Error Handling

| Case | HTTP/SSE behavior |
|---|---|
| Invalid source, date range, request body, or malformed historical reference | `400` with a safe validation message |
| Missing session | `404` |
| Different request while a session is active, or deletion of an active session | `409 session_busy`; no second user message or run |
| Duplicate active request ID | `409 request_in_progress`; no second user message or run |
| Duplicate terminal or interrupted request ID | Replay stored terminal outcome as SSE without creating a second run |
| Empty history or session search | `200` with an empty result |
| Connector warning | `200`; included in rendered markdown and structured digest warnings |
| Failure before SSE starts | `500` plus safe message and correlation ID |
| Failure after SSE starts | Terminal `error` event; HTTP status remains `200` |
| Cancellation before digest persistence | Terminal `error` event with `code: "cancelled"` |
| Cancellation after digest persistence starts | `204`; successful terminal result remains authoritative |
| Startup finds active request | Mark `interrupted`; never automatically rerun it |
| Unexpected repository/workflow failure | Safe client message, correlation ID, full diagnostic only in existing logs |

The API never exposes stack traces, provider tokens, connector credentials, or raw upstream response bodies.

## Testing and Acceptance

This implementation is TDD-suitable and must use strict RED/GREEN cycles. Refactoring-only package moves occur only after the current suite is green and remain behavior-preserving.

Automated coverage must include:

- v1 SQLite migration: existing digest, history, CLI, and shared-interface follow-up reads survive migration to schema v2.
- Migration failure preserves the v1 database and its one-time backup; normal v2 startup does not create a backup.
- Session CRUD, deterministic initial titles, ordered message persistence, user-selected session preferences, and inactive-session deletion/unlink behavior.
- Session isolation: two sessions generate runs; a structured follow-up in each resolves only that session's latest run.
- Shared-interface compatibility: CLI, Gradio, and OpenClaw use only non-session runs and browser-created runs do not change their context.
- Session Request idempotency, terminal replay, `interrupted` startup recovery, one-active-request rule, and cancellation point of no return.
- One atomic transaction persists each digest bundle and its session-request association; a failed bundle has no visible partial rows.
- SSE ordering, progress/delta forwarding, `DigestView` discriminated-union payloads, terminal `done`, and failure-after-start `error`.
- Client disconnect does not prevent server-side terminal persistence; request-status polling recovers the UI.
- Cursor pagination and lexical session-search weighting, one-result-per-session rule, snippet, and matching message ID.
- `/health`, `/digest`, and `/followup` parity with current OpenClaw response schemas and path values.
- API history endpoints preserve 7D.1 lexical, persist-only behavior.
- CORS allowlist behavior.
- Fake-mode end-to-end API smoke test with no network or provider key.
- Regression coverage for CLI, Gradio, deterministic structured follow-ups, open-ended tool routing, rendering, and existing history tests.

Acceptance:

1. Concurrent browser sessions can run digests and follow up independently; each session permits only one active request.
2. Reloading a completed or disconnected session reveals its durable transcript, request status, and associated digest view without stream resumption.
3. CLI, Gradio, and OpenClaw continue to inspect only shared-interface context and never a browser-session run.
4. Vue 8B can obtain a generated typed client from the FastAPI OpenAPI document and render source-specific digest views plus Markdown fallback.
5. Existing OpenClaw workflows work without an endpoint, response-shape, or path-taxonomy change.
6. Gradio remains a working transitional client until 8B is accepted.
7. All default tests run offline in fake mode; no default test calls an external API.

## Implementation Slices

### 8A.1a: Persistence foundation

Implement and test schema v2 migration backup/rollback behavior; sessions, messages, and Session Requests; shared-interface versus session context; the SQLite Unit of Work; and atomic digest-bundle persistence. No FastAPI routes or Vue work land in this slice.

### 8A.1b: Session application behavior

Implement and test session service behavior: one active request per session, idempotency and terminal replay, interrupted-request startup recovery, cancellation point of no return, typed chat events, and the `DigestView` discriminated union. Existing Gradio behavior remains compatible through its string-stream adapter.

### 8A.1c: HTTP API and compatibility

Implement and test `/api/v1` FastAPI routes, SSE transport, request-status recovery, cursor pagination, session lexical search, history adapters, loopback CORS configuration, OpenAPI generation, and unversioned OpenClaw route parity. Replace the hand-written HTTP service only after parity passes. OpenDesign work begins after this slice freezes and proves the OpenAPI contract.

## Deferred Work

### 8A.2: Vector-backed semantic recall and memory

SQLite remains the source of truth for session metadata, message ordering, and digest relationships. A vector index, if adopted, is a secondary retrieval index, not a replacement for session storage.

8A.2 may change only the implementation behind `GET /api/v1/sessions/search` from lexical session-title/message matching to semantic search. A separate ADR must select the embedding provider and vector index after evaluating:

- **sqlite-vec**, preserving the single-file local-first deployment;
- **Chroma**, a local development-oriented vector store;
- **Qdrant**, appropriate if a separately hosted service becomes necessary.

Memory RAG is a separate 8A.2 behavior: retrieve bounded relevant prior turns for open-ended tool-agent follow-ups only. It must not modify deterministic structured follow-ups, rank deep-dives, or historical digest search. Fake mode requires a deterministic fake embedder or an explicit feature-disabled response; it must not silently require a remote embedding key.

### 8B: Vue web interface

8B creates the frontend after OpenDesign produces the UI design. It uses Vue 3, Vite, TypeScript, Tailwind CSS, shadcn-vue, and an OpenAPI-generated client. Its core screens are session navigation, transcript/chat stream, digest cards and tables, source preferences, history search, and explicit fake-demo status. It consumes the 8A.1 contract and does not dictate backend contract changes merely for presentation.

### Future deployment and accounts

If the application becomes remotely live, add authentication, per-user or anonymous-visitor isolation, expiry, quotas, rate limiting, provider-key safeguards, and a persistent hosted database before exposing digest generation. These concerns are intentionally not hidden behind a single shared password or fake mode in 8A.1.
