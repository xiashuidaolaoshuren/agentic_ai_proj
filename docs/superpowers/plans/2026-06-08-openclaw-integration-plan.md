# Implementation Plan: Milestone 3 OpenClaw Integration

**Spec:** `docs/superpowers/specs/2026-06-08-openclaw-integration-design.md`  
**Created:** 2026-06-08  
**Subsystem scope:** Local OpenClaw CLI-backed adapter integration

## Summary

Decompose Milestone 3 into a focused subsystem: OpenClaw-triggered digest generation using the
existing Python CLI path and workflow boundaries. The plan adds a thin adapter module, a local
OpenClaw skill definition, and integration documentation, while preserving current digest behavior.

## Discovery Notes

- **Reuse:** `src/ai_news_agent/cli.py` already maps `--sources` to
  `DigestRequest.connector_names` through `sources.py`.
- **Reuse:** `src/ai_news_agent/intent.py` and `src/ai_news_agent/digest_request_builder.py`
  already implement natural-language source/timeframe parsing patterns we can mirror.
- **Constraints:** existing source validation contract lives in `src/ai_news_agent/sources.py`
  (`normalize_source_names`, `parse_sources_csv`).
- **Constraints:** test stack is pytest with deterministic fake-mode workflows, so new adapter
  behavior should be tested without live OpenClaw dependency.
- **Anti-goals:** no change to digest core graph/ranking/summarization, no OpenClaw plugin
  implementation, no source expansion, no deployment refactor.

## File Map

### Subsystem: OpenClaw CLI Adapter Boundary

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `src/ai_news_agent/adapters/openclaw.py` | create | Normalize OpenClaw-facing hints and build safe digest CLI argv | `build_digest_cli_argv`, normalization helpers |
| `src/ai_news_agent/adapters/__init__.py` | create | Export adapter helpers for import stability | adapter exports |
| `tests/test_openclaw_adapter.py` | create | Verify normalization, argv construction, and input validation behavior | pytest coverage for adapter API |

### Subsystem: OpenClaw Skill Contract

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `openclaw/skills/ai-news-digest/SKILL.md` | create | Define OpenClaw skill trigger and command delegation contract | `SKILL.md` frontmatter and instructions |

### Subsystem: User Setup Documentation

| Path | Create/Modify | Single Responsibility | Public Surface |
| --- | --- | --- | --- |
| `README.md` | modify | Document local OpenClaw setup, usage, and smoke checks | Milestone 3 usage section |

## Blast Radius

| Path | Why Sensitive | Existing Behavior To Preserve | Plan Mode |
| --- | --- | --- | --- |
| `src/ai_news_agent/sources.py` (indirect dependency) | Canonical source validation used by CLI and Gradio | Allowed sources and error semantics | high |
| `src/ai_news_agent/cli.py` (integration contract) | User-facing entrypoint and smoke workflow | Current flags and digest output behavior | high |
| `README.md` | Primary onboarding guide | Existing Milestone 1/2 setup clarity | medium |
| `openclaw/skills/ai-news-digest/SKILL.md` | Runtime execution instruction boundary | Safe deterministic command template | high |

## Workflow For Implementers

1. Keep this file as the durable type-1 plan for Milestone 3.
2. For `Plan mode: high` tasks, validate interfaces and tests before broad edits.
3. For `TDD suitable: yes`, follow fail-first tests where practical.
4. If plan assumptions change during implementation, update this plan and append changelog entry.

## Subtasks

### T1 - Implement OpenClaw Adapter Module

- [ ] **Do:** Add `src/ai_news_agent/adapters/openclaw.py` with helpers to normalize
  timeframe/source/topic hints and produce safe argv for `ai-news-agent digest`.
- **TDD suitable:** yes (pure logic and validation boundaries are deterministic)
- **Plan mode:** high
- **Verification:** `uv run pytest tests/test_openclaw_adapter.py -q`
- **Blocked by:** -

### T2 - Export Adapter Public Surface

- [ ] **Do:** Add `src/ai_news_agent/adapters/__init__.py` to export stable adapter helper APIs.
- **TDD suitable:** partial (lightweight export wiring; behavior validation comes from T1 tests)
- **Plan mode:** medium
- **Verification:** `uv run python -c "from ai_news_agent.adapters import build_digest_cli_argv"`
- **Blocked by:** T1

### T3 - Create OpenClaw Skill Definition

- [ ] **Do:** Add `openclaw/skills/ai-news-digest/SKILL.md` with natural-language trigger guidance,
  deterministic `exec` command template, argument mapping rules, and metadata gates.
- **TDD suitable:** no (declarative skill content; runtime validated by smoke usage)
- **Plan mode:** medium
- **Verification:** manual file review + local OpenClaw skill load/manual prompt check
- **Blocked by:** T1

### T4 - Update Milestone 3 Setup Docs

- [ ] **Do:** Update `README.md` with local OpenClaw Gateway setup assumptions, skill location/setup,
  required env vars, and smoke prompts.
- **TDD suitable:** no (documentation-only change)
- **Plan mode:** skip
- **Verification:** markdown review + command snippets align with current CLI usage
- **Blocked by:** T3

### T5 - Regression Sweep

- [ ] **Do:** Run focused and full tests, then fix any integration regressions discovered.
- **TDD suitable:** partial (verification/stabilization pass; bug fixes discovered here should be
  test-first where feasible)
- **Plan mode:** high
- **Verification:** `uv run pytest`
- **Blocked by:** T2, T3, T4

## Acceptance Checklist

- Adapter helpers exist with deterministic tests.
- OpenClaw skill contract file exists and maps to the CLI-backed flow.
- README contains actionable Milestone 3 setup and smoke instructions.
- Existing digest workflow behavior remains unchanged.
- Regression tests pass.

## Plan Changelog

| Date | Change |
| --- | --- |
| 2026-06-08 | Initial Milestone 3 plan created from approved OpenClaw integration spec |
| 2026-06-08 | Expanded to type-1 decomposition format with subsystem map, blast radius, and subtasks tagged by TDD suitability and Plan mode |
