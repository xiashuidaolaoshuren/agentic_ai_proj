# Implementation Plan: Milestone 6 AI Ecosystem And Practitioner Signals

**Spec:** `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`  
**Parent spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**ADR:** `docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md`  
**Created:** 2026-08-16  
**Subsystem scope:** Milestone 6 only — add opt-in Hugging Face trending-model and Zhihu practitioner-insight connectors, preserve Juya-only defaults, and make kind-aware ranking, rendering, tools, and live interfaces source-role aware for the two new kinds.

## Summary

Milestone 6 ships two distinct opt-in source jobs through the existing digest pipeline: Hugging Face as Hub-native **trending models** (global or topic/task-filtered), and Zhihu as official-search **practitioner insights** (deterministic 实战/踩坑, 部署/成本, 评测/对比 lenses). Bare digests remain Juya-only. Mixed digests keep one overall `top_n` with no quotas and sectional order intent-first, else Juya → Hugging Face → GitHub → Zhihu → Bilibili.

This is a behavior-changing expansion. Existing Juya, GitHub, and Bilibili collection, ranking evidence, Bilibili newest-in-window selection, tool-loop contracts, Gradio streaming, OpenClaw transport schemas, follow-up path taxonomy, and at-most-one digest persist must remain reliable.

arXiv, generic RSS, Hugging Face datasets/Spaces, Zhihu hotlist/direct-answer/page crawl, source quotas, and storage migrations are out of scope.

## Multi-Subsystem Gate

The milestone changes the shared item contract, two new connectors, source selection, ranking/rendering, and interface/tool wiring. These are sequenced parts of one source-expansion subsystem rather than independently shippable projects:

1. Connectors cannot persist honestly until `SourceKind` and `source_evidence` exist.
2. Registry/defaults cannot expose names until both connectors (and fakes) exist.
3. Intent and mixed-digest rendering require the registry’s canonical names and kind-aware scores.
4. Tool wrappers and live interface constructors must use the same registry/factories or the new source roles will drift by entrypoint.

Use one type-1 plan with the dependencies below. Create a type-2 plan in Cursor Plan mode before each `Plan mode: high` task.

## Discovery Notes

- Reuse: `SourceConnector`, `ConnectorRequest`, `ConnectorResult`, `sources.py`, and `build_connectors()` are the established connector boundary used by CLI, Gradio, OpenClaw, tools, and tests.
- Reuse: GitHub is the reference non-article connector (warning taxonomy, optional auth, mocked httpx tests, README-as-evidence not story). Hugging Face and Zhihu should follow that *pattern*, not GitHub’s stars/recency formula or `stars_or_views`.
- Reuse: `DigestRequest` → `graph/nodes/parse.py` is the user-request-to-connector-request boundary. Hugging Face discovery mode belongs there, not in a tool-only workaround.
- Reuse: `rank_items()`, `order_selected_for_digest()`, `summarize_ranked_items()`, and renderer `_SECTION_LABELS` provide the current score/order/render chain. Preserve persisted `RankedItem` evidence, Bilibili newest-in-window, and single-source rendering.
- Reuse: `build_tool_registry()` keeps pure connector search functions separate from LangChain `@tool` registration. Extend that pattern; do not add a tool-only collection path.
- Reuse: Gradio and `DigestServiceRuntime` obtain connectors through the source registry and pass a trusted `DigestRequest` to the interface router. Source-role logic stays in shared request resolution; the model cannot override resolved sources.
- Constraints: `NewsItem` currently uses `model_config extra="ignore"` and has no `source_evidence`. Add a JSON-safe mapping with an empty default so historical rows—including GitHub-tagged Juya records—load without a SQLite migration.
- Constraints: `ALLOWED_SOURCES` and `DEFAULT_SOURCE_NAMES` are currently `{"juya", "github", "bilibili"}` and `("juya",)`. Adding names must not change the Juya-only default. Tests still use `"arxiv"` as an unknown-source sentinel; keep arXiv unknown.
- Constraints: `intent.py` regexes only recognize `{juya, github, bilibili}`. Hugging Face intent must distinguish **global** trending from **topic/task-filtered** trending. Zhihu intent means practitioner lessons/trade-offs, not generic Chinese web search.
- Constraints: Hugging Face Hub exposes `list_models` sort `trending_score`, 30-day `downloads`, `likes`, `last_modified`, `pipeline_tag`, and `trending_score`. Do not claim model quality or adoption velocity from cumulative counters.
- Constraints: Zhihu official search (`api_id=zhihu_search`, payload `Query`/`Count`) returns title, URL, snippet, source label, and relevance. It does not provide a trustworthy trend or freshness contract. Cap lens expansion to three search calls. Never fetch linked pages.
- Constraints: The approved mixed-digest policy does not introduce quotas. `top_n` remains an overall digest cap.
- Constraints: OpenClaw `/digest` and `/followup` request/response schemas, follow-up `path` taxonomy, fake-mode deterministic operation, existing tool names, and at-most-one digest persist must remain unchanged.
- Constraints: `huggingface_hub` is not yet a project dependency. Add it with the Hugging Face connector. Zhihu should use the existing `httpx` stack unless type-2 planning finds an official SDK that matches the documented search contract.
- Anti-goals: do not add arXiv, generic RSS, datasets/Spaces, Zhihu hotlist/direct-answer/crawl, LLM-generated queries, LLM-as-judge ranking, source quotas, true star-velocity, release-as-primary, transcript enrichment, storage schema migrations, or a generic source-policy engine.

