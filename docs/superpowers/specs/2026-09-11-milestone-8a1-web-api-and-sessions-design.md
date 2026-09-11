# Milestone 8A.1: Web API and Session-Scoped Chat

Date: 2026-09-11
Status: approved design

## Summary

Milestone 8 turns the local Gradio interface into a full-stack web application in two stages:

- **8A.1 (this design):** establish a three-layer FastAPI backend, preserve the OpenClaw HTTP contract, and add durable, session-scoped chat over REST plus Server-Sent Events (SSE).
- **8A.2 (later):** add optional semantic session search and long-term memory behind the 8A.1 API contract.
- **8B (later):** build the Vue 3 + Vite + Tailwind CSS + shadcn-vue web interface from the stable 8A.1 contract. OpenDesign is used to create the UI design after 8A.1 is complete.

The project remains local-first and single-user in 8A.1. A user may have multiple browser conversations at once; each conversation owns its transcript and its follow-up context. A public demonstration may host the Vue app on Vercel only when its backend runs in deterministic `--fake` mode. Live credentials and a live backend remain local-only in this milestone.

This design supersedes the hand-written HTTP implementation in `app/digest_service.py` as the web-service implementation, while retaining its `/health`, `/digest`, and `/followup` contracts for OpenClaw.

## Goals

- Expose the agent through a documented FastAPI REST API with streamed chat responses.
- Add durable chat sessions and messages, so concurrent browser conversations do not overwrite one another's follow-up context.
- Keep existing CLI, Gradio, and OpenClaw behavior working during the transition.
- Return both existing server-rendered markdown and structured digest data, allowing the future Vue UI to render rich components without duplicating the authoritative text renderer.
- Establish visible, enforceable presentation, application, and data-access boundaries without moving unrelated mature modules.
- Preserve local, deterministic fake-mode tests and demos.
- Freeze a session-search endpoint contract now, while leaving its initial implementation lexical and SQLite-backed.

## Non-Goals

- Vue, Vite, Tailwind, shadcn-vue, or OpenDesign-generated production UI work (Milestone 8B).
- Removing Gradio before the Vue interface has shipped.
- User accounts, authorization, multi-tenancy, or public live-backend access.
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
| Session ownership | A session owns its messages, source settings, and latest digest context |
| Existing global context | It remains for CLI and OpenClaw; session-scoped reads are added beside it |
| Persistence | SQLite remains the system of record |
| Public demo | Vercel frontend may call an explicitly CORS-allowed backend running `--fake`; live backend stays local |
| Semantic memory | Deferred to 8A.2 behind the API contract |

ADR-0008 records the FastAPI and session-context decisions. Existing historical digest search remains governed by ADR-0007: it searches saved digest entries lexically and is not conversation memory.

## Architecture

### Layer boundaries

The new API-related modules use this direction:

```text
api  →  services  →  repositories
```

`api` translates HTTP, SSE, and Pydantic API contracts into service calls. It contains no SQL, connector construction, graph execution, or rendering rules.

`services` implements application use cases: session lifecycle, chat routing, streaming event translation, and cancellation coordination. It depends on repository interfaces and existing domain/workflow modules, but not on FastAPI request or response objects.

`repositories` owns SQLite schema migration and queries. It returns domain data or repository records and contains no routing, Markdown rendering, SSE encoding, or lexical/semantic scoring policy.

Existing `connectors/`, `graph/`, `tools/`, `models.py`, `rendering.py`, `ranking.py`, and follow-up formatters remain where they are. The package relocation is intentionally limited to the API-facing units; imports and module documentation identify their conceptual layer. An import-boundary test or linter rule enforces that `repositories` never imports `services` or `api`, and `services` never imports `api`.

### New and moved modules

```text
src/ai_news_agent/
  api/
    app.py                 # FastAPI application factory, lifespan, CORS
    deps.py                # dependencies backed by the composition root
    sse.py                 # SSE event encoding only
    schemas/
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
```

Compatibility re-export modules may remain temporarily at the old `chat.py` and `storage.py` import paths if they keep CLI, Gradio, tools, and tests stable while callers migrate. They must contain no behavior.

### Single composition root

`services/composition.py` is the only place that constructs a `DigestStore`, session store, LLMs, connector factories, workflow runner, interface tool router, and chat service. It accepts `fake` and `db_path` configuration.

Gradio, CLI/service startup, and FastAPI all obtain services from this composition root. This removes the currently duplicated construction in Gradio and the warm digest service and prevents a third divergent FastAPI implementation.

### Why FastAPI

The existing workflow and streaming code are asynchronous, and domain/tool schemas already use Pydantic v2. FastAPI exposes these naturally and produces an OpenAPI document from which 8B can generate a typed TypeScript client. Django's ORM, admin, template system, and built-in authentication are not needed in 8A.1; Django plus DRF or Django Ninja would add adaptation around the async stream without solving a current problem.

## Session and Message Model

### Ownership rules

A **session** is a durable conversation thread. It owns:

- ordered user and assistant messages;
- session-sticky connector selections and `items_per_source`;
- the session's latest digest run, derived from the latest run associated with that session.

