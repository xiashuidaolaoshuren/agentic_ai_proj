# AI News Research Agent

Local-first Python agent that generates **on-demand AI news digests** from GitHub and conservative Bilibili-oriented sources, ranks candidates, summarizes them with an LLM (or offline fakes), persists runs to SQLite, and exposes a **CLI** plus optional **Gradio** chat UI.

Design details: [AI News Research Agent design](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md).

**Milestone 1 (Local Digest MVP)** is complete: LangGraph workflow, storage, connectors, ranking, summarization, chat follow-ups, CLI smoke mode, Gradio UI, and tests.

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

| Variable | When needed | Purpose |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Live digest / chat LLM follow-ups | Summarization via OpenAI-compatible API ([`llm.py`](src/ai_news_agent/llm.py)) |
| `OPENAI_BASE_URL` | Optional | Custom gateway / compatible endpoint |
| `OPENAI_MODEL` | Optional | Model name (default `gpt-4o-mini`) |
| `GITHUB_TOKEN` | Optional | Higher GitHub API rate limits ([`connectors/github.py`](src/ai_news_agent/connectors/github.py)) |

SQLite defaults to `./digest.sqlite` in the current working directory unless you pass `--db-path`. Database files matching `*.db` are gitignored.

## Quick start (offline, no API keys)

Smoke acceptance tests (no network):

```bash
uv run pytest tests/test_mvp_smoke.py -q
```

One-shot fake digest (deterministic connectors + summarizer):

```bash
uv run ai-news-agent digest --fake
```

Gradio chat UI in offline mode:

```bash
uv run python -m ai_news_agent.app.gradio_app --fake
```

Open the printed URL (default port **7860**). Try **“Give me today's AI digest”**, then **“show sources”**.

## Live digest (network + LLM)

Requires `OPENAI_API_KEY`. Optionally set `GITHUB_TOKEN` for reliability.

```bash
uv run ai-news-agent digest --sources github,bilibili --topics "RAG,agents" --timeframe today
```

Useful flags:

- `--sources` — comma-separated: `github`, `bilibili`
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

The UI delegates to [`ChatService`](src/ai_news_agent/chat.py): digest phrases trigger the workflow; follow-ups such as listing **sources**, **ranking/top pick**, or **caveats** use persisted traces. Open-ended follow-ups need a configured model with `generate_followup_reply` where implemented.

## Tests

Full suite:

```bash
uv run pytest
```

Milestone 1 smoke only:

```bash
uv run pytest tests/test_mvp_smoke.py -q
```

## Known MVP limits

- **Bilibili** is **metadata-first** (title, description, views, etc. via public APIs). There is **no** transcript or deep video understanding; items are labeled lower confidence when content is thin (see [`connectors/bilibili.py`](src/ai_news_agent/connectors/bilibili.py)).
- **Out of scope for Milestone 1:** OpenClaw adapter, scheduled runs, cloud deployment, arXiv / Hugging Face / RSS connectors, vector RAG (see design spec milestones).

## Documentation

- [Implementation plan (T1–T14)](docs/superpowers/plans/2026-05-02-ai-news-research-agent-plan.md)
- [Design spec](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md)
