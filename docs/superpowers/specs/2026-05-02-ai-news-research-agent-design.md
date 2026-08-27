# AI News Research Agent Design

Date: 2026-05-02  
Amended: 2026-05-19 (Bilibili connector library refactor)
Amended: 2026-05-21 (Milestone 2 LLM tool usage layer)
Amended: 2026-06-29 (Milestone 4 inserted: Pydantic + LangChain @tool migration; former M4 -> M5, former M5 -> M6)
Amended: 2026-08-11 (Source role split per `docs/adr/0001-source-role-split.md`; Milestone 5 sourcing refactor inserted; former M5 -> M6, former M6 -> M7)
Amended: 2026-08-16 (Milestone 6 reframed as Hugging Face model momentum + Zhihu practitioner insight; arXiv/RSS deferred)
Amended: 2026-08-27 (Milestone 6.5: persist-only Hugging Face family card and Zhihu practitioner-insight card on rank follow-up)

## Summary

Build a local-first, on-demand AI News Research Chatbot for personal learning. The user asks for an AI digest, and the agent collects recent AI-related signals from distinct source roles — default **Juya** curated bulletin, opt-in **GitHub** trending-repo ecosystem signals, and opt-in **Bilibili** video discovery — ranks and presents them in a kind-aware way, summarizes them in their source language, explains why they matter, suggests follow-up learning actions, and stores source traces for verification and follow-up chat.

OpenClaw is included as a planned Milestone 3 interface adapter, not as the MVP foundation. Domain language lives in `CONTEXT.md`; architectural source-role decisions live in `docs/adr/0001-source-role-split.md`.

## Goals

- Learn core agentic AI engineering patterns through a scoped, useful project.
- Support an on-demand chatbot workflow: ask for a digest, receive ranked summaries, and ask follow-up questions.
- Keep each source's product job distinct: Juya = curated bulletin (default), GitHub = trending-repo ecosystem signal, Hugging Face = model momentum, Zhihu = practitioner insight, and Bilibili = video learning (all except Juya opt-in).
- Preserve source URLs, collected metadata, ranking decisions, and generated outputs for debugging.
- Keep the architecture modular so later sources and interfaces can be added without rewriting the core agent.
- Add explicit LLM tool usage after the local digest MVP is stable, using existing connector and storage boundaries rather than duplicating source logic.

## Non-Goals For MVP

- Full web-scale crawling.
- Deep Bilibili video understanding when transcript or accessible content is unavailable.
- Scheduled digest generation.
- Cloud deployment.
- OpenClaw production integration.
- arXiv, Hugging Face, RSS/blog connectors.
- Heavy vector database/RAG infrastructure.
- Automated LLM-as-judge evaluation.

## User Experience

The first version uses a local chatbot interface.

Example request:

> Give me today's AI digest.

The agent returns a digest containing selected items. Each item includes:

- title
- source name
- source URL
- short summary in the source's original language
- why it matters
- useful background knowledge
- suggested follow-up action: read, watch, try, or build
- confidence or caveat when content is incomplete

The user can then ask follow-up questions such as:

- Why is this repo important?
- Which item should I study first?
- Show me the original sources for item 2.
- Turn this digest into a weekend learning plan.

## Architecture

The system is split into small modules with clear responsibilities.

### Chat Interface

Receives user requests and displays digest and follow-up answers. The MVP uses a simple local chatbot UI. Gradio is the default choice because it can provide a local Python chatbot with little interface code, keeping attention on the agent workflow.

### Agent Orchestrator

Coordinates the workflow. LangGraph is the preferred orchestrator because the workflow has clear stages and may grow into a graph with retries, conditional paths, and later scheduling.

The orchestrator is responsible for:

- interpreting the user's digest request
- selecting source connectors
- passing search parameters to connectors
- triggering ranking
- triggering summarization
- saving results
- answering follow-up questions from saved digest context

### Source Connectors

Each connector returns a normalized `NewsItem` object and hides source-specific access details.

Current / target connectors (distinct roles; see ADR-0001):

- **Juya** connector — curated daily bulletin from `https://daily.juya.uk/` (first-class; not a GitHub special case)
- **GitHub** connector — opt-in ecosystem signal; atomic item is a trending repo (stars × recency heuristic)
- **Bilibili**-oriented connector — opt-in video metadata discovery