## File Map

### Subsystem A: Shared item contract

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/models.py` | modify | Add Hugging Face and Zhihu kinds plus JSON-safe source-native evidence without breaking existing fields | `SourceKind.HUGGINGFACE`, `SourceKind.ZHIHU`, `NewsItem.source_evidence` |
| `src/ai_news_agent/storage.py` | modify only if dump/load helpers need an explicit default | Persist `source_evidence` through existing JSON round trips; no schema migration | `DigestStore` item JSON compatibility |
| `tests/test_models.py` | modify | Prove new kinds serialize and missing `source_evidence` defaults to `{}` | pytest tests |
| `tests/test_storage.py` | modify | Prove historical items without `source_evidence` still load; new items persist the mapping | pytest tests |

### Subsystem B: Hugging Face trending-model connector

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `pyproject.toml` | modify | Add `huggingface_hub` for official Hub listing | package dependency |
| `src/ai_news_agent/connectors/base.py` | modify | Carry Hugging Face discovery mode without overloading GitHub selectors | `ConnectorRequest` Hugging Face field(s); name finalized in Plan mode |
| `src/ai_news_agent/connectors/huggingface.py` | create | Own Hub `list_models` collection, global vs topic/task trending, model-only mapping, warnings, and lifecycle | `HuggingFaceConnector` |
| `src/ai_news_agent/connectors/__init__.py` | modify | Export the dedicated connector consistently | connector package exports |
| `tests/fixtures/huggingface_models_sample.json` | create | Stable mocked Hub list payload | test fixture |
| `tests/test_connectors_huggingface.py` | create | Prove mapping, dual discovery, malformed rows, rate-limit/search failures, missing trend evidence, and no dataset/Space rows | pytest tests |
| `tests/test_connectors_huggingface_live.py` | create only if opt-in live smoke is warranted | Optional live Hub listing behind `RUN_LIVE_HUGGINGFACE` | marked live tests |

### Subsystem C: Zhihu practitioner-insight connector

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/connectors/zhihu.py` | create | Own official search calls, deterministic lens expansion (max three calls), URL/id dedupe, thin-evidence confidence, timeframe caveat, and no page fetch | `ZhihuConnector`, lens helpers needed by tests |
| `src/ai_news_agent/env.py` | modify | Load documented Zhihu credentials the same way as other optional connector secrets | env helpers / names finalized in Plan mode |
| `.env.example` | modify | Document Zhihu (and Hugging Face token) env names without secrets | env var names |
| `src/ai_news_agent/connectors/__init__.py` | modify | Export `ZhihuConnector` | connector package exports |
| `tests/fixtures/zhihu_search_sample.json` | create | Stable mocked official search payload | test fixture |
| `tests/test_connectors_zhihu.py` | create | Prove lens expansion cap, dedupe, thin results, auth/quota/malformed warnings, unsupported-timeframe caveat, and that linked pages are not fetched | pytest tests |
| `tests/test_connectors_zhihu_live.py` | create only if opt-in live smoke is warranted | Optional live search behind `RUN_LIVE_ZHIHU` | marked live tests |

