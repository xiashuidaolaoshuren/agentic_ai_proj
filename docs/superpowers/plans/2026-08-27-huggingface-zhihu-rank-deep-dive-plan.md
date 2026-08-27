# Implementation Plan: Milestone 6.5 Hugging Face And Zhihu Rank Deep-Dive

**Spec:** `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md` (Milestone 6.5 section)  
**Parent spec:** `docs/superpowers/specs/2026-05-02-ai-news-research-agent-design.md`  
**ADR:** `docs/adr/0005-persist-only-rank-deep-dive.md`  
**Created:** 2026-08-27  
**Subsystem scope:** Milestone 6.5 only — specialize structured **rank** follow-up for Hugging Face (**family card**) and Zhihu (**practitioner-insight card**) from persisted digest evidence. No live fetch, no new tools, no OpenClaw path strings, no Milestone 7.

## Summary

Milestone 6.5 closes the follow-up gap Milestone 6 left: Hugging Face digest rows are stubs (comparison table, skip LLM summarize) and Zhihu’s practitioner job is the official-search result, but `format_rank_item` still reprints a generic `Digest item N` block. Ship persist-only kind-specific rank deep-dives on the existing phrases, following the Juya issue-deep-dive seam.

Out of scope: Hub re-list / model-card re-fetch, Zhihu page crawl, Bilibili-style `get_source_trace` enrich, new structured phrases, kind-aware sources/study-first/caveats, tool-JSON reshapes, Gradio open-ended prompt rewrites, persisting `output_language`, arXiv/RSS/datasets/Spaces, Milestone 7 memory/scheduling/deployment.

## Multi-subsystem gate

One formatter subsystem. Collection, ranking, rendering, tools, and HTTP contracts already exist. Hugging Face and Zhihu cards are sequenced parts of that seam (sibling modules, then one dispatch site), not independently shippable products. Use one type-1 plan.

## Discovery notes

- Reuse: `juya_followup.py` + `format_rank_item` in `followup_structured.py`. Juya heuristic (`is_juya_news_item`) runs first; generic `_format_digest_entry_detail` is the fallback. `match_news_item_for_digest_entry` already resolves the persisted `NewsItem` by `source_id` then URL — keep it there; do not invent a second matcher.
- Reuse: `NewsItem.source_evidence` keys already persisted — Hugging Face: `trending_score`, `downloads_30d`, `likes`, `pipeline_tag`, `family_variants` (`source_id` / `title`); Zhihu: `relevance`, `query_lens`, `source_label`, `evidence_text_length`. Publisher is `NewsItem.author`; snippet is `raw_snippet`.
- Reuse: Structured terminal tools and OpenClaw `/followup` call `format_rank_item` / `answer_structured_followup`. Changing those functions is sufficient; do not edit `tools/followup.py` observation shapes.
- Constraints: Same rank phrases and parser; OpenClaw `path` remains `no_digest` / `structured` / `guidance`. Show sources, study-first, and caveats wording stays frozen (`test_public_format_helpers_preserve_wording` uses a GitHub seed).
- Constraints: Dispatch is Juya heuristic first (historical GitHub-tagged Juya rows), else Hugging Face / Zhihu on `entry.source_kind` even when `NewsItem` is missing (honest degraded card), else generic. Do not change Juya’s current “no news_item → generic reprint” behavior.
- Constraints: Family card chrome is English **words** matching the table columns (Rank, Model, Link, Trending, Downloads (30d), Likes, Pipeline, Also). Do **not** copy digest-table emoji headers — `CONTEXT.md` forbids treating emoji chrome as follow-up vocabulary.
- Constraints: Zhihu chrome is Chinese (第 N 条, 镜头, 搜索相关性, 原文摘录, 摘要, 为什么值得看). 搜索相关性 is official-search relevance, never 热度. Payload text is never translated. LLM 摘要 / 为什么值得看 only when those `DigestEntry` fields are non-empty.
- Constraints: Also variants do not get their own ranks. Empty Also / empty Hub stats / empty snippet are omitted, never invented, never printed as “Also: none”.
- Anti-goals: formatter registry, live connector calls on the rank path, moving `match_news_item_for_digest_entry` unless a type-2 plan proves a real duplication problem, drive-by ranking/renderer/tool refactors.



## File map



### Subsystem: Persist-only rank deep-dive