Milestone 6 target connectors:

- **Hugging Face** — opt-in model-momentum signal; atomic item is a Hub-native trending model
- **Zhihu** — opt-in Chinese-language practitioner signal; atomic item is a traceable search result with practical lessons, trade-offs, or pitfalls

Later connectors:

- arXiv or another primary academic source
- generic or curated RSS/blog sources
- general web search

### Ranking Layer

Scores and filters candidate items before summarization. Ranking should use **kind-aware** features (bulletin issues, trending repos, trending models, practitioner insights, and videos are not one naive “newsiness” score). Ranking should consider:

- freshness
- relevance to AI topics
- source quality
- source-native momentum or relevance where available (GitHub stars plus activity; Hugging Face native trending score; Zhihu search relevance plus practitioner-lens match)
- learning value for the user
- metadata completeness
- duplication with other candidates

When a digest intentionally mixes SourceKinds, present **segmented sections by source** rather than a single interleaved top-N. Keep one overall `top_n` cap with no source quotas. Section order is **intent-first** (primary kind from the ask leads); otherwise fixed fallback **Juya → Hugging Face → GitHub → Zhihu → Bilibili**, omitting empty sections.

Ranking should prefer verifiable items with clear source links and useful metadata.

### Summarization Layer

Generates digest entries from ranked items. Summaries should stay faithful to collected source data and avoid inventing details when source content is incomplete.

Each summary includes:

- concise source-language summary
- why the item matters
- background knowledge needed
- suggested follow-up action
- confidence or caveat when relevant

### Storage Layer

Stores local data so runs are inspectable and follow-up chat has context.

The MVP should store:

- raw or semi-raw fetched metadata
- normalized candidate items
- ranking scores and selected items
- final digest output
- source URLs
- connector errors and warnings

SQLite is the preferred MVP storage choice. Markdown and JSON artifacts can also be written for easy inspection.

### Evaluation And Logging Layer

Records enough information to debug and improve the agent:

- source queries
- connector results
- connector failures
- ranking decisions
- prompts and model outputs
- final digest artifacts

Logs should make it possible to answer: why was this item included, why was another item excluded, and what evidence was used for the summary?

### LLM Tool Usage Layer

Milestone 2 adds explicit LLM-callable tools on top of the completed local digest workflow. The deterministic Milestone 1 LangGraph digest graph remains the stable default path for generating a digest; tool usage is introduced as an additional agentic layer for learning, follow-up reasoning, and controlled source exploration.

The tool layer should expose existing capabilities through a small registry of structured tools instead of creating a parallel connector system. Tool implementations should delegate to the same `SourceConnector`, `DigestStore`, ranking, and rendering contracts already used by CLI and Gradio.

Initial follow-up tools:

- `load_latest_digest`: return the latest saved digest summary and run id.
- `get_digest_item`: return one selected item by rank or item id.
- `get_source_trace`: return stored source metadata, URL, connector warnings, and evidence for a digest item.
- `get_ranking_explanation`: return ranking score, ranking reasons, penalties, and caveats for a digest item.

Initial connector tools:

- `search_github_ai_news`: call the GitHub connector through the shared connector request boundary.
- `search_bilibili_ai_news`: call the Bilibili connector through the shared connector request boundary.

After Milestone 5 source role split, add:

- `search_juya_ai_news` (or equivalent): call the Juya connector through the shared connector request boundary.

Milestone 6 adds `search_huggingface_trending_models` and `search_zhihu_practitioner_insights` through the same connector-tool boundary. arXiv and generic RSS/blog tools remain deferred.

The Milestone 2 agent should use a bounded tool-calling loop: the model decides when to call a registered tool, a tool execution node runs the call, and the model then answers from the returned observations. Tool calls must have typed input schemas, stable tool names, concise descriptions, and outputs that can be serialized to JSON or markdown for the final answer.

Reliability constraints:

- Tool calls must be logged with tool name, arguments, success/failure, and summarized output.
- Tool failures should become user-facing caveats or partial-result warnings, not crashes.
- Connector tools must preserve source URLs and confidence/caveat metadata.
- Follow-up answers must stay grounded in tool results and saved digest traces.
- The Milestone 2 tool layer must not require OpenClaw, future source connectors, scheduling, vector search, or deployment; Milestone 6 extends the same registry without changing that isolation.

