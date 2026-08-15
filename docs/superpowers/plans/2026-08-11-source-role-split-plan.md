# Implementation Plan: Milestone 5 Source Role Split

**Spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**ADR:** `docs/adr/0001-source-role-split.md`  
**Created:** 2026-08-11  
**Subsystem scope:** Milestone 5 only — make Juya a first-class default bulletin, make GitHub an opt-in trending-repository signal, preserve Bilibili as opt-in video discovery, and make mixed-source selection, ranking, and rendering source-kind aware.

## Summary

Milestone 5 removes the accidental coupling in which `GitHubConnector` owns Juya website RSS/markdown ingestion and Juya items are persisted as `SourceKind.GITHUB`. It creates a dedicated Juya connector, changes bare digests to Juya-only, makes user source selection explicit and target-aware, reorients GitHub repository search toward a transparent stars-and-recency momentum heuristic, and renders intentionally mixed digests in source sections rather than one interleaved list.

This is a behavior-changing refactor. Existing GitHub repository targeting, Bilibili targeting, persistence, tool-loop contracts, Gradio streaming, OpenClaw transport contracts, and Juya issue follow-up must remain reliable while their source identity and default routing change.

## Multi-Subsystem Gate

The milestone changes connector collection, source selection, ranking/rendering, and interface/tool wiring. These are sequenced parts of one source-selection subsystem rather than independently shippable projects:

1. Juya cannot become the default until it has its own `SourceKind`, connector, and registry entry.
2. Intent and interface defaults require the registry’s canonical names.
3. Mixed-digest rendering requires the selected source kinds and primary-intent information produced by selection.
4. Tool wrappers and live interface constructors must use the same registry/factories or the new source role split will drift by entrypoint.

Use one type-1 plan with the dependencies below. Create a type-2 plan in Cursor Plan mode before each `Plan mode: high` task.

## Discovery Notes

- Reuse: `connectors/github_juya.py` already contains website-RSS parsing, markdown enrichment, canonical URL helpers, and stable Juya source IDs. Move/rehome this behavior behind a dedicated `JuyaConnector`; do not reimplement feed parsing.
- Reuse: `SourceConnector`, `ConnectorRequest`, `ConnectorResult`, `sources.py`, and `build_connectors()` are the established connector boundary used by CLI, Gradio, OpenClaw, tools, and tests.
- Reuse: `DigestRequest` → `graph/nodes/parse.py` is the existing user-request-to-connector-request boundary. New Juya targeting belongs there, not in a connector-specific interface workaround.
- Reuse: `rank_items()`, `order_selected_for_digest()`, `summarize_ranked_items()`, and renderer functions provide the current score/order/render chain. Preserve persisted `RankedItem` evidence and digest-entry order.
- Reuse: `build_tool_registry()` keeps pure connector search functions separate from LangChain `@tool` registration. Extend that pattern with Juya rather than adding a tool-only collection path.
- Reuse: Gradio and `DigestServiceRuntime` already obtain connectors through the source registry and pass a trusted `DigestRequest` to the interface router; source-role logic must remain in shared request resolution rather than model tool arguments.
- Constraints: `NewsItem.source` / `DigestEntry.source_kind` and `DigestStore` JSON round trips are shared persistence contracts. Existing saved GitHub-tagged Juya records must continue to load; this milestone does not rewrite historical rows.
- Constraints: `DigestRequest.connector_names=None` currently means “all injected connectors” in several direct workflow paths. Replace this behavior deliberately at all entrypoints so a bare user request becomes Juya-only without making injected connector lists silently override selection.
- Constraints: GitHub repository search exposes current `stargazers_count`, not historical star deltas. Describe its result as a transparent momentum heuristic; never claim “stars gained in N days.”
- Constraints: The approved kind-aware-scoring choice does not introduce quotas. `top_n` remains an overall digest cap; source sections organize the selected rows without promising one section per source.
- Constraints: A Juya-only digest may retain default topic metadata for traceability, but the Juya connector must not turn those topics into an RSS search filter.
- Constraints: OpenClaw `/digest` and `/followup` request/response schemas, follow-up `path` taxonomy, fake-mode deterministic operation, and at-most-one digest persist must remain unchanged.
- Anti-goals: do not add arXiv, Hugging Face, generic RSS, web search, true star-velocity storage, release-as-primary items, transcript enrichment, storage schema migrations, or a generic source-policy engine.

