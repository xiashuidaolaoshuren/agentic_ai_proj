# Implementation Plan: Milestone 4 Pydantic Schema + LangChain `@tool` Registry Migration

**Spec:** `docs/superpowers/specs/2026-06-29-pydantic-and-langchain-tool-migration-design.md`  
**Created:** 2026-06-30  
**Subsystem scope:** Milestone 4a and 4b together: internal schema validation and LLM tool registration modernization

## Summary

Migrate the AI News Research Agent's schema and tool infrastructure in one coherent implementation pass. First, replace dataclass-based domain/tool schemas and hand-written JSON helpers with Pydantic v2. Then, use those Pydantic schemas as LangChain `@tool` argument schemas and replace the custom `ToolDefinition` registry with a `BaseTool`-backed registry. The digest graph, bounded tool loop semantics, streaming progress lines, and SQLite schema remain behaviorally unchanged.

## Multi-Subsystem Gate

The spec contains two sub-projects, but they are not independent subsystems. The `@tool` migration depends on the Pydantic args models from 4a, and both changes touch the same `tools` boundary. Produce one type-1 plan with schema-first dependencies instead of splitting into separate specs or plans.

## Discovery Notes

- Reuse: `models.py` already centralizes domain types and JSON conversion helpers; this is the right boundary for the domain Pydantic migration.
- Reuse: `storage.py` already routes persisted news-item JSON through `news_item_to_dict` / `news_item_from_dict`, making storage compatibility testable without changing the SQLite schema.
- Reuse: `tools/followup.py` and `tools/connectors.py` already keep pure tool logic separate from registry wiring; preserve this separation and wrap those functions from `build_tool_registry`.
- Reuse: `ToolAgentRunner` already has the bounded LangGraph loop, iteration cap, progress-line streaming, and fallback behavior. Keep this control flow and change only binding/dispatch to `BaseTool`.
- Constraint: `pyproject.toml` already depends on `langchain-core>=1.0` and `langchain-openai>=0.3`; add `pydantic>=2.0` explicitly rather than relying on transitive dependencies.
- Constraint: LangChain docs support `@tool(args_schema=...)`, Pydantic input models, and binding tool objects to chat models. The exact `ToolObservation` artifact-return mechanism must be confirmed by a RED test before production code.
- Constraint: the repository enforces TDD for `TDD suitable: yes` / `partial` subtasks; production edits require a failing scoped test first.
- Anti-goals: do not add source connectors, do not alter the deterministic digest graph, do not change the SQLite schema, do not replace the bounded loop with `create_react_agent`, and do not adopt the literal prebuilt `ToolNode`.

## File Map

### Subsystem 4a: Pydantic Schema Migration

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `pyproject.toml` | modify | Declare Pydantic as an explicit project dependency | project dependency metadata |
| `src/ai_news_agent/models.py` | modify | Convert domain dataclasses to Pydantic models and remove hand-written JSON helpers | `SourceKind`, `FollowUpAction`, `ConfidenceLevel`, `NewsItem`, `RankedItem`, `DigestEntry`, `Digest`, `ConnectorWarning`, `utcnow` |
| `src/ai_news_agent/storage.py` | modify | Preserve SQLite read/write compatibility while using Pydantic JSON-mode dumps and validation | `DigestStore`, `FollowupContext` |
| `src/ai_news_agent/tools/schemas.py` | modify | Convert tool observations/search inputs to Pydantic and add LLM-facing args models | `ToolObservationStatus`, `ToolObservation`, `SearchQueryInput`, `RankOrSourceArgs`, `SearchArgs` |
| `src/ai_news_agent/tools/followup.py` | modify | Keep follow-up pure tool logic; serialize domain/tool models with Pydantic | `load_latest_digest`, `get_digest_item`, `get_source_trace`, `get_ranking_explanation` |
| `src/ai_news_agent/tools/connectors.py` | modify | Keep connector pure tool logic; serialize domain/tool models with Pydantic | `search_github_ai_news`, `search_bilibili_ai_news` |
| `src/ai_news_agent/tools/agent.py` | modify | Serialize `ToolObservation` payloads with Pydantic during tool dispatch | `ToolAgentRunner`, `build_tool_agent_runner` |
| `tests/test_models.py` | modify | Assert Pydantic domain model parity, validation, and JSON shape compatibility | pytest tests |
| `tests/test_storage.py` | modify | Assert storage round trips and legacy JSON payload compatibility | pytest tests |
| `tests/test_tools_schemas.py` | modify | Assert Pydantic tool schema defaults, validation, and JSON-safe dumping | pytest tests |
| `tests/test_tools_followup.py` | modify | Assert follow-up observations remain JSON-safe and behaviorally unchanged | pytest tests |
| `tests/test_tools_connectors.py` | modify | Assert connector tool observations remain JSON-safe and behaviorally unchanged | pytest tests |
| `tests/test_summarizer.py` | modify | Update digest round-trip expectations from removed helpers to Pydantic validation | pytest tests |
| `src/ai_news_agent/connectors/github_juya.py` | modify | Replace `dataclasses.replace(NewsItem, ...)` with `NewsItem.model_copy(update=...)` after T1 Pydantic migration | article-enrichment path on `NewsItem` |
| `tests/test_connectors_github_juya.py` | modify | Assert markdown-enrichment still updates `NewsItem` fields after `model_copy` swap | pytest tests |

