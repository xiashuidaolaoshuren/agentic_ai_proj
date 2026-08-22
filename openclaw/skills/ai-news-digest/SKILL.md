---
name: ai-news-digest
description: "Generate an AI news digest from Juya (default), Hugging Face, GitHub, Zhihu, or Bilibili via the local warm digest service. Use exec to call openclaw-digest — never use web_fetch."
user-invocable: true
metadata: {"openclaw":{"requires":{"bins":["uv"]}}}
---

# AI News Digest

Generate a markdown AI news digest by calling the **local warm digest service** through
`ai-news-agent openclaw-digest`. OpenClaw is the channel gateway; this project handles
retrieval, ranking, summarization, and persistence.

> **IMPORTANT:** Never use `web_fetch`, RSS lookups, or manual scraping for digest or follow-up requests. Always use `exec` to call `openclaw-digest` or `openclaw-followup`. This applies to `daily.juya.uk`, Hugging Face, GitHub, Zhihu, and Bilibili requests equally.

## When To Use

Activate this skill when the user asks for a digest in natural language, including:

**Broad multi-source digests**

- "Give me today's AI digest."
- "Give me today's AI digest from GitHub only."
- "Give me this week's AI digest on RAG and agents."
- "Give me Hugging Face trending RAG models."
- "Give me Zhihu practitioner insights on RAG."

**Targeted digests (single URL, BV id, or channel)**

- "Digest bilibili video BV1gRJs63EYX"
- "Digest https://www.bilibili.com/video/BV1gRJs63EYX"
- "Digest https://github.com/langchain-ai/langgraph"
- "Digest https://daily.juya.uk/"
- "Digest https://daily.juya.uk/issues/2026-06-19/"
- "Digest bilibili channel 285286947"

Targeted requests are **in scope** for this skill. Never treat them as generic research.

Do not use this skill for follow-up Q&A, scheduled digests, or non-digest research tasks.
Use the separate **`ai-news-followup`** skill for structured follow-up (show sources, study
first, show caveats) after a digest has been generated.

## Prerequisites

- **Digest service running** (start once per machine/session):

```bash
uv run ai-news-agent service --port 8765
```

- **Required:** `uv` on PATH (enforced via skill metadata).
- **Live runs:** `OPENAI_API_KEY` in `.env` or shell (service inherits env on start).
- **Workspace:** Run client commands from the `agentic_ai_proj` repository root.

Optional env: `AI_NEWS_AGENT_SERVICE_URL` (default `http://127.0.0.1:8765`).

## Argument Mapping

Map user intent into constrained CLI options. Defaults and aliases match
`ai_news_agent.adapters.openclaw` normalization helpers.

| User intent | CLI flag | Default / rules |
| --- | --- | --- |
| Full user digest phrase (preferred for targeted) | `--message` | Pass the user's digest sentence verbatim as one quoted argument. |
| Timeframe | `--timeframe` | Default `today`. Map `daily` -> `today`; `week` / `this week` / `last7` -> `last_7_days`. |
| Sources | `--sources` | Default **`juya`** for bare broad digests. Allowed names: `juya`, `huggingface`, `github`, `zhihu`, `bilibili`. Use comma-separated mixes when the user asks explicitly. Hugging Face cues (`huggingface only`, `trending models on hugging face`) map to `huggingface` (global Hub trending unless a topic/task filter is named). Zhihu cues (`zhihu practitioner insights`, lessons, trade-offs, pitfalls) map to `zhihu`. For targeted Bilibili-only requests, omit or set `bilibili`. For GitHub repo URLs, omit or set `github`. |
| Topics | `--topics` | Optional comma-separated list. Omit when user does not specify topics. |
| Output style | `--output-style` | Default bulletin. Use `editorial` or `newsletter` for a compact Chinese Juya index (one line per issue). |
| Output language | `--output-language` | Optional BCP-47 tag. Use `zh-CN` with Juya editorial digests. |

Do not invent new flags or source names. Do not treat Hugging Face as datasets/Spaces search or Zhihu as generic Chinese web search / hotlist / page crawl.

## Execution

Run from the project workspace root. Use the `exec` tool with a **fixed command prefix**
and validated argument tokens. Never build a shell string from raw user text.