## File Map

### Subsystem A: Canonical Juya source and source registry

| Path | Create/Modify/Delete | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/models.py` | modify | Add the distinct Juya source enum value without changing common item fields | `SourceKind.JUYA` |
| `src/ai_news_agent/connectors/base.py` | modify | Carry Juya-specific targeting without overloading GitHub selectors | `ConnectorRequest.juya_manual_urls` (name finalized in Plan mode) |
| `src/ai_news_agent/connectors/juya.py` | create | Own Juya RSS collection, website-target recognition, markdown enrichment, warnings, and lifecycle | `JuyaConnector`, canonical URL helpers needed by intent/follow-up |
| `src/ai_news_agent/connectors/github_juya.py` | delete or rename into `juya.py` | Remove GitHub ownership from Juya-specific implementation while preserving tested RSS/markdown behavior | no `github_*` Juya public surface remains |
| `src/ai_news_agent/connectors/github.py` | modify | Remove Juya URL detection and RSS delegation; retain only GitHub repository collection | `GitHubConnector` repository-only contract |
| `src/ai_news_agent/sources.py` | modify | Register Juya, set the Juya-only default, and add a deterministic fake Juya connector | `ALLOWED_SOURCES`, `DEFAULT_SOURCE_NAMES`, `FakeJuyaConnector`, connector factories |
| `src/ai_news_agent/connectors/__init__.py` | modify if exports are maintained | Export the dedicated connector consistently | connector package exports |
| `src/ai_news_agent/juya_followup.py` | modify | Recognize `SourceKind.JUYA` as the authoritative Juya identity while retaining tag/URL detection for historical saved rows | `is_juya_news_item` |
| `tests/test_models.py` | modify | Prove Juya enum/model serialization compatibility | pytest tests |
| `tests/test_connectors_juya.py` | create (from focused existing tests) | Prove dedicated Juya collection and `SourceKind.JUYA` output | pytest tests |
| `tests/test_connectors_github.py` | modify | Prove GitHub no longer routes Juya website/legacy URLs into RSS ingestion | pytest tests |
| `tests/test_sources.py` | modify | Prove default/allowed registry and fake/factory behavior include Juya | pytest tests |
| `tests/test_juya_followup.py`, `tests/test_juya_editorial.py` | modify | Prove current Juya rows use the new source identity and historical persisted evidence remains eligible for deep dives/editorial output | pytest tests |
| `tests/test_connectors_github_juya.py` | delete or rename | Remove obsolete GitHub-owned Juya test identity | no stale test module |

### Subsystem B: Request intent, selection, and entrypoint defaults

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/request.py` | modify | Represent Juya target input and selected/primary source information needed downstream | `DigestRequest` source-selection fields/helpers |
| `src/ai_news_agent/intent.py` | modify | Parse explicit Juya URLs, source names, platform targets, GitHub momentum intent, and the rejected legacy Juya GitHub alias | `parse_digest_intent`, `parse_connector_names_from_message` (or renamed explicit-source parser) |
| `src/ai_news_agent/digest_request_builder.py` | modify | Apply the approved precedence: explicit source list/intent/target replaces bare Juya default unless Juya is explicitly included | `resolve_digest_request` |
| `src/ai_news_agent/adapters/openclaw.py` | modify | Apply identical source defaults, target inference, selector consistency, and legacy-alias failure for OpenClaw hints/messages | `resolve_openclaw_digest_request`, hint/argv builders |
| `src/ai_news_agent/cli.py` | modify | Make CLI help and omitted `--sources` use Juya-only defaults | digest/openclaw CLI parser and request builders |
| `src/ai_news_agent/graph/nodes/parse.py` | modify | Map new Juya request fields into `ConnectorRequest` without changing Bilibili/GitHub mappings | `parse_request_node` |
| `src/ai_news_agent/graph/nodes/collect.py` | modify if required | Enforce the resolved source set even when callers inject multiple connectors | `make_collect_sources_node` behavior |
| `src/ai_news_agent/graph/nodes/persist_render.py` | modify | Persist resolved connector names consistently for default and explicitly selected runs | `_connector_names_for_run` |
| `tests/test_intent.py` | modify | Cover Juya default/target, explicit source parsing, trend intent, replacement semantics, and alias rejection | pytest tests |
| `tests/test_workflow.py` | modify | Cover request mapping, selected-connector filtering, persistence connector names, and unchanged graph errors | pytest tests |
| `tests/test_cli.py` | modify | Cover Juya default CLI parsing/help and named-source validation | pytest tests |
| `tests/test_openclaw_adapter.py`, `tests/test_openclaw_targeted.py` | modify | Cover default hints, website-only Juya targeting, target replacement, and explicit legacy guidance | pytest tests |