### Subsystem D: Registry, fakes, and request mapping

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/sources.py` | modify | Register Hugging Face and Zhihu, keep Juya-only default, add deterministic fakes | `ALLOWED_SOURCES`, `DEFAULT_SOURCE_NAMES`, `FakeHuggingFaceConnector`, `FakeZhihuConnector`, factories |
| `src/ai_news_agent/request.py` | modify | Represent Hugging Face discovery mode and any Zhihu-specific request fields needed downstream | `DigestRequest` fields/helpers |
| `src/ai_news_agent/graph/nodes/parse.py` | modify | Map new request fields into `ConnectorRequest` without changing Juya/GitHub/Bilibili mappings | `parse_request_node` |
| `tests/test_sources.py` | modify | Prove allowed names, Juya-only default, fake/factory behavior, and that `arxiv` remains unknown | pytest tests |
| `tests/test_workflow.py` | modify | Cover request mapping and selected-connector filtering for the new names | pytest tests |

### Subsystem E: Intent, selection, and entrypoint defaults

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/intent.py` | modify | Parse Hugging Face / Zhihu source names, global vs topic/task model-trending cues, and practitioner-insight cues | `parse_digest_intent`, `parse_connector_names_from_message` |
| `src/ai_news_agent/digest_request_builder.py` | modify | Apply existing precedence to the new kinds: explicit list/intent/target replaces Juya unless Juya is also included | `resolve_digest_request` |
| `src/ai_news_agent/adapters/openclaw.py` | modify | Apply identical source defaults, names, and replacement semantics for OpenClaw hints/messages | `resolve_openclaw_digest_request`, hint/argv builders |
| `src/ai_news_agent/cli.py` | modify | Document and validate `huggingface` and `zhihu` in `--sources` help; omitted `--sources` stays Juya-only | digest/openclaw CLI parser |
| `tests/test_intent.py` | modify | Cover new source phrases, Hugging Face dual-mode intent, Zhihu practitioner intent, replacement semantics, and unchanged Juya/GitHub/Bilibili cases | pytest tests |
| `tests/test_cli.py` | modify | Cover help, named-source validation, and Juya default | pytest tests |
| `tests/test_openclaw_adapter.py`, `tests/test_openclaw_targeted.py` | modify | Cover default hints, new allowed names, and unchanged HTTP/CLI contracts | pytest tests |

### Subsystem F: Kind-aware ranking and segmented digest output

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/ranking.py` | modify | Score Hugging Face from Hub `trending_score` (primary) plus transparent tie-breakers; score Zhihu from relevance, lens/topic match, and returned-text completeness; keep overall `top_n` and Bilibili newest guarantee | `rank_items`, `order_selected_for_digest`, `_FALLBACK_KIND_ORDER` |
| `src/ai_news_agent/summarizer.py` | modify | Display names, source-evidence in summarizer context, and Hugging Face/Zhihu caveats (no quality/trend/freshness overclaim) | `summarize_ranked_items`, `_source_display_name` |
| `src/ai_news_agent/rendering.py` | modify | Section labels for Hugging Face and Zhihu; preserve single-source Markdown/text/editorial output | `_SECTION_LABELS`, Markdown/text renderers |
| `tests/test_ranking.py` | modify | Assert kind-specific score keys, no `stars_or_views` overload, overall cap without quotas, new fallback order, intent-first order, omitted empty sections, and preserved Bilibili newest-in-window | pytest tests |
| `tests/test_summarizer.py` | modify | Assert Hugging Face / Zhihu display names, caveats, and requested section ordering | pytest tests |
| `tests/test_rendering.py` | modify | Assert mixed-digest section headers and unchanged one-source output | pytest tests |

### Subsystem G: Tool registry and interface consumption

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/tools/schemas.py` | modify | Add Hugging Face search args (discovery mode + optional topic/task + limit) without changing existing `SearchArgs` for GitHub/Bilibili/Juya | new args schema; existing `SearchArgs` unchanged |
| `src/ai_news_agent/tools/connectors.py` | modify | Add pure Hugging Face and Zhihu search through the shared connector request/result boundary | `search_huggingface_trending_models`, `search_zhihu_practitioner_insights` |
| `src/ai_news_agent/tools/registry.py` | modify | Inject/register the two new tool factories; preserve existing tool names and terminal-routing protections | `build_tool_registry` extended dependency surface |
| `src/ai_news_agent/tools/__init__.py` | modify if needed | Export the new tool surface consistently | package exports |
| `src/ai_news_agent/tools/interface_router.py` | modify | Pass the new factories through per-request registry construction without allowing the model to override resolved sources | interface-router dependency wiring |
| `src/ai_news_agent/app/gradio_app.py` | modify | Add source toggles/examples/validation for Hugging Face and Zhihu; keep Juya default | `_SOURCE_TOGGLE_CHOICES`, `_build_service`, examples |
| `src/ai_news_agent/app/digest_service.py` | modify | Build live/fake connector sets through the shared registry including the two new factories | `DigestServiceRuntime` |
| `tests/test_tools_connectors.py`, `tests/test_tools_registry.py` | modify | Assert new pure-tool delegation, JSON-safe observations, registration, and factory lifecycle | pytest tests |
| `tests/test_interface_router.py` | modify | Assert per-request factory availability and unchanged trusted request behavior | pytest tests |
| `tests/test_gradio_app.py` | modify | Assert new toggle options and Juya default | pytest tests |
| `tests/test_digest_service.py`, `tests/test_digest_service_parity.py` | modify | Assert fake/live runtime defaults and unchanged HTTP contracts | pytest tests |
| `tests/test_mvp_smoke.py` | modify | Keep a deterministic end-to-end fake source-selection smoke test | pytest tests |

