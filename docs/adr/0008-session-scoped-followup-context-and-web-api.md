# Session-scoped follow-up context and FastAPI web API

Status: accepted

The existing local interfaces resolve structured follow-ups from one global latest saved digest. That is acceptable for CLI and OpenClaw's single shared local workflow, but incorrect for a browser application with concurrent conversations: a digest generated in one tab can silently change the follow-up context in another.

Milestone 8A.1 introduces durable sessions and messages in SQLite. Browser chat reads follow-up context through a session-scoped query that finds the latest run associated with that session. The existing global `get_latest_followup_context()` remains unchanged for CLI and OpenClaw, including when the global latest run originated in a browser session. Sessions own their conversation transcript and preferences; digest runs remain global records, and historical digest search remains archive-wide.

The web API is FastAPI with REST resources and a POST response streamed by Server-Sent Events. It exposes both structured digest data and the existing authoritative Markdown rendering. FastAPI's async model and Pydantic/OpenAPI support fit the existing asynchronous LangGraph workflow and enable a typed Vue client. Existing `/health`, `/digest`, and `/followup` paths retain their OpenClaw contracts and delegate to the same application composition root. Gradio remains as a transitional interface until Milestone 8B's Vue application is complete.

## Considered options (rejected)

- **Django + Django REST Framework or Django Ninja** — Django's ORM, admin, templates, and built-in authentication do not solve an 8A.1 problem, while the current asynchronous streaming workflow would require extra adaptation. FastAPI directly fits the project’s Pydantic schemas and async generators.
- **GraphQL with subscriptions** — the primary operation is a fixed-shape, long-running command with server progress, not client-selected traversal of a large entity graph. GraphQL would require a mutation plus WebSocket subscription correlation where REST plus SSE is simpler.
- **WebSocket chat transport** — bidirectional transport is unnecessary for current streamed output. Cancellation has a separate idempotent REST endpoint; WebSockets can be introduced later only if a real bidirectional feature requires them.
- **Markdown-only API** — this preserves rendering but reduces the Vue app to a styled Markdown viewer.
- **Structured-JSON-only API** — this duplicates rendering rules already shared by CLI and OpenClaw and risks presentation drift.
- **A session service that bypasses `DigestStore`** — latest-follow-up context is defined by storage queries, so this would duplicate data-access logic outside the repository boundary.
- **Make every interface session-first** — it would remove the global concept but require broad CLI/OpenClaw behavior and test changes with no browser requirement.
- **Keep a separate hand-written OpenClaw HTTP server** — this would leave duplicated application assembly and divergent HTTP behavior.
- **Add vectors as session storage** — sessions need ordered messages, foreign keys, and exact IDs, which are relational concerns. A vector index is only justified as optional semantic retrieval.
- **Add real accounts or a shared public live password in 8A.1** — public live requests would still need rate limits, ownership, and credential safeguards. The initial hosted demo therefore uses fake mode.

## Consequences

- Browser conversations no longer cross-contaminate structured follow-up context.
- SQLite schema advances from v1 to v2, preserving existing global digest data and allowing `runs.session_id` to be null for preexisting rows.
- Global CLI and OpenClaw behavior deliberately remains global, rather than implicitly adopting the last browser session.
- FastAPI becomes the HTTP implementation and is the source of the Vue client's OpenAPI contract.
- Server-rendered Markdown remains the text contract; structured digest data supports richer frontend presentation.
- An SSE reconnect reloads durable transcript state rather than resuming arbitrary partial stream bytes.
- SQLite remains the system of record. Semantic session search and memory RAG are deferred to 8A.2 behind the `/api/sessions/search` contract.
- Gradio remains temporarily, then is removed only after Milestone 8B provides equivalent functionality.