### Subsystem C: GitHub momentum, kind-aware ranking, and segmented digest output

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/connectors/github.py` | modify | Make topic discovery rank candidate repositories as current momentum using stars plus activity/recentness; keep manual repo/org targeting as GitHub repository behavior | GitHub query construction and normalized repo metadata |
| `src/ai_news_agent/ranking.py` | modify | Score GitHub, Juya, and Bilibili with source-kind-aware factors while retaining inspectable `score_breakdown` and existing dedupe guarantees | `rank_items`, `order_selected_for_digest` |
| `src/ai_news_agent/summarizer.py` | modify | Preserve source-kind display names and order selected entries by the resolved section order | `summarize_ranked_items` |
| `src/ai_news_agent/rendering.py` | modify | Render mixed digests into source sections; preserve single-source Markdown/text/editorial output as appropriate | Markdown/text/editorial renderers |
| `src/ai_news_agent/graph/nodes/rank.py` | modify only if request primary source/order must be forwarded | Carry source-selection context into rank/order operations without adding model-controlled behavior | rank-node contract |
| `src/ai_news_agent/graph/nodes/persist_render.py` | modify | Pass resolved primary/fallback source order to rendering while preserving existing custom-renderer injection | render-node contract |
| `tests/test_connectors_github.py` | modify | Assert GitHub topic requests and returned items expose the documented momentum inputs without claiming star deltas | pytest tests |
| `tests/test_ranking.py` | modify | Assert kind-specific score evidence, overall-cap selection without quotas, Juya behavior, preserved Bilibili newest guarantee, and deterministic selected ordering | pytest tests |
| `tests/test_summarizer.py` | modify | Assert Juya display name and requested section ordering reach entries | pytest tests |
| `tests/test_rendering.py` | modify | Assert intent-first sections, fallback Juya → GitHub → Bilibili, omitted empty sections, and unchanged one-source output | pytest tests |

### Subsystem D: Tool registry and interface consumption

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/tools/connectors.py` | modify | Add pure Juya search through the shared connector request/result boundary | `search_juya_ai_news` |
| `src/ai_news_agent/tools/registry.py` | modify | Inject/register the Juya tool factory beside GitHub and Bilibili; preserve existing tool names and terminal-routing protections | `build_tool_registry` extended dependency surface |
| `src/ai_news_agent/tools/__init__.py` | modify if needed | Export the new tool surface consistently | package exports |
| `src/ai_news_agent/tools/interface_router.py` | modify if constructor forwards connector factories | Pass the Juya factory through per-request registry construction without allowing the model to override resolved sources | interface-router dependency wiring |
| `src/ai_news_agent/app/gradio_app.py` | modify | Make default source toggles, examples, validation message, factories, and trusted request routing match the shared Juya default | `_build_service`, `create_app`, examples |
| `src/ai_news_agent/app/digest_service.py` | modify | Build defaults and live/fake connector sets through the shared Juya-aware registry | `DigestServiceRuntime`, request payload behavior |
| `tests/test_tools_connectors.py`, `tests/test_tools_registry.py` | modify | Assert Juya pure tool delegation, JSON-safe observations, registration, and factory lifecycle | pytest tests |
| `tests/test_interface_router.py` | modify if wiring is explicit | Assert per-request Juya factory availability and unchanged trusted request behavior | pytest tests |
| `tests/test_gradio_app.py` | modify | Assert Juya default toggle/options and target replacement through chat | pytest tests |
| `tests/test_digest_service.py`, `tests/test_digest_service_parity.py` | modify | Assert fake/live runtime defaults and unchanged HTTP contracts | pytest tests |
| `tests/test_mvp_smoke.py` | modify | Keep a deterministic end-to-end fake source-selection smoke test | pytest tests |