## OpenClaw Integration

OpenClaw should be integrated as Milestone 3, after the local agent and internal LLM tool usage layer work.

OpenClaw's role is an outer assistant gateway, not the core retrieval engine. It can receive messages from channels such as Telegram, Slack, Discord, or webchat, then call the AI News Research Agent through a registered tool.

Target flow:

```text
OpenClaw channel message
  -> OpenClaw Gateway
  -> registered tool: generate_ai_news_digest
  -> local or hosted Python agent API/CLI
  -> selected connectors (default: Juya; opt-in source kinds selected from trusted cues)
  -> kind-aware ranked / segmented digest
  -> OpenClaw reply
```

The OpenClaw adapter should call the same core Python workflow used by the local chatbot. This keeps the core agent independent from any single interface.

Primary adapter boundary:

- HTTP: `POST /digest`

Fallback adapter boundary:

- CLI: `python -m ai_news_agent digest --timeframe today` (default sources: Juya)
- CLI: `python -m ai_news_agent digest --timeframe today --sources github,bilibili` (opt-in platforms)

### Source selection (all entrypoints)

Source selection for CLI, Gradio, and OpenClaw maps to `DigestRequest.connector_names` via the shared registry in `ai_news_agent.sources`, with these product rules (ADR-0001):

- **Bare digest** (no platform cue): run **Juya only**.
- **Opt-in platforms**: add GitHub, Hugging Face, Zhihu, and/or Bilibili via explicit `--sources` / UI lists, clear intent phrases, or supported platform-specific targets.
- **Replace, don’t stack**: a clear opt-in source cue **replaces** the Juya default unless Juya is also named or targeted.
- **Juya targets**: website URLs only (`https://daily.juya.uk/…`). The legacy `https://github.com/jujuyaya/juya-ai-daily` URL is **not** a Juya alias — reject with guidance to the website.
- **Hugging Face intent**: distinguish global model trending from topic/task-filtered model trending.
- **Zhihu intent**: target practitioner lessons, trade-offs, and pitfalls rather than generic Chinese web search.
- Allowed connector names include `juya`, `huggingface`, `github`, `zhihu`, and `bilibili`.

OpenClaw should not be required for MVP success.

## Data Flow

1. User asks the chatbot for an AI digest.
2. Agent interprets the request into topic, timeframe, source selection, language preferences, and optional source-targeting inputs (for example, Juya website URLs, GitHub repo intent, Hugging Face global/topic model-trending intent, Zhihu practitioner intent, or Bilibili uploader/video targets).
3. Selected connectors collect candidate items (default: Juya; otherwise the implied/named set).
4. Candidates are normalized into a shared `NewsItem` format with the correct `SourceKind` and JSON-safe source-native evidence.
5. Ranking layer applies kind-aware scoring, filters duplicates and weak items, and selects top candidates; mixed digests are segmented by source.
6. Summarization layer creates source-language summaries, significance notes, learning suggestions, and source-specific caveats.
7. Storage layer saves source metadata, ranking decisions, and final digest.
8. Follow-up chat uses the saved digest and source traces to answer questions.

## Source Strategy

### Juya (default bulletin)

Juya is a **first-class** curated daily AI bulletin, not a GitHub special case and not a generic RSS connector.

- Canonical target: `https://daily.juya.uk/` (RSS + per-issue markdown enrichment when available).
- `SourceKind.JUYA` / connector name `"juya"`.
- Bulletin rows must not be tagged as GitHub.
- Follow-up may extract sub-news from persisted issue evidence (existing Juya deep-dive path).
- Legacy GitHub repo URL `https://github.com/jujuyaya/juya-ai-daily` must **fail with guidance** to the website (clean break; update docs and smoke commands accordingly).

### GitHub (opt-in ecosystem signal)

GitHub’s product job is **open-source momentum**, not a primary news feed and not a host for Juya.

