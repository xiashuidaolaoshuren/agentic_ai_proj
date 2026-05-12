# Implementation Plan: AI News Research Agent

**Spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**Created:** 2026-05-02  
**Subsystem scope:** Milestone 1: Local Digest MVP

## Summary

Ship a local-first Python/LangGraph AI News Research Chatbot that generates an on-demand digest from GitHub and conservative Bilibili-oriented sources. The MVP includes domain models, source connectors, ranking, summarization, local persistence, inspectable artifacts, a Gradio chat UI, and tests. OpenClaw, scheduled runs, cloud deployment, arXiv, Hugging Face, RSS/blog connectors, and vector RAG are out of scope for this implementation pass.

## Discovery Notes

- Reuse: the repo currently contains the approved design spec only, so this plan establishes the initial Python project structure.
- Constraints: keep source access conservative; use GitHub APIs/search where possible; do not depend on brittle Bilibili deep crawling for MVP success.
- Patterns to follow: use focused modules under `src/ai_news_agent/`; define typed domain models before connectors; keep external APIs behind connector interfaces.
- Framework notes: LangGraph workflows should use typed state and named nodes; Gradio can expose a small chatbot function that delegates to the core agent.
- Anti-goals: no broad crawler, no production OpenClaw adapter, no deployment, no large vector database, and no unrelated project scaffolding.

## File Map

### Subsystem: Local Digest MVP

| Path | Create/Modify | Responsibility | Public Surface |
|------|----------------|----------------|----------------|
| `pyproject.toml` | create | Python package metadata, dependencies, dev tools, pytest config | package config; console script if used |
| `.gitignore` | create | Ignore local env, caches, generated DBs, and digest artifacts | repo hygiene |
| `.env.example` | create | Document required environment variables without secrets | env var names |
| `README.md` | create | Explain setup, local run, test commands, and MVP limits | user-facing project guide |
| `src/ai_news_agent/__init__.py` | create | Package marker and version metadata | package import |
| `src/ai_news_agent/config.py` | create | Load settings from environment with safe defaults | `Settings`, `load_settings()` |
| `src/ai_news_agent/models.py` | create | Shared typed domain models for items, rankings, digests, and warnings | `NewsItem`, `RankedItem`, `Digest`, enums |
| `src/ai_news_agent/topics.py` | create | Initial AI topic taxonomy and query expansion helpers | `DEFAULT_TOPICS`, `build_queries()` |
| `src/ai_news_agent/connectors/__init__.py` | create | Connector package exports | connector imports |
| `src/ai_news_agent/connectors/base.py` | create | Connector protocol and shared result types | `SourceConnector`, `ConnectorResult` |
| `src/ai_news_agent/connectors/github.py` | create | GitHub search/repo metadata connector | `GitHubConnector` |
| `src/ai_news_agent/connectors/bilibili.py` | create | Conservative Bilibili metadata connector (keyword + uploader-targeted + manual-link inputs) | `BilibiliConnector` |
| `src/ai_news_agent/ranking.py` | create | Score, deduplicate, and select candidate items | `rank_items()` |
| `src/ai_news_agent/llm.py` | create | OpenAI-compatible chat client wrapper and testable protocol | `ChatModel`, `build_chat_model()` |
| `src/ai_news_agent/summarizer.py` | create | Convert ranked source data into digest entries using LLM or test stub | `summarize_ranked_items()` |
| `src/ai_news_agent/storage.py` | create | SQLite persistence for items, rankings, digests, warnings, and logs | `DigestStore` |
| `src/ai_news_agent/rendering.py` | create | Render digests as Markdown/text for CLI and UI | `render_digest_markdown()` |
| `src/ai_news_agent/graph/__init__.py` | create | LangGraph package exports | graph imports |
| `src/ai_news_agent/graph/state.py` | create | Typed LangGraph state shape | `DigestGraphState` |
| `src/ai_news_agent/graph/workflow.py` | create | Build and run the LangGraph digest workflow | `build_digest_graph()`, `run_digest()` |
| `src/ai_news_agent/chat.py` | create | Follow-up chat service over latest saved digest and source traces | `ChatService` |
| `src/ai_news_agent/cli.py` | create | Local command-line entrypoints for smoke testing and future adapters | `main()` |
| `src/ai_news_agent/app/__init__.py` | create | UI package marker | app imports |
| `src/ai_news_agent/app/gradio_app.py` | create | Gradio chatbot UI that delegates to `ChatService`/workflow | `create_app()`, `main()` |
| `tests/fixtures/*.json` | create | Stable connector/ranking/summarization fixture data | test fixtures |
| `tests/conftest.py` | create | Shared pytest fixtures and fake model/client setup | pytest fixtures |
| `tests/test_models.py` | create | Validate model defaults, serialization, and required fields | pytest tests |
| `tests/test_storage.py` | create | Verify SQLite persistence and retrieval | pytest tests |
| `tests/test_connector_contracts.py` | create | Verify connector protocol, shared result shape, and fixture loading | pytest tests |
| `tests/test_connectors_github.py` | create | Verify GitHub connector mapping with mocked responses | pytest tests |
| `tests/test_connectors_bilibili.py` | create | Verify Bilibili connector mapping and low-confidence behavior | pytest tests |
| `tests/test_ranking.py` | create | Verify scoring, deduplication, and top-N selection | pytest tests |
| `tests/test_summarizer.py` | create | Verify digest entry format and missing-content caveats | pytest tests |
| `tests/test_rendering.py` | create | Verify Markdown/text digest rendering | pytest tests |
| `tests/test_workflow.py` | create | Verify end-to-end graph behavior using fake connectors/model | pytest tests |
| `tests/test_chat.py` | create | Verify digest requests and follow-up routing independent of UI | pytest tests |
| `tests/test_cli.py` | create | Verify CLI smoke path against fixture/fake data | pytest tests |