### Subsystem E: Documentation and acceptance evidence

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `README.md` | modify | Document source roles, Juya default, all valid source names, website-only Juya command, legacy alias failure, and updated smoke commands | user-facing setup/usage |
| `docs/benchmarks/openclaw-latency-baseline.md` | modify | Keep benchmark commands accurate while clearly separating a historical baseline from new expected source defaults | reproducible benchmark notes |
| `docs/superpowers/plans/2026-08-11-source-role-split-plan.md` | modify during execution only if discovery invalidates scope/order | Remain authoritative type-1 plan | this plan |

## Future Paths Not In This Plan

| Path / capability | Reason deferred |
| --- | --- |
| `src/ai_news_agent/connectors/arxiv.py` | Milestone 6 broader research sources |
| `src/ai_news_agent/connectors/huggingface.py` | Milestone 6 broader research sources |
| generic RSS/blog connector modules | Milestone 6; Juya remains dedicated rather than becoming the generic RSS template now |
| star-history persistence, trending API integration, or precise star-delta | No historical data source exists in the current connector; ADR explicitly defers true velocity |
| GitHub release collection as primary item | ADR makes releases later optional enrichment |
| transcript enrichment / new Bilibili content strategy | Separate future capability |
| SQLite migration for historical GitHub-tagged Juya records | New rows use `juya`; old serialized rows remain readable for compatibility |
| generic policy engine / LLM-controlled source selection | Source rules remain deterministic and trusted at request normalization |

## Blast Radius

| Path / boundary | Why sensitive | Existing behavior to preserve | Plan mode |
| --- | --- | --- | --- |
| `models.py`, `storage.py`, persisted `NewsItem` JSON | `SourceKind` is stored and read throughout ranking, follow-up, and traces | Existing `github`/`bilibili` rows load; no SQLite migration; new Juya rows persist as `juya` | high |
| `sources.py`, `request.py`, `digest_request_builder.py`, `intent.py` | Defines all default and target-driven collection choices | Clear explicit source lists still work; invalid/contradictory requests give actionable errors; no hidden all-connectors fallback | high |
| `connectors/github.py`, new Juya connector | Network boundaries with retry/warning contracts and a major source split | GitHub repo/manual/org paths remain repository-only; Juya retains RSS→markdown fallback and warning taxonomy | high |
| `ranking.py`, `summarizer.py`, `rendering.py` | Changes digest selection/order visible to users and saved follow-up ranks | Dedupe, score evidence, Bilibili newest-in-window guarantee, and single-source rendering remain deterministic | high |
| `tools/registry.py`, `tools/interface_router.py` | Model-facing stable tool names and protected request context | Existing tools, bounded loop, terminal short-circuit, and no model override of trusted source selection | high |
| Gradio, CLI, OpenClaw service/adapter | Public UI/CLI/HTTP behavior and fake-mode smoke path | HTTP schemas, follow-up paths, streaming, lifecycle closing, and safe argv remain unchanged | high |
| README/benchmark commands | Users currently see the obsolete Juya GitHub alias | Documentation teaches website-only Juya and new default without leaving stale runnable commands | medium |

