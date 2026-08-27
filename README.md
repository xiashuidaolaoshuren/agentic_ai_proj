# AI News Research Agent

Local-first Python agent that generates **on-demand AI news digests** from **Juya** (default daily bulletin), optional **Hugging Face** trending models, optional **GitHub** trending-repo signals, optional **Zhihu** practitioner insights, and conservative **Bilibili**-oriented sources. It ranks candidates, summarizes them with an LLM (or offline fakes), persists runs to SQLite, and exposes a **CLI** plus optional **Gradio** chat UI.

Design details: [AI News Research Agent design](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md).

**Milestone 1 (Local Digest MVP)** is complete: LangGraph workflow, storage, connectors, ranking, summarization, chat follow-ups, CLI smoke mode, Gradio UI, and tests.

**Milestone 2 (LLM tool usage layer)** is complete: bounded tool-calling for follow-up inspection and connector search; Gradio wires a tool agent in live and fake modes. Plan: [Milestone 2 implementation plan](docs/superpowers/plans/2026-05-21-llm-tool-usage-layer-plan.md).

**Milestone 3 (OpenClaw integration)** is complete: a local OpenClaw skill delegates digest requests to the existing `ai-news-agent` CLI via a thin adapter boundary. Plan: [Milestone 3 OpenClaw integration plan](docs/superpowers/plans/2026-06-08-openclaw-integration-plan.md).

**Milestone 6 (AI ecosystem and practitioner signals)** is complete: opt-in Hugging Face trending-model and Zhihu practitioner-insight connectors, kind-aware ranking, Gradio/CLI/OpenClaw source names, and dedicated search tools. Bare digests stay Juya-only. Design: [Milestone 6 design](docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md). ADR: [ADR-0002](docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md).

## Prerequisites

- Python **3.11+** (see [.python-version](.python-version) for the pinned dev version)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip + venv

## Install

From the repo root:

```bash
uv sync --group dev
```

Without uv:

```bash
pip install -e .
pip install "pytest>=8.0"
```

If `import ai_news_agent` fails outside an editable install, use `PYTHONPATH=src` or install with `-e`.

## Environment variables

Copy [`.env.example`](.env.example) to `.env` and fill values as needed (never commit secrets).

**Local entrypoints auto-load `.env`** when you run `ai-news-agent` or `python -m ai_news_agent.app.gradio_app`. Lookup order: `./.env` in the current working directory, then the first `.env` found in parent directories. Variables already exported in your shell are **not** overwritten.

| Variable | When needed | Purpose |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Live digest + live Gradio tool follow-ups | Digest summarization (`build_chat_model`) and tool-calling follow-ups (`build_tool_chat_model`) via [`llm.py`](src/ai_news_agent/llm.py) |
| `OPENAI_BASE_URL` | Optional | Custom gateway / compatible endpoint (applies to both summarization and tool agent) |
| `OPENAI_MODEL` | Optional | Model name (default `gpt-4o-mini`) |
| `GITHUB_TOKEN` | Optional | Higher GitHub API rate limits ([`connectors/github.py`](src/ai_news_agent/connectors/github.py)) |
| `HUGGINGFACE_TOKEN` | Optional | Higher Hugging Face Hub rate limits ([`connectors/huggingface.py`](src/ai_news_agent/connectors/huggingface.py)) |
| `ZHIHU_ACCESS_SECRET` | Live Zhihu practitioner search | Zhihu Developer Platform Access Secret, sent as Bearer ([`env.py`](src/ai_news_agent/env.py)) |
| `BILIBILI_SESSDATA` | Optional | Bilibili session token ([`env.py`](src/ai_news_agent/env.py)) |
| `BILIBILI_BILI_JCT` | Optional | Bilibili CSRF token (often required with `SESSDATA`) |
| `BILIBILI_BUVID3` | Optional | Bilibili device id cookie (helps avoid HTTP 412) |
| `BILIBILI_HTTP_CLIENT` | Optional | `curl_cffi`, `httpx`, or `aiohttp` (if installed in bilibili-api) |
| `BILIBILI_PROXY_URL` | Optional | HTTP proxy for bilibili-api requests |
| `BILIBILI_IMPERSONATE` | Optional | Browser TLS fingerprint for `curl_cffi` (e.g. `chrome131`) |
| `BILIBILI_TIMEOUT_SECONDS` | Optional | Request timeout override for bilibili-api |

