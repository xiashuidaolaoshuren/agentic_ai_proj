---
name: ai-news-digest
description: "Generate an AI news digest from GitHub and Bilibili via the local warm digest service."
user-invocable: true
metadata: {"openclaw":{"requires":{"bins":["uv"]}}}
---

# AI News Digest

Generate a markdown AI news digest by calling the **local warm digest service** through
`ai-news-agent openclaw-digest`. OpenClaw is the channel gateway; this project handles
retrieval, ranking, summarization, and persistence.

**Do not** use `web_fetch`, RSS lookups, or other research tools for digest requests.
Map user intent to CLI flags and run **only** the fixed `openclaw-digest` command below.

## When To Use

Activate this skill when the user asks for an AI news digest in natural language, for example:

- "Give me today's AI digest."
- "Give me today's AI digest from GitHub only."
- "Give me this week's AI digest on RAG and agents."

Do not use this skill for follow-up Q&A, scheduled digests, or non-digest research tasks.

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
| Timeframe | `--timeframe` | Default `today`. Map `daily` -> `today`; `week` / `this week` / `last7` -> `last_7_days`. |
| Sources | `--sources` | Default `github,bilibili`. Allowed: `github`, `bilibili`. |
| Topics | `--topics` | Optional comma-separated list. Omit when user does not specify topics. |

Do not invent new flags or source names.

## Execution

Run from the project workspace root. Use the `exec` tool with a **fixed command prefix**
and validated argument tokens. Never build a shell string from raw user text.

**Live run template:**

```bash
uv run ai-news-agent openclaw-digest --timeframe <timeframe> --sources <sources>
```

Add `--topics <csv>` only when the user specified topics.

**Offline / smoke template** (service must be started with `--fake`):

```bash
uv run ai-news-agent openclaw-digest --fake --timeframe <timeframe> --sources <sources>
```

### Examples

| User prompt | Command |
| --- | --- |
| Give me today's AI digest. | `uv run ai-news-agent openclaw-digest --timeframe today --sources github,bilibili` |
| Give me today's AI digest from GitHub only. | `uv run ai-news-agent openclaw-digest --timeframe today --sources github` |
| Give me this week's AI digest on RAG and agents. | `uv run ai-news-agent openclaw-digest --timeframe last_7_days --sources github,bilibili --topics RAG,agents` |

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
| Invalid source name | Report allowed sources: `github`, `bilibili`. |
| Empty digest or connector warnings | Return digest output and surface warnings. |
| Non-zero exit code | Summarize stderr; do not expose full stack traces. |