### Subsystem H: Documentation and acceptance evidence

| Path | Create/Modify | Single responsibility | Public surface |
| --- | --- | --- | --- |
| `README.md` | modify | Document source roles, Juya default, allowed names including `huggingface` and `zhihu`, Hugging Face dual mode, Zhihu practitioner job, env vars, tools, and updated smoke commands | user-facing setup/usage |
| `openclaw/skills/ai-news-digest/SKILL.md` | modify | Teach allowed source names and Hugging Face/Zhihu intent without inventing flags | OpenClaw digest skill |
| `openclaw/skills/ai-news-followup/SKILL.md` | modify if source lists are documented | Keep follow-up skill aligned with new kinds | OpenClaw follow-up skill |
| `docs/benchmarks/openclaw-latency-baseline.md` | modify | Keep historical baseline commands accurate; do not imply new sources are the default | reproducible benchmark notes |
| `pyproject.toml` | modify if live markers are added | Document `live` marker env names for Hugging Face/Zhihu | pytest markers |
| `docs/superpowers/plans/2026-08-16-ai-ecosystem-and-practitioner-signals-plan.md` | modify during execution only if discovery invalidates scope/order | Remain authoritative type-1 plan | this plan |

## Future Paths Not In This Plan

| Path / capability | Reason deferred |
| --- | --- |
| `src/ai_news_agent/connectors/arxiv.py` | ADR-0002 defers primary academic sources |
| generic RSS/blog connector modules | ADR-0002; Juya remains the dedicated bulletin |
| Hugging Face datasets, Spaces, eval results | Models-only atomic item |
| Zhihu hotlist, direct-answer, or page enrichment | Official search evidence only |
| LLM-generated Zhihu queries or LLM-as-judge ranking | Deterministic lenses and scores |
| per-source quotas or separate per-source `top_n` | ADR-0001 mixed-digest policy |
| star-history / true star-delta / release-as-primary | Unchanged GitHub constraints |
| SQLite migration for historical rows | Empty `source_evidence` default is enough |
| generic policy engine / LLM-controlled source selection | Selection stays deterministic and trusted |

## Blast Radius

| Path / boundary | Why sensitive | Existing behavior to preserve | Plan mode |
| --- | --- | --- | --- |
| `models.py`, `storage.py`, persisted `NewsItem` JSON | `SourceKind` and item JSON are stored and read throughout ranking, follow-up, and traces | Existing `github`/`bilibili`/`juya` rows load; no SQLite migration; missing `source_evidence` becomes `{}` | high |
| `sources.py`, `request.py`, `digest_request_builder.py`, `intent.py` | Defines all default and target-driven collection choices | Bare digest stays Juya-only; invalid names still error; `arxiv` stays unknown; no hidden all-connectors fallback | high |
| New Hugging Face / Zhihu connectors | Network boundaries, auth, rate/quota, and ranking honesty | Failures are non-fatal warnings; explicit source failure never silently becomes Juya | high |
| `ranking.py`, `summarizer.py`, `rendering.py` | Changes digest selection/order visible to users and saved follow-up ranks | Dedupe, score evidence, Bilibili newest-in-window, and single-source rendering remain deterministic | high |
| `tools/registry.py`, `tools/interface_router.py`, `tools/schemas.py` | Model-facing tool names and protected request context | Existing tools, bounded loop, terminal short-circuit, and no model override of trusted source selection | high |
| Gradio, CLI, OpenClaw service/adapter | Public UI/CLI/HTTP behavior and fake-mode smoke path | HTTP schemas, follow-up paths, streaming, lifecycle closing, and at-most-one persist remain unchanged | high |
| README / OpenClaw skills / `.env.example` | Users currently see Hugging Face as out of scope | Documentation teaches opt-in names and jobs without leaving stale “out of scope” claims | skip / medium |

