# OpenClaw Digest Latency Baseline (2026-06-14)

Captured before the persistent digest-service adapter. Use the same prompts for post-fix comparison.

## Test environment

- OS: Windows 10
- Repo: `agentic_ai_proj`
- Gradio: `uv run python -m ai_news_agent.app.gradio_app` (live mode)
- OpenClaw: `openclaw gateway run` + `ai-news-digest` skill via CLI exec
- Prompt under test: `Give me today's AI digest` (default `github,bilibili`, timeframe `today`)

## Digest runtime (workflow only)

| Path | Run | Entries | Warnings | Elapsed |
|------|-----|---------|----------|---------|
| CLI (`ai-news-agent digest`) | run_id=69 | 5 | 0 | **52s** (22:40:44 → 22:41:36) |
| Gradio (`ChatService`) | run_id=72 | 5 | 0 | **27.23s** |
| Gradio (channel digest) | run_id=71 | 5 | 1 | **29.62s** |

**Observation:** Gradio keeps process warm (model + env + Bilibili network config loaded once). CLI cold-starts per invocation via `uv run` + OpenClaw exec, roughly doubling perceived digest time.

## OpenClaw end-to-end (channel)

Representative gateway trace (same session as CLI run above):

| Phase | Approx. duration | Evidence |
|-------|------------------|----------|
| Gateway session queued behind model work | **135s+** | `long-running session … state=processing age=135s` |
| Pre-exec `web_fetch` attempts (off-path) | **~50s** | Multiple `web_fetch failed` (412/403) on Bilibili/RSS URLs 22:54:04–22:54:52 |
| CLI digest exec | **52s** | `cli digest start` → `cli digest done` |
| **Estimated end-to-end (this run)** | **~3+ min** | Gateway orchestration + failed fetches + CLI cold start |

## Bottleneck summary

1. **Per-request CLI cold start** — new Python process, env load, model client init each OpenClaw digest.
2. **OpenClaw gateway orchestration overhead** — skill routing may trigger extra tools (`web_fetch`) before `exec`.
3. **Connector variance** — Bilibili anti-bot retries add seconds; not unique to OpenClaw but visible in both paths.

## Post-fix targets

- Digest runtime via warm service: within ~5s of Gradio p50 (~27s) for same prompt.
- End-to-end OpenClaw: remove CLI spawn overhead; skill should call local client only (no `web_fetch` side paths).
- Telemetry: log `correlation_id` + per-stage timings for each request.

## Comparison procedure (repeat after fix)

1. Start digest service: `uv run ai-news-agent service --port 8765`
2. Restart OpenClaw gateway; `/new` session.
3. Run prompt `Give me today's AI digest` **10 times**; record wall-clock from send to final reply.
4. Record p50/p95 and grep logs for `correlation_id` stage lines.
5. Compare to table above.

## Targeted digest smoke (OpenClaw)

With the digest service running, verify these prompts route through `openclaw-digest --message` (not `web_fetch`):

| Prompt | Expected command |
|--------|------------------|
| `Digest bilibili video BV1gRJs63EYX` | `openclaw-digest --message "Digest bilibili video BV1gRJs63EYX"` |
| `Digest https://www.bilibili.com/video/BV1gRJs63EYX` | `openclaw-digest --message "Digest https://www.bilibili.com/video/BV1gRJs63EYX"` |
| `Digest https://github.com/langchain-ai/langgraph` | `openclaw-digest --message "Digest https://github.com/langchain-ai/langgraph"` |
| `Digest https://github.com/jujuyaya/juya-ai-daily` | `openclaw-digest --message "Digest https://github.com/jujuyaya/juya-ai-daily" --output-style editorial --output-language zh-CN` |

Success criteria: markdown digest output from our workflow, connector caveats preserved, no gateway `web_fetch` attempts in logs.

### Juya daily repo ingestion smoke

1. Start digest service: `uv run ai-news-agent service --port 8765`
2. Run: `uv run ai-news-agent openclaw-digest --message "Digest https://github.com/jujuyaya/juya-ai-daily" --output-style editorial --output-language zh-CN`
3. Expect digest items with daily post titles/links (e.g. `daily.juya.uk`), newsletter-style Chinese sections, and richer evidence from `BACKUP/*.md` when available.
4. If `rss.xml` is unreachable, expect a single repo-metadata item plus `juya_rss_unavailable` in connector caveats.
5. If BACKUP markdown is missing for an entry, expect `juya_backup_unavailable` and RSS snippets preserved.

## Structured follow-up smoke (OpenClaw)

Prerequisite: digest service running and a digest already generated in the same `digest.sqlite`.

1. Generate digest: `uv run ai-news-agent openclaw-digest --fake --timeframe today --sources github`
2. Follow up: `uv run ai-news-agent openclaw-followup --message "show sources"`
3. Expect numbered source links from the latest digest (not a new digest run).
4. Try `openclaw-followup --message "show caveats"` and `openclaw-followup --message "which item should I study first"`.
5. Try `openclaw-followup --message "follow up on item 1"` and expect item-level details (title, URL, summary).
6. For Juya daily digests, try `openclaw-followup --message "Digest the first news"` and expect sub-news extraction for the selected issue.
7. Unsupported phrase (e.g. open-ended why-question) should return structured-mode guidance, not `web_fetch`.
