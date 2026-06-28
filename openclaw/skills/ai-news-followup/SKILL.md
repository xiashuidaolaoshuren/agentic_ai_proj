---
name: ai-news-followup
description: "Structured follow-up over the latest saved digest (sources, ranking, caveats) via the local warm digest service."
user-invocable: true
metadata: {"openclaw":{"requires":{"bins":["uv"]}}}
---

# AI News Digest — Structured Follow-up

Answer deterministic follow-up questions against the **latest saved digest** by calling the
local warm digest service through `ai-news-agent openclaw-followup`.

**Do not** use `web_fetch`, RSS lookups, or manual scraping for these follow-ups. Map user
intent to the fixed `openclaw-followup` command below.

## When To Use

Activate this skill when the user asks to inspect the **most recent digest** you generated
through `ai-news-digest`, including:

- "Show sources"
- "List sources from the digest"
- "Which item should I study first?"
- "What's the top pick?"
- "Show caveats"
- "Any warnings or confidence issues?"
- "Follow up on item 1" / "#2" / "the second one"
- "Followup the first issue" (first digest item)
- "Digest the first news" / "the first news" (Juya issue deep dive with sub-news)
- "First juya news"

**Prerequisite:** a digest must already exist in the service database. Run
`ai-news-digest` first if the user has not generated a digest in this session.

For **Juya daily** digests (`daily.juya.uk` or legacy `jujuyaya/juya-ai-daily` alias), rank-targeted follow-up expands the
selected issue into structured sub-news using persisted website markdown evidence. Return that output
unchanged instead of improvising sub-items from memory.

Do **not** use this skill for:

- New digest generation (use `ai-news-digest`)
- Open-ended Q&A ("why does item 1 matter for my team?", "compare Grok vs Sora")
- Scheduled digests or non-digest research

## Prerequisites

- **Digest service running** (same instance that served the digest):

```bash
uv run ai-news-agent service --port 8765
```

- **Required:** `uv` on PATH.
- **Workspace:** Run client commands from the `agentic_ai_proj` repository root.
- **Shared DB:** Service and client must use the same `digest.sqlite` (default cwd).

Optional env: `AI_NEWS_AGENT_SERVICE_URL` (default `http://127.0.0.1:8765`).

## Execution

Run from the project workspace root. Use the `exec` tool with a **fixed command prefix**
and pass the user's follow-up phrase as a single quoted `--message` argument.

```bash
uv run ai-news-agent openclaw-followup --message "<user follow-up phrase>"
```

Return the client stdout to the user unchanged.

### Examples

| User prompt | Command |
| --- | --- |
| Show sources | `uv run ai-news-agent openclaw-followup --message "show sources"` |
| Which item should I study first? | `uv run ai-news-agent openclaw-followup --message "which item should I study first"` |
| Follow up on item 1 | `uv run ai-news-agent openclaw-followup --message "follow up on item 1"` |
| Digest the first news (Juya deep dive) | `uv run ai-news-agent openclaw-followup --message "Digest the first news"` |
| The second one | `uv run ai-news-agent openclaw-followup --message "follow up on the second one"` |
| Any caveats? | `uv run ai-news-agent openclaw-followup --message "show caveats"` |

## Error Handling

| Condition | User-facing response |
| --- | --- |
| Service not reachable | Ask user to start `uv run ai-news-agent service` and retry. |
| No saved digest | Client returns guidance to generate a digest first. |
| Unsupported follow-up phrase | Client returns structured-mode guidance; suggest supported phrases or Gradio for open-ended Q&A. |
| Non-zero exit code | Summarize stderr; do not expose full stack traces. |

## Security

- Local-first trusted operation only.
- Use fixed command templates with validated tokens. Do not interpolate user text into shell strings beyond `--message` quoting.
- Restrict `exec` to this trusted local workspace context.
