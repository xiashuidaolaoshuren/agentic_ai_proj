# Milestone 4: Pydantic Schema + LangChain `@tool` Registry and Shared Interface Routing Design

Date: 2026-06-29
Revised: 2026-08-02 — add sub-project 4c shared interface BaseTool routing

## Summary

Milestone 4 modernizes the validation, tool-registration, and interface-routing layers of the AI News Research Agent. It migrates domain and tool schemas from hand-rolled dataclasses to Pydantic v2, migrates the custom registry to LangChain `@tool` objects with Pydantic-derived argument schemas, then routes Gradio and OpenClaw digest and follow-up requests through a shared bounded BaseTool agent.

The digest graph and structured follow-up formatters remain the deterministic implementations of their respective capabilities. The model selects a high-level capability tool; it does not compose, reorder, or replace the digest graph's collection, ranking, summarization, persistence, and rendering stages. Existing Gradio and OpenClaw external contracts remain unchanged.

The milestone is split into three sequenced sub-projects:

- **4a — Pydantic schema migration** (lands first).
- **4b — LangChain `@tool` registry migration** (depends on 4a).
- **4c — Shared interface BaseTool routing** (depends on 4b).

This milestone is inserted ahead of the previously-planned "Broader Research Sources" milestone, which becomes Milestone 5, and "Memory, Scheduling, And Deployment" becomes Milestone 6.

## Motivation

Two problems motivate this milestone.

1. **Dual-schema drift.** Today the JSON Schema shown to the LLM is hand-written in `tools/registry.py`, while runtime argument validation uses a separate dataclass (`SearchQueryInput` in `tools/schemas.py`). The two can drift. Adopting LangChain `@tool` with a Pydantic `args_schema` makes the Pydantic model the single source of truth: the model's JSON Schema is derived from it automatically.

2. **Hand-rolled validation and serialization.** Domain models in `models.py` are dataclasses serialized through a custom `_encode_value` recursive encoder and hand-written `*_to_dict` / `*_from_dict` round-trip helpers with manual enum coercion and datetime decoding. Pydantic v2 handles enum coercion, datetime parsing, nested-model serialization, and JSON-safe dumping natively, removing bespoke code and making validation declarative.

## Scope

### In Scope

- Convert the domain models in `models.py` and the tool schemas in `tools/schemas.py` from dataclasses to Pydantic v2 (`BaseModel` / `StrEnum`), preserving the current field set and validation intent.
- Replace the hand-written domain serialization/validation helpers (`_encode_value`, `_decode_datetime`, and the `*_to_dict` / `*_from_dict` family) with Pydantic's `model_dump(mode="json")` / `model_validate()` at all call sites. Keep `tool_observation_to_dict` private to the custom agent's `ToolMessage` boundary while it requires a JSON payload.
- Migrate the six tool functions to LangChain `@tool`-decorated `BaseTool` objects with Pydantic `args_schema`, built by a factory that injects `DigestStore` and connector factories.
- Replace the custom `ToolDefinition` with LangChain `BaseTool`; keep a thin `ToolRegistry` lookup wrapper over `list[BaseTool]`.
- Update `tools/agent.py` to bind and dispatch `BaseTool` objects while preserving the bounded loop, progress-line streaming, and `ToolObservation` contract for non-terminal research tools.
- Add high-level digest and structured-follow-up BaseTools that delegate to the current deterministic workflow and formatters.
- Route both Gradio and OpenClaw digest and follow-up messages through one shared bounded tool agent in live mode; require the agent to choose at least one BaseTool before returning a result.
- Preserve Gradio UI behavior plus OpenClaw `/digest`, `/followup`, CLI, and HTTP response contracts. On agent-routing failure, use the existing deterministic path for the same request.
- Add an explicit `pydantic>=2.0` dependency.
- Renumber the roadmap: insert this milestone as M4; the previous M4 (broader sources) becomes M5 and the previous M5 (memory/scheduling/deploy) becomes M6.

### Out of Scope

