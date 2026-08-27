# Hugging Face comparison table (search and digest)

Status: accepted

After ADR-0003 collapsed Hub packaging variants into **model families**, digest Hugging Face sections still rendered each family as an article-like entry block (Summary, Why it matters, Background) via the same LLM path as Juya and Zhihu. That format suited narrative sources but wasted tokens and hid the Hub stats users wanted to scan. Search used a numbered Source/Link list with inline Hub stats — readable but not scannable when comparing families side by side.

We render **Hugging Face search and digest** as one **GFM comparison table**: Rank, Model, Link, Trending, Downloads (30d), Likes, Pipeline, Also — one row per model family up to **Items per source** N. In mixed digests, **display rank** uses the global digest index (same as follow-up `rank`); in HF-only search, rank is 1-based family order. Hub column values come from `NewsItem.source_evidence`. Digest HF `DigestEntry` stubs persist for follow-up but skip `generate_entry_fields`. Rank follow-up of those stubs is a **family card** from persisted `NewsItem` evidence (Milestone 6.5 / ADR-0005), not the generic `Digest item N` reprint. Other source kinds keep entry blocks and LLM summarize in digests; other search tools keep the numbered Source/Link list.

The default renderer adds emoji prefixes to the digest title, metadata, section labels, entry fields, and HF table column headers for scan-friendly UI. The Chinese editorial Juya bulletin style is unchanged.

## Considered options (rejected)

- Keep article-like HF entry blocks in digest — poor fit for Hub stat comparison; unnecessary LLM cost.
- Keep search as numbered list while digest uses table — inconsistent HF UX; harder to compare Hub stats in search.
- Interleave HF table rows with Juya blocks — breaks segmented mixed-digest layout from ADR-0001.
- Put Hub stats only in LLM summary text — non-deterministic and hard to scan.
- One row per Hub repo — repeats families; ADR-0003 grouping stays.

## Consequences

- `summarize_ranked_items` builds deterministic HF stubs (snippet or title, empty why/background, `follow_up_action=try`, popularity caveat).
- `render_search_items_text` emits the HF comparison table when all items are Hugging Face.
- `render_digest_markdown` / `render_digest_text` accept optional `news_items` for Hub stat lookup by `(source_kind, source_id)`.
- Mixed digests: Juya/GitHub/Zhihu/Bilibili sections unchanged; Hugging Face section is a single table.
- Family definition and **Also:** variants remain in ADR-0003.
- Milestone 6.5 rank follow-up must reuse the same family identity and Hub columns; it must not re-expand variants into their own ranks.
