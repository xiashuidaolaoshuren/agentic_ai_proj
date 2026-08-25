# Milestone 6: AI Ecosystem And Practitioner Signals

Date: 2026-08-16  
Status: approved design

## Summary

Milestone 6 expands the digest with two opt-in sources that have distinct product jobs:

- **Hugging Face** supplies model-momentum signals. Its atomic item is a **trending model**.
- **Zhihu** supplies Chinese-language practitioner lessons, trade-offs, and pitfalls. Its atomic item is a **practitioner insight**.

This replaces the former “Broader Research Sources” scope. arXiv and generic RSS are deferred rather than represented by Zhihu, because Zhihu is secondary practitioner evidence rather than primary academic evidence. The bare-digest default remains Juya-only.

Domain terminology is defined in `CONTEXT.md`. Architectural decisions live in `docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md`. This design amends the Milestone 6 section of `2026-05-02-ai-news-research-agent-design.md`.

## Goals

- Make Hugging Face useful for finding globally or topically trending model repositories.
- Make Zhihu useful for finding practical Chinese-language experience rather than generic search results.
- Preserve one connector, ranking, persistence, tool, and interface architecture across all source kinds.
- Keep every ranking claim inspectable and limited to evidence actually returned by the source.
- Preserve Juya-only defaults and the accepted overall `top_n` mixed-digest policy.
- Preserve existing Bilibili newest-in-window selection, OpenClaw transport, follow-up, and single-persist behavior.

## Non-Goals

- arXiv or academic-paper discovery.
- Generic or curated RSS/blog connectors.
- Hugging Face datasets or Spaces.
- Calling a popular model the “best” model or a benchmark winner.
- Zhihu hotlist/trending claims, direct-answer integration, page crawling, or multi-result synthesis.
- LLM-generated connector queries or LLM-as-judge ranking.
- Source quotas, storage migrations, scheduling, deployment, or long-term memory.

## Chosen Architecture

Use shared pipeline contracts with source-specific evidence.

Both connectors return `ConnectorResult` and normalized `NewsItem` values, participate in the existing deterministic workflow, and persist through the existing JSON item representation. `NewsItem` gains a backward-compatible JSON-safe `source_evidence` mapping for source-native ranking and explanation fields. Older saved items—including historical GitHub-tagged Juya rows—load with an empty mapping; no SQLite schema migration is required.

Do not overload `stars_or_views` with Hugging Face trending score, downloads, likes, or Zhihu relevance. Those values have different meanings and remain separately named in `source_evidence`.

Alternatives rejected:

- Flattening both sources into existing generic fields would lose the evidence needed for honest source-specific ranking.
- Separate per-source workflows would duplicate intent, persistence, rendering, tool, and interface behavior.

## Hugging Face: Model Momentum

### Collection

Use the official `huggingface_hub` client and `HfApi.list_models`. The Hub supports `trending_score` sorting and exposes model metadata including 30-day downloads, all-time downloads, likes, creation and modification times, pipeline tag, tags, library name, gated status, and native trending score.

The connector has two deterministic discovery modes:

- **Global trending**: no topic constraint; return the Hub’s currently trending models.
- **Topic/task trending**: apply a user-named topic, search term, or pipeline-task filter before requesting trending order.

Models are the only accepted Hub entity in this milestone. A model URL or model identifier remains traceable as the item source.

### Normalization

Each model becomes one `NewsItem` with:

- `source=SourceKind.HUGGINGFACE`
- model id, canonical Hub URL, author, task/library tags, and last-modified time
- model-card excerpt when returned through the supported API
- `source_evidence` values for `trending_score`, `downloads_30d`, `downloads_all_time`, `likes`, `pipeline_tag`, `library_name`, `gated`, and discovery mode

Missing optional fields do not reject a model. Missing native trending score lowers ranking confidence and is exposed as a caveat.

### Ranking And Summary

Hub `trending_score` is the primary within-kind signal. Topic relevance, 30-day downloads, likes, activity recency, and metadata completeness are transparent supporting evidence or tie-breakers. The connector and renderer must never describe cumulative popularity as recent velocity.

The summary explains:

- what task the model targets
- why it appears in the current trending result
- which source metrics support that statement
- that popularity does not establish model quality

## Zhihu: Practitioner Insight

### Collection

Use only the official Zhihu search API documented at `https://developer.zhihu.com/docs?key=zhihu_search`. The published client contract sends `api_id=zhihu_search` with `Query` and `Count`, and returns search records containing a stable id when available, title, URL, returned text/snippet, source label, and relevance score.

Expand user topics through a bounded deterministic set of Chinese practitioner lenses:

- 实战 / 踩坑
- 部署 / 成本
- 评测 / 对比