- New source connectors (arXiv, Hugging Face, RSS) — now Milestone 5.
- Scheduled digest execution, long-term memory/vector search, deployment, automated quality evaluation — now Milestone 6.
- Changing the deterministic Milestone 1 digest graph, ranking, summarization, structured-follow-up formatting, or SQLite schema.
- Letting an LLM invoke individual digest stages, create multiple persisted digest runs for one request, or override trusted UI/API request constraints.
- Adopting `langgraph.prebuilt.create_react_agent` or the literal prebuilt `ToolNode` class (see Design Decisions).
- Adding source connectors, memory, scheduling, deployment, or OpenClaw transport changes.

## Design Decisions

Captured during brainstorming:

1. **Schema scope = tool-layer + core domain models.** Both `tools/schemas.py` and `models.py` convert to Pydantic v2.
2. **`@tool` reach = tools + registry only; keep the custom bounded loop.** The loop in `tools/agent.py` (iteration cap, routing, fallback, streaming progress events) is preserved. Tools become `BaseTool` objects; `bind_tools` receives them directly.
3. **Dispatch via `BaseTool.ainvoke`, not the literal `ToolNode` class.** The prebuilt `langgraph.prebuilt.ToolNode` has no pre-invoke hook, so it cannot emit the `"Calling {name}…"` progress line before execution. The custom `tool_node` is retained but dispatches through `BaseTool.ainvoke`, preserving the exact `"Calling…/Done…/Failed…"` stream and the `ToolObservation` type check that tests assert on.
4. **Domain round-trip helpers removed (no-wrapper strategy).** The hand-written domain helpers are deleted; their call sites use `model_dump(mode="json")` / `model_validate()` directly, with no compatibility shim layer. The private `tool_observation_to_dict` function remains only at the custom agent's JSON `ToolMessage` boundary.
5. **One milestone, three sequenced sub-projects, schema-first.** 4a lands before 4b because `@tool` `args_schema` depends on the Pydantic foundation; 4c extends that registry only after the BaseTool boundary is proven.
6. **High-level capability tools, not digest-stage tools.** `generate_ai_news_digest` owns exactly one complete digest graph invocation. Structured tools own one exact follow-up response each. The model selects a capability but does not orchestrate connector collection, ranking, summarization, persistence, or rendering separately.
7. **Agent-first routing with deterministic fallback.** Live Gradio and OpenClaw requests enter a shared bounded agent which must produce a tool call. Model unavailability, timeout, invalid/missing tool calls, an iteration-cap exit without a terminal result, or a tool failure triggers the existing direct deterministic route for that same request. Fake mode uses the deterministic route directly because it intentionally has no live tool-calling model.
8. **Trusted interface context wins.** Gradio session source toggles and OpenClaw's validated request hints are resolved before agent invocation. The digest BaseTool captures that resolved `DigestRequest`; model-generated tool arguments cannot relax, replace, or conflict with those interface constraints.
9. **Exact structured terminal output.** Source lists, rank recommendations, item details, and caveats are returned verbatim from their deterministic formatters. The agent terminates after such a tool result; it does not rewrite it.
10. **Stable transport boundary.** The change is internal to application routing. Gradio rendering, OpenClaw `/digest` and `/followup` response bodies, CLI arguments, correlation IDs, and the persisted digest schema remain compatible.

## Architecture

Gradio and OpenClaw become peers over one shared application-facing tool-agent boundary:

```text
Gradio message ──┐
                 ├─> trusted request/context resolution
OpenClaw request ┘             │
                               v
                     shared bounded BaseTool agent
                      │              │              │
                      v              v              v
        generate_ai_news_digest  structured tools  existing research tools
                      │              │              │
                      v              v              v
           existing digest graph   exact formatter  pure store/connector logic
```

The first two tool families return terminal results. The existing research tools retain their `ToolObservation` loop behavior so the model can inspect observations and, within the iteration cap, make further research calls or compose a grounded answer. The shared runner returns a typed terminal result rather than always only a string; adapters map that result back into their unchanged user-facing contract.

### Sub-project 4a: Pydantic Schema Migration