## Workflow For Implementers

1. This plan is the durable type-1 source of truth for Milestone 6. Create a focused type-2 plan before every task marked `Plan mode: high`.
2. Honor strict TDD for every task tagged `TDD suitable: yes`: test-only RED, scoped failing test run, explicit `RED` status, one behavior per production GREEN, scoped passing run, explicit `GREEN` status.
3. When a type-2 plan establishes a new module such as `connectors/huggingface.py` or `connectors/zhihu.py`, start its first GREEN with the smallest public stub required by that test; do not add network logic, registry wiring, and intent routing in one GREEN.
4. Preserve consumer behavior at public boundaries (`SourceConnector`, `DigestRequest`, renderer output, CLI/HTTP payloads), not tests of import location alone.
5. If Hugging Face discovery-mode field names, Zhihu credential env names, or score-breakdown keys cannot be fixed from the ADR/spec and existing contracts, stop and update this plan with the resolved decision before implementation.

## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 — Establish shared source kinds and source_evidence

- [ ] **Do:** Add `SourceKind.HUGGINGFACE` and `SourceKind.ZHIHU`, plus a JSON-safe `NewsItem.source_evidence` mapping that defaults to `{}`. Prove model serialization and storage round-trip compatibility for old rows without the field and new rows with populated evidence. No SQLite migration.
- **Blocked by:** —
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_models.py tests/test_storage.py -q`

### T2 — Implement Hugging Face trending-model connector

- [ ] **Do:** Add `huggingface_hub` and a dedicated `HuggingFaceConnector` that lists models only. Support global trending and topic/task-filtered trending. Map Hub `trending_score`, 30-day downloads, likes, activity, pipeline/library tags, and discovery mode into `source_evidence` (never into `stars_or_views`). Record inspectable warnings for request/rate-limit failure, malformed responses, skipped malformed models, and missing trend evidence. First GREEN is types + stub only.
- **Blocked by:** T1
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_connectors_huggingface.py tests/test_models.py -q`

### T3 — Implement Zhihu practitioner-insight connector

- [ ] **Do:** Add a dedicated `ZhihuConnector` that calls only the official search API. Expand topics with the three deterministic practitioner lenses, cap at three search calls, and dedupe by stable id or canonical URL. Rankable evidence is API relevance, lens/topic match, and returned-text completeness. Thin results are low-confidence discovery links. Timeframe requests emit an unsupported-timeframe warning rather than claiming freshness. Auth/quota/malformed/skipped-row warnings are non-fatal. Prove linked pages are not fetched. First GREEN is types + stub only.
- **Blocked by:** T1
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_connectors_zhihu.py tests/test_models.py -q`

### T4 — Register sources and map request fields

- [ ] **Do:** Add real/fake Hugging Face and Zhihu factories to the canonical registry; keep `DEFAULT_SOURCE_NAMES` as Juya-only. Add DigestRequest/ConnectorRequest fields for Hugging Face discovery mode (names finalized in Plan mode) and map them in `parse_request_node`. Direct workflow construction, persistence metadata, and connector lifecycle use the resolved set rather than “all injected connectors.”
- **Blocked by:** T2, T3
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_sources.py tests/test_workflow.py tests/test_cli.py tests/test_mvp_smoke.py -q`

### T5 — Implement deterministic Hugging Face and Zhihu intent