Digest runs remain global persisted records. Historical digest search continues to search the whole saved digest archive, not only one session.

`DigestStore.get_latest_followup_context()` remains global and unchanged. It is used by CLI and OpenClaw. A new `get_followup_context_for_session(session_id)` selects the latest run associated with that session and is used only by the web-session flow. Therefore, a browser digest must not change the meaning of `openclaw-followup`; OpenClaw still resolves global latest state.

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

ALTER TABLE runs ADD COLUMN session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL;
CREATE INDEX idx_runs_session_id_id ON runs(session_id, id DESC);
CREATE INDEX idx_session_messages_session_sequence
  ON session_messages(session_id, sequence);
```

Session identifiers are UUIDs created by the server. A session title is nullable at creation and is derived from the first user message until the user changes it. `connector_names` is the canonical source-name JSON array or `NULL`; `NULL` preserves the existing default source resolution. `items_per_source` is `NULL` until the user chooses a session preference.

Existing databases are upgraded in place. `DigestStore.init_schema()` becomes a versioned migration that increments `SCHEMA_VERSION` from `"1"` to `"2"` after adding the column, tables, and indexes. Migration is idempotent and preserves all v1 rows. Preexisting runs have `session_id = NULL` and remain reachable through global CLI, OpenClaw, and history behavior.

### Message durability

The service persists the user message before beginning work. It collects streamed assistant text server-side and persists the final assistant message with its associated run ID when terminal processing completes. Persistence continues if the HTTP/SSE client disconnects; reconnecting clients can load the completed transcript. A failed or cancelled run persists a safe terminal assistant message when there is user-facing output, but it never stores raw exception detail.

The initial release does not resume a partially consumed SSE byte stream. A client that reconnects reloads persisted messages, then may send a new request. This avoids claiming resumability that a `fetch`-based POST SSE client cannot provide.

## API Contract

The FastAPI application serves both the versioned browser API and unversioned OpenClaw compatibility routes. It produces OpenAPI at the normal FastAPI OpenAPI endpoint; 8B treats that document as the client-contract source.

### Browser API

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Web API health and mode (`fake`) |
| `GET /api/sources` | Canonical sources, defaults, and opt-in metadata |
| `POST /api/sessions` | Create a session |
| `GET /api/sessions` | List sessions, newest activity first |
| `GET /api/sessions/{session_id}` | Get session metadata |
| `PATCH /api/sessions/{session_id}` | Rename a session or update sticky source preferences |
| `DELETE /api/sessions/{session_id}` | Delete its session/messages; unlinks, but does not delete, global digest runs |
| `GET /api/sessions/{session_id}/messages` | Return ordered durable transcript, including the persisted digest payload for digest-linked assistant messages |
| `POST /api/sessions/{session_id}/messages` | Persist user input and return an SSE response |
| `POST /api/sessions/{session_id}/requests/{request_id}/cancel` | Ask the active request to cancel |
| `GET /api/sessions/search?q=` | Search sessions; lexical in 8A.1, semantic in 8A.2 |
| `GET /api/history/search` | Existing historical digest search, using its established filters |
| `GET /api/history/{historical_item_ref}` | Existing read-only historical item open |

`POST /api/sessions/{session_id}/messages` accepts:

```json
{
  "content": "Give me today's AI digest",
  "client_request_id": "optional-uuid"
}
```

The server creates a request UUID when `client_request_id` is absent. Reusing the same ID for the same session is idempotent: it must not create a duplicate user message or rerun an already terminal request. A duplicate active request returns `409 request_in_progress`; a duplicate terminal request returns its stored outcome as a normal SSE replay (`started`, any persisted `delta` text, optional `digest`, then `done`). This makes browser retry behavior safe without claiming arbitrary SSE byte-stream resumption.

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

`markdown` is the existing renderer's authoritative output. `digest` uses the existing Pydantic domain model where its public shape is already suitable; API-specific Pydantic DTOs are limited to sessions, messages, requests, and event envelopes. `GET /api/sessions/{session_id}/messages` includes the same digest payload for an assistant message linked to a digest run, so a refreshed UI retains rich rendering. Vue may render rich digest components from `digest` but must fall back to `markdown` for tool-agent, structured-follow-up, history, and guidance responses.

The browser consumes the POST stream with `fetch` and a `ReadableStream` reader; native `EventSource` only supports GET and is not applicable to this request shape.

Cancellation is cooperative. The service tracks active request IDs, sets cancellation state, and stops at a safe await boundary. The cancel endpoint returns `202 Accepted` for an active request and `204 No Content` for an already terminal or unknown request, making repeated cancellation safe. A cancellation emits terminal `error` with a stable `cancelled` code rather than pretending a partial digest succeeded.

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

1. The client creates or selects a session and loads its transcript.
2. It posts a message to that session, optionally with a client request UUID.
3. The session service validates the request and persists the user message before emitting `started`.
4. Chat routing uses the session's preferences and `get_followup_context_for_session()`. Digest runs are written with the current `session_id`.
5. The service translates typed chat events into `progress` and `delta` SSE events. The existing Gradio string-stream adapter preserves its current behavior over the same event seam.
6. At terminal success, the assistant message is persisted, then the service emits a `digest` event when relevant and a `done` event.
7. The Vue client updates optimistically from events and reconciles from the persisted transcript after reconnect or refresh.

### History

The history router adapts the established `HistorySearchQuery`, `HistorySearchResult`, and historical-item formatter to HTTP. It does not alter history scoring, storage, reference semantics, latest-digest context, or OpenClaw capabilities.

### CORS and deployment

The API uses an explicit allowlist from configuration for browser origins, methods, and headers. Development allows the Vite origin; a public fake-mode demo may add its Vercel origin. Wildcard origins are not used. The frontend calls the backend directly rather than through a Vercel function, because digest streaming requires a long-lived backend process and SQLite needs persistent storage. A live public endpoint is out of scope without authentication and rate limiting.

## Error Handling

| Case | HTTP/SSE behavior |
|---|---|
| Invalid source, date range, request body, or malformed historical reference | `400` with a safe validation message |
| Missing session | `404` |
| Duplicate active request ID | `409 request_in_progress`; no second user message or run |
| Duplicate terminal request ID | Replay stored terminal outcome as SSE without creating a second run |
| Empty history or session search | `200` with an empty result |
| Connector warning | `200`; included in rendered markdown and structured digest warnings |
| Failure before SSE starts | `500` plus safe message and correlation ID |
| Failure after SSE starts | Terminal `error` event; HTTP status remains `200` |
| Cancellation | Terminal `error` event with `code: "cancelled"` |
| Unexpected repository/workflow failure | Safe client message, correlation ID, full diagnostic only in existing logs |

The API never exposes stack traces, provider tokens, connector credentials, or raw upstream response bodies.

## Testing and Acceptance

This implementation is TDD-suitable and must use strict RED/GREEN cycles. Refactoring-only package moves occur only after the current suite is green and remain behavior-preserving.

Automated coverage must include:

- v1 SQLite migration: existing digest, history, CLI, and global latest-follow-up reads survive migration to schema v2.
- Session CRUD, ordered message persistence, user-selected session preferences, and deletion/unlink behavior.
- Session isolation: two sessions generate runs; a structured follow-up in each resolves only that session's latest run.
- Global compatibility: CLI and OpenClaw continue to use global latest-follow-up context, including browser-created runs.
- Chat request idempotency and cancellation semantics.
- SSE ordering, progress/delta forwarding, structured `digest` payload, terminal `done`, and failure-after-start `error`.
- Client disconnect does not prevent server-side terminal persistence.
- `/health`, `/digest`, and `/followup` parity with current OpenClaw response schemas and path values.
- API history endpoints preserve 7D.1 lexical, persist-only behavior.
- CORS allowlist behavior.
- Fake-mode end-to-end API smoke test with no network or provider key.
- Regression coverage for CLI, Gradio, deterministic structured follow-ups, open-ended tool routing, rendering, and existing history tests.

Acceptance:

1. Two active browser sessions can run digests and follow up independently without context crossover.
2. Reloading a completed or disconnected session shows its durable transcript and associated digest result.
3. Vue 8B can obtain a generated typed client from the FastAPI OpenAPI document and render digests from both JSON and markdown.
4. Existing OpenClaw workflows work without an endpoint, response-shape, or path-taxonomy change.
5. Gradio remains a working transitional client until 8B is accepted.
6. All default tests run offline in fake mode; no default test calls an external API.

## Deferred Work

### 8A.2: Vector-backed semantic recall and memory

SQLite remains the source of truth for session metadata, message ordering, and digest relationships. A vector index, if adopted, is a secondary retrieval index, not a replacement for session storage.

8A.2 may change only the implementation behind `GET /api/sessions/search` from lexical session-title/message matching to semantic search. A separate ADR must select the embedding provider and vector index after evaluating:

- **sqlite-vec**, preserving the single-file local-first deployment;
- **Chroma**, a local development-oriented vector store;
- **Qdrant**, appropriate if a separately hosted service becomes necessary.

Memory RAG is a separate 8A.2 behavior: retrieve bounded relevant prior turns for open-ended tool-agent follow-ups only. It must not modify deterministic structured follow-ups, rank deep-dives, or historical digest search. Fake mode requires a deterministic fake embedder or an explicit feature-disabled response; it must not silently require a remote embedding key.

### 8B: Vue web interface

8B creates the frontend after OpenDesign produces the UI design. It uses Vue 3, Vite, TypeScript, Tailwind CSS, shadcn-vue, and an OpenAPI-generated client. Its core screens are session navigation, transcript/chat stream, digest cards and tables, source preferences, history search, and explicit fake-demo status. It consumes the 8A.1 contract and does not dictate backend contract changes merely for presentation.

### Future deployment and accounts

If the application becomes remotely live rather than a fake-mode demo, add authentication, per-user ownership, rate limiting, provider-key safeguards, and a persistent hosted database before exposing live digest generation. These concerns are intentionally not hidden behind a single shared password in 8A.1.
