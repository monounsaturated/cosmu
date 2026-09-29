# COSMU — Generalization / Research-Engine Plan (barbell) — 2026-06-06

Adopted (claims verified against the tree). **One correction vs the source memo: the Gate is NOT trustworthy yet
(see `integrity-bugs-2026-06-06.md` + `poc-acceleration-plan.md`) — fix the harness BEFORE adding sources, or new
adapters just feed a broken oracle.**

## The doctrine (keeps it smart, not slop)
Finance works because it has an **incorruptible oracle**: did price move, did it profit net of fees? The Gate can't be
lied to. Health/medicine/habits/"ontology" have **no cheap objective oracle** → building them as *advice* re-creates
the v1 failure (LLM grading its own homework) and abandons the north star (profit is the only score).
**RULE: generalize the substrate; keep the money-machine as proving ground + revenue. A domain graduates from
"correlation surface (read-only, disclaimers)" to "research engine" ONLY when it brings its OWN oracle.**

Architecture (already ~70% built): `source → ingest/llm_formatter (text→TypedFeature, never on money path) →
PIT store → feature_registry → Gate`. New source = a new **adapter** in `data/sources/` + `/add-data-source`, NOT a new app.

## Sequence (re-ordered for trust-first)
- **Lane A0 — REAL NOW (this session's #1):** harness-trust fix (P0 risk_on) + Binance-Vision bar backbone + honesty
  fixes (fake `exchange_netflow`, funding annualization, FRED vintage) → **re-run the crypto cohort.** Prove the Gate
  works before feeding it more. *Adding sources before this is wasted.*
- **Lane A1 — cheap + independent (do early, parallel-safe — it's an ACCESS layer, not the Gate):**
  **MCP over the engine + Supabase/Postgres** so Claude Code & agents query the DB / run the Gate natively. Biggest
  "Claude Code drives it" lever; thin wrap of existing CLIs. Aligns with the agentic-first vision.
- **Lane A2 — new feature families (AFTER A0 is trustworthy), ROI order:**
  1. **LlamaParse/Unstructured → SEC filings** (8-K/10-Q/Form 4/13F + transcripts) → TypedFeatures. *(Note: this is an
     EQUITIES expansion — only pursue once crypto is honestly tested AND we decide to trade equities / use them as
     cross-asset transfer features. Task drafted: `.claude/tasks/lane-a-filings-llamaparse.md`.)*
  2. **Firecrawl + GDELT (free) + Quiver** — Reddit/web/news/congress/insider weak signals; one adapter each.
  3. **Cohere Rerank** on pgvector — sharper qual→quant retrieval; drop-in, pennies.
  4. **Renovate (free) + CodeRabbit** — dep hygiene + AI review on every agent PR; config only.
- **Lane B — VISION, not a now-build:** cross-domain platform. The formatter/source-trust/PIT-store/scan-signals are
  already domain-agnostic → a "domain" = config (source set + feature taxonomy + **its own scorer/oracle**).
  Engineering/quant facts can have an oracle (reproducible benchmark) → eligible sooner. Health/medicine/habits =
  correlation surface with disconfirmers + FDR + heavy disclaimers, **never advice, never an unguarded claim.**
  A `/add-domain` skill (scaffold: sources + taxonomy + REQUIRED oracle) is the eventual build interface.

## Why this stays coherent + profitable
One pipeline, not many apps. Finance funds + proves the engine; other domains wait behind an oracle. Lane B spends
nothing until Lane A pays for it. Every Lane A item adds edges to the money-machine — but ONLY once the Gate is honest.
