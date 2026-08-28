# AI News Research Agent

Local-first on-demand digest of AI learning signals from distinct source kinds. Language here is product/domain vocabulary only.

## Language

### Sources

**Juya**:
A first-class curated daily AI bulletin source identified by the website (`daily.juya.uk`), separate from GitHub and from generic RSS. It is the default digest source when the user does not name platforms. The old GitHub repo URL is not a Juya target; using it should fail with guidance to the website.
_Avoid_: GitHub special case, `github_manual_urls` alias as the conceptual or operational home, generic RSS, treating `github.com/jujuyaya/juya-ai-daily` as Juya, silently turning that URL into a repo news item

**Bilibili**:
A source whose digest items are video learning signals from Bilibili. Opt-in unless the user asks for it or names it in sources.
_Avoid_: Transcript-first news (until that milestone exists)

**GitHub (ecosystem signal)**:
A source whose digest items are open-source momentum signals (trending repos), not article-like news or curated bulletins. Opt-in unless the user asks for ecosystem/repo signals or names it in sources.
_Avoid_: Primary news feed, Juya host, generic RSS, default always-on platform feed

**Hugging Face (model momentum signal)**:
A source for currently notable model repositories, using Hub-native momentum evidence such as trending score, recent downloads, likes, and activity rather than treating models as article-like news. **Search and digest** both present Hugging Face as a **comparison table** of model families for quick Hub stat scanning; other search tools keep the numbered Source/Link list.
_Avoid_: Primary news feed, calling popularity model quality, claiming precise adoption velocity from cumulative counters, article-like HF entry blocks, LLM paraphrase of Hub stats in the HF table

**Hugging Face comparison table**:
The Hugging Face presentation for **search and digest** — one GFM table row per **model family** with Rank, Model, Link, Trending, Downloads (30d), Likes, Pipeline, and Also columns (emoji-prefixed labels in the default renderer). Hub stats come from collected `NewsItem` evidence; digest HF skips per-item LLM summarize. Mixed digests keep entry blocks for other sources; only the Hugging Face section is a table. **Display rank** in the Rank column is the global digest index in mixed digests; search ranks are 1-based family order.
_Avoid_: `###` summary blocks for Hugging Face, treating each table row as a raw Hub repo rather than a family, restarting rank at 1 inside the Hugging Face section in mixed digests

**Digest presentation chrome**:
Optional emoji prefixes on the default digest title, metadata lines, mixed-section labels, entry field labels, and HF table column headers — presentation only, not domain entities. Applies to default `render_digest_*` and HF search table output; the Chinese editorial Juya bulletin style is unchanged.
_Avoid_: Emoji in editorial digest output, emoji on non-HF search lists, treating emoji labels as follow-up vocabulary

**Zhihu (practitioner insight signal)**:
A source for Chinese-language practitioner lessons, trade-offs, and pitfalls about AI topics, distinct from primary academic evidence.
_Avoid_: arXiv substitute with equivalent evidence, generic web search, claiming relevance-ranked results are trending

**Practitioner insight**:
The atomic Zhihu digest item — one traceable search result framed for its practical experience, trade-off, or pitfall value.
_Avoid_: Uncited multi-result synthesis, treating a relevance score as popularity, inferring claims not supported by the returned content

**Trending repo**:
The atomic GitHub digest item — a repository under a topic that scores as notable momentum via a transparent heuristic (e.g. stars combined with recent activity), not true star-delta until that exists.
_Avoid_: Release-as-primary-item, README snippet as the story, treating every matching repo as equally newsworthy, claiming precise “stars gained in N days” without that data

**Trending model**:
The atomic Hugging Face digest item — one **model family** with notable current Hub momentum, represented by the family’s highest-trending Hub repository. It may be global or constrained to a user-named topic or task.
_Avoid_: Dataset or Space, “best model,” benchmark winner, equating popularity with technical quality, treating every packaging variant (GGUF, MLX, quant, Instruct) as its own slot when it shares version, size, and product SKU

**Model family**:
The Hugging Face presentation unit: Hub repositories that share architecture version, parameter size, and product SKU (e.g. `27B` vs other sizes; `pro` vs `flash`), regardless of publisher or packaging format.
_Avoid_: Grouping different sizes or product SKUs together, splitting the same size/version across multiple visible rows because of GGUF/MLX/quant/Instruct/Chat/Uncensored suffixes