### Future Paths Not In This Plan

| Path | Reason Deferred |
|------|-----------------|
| `src/ai_news_agent/adapters/openclaw.py` | Milestone 2 after local workflow is stable |
| `src/ai_news_agent/connectors/arxiv.py` | Milestone 3 broader source expansion |
| `src/ai_news_agent/connectors/huggingface.py` | Milestone 3 broader source expansion |
| `src/ai_news_agent/scheduler.py` | Milestone 4 scheduling |
| vector database integration | Not needed until saved digest volume justifies semantic retrieval |

### Blast Radius

| Path | Why Sensitive | Plan Mode Before Implementation |
|------|---------------|---------------------------------|
| `pyproject.toml` | Establishes dependency and command structure for the whole project | high - confirm package manager, supported Python version, and dependency set |
| `src/ai_news_agent/models.py` | Shared contract used by connectors, ranking, storage, summarization, and UI | high - finalize fields before dependent work |
| `src/ai_news_agent/storage.py` | SQLite schema becomes the persistence contract | high - confirm schema and migration approach for MVP |
| `src/ai_news_agent/connectors/github.py` | External API behavior, rate limits, auth, and response shape can change | high - verify API strategy and fallback behavior |
| `src/ai_news_agent/connectors/bilibili.py` | Source access is less stable and must avoid brittle assumptions | high - verify conservative metadata approach |
| `src/ai_news_agent/graph/workflow.py` | Orchestrates the whole workflow and sets LangGraph conventions | high - research graph state and node boundaries before implementation |
| `src/ai_news_agent/app/gradio_app.py` | User-facing entrypoint and interaction loop | medium - confirm Gradio chat history shape before implementation |

## Workflow For Implementers

1. `writing-plans` produced this file as decomposition only.
2. For each subtask: use Cursor Plan mode when priority is high or the integration is uncertain; then use Agent mode with the `test-driven-development` skill.
3. If implementation reveals missing files, wrong boundaries, or changed dependencies, pause and update this plan before continuing.
4. Keep this file as the durable source of truth for this implementation pass.

## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 - Project Scaffold And Tooling

- [X] **Do:** Create the Python package scaffold, dependency config, README, `.gitignore`, and `.env.example`. Establish the test command and local run command.
- **Blocked by:** —
- **Plan mode:** high
- **Verification:** `python -m pytest --version` and `python -c "import ai_news_agent"`

### T2 - Domain Models And Topic Defaults

- [X] **Do:** Define typed models for source items, ranked items, digest outputs, warnings, and the initial AI topic taxonomy. Keep the models stable enough for connectors and storage to depend on.
- **Blocked by:** T1
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_models.py`

### T3 - Connector Interfaces And Fixtures

- [X] **Do:** Define the connector protocol/result shape and create fixture data for GitHub and Bilibili-like results. This gives later connector work a test-first contract.
- **Blocked by:** T2
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_connector_contracts.py`

