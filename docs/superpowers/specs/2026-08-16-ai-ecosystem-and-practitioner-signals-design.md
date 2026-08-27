# Milestone 6: AI Ecosystem And Practitioner Signals

Date: 2026-08-16  
Amended: 2026-08-27 (Milestone 6.5: Hugging Face and Zhihu rank deep-dive; HF collect-time card excerpt for family-card Snippet)  
Status: approved design

## Summary

Milestone 6 expands the digest with two opt-in sources that have distinct product jobs:

- **Hugging Face** supplies model-momentum signals. Its atomic item is a **trending model**.
- **Zhihu** supplies Chinese-language practitioner lessons, trade-offs, and pitfalls. Its atomic item is a **practitioner insight**.

This replaces the former “Broader Research Sources” scope. arXiv and generic RSS are deferred rather than represented by Zhihu, because Zhihu is secondary practitioner evidence rather than primary academic evidence. The bare-digest default remains Juya-only.

Domain terminology is defined in `CONTEXT.md`. Architectural decisions live in `docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md` and, for rank follow-up, `docs/adr/0005-persist-only-rank-deep-dive.md`. This design amends the Milestone 6 and 6.5 sections of `2026-05-02-ai-news-research-agent-design.md`.

Milestone 6 ships collection, ranking, rendering, and tools. It preserves existing structured follow-up phrases and OpenClaw path taxonomy; it does not specialize Hugging Face or Zhihu rank replies. **Milestone 6.5** is that follow-up gap: kind-specific **rank deep-dives** from persisted evidence, before Milestone 7 memory/scheduling/deployment.

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

Use the official `huggingface_hub` client and `HfApi.list_models`. Collection requests `cardData=True` on the existing collect window so model-card summary or description can be saved to `NewsItem.raw_snippet` for family-card rank follow-up (persist-only at rank time; ADR-0005 unchanged). The Hub supports `trending_score` sorting and exposes model metadata including 30-day downloads, all-time downloads, likes, creation and modification times, pipeline tag, tags, library name, gated status, and native trending score.

The connector has two deterministic discovery modes:

- **Global trending**: no topic constraint; return the Hub’s currently trending models.
- **Topic/task trending**: apply a user-named topic, search term, or pipeline-task filter before requesting trending order.

Models are the only accepted Hub entity in this milestone. A model URL or model identifier remains traceable as the item source.

### Normalization

Each model becomes one `NewsItem` with:

- `source=SourceKind.HUGGINGFACE`
- model id, canonical Hub URL, author, task/library tags, and last-modified time
- model-card excerpt in `raw_snippet` when Hub returns card summary or description via `cardData=True` at collect time (no README fetch)
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

Existing tool names, bounded tool-loop behavior, OpenClaw `/digest` and `/followup` request/response schemas, follow-up path taxonomy, and at-most-one digest persistence per request remain unchanged. Milestone 6.5 changes only the structured **rank** formatter text for Hugging Face and Zhihu; it does not add tools, path strings, or live enrichment.

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

## Milestone 6.5: Hugging Face And Zhihu Rank Deep-Dive

Date: 2026-08-27  
Status: approved design

Milestone 6 left Hugging Face and Zhihu on the generic rank reprint (`Digest item N` from `DigestEntry` fields). That is a poor fit: Hugging Face digest rows are **stubs** (comparison table at digest time, skip LLM summarize), so generic follow-up hides Hub stats and **Also** variants that already live on `NewsItem.source_evidence`. Zhihu still gets an LLM entry, but the practitioner job is the official-search result (snippet, lens, relevance), not the paraphrase.

Juya already has a persist-only **issue deep-dive** on the same rank phrases. Milestone 6.5 gives Hugging Face and Zhihu the same job: a kind-specific **rank deep-dive** built only from the latest saved digest. Bilibili-style live enrichment, new structured phrases, digest-renderer “follow-up sections,” tool-JSON reshapes, open-ended prompt special-cases, and Milestone 7 memory/scheduling are out of scope.

### Product job

On existing rank phrases (`follow up on item 1`, `#2`, `the second one`, `Digest the first news`, and the current rank parser), `format_rank_item` returns:

