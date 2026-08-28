# Hugging Face live model-card on rank follow-up

Status: accepted

Milestone 6.5 made Hugging Face rank follow-up a persist-only **family card** (ADR-0005). Collect-time `cardData=True` saves a short card summary, but practitioners often want the full model-card README. We now live-fetch the family representative's model-card README once on rank follow-up or `get_source_trace`, upsert the bounded text into `NewsItem.raw_snippet`, and reuse it on later follow-ups. Trending, downloads, and likes stay digest-time; only the snippet can reflect live Hub state after a successful fetch. Zhihu remains persist-only. This supersedes ADR-0005 for Hugging Face model-card enrichment only—not for Hub re-list, git clone, or Also-variant READMEs.

## Considered options (rejected)

- Persist-only only — family cards stay thin when Hub omits card summary at collect time.
- Live fetch on every follow-up — unnecessary Hub latency; Bilibili re-enrich pattern rejected for OpenClaw rank phrases.
- Git clone / weights download — out of proportion; not the Juya markdown analog.
- README for every Also variant — packaging SKUs, not separate stories.

## Consequences

- `HuggingFaceConnector.enrich_news_item` loads `ModelCard` for the representative once; marks `model_card_live_fetched` in `source_evidence`.
- Rank phrases and `get_source_trace` call enrich before rendering; `format_huggingface_family_card` stays a pure formatter with honesty caveats.
- First Hugging Face rank follow-up may pay Hub latency; repeats are persist-only for the README.
