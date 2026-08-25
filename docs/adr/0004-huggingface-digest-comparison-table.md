# Hugging Face digest comparison table

Status: accepted

After ADR-0003 collapsed Hub packaging variants into **model families**, digest Hugging Face sections still rendered each family as an article-like entry block (Summary, Why it matters, Background) via the same LLM path as Juya and Zhihu. That format suited narrative sources but wasted tokens and hid the Hub stats users wanted to scan. Search already showed a deterministic Source/Link list; the digest needed a different, scan-friendly shape.

We render digest Hugging Face sections (HF-only digests and the `## Hugging Face` block in mixed digests) as one **GFM comparison table**: Rank, Model, Link, Trending, Downloads (30d), Likes, Pipeline, Also — one row per model family up to **Items per source** N. **Display rank** uses the global digest index (same as follow-up `rank`). Hub column values come from collected `NewsItem.source_evidence` at render time; `DigestEntry` stubs persist for follow-up but skip `generate_entry_fields`. Other source kinds keep entry blocks and LLM summarize. Search `formatted_text` is unchanged (numbered list, not a table).

## Considered options (rejected)

- Keep article-like HF entry blocks — poor fit for Hub stat comparison; unnecessary LLM cost.
- Interleave HF table rows with Juya blocks — breaks segmented mixed-digest layout from ADR-0001.
- Put Hub stats only in LLM summary text — non-deterministic and hard to scan.
- Render search results as the same table — search UX stays a simple Source/Link list.
- One row per Hub repo — repeats families; ADR-0003 grouping stays.

## Consequences

- `summarize_ranked_items` builds deterministic HF stubs (snippet or title, empty why/background, `follow_up_action=try`, popularity caveat).
- `render_digest_markdown` / `render_digest_text` accept optional `news_items` for Hub stat lookup by `(source_kind, source_id)`.
- Mixed digests: Juya/GitHub/Zhihu/Bilibili sections unchanged; Hugging Face section is a single table.
- Family definition and **Also:** variants remain in ADR-0003.