## Workflow For Implementers

1. This plan is the durable type-1 source of truth for Milestone 5. Create a focused type-2 plan before every task marked `Plan mode: high`.
2. Honor strict TDD for every task tagged `TDD suitable: yes`: test-only RED, scoped failing test run, explicit `RED` status, one behavior per production GREEN, scoped passing run, explicit `GREEN` status.
3. Preserve consumer behavior while moving modules: use tests at public boundaries (`SourceConnector`, `DigestRequest`, renderer output, CLI/HTTP payloads), not tests of import location alone.
4. When a type-2 plan establishes a new module such as `connectors/juya.py`, start its first GREEN with the smallest public stub required by that test; do not move network logic, registry wiring, and intent routing in one GREEN.
5. If source-selection semantics, section headers/order, or the GitHub formula cannot be fixed from the ADR/spec and existing contracts, stop and update this plan with the resolved decision before implementation.

## Subtasks

### T1 — Establish Juya as a first-class connector

- [X] **Do:** Add `SourceKind.JUYA`, move Juya RSS/markdown behavior from GitHub ownership into a dedicated `JuyaConnector`, and ensure collected bulletin rows use connector `"juya"` and `SourceKind.JUYA`. Update Juya follow-up detection to prefer that source kind while retaining tag/URL compatibility for historical rows. Delete/rename the GitHub-named helper module and tests once callers move. Remove Juya delegation from `GitHubConnector`; its existing normal repository URL/org behavior remains.
- **TDD suitable:** yes — new connector API, source identity, and regression-sensitive network/warning behavior have clear mocked inputs and outputs.
- **Verification:** `uv run pytest tests/test_models.py tests/test_connectors_juya.py tests/test_connectors_github.py tests/test_sources.py tests/test_juya_followup.py tests/test_juya_editorial.py -q`
- **Dependencies:** none
- **Plan mode:** high

### T2 — Register Juya and make the runtime default deterministic

- [X] **Do:** Add real/fake Juya factories and `"juya"` to the canonical registry; make its ordered default source set Juya-only. Ensure CLI, direct workflow construction, persistence metadata, and connector lifecycle use the resolved set rather than treating omitted source selection as “all injected connectors.”
- **TDD suitable:** yes — registry/default selection and fake end-to-end behavior are deterministic contracts.
- **Verification:** `uv run pytest tests/test_sources.py tests/test_cli.py tests/test_workflow.py tests/test_mvp_smoke.py -q`
- **Dependencies:** T1
- **Plan mode:** high

### T3 — Implement deterministic source intent and target selection

- [X] **Do:** Give `DigestRequest`/`ConnectorRequest` a Juya target representation and carry it through parsing. Implement the approved selection precedence consistently in chat/Gradio, CLI, and OpenClaw: bare request → Juya; explicit source list, clear GitHub trending-repo/Bilibili intent, or platform target → implied/named sources; platform cue replaces Juya unless Juya is also selected. Accept only `daily.juya.uk` as a Juya URL and reject `github.com/jujuyaya/juya-ai-daily` with actionable website guidance. Preserve source-selector conflict validation and record a primary source for mixed-digest section order.
- **TDD suitable:** yes — parser and normalization behavior are deterministic public inputs/outputs, including errors.
- **Verification:** `uv run pytest tests/test_intent.py tests/test_workflow.py tests/test_cli.py tests/test_openclaw_adapter.py tests/test_openclaw_targeted.py -q`
- **Dependencies:** T2
- **Plan mode:** high

### T4 — Re-purpose GitHub collection as a transparent trending-repo signal