**Broad digest template:**

```bash
uv run ai-news-agent openclaw-digest --timeframe <timeframe> --sources <sources>
```

**Targeted digest template (preferred):**

```bash
uv run ai-news-agent openclaw-digest --message "<user digest sentence>"
```

Add `--topics <csv>` only when the user specified topics for broad digests.

**Juya editorial digest template (website-only — `https://daily.juya.uk/`):**

```bash
uv run ai-news-agent openclaw-digest --message "Digest https://daily.juya.uk/" --output-style editorial --output-language zh-CN
```

The legacy GitHub repo `jujuyaya/juya-ai-daily` is **rejected** with guidance to use `https://daily.juya.uk/` instead. Do not pass that URL to `openclaw-digest`.

This stays on the local workflow (website RSS + per-issue markdown enrichment, ranking, summarization, persistence).
The top-level output is a **compact issue index**. For sub-news extraction inside one issue,
use **`ai-news-followup`** (for example: `Digest the first news` or `follow up on item 1`).
Do **not** substitute `web_fetch` or manual scraping for this path.

**Offline / smoke template** (service must be started with `--fake`):

```bash
uv run ai-news-agent openclaw-digest --fake --message "Digest bilibili video BV1demo0001"
```

### Examples

| User prompt | Command |
| --- | --- |
| Give me today's AI digest. | `uv run ai-news-agent openclaw-digest --timeframe today --sources juya` |
| Give me today's AI digest from GitHub only. | `uv run ai-news-agent openclaw-digest --timeframe today --sources github` |
| Give me this week's AI digest on RAG and agents. | `uv run ai-news-agent openclaw-digest --timeframe last_7_days --sources juya --topics RAG,agents` |
| Give me Hugging Face trending RAG models. | `uv run ai-news-agent openclaw-digest --message "trending RAG models on hugging face"` |
| Give me Zhihu practitioner insights on RAG. | `uv run ai-news-agent openclaw-digest --message "zhihu practitioner insights on RAG"` |
| Give me a mixed digest from GitHub and Bilibili. | `uv run ai-news-agent openclaw-digest --timeframe today --sources github,bilibili` |
| Digest bilibili video BV1gRJs63EYX | `uv run ai-news-agent openclaw-digest --message "Digest bilibili video BV1gRJs63EYX"` |
| Digest https://github.com/langchain-ai/langgraph | `uv run ai-news-agent openclaw-digest --message "Digest https://github.com/langchain-ai/langgraph"` |
| Digest https://daily.juya.uk/ | `uv run ai-news-agent openclaw-digest --message "Digest https://daily.juya.uk/" --output-style editorial --output-language zh-CN` |
| Digest https://github.com/jujuyaya/juya-ai-daily | **Rejected** — use `https://daily.juya.uk/` instead |
| Digest bilibili channel 285286947 | `uv run ai-news-agent openclaw-digest --message "Digest bilibili channel 285286947"` |

Return the client stdout (markdown digest) to the user unchanged. Preserve source links and
connector caveats in the response.

## Fallback (cold CLI path)

If the digest service is not running, start it or use the legacy cold path:

```bash
uv run ai-news-agent digest --timeframe <timeframe> --sources <sources>
```

Prefer the warm `openclaw-digest` path for lower latency.

## Security

- Local-first trusted operation only. Keep OpenClaw Gateway on loopback/local.
- Use fixed command templates with validated tokens. Do not interpolate user text into shell strings.
- Restrict `exec` to this trusted local workspace context.

## Error Handling

| Condition | User-facing response |
| --- | --- |
| Service not reachable | Ask user to start `uv run ai-news-agent service` and retry. |
| Missing `OPENAI_API_KEY` in live mode | Explain live digest requires `OPENAI_API_KEY`; suggest `--fake` smoke. |
| Invalid source name | Report allowed sources: `juya`, `huggingface`, `github`, `zhihu`, `bilibili`. |
| Conflicting source toggle vs URL/channel selector | Explain the mismatch and ask user to remove one side of the conflict. |
| Empty digest or connector warnings | Return digest output and surface warnings. |
| Non-zero exit code | Summarize stderr; do not expose full stack traces. |