SQLite defaults to `./digest.sqlite` in the current working directory unless you pass `--db-path`. Database files matching `*.db` are gitignored.

## Quick start (offline, no API keys)

Smoke acceptance tests (no network):

```bash
uv run pytest tests/test_mvp_smoke.py -q
```

One-shot fake digest (deterministic connectors + summarizer). Omitted `--sources` stays **Juya-only**:

```bash
uv run ai-news-agent digest --fake
uv run ai-news-agent digest --fake --sources huggingface
uv run ai-news-agent digest --fake --sources zhihu
uv run ai-news-agent digest --fake --sources huggingface,zhihu,github
```

Gradio chat UI in offline mode:

```bash
uv run python -m ai_news_agent.app.gradio_app --fake
```

Open the printed URL (default port **7860**). Try **“Give me today's AI digest”**, then **“show sources”** (structured follow-up). Try an open-ended question such as **“Why does the top item matter?”** to see fake tool-agent behavior (fixed offline reply, not live search).

## Live digest (network + LLM)

Requires `OPENAI_API_KEY` (in `.env` or your shell). Optionally set `GITHUB_TOKEN`, `HUGGINGFACE_TOKEN`, and `ZHIHU_ACCESS_SECRET` for reliability.

Bare request (Juya-only default):

```bash
uv run ai-news-agent digest --timeframe today
```

Explicit mixed sources (GitHub + Bilibili, no Juya):

```bash
uv run ai-news-agent digest --sources github,bilibili --topics "RAG,agents" --timeframe today
```

Hugging Face trending models (opt-in; Hub popularity is not model quality):

```bash
uv run ai-news-agent digest --sources huggingface --topics RAG --timeframe today
```

Zhihu practitioner insights (opt-in; official search only, no page crawl):

```bash
uv run ai-news-agent digest --sources zhihu --topics RAG --timeframe today
```

Useful flags:

- `--sources` — comma-separated: `juya`, `huggingface`, `github`, `zhihu`, `bilibili` (default: `juya`)
- `--topics` — comma-separated topic strings (omit for built-in defaults)
- `--timeframe` — passed through to connectors (e.g. `today`)
- `--top-n`, `--max-items` — ranking/collection limits
- `--db-path` — SQLite path for [`DigestStore`](src/ai_news_agent/storage.py)

Console entrypoint: [`ai-news-agent`](pyproject.toml) → [`cli.main`](src/ai_news_agent/cli.py).

## Gradio chatbot

Launch:

```bash
uv run python -m ai_news_agent.app.gradio_app
```

Offline:

```bash
uv run python -m ai_news_agent.app.gradio_app --fake --port 7860 --db-path ./digest.sqlite
```

The UI delegates to [`ChatService`](src/ai_news_agent/chat.py):

- **Digest requests** (phrases like “digest”, URLs, source toggles) run the **deterministic LangGraph workflow** — collect, rank, summarize, persist — with streaming progress, then stream the final digest text.
- **Follow-ups** use the latest saved digest from SQLite. Routing order:
  1. **Structured** prompts → instant answers from persisted traces (no LLM tools): sources, ranking / study-first, caveats.
  2. **Open-ended** or source-exploration questions → **bounded tool agent** when configured (Gradio live and fake modes inject `tool_agent_runner` in [`gradio_app.py`](src/ai_news_agent/app/gradio_app.py)).
  3. **Legacy fallback** → `chat_model.generate_followup_reply` only if no tool agent is configured (not used by default live Gradio).
  4. **Guidance** message if neither tool agent nor chat model is available.

Example prompts live in a collapsible **Example prompts** panel below the chat. Clicking an example sets **Sources** to match that prompt (Items per source is unchanged). Digest responses show live workflow progress (collecting, ranking, summarizing, etc.), then stream the final digest text incrementally in the chat bubble.

### Milestone 2 — Follow-up tools (Gradio / ChatService)

**Deterministic digest** (unchanged): LangGraph path for digest keywords, targeted URLs/channels, and session source toggles.

**Follow-up modes** after a digest is saved:

| Mode | What it does | Example |
|------|----------------|---------|
| Structured | Fast answers from SQLite traces | `show sources`, `Which item should I study first?`, `Any confidence caveats?` |
| Tool agent | Bounded LangGraph loop over six registry tools | `Why does the top item matter for RAG agents?`, `Search GitHub for langgraph agents` |
| Legacy LLM | Grounded reply via `generate_followup_reply` | Only when `tool_agent_runner` is not set |
| Guidance | Static hint to use structured prompts | When no model or tool agent is configured |

Registry tools (live mode): `load_latest_digest`, `get_digest_item`, `get_source_trace`, `get_ranking_explanation`, `search_juya_ai_news`, `search_github_ai_news`, `search_bilibili_ai_news`, `search_huggingface_trending_models`, `search_zhihu_practitioner_insights` (see [`tools/registry.py`](src/ai_news_agent/tools/registry.py)).

**Fake mode (`--fake`):**

- Digest: `FakeDigestModel` + fake Juya/Hugging Face/GitHub/Zhihu/Bilibili connectors (no API keys).
- Structured follow-ups: work as in live mode (deterministic from stored traces).
- Open-ended follow-ups: return a **fixed offline message** from the fake tool agent (no real tool-calling model, no connector search). Use structured prompts for reliable offline demos.

**Live Gradio:** requires `OPENAI_API_KEY` for both digest summarization and tool-calling follow-ups (`build_chat_model` + `build_tool_chat_model`).

### Example prompts (after a digest)

| Category | Example |
|----------|---------|
| Digest | `Give me today's AI digest` |
| Structured | `show sources`, `Which item should I study first?`, `Any confidence caveats?` |
| Open-ended | `Why does the top item matter for RAG agents?` |
| Source exploration | `Search Juya for agent news`, `Search Hugging Face for trending RAG models`, `Search GitHub for langgraph agents`, `Search Zhihu for practitioner insights on RAG`, `Search Bilibili for RAG tutorials` |

In **fake mode**, open-ended and source-exploration prompts return the offline tool-agent guidance string, not live search results.

### Source toggles and selection

Gradio shows **session-sticky** checkboxes for `juya`, `huggingface`, `github`, `zhihu`, and `bilibili` (**Juya selected by default**). Each digest run uses the current checkbox selection via `DigestRequest.connector_names`. Use **Items per source** (default 5, range 1–20) to cap how many ranked items appear from each enabled source in mixed digests.

Bare digest requests (no source toggles or explicit `--sources`) resolve to **Juya-only** via [`DEFAULT_SOURCE_NAMES`](src/ai_news_agent/sources.py). Select multiple checkboxes or pass a comma-separated `--sources` list for a **mixed digest**; section order is primary intent first, otherwise Juya → Hugging Face → GitHub → Zhihu → Bilibili (empty sections omitted).

You can override the toggles for a single request with natural-language phrases:

- `Give me today's AI digest` (Juya-only default)
- `Give me today's AI digest from github only`
- `huggingface only digest today`
- `trending RAG models on hugging face`
- `zhihu practitioner insights on RAG`
- `bilibili only digest today`
- `use juya and huggingface for today's digest`

CLI, Gradio, and OpenClaw share the canonical source registry in [`sources.py`](src/ai_news_agent/sources.py). The OpenClaw adapter maps hints to the same `DigestRequest.connector_names` field via CLI flags.

### Targeted digests (URLs and channels)

In chat, you can include GitHub repo URLs, Bilibili video URLs, or channel hints in the same message as “digest”. The app parses them via [`intent.py`](src/ai_news_agent/intent.py) and skips broad topic keyword search when explicit targets are present.

Examples:

- `Digest https://daily.juya.uk/` (Juya daily bulletin; use `--output-style editorial --output-language zh-CN` for a compact Chinese issue index)
- `Digest https://github.com/langchain-ai/langgraph`
- `Digest https://www.bilibili.com/video/BV1xxxxx`
- `Digest bilibili channel 285286947`
- `Digest github user openai and https://www.bilibili.com/video/BV1demo0001`
- `Give me today's AI digest` (Juya-only default topics + timeframe when mentioned)

**Juya targeting is website-only.** The legacy GitHub repo `jujuyaya/juya-ai-daily` is **rejected** with an actionable error pointing to `https://daily.juya.uk/` (see [`intent.py`](src/ai_news_agent/intent.py)).