### Subsystem 4b: LangChain `@tool` Registry Migration

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/tools/registry.py` | modify | Build injected LangChain `BaseTool` objects and expose a thin lookup registry | `ConnectorFactory`, `ToolRegistry`, `build_tool_registry` |
| `src/ai_news_agent/tools/agent.py` | modify | Bind `BaseTool` objects and dispatch via `BaseTool.ainvoke` while preserving the bounded loop | `ToolAgentRunner`, `ToolCallModel`, `build_tool_agent_runner` |
| `src/ai_news_agent/tools/__init__.py` | modify | Export the new public tool/schema surface and remove deleted helper exports | package exports |
| `tests/test_tools_registry.py` | modify | Assert `BaseTool` registry behavior, stable names, descriptions, dedupe, and injected lifecycle | pytest tests |
| `tests/test_tool_agent.py` | modify | Assert `BaseTool` binding/dispatch preserves direct answers, tool progress, failures, and caps | pytest tests |

### Future Paths Not In This Plan

| Path | Reason Deferred |
| --- | --- |
| `src/ai_news_agent/connectors/arxiv.py` | Milestone 5 broader source expansion |
| `src/ai_news_agent/connectors/huggingface.py` | Milestone 5 broader source expansion |
| RSS/blog connector modules | Milestone 5 broader source expansion |
| scheduler, memory, vector search, deployment modules | Milestone 6 |
| SQLite schema migration | Not required; existing row compatibility must be preserved |
| `langgraph.prebuilt.create_react_agent` / literal prebuilt `ToolNode` adoption | Out of scope; current bounded loop semantics must remain stable |

## Blast Radius

| Path | Why Sensitive | Existing Behavior To Preserve | Plan Mode Before Implementation |
| --- | --- | --- | --- |
| `src/ai_news_agent/models.py` | Shared domain contract imported by connectors, ranking, storage, summarizer, rendering, and tests | Field names, enum values, defaults, equality semantics practical for tests, JSON shapes | high |
| `src/ai_news_agent/storage.py` | Persistence boundary for saved digests and follow-up context | Existing SQLite schema and existing JSON rows continue to read/write | high |
| `src/ai_news_agent/tools/schemas.py` | Shared LLM-facing observation/input contract | `ToolObservation` status/summary/data/caveats envelope and validation intent | high |
| `src/ai_news_agent/tools/registry.py` | Tool names/descriptions/schemas are model-facing public behavior | Six stable tool names, dependency injection, per-call connector factories | high |
| `src/ai_news_agent/tools/agent.py` | Bounded tool loop can regress into runaway calls or broken streaming | Iteration cap, fallback, `Calling/Done/Failed` progress lines, JSON `ToolMessage` payloads | high |
| `src/ai_news_agent/tools/__init__.py` | Package-level imports are used by tests and app wiring | Stable exports for kept public APIs; removed helpers fail only after call sites are updated | medium |
| `pyproject.toml` | Dependency metadata affects every environment and CI run | Existing install/test behavior and Python version support | medium |
| `src/ai_news_agent/connectors/github_juya.py` | Uses `dataclasses.replace()` on `NewsItem`; breaks when domain models become Pydantic `BaseModel` | Article-enrichment path still updates `raw_snippet`, `content_confidence`, `metadata_completeness`, and `tags` | high |

## Workflow For Implementers

1. Treat this file as the durable type-1 source of truth for Milestone 4.
2. Use Cursor Plan mode with the `planning-subtasks` skill for subtasks marked `Plan mode: high` or `medium` before Agent-mode implementation.
3. For subtasks marked `TDD suitable: yes` or `partial`, Agent mode must follow the test-driven-development skill: scoped RED test first, one-behavior GREEN, then refactor.
4. If Plan mode or implementation shows this decomposition is wrong, pause, update this plan and append a changelog entry before continuing.

## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is complete.

### T1 - Domain Model Pydantic Foundation

- [X] **Do:** Add the explicit Pydantic dependency and migrate `models.py` domain models to Pydantic while preserving field names, defaults, enum values, JSON shape, and existing row compatibility expectations. Remove domain helper functions only after tests prove equivalent Pydantic dump/validate behavior.
- **TDD suitable:** partial - domain model behavior and helper-removal parity are testable first; dependency metadata is declarative and verified by import/tests.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_models.py -q` and `uv run python -c "from ai_news_agent.models import NewsItem, Digest"`
- **Blocked by:** -