- **Juya**: unchanged issue deep-dive (historical GitHub-tagged Juya heuristics stay).
- **Hugging Face**: a **family card** for the **model family** at that **display rank** — same identity as the digest table row.
- **Zhihu**: a **practitioner-insight card** for that rank’s single search result.
- **GitHub / Bilibili / unknown**: unchanged generic entry reprint.

Show sources, study-first, and caveats stay generic. OpenClaw `/followup` paths remain `no_digest` / `structured` / `guidance`. `get_digest_item` / `get_source_trace` / ranking-explanation JSON stay as they are.

No live Hub re-list, no model-card re-fetch, no Zhihu page crawl. Also variants do not get their own ranks. Zhihu cards do not stitch other digest insights or parse a snippet as Juya sub-news.

### Hugging Face family card

English chrome matching the comparison table. Fields:

- display rank, family representative (model id / title), Hub URL
- Trending, Downloads (30d), Likes, Pipeline
- Also variants when `family_variants` was persisted
- publisher when present
- card snippet from saved `raw_snippet` when Hub returned summary/description at digest collection (no live Hub fetch on rank follow-up)
- always-on popularity-not-quality caveat

Omit empty why/background, gated, library, all-time downloads, discovery mode, and `follow_up_action`. Empty Also is omitted, not printed as “Also: none”.

### Zhihu practitioner-insight card

Chinese chrome. Evidence-first body:

- 第 N 条, title, URL
- 镜头 (`query_lens`)
- author / source label
- 搜索相关性, labeled as official-search relevance, never 热度
- 原文摘录 from `raw_snippet`
- 摘要 / 为什么值得看 only when those `DigestEntry` fields are non-empty
- thin-evidence and “relevance is not freshness/trending” caveats

Do not show `evidence_text_length` as a user-facing metric. Do not translate payload text.

### Missing evidence

If the `NewsItem` is missing or Hub stats / snippet are empty, still return a kind-specific card with title, URL, and any persisted fields. Never invent stats or excerpt. Add an explicit missing-evidence or discovery-only caveat (same honesty as Juya falling back to the entry summary when sub-news parse finds nothing).

### Architecture

Sibling modules next to `juya_followup.py` (`huggingface_followup.py`, `zhihu_followup.py`) own formatting from persisted `DigestEntry` + `NewsItem`. `format_rank_item` dispatches: Juya heuristic first, else Hugging Face / Zhihu on `entry.source_kind`, else generic. No formatter registry, no live connector calls, no new tools.

Update the OpenClaw follow-up skill and README examples so rank follow-up on Hugging Face / Zhihu is documented as family card / insight card, still via the same phrases. Do not invent Hub quality or Zhihu freshness claims.

### Testing And Acceptance

TDD-suitable; strict test-first. Coverage must include:

- Hugging Face rank phrase → family card with table stats, Also, snippet, publisher, popularity caveat
- Zhihu rank phrase → evidence-first insight card; labeled LLM fields only when non-empty; relevance not presented as 热度
- mixed digest: rank N uses the global display rank; Juya / HF / Zhihu / generic branches do not steal each other’s rows
- missing `NewsItem` or empty evidence → honest degraded card, no invented Hub stats or snippet
- sources / study-first / caveats text unchanged; OpenClaw path taxonomy unchanged
- no HTTP/Hub/Zhihu calls on the rank path
- regression for Juya issue deep-dive and generic GitHub/Bilibili reprint

### Out of scope (6.5)

- Live enrichment (Hub re-fetch, Zhihu page fetch, Bilibili transcript-style `get_source_trace` extension)
- New structured phrases, kind-aware sources/study-first/caveats formatters, or Gradio open-ended prompt rewrites
- Persist `output_language` to switch chrome (storage; closer to Milestone 7)
- arXiv, generic RSS, HF datasets/Spaces, Zhihu hotlist/direct-answer/crawl
- Milestone 7 memory, scheduling, deployment, quality evaluation

## Deferred Work

- arXiv or another primary academic source
- generic or curated RSS/blog discovery
- Zhihu hotlist, direct answer, full-page enrichment, or cross-result synthesis
- Hugging Face datasets, Spaces, benchmark evaluation, or adoption-velocity history
- per-source quotas or separate per-source digest sizes
- live follow-up enrichment for Hugging Face or Zhihu (rejected for 6.5; Bilibili transcript enrich stays Bilibili-only)
- kind-aware show-sources / study-first / caveats formatters
