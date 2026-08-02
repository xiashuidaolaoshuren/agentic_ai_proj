# Implementation Plan: Milestone 4 Pydantic Schema + LangChain `@tool` Registry And Shared Interface Routing

**Spec:** `docs/superpowers/specs/2026-06-29-pydantic-and-langchain-tool-migration-design.md`  
**Created:** 2026-06-30  
**Subsystem scope:** Milestone 4a–4c as one sequenced pass: schema validation, BaseTool registration, then shared Gradio/OpenClaw BaseTool routing

## Summary

Migrate the AI News Research Agent's schema and tool infrastructure, then route live Gradio and OpenClaw digest and follow-up requests through a shared bounded BaseTool agent. Sub-projects 4a and 4b (T1–T8) land Pydantic models and the six research `BaseTool`s. Sub-project 4c (T9+) adds high-level terminal capability tools, typed terminal results, and agent-first interface routing with deterministic fallback while preserving Gradio and OpenClaw external contracts. The digest graph and structured formatters remain the deterministic implementations behind those tools.

## Multi-Subsystem Gate

The spec contains three sequenced sub-projects, but they are not independent subsystems. 4b depends on 4a schemas; 4c depends on the BaseTool registry and agent from 4b and touches the same `tools` plus Gradio/OpenClaw wiring. Produce one type-1 plan with schema-first then routing dependencies instead of splitting into separate specs or plans.

## Discovery Notes

- Reuse: `models.py` already centralizes domain types and JSON conversion helpers; this is the right boundary for the domain Pydantic migration.
- Reuse: `storage.py` already routes persisted news-item JSON through `news_item_to_dict` / `news_item_from_dict`, making storage compatibility testable without changing the SQLite schema.
- Reuse: `tools/followup.py` and `tools/connectors.py` already keep pure tool logic separate from registry wiring; preserve this separation and wrap those functions from `build_tool_registry`.
- Reuse: `ToolAgentRunner` already has the bounded LangGraph loop, iteration cap, progress-line streaming, and fallback behavior. Keep this control flow and change only binding/dispatch to `BaseTool`.
- Reuse (4c): `resolve_digest_request` / `resolve_openclaw_digest_request` remain the trusted request-normalization boundaries; `run_digest` / `run_digest_instrumented` remain the indivisible digest graph; `answer_structured_followup` and its formatters remain the exact structured text source.
- Reuse (4c): Gradio already builds a tool registry and agent for open-ended follow-up; OpenClaw `DigestServiceRuntime` still calls the digest graph and structured follow-up directly — both must share one router without changing HTTP/CLI contracts.
- Constraint: `pyproject.toml` already depends on `langchain-core>=1.0` and `langchain-openai>=0.3`; add `pydantic>=2.0` explicitly rather than relying on transitive dependencies.
- Constraint: LangChain docs support `@tool(args_schema=...)`, Pydantic input models, and binding tool objects to chat models. The exact `ToolObservation` artifact-return mechanism must be confirmed by a RED test before production code.
- Constraint (4c): `@tool(return_direct=True)` alone is insufficient; terminal-result short-circuit must live in the custom `tool_node` / runner because this project owns its LangGraph dispatch loop.
- Constraint (4c): Gradio today routes digest keyword hits before structured follow-up; phrases like `"Digest the first news"` match both `_message_requests_digest()` and structured rank parsing. Plan mode for T12/T13 must lock explicit intent precedence (structured rank/follow-up vs new digest) so Gradio and OpenClaw do not diverge.
- Constraint (4c): OpenClaw `/followup` external `path` values remain `no_digest` / `structured` / `guidance` only. Internal agent/fallback reasons map into that taxonomy; do not leak new path strings in the HTTP contract.
- Constraint (4c): Fake Gradio/OpenClaw must fully bypass model tool selection (direct digest graph + deterministic structured/guidance). Live Gradio may drop `_FakeToolAgentRunner` for capability routing; existing fake open-ended progress tests will need adaptation.
- Constraint (4c): Sync and streaming follow-up paths in `chat.py` currently duplicate structured-before-agent logic; M4c agent-first routing must centralize so sync/streaming cannot drift.
- Constraint: the repository enforces TDD for `TDD suitable: yes` / `partial` subtasks; production edits require a failing scoped test first.
- Anti-goals: do not add source connectors, do not alter the deterministic digest graph, do not change the SQLite schema, do not replace the bounded loop with `create_react_agent`, do not adopt the literal prebuilt `ToolNode`, do not let the model compose digest stages or override trusted UI/API request constraints, and do not change OpenClaw transport schemas.

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