| Path                                           | Create/Modify                                                                         | Single responsibility                                                                                                                                                             | Public surface                                  |
| ---------------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `src/ai_news_agent/huggingface_followup.py`    | create                                                                                | Format a Hugging Face **family card** from persisted `DigestEntry` + optional `NewsItem`                                                                                          | `format_huggingface_family_card`                |
| `src/ai_news_agent/zhihu_followup.py`          | create                                                                                | Format a Zhihu **practitioner-insight card** from persisted `DigestEntry` + optional `NewsItem`                                                                                   | `format_zhihu_practitioner_insight_card`        |
| `src/ai_news_agent/followup_structured.py`     | modify                                                                                | Dispatch rank follow-up: Juya heuristic, else HF/Zhihu `source_kind`, else generic                                                                                                | `format_rank_item` (other formatters unchanged) |
| `src/ai_news_agent/juya_followup.py`           | unmodified unless type-2 finds a shared helper that must move                         | Keep issue deep-dive and `match_news_item_for_digest_entry`                                                                                                                       | existing exports                                |
| `tests/test_huggingface_followup.py`           | create                                                                                | Prove family-card fields, Also, omitted empties, popularity caveat, degraded missing evidence                                                                                     | pytest tests                                    |
| `tests/test_zhihu_followup.py`                 | create                                                                                | Prove evidence-first insight card, labeled LLM fields, 搜索相关性 not 热度, degraded missing evidence                                                                                    | pytest tests                                    |
| `tests/test_rank_deep_dive.py`                 | create                                                                                | Prove `format_rank_item` / `answer_structured_followup` dispatch: mixed-digest display ranks, Juya still wins, GitHub generic, missing `NewsItem` still kind-specific, no network | pytest tests                                    |
| `tests/test_juya_followup.py`                  | modify only if a regression assertion must be added                                   | Keep issue deep-dive behavior                                                                                                                                                     | pytest tests                                    |
| `tests/test_openclaw_followup.py`              | modify                                                                                | Prove HF/Zhihu rank replies stay `path=structured`; generic GitHub rank wording unchanged                                                                                         | pytest tests                                    |
| `tests/test_tools_followup.py`                 | unmodified expected                                                                   | GitHub seed still matches exact sources / study-first / rank / caveats strings                                                                                                    | existing test                                   |
| `openclaw/skills/ai-news-followup/SKILL.md`    | modify                                                                                | Teach family card / insight card on the same rank phrases; no quality/freshness invention                                                                                         | skill text                                      |
| `README.md`                                    | modify                                                                                | Document rank follow-up for HF/Zhihu as persist-only cards; keep Juya deep-dive examples                                                                                          | user-facing follow-up section                   |
| `docs/benchmarks/openclaw-latency-baseline.md` | modify only if a follow-up example would otherwise imply generic reprint for HF/Zhihu | Keep historical baseline commands accurate                                                                                                                                        | benchmark notes                                 |




### Blast radius


| Path / boundary                          | Why sensitive                                                                                            | Existing behavior to preserve                                                                                                                                      | Plan mode                       |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------- |
| `followup_structured.py`                 | Single rank-reply source for Gradio structured path, OpenClaw `/followup`, and structured terminal tools | Juya deep-dive; GitHub/Bilibili generic reprint; sources / study-first / caveats wording; `path` taxonomy; `is_structured_followup` still must not call formatters | high                            |
| New HF/Zhihu follow-up modules           | User-visible card contracts (chrome language, Hub honesty, no Zhihu synthesis)                           | No HTTP/Hub calls; no invented stats; Also variants not ranked                                                                                                     | high                            |
| OpenClaw follow-up HTTP/CLI              | External `path` and client stdout                                                                        | `no_digest` / `structured` / `guidance` only; unsupported phrases still guidance                                                                                   | medium                          |
| `tools/followup.py`, `tools/registry.py` | Easy to “helpfully” reshape observations                                                                 | JSON observations unchanged; registry still delegates to `format_rank_item`                                                                                        | skip unless a test proves drift |
| README / OpenClaw skill                  | Operators copy examples                                                                                  | Same phrases; do not invent new flags or live-enrich instructions                                                                                                  | skip                            |




## Workflow (for implementers)

