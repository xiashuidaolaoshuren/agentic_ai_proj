# Session-scoped follow-up context and FastAPI web API

Status: accepted

The existing local interfaces resolve structured follow-ups from one global latest saved digest. That is acceptable for a single local workflow, but incorrect for a browser application with concurrent conversations: a digest generated in one tab can silently change the follow-up context in another. Letting browser-created runs become the global latest would also make CLI, Gradio, and OpenClaw inspect an unrelated browser conversation.

Milestone 8A.1 introduces durable sessions, messages, and Session Requests in SQLite. Browser chat reads follow-up context through a session-scoped query that finds the latest successful run associated with that session. CLI, Gradio, and OpenClaw instead use **shared-interface context**: the latest saved run with no session association. Sessions own their conversation transcript, preferences, and one-active-request lifecycle; digest runs remain global records, and historical digest search remains archive-wide.

The web API is FastAPI with `/api/v1` REST resources and a POST response streamed by Server-Sent Events. It exposes both structured `DigestView` data and the existing authoritative Markdown rendering. FastAPI's async model and Pydantic/OpenAPI support fit the existing asynchronous LangGraph workflow and enable a typed Vue client. Existing `/health`, `/digest`, and `/followup` paths retain their OpenClaw contracts and delegate to the same application composition root. Gradio remains as a transitional interface until Milestone 8B's Vue application is complete.

Session Requests provide a durable idempotency key, terminal replay, cancellation state, and crash recovery. Startup marks stranded active requests as interrupted and never reruns them automatically. A connection-scoped SQLite Unit of Work writes a complete digest bundle and request association atomically; digest persistence is the cancellation point of no return. The initial delivery is split into persistence foundation (8A.1a), session application behavior (8A.1b), and FastAPI exposure (8A.1c).

## Considered options (rejected)

- **Django + Django REST Framework or Django Ninja** — Django's ORM, admin, templates, and built-in authentication do not solve an 8A.1 problem, while the current asynchronous streaming workflow would require extra adaptation. FastAPI directly fits the project’s Pydantic schemas and async generators.
- **GraphQL with subscriptions** — the primary operation is a fixed-shape, long-running command with server progress, not client-selected traversal of a large entity graph. GraphQL would require a mutation plus WebSocket subscription correlation where REST plus SSE is simpler.
- **WebSocket chat transport** — bidirectional transport is unnecessary for current streamed output. Cancellation has a separate idempotent REST endpoint; WebSockets can be introduced later only if a real bidirectional feature requires them.
- **Markdown-only API** — this preserves rendering but reduces the Vue app to a styled Markdown viewer.
- **Structured-JSON-only API** — this duplicates rendering rules already shared by CLI and OpenClaw and risks presentation drift.
- **A session service that bypasses `DigestStore`** — latest-follow-up context is defined by storage queries, so this would duplicate data-access logic outside the repository boundary.
- **Make every interface session-first** — it would remove the global concept but require broad CLI/OpenClaw behavior and test changes with no browser requirement.
- **Let browser runs update global latest context** — old interfaces would retain the browser cross-context bug.
- **Keep a separate hand-written OpenClaw HTTP server** — this would leave duplicated application assembly and divergent HTTP behavior.
- **Add vectors as session storage** — sessions need ordered messages, foreign keys, and exact IDs, which are relational concerns. A vector index is only justified as optional semantic retrieval.
- **Unauthenticated shared fake backend** — fake mode protects provider credentials but does not isolate visitors or prevent storage abuse. Public hosting requires a separate deployment decision.

## Consequences

- Browser conversations no longer cross-contaminate structured follow-up context.
- SQLite schema advances from v1 to v2 through a one-time backup and transactional migration, preserving existing global digest data and allowing `runs.session_id` to be null for preexisting rows.
- CLI, Gradio, and OpenClaw deliberately use only non-session shared-interface context, rather than adopting a browser session's latest run.
- FastAPI becomes the HTTP implementation and `/api/v1` is the Vue client's OpenAPI contract; OpenClaw routes remain unversioned.
- Server-rendered Markdown remains the text contract; source-kind-discriminated `DigestView` data supports richer frontend presentation without exposing raw connector evidence.
- An SSE reconnect uses durable Session Request status and transcript reload/replay rather than resuming arbitrary partial stream bytes.
- One Session Request can be active per session; requests are idempotent, terminally replayable, and safely marked interrupted on startup after a crash.
- SQLite remains the system of record. Semantic session search and memory RAG are deferred to 8A.2 behind the `/api/v1/sessions/search` contract.
- Gradio remains temporarily, then is removed only after Milestone 8B provides equivalent functionality.