### Subsystem 4c: Shared Interface BaseTool Routing

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/tools/schemas.py` | modify | Add terminal-result types and validated rank args for structured item tools | `InterfaceAgentResult` (or equivalent), path discriminators, `DigestItemRankArgs` |
| `src/ai_news_agent/followup_structured.py` | modify | Expose reusable exact formatters / helpers needed by structured terminal tools without changing response text | existing public APIs plus any formatter helpers tools require |
| `src/ai_news_agent/tools/registry.py` | modify | Register `generate_ai_news_digest` and structured terminal tools beside the six research tools, capturing trusted request/context via closures | `build_tool_registry` (extended deps), new stable tool names |
| `src/ai_news_agent/tools/agent.py` | modify | Require a first tool call; short-circuit after terminal digest/structured results; keep research `ToolObservation` loop; return typed terminal results | `ToolAgentRunner` typed run/stream APIs |
| `src/ai_news_agent/tools/interface_router.py` | create | Shared live-mode router: build per-request agent context, invoke the agent, apply deterministic fallback with reason logging, enforce at-most-one successful digest persist | `InterfaceToolRouter` / `build_interface_tool_router` (names finalized in Plan mode) |
| `src/ai_news_agent/tools/__init__.py` | modify | Export router/result types needed by Gradio and OpenClaw without re-exporting deleted helpers | package exports |
| `src/ai_news_agent/chat.py` | modify | Route live Gradio digest and follow-up messages through the shared router while preserving streaming and fake/direct paths | `ChatService` |
| `src/ai_news_agent/app/gradio_app.py` | modify | Construct live shared-router dependencies; keep fake mode on the direct deterministic path | `_build_service`, app wiring |
| `src/ai_news_agent/app/digest_service.py` | modify | Route live OpenClaw `/digest` and `/followup` through the shared router without changing HTTP body/CLI contracts | `DigestServiceRuntime` |
| `tests/test_tools_schemas.py` | modify | Assert terminal-result and rank-args validation | pytest tests |
| `tests/test_tools_registry.py` | modify | Assert capability tool names, descriptions, trusted-context capture, and exactly-one digest graph invocation | pytest tests |
| `tests/test_tool_agent.py` | modify | Assert first-tool requirement, terminal short-circuit, exact structured text, research-loop preservation | pytest tests |
| `tests/test_interface_router.py` | create | Assert fallback reasons, safe digest retry policy, and interface-agnostic routing outcomes | pytest tests |
| `tests/test_chat.py` | modify | Assert live Gradio routing through shared tools with fake-model stubs; adapt structured-before-agent and fake open-ended expectations | pytest tests |
| `tests/test_gradio_app.py` | modify | Assert live vs fake construction and streaming contracts; fake bypasses capability-agent selection | pytest tests |
| `tests/test_digest_service.py`, `tests/test_digest_service_parity.py` | modify | Assert live OpenClaw service routing stubs; fake parity with CLI digest remains | pytest tests |
| `tests/test_openclaw_adapter.py`, `tests/test_openclaw_followup.py`, `tests/test_openclaw_client.py`, `tests/test_openclaw_targeted.py` | modify | Assert unchanged OpenClaw contracts with live router stubs, stable `path` taxonomy, and deterministic fallbacks | pytest tests |

### Future Paths Not In This Plan

| Path | Reason Deferred |
| --- | --- |
| `src/ai_news_agent/connectors/arxiv.py` | Milestone 5 broader source expansion |
| `src/ai_news_agent/connectors/huggingface.py` | Milestone 5 broader source expansion |
| RSS/blog connector modules | Milestone 5 broader source expansion |
| scheduler, memory, vector search, deployment modules | Milestone 6 |
| SQLite schema migration | Not required; existing row compatibility must be preserved |
| `langgraph.prebuilt.create_react_agent` / literal prebuilt `ToolNode` adoption | Out of scope; current bounded loop semantics must remain stable |
| OpenClaw skill/transport redesign | Out of scope; preserve `/digest`, `/followup`, and CLI contracts |

## Blast Radius

| Path | Why Sensitive | Existing Behavior To Preserve | Plan Mode Before Implementation |
| --- | --- | --- | --- |
| `src/ai_news_agent/models.py` | Shared domain contract imported by connectors, ranking, storage, summarizer, rendering, and tests | Field names, enum values, defaults, equality semantics practical for tests, JSON shapes | high |
| `src/ai_news_agent/storage.py` | Persistence boundary for saved digests and follow-up context | Existing SQLite schema and existing JSON rows continue to read/write | high |
| `src/ai_news_agent/tools/schemas.py` | Shared LLM-facing observation/input and terminal-result contracts | `ToolObservation` envelope plus new typed terminal results | high |
| `src/ai_news_agent/tools/registry.py` | Tool names/descriptions/schemas are model-facing public behavior | Six research tools remain; capability tools must not expose model-editable digest request overrides | high |
| `src/ai_news_agent/tools/agent.py` | Bounded tool loop can regress into runaway calls, rewritten structured text, or broken streaming | Iteration cap, `Calling/Done/Failed` progress lines, research `ToolObservation` JSON payloads, terminal short-circuit | high |
| `src/ai_news_agent/tools/interface_router.py` | Shared Gradio/OpenClaw routing and fallback policy | At-most-one successful digest persist; external contracts unchanged | high |
| `src/ai_news_agent/chat.py` | Gradio digest vs follow-up routing and streaming | Session source toggles, ephemeral progress, fake/direct path | high |
| `src/ai_news_agent/app/gradio_app.py` | Live service construction | Fake mode bypasses model selection | high |
| `src/ai_news_agent/app/digest_service.py` | OpenClaw warm HTTP surface | `/digest` and `/followup` bodies, correlation IDs, CLI clients | high |
| `src/ai_news_agent/followup_structured.py` | Exact structured reply text used by OpenClaw and Gradio | Formatter wording and guidance fallback semantics | medium |
| `src/ai_news_agent/digest_request_builder.py`, `adapters/openclaw.py` | Trusted request normalization | Interface hints win over model tool arguments | high |
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

- [X] **Do:** Update package exports and any downstream import sites to remove deleted helpers and expose the new schema/registry public surface. Keep ChatService and Gradio construction behavior stable, and use existing integration tests as smoke coverage unless Plan mode discovers a required test update.
- **TDD suitable:** partial - import/export cleanup is mostly mechanical, but integration behavior is testable first through package import and existing chat/UI construction tests.
- **Plan mode:** medium
- **Verification:** `uv run pytest tests/test_chat.py tests/test_gradio_app.py tests/test_tools_schemas.py tests/test_tool_agent.py -q`
- **Blocked by:** T5, T6

### T8 - Milestone 4 Regression Sweep

- [X] **Do:** Run the focused M4 tests and the full suite. If regressions expose a plan gap, update this plan before fixing; if a real behavior bug is discovered, add a failing test first where feasible.
- **TDD suitable:** no - verification/stabilization pass; any discovered code fix should be handled with TDD in the relevant earlier subtask.
- **Plan mode:** skip
- **Verification:** `uv run pytest`
- **Blocked by:** T7

### T9 - Terminal Result Types And Structured Rank Args

- [X] **Do:** Add typed terminal-result models for digest, structured, conversational, and fallback outcomes, plus validated rank args for the structured item-detail tool. Keep research `ToolObservation` unchanged.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_schemas.py -q`
- **Blocked by:** T8

