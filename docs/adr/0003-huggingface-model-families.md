# Hugging Face model families as the visible HF unit

Status: accepted

Hub trending lists often return many repositories for the same architecture (base, GGUF, MLX, quant, Instruct) that differ only in packaging or light tuning. Showing each repo as its own row let one family consume every slot when **Items per source** was small, which misrepresented diversity.

We treat the visible Hugging Face unit as a **model family** (version + parameter size + product SKU), not every Hub repository card. Variants collapse to one row; the **family representative** is the highest Hub `trending_score` member; siblings appear on an **Also:** line. Grouping uses Hub `base_model` when present, otherwise a deterministic name heuristic—no extra per-model API calls. Collection over-fetches from Hub, then collapses to the requested family count.

## Considered options (rejected)

- Show every Hub repo — repeats one architecture across the list.
- Nest variants under headings without collapsing — still consumes N slots visually.
- Drop variants silently — list can shrink below N with no explanation.
- LLM or download-based grouping — slower, less inspectable than heuristic + optional `base_model`.
- Same-org-only grouping — community quant repos would still duplicate official cards.

## Consequences

- Search lists and digest Hugging Face sections select and render families, not raw repo counts.
- `source_evidence` may carry `base_model` and `family_variants` for traceability.
- **Display rank** on search rows reflects shown family order; digest rank stays the global entry index from ADR-0001 mixed-digest follow-up.