The domain models (`NewsItem`, `RankedItem`, `DigestEntry`, `Digest`, `ConnectorWarning`) and the tool schemas (`ToolObservation`, `SearchQueryInput`) become Pydantic v2 `BaseModel` types. The `StrEnum` types (`SourceKind`, `FollowUpAction`, `ConfidenceLevel`, `ToolObservationStatus`) are unchanged; Pydantic v2 coerces and serializes them natively, matching the current `_encode_value` behavior. The `BaseModel` config uses `extra="ignore"` to match the current `*_from_dict` behavior of ignoring unknown keys. The current `__post_init__` validation in `ToolObservation` and `SearchQueryInput` is expressed as Pydantic field constraints / validators.

The hand-written domain serialization and validation helpers are removed. Every domain `*_to_dict` call site uses `model_dump(mode="json")`; every domain `*_from_dict` call site uses `model_validate()`. Pydantic's JSON-mode dump produces the same field set and value shapes as `_encode_value` (StrEnum -> value, datetime -> isoformat, nested models -> dict, `None` preserved). `tool_observation_to_dict` remains an internal JSON conversion at the custom agent's `ToolMessage` boundary rather than a package-level public helper.

**Stored-data compatibility (hard constraint):** existing SQLite rows were written by the current `*_to_dict` helpers. Because `model_dump(mode="json")` produces the same field names and semantically identical values, and `model_validate` accepts both `+00:00` and `Z` datetime suffixes, existing rows continue to parse with no SQLite schema migration. The storage round-trip in `storage.py` is the most sensitive call site and must preserve exact read/write compatibility.

New Pydantic args models are introduced for tool inputs: `RankOrSourceArgs` (for the rank/source_id tools) and `SearchArgs` (for the connector search tools). `SearchQueryInput` remains as the internal search-input model used by the connector functions; the LLM-facing `SearchArgs` is converted to it at the tool boundary. Exact field constraints are defined in the implementation plan.

**Behavior change to flag:** validation errors become `pydantic.ValidationError` (a subclass of `ValueError`) with Pydantic message text instead of the custom strings raised today. Tests that assert on those exact messages are updated to assert on the exception type or Pydantic's constraint messages.

### Sub-project 4b: LangChain `@tool` Registry Migration

The six tool functions become LangChain `@tool`-decorated `BaseTool` objects whose `args_schema` is the Pydantic model from 4a. The JSON Schema shown to the LLM is then derived from that model, eliminating the separate hand-written schemas in `tools/registry.py` and the dual-schema drift.

**Pure logic separated from `@tool` wrappers.** The module-level pure functions in `tools/followup.py` and `tools/connectors.py` keep their current injected-deps signatures so they remain directly testable. `build_tool_registry` constructs `@tool` async wrappers inside the factory, capturing `store` and the connector factories via closures. Each wrapper's docstring becomes the tool description and its function name becomes the tool name, preserving the six stable tool names exactly. Per-call connector lifecycle is preserved (factories are called inside the wrapper body on each invocation), and the `get_source_trace` wrapper preserves the current Bilibili env/connector handling.

**Registry.** `ToolDefinition` is removed; LangChain `BaseTool` replaces it. `ToolRegistry` is kept as a thin lookup/dedup wrapper over `list[BaseTool]` so the agent dispatch and tests retain a stable lookup API. `build_tool_registry` remains the public entry, now returning a `BaseTool`-backed registry.

**Agent loop.** `bind_tools` receives the `BaseTool` objects directly. The custom `tool_node` dispatches via `BaseTool.ainvoke` instead of the manual `tool.execute(**args)`. The bounded loop (iteration cap, `route_after_agent`, fallback), the `"Calling/Done/Failed"` progress-line streaming, the `ToolObservation` return-type check, and the JSON-serialized `ToolMessage` content are all preserved. The exact mechanism for returning a `ToolObservation` through `BaseTool.ainvoke` (e.g. `response_format="content_and_artifact"`) is an implementation detail to be confirmed by a failing RED test before adoption, per the project's TDD rule.

### Sub-project 4c: Shared Interface BaseTool Routing

**Capability tool families.** The existing six BaseTools continue to support source search and digest inspection. The registry gains:

- **One digest tool:** `generate_ai_news_digest`, with no model-controlled request parameters. It captures the already-resolved interface request and invokes the existing digest graph once. It returns a typed terminal digest result containing the `DigestResult`, rendered text, run ID, and stage timings.
- **Structured terminal tools:** separate no-argument tools for listing sources, recommending the highest-ranked item, listing caveats, plus an item-detail tool with a validated 1-based rank. Each delegates to the existing structured follow-up logic and returns its exact formatted text and run ID.

Tool descriptions clearly instruct the model to use one terminal capability for every new digest or structured request. The agent does not accept a direct natural-language answer as success: if its first response has no tool calls, the request falls back to the current direct path.

**Shared runner context.** A new application-level factory supplies the tool registry with a per-request context: resolved `DigestRequest`, session-selected sources, OpenClaw validated hints, `DigestStore`, connector factories, workflow runner, interface name, fake/live mode, and correlation ID. The context is injected by closures or an equivalent typed runtime context, never copied into model-editable tool arguments.

**Terminal results.** The runner distinguishes:

- `digest`: a completed `DigestResult` and its rendered text;
- `structured`: exact formatter text and its associated run ID;
- `conversational`: an agent-authored response grounded in `ToolObservation` messages; and
- `fallback`: the result from the pre-existing direct route, annotated internally with the reason the agent route failed.

For terminal digest and structured results, dispatch records the normal `Calling` and `Done` progress lines and ends without another model invocation. This must be implemented in the existing custom runner; `@tool(return_direct=True)` alone is insufficient because the project owns its LangGraph dispatch loop.

**Interface integration.**

- Gradio resolves message intent and session source toggles exactly as today, then calls the shared runner. Its current streaming behavior remains: progress is ephemeral and only the final user-facing text remains in chat history.
- OpenClaw continues to normalize `message`, source, timeframe, topic, output style, and output language hints before execution. `/digest` and `/followup` remain separate external operations but call the same internal runner. Their existing body schema and client CLI output do not change.
- Fake Gradio/OpenClaw runs bypass model selection and execute the direct deterministic path. This preserves offline behavior and avoids pretending that a fake model used live BaseTools.

## Error Handling

- Tool execution exceptions remain caught by the dispatch node and surfaced as `{"error": ...}` with a `"Tool failed …"` progress line — unchanged.
- Invalid tool arguments are validated by `BaseTool.ainvoke` against the Pydantic `args_schema` before the wrapper runs, raising `ValidationError`; caught by the same handler and surfaced as a caveat. Same outcome as today's `SearchQueryInput` rejection, raised earlier.
- Domain model validation errors become `pydantic.ValidationError` (a `ValueError` subclass); existing call sites that catch `ValueError` continue to work.
- The shared agent treats a model timeout or exception, an initial response without a tool call, malformed/unknown calls, a terminal-result type violation, and a cap exit without a qualifying terminal result as routing failures. It logs the reason with the interface and correlation ID, then calls the pre-existing direct digest or structured-follow-up path.
- A terminal digest tool may fail before persistence or after a partial graph failure; the fallback path is invoked only when it is safe to make one direct attempt. The implementation must not run two successful persisted digest graphs for the same request. If completion is ambiguous, return the safe user-facing error and preserve logs for diagnosis rather than retrying.
- The OpenClaw adapter retains its explicit guidance response for an unsupported request only after both the agent and its deterministic structured fallback cannot serve it. It does not expose internal tool payloads or stack traces.

## Testing Strategy

The project enforces TDD in Agent mode. The implementation plan (produced separately via the writing-plans skill) defines the scoped RED/GREEN pairs and the file-by-file changes. TDD suitability by area:

