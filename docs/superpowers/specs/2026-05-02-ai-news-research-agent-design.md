# AI News Research Agent Design

Date: 2026-05-02

## Summary

Build a local-first, on-demand AI News Research Chatbot for personal learning. The user asks for an AI digest, and the agent collects recent AI-related signals from GitHub and conservative Bilibili-oriented sources, ranks the most useful items, summarizes them in their source language, explains why they matter, suggests follow-up learning actions, and stores source traces for verification and follow-up chat.

OpenClaw is included as a planned Milestone 2 interface adapter, not as the MVP foundation.

## Goals

- Learn core agentic AI engineering patterns through a scoped, useful project.
- Support an on-demand chatbot workflow: ask for a digest, receive ranked summaries, and ask follow-up questions.
- Start with GitHub and Bilibili-oriented discovery while keeping source collection reliable and inspectable.
- Preserve source URLs, collected metadata, ranking decisions, and generated outputs for debugging.
- Keep the architecture modular so later sources and interfaces can be added without rewriting the core agent.

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

## OpenClaw Integration

OpenClaw should be integrated as Milestone 2, after the local agent works.

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

OpenClaw should not be required for MVP success.

## Data Flow

1. User asks the chatbot for an AI digest.
2. Agent interprets the request into topic, timeframe, source, and language preferences.
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

Start conservatively. The connector may use keyword/search-result metadata and manually supplied video links if needed. It should collect available metadata such as:

- video title
- URL
- author/uploader
- description
- tags
- publish time
- accessible transcript, subtitle, or text metadata when available

If transcript or deeper video content is unavailable, the agent must label the item as lower confidence and summarize only from available metadata.

### Future Sources

After the core digest loop works, add connectors for:

- arXiv
- Hugging Face
- AI blogs and RSS feeds
- general news or web search
- deeper Bilibili video extraction if reliable and appropriate

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
- conservative Bilibili-oriented connector
- normalized item model
- ranking layer
- source-language digest generation
- local storage and inspectable artifacts
- basic tests and smoke test

### Milestone 2: OpenClaw Adapter

- Register an OpenClaw tool such as `generate_ai_news_digest`
- Expose the Python agent through HTTP or CLI
- Return digest results through an OpenClaw-supported channel
- Preserve the same source traces and logging used by the local interface

### Milestone 3: Broader Research Sources

- Add arXiv connector
- Add Hugging Face connector
- Add RSS/blog sources
- Improve ranking across source types

### Milestone 4: Memory, Scheduling, And Deployment

- Add scheduled daily or weekly digest generation
- Add richer local memory or vector search if stored digests become large
- Deploy the agent or a lightweight API
- Add automated quality evaluation

## Implementation Planning Defaults

- Local chatbot UI: Gradio.
- Model access: use an OpenAI-compatible client abstraction configured by environment variables, so the first implementation can work with the user's available API provider.
- Initial topic taxonomy: AI agents, model releases, RAG, multimodal AI, AI developer tools, and notable open-source repos.
- Initial GitHub query strategy: search recent repositories and topics using the taxonomy above, with ranking boosted by freshness, stars, recent activity, and README relevance.
- Initial Bilibili strategy: keyword-based discovery plus manually supplied links when needed; do not require brittle deep crawling for MVP success.
- Default digest length: 5 ranked items per run, with the option to request a shorter or longer digest in chat.