- [ ] **Do:** Extend NL source parsing and OpenClaw/CLI/Gradio request resolution so `huggingface` and `zhihu` are valid opt-in names. Hugging Face cues distinguish global trending from topic/task-filtered trending. Zhihu cues mean practitioner lessons, trade-offs, and pitfalls. Platform/source cues replace the Juya default unless Juya is also named. Preserve existing Juya/GitHub/Bilibili phrases, legacy Juya-alias rejection, and `arxiv` as unknown.
- **Blocked by:** T4
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_intent.py tests/test_workflow.py tests/test_cli.py tests/test_openclaw_adapter.py tests/test_openclaw_targeted.py -q`

### T6 — Add kind-aware ranking and source-section presentation

- [ ] **Do:** Score Hugging Face primarily by Hub `trending_score` with transparent relevance/downloads/likes/recency tie-breakers. Score Zhihu by API relevance, practitioner-lens match, topic match, and returned-text completeness, without implying popularity or freshness. Keep `top_n` as the overall cap (no quotas) and preserve the Bilibili newest-in-window guarantee. Fallback section order becomes Juya → Hugging Face → GitHub → Zhihu → Bilibili; intent-first still leads; empty sections are omitted. Summaries and renderers use source-specific display names and caveats (Hugging Face: popularity ≠ quality; Zhihu: thin results are discovery-only).
- **Blocked by:** T1, T2, T3, T5
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_ranking.py tests/test_summarizer.py tests/test_rendering.py tests/test_workflow.py -q`

### T7 — Expose connectors through tools and shared live interfaces

- [ ] **Do:** Add pure `search_huggingface_trending_models` and `search_zhihu_practitioner_insights` wrappers and register them with injected factories. Hugging Face tool args include discovery mode plus optional topic/task and limit; Zhihu tool args include topics and limit, with lens expansion remaining connector-owned. Thread factories through the interface router, Gradio, and OpenClaw runtime. Update Gradio toggles/examples/validation. Retain existing tool names, bounded loop, streaming, HTTP schemas, follow-up paths, and at-most-one persist.
- **Blocked by:** T4, T5, T6
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_tools_connectors.py tests/test_tools_registry.py tests/test_interface_router.py tests/test_gradio_app.py tests/test_digest_service.py tests/test_digest_service_parity.py tests/test_mvp_smoke.py -q`

### T8 — Update usage, skill, and environment documentation

- [ ] **Do:** Replace “Hugging Face / RSS out of scope” claims with the Milestone 6 source roles. Document Juya-only bare defaults, allowed names (`juya`, `huggingface`, `github`, `zhihu`, `bilibili`), Hugging Face dual discovery, Zhihu practitioner job and official-API-only evidence, credential env vars, and fake CLI examples. Align OpenClaw skill docs and benchmark notes without changing historical baseline meaning.
- **Blocked by:** T4, T5, T6, T7
- **Plan mode:** skip
- **TDD suitable:** no
- **TDD suitable reason:** static documentation and `.env.example` comments only; no runtime behavior.
- **Verification:** review `git diff --check`; run every changed fake CLI command where practical; confirm README and OpenClaw skills no longer list Hugging Face as out of scope and still reject the legacy Juya GitHub alias.

### T9 — Run milestone-level regression and acceptance checks

- [ ] **Do:** Run the full automated suite and focused fake/manual acceptance paths after all behavior and documentation changes. Update this plan’s changelog if verification exposes a missing file, a changed external contract, or a required follow-up subtask.
- **Blocked by:** T1, T2, T3, T4, T5, T6, T7, T8
- **Plan mode:** medium
- **TDD suitable:** no
- **TDD suitable reason:** verification-only integration pass; production behavior was already driven test-first in T1–T7.
- **Verification:** `uv run pytest -q`; fake CLI bare digest (Juya-only); fake CLI `--sources huggingface`; fake CLI `--sources zhihu`; fake CLI mixed `--sources huggingface,zhihu,github`; fake OpenClaw/HTTP bare request remains Juya; a mixed-source render with intent-first section order and fallback Juya → Hugging Face → GitHub → Zhihu → Bilibili; existing GitHub/Bilibili/Juya smoke paths still pass.

## TDD Note For Agent Mode

When implementing, follow the `test-driven-development` skill for each subtask tagged `TDD suitable: yes`: write the failing test first, implement the minimal code, then refactor. This plan names the boundaries and acceptance checks; it does not replace red/green/refactor. New modules start GREEN with types and stubs only.

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-08-16 | Created from the accepted Milestone 6 ADR and ecosystem/practitioner-signals design spec. |
