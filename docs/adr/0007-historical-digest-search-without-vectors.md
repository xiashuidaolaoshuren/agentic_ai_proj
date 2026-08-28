# Historical digest search without vectors or context switch

Status: accepted

Milestone 7 named “richer local memory or vector search.” The first memory slice is **historical digest search**: lexical recall of saved digest entries, then read-only **history show** by a stable **historical item reference**. We keep a filtered SQLite scan with deterministic application scoring, no embeddings, no FTS table, and no change to latest-digest follow-up context. Opening `dN:rN` formats that old rank from persisted evidence only (no Hugging Face/Bilibili enrich). FTS or vectors wait until a real archive proves the scan insufficient. Spec: `docs/superpowers/specs/2026-08-28-milestone-7d-historical-digest-search-design.md`.

## Considered options (rejected)

- SQLite FTS5 in the first slice — extra schema, backfill, and tokenizer work before size has justified it.
- Local or remote embeddings — needs a model/API; ranking is harder to explain; user constraint was fully local and deterministic.
- Switch latest-digest context to the opened run — later “show sources” / rank phrases would silently inspect the wrong digest.
- Search unselected collected `NewsItem` rows — those were not chosen for a digest; the product job is historical digest recall.

## Consequences

- `DigestStore` gains historical reads only; `get_latest_followup_context()` stays latest-only.
- Scoring lives outside storage so FTS can replace the scan later without changing CLI/Gradio callers.
- OpenClaw, trend synthesis, personalization, and conversation memory stay later slices.