- Atomic digest item: a **trending repo** under a topic, scored by a transparent heuristic (e.g. stars × recency of activity). Do not claim precise “stars gained in N days” until true star-delta exists.
- Use official GitHub APIs and search features where possible. Collect metadata such as:
  - repository name
  - URL
  - description
  - stars and recent activity
  - language/topic tags
  - README excerpt when available and appropriate
  - creation or update time
- **Release** data may later enrich a GitHub item; releases are not the primary digest row in this refactor.
- True star-velocity infrastructure and release-as-primary remain out of scope until after the sourcing refactor (Milestone 6+ as needed).

### Bilibili-Oriented Discovery

Start conservatively. The connector collects keyword/search-result metadata, uploader-targeted metadata (via request-provided handles/UIDs), and manually supplied video links. It should collect available metadata such as:

- video title
- URL
- author/uploader
- description
- tags
- publish time
- accessible transcript, subtitle, or text metadata when available

If transcript or deeper video content is unavailable, the agent must label the item as lower confidence and summarize only from available metadata.

Uploader targeting remains metadata-first in Milestone 1: collect uploader/video metadata when accessible, but do not require full transcript extraction for digest success.

#### Implementation: `bilibili-api-python` (refactor, 2026-05-19)

The Bilibili connector is implemented behind the shared `SourceConnector` protocol (`ConnectorRequest` → `ConnectorResult`). Internally it delegates to the community-maintained [bilibili-api-python](https://github.com/nemo2011/bilibili-api) package (PyPI: `bilibili-api-python`, docs: [bilibili-api dev docs](https://nemo2011.github.io/bilibili-api/)) instead of hand-rolled `httpx` calls to `api.bilibili.com`.

**Rationale**

- Raw HTTP access is brittle under Bilibili anti-bot (HTTP 412, HTML challenge pages, invalid JSON payloads).
- The library maintains endpoint knowledge, retries, and optional browser fingerprinting (`curl_cffi`) without duplicating that logic in this repo.
- The same library exposes subtitle and AI-summary APIs needed for a later transcript-enrichment milestone.

**External contract (unchanged)**

- Module: `src/ai_news_agent/connectors/bilibili.py`, class `BilibiliConnector`.
- Inputs: `ConnectorRequest` fields `topics`, `timeframe`, `max_items`, `bilibili_target_channels` / `target_channels`, `bilibili_manual_urls` / `manual_urls`.
- Outputs: `ConnectorResult` with `NewsItem` list, `ConnectorWarning` list, `raw_count`.
- Warning codes remain stable (`no_input`, `anti_bot_blocked`, `keyword_search_failed`, `space_search_failed`, `user_search_failed`, `view_fetch_failed`, `invalid_payload`, `metadata_limited`, `skipped_malformed_video`, `keyword_search_fallback`, `unresolved_channel`, `invalid_manual_url`, etc.).
- `intent.py`, `chat.py`, and LangGraph nodes are not changed by this refactor.

**Library API mapping**

| Connector behavior | Library entry point | Notes |
| --- | --- | --- |
| Keyword / topic search | `bilibili_api.search.search_by_type` with `SearchObjectType.VIDEO` | Replaces `/x/web-interface/search/type` |
| Timeframe filter | `time_start`, `time_end` (`YYYY-MM-DD`) on `search_by_type` | Derived from `ConnectorRequest.timeframe` (see below) |
| AI/tech zone bias | `video_zone_type` (e.g. `VideoZoneTypes.TECH`, `VideoZoneTypes.KNOWLEDGE`) | Optional narrowing for digest topics |
| Single video by URL/BV | `bilibili_api.video.Video(bvid=...).get_info()` | Replaces `/x/web-interface/view` |
| Uploader feed | `bilibili_api.user.User(uid=...).get_videos(pn=1, ps=...)` | Replaces `/x/space/arc/search` |
| Resolve handle → MID | `search_by_type` with `SearchObjectType.USER` | Replaces user search on same path |
| Future: subtitles | `Video.get_pages()`, `Video.get_subtitle(cid)` | Not used in Milestone 1 digest |
| Future: AI summary | `Video.get_ai_conclusion(...)` | Not used in Milestone 1 digest |

**Timeframe → search date range**

`ConnectorRequest.timeframe` is mapped to `time_start` / `time_end` for video search:

| `timeframe` value | `time_start` | `time_end` |
| --- | --- | --- |
| `today` | today (UTC) | today (UTC) |
| `this week`, `week` | 7 days ago | today |
| `this month`, `month` | 30 days ago | today |
| missing / unknown | omitted | omitted |

**Credentials**

Authentication is optional for read-only metadata collection but recommended when search is rate-limited or blocked.

Environment variables (see `.env.example`):

| Variable | Required | Purpose |
| --- | --- | --- |
| `BILIBILI_SESSDATA` | no | Session token from browser cookies |
| `BILIBILI_BILI_JCT` | no | CSRF token for logged-in calls |
| `BILIBILI_BUVID3` | no | Device id cookie (helps avoid HTTP 412) |

`env.get_bilibili_credential()` builds `bilibili_api.Credential(sessdata=..., bili_jct=..., buvid3=...)`. When unset, the connector runs without credentials and surfaces library/network failures as existing warning codes.

**Collection flow (unchanged logically)**

1. Keyword search: combined topics, then per-topic fallback if combined returns no items.
2. Channel feeds: numeric MID or resolved handle.
3. Manual URLs: BV id extraction, then `Video.get_info()`.
4. Dedupe by `source_id` (bvid), sort by `published_at`, cap at `max_items`.
5. Dedupe warnings by `(connector, code, message, detail)` before returning.

**Testing**

- Unit tests patch library functions (`search.search_by_type`, `Video.get_info`, `User.get_videos`, etc.) with `unittest.mock`; existing JSON fixtures remain valid because the library returns the same envelope shapes.
- Opt-in live smoke: `RUN_LIVE_BILIBILI=1` in `tests/test_connectors_bilibili_live.py`.

**Licensing note**

`bilibili-api-python` is GPL-3.0. This project uses it as a library dependency for personal learning tooling; comply with license terms if distributing binaries or combined works.

**Out of scope for this refactor**

- Changing `NewsItem` schema or adding `transcript` fields (deferred to transcript milestone).
- Wiring `get_subtitle` / `get_ai_conclusion` into summarization (deferred).
- Replacing GitHub connector or adding new source types.

### Hugging Face Model Momentum (Milestone 6)

Hugging Face is an opt-in model-momentum source whose atomic item is a **trending model**. It supports global trending and user-topic/task-filtered trending, ranked primarily by the Hub's native `trending_score`; 30-day downloads, likes, activity, and relevance are supporting evidence rather than model-quality claims.

Use the official `huggingface_hub` client. Preserve native model metrics as separately named source evidence rather than overloading GitHub stars or Bilibili views. Models only are in scope; datasets, Spaces, benchmarks, and adoption-velocity history are deferred.

### Zhihu Practitioner Insight (Milestone 6)

Zhihu is an opt-in Chinese-language practitioner source whose atomic item is one traceable **practitioner insight** returned by the official search API. Topic searches use bounded deterministic lenses for 实战/踩坑, 部署/成本, and 评测/对比, then deduplicate and rank by API relevance, lens/topic match, and returned-text completeness.

Use only returned search evidence. Do not crawl linked pages, infer popularity or freshness, or turn thin snippets into unsupported takeaways. Timeframe requests receive an explicit caveat because this search contract is relevance-based.

Detailed Milestone 6 behavior is specified in `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`.

### Future Sources

After Milestone 6, possible source expansion includes:

- arXiv or another primary academic source
- AI blogs and generic/curated RSS feeds (Juya remains a dedicated bulletin)
- general news or web search
- Bilibili transcript enrichment via `Video.get_subtitle` / `get_ai_conclusion` (library already integrated at connector layer)
- Optional GitHub enrichments: true star-velocity, release metadata on trending repos

## Data Model

The implementation should define a common item shape similar to:

```text
NewsItem
- id
- source_type
- source_name
- title
- url
- author
- published_at
- fetched_at
- language
- source_evidence (JSON-safe, source-native metrics and relevance evidence)
- content_excerpt
- transcript_available
- confidence
- tags
```

Ranking output should include:

```text
RankedItem
- news_item_id
- score
- rank
- ranking_reasons
- penalties
```

Digest output should include:

```text
Digest
- request
- timeframe
- generated_at
- selected_items
- partial_result_warnings
- follow_up_suggestions
```

## Reliability And Error Handling

- Every digest item must include a source URL.
- Connector failures should produce partial-results warnings instead of silent failure.
- An explicitly selected failed source must not be silently replaced with Juya.
- Missing transcript or content should be marked clearly.
- Low-confidence summaries should state the reason for lower confidence.
- Duplicate, stale, weakly sourced, or metadata-poor items should be penalized in ranking.
- The agent should avoid claiming facts that are not present in collected data.
- Source-native relevance or popularity must not be mislabeled as quality, freshness, or velocity.
- Logs should preserve enough context to debug failed or low-quality runs.

## Testing And Evaluation

MVP testing should include:

- unit tests for connectors with mocked responses
- unit tests for ranking with fixed candidate lists
- summarization format tests using golden sample inputs
- end-to-end smoke test that generates a small digest from fixture data

Milestone 2 tool-usage testing should include:

- unit tests for each tool schema and argument validation
- unit tests proving connector tools delegate to the existing `SourceConnector` contract
- follow-up chat tests where the model chooses digest-inspection tools and answers from tool observations
- failure-path tests where tool errors become caveats or partial-result warnings
- smoke tests that keep the deterministic digest workflow passing unchanged

Milestone 6 source-expansion testing should include:

- mocked Hugging Face global/topic discovery, native-trend evidence, malformed responses, and failure warnings
- mocked Zhihu deterministic lens expansion, bounded call count, dedupe, thin evidence, unsupported-timeframe caveat, and proof that linked pages are not fetched
- source-evidence persistence compatibility and kind-aware mixed ranking/rendering
- connector-tool, registry, CLI, Gradio, OpenClaw, and deterministic fake-mode parity
- full regression coverage for existing source and follow-up behavior

Manual quality evaluation should score early digests on:

- relevance
- source correctness
- summary faithfulness
- usefulness for learning
- clarity of follow-up suggestions

Automated LLM-as-judge evaluation can be added later after the workflow stabilizes.

## Milestones

### Milestone 1: Local Digest MVP

- Local chatbot interface
- GitHub connector
- Bilibili-oriented connector via `bilibili-api-python` (metadata-only digest)
- normalized item model
- ranking layer
- source-language digest generation
- local storage and inspectable artifacts
- basic tests and smoke test

### Milestone 2: LLM Tool Usage Layer

- Add a structured tool registry for LLM-callable follow-up and connector tools
- Implement follow-up tools for latest digest lookup, digest item lookup, source trace inspection, and ranking explanation
- Wrap GitHub and Bilibili connectors as LLM-callable search tools through the existing connector boundary
- Add a bounded LangGraph tool-calling loop for follow-up chat and controlled source exploration
- Log tool calls and surface tool failures as caveats or partial-result warnings
- Keep the deterministic Milestone 1 digest graph available as the stable default digest path

### Milestone 3: OpenClaw Adapter

- Register an OpenClaw tool such as `generate_ai_news_digest`
- Expose the Python agent through HTTP or CLI
- Return digest results through an OpenClaw-supported channel
- Preserve the same source traces and logging used by the local interface

### Milestone 4: Pydantic Schema + LangChain `@tool` Registry Migration

- Migrate `models.py` domain models and `tools/schemas.py` tool schemas from dataclasses to Pydantic v2
- Replace hand-written `*_to_dict` / `*_from_dict` / `_encode_value` serialization with `model_dump(mode="json")` / `model_validate()`; preserve stored SQLite row compatibility
- Migrate the custom tool registry to LangChain `@tool` / `BaseTool` with Pydantic `args_schema` (single source of truth for tool schemas, eliminating dual-schema drift)
- Keep the bounded LangGraph tool-calling loop, progress-line streaming, and `ToolObservation` return contract
- See `docs/superpowers/specs/2026-06-29-pydantic-and-langchain-tool-migration-design.md`

### Milestone 5: Source Role Split (before broader expansion)

Prerequisite for Milestone 6. Implements ADR-0001 / `CONTEXT.md` source language:

- Extract a first-class **Juya** connector (`SourceKind.JUYA`); stop routing bulletin ingestion through GitHub / `github_manual_urls`
- Re-purpose **GitHub** toward topic trending-repo discovery (stars × recency heuristic); remove Juya website/RSS ownership from the GitHub connector
- Change **default** digest sources to **Juya only**; GitHub and Bilibili opt-in via sources, intent, or platform targets (platform cue replaces Juya unless Juya also selected)
- Reject legacy `github.com/jujuyaya/juya-ai-daily` as a Juya target with guidance to `https://daily.juya.uk/`
- Kind-aware ranking features plus **segmented** mixed-digest presentation (intent-first section order; else Juya → GitHub → Bilibili)
- Update CLI/Gradio/OpenClaw docs and smoke commands accordingly
- Add `search_juya_ai_news` (or equivalent) through the existing connector-tool boundary when tools are updated

Out of scope for Milestone 5: arXiv, Hugging Face, generic RSS, true star-velocity, release-as-primary.

### Milestone 6: AI Ecosystem And Practitioner Signals

- Add a Hugging Face connector for global or topic/task-filtered **trending models**
- Add an official-API-only Zhihu connector for Chinese-language **practitioner insights**
- Preserve source-native evidence for transparent kind-aware ranking and caveats
- Expose both sources through the registry, workflow, tools, CLI, Gradio, and OpenClaw
- Keep Juya-only defaults, one overall mixed `top_n`, and sectional presentation
- Defer arXiv, generic RSS/blog sources, Hugging Face datasets/Spaces, and Zhihu crawling/direct-answer/hotlist capabilities
- See ADR-0002 / `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`

### Milestone 6.5: Hugging Face And Zhihu Rank Deep-Dive

- Specialize structured **rank** follow-up for Hugging Face and Zhihu using persisted evidence only (Juya pattern, not Bilibili live enrich)
- Hugging Face: **family card** at the same **display rank** as the comparison-table row
- Zhihu: one **practitioner-insight card**, evidence-first, no page fetch, no multi-result synthesis
- Keep existing phrases and OpenClaw `/followup` path taxonomy; do not reshape tool JSON or sources/study-first/caveats
- See ADR-0005 / Milestone 6.5 section of `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`

### Milestone 7: Memory, Scheduling, And Deployment

- Add scheduled daily or weekly digest generation
- Add richer local memory or vector search if stored digests become large
- Deploy the agent or a lightweight API
- Add automated quality evaluation

## Implementation Planning Defaults

- Local chatbot UI: Gradio.
- Model access: use an OpenAI-compatible client abstraction configured by environment variables, so the first implementation can work with the user's available API provider.
- Initial topic taxonomy: AI agents, model releases, RAG, multimodal AI, AI developer tools, and notable open-source repos.
- Default source set: **Juya only** for bare digests; Hugging Face, GitHub, Zhihu, and Bilibili require explicit sources, clear intent, or supported platform targets.
- Juya strategy: website RSS + per-issue markdown enrichment from `daily.juya.uk`; no GitHub-repo alias.
- GitHub query strategy: topic-scoped repository search scored as trending via stars × recency (transparent heuristic); README excerpt as evidence, not the story; releases optional later enrichment.
- Hugging Face strategy: models only; native Hub `trending_score` first, with global and topic/task-filtered modes and transparent supporting metrics. Rank follow-up is a persist-only **family card** (Milestone 6.5), not live Hub re-fetch.
- Zhihu strategy: official search API only; bounded deterministic practitioner lenses, relevance/lens/completeness ranking, no page fetch, no trend/freshness claim. Rank follow-up is a persist-only **practitioner-insight card** (Milestone 6.5).
- Bilibili strategy: `bilibili-api-python` for keyword search (with optional timeframe and TECH/KNOWLEDGE zone filters), uploader feeds, and manual BV/URL resolution; metadata-first, no transcript in digest MVP; optional `BILIBILI_*` credentials for anti-bot resilience.
- Mixed-digest presentation: one overall `top_n`, kind-aware scores, no source quotas, and sectional output (intent-first; fallback Juya → Hugging Face → GitHub → Zhihu → Bilibili).
- LLM tool strategy: use structured tool schemas with stable names and a bounded LangGraph tool-calling loop; connector wrappers follow each source's distinct product job.
- Default digest length: 5 ranked items overall per run, with the option to request a shorter or longer digest in chat.