### T2 - Storage Round-Trip Migration

- [X] **Do:** Update `DigestStore` persistence paths to use Pydantic dump/validation while preserving the SQLite schema and existing serialized payload compatibility. Add or update tests that prove old-style JSON payloads still load.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_storage.py tests/test_models.py -q`
- **Blocked by:** T1

### T3 - Tool Schema Pydantic Foundation

- [X] **Do:** Convert `ToolObservation` and `SearchQueryInput` to Pydantic, add the LLM-facing args models needed for registry tools, and remove tool serialization helper APIs after call sites are ready. Preserve the observation envelope and validation intent.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_schemas.py -q`
- **Blocked by:** T1

### T4 - Pure Tool Observation Serialization Migration

- [X] **Do:** Update the pure follow-up and connector tool modules to use Pydantic JSON-mode dumps for domain objects and `ToolObservation` payloads, while keeping their injected-dependency function signatures directly testable.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_followup.py tests/test_tools_connectors.py -q`
- **Blocked by:** T2, T3

### T5 - BaseTool Registry And `@tool` Wrappers

- [X] **Do:** Replace `ToolDefinition` and hand-written JSON schemas with LangChain `@tool` wrappers using Pydantic `args_schema`, while keeping a thin `ToolRegistry` lookup/dedup API and preserving six stable tool names/descriptions plus per-call connector factory behavior.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_registry.py tests/test_tools_connectors.py -q`
- **Blocked by:** T3, T4

### T6 - Bounded Agent BaseTool Dispatch

- [X] **Do:** Update the bounded tool agent to bind `BaseTool` objects directly and dispatch via `BaseTool.ainvoke`, preserving iteration caps, fallback behavior, progress-line streaming, failure handling, and JSON `ToolMessage` content.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tool_agent.py -q`
- **Blocked by:** T5

### T7 - Public Surface And Integration Smoke

- [ ] **Do:** Update package exports and any downstream import sites to remove deleted helpers and expose the new schema/registry public surface. Keep ChatService and Gradio construction behavior stable, and use existing integration tests as smoke coverage unless Plan mode discovers a required test update.
- **TDD suitable:** partial - import/export cleanup is mostly mechanical, but integration behavior is testable first through package import and existing chat/UI construction tests.
- **Plan mode:** medium
- **Verification:** `uv run pytest tests/test_chat.py tests/test_gradio_app.py tests/test_tools_schemas.py tests/test_tool_agent.py -q`
- **Blocked by:** T5, T6

### T8 - Milestone 4 Regression Sweep

- [ ] **Do:** Run the focused M4 tests and the full suite. If regressions expose a plan gap, update this plan before fixing; if a real behavior bug is discovered, add a failing test first where feasible.
- **TDD suitable:** no - verification/stabilization pass; any discovered code fix should be handled with TDD in the relevant earlier subtask.
- **Plan mode:** skip
- **Verification:** `uv run pytest`
- **Blocked by:** T7

## Acceptance Checklist

- Domain and tool schemas are Pydantic v2 models where specified by the spec.
- Deleted serialization helpers have no remaining production or test call sites.
- Existing SQLite row payloads remain readable without a schema migration.
- Tool schemas shown to the LLM are derived from Pydantic args models.
- The registry exposes six stable `BaseTool`-backed tools with the same names and descriptions.
- The bounded agent loop preserves progress streaming, fallback behavior, and `ToolObservation` JSON payloads.
- Focused tests and the full test suite pass.

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-06-30 | Initial type-1 plan for Milestone 4a + 4b from approved Pydantic/tool migration spec |
| 2026-07-01 | T1 planning: add `connectors/github_juya.py` and `tests/test_connectors_github_juya.py` to file map and blast radius (`dataclasses.replace(NewsItem)` call site) |
