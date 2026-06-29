# Milestone 4: Pydantic Schema + LangChain `@tool` Registry Migration Design

Date: 2026-06-29

## Summary

Milestone 4 modernizes the internal validation and tooling layer of the AI News Research Agent. It migrates the domain models and tool schemas from hand-rolled dataclasses with custom serialization to Pydantic v2, and migrates the custom tool registry to LangChain's `@tool` decorator workflow with Pydantic-derived argument schemas. The deterministic digest workflow (Milestone 1), the bounded tool-calling loop behavior (Milestone 2), and the OpenClaw adapter (Milestone 3) remain behaviorally unchanged.

The milestone is split into two sequenced sub-projects:

- **4a — Pydantic schema migration** (lands first).
- **4b — LangChain `@tool` registry migration** (depends on 4a).

This milestone is inserted ahead of the previously-planned "Broader Research Sources" milestone, which becomes Milestone 5, and "Memory, Scheduling, And Deployment" becomes Milestone 6.

## Motivation

Two problems motivate this milestone.

1. **Dual-schema drift.** Today the JSON Schema shown to the LLM is hand-written in `tools/registry.py`, while runtime argument validation uses a separate dataclass (`SearchQueryInput` in `tools/schemas.py`). The two can drift. Adopting LangChain `@tool` with a Pydantic `args_schema` makes the Pydantic model the single source of truth: the model's JSON Schema is derived from it automatically.

2. **Hand-rolled validation and serialization.** Domain models in `models.py` are dataclasses serialized through a custom `_encode_value` recursive encoder and hand-written `*_to_dict` / `*_from_dict` round-trip helpers with manual enum coercion and datetime decoding. Pydantic v2 handles enum coercion, datetime parsing, nested-model serialization, and JSON-safe dumping natively, removing bespoke code and making validation declarative.

## Scope

### In Scope

- Convert the domain models in `models.py` and the tool schemas in `tools/schemas.py` from dataclasses to Pydantic v2 (`BaseModel` / `StrEnum`), preserving the current field set and validation intent.
- Replace the hand-written serialization/validation helpers (`_encode_value`, `_decode_datetime`, the `*_to_dict` / `*_from_dict` family, `encode_tool_value`, `tool_observation_to_dict`) with Pydantic's `model_dump(mode="json")` / `model_validate()` at all call sites.
- Migrate the six tool functions to LangChain `@tool`-decorated `BaseTool` objects with Pydantic `args_schema`, built by a factory that injects `DigestStore` and connector factories.
- Replace the custom `ToolDefinition` with LangChain `BaseTool`; keep a thin `ToolRegistry` lookup wrapper over `list[BaseTool]`.
- Update `tools/agent.py` to bind and dispatch `BaseTool` objects while preserving the bounded loop, progress-line streaming, and `ToolObservation` return contract.
- Add an explicit `pydantic>=2.0` dependency.
- Renumber the roadmap: insert this milestone as M4; the previous M4 (broader sources) becomes M5 and the previous M5 (memory/scheduling/deploy) becomes M6.

### Out of Scope

- New source connectors (arXiv, Hugging Face, RSS) — now Milestone 5.
- Scheduled digest execution, long-term memory/vector search, deployment, automated quality evaluation — now Milestone 6.
- Changing the deterministic Milestone 1 digest graph, ranking, summarization, or SQLite schema.
- Changing the bounded tool-calling loop control flow (iteration cap, routing, fallback, streaming event shape).
- Adopting `langgraph.prebuilt.create_react_agent` or the literal prebuilt `ToolNode` class (see Design Decisions).
- Converting the OpenClaw adapter or any non-`models.py` / non-`tools` module to Pydantic beyond the call-site updates required by the helper removal.

## Design Decisions

Captured during brainstorming:

1. **Schema scope = tool-layer + core domain models.** Both `tools/schemas.py` and `models.py` convert to Pydantic v2.
2. **`@tool` reach = tools + registry only; keep the custom bounded loop.** The loop in `tools/agent.py` (iteration cap, routing, fallback, streaming progress events) is preserved. Tools become `BaseTool` objects; `bind_tools` receives them directly.
3. **Dispatch via `BaseTool.ainvoke`, not the literal `ToolNode` class.** The prebuilt `langgraph.prebuilt.ToolNode` has no pre-invoke hook, so it cannot emit the `"Calling {name}…"` progress line before execution. The custom `tool_node` is retained but dispatches through `BaseTool.ainvoke`, preserving the exact `"Calling…/Done…/Failed…"` stream and the `ToolObservation` type check that tests assert on.
4. **Round-trip helpers removed (no-wrapper strategy).** The hand-written helpers are deleted; call sites use `model_dump(mode="json")` / `model_validate()` directly, with no compatibility shim layer.
5. **One milestone, two sequenced sub-projects, schema-first.** 4a lands before 4b because `@tool` `args_schema` depends on the Pydantic foundation.

