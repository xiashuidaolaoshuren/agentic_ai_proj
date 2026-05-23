# Implementation Plan: Milestone 2 LLM Tool Usage Layer

**Spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**Created:** 2026-05-21  
**Subsystem scope:** Milestone 2: internal LLM-callable tool layer for follow-up inspection and connector-boundary source exploration

## Summary

Add a bounded LangGraph tool-calling layer on top of the completed Milestone 1 digest MVP. The deterministic digest workflow remains the stable default path. Milestone 2 introduces structured tools for saved-digest inspection, ranking/source trace explanation, and GitHub/Bilibili connector search through the existing `SourceConnector` contract. The first user-facing integration is follow-up chat in Gradio/ChatService, with connector tools available for controlled source exploration.

## Discovery Notes

- Reuse: `ChatService` already separates digest requests from follow-up handling, `DigestStore.get_latest_followup_context()` already returns digest, item, ranking, and warning data, and `SourceConnector`/`ConnectorRequest` is the right connector boundary for tool wrappers.
- Reuse: `sources.py` already owns source names and connector construction for CLI/Gradio; extend this boundary rather than duplicating connector factories.
- Reuse: existing tests cover chat routing, storage round trips, connector contracts, workflow regression, Gradio construction, and fake connectors/models.
- Framework constraint: current LangGraph docs support a tool loop with message state, `model.bind_tools(tools)`, a tool execution node or `ToolNode`, and conditional routing based on `last_message.tool_calls`.
- Dependency constraint: the project currently depends on `langgraph` and `openai`, but not explicit LangChain model/tool packages. If Milestone 2 imports LangChain tool/model abstractions directly, add explicit dependencies instead of relying on transitive packages.
- Runtime constraint: production model access remains OpenAI-compatible and environment-driven. Fake/offline mode must keep tests and local smoke runs deterministic.
- Anti-goals: do not replace the Milestone 1 digest graph, do not add OpenClaw, do not implement arXiv/Hugging Face/RSS connectors, do not add vector search or scheduling, and do not require live network calls in default tests.

## File Map

### Subsystem: LLM Tool Usage Layer

| Path | Create/Modify | Responsibility | Public Surface |
| --- | --- | --- | --- |
| `pyproject.toml` | modify | Add explicit LangChain tool/model dependencies needed by Milestone 2 imports | project dependencies |
| `src/ai_news_agent/tools/__init__.py` | create | Package exports for tool registry and tool agent helpers | `build_tool_registry`, `build_tool_agent_runner` |
| `src/ai_news_agent/tools/schemas.py` | create | Shared typed input/output models and JSON-safe serialization for tool observations | tool argument schemas, `ToolObservation` or equivalent |
| `src/ai_news_agent/tools/followup.py` | create | Implement digest-inspection tools over `DigestStore` and `FollowupContext` | `load_latest_digest`, `get_digest_item`, `get_source_trace`, `get_ranking_explanation` |
| `src/ai_news_agent/tools/connectors.py` | create | Implement GitHub/Bilibili connector search tools through `SourceConnector.collect()` | `search_github_ai_news`, `search_bilibili_ai_news` builders |
| `src/ai_news_agent/tools/registry.py` | create | Assemble stable tool names, descriptions, schemas, and dependency injection for store/connectors | `ToolRegistry`, `build_tool_registry()` |
| `src/ai_news_agent/tools/agent.py` | create | Bounded LangGraph tool-calling loop and runner API for follow-up chat | `ToolAgentRunner`, `build_tool_agent_runner()` |
| `src/ai_news_agent/llm.py` | modify | Add a tool-capable chat model factory while preserving current summarization API | `build_tool_chat_model()` or equivalent |
| `src/ai_news_agent/chat.py` | modify | Route open-ended follow-ups and controlled source exploration through the tool agent when configured | `ChatService(..., tool_agent_runner=...)` |
| `src/ai_news_agent/sources.py` | modify | Expose connector construction in a form safe for per-tool-call lifecycle management | connector factory helpers |
| `src/ai_news_agent/app/gradio_app.py` | modify | Build and inject the tool agent for UI follow-up chat without changing digest streaming behavior | `_build_service()` wiring |
| `README.md` | modify | Document Milestone 2 tool usage behavior, fake-mode limits, and example follow-up prompts | user-facing usage notes |
| `tests/test_tools_schemas.py` | create | Validate tool schema defaults, argument validation, and JSON-safe output shape | pytest tests |
| `tests/test_tools_followup.py` | create | Verify follow-up tools return digest, item, source, ranking, warning, and not-found observations | pytest tests |
| `tests/test_tools_connectors.py` | create | Verify connector tools delegate to fake connectors and convert failures to caveats | pytest tests |
| `tests/test_tools_registry.py` | create | Verify stable tool names, descriptions, deduping, and dependency injection | pytest tests |
| `tests/test_tool_agent.py` | create | Verify bounded tool loop behavior with fake tool-calling model and fake tools | pytest tests |
| `tests/test_chat.py` | modify | Add ChatService routing tests for configured tool agent and fallback behavior | pytest tests |
| `tests/test_gradio_app.py` | modify | Verify Gradio service construction still works in fake and model-backed modes | pytest tests |
| `tests/test_mvp_smoke.py` | modify | Add regression that deterministic digest workflow still passes unchanged | pytest tests |