1. **writing-plans** produced this file (type-1 decomposition only).
2. For each subtask: **Plan mode** + **planning-subtasks** skill → type-2 plan (`.cursor/plans/*.plan.md`) when **Plan mode** priority warrants it.
3. **Agent mode**: **test-driven-development** when `TDD suitable: yes`. New modules: first GREEN is types + stubs only (`NotImplementedError` / empty string), no dispatch wiring in that GREEN.
4. Update this document if reality diverges; add a **Plan changelog** row.



## Subtasks

Dependency notation: `Blocked by: T1` means start after T1 is done.

### T1 — Hugging Face family card formatter

- [x] **Do:** Add `huggingface_followup.py` that formats one **family card** from a digest row plus optional persisted `NewsItem`: display rank, representative title/id, URL, Trending / Downloads (30d) / Likes / Pipeline, Also variants when present, publisher, card snippet, always-on popularity-not-quality caveat. Omit empty why/background, gated, library, all-time downloads, discovery mode, and empty Also. Honest degraded card when `NewsItem` or Hub stats/snippet are missing — never invent values. First GREEN is the public function stub only.

- **Blocked by:** —
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_huggingface_followup.py -q`



### T2 — Zhihu practitioner-insight card formatter

- [x] **Do:** Add `zhihu_followup.py` that formats one **practitioner-insight card** for a single rank: 第 N 条, title, URL, 镜头, author/source_label, 搜索相关性 labeled as official-search relevance (never 热度), 原文摘录, then 摘要 / 为什么值得看 only when those `DigestEntry` fields are non-empty, plus thin-evidence and no-freshness caveats. Do not show `evidence_text_length` as a user-facing metric. Honest degraded card when `NewsItem` or snippet is missing. First GREEN is the public function stub only.

- **Blocked by:** —
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_zhihu_followup.py -q`



### T3 — Dispatch rank follow-up and lock mixed-digest ranks

- [x] **Do:** Wire `format_rank_item` to Juya heuristic first, else Hugging Face / Zhihu on `entry.source_kind` (including missing `NewsItem`), else generic. Prove mixed-digest **display rank** identity (rank N is the global entry index). Prove GitHub generic reprint, Juya issue deep-dive, sources/study-first/caveats wording, and OpenClaw `path=structured` for HF/Zhihu rank phrases. No connector/HTTP calls on this path.

- **Blocked by:** T1, T2
- **Plan mode:** high
- **TDD suitable:** yes
- **Verification:** `uv run pytest tests/test_rank_deep_dive.py tests/test_huggingface_followup.py tests/test_zhihu_followup.py tests/test_juya_followup.py tests/test_openclaw_followup.py tests/test_tools_followup.py tests/test_tools_registry.py -q`



### T4 — Document family card and insight card on existing phrases

- [x] **Do:** Update the OpenClaw follow-up skill and README structured-follow-up section so rank follow-up on Hugging Face / Zhihu is described as persist-only family / insight cards using the same phrases. Keep Juya deep-dive examples. Do not add live-fetch instructions or new CLI flags.

- **Blocked by:** T3
- **Plan mode:** skip
- **TDD suitable:** no
- **TDD suitable reason:** static documentation only; no runtime behavior.
- **Verification:** review `git diff --check`; confirm skill/README still list the existing phrases and no longer imply a generic `Digest item N` reprint for HF/Zhihu ranks.



### T5 — Milestone-level regression

- [ ] **Do:** Run the full automated suite after behavior and docs land. Update this plan’s changelog if verification exposes a missing file, a changed OpenClaw contract, or a required extra subtask.

- **Blocked by:** T1, T2, T3, T4
- **Plan mode:** medium
- **TDD suitable:** no
- **TDD suitable reason:** verification-only integration pass; production behavior was already driven test-first in T1–T3.
- **Verification:** `uv run pytest -q`; confirm `test_public_format_helpers_preserve_wording` still exact-matches GitHub formatter strings; fake OpenClaw follow-up `path` values remain `no_digest` / `structured` / `guidance`.



## TDD note (Agent mode)

Per subtask, obey `TDD suitable`: `yes` means strict **test-driven-development** (red/green/refactor); `no` means do not force test-first—still satisfy **Verification**. New modules start GREEN with types and stubs only. Type-2 planning → **planning-subtasks** skill.

## Plan changelog


| Date       | Change                                                             |
| ---------- | ------------------------------------------------------------------ |
| 2026-08-27 | Created from the accepted Milestone 6.5 spec section and ADR-0005. |