### T4 - Local Storage Layer

- [X] **Do:** Implement SQLite persistence for source metadata, normalized items, ranking results, final digests, and connector warnings. Include retrieval helpers for latest digest follow-up.
- **Blocked by:** T2
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_storage.py`

### T5 - GitHub Connector

- [X] **Do:** Implement a GitHub connector that maps API/search results into `NewsItem` objects, handles missing optional fields, and records rate-limit or request warnings.
- **Blocked by:** T3
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_connectors_github.py`

### T6 - Bilibili-Oriented Connector

- [X] **Do:** Implement conservative Bilibili-oriented collection using keyword metadata, optional uploader-targeted inputs (request-provided handles/UIDs), and/or manually supplied links. It must mark missing transcript/content as lower confidence rather than inventing details.
- **Blocked by:** T3
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_connectors_bilibili.py`

### T7 - Ranking And Deduplication

- [X] **Do:** Implement scoring, duplicate handling, source-quality penalties, freshness handling, and top-N selection. Ranking reasons must be inspectable.
- **Blocked by:** T2, T5, T6
- **Plan mode:** medium
- **Verification:** `python -m pytest tests/test_ranking.py`

### T8 - LLM Client And Summarization

- [ ] **Do:** Add an OpenAI-compatible model wrapper plus a summarizer that creates source-language summaries, why-it-matters notes, background knowledge, follow-up actions, and confidence caveats. Tests should use a fake model.
- **Blocked by:** T2, T7
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_summarizer.py`

### T9 - Markdown/Text Rendering

- [ ] **Do:** Render digest objects into readable Markdown/text for CLI and Gradio. Keep rendering separate from summarization so outputs are easy to test.
- **Blocked by:** T8
- **Plan mode:** skip
- **Verification:** `python -m pytest tests/test_rendering.py`

### T10 - LangGraph Workflow

- [ ] **Do:** Build the digest graph with nodes for request parsing, source collection, ranking, summarization, storage, and rendering. Use fake connectors/model in tests for deterministic coverage.
- **Blocked by:** T4, T5, T6, T7, T8, T9
- **Plan mode:** high
- **Verification:** `python -m pytest tests/test_workflow.py`

### T11 - Follow-Up Chat Service

- [ ] **Do:** Implement a chat service that routes digest requests through the workflow and answers follow-up questions from the latest saved digest/source traces. Keep it independent from Gradio.
- **Blocked by:** T4, T10
- **Plan mode:** medium
- **Verification:** `python -m pytest tests/test_chat.py`

### T12 - CLI Smoke Entry Point

- [ ] **Do:** Add a CLI path that can run a digest request with fixture/fake mode for smoke testing and future OpenClaw adapter compatibility.
- **Blocked by:** T10
- **Plan mode:** skip
- **Verification:** `python -m pytest tests/test_cli.py`

### T13 - Gradio Chat UI

- [ ] **Do:** Build a local Gradio chatbot that delegates to `ChatService`, shows digest output, and supports follow-up messages. Keep UI code thin.
- **Blocked by:** T11
- **Plan mode:** medium
- **Verification:** launch locally with `python -m ai_news_agent.app.gradio_app` and ask for a fixture-backed digest

### T14 - End-To-End MVP Check And Docs

- [ ] **Do:** Add a final smoke path and update README instructions for setup, environment variables, running tests, launching the chatbot, and known MVP limits.
- **Blocked by:** T12, T13
- **Plan mode:** skip
- **Verification:** `python -m pytest` and manual local chatbot digest request

## TDD Note For Agent Mode

When implementing, follow the `test-driven-development` skill for each subtask or small batch: write the failing test first, implement the minimal code, then refactor. This plan names the boundaries and acceptance checks; it does not replace red/green/refactor.

## Plan Changelog

| Date | Change |
|------|--------|
| 2026-05-02 | Initial implementation plan for Milestone 1: Local Digest MVP |
| 2026-05-12 | Completed T6: `BilibiliConnector`, extended `ConnectorRequest`, tests in `test_connectors_bilibili.py` |
| 2026-05-12 | Completed T7: `rank_items()` in `ranking.py`, tests in `test_ranking.py` |

