# Persist-only rank deep-dive for Hugging Face and Zhihu

Status: accepted (Hugging Face live model-card on rank follow-up superseded for Hugging Face only — see ADR-0006; Zhihu persist-only unchanged)

Milestone 6 shipped Hugging Face and Zhihu through the digest pipeline but left rank follow-up on the generic `DigestEntry` reprint. Juya already expands a rank from persisted evidence; Bilibili can live-enrich transcripts on `get_source_trace`. We decided Hugging Face and Zhihu follow Juya, not Bilibili: **rank deep-dive** is a kind-specific card built only from the latest saved `DigestEntry` + `NewsItem` — Hugging Face as a **family card** (same display rank as the comparison-table row), Zhihu as one **practitioner-insight card** (evidence-first, no related-result synthesis). Same structured phrases; show-sources / study-first / caveats unchanged; no new OpenClaw paths; no Hub re-fetch; no Zhihu page fetch (already forbidden by ADR-0002). Milestone 7 memory/scheduling/deployment stays separate.

## Considered options (rejected)

- Live enrichment on follow-up (re-hit Hub or fetch Zhihu pages) — new connector work; Zhihu page fetch contradicts ADR-0002; Hub re-list can disagree with the saved table.
- New structured phrases (“show family variants”, “which lens”) — extra OpenClaw surface for a job rank follow-up already names.
- A follow-up section in the digest renderer — not chat follow-up; fights ADR-0004’s table-as-HF-digest.
- Reshape `get_digest_item` / `get_source_trace` JSON or Gradio open-ended prompts — second presentation contract; open-ended already receives `news_item`.
- Specialize all four structured formatters — larger UX rewrite than the Juya-shaped gap.
- Treat Also variants as nested sub-news, or stitch other Zhihu hits into one card — variants are packaging, not stories; multi-result synthesis is already out of the practitioner-insight job.

## Consequences

- `format_rank_item` gains Hugging Face / Zhihu branches; Juya heuristics stay first.
- Family card and insight card field lists live in the Milestone 6.5 section of `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`.
- Domain terms: **rank deep-dive**, **Hugging Face family card**, **Zhihu practitioner-insight card** in `CONTEXT.md`.
