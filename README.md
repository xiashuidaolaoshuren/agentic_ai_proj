# AI News Research Agent

Local-first Python agent that builds on-demand AI news digests from GitHub and conservative Bilibili-oriented sources (see [design spec](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md)).

**Milestone 1 (in progress):** project scaffold, domain models, connectors, ranking, summarization, storage, LangGraph workflow, Gradio UI, and tests. This repo currently completes **Task 1** (tooling + importable package only).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (recommended) or another Python 3.11+ environment
- Python **3.11+** (see [.python-version](.python-version) for the pinned dev version)

## Setup (uv)

```bash
cd agentic_ai_proj
uv sync --group dev
```

Copy environment template when you add API-backed features:

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

## Verify Task 1

```bash
uv run python -m pytest --version
uv run python -c "import ai_news_agent; print(ai_news_agent.__version__)"
uv run pytest
```

Without `uv`, from the repo root with dev dependencies installed:

```bash
python -m pytest --version
python -c "import ai_news_agent; print(ai_news_agent.__version__)"
```

If `import ai_news_agent` fails globally, use `uv sync` (editable install) or set `PYTHONPATH=src` for one-off commands.

## Tests

```bash
uv run pytest
```

## What is not in Milestone 1

OpenClaw, scheduled runs, cloud deploy, arXiv/HF/RSS connectors, and vector RAG are out of scope for the first milestone (see the design spec).

## Documentation

- [Implementation plan (subtasks T1–T14)](docs/superpowers/plans/2026-05-02-ai-news-research-agent-plan.md)
- [Design spec](docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md)
