# Distinct source roles: Juya default, GitHub trending, Bilibili opt-in

Status: accepted

The digest was treating GitHub as both repo search and the host for Juya bulletin ingestion (`daily.juya.uk` / legacy `jujuyaya/juya-ai-daily` via `github_manual_urls`), which duplicated “news feed” work and blocked a clean Milestone 5 RSS expansion. We decided to give each source a distinct job before Phase 5: **Juya** is a first-class bulletin and the bare-digest default; **GitHub** is an opt-in ecosystem signal whose atomic item is a **trending repo** (stars × recency heuristic, not true star-delta yet); **Bilibili** stays opt-in video. Platform cues (explicit sources, intent, or targets) replace the Juya default unless Juya is also named/targeted. The old GitHub repo URL is not a Juya alias — reject it with guidance to `https://daily.juya.uk/`. Mixed digests use kind-aware scoring and segmented sections (intent-first order; else Juya → GitHub → Bilibili). This refactor includes the connector split and ranking/presentation pass; arXiv, Hugging Face, generic RSS, true star-velocity, and release-as-primary stay for Phase 5+.

## Considered options (rejected)

- Keep Juya inside GitHub as a special case — preserves the mess and conflates SourceKind.
- Make Juya the first generic RSS feed now — blurs bulletin-specific follow-up; defer generic RSS to Phase 5.
- GitHub atomic item = Release — weaker “what got hot”; releases remain later enrichment.
- Default sources = GitHub + Bilibili (status quo) or always all three — fights bulletin-first identity.
- Keep `github.com/jujuyaya/juya-ai-daily` as a soft Juya alias — clean break preferred; teach via hard fail.
- Interleave mixed kinds in one top-N — unlike genres; segment instead.

## Consequences

- `SourceKind.JUYA` / connector `"juya"`; stop tagging bulletin rows as GitHub.
- Default connector set becomes Juya-only; docs and OpenClaw smoke commands must drop the GitHub alias.
- Ranking and rendering gain kind-aware + sectional behavior when sources are intentionally mixed.