If Bilibili requests fail with HTTP 412:

1. Confirm startup log shows `bilibili env: ... credential_available=True`.
2. If cookies are missing, set `BILIBILI_SESSDATA`, `BILIBILI_BILI_JCT`, and `BILIBILI_BUVID3` in `.env` (from browser cookies).
3. If cookies are loaded but you still see `anti_bot_blocked`, tune network settings:
   - `BILIBILI_HTTP_CLIENT=curl_cffi` (when installed)
   - `BILIBILI_IMPERSONATE=chrome131`
   - `BILIBILI_PROXY_URL=http://127.0.0.1:7890` (or your proxy)
4. Prefer specific video URLs when channel feeds are blocked.
5. After a run, ask **show caveats** to distinguish `auth_required_*` (login) vs `anti_bot_blocked` (WAF/fingerprint).
6. Some videos have **no CC/AI subtitles** at all; follow-up enrichment will show `subtitle_unavailable` (not a network or login failure).

### Logging

Gradio and CLI share structured logging to **terminal** and a rotating file (default: `logs/ai-news-agent.log`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `AI_NEWS_AGENT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `AI_NEWS_AGENT_LOG_PATH` | `logs/ai-news-agent.log` | Log file location |
| `AI_NEWS_AGENT_LOG_MAX_BYTES` | `2000000` | Rotate when file exceeds this size |
| `AI_NEWS_AGENT_LOG_BACKUP_COUNT` | `3` | Number of rotated backups kept |

On failures, the Gradio UI shows a short user-friendly message; full stack traces are written to the terminal and log file.

## OpenClaw integration (Milestone 3)

Use [OpenClaw](https://docs.openclaw.ai/) as an outer gateway to trigger digest generation through natural-language prompts. OpenClaw handles channels and sessions; this project still runs retrieval, ranking, summarization, and persistence through the existing CLI workflow.

Design: [OpenClaw integration design](docs/superpowers/specs/2026-06-08-openclaw-integration-design.md).

### Prerequisites

- **OpenClaw Gateway** installed and running locally (loopback / trusted workspace).
- **uv** on PATH (required by the skill metadata).
- This repository installed (`uv sync --group dev` from repo root).
- **Live digests:** `OPENAI_API_KEY` in `.env` or your shell (same as CLI/Gradio live mode).
- Optional: `GITHUB_TOKEN`, `HUGGINGFACE_TOKEN`, `ZHIHU_ACCESS_SECRET`, Bilibili cookie vars (see [Environment variables](#environment-variables)).

### Skill setup

The skill definitions live in this repo at [`openclaw/skills/ai-news-digest/SKILL.md`](openclaw/skills/ai-news-digest/SKILL.md) and [`openclaw/skills/ai-news-followup/SKILL.md`](openclaw/skills/ai-news-followup/SKILL.md).

**Start the warm digest service** (once per session; keeps model and connectors warm):

```bash
uv run ai-news-agent service --port 8765
```

Optional: set `AI_NEWS_AGENT_SERVICE_URL` if not using the default `http://127.0.0.1:8765`.

Make the skill visible to your OpenClaw workspace (adjust paths for your OS):

```bash
# Example: symlink repo skills into OpenClaw workspace skills directory
ln -s "$(pwd)/openclaw/skills/ai-news-digest" ~/.openclaw/workspace/skills/ai-news-digest
ln -s "$(pwd)/openclaw/skills/ai-news-followup" ~/.openclaw/workspace/skills/ai-news-followup
```

After adding or updating the skill, start a new OpenClaw session (e.g. `/new` in chat) or restart the gateway so it reloads skills.

The skill instructs OpenClaw to use the `exec` tool with a **fixed command template** —
`uv run ai-news-agent openclaw-digest ...` — run from this repository root. The client
calls the warm local digest service (`ai-news-agent service`). Argument mapping (timeframe,
sources, topics) aligns with [`adapters/openclaw.py`](src/ai_news_agent/adapters/openclaw.py).

Latency baseline and comparison procedure: [`docs/benchmarks/openclaw-latency-baseline.md`](docs/benchmarks/openclaw-latency-baseline.md).

### Usage

Send natural-language digest requests through any OpenClaw-connected channel. The skill maps intent to CLI flags and returns the markdown digest stdout unchanged (including source links and connector caveats).

| Smoke prompt | Expected CLI shape |
|--------------|-------------------|
| Give me today's AI digest. | `openclaw-digest --timeframe today --sources juya` |
| Give me today's AI digest from GitHub only. | `openclaw-digest --timeframe today --sources github` |
| Give me this week's AI digest on RAG and agents. | `openclaw-digest --timeframe last_7_days --sources juya --topics RAG,agents` |
| Give me Hugging Face trending RAG models. | `openclaw-digest --message "trending RAG models on hugging face"` |
| Give me Zhihu practitioner insights on RAG. | `openclaw-digest --message "zhihu practitioner insights on RAG"` |
| Give me a mixed digest from GitHub and Bilibili. | `openclaw-digest --timeframe today --sources github,bilibili` |
| Digest bilibili video BV1gRJs63EYX | `openclaw-digest --message "Digest bilibili video BV1gRJs63EYX"` |
| Digest https://github.com/langchain-ai/langgraph | `openclaw-digest --message "Digest https://github.com/langchain-ai/langgraph"` |
| Digest https://daily.juya.uk/ | `openclaw-digest --message "Digest https://daily.juya.uk/" --output-style editorial --output-language zh-CN` |
| Digest https://github.com/jujuyaya/juya-ai-daily | **Rejected** — use `https://daily.juya.uk/` instead |
| Digest bilibili channel 285286947 | `openclaw-digest --message "Digest bilibili channel 285286947"` |

Full commands (from repo root, service running):

```bash
uv run ai-news-agent openclaw-digest --timeframe today --sources juya
uv run ai-news-agent openclaw-digest --timeframe today --sources github,bilibili
uv run ai-news-agent openclaw-digest --message "Digest bilibili video BV1gRJs63EYX"
uv run ai-news-agent openclaw-digest --message "Digest https://daily.juya.uk/" --output-style editorial --output-language zh-CN
uv run ai-news-agent openclaw-followup --message "follow up on item 1"
```

Targeted Juya digests use **`https://daily.juya.uk/` only** (not the legacy `jujuyaya/juya-ai-daily` GitHub repo). Ingestion reads the website RSS feed, then enriches each issue from `daily.juya.uk/markdown/{date}.md` when available (falling back to RSS `content:encoded`). Use `--output-style editorial --output-language zh-CN` for a compact Chinese issue index. Ask for a specific issue with `openclaw-followup --message "Digest the first news"` to expand sub-news from persisted issue evidence.

Targeted prompts must route through `openclaw-digest --message` (not `web_fetch` or manual API scraping).

### Structured follow-up (OpenClaw)

After generating a digest, use the **`ai-news-followup`** skill for deterministic inspection of the latest saved digest (same `digest.sqlite` as the warm service):

| Smoke prompt | Expected CLI shape |
|--------------|-------------------|
| Show sources | `openclaw-followup --message "show sources"` |
| Which item should I study first? | `openclaw-followup --message "which item should I study first"` |
| Follow up on item 1 | `openclaw-followup --message "follow up on item 1"` |
| Digest the first news (Juya deep dive) | `openclaw-followup --message "Digest the first news"` |
| Follow up on the second one | `openclaw-followup --message "follow up on the second one"` |
| Show caveats | `openclaw-followup --message "show caveats"` |

```bash
uv run ai-news-agent openclaw-followup --message "show sources"
uv run ai-news-agent openclaw-followup --message "follow up on item 1"
```

Rank-targeted follow-up uses those same phrases and the latest digest **display rank** (global list order). It is persist-only: no Hub re-fetch and no Zhihu page crawl. Kind-specific cards:

- **Juya** daily issues: **issue deep-dive** with sub-news from persisted website markdown
- **Hugging Face**: **family card** from saved Hub stats / Also variants / snippet (Hub card text saved at digest collection, not fetched live on follow-up; Hub trending is popularity, not quality)
- **Zhihu**: **practitioner-insight card** from saved search evidence (搜索相关性 is official-search relevance, not 热度)
- **GitHub / Bilibili**: generic digest-item reprint

Open-ended follow-up Q&A is still **not** supported in OpenClaw; use Gradio for tool-agent follow-ups.

Offline smoke (no API key, no network) — run directly from repo root:

```bash
uv run ai-news-agent digest --fake --timeframe today
uv run ai-news-agent digest --fake --timeframe today --sources huggingface
uv run ai-news-agent digest --fake --timeframe today --sources zhihu
uv run ai-news-agent digest --fake --timeframe today --sources huggingface,zhihu,github
uv run ai-news-agent digest --fake --timeframe today --sources github,bilibili
```

Live equivalent (Juya-only default):

```bash
uv run ai-news-agent digest --timeframe today
```

Live mixed sources (explicit opt-in):

```bash
uv run ai-news-agent digest --timeframe today --sources github,bilibili
```

### Security notes

- Keep the gateway on loopback / trusted local contexts only.
- Commands use validated tokens; do not interpolate raw user text into shell strings.
- OpenClaw supports **structured** follow-up only (`openclaw-followup`); open-ended Q&A remains in Gradio.

## Tests

Full suite:

```bash
uv run pytest
```

Milestone 1 smoke only:

```bash
uv run pytest tests/test_mvp_smoke.py -q
```

Optional live Bilibili URL smoke (network; uses a fixed public BV id):

```bash
RUN_LIVE_BILIBILI=1 uv run pytest -m live tests/test_connectors_bilibili_live.py -q
```

Set `BILIBILI_SESSDATA`, `BILIBILI_BILI_JCT`, and `BILIBILI_BUVID3` in `.env` if the live test reports HTTP 412.

## Known limits

**Connectors:**

- **Juya** is the **default bare digest** source (`daily.juya.uk` RSS + per-issue markdown enrichment). Target the website URL only; the legacy GitHub repo alias is rejected.
- **Hugging Face** is an **opt-in** Hub-native **trending models** source (global or topic/task-filtered). Ranking uses Hub `trending_score` plus downloads/likes tie-breakers; Hub popularity is **not** model quality. Models only — not datasets or Spaces.
- **GitHub** opt-in collection ranks repositories with a **momentum** score (star count × recency). This is a transparent heuristic for trending signal, **not** historical star velocity or true growth rate.
- **Zhihu** is an **opt-in practitioner-insight** source. Collection uses the official search API only (deterministic 实战/踩坑, 部署/成本, 评测/对比 lenses; max three calls). Rankable evidence is API relevance, lens match, and returned-text completeness — not popularity or freshness. Linked pages are never fetched. Thin results are discovery-only.
- **Bilibili** is **metadata-first** at digest time; follow-up enrichment can add transcripts when subtitle tracks exist. Many videos have no published CC/AI subtitles (`subtitle_unavailable`). Items are labeled lower confidence when content is thin (see [`connectors/bilibili.py`](src/ai_news_agent/connectors/bilibili.py)).

**Milestone 2 tool layer:**

- Tool agent has a **bounded iteration cap**; very complex multi-step questions may hit the fallback message.
- **Fake mode** does not run a real tool-calling model or live connector search for open-ended prompts.
- **Out of scope:** scheduled runs, cloud deployment, arXiv / generic RSS connectors, Hugging Face datasets/Spaces, Zhihu hotlist/direct-answer/page crawl, vector RAG, OpenClaw follow-up orchestration (see design spec milestones).

**Milestone 3 OpenClaw:**

- Digest generation only via CLI delegation; no gateway-native TypeScript plugin.
- OpenClaw supports structured follow-up via `openclaw-followup`; open-ended Q&A in channels uses Gradio.

## Documentation

- [Implementation plan (T1–T14, Milestone 1)](docs/superpowers/plans/2026-05-02-ai-news-research-agent-plan.md)
- [Milestone 2 LLM tool usage layer plan](docs/superpowers/plans/2026-05-21-llm-tool-usage-layer-plan.md)
- [Milestone 3 OpenClaw integration plan](docs/superpowers/plans/2026-06-08-openclaw-integration-plan.md)
- [Milestone 3 OpenClaw integration design](docs/superpowers/specs/2026-06-08-openclaw-integration-design.md)
- [Design spec](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md)
- [Milestone 6 AI ecosystem and practitioner signals design](docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md)
- [Milestone 6 implementation plan](docs/superpowers/plans/2026-08-16-ai-ecosystem-and-practitioner-signals-plan.md)
- [ADR-0002 Milestone 6 source roles](docs/adr/0002-milestone-6-ecosystem-and-practitioner-signals.md)
