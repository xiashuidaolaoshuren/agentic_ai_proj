# Milestone 6: Hugging Face trending models and Zhihu practitioner insights

Status: accepted

Milestone 6 was specified as “Broader Research Sources”: arXiv, Hugging Face, and generic RSS. We decided that each source must keep a distinct product job, as in ADR-0001, so replacing arXiv with Zhihu is not a like-for-like swap: arXiv is primary academic evidence, while Zhihu is Chinese-language practitioner experience. Milestone 6 is therefore **AI Ecosystem & Practitioner Signals**: **Hugging Face** is an opt-in model-momentum source whose atomic item is a **trending model** (Hub-native `trending_score` first; global or topic/task-filtered); **Zhihu** is an opt-in practitioner-insight source whose atomic item is one official-search result, expanded with deterministic 实战/踩坑, 部署/成本, and 评测/对比 lenses and ranked by relevance, lens match, and returned-text completeness. Bare digests stay Juya-only; mixed digests keep one overall `top_n` with no quotas and sectional order intent-first, else Juya → Hugging Face → GitHub → Zhihu → Bilibili. arXiv and generic RSS remain deferred.

## Considered options (rejected)

- Keep Milestone 6 as “Broader Research Sources” and add Zhihu on top of arXiv — larger scope; Zhihu still would not fill the academic-paper job.
- Treat Zhihu as the arXiv substitute — conflates primary papers with secondary practitioner commentary.
- Keep generic RSS in this milestone — dilutes the source-specific Hugging Face and Zhihu experiences; Juya already owns bulletin RSS.
- Hugging Face datasets/Spaces, or Zhihu hotlist/direct-answer/page crawl — extra entity types or evidence the official search payload does not honestly support.
- Flatten Hub trending score, downloads, likes, and Zhihu relevance into `stars_or_views` — those metrics do not mean the same thing.
- Separate Hugging Face and Zhihu workflows — duplicates intent, persistence, rendering, tools, and interface wiring.
- Change the Juya-only default or add source quotas — fights the accepted mixed-digest policy from ADR-0001.

## Consequences

- New `SourceKind` values and connector names `huggingface` and `zhihu`; tools `search_huggingface_trending_models` and `search_zhihu_practitioner_insights`.
- `NewsItem` gains JSON-safe `source_evidence`; no SQLite migration; historical rows, including GitHub-tagged Juya items, still load.
- Zhihu never claims trending, freshness, or popularity from search relevance; Hugging Face never claims model quality from Hub popularity.
- Implementation details live in `docs/superpowers/specs/2026-08-16-ai-ecosystem-and-practitioner-signals-design.md`.
