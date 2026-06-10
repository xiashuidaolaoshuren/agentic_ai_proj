---
name: ai-news-digest
description: "Generate an AI news digest from GitHub and Bilibili via the local ai-news-agent CLI."
user-invocable: true
metadata: {"openclaw":{"requires":{"bins":["uv"]}}}
---

# AI News Digest

Generate a markdown AI news digest by delegating to the existing `ai-news-agent` CLI.
OpenClaw is the channel gateway; this project handles retrieval, ranking, summarization,
and persistence.

## When To Use

Activate this skill when the user asks for an AI news digest in natural language, for example:

- "Give me today's AI digest."
- "Give me today's AI digest from GitHub only."
- "Give me this week's AI digest on RAG and agents."

Do not use this skill for follow-up Q&A, scheduled digests, or non-digest research tasks.

## Argument Mapping

Map user intent into constrained CLI options before execution. Defaults and aliases match
`ai_news_agent.adapters.openclaw` normalization helpers.

| User intent | CLI flag | Default / rules |
| --- | --- | --- |
| Timeframe | `--timeframe` | Default `today`. Map `daily` -> `today`; `week` / `this week` / `last7` -> `last_7_days`. Pass canonical values through unchanged (`today`, `last_7_days`, `last_30_days`). |
| Sources | `--sources` | Default `github,bilibili`. Allowed values: `github`, `bilibili`. Map phrases like "GitHub only" -> `github`; "Bilibili only" -> `bilibili`. Reject unknown sources with a concise user-facing error. |
| Topics | `--topics` | Optional comma-separated list (e.g. `RAG,agents`). Omit the flag when the user does not specify topics so built-in defaults apply. |

Do not invent new flags or source names. Only use existing CLI options: `--timeframe`,
`--sources`, `--topics`, and optionally `--fake` or `--db-path` for offline/testing runs.

## Execution

Run from the project workspace root. Use the `exec` tool with a **fixed command prefix**
and validated argument tokens. Never build a shell string from raw user text.

**Live run template:**

```bash
uv run ai-news-agent digest --timeframe <timeframe> --sources <sources>
```

Add `--topics <csv>` only when the user specified topics.

**Offline / smoke template** (no network, no `OPENAI_API_KEY`):

```bash
uv run ai-news-agent digest --fake --timeframe <timeframe> --sources <sources>
```

### Examples

| User prompt | Command |
| --- | --- |
| Give me today's AI digest. | `uv run ai-news-agent digest --timeframe today --sources github,bilibili` |
| Give me today's AI digest from GitHub only. | `uv run ai-news-agent digest --timeframe today --sources github` |
| Give me this week's AI digest on RAG and agents. | `uv run ai-news-agent digest --timeframe last_7_days --sources github,bilibili --topics RAG,agents` |

Return the CLI stdout (markdown digest) to the user unchanged. Preserve source links and
connector caveats in the response.

## Prerequisites And Gating

- **Required:** `uv` on PATH (enforced via skill metadata).
- **Live runs:** `OPENAI_API_KEY` must be set in the environment.
- **Workspace:** Run commands from the `agentic_ai_proj` repository root where `pyproject.toml`
  and the `ai-news-agent` entrypoint are available.

## Security

- Local-first trusted operation only. Keep OpenClaw Gateway on loopback/local.
- Use fixed command templates with validated tokens. Do not interpolate user text into shell
  strings.
- Restrict `exec` to this trusted local workspace context.

## Error Handling

Return concise, actionable errors to the user. Keep detailed diagnostics in application logs.

| Condition | User-facing response |
| --- | --- |
| Missing `OPENAI_API_KEY` in live mode | Explain that live digest requires `OPENAI_API_KEY` and suggest `--fake` for offline smoke. |
| Invalid source name | Report allowed sources: `github`, `bilibili`. |
| Empty digest or connector warnings | Return the digest output and surface any warnings (e.g. Bilibili anti-bot constraints). |
| Non-zero CLI exit code | Summarize stderr; do not expose full stack traces. |