## Architecture

No runtime topology changes. The digest LangGraph, the bounded tool-calling LangGraph, storage, connectors, ranking, summarization, rendering, and the OpenClaw adapter all keep their current shape. The change is internal to the validation / serialization / tool-registration layer.

### Sub-project 4a: Pydantic Schema Migration

The domain models (`NewsItem`, `RankedItem`, `DigestEntry`, `Digest`, `ConnectorWarning`) and the tool schemas (`ToolObservation`, `SearchQueryInput`) become Pydantic v2 `BaseModel` types. The `StrEnum` types (`SourceKind`, `FollowUpAction`, `ConfidenceLevel`, `ToolObservationStatus`) are unchanged; Pydantic v2 coerces and serializes them natively, matching the current `_encode_value` behavior. The `BaseModel` config uses `extra="ignore"` to match the current `*_from_dict` behavior of ignoring unknown keys. The current `__post_init__` validation in `ToolObservation` and `SearchQueryInput` is expressed as Pydantic field constraints / validators.

The hand-written serialization and validation helpers are removed. Every `*_to_dict` call site uses `model_dump(mode="json")`; every `*_from_dict` call site uses `model_validate()`. Pydantic's JSON-mode dump produces the same field set and value shapes as `_encode_value` (StrEnum -> value, datetime -> isoformat, nested models -> dict, `None` preserved).

**Stored-data compatibility (hard constraint):** existing SQLite rows were written by the current `*_to_dict` helpers. Because `model_dump(mode="json")` produces the same field names and semantically identical values, and `model_validate` accepts both `+00:00` and `Z` datetime suffixes, existing rows continue to parse with no SQLite schema migration. The storage round-trip in `storage.py` is the most sensitive call site and must preserve exact read/write compatibility.

New Pydantic args models are introduced for tool inputs: `RankOrSourceArgs` (for the rank/source_id tools) and `SearchArgs` (for the connector search tools). `SearchQueryInput` remains as the internal search-input model used by the connector functions; the LLM-facing `SearchArgs` is converted to it at the tool boundary. Exact field constraints are defined in the implementation plan.

**Behavior change to flag:** validation errors become `pydantic.ValidationError` (a subclass of `ValueError`) with Pydantic message text instead of the custom strings raised today. Tests that assert on those exact messages are updated to assert on the exception type or Pydantic's constraint messages.

### Sub-project 4b: LangChain `@tool` Registry Migration

The six tool functions become LangChain `@tool`-decorated `BaseTool` objects whose `args_schema` is the Pydantic model from 4a. The JSON Schema shown to the LLM is then derived from that model, eliminating the separate hand-written schemas in `tools/registry.py` and the dual-schema drift.

**Pure logic separated from `@tool` wrappers.** The module-level pure functions in `tools/followup.py` and `tools/connectors.py` keep their current injected-deps signatures so they remain directly testable. `build_tool_registry` constructs `@tool` async wrappers inside the factory, capturing `store` and the connector factories via closures. Each wrapper's docstring becomes the tool description and its function name becomes the tool name, preserving the six stable tool names exactly. Per-call connector lifecycle is preserved (factories are called inside the wrapper body on each invocation), and the `get_source_trace` wrapper preserves the current Bilibili env/connector handling.

**Registry.** `ToolDefinition` is removed; LangChain `BaseTool` replaces it. `ToolRegistry` is kept as a thin lookup/dedup wrapper over `list[BaseTool]` so the agent dispatch and tests retain a stable lookup API. `build_tool_registry` remains the public entry, now returning a `BaseTool`-backed registry.

**Agent loop.** `bind_tools` receives the `BaseTool` objects directly. The custom `tool_node` dispatches via `BaseTool.ainvoke` instead of the manual `tool.execute(**args)`. The bounded loop (iteration cap, `route_after_agent`, fallback), the `"Calling/Done/Failed"` progress-line streaming, the `ToolObservation` return-type check, and the JSON-serialized `ToolMessage` content are all preserved. The exact mechanism for returning a `ToolObservation` through `BaseTool.ainvoke` (e.g. `response_format="content_and_artifact"`) is an implementation detail to be confirmed by a failing RED test before adoption, per the project's TDD rule.