- **4a (TDD suitable: yes):** round-trip parity (`model_dump` -> `model_validate` -> equal), JSON-shape parity vs. the old `*_to_dict` output (guards stored-DB compatibility), and Pydantic validation behavior.
- **4b (TDD suitable: yes for registry/agent; partial for `@tool` wiring):** `args_schema` derivation, six stable tool names, non-empty descriptions, per-call connector-factory invocation, and the dispatch / progress-line / fallback behaviors. The `ToolObservation`-through-`ainvoke` mechanism is verified by a RED test first.
- **4c (TDD suitable: yes):** RED/GREEN tests cover forced first-tool selection, exactly-one graph invocation for the digest terminal tool, trusted request context precedence, exact structured text with no model rewrite, terminal progress lines, bounded research loops, and each routing-failure fallback reason.
- **Interface integration (TDD suitable: partial):** Gradio tests cover live and fake digest/follow-up routing plus streaming; OpenClaw tests cover unchanged `/digest` and `/followup` payloads, CLI behavior, structured hints, and deterministic fallbacks. Use fake tool-call models and injected workflow runners; do not call external LLMs or connectors.
- **Regression sweep:** `uv run pytest` stays green. An optional live run with configured `OPENAI_*` confirms that both Gradio and OpenClaw choose the expected BaseTool while preserving their user-visible output contracts.

## Blast Radius

| Path | Change | Risk |
| --- | --- | --- |
| `src/ai_news_agent/models.py` | dataclasses -> Pydantic; remove helpers | high -- imported by ~30 files |
| `src/ai_news_agent/tools/schemas.py` | -> Pydantic; add args models; remove helpers | high |
| `src/ai_news_agent/tools/registry.py` | existing six `BaseTool`s plus high-level digest/structured capability tools | high |
| `src/ai_news_agent/tools/agent.py` | `bind_tools(BaseTool)`; terminal-result dispatch and bounded research loop | high |
| `src/ai_news_agent/tools/followup.py`, `tools/connectors.py` | serialization call sites; pure logic kept | medium |
| `src/ai_news_agent/storage.py` | round-trip -> `model_dump` / `model_validate` | high -- persistence boundary |
| `src/ai_news_agent/tools/__init__.py` | public surface updated | medium |
| `src/ai_news_agent/chat.py` | route Gradio digest and follow-up messages through shared tool agent; preserve streaming and fallback | high |
| `src/ai_news_agent/app/gradio_app.py` | construct live shared routing dependencies while preserving fake mode and UI behavior | high |
| `src/ai_news_agent/app/digest_service.py` | route OpenClaw `/digest` and `/followup` through shared agent without changing transport contracts | high |
| `src/ai_news_agent/followup_structured.py` | reuse exact formatters behind structured terminal tools | medium |
| `src/ai_news_agent/digest_request_builder.py`, `adapters/openclaw.py` | remain trusted request-normalization boundaries | high |
| `pyproject.toml` | explicit `pydantic>=2.0` | low |
| affected tests (`test_models.py`, `test_tools_*`, `test_tool_agent.py`, `test_summarizer.py`, `test_chat.py`, `test_gradio_app.py`, `test_openclaw_*.py`) | rewritten / adapted | high |
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
- The hand-written domain serialization/validation helpers are removed with no remaining call sites; `tool_observation_to_dict` remains private to the agent's JSON `ToolMessage` boundary.
- Existing SQLite rows from prior milestones still round-trip through `model_validate` / `model_dump(mode="json")` without a schema migration.
- The existing six tool functions plus high-level capability tools are LangChain `BaseTool` objects with Pydantic-derived `args_schema` where they accept arguments; the hand-written JSON Schema dicts in `tools/registry.py` are gone.
- `bind_tools` receives `BaseTool` objects directly; the bounded loop, progress-line streaming, fallback, and `ToolObservation` contract for research tools are preserved.
- Gradio and OpenClaw live requests select at least one shared BaseTool for digest and structured follow-up operations; fake mode uses the direct deterministic route.
- `generate_ai_news_digest` invokes the complete existing graph at most once per request, persists at most one successful digest run, and uses the interface-resolved request without model-controlled overrides.
- Structured terminal tools return the existing exact source, ranking, item-detail, and caveat text with no model rewrite.
- Gradio and OpenClaw external contracts, including OpenClaw `/digest` and `/followup` payloads and CLI output, remain compatible. Agent-routing failures take the matching deterministic fallback.
- `uv run pytest` is green.
- The roadmap is renumbered across the design spec, M1/M2 plans, and `PROPOSAL.md`.