**Family representative**:
The Hub repository shown for a model family — the member with the highest Hub trending score. Other format or packaging variants may appear on an **Also:** line but do not occupy their own slot.
_Avoid_: Picking a representative by downloads alone when trending score is available, hiding that sibling variants exist when they were collected

**Display rank**:
The 1-based position shown before each digest entry or search row. In digests it is the continuous index across the full entry list (mixed sections do not restart at 1). In search lists it is the order of rows actually shown after any Hugging Face family collapse.
_Avoid_: Raw Hub list index as the user-facing number, per-section rank that disagrees with follow-up `rank`, rank numbers that skip after grouping

**Release**:
A later optional enrichment on a GitHub item (what shipped), not the primary digest row.
_Avoid_: Using releases as the only way a repo can appear in the digest

### Follow-up

**Follow-up action**:
The suggested next learning move stored on a digest row (read, watch, try, or build). It is not chat follow-up.
_Avoid_: Structured follow-up, rank deep-dive, “follow-up section”

**Structured follow-up**:
Deterministic inspection of the latest saved digest via fixed phrases: show sources, study first, caveats, and rank. OpenClaw supports only this; Gradio also allows open-ended Q&A.
_Avoid_: New OpenClaw path strings, treating open-ended chat as structured follow-up, inventing Hub quality or Zhihu freshness beyond saved evidence

**Rank deep-dive**:
The structured reply for one 1-based **display rank**. Kind-specific cards from saved digest evidence: Juya **issue deep-dive**, Hugging Face **family card**, Zhihu **practitioner-insight card**; other kinds stay a generic entry reprint. Hugging Face may live-fetch the representative model-card README once on rank follow-up (ADR-0006); Zhihu stays persist-only.
_Avoid_: A digest-renderer “follow-up section”, giving Also variants their own ranks, synthesizing multiple Zhihu results, changing show-sources / study-first / caveats in the same change, git clone, Also-variant READMEs, Zhihu page fetch

**Issue deep-dive**:
The Juya rank deep-dive — one daily issue expanded into sub-news from persisted website markdown. Chinese chrome.
_Avoid_: Inventing sub-items not in persisted evidence, using this shape for Hugging Face families or Zhihu search snippets

**Hugging Face family card**:
The Hugging Face rank deep-dive — the **model family** at that display rank: representative, comparison-table Hub stats, Also variants, publisher, card snippet, and the popularity-not-quality caveat. English chrome matching the comparison table. Snippet may come from collect-time card data or a once-fetched live model-card README (ADR-0006).
_Avoid_: Repeating only the table with no snippet, dumping every Hub key, git clone, Also-variant READMEs, treating the row as a raw weights repo rather than a family, inventing description from HTML

**Zhihu practitioner-insight card**:
The Zhihu rank deep-dive — that rank’s single **practitioner insight**: Chinese chrome, evidence-first snippet/lens/author, 搜索相关性 labeled as search relevance not 热度, optional labeled LLM 摘要 / 为什么值得看, thin-evidence and no-freshness caveats.
_Avoid_: Related-insight synthesis, parsing a snippet as Juya sub-news, fetching the linked page, treating relevance as 热度 or trending

### Shared

**NewsItem**:
The normalized candidate collected from any connector before ranking and summarization.
_Avoid_: Treating every NewsItem as an article; shape depends on SourceKind

**SourceKind**:
Which source family produced a NewsItem (`github`, `bilibili`, `juya`, …).
_Avoid_: Overloading `github` for Juya bulletin rows

**Source selection**:
Which connectors run for a digest. Bare digest with no platform cue defaults to Juya only. Explicit source lists, clear intent phrases, or platform-specific targets select those connectors and replace the Juya default unless Juya is also named or targeted. Juya targets are website URLs only (`daily.juya.uk`), not the former GitHub repo alias.
_Avoid_: Always running GitHub+Bilibili by default; always adding Juya on top of platform-targeted digests; requiring a source name when a target already implies the platform; routing `jujuyaya/juya-ai-daily` to Juya

**Cross-source ranking**:
When a digest mixes SourceKinds, candidates are scored with kind-aware features (not one naive “newsiness”), then presented in segmented sections by source rather than a single interleaved top-N. Section order is intent-first (primary kind from the ask leads); otherwise fixed fallback Juya → Hugging Face → GitHub → Zhihu → Bilibili, omitting empty sections.
_Avoid_: One score that treats bulletins, trending models, repos, practitioner insights, and videos as the same kind of “newsiness” without kind-aware rules; interleaving unlike genres into one ranked list as the primary UX; unstable size-based section order
