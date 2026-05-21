# AI News Research Agent Design

Date: 2026-05-02  
Amended: 2026-05-19 (Bilibili connector library refactor)
Amended: 2026-05-21 (Milestone 2 LLM tool usage layer)

## Summary

Build a local-first, on-demand AI News Research Chatbot for personal learning. The user asks for an AI digest, and the agent collects recent AI-related signals from GitHub and conservative Bilibili-oriented sources, ranks the most useful items, summarizes them in their source language, explains why they matter, suggests follow-up learning actions, and stores source traces for verification and follow-up chat.

OpenClaw is included as a planned Milestone 3 interface adapter, not as the MVP foundation.

## Goals

- Learn core agentic AI engineering patterns through a scoped, useful project.
- Support an on-demand chatbot workflow: ask for a digest, receive ranked summaries, and ask follow-up questions.
- Start with GitHub and Bilibili-oriented discovery while keeping source collection reliable and inspectable.
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

Initial connectors:

- GitHub connector
- Bilibili-oriented connector

Future connectors:

- arXiv
- Hugging Face
- RSS/blog sources
- general web search

### Ranking Layer

Scores and filters candidate items before summarization. Ranking should consider:

- freshness
- relevance to AI topics
- source quality
- popularity or engagement signal where available
- learning value for the user
- metadata completeness
- duplication with other candidates

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

Future connector tools should be added when the corresponding connectors exist, for example `search_arxiv_ai_news`, `search_huggingface_ai_news`, and RSS/blog search tools after Milestone 4 source expansion.

The Milestone 2 agent should use a bounded tool-calling loop: the model decides when to call a registered tool, a tool execution node runs the call, and the model then answers from the returned observations. Tool calls must have typed input schemas, stable tool names, concise descriptions, and outputs that can be serialized to JSON or markdown for the final answer.

Reliability constraints:

- Tool calls must be logged with tool name, arguments, success/failure, and summarized output.
- Tool failures should become user-facing caveats or partial-result warnings, not crashes.
- Connector tools must preserve source URLs and confidence/caveat metadata.
- Follow-up answers must stay grounded in tool results and saved digest traces.
- The tool layer must not require OpenClaw, arXiv, Hugging Face, RSS, scheduling, vector search, or deployment.

## OpenClaw Integration

OpenClaw should be integrated as Milestone 3, after the local agent and internal LLM tool usage layer work.

OpenClaw's role is an outer assistant gateway, not the core retrieval engine. It can receive messages from channels such as Telegram, Slack, Discord, or webchat, then call the AI News Research Agent through a registered tool.

Target flow:

```text
OpenClaw channel message
  -> OpenClaw Gateway
  -> registered tool: generate_ai_news_digest
  -> local or hosted Python agent API/CLI
  -> GitHub and Bilibili connectors
  -> ranked digest
  -> OpenClaw reply
```

The OpenClaw adapter should call the same core Python workflow used by the local chatbot. This keeps the core agent independent from any single interface.

Primary adapter boundary:

- HTTP: `POST /digest`

Fallback adapter boundary:

- CLI: `python -m ai_news_agent digest --timeframe today --sources github,bilibili`

Source selection for all entrypoints (CLI, Gradio, future OpenClaw tool) should map to `DigestRequest.connector_names` via the shared registry in `ai_news_agent.sources`. `None` means all injected connectors; a non-empty list runs only those named connectors.

OpenClaw should not be required for MVP success.

## Data Flow

1. User asks the chatbot for an AI digest.
2. Agent interprets the request into topic, timeframe, source, language preferences, and optional source-targeting inputs (for example, specific Bilibili uploader handles/UIDs or manually supplied links).
3. GitHub and Bilibili-oriented connectors collect candidate items.
4. Candidates are normalized into a shared `NewsItem` format.
5. Ranking layer filters duplicates and weak items, then selects top candidates.
6. Summarization layer creates source-language summaries, significance notes, and learning suggestions.
7. Storage layer saves source metadata, ranking decisions, and final digest.
8. Follow-up chat uses the saved digest and source traces to answer questions.

## Source Strategy

### GitHub

Use official GitHub APIs and search features where possible. The connector should collect metadata such as:

- repository name
- URL
- description
- stars and recent activity
- language/topic tags
- README excerpt when available and appropriate
- creation or update time

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

### Future Sources

After the core digest loop works, add connectors for:

- arXiv
- Hugging Face
- AI blogs and RSS feeds
- general news or web search
- Bilibili transcript enrichment via `Video.get_subtitle` / `get_ai_conclusion` (library already integrated at connector layer)

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
- raw_metadata
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
- Missing transcript or content should be marked clearly.
- Low-confidence summaries should state the reason for lower confidence.
- Duplicate, stale, weakly sourced, or metadata-poor items should be penalized in ranking.
- The agent should avoid claiming facts that are not present in collected data.
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

### Milestone 4: Broader Research Sources

- Add arXiv connector
- Add Hugging Face connector
- Add RSS/blog sources
- Improve ranking across source types

### Milestone 5: Memory, Scheduling, And Deployment

- Add scheduled daily or weekly digest generation
- Add richer local memory or vector search if stored digests become large
- Deploy the agent or a lightweight API
- Add automated quality evaluation

## Implementation Planning Defaults

- Local chatbot UI: Gradio.
- Model access: use an OpenAI-compatible client abstraction configured by environment variables, so the first implementation can work with the user's available API provider.
- Initial topic taxonomy: AI agents, model releases, RAG, multimodal AI, AI developer tools, and notable open-source repos.
- Initial GitHub query strategy: search recent repositories and topics using the taxonomy above, with ranking boosted by freshness, stars, recent activity, and README relevance.
- Initial Bilibili strategy: `bilibili-api-python` for keyword search (with optional timeframe and TECH/KNOWLEDGE zone filters), uploader feeds, and manual BV/URL resolution; metadata-first, no transcript in digest MVP; optional `BILIBILI_*` credentials for anti-bot resilience.
- Initial LLM tool strategy: use structured tool schemas with stable names and a bounded LangGraph tool-calling loop; start with follow-up inspection tools plus GitHub/Bilibili connector wrappers.
- Default digest length: 5 ranked items per run, with the option to request a shorter or longer digest in chat.