- [X] **Do:** Keep GitHub manual repo/org collection available as opt-in ecosystem targeting, but change topic discovery and ranking inputs to prioritize repositories by the documented stars-and-recent-activity momentum heuristic. Keep README text as evidence only, preserve warning/error handling, and expose inspectable ranking factors without claiming historical star velocity.
- **TDD suitable:** yes — query construction, candidate ordering/metadata, and score evidence are deterministic under mocked GitHub payloads.
- **Verification:** `uv run pytest tests/test_connectors_github.py tests/test_ranking.py -q`
- **Dependencies:** T1
- **Plan mode:** high

### T5 — Add kind-aware ranking and source-section digest presentation

- [X] **Do:** Apply source-kind-aware score factors for Juya issues, GitHub trending repos, and Bilibili videos while retaining shared dedupe and the newest-in-window Bilibili guarantee. Keep `top_n` as the existing overall cap (no source quotas). For an intentionally mixed digest, order selected entries and render them in source sections: primary intent first, otherwise Juya → GitHub → Bilibili, omitting empty sections. Keep one-source default Markdown/text/editorial output stable except for correct Juya labeling.
- **TDD suitable:** yes — scoring evidence, ordering, and rendered section structure have deterministic contracts.
- **Verification:** `uv run pytest tests/test_ranking.py tests/test_summarizer.py tests/test_rendering.py tests/test_workflow.py -q`
- **Dependencies:** T1, T3, T4
- **Plan mode:** high

### T6 — Expose Juya through connector tools and shared live interfaces

- [X] **Do:** Add a pure `search_juya_ai_news` wrapper and register it with injected Juya factories. Thread the factory/default source set through the interface router, Gradio, and OpenClaw runtime so all live and fake entrypoints use the same source roles. Update Gradio source toggles, examples, and user-facing validation for Juya; retain the existing tool-loop, streaming, HTTP, and follow-up contracts.
- **TDD suitable:** yes — tool delegation/JSON output, registry dependencies, and interface request wiring are testable contracts.
- **Verification:** `uv run pytest tests/test_tools_connectors.py tests/test_tools_registry.py tests/test_interface_router.py tests/test_gradio_app.py tests/test_digest_service.py tests/test_digest_service_parity.py tests/test_mvp_smoke.py -q`
- **Dependencies:** T2, T3, T5
- **Plan mode:** high

### T7 — Update usage and benchmark documentation

- [ ] **Do:** Replace obsolete GitHub/Bilibili-default and Juya GitHub-alias claims in user-facing commands, source lists, examples, and baseline notes. Document Juya-only bare defaults, explicit/mixed source options, website-only Juya targeting, the expected legacy-alias error, and the difference between current GitHub momentum heuristic and true velocity.
- **TDD suitable:** no — static documentation only; no runtime behavior.
- **Verification:** review `git diff --check`; run every changed fake CLI command where practical; confirm no repository documentation still presents `jujuyaya/juya-ai-daily` as a valid Juya command.
- **Dependencies:** T2, T3, T4, T5, T6
- **Plan mode:** skip

### T8 — Run milestone-level regression and acceptance checks

- [ ] **Do:** Run the full automated suite and focused fake/manual acceptance paths after all behavior and documentation changes. Update this plan’s changelog if verification exposes a missing file, a changed external contract, or a required follow-up subtask.
- **TDD suitable:** no — verification-only integration pass; production behavior was already driven test-first in T1–T6.
- **Verification:** `uv run pytest -q`; fake CLI bare digest; fake CLI explicit `--sources github,bilibili`; fake OpenClaw/HTTP bare request; targeted `https://daily.juya.uk/`; legacy URL rejection; a mixed-source render with intent-first section order.
- **Dependencies:** T1, T2, T3, T4, T5, T6, T7
- **Plan mode:** medium

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-08-11 | Created from the accepted source-role ADR and updated Milestone 5 design spec. |
| 2026-08-11 | Added source-kind-aware Juya follow-up compatibility and fixed mixed-digest selection to the existing overall `top_n` cap (no quotas). |