### T10 - High-Level Digest And Structured Capability Tools

- [X] **Do:** Extend the registry with `generate_ai_news_digest` (no model-controlled request parameters; captures trusted resolved `DigestRequest` and invokes the existing digest graph once) and structured terminal tools for sources, ranking recommendation, caveats, and item detail by rank. Reuse exact formatters from `followup_structured.py` without changing wording. Preserve the six research tools.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tools_registry.py tests/test_tools_followup.py -q`
- **Blocked by:** T9

### T11 - Agent Terminal Dispatch And Typed Runner API

- [ ] **Do:** Update the bounded agent so a first response without tool calls is a routing failure, terminal digest/structured tool results short-circuit without another model rewrite, research tools keep the `ToolObservation` loop and progress lines, and the runner returns typed terminal results rather than only a bare string.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_tool_agent.py -q`
- **Blocked by:** T10

### T12 - Shared Interface Router With Deterministic Fallback

- [ ] **Do:** Create the shared live-mode interface router that builds per-request trusted context, invokes the typed tool agent, logs fallback reasons (model failure, missing first tool call, malformed/unknown call, terminal-type violation, unsafe/ambiguous digest completion, cap exit without terminal result), and applies the existing direct deterministic path when safe. Enforce at-most-one successful persisted digest for a single user request. Lock Gradio/OpenClaw-shared intent precedence for ambiguous phrases (e.g. structured rank vs new digest) and map internal outcomes to interface-facing result shapes without changing transport contracts.
- **TDD suitable:** yes
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_interface_router.py -q`
- **Blocked by:** T11

### T13 - Gradio ChatService Live Shared Routing

- [ ] **Do:** Wire live Gradio/`ChatService` digest and follow-up messages through the shared router while preserving session source toggles, ephemeral progress streaming, and fake-mode direct deterministic behavior (full agent bypass; adapt or remove `_FakeToolAgentRunner` open-ended fake progress expectations). Centralize sync and streaming so they cannot drift.
- **TDD suitable:** partial - routing and streaming contracts are testable with fake tool-call models; visual Gradio UX remains a smoke/manual check.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_chat.py tests/test_gradio_app.py -q`
- **Blocked by:** T12

