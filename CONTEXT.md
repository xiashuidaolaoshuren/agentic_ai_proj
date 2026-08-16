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
A source for currently notable model repositories, using Hub-native momentum evidence such as trending score, recent downloads, likes, and activity rather than treating models as article-like news.
_Avoid_: Primary news feed, calling popularity model quality, claiming precise adoption velocity from cumulative counters

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
The atomic Hugging Face digest item — a model repository with notable current Hub momentum, ranked primarily by the Hub’s native trending score. It may be global or constrained to a user-named topic or task.
_Avoid_: Dataset or Space, “best model,” benchmark winner, equating popularity with technical quality

**Release**:
A later optional enrichment on a GitHub item (what shipped), not the primary digest row.
_Avoid_: Using releases as the only way a repo can appear in the digest

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