## Error Handling

- Tool execution exceptions remain caught by the dispatch node and surfaced as `{"error": ...}` with a `"Tool failed …"` progress line — unchanged.
- Invalid tool arguments are validated by `BaseTool.ainvoke` against the Pydantic `args_schema` before the wrapper runs, raising `ValidationError`; caught by the same handler and surfaced as a caveat. Same outcome as today's `SearchQueryInput` rejection, raised earlier.
- Domain model validation errors become `pydantic.ValidationError` (a `ValueError` subclass); existing call sites that catch `ValueError` continue to work.

## Testing Strategy

The project enforces TDD in Agent mode. The implementation plan (produced separately via the writing-plans skill) defines the scoped RED/GREEN pairs and the file-by-file changes. TDD suitability by area:

- **4a (TDD suitable: yes):** round-trip parity (`model_dump` -> `model_validate` -> equal), JSON-shape parity vs. the old `*_to_dict` output (guards stored-DB compatibility), and Pydantic validation behavior.
- **4b (TDD suitable: yes for registry/agent; partial for `@tool` wiring):** `args_schema` derivation, six stable tool names, non-empty descriptions, per-call connector-factory invocation, and the dispatch / progress-line / fallback behaviors. The `ToolObservation`-through-`ainvoke` mechanism is verified by a RED test first.
- **Regression sweep:** `uv run pytest` stays green; the deterministic digest graph and tool-agent routing remain behaviorally unchanged. An optional live run with configured `OPENAI_*` confirms end-to-end tool-calling through Gradio follow-up chat.

## Blast Radius

| Path | Change | Risk |
| --- | --- | --- |
| `src/ai_news_agent/models.py` | dataclasses -> Pydantic; remove helpers | high -- imported by ~30 files |
| `src/ai_news_agent/tools/schemas.py` | -> Pydantic; add args models; remove helpers | high |
| `src/ai_news_agent/tools/registry.py` | `ToolDefinition` removed; `ToolRegistry` over `BaseTool`; `@tool` wrappers | high |
| `src/ai_news_agent/tools/agent.py` | `bind_tools(BaseTool)`; `BaseTool.ainvoke` dispatch; loop preserved | high |
| `src/ai_news_agent/tools/followup.py`, `tools/connectors.py` | serialization call sites; pure logic kept | medium |
| `src/ai_news_agent/storage.py` | round-trip -> `model_dump` / `model_validate` | high -- persistence boundary |
| `src/ai_news_agent/tools/__init__.py` | public surface updated | medium |
| `pyproject.toml` | explicit `pydantic>=2.0` | low |
| affected tests (`test_models.py`, `test_tools_*`, `test_tool_agent.py`, `test_summarizer.py`) | rewritten / adapted | medium |
| design spec, M1/M2 plans, `PROPOSAL.md` | milestone renumbering + cross-refs | low |

## Roadmap Impact

The authoritative roadmap in `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md` is amended:

| New # | Title | Old # |
| --- | --- | --- |
| M4 | Pydantic Schema + LangChain `@tool` Registry Migration | (new) |
| M5 | Broader Research Sources | M4 |
| M6 | Memory, Scheduling, And Deployment | M5 |

Cross-references in the M1 plan, the M2 plan, and `PROPOSAL.md` are aligned to the new numbering.

## Acceptance Criteria

- All domain models in `models.py` and all schemas in `tools/schemas.py` are Pydantic v2 `BaseModel` / `StrEnum`.
- The hand-written serialization/validation helpers are removed with no remaining call sites.
- Existing SQLite rows from prior milestones still round-trip through `model_validate` / `model_dump(mode="json")` without a schema migration.
- The six tool functions are LangChain `BaseTool` objects with Pydantic-derived `args_schema`; the hand-written JSON Schema dicts in `tools/registry.py` are gone.
- `bind_tools` receives `BaseTool` objects directly; the bounded loop, progress-line streaming, fallback, and `ToolObservation` contract are preserved.
- `uv run pytest` is green; digest generation and follow-up tool-agent routing are behaviorally unchanged.
- The roadmap is renumbered across the design spec, M1/M2 plans, and `PROPOSAL.md`.