### Future Paths Not In This Plan

| Path | Reason Deferred |
| --- | --- |
| `src/ai_news_agent/adapters/openclaw.py` | Milestone 3 external adapter, after internal tool usage works |
| `src/ai_news_agent/connectors/arxiv.py` | Milestone 4 broader source expansion |
| `src/ai_news_agent/connectors/huggingface.py` | Milestone 4 broader source expansion |
| RSS/blog connector modules | Milestone 4 broader source expansion |
| vector store or semantic memory modules | Milestone 5 or later, only if stored digest volume justifies it |
| database schema migration for tool-call logs | Not required for Milestone 2; application logs are enough unless implementation discovers a durable audit need |

## Blast Radius

| Path | Why Sensitive | Existing Behavior To Preserve | Plan Mode Before Implementation |
| --- | --- | --- | --- |
| `pyproject.toml` | Dependency changes affect all environments and CI | Existing `uv run pytest` and package import behavior | high |
| `src/ai_news_agent/llm.py` | Shared model factory currently powers summarization | `build_chat_model()` and `generate_entry_fields()` contract | high |
| `src/ai_news_agent/chat.py` | Main routing boundary for digest vs follow-up messages | Digest requests still run the deterministic workflow; structured follow-ups still work | high |
| `src/ai_news_agent/sources.py` | Canonical source registry used by CLI, Gradio, and tests | Source names, fake connectors, and validation behavior | high |
| `src/ai_news_agent/app/gradio_app.py` | User-facing UI service construction | Streaming digest progress and fake mode | high |
| `src/ai_news_agent/tools/agent.py` | New agent loop can accidentally create runaway tool calls | Bounded iterations, deterministic tests, clear fallback on failure | high |
| connector wrappers in `src/ai_news_agent/tools/connectors.py` | Touch external API boundaries indirectly | No live network calls in default tests; connector warnings preserved | high |

## Workflow For Implementers

1. Treat this file as the durable source of truth for Milestone 2.
2. For high-priority subtasks, use Cursor Plan mode first to confirm the exact APIs, then Agent mode to implement.
3. For subtasks marked `TDD suitable: yes`, Agent mode must follow the test-driven-development skill: failing test, minimal implementation, refactor.
4. If Plan mode or implementation shows this decomposition is wrong, pause, update this plan, add a changelog entry, then continue.

## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 - Dependencies And Tool Schema Foundation