The connector caps expansion to three search calls per collection pass, deduplicates by stable id or canonical URL, and applies the existing per-source item cap. It does not ask an LLM to invent queries.

Zhihu search does not provide a trustworthy trend or freshness contract for this design. When a timeframe is requested, the connector reports that the Zhihu results are relevance-based and does not claim the results were published in that timeframe.

### Normalization

Each result becomes one `NewsItem` with:

- `source=SourceKind.ZHIHU`
- stable result id or canonical URL identity
- title, URL, returned text, source label, and Chinese language metadata
- lens/topic matches
- `source_evidence` values for API relevance, query lens, returned source label, and evidence-text length

Results without a usable title or URL are skipped with a warning. A useful returned excerpt can support medium confidence; a title-only or thin result is low-confidence and discovery-only. Search results are never enriched by fetching the linked page.

### Ranking And Summary

Zhihu ranking combines:

- API relevance
- practitioner-lens match
- topic match
- returned-text completeness
- shared duplicate and weak-evidence penalties

It does not use or imply popularity, votes, freshness, or authority when those values are absent.

The summary extracts only practical lessons, trade-offs, or pitfalls supported by the returned text. A thin result is presented as a link to investigate, with an explicit caveat instead of an inferred takeaway.

## Source Selection And Presentation

- Bare digest requests remain **Juya-only**.
- Hugging Face and Zhihu are opt-in through explicit source lists, clear source-specific intent, or supported platform targets.
- A source cue replaces the Juya default unless Juya is also named.
- Hugging Face intent distinguishes global trending from topic/task-filtered trending.
- Zhihu intent means practitioner experience and trade-offs, not generic Chinese web search.
- The LLM cannot override the trusted source set resolved from the user request.

Mixed digests preserve one overall `top_n` cap with no per-source quotas. Scoring remains kind-aware and rendering remains segmented. The primary source named or implied by the user leads; otherwise the fixed fallback order is:

Juya → Hugging Face → GitHub → Zhihu → Bilibili.

Empty sections are omitted.

## Tools And Interface Parity

Add source-specific tools through the existing registry and connector boundary:

- `search_huggingface_trending_models`
- `search_zhihu_practitioner_insights`

Tool inputs are typed and bounded. Hugging Face accepts discovery mode plus optional topic/task and limit. Zhihu accepts topics and limit; lens expansion remains connector-owned and deterministic.

The canonical source registry, deterministic fake connectors, digest workflow, CLI, Gradio, interface router, and OpenClaw adapter all expose the same source names and selection behavior. Direct connector tools do not create a parallel collection or persistence path.

Existing tool names, bounded tool-loop behavior, OpenClaw `/digest` and `/followup` request/response schemas, follow-up path taxonomy, and at-most-one digest persistence per request remain unchanged.

## Reliability And Errors

Connector failures are non-fatal and preserve partial results from other selected sources. An explicitly selected source that fails is never silently replaced with Juya.

Hugging Face warnings distinguish request/rate-limit failure, malformed responses, skipped malformed models, and missing trend evidence.

Zhihu warnings distinguish missing or rejected authentication, quota exhaustion, request failure, malformed responses, skipped malformed results, thin evidence, and unsupported timeframe guarantees.

All warnings retain connector name, stable code, actionable message, and bounded detail. Connector clients follow the existing async lifecycle and close owned resources.

## Testing And Acceptance

Implementation is TDD-suitable and must follow strict test-first RED/GREEN cycles.

Automated coverage must include:

- mocked connector response mapping, malformed rows, auth/quota/rate failures, deduplication, and warning contracts
- Hugging Face global versus topic/task discovery and native-trend-first ranking evidence
- Zhihu deterministic lens expansion, three-call cap, relevance/lens/completeness ranking, thin-result behavior, and no page fetch
- backward-compatible `NewsItem` persistence with empty or populated `source_evidence`
- source registry, aliases, Juya-only default, replacement semantics, and primary-source resolution
- one overall mixed-digest cap, no quotas, new fallback order, and omitted empty sections
- preserved Bilibili newest-in-window selection and stable single-source rendering
- source-specific summarization caveats and source labels
- tool schema/delegation, bounded JSON-safe observations, and failure conversion
- CLI, Gradio, interface-router, OpenClaw schema/path, single-persist, and fake-mode parity
- full regression coverage for Juya, GitHub, Bilibili, persistence, and follow-up behavior

No default automated test performs a live external request. Optional live smoke tests require explicit opt-in and configured credentials.

## Deferred Work

- arXiv or another primary academic source
- generic or curated RSS/blog discovery
- Zhihu hotlist, direct answer, full-page enrichment, or cross-result synthesis
- Hugging Face datasets, Spaces, benchmark evaluation, or adoption-velocity history
- per-source quotas or separate per-source digest sizes