### T14 - OpenClaw Digest Service Live Shared Routing

- [ ] **Do:** Wire live OpenClaw `/digest` and `/followup` through the shared router while preserving request normalization, response bodies (`text`/`run_id`/`correlation_id`/`elapsed_s`/`stages` for digest; `text`/`run_id`/`path`/`correlation_id` for follow-up with `path` limited to `no_digest`/`structured`/`guidance`), CLI client behavior, and post-fallback guidance text for unsupported follow-ups. Keep fake service mode on the current direct paths.
- **TDD suitable:** partial - service routing and contract assertions are testable with stubs; live channel UX remains optional smoke.
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_digest_service.py tests/test_digest_service_parity.py tests/test_openclaw_adapter.py tests/test_openclaw_followup.py tests/test_openclaw_client.py tests/test_openclaw_targeted.py -q`
- **Blocked by:** T12

### T15 - Milestone 4c Regression Sweep

- [ ] **Do:** Run the focused 4c tests and the full suite. If regressions expose a plan gap, update this plan before fixing; if a real behavior bug is discovered, add a failing test first where feasible.
- **TDD suitable:** no - verification/stabilization pass; any discovered code fix should be handled with TDD in the relevant earlier subtask.
- **Plan mode:** skip
- **Verification:** `uv run pytest`
- **Blocked by:** T13, T14

## Acceptance Checklist

- Domain and tool schemas are Pydantic v2 models where specified by the spec.
- Deleted domain serialization helpers have no remaining production or test call sites; `tool_observation_to_dict` remains private to the agent's JSON `ToolMessage` boundary.
- Existing SQLite row payloads remain readable without a schema migration.
- Tool schemas shown to the LLM are derived from Pydantic args models.
- The registry exposes the six research `BaseTool`s plus high-level digest and structured capability tools.
- The bounded agent preserves research-tool progress streaming and `ToolObservation` payloads, short-circuits terminal capability results without model rewrite, and requires a first tool call in live mode.
- Live Gradio and OpenClaw digest/follow-up requests route through the shared BaseTool agent; fake mode uses the direct deterministic path.
- `generate_ai_news_digest` invokes the existing graph at most once per request and cannot override trusted interface request constraints.
- Structured terminal tools return existing exact formatter text.
- Gradio and OpenClaw external contracts remain compatible; agent-routing failures take the matching deterministic fallback when safe.
- Focused tests and the full test suite pass.

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-06-30 | Initial type-1 plan for Milestone 4a + 4b from approved Pydantic/tool migration spec |
| 2026-07-01 | T1 planning: add `connectors/github_juya.py` and `tests/test_connectors_github_juya.py` to file map and blast radius (`dataclasses.replace(NewsItem)` call site) |
| 2026-08-02 | Append 4c after T8: shared Gradio/OpenClaw BaseTool routing (T9–T15), file map, blast radius, and acceptance updates from revised M4 spec |
| 2026-08-02 | Fold Gradio/OpenClaw routing discovery into 4c constraints: digest-vs-structured intent precedence, OpenClaw `path` taxonomy, fake bypass, sync/streaming centralization; expand T12–T14 and digest-service tests |