- [X] **Do:** Add explicit dependencies for the tool-calling implementation and create shared schema/serialization helpers for tool inputs and observations. Keep outputs compact, JSON-safe, and easy for the LLM to quote.
- **TDD suitable:** partial - schema behavior is testable first; dependency metadata is declarative and verified by import/tests.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_schemas.py` and `uv run python -c "from ai_news_agent.tools import build_tool_registry"`
- **Blocked by:** -

### T2 - Follow-Up Inspection Tools

- [X] **Do:** Implement `load_latest_digest`, `get_digest_item`, `get_source_trace`, and `get_ranking_explanation` over `DigestStore.get_latest_followup_context()`. Tools should return structured observations for happy paths, empty store, missing rank/item, and caveat/warning cases.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_followup.py tests/test_storage.py`
- **Blocked by:** T1

### T3 - Connector Tool Wrappers

- [X] **Do:** Implement `search_github_ai_news` and `search_bilibili_ai_news` wrappers that build `ConnectorRequest`, call the selected connector through the existing protocol, serialize `NewsItem`/warnings, and convert connector exceptions into caveat observations.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_connectors.py tests/test_connector_contracts.py`
- **Blocked by:** T1

### T4 - Tool Registry And Connector Lifecycle

- [X] **Do:** Build a registry that exposes stable tool names/descriptions/schemas and injects `DigestStore` plus connector factories. Ensure connector tools can create and close connectors per call when needed, so Gradio does not keep stale network clients alive.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_registry.py tests/test_sources.py`
- **Blocked by:** T2, T3

### T5 - Bounded LangGraph Tool Agent

- [X] **Do:** Create the LangGraph tool-calling runner used by follow-up chat. The runner should bind tools to the model, route model tool calls to a tool execution node, cap tool-call iterations, log tool call start/end/failure, and return a final grounded answer or graceful fallback.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tool_agent.py`
- **Blocked by:** T4

### T6 - Tool-Capable Model Factory

- [ ] **Do:** Add a model factory for Milestone 2 tool calling while preserving the current summarization model contract. Prefer a small new factory over changing `build_chat_model()` behavior in place.
- **TDD suitable:** partial - factory/import behavior is testable; live provider compatibility remains manual or smoke-tested with real credentials.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tool_agent.py tests/test_summarizer.py` and optional manual run with configured `OPENAI_*`
- **Blocked by:** T1, T5

### T7 - ChatService Integration

- [ ] **Do:** Add optional tool-agent injection to `ChatService`. Digest requests still use the deterministic workflow; existing structured follow-ups may remain fast deterministic answers; open-ended follow-ups and source-exploration questions use the tool agent when configured, then fall back to the existing LLM/fallback path.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_chat.py tests/test_streaming.py`
- **Blocked by:** T5

### T8 - Gradio Wiring

- [ ] **Do:** Construct the Milestone 2 tool registry/agent in `_build_service()` and inject it into `ChatService` while preserving streaming digest behavior, source toggles, and fake mode. Fake mode may use a deterministic fake tool agent instead of a real tool-calling model.
- **TDD suitable:** partial - service construction and routing are testable; visual/UI behavior remains a smoke/manual check.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_gradio_app.py tests/test_chat.py`
- **Blocked by:** T6, T7

### T9 - Documentation And Examples

- [ ] **Do:** Update README usage notes with Milestone 2 behavior, example prompts, fake-mode limitations, and the distinction between deterministic digest generation and tool-using follow-up/source exploration.
- **TDD suitable:** no - documentation-only work.
- **Plan mode:** skip
- **Verification:** Review rendered markdown and run `uv run pytest tests/test_mvp_smoke.py`
- **Blocked by:** T7

### T10 - Milestone 2 Regression Sweep

- [ ] **Do:** Run the focused Milestone 2 tests plus the existing MVP regression suite. Fix any plan gaps discovered by integration, updating this plan before continuing if the file map or task order changes.
- **TDD suitable:** no - verification and stabilization pass.
- **Plan mode:** skip
- **Verification:** `uv run pytest`
- **Blocked by:** T8, T9

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-05-21 | Initial Milestone 2 implementation plan for hybrid LLM tool usage layer |
