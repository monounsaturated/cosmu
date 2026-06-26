# Epic — Capped DISCRETIONARY LIVE lane (DESIGN-PENDING · invariant-exception)

> Status: **DESIGN-PENDING — operator must approve this design before any code touches real orders.**
> Source: operator decision 2026-06-15. **Extracted verbatim from `BACKLOG.md` on 2026-06-26** (status-first
> restructure, per `docs/reports/backlog-structure-audit-2026-06-26.md`) — the spec lived only inline in the
> backlog; it now lives here and is indexed from `BACKLOG.md ## EPICS (index)`.
>
> ⚠️ **invariant-exception:** this is a deliberate, bounded exception to the hard invariant *"the deterministic
> Gate is the SOLE funder of real money."* It must NEVER be picked up as routine work — it ships ONLY after the
> operator signs off on the safety design below, and the LLM still NEVER fires the order itself.

---

## EPIC: Capped DISCRETIONARY LIVE lane (DESIGN-FIRST — operator must approve the design before any code touches real orders)

Operator decision 2026-06-15: allow a non-FDR-gated strategy (e.g. an LLM/event-driven "act like a human on
tweets" strategy) to move SMALL, hard-capped REAL money. This is a deliberate, bounded exception to "the
deterministic Gate is the SOLE funder of real money" — so it ships ONLY with the safety design below, and the
LLM still NEVER fires the order itself (the deterministic order path + risk gauntlet do).

Safety design (the spec to approve):

1. **A lighter, named admission check stands in for the FDR cohort gate** — NOT "no check": the strategy must
   clear an honest event-study/credibility bar (a real, pre-registered SCAR verdict from `research/event_study.py`
   and/or a min `voice_scoreboard` skill) before it can be armed. Volume can't manufacture admission.
2. **Its own interlocks, stricter than the standard 5:** a dedicated `discretionary` lane flag (off by default),
   a hard per-trade cap + a hard daily-spend cap + a global discretionary-capital cap (all separate from the
   gate-lane caps), the kill-switch, and venue key-gating. Any one missing ⇒ sim fill, no real order.
3. **Memoryless sizing preserved** (no martingale/revenge), SL/TP still required, every decision + fill audited
   with the admitting check recorded, and a paper twin runs alongside for SIM↔live variance attribution.
4. **Auto-disarm on the daily-loss cap and on edge decay** (reuse `master/drift.py`), same as gate-lane tracks.

INVARIANT kept: the LLM proposes/admits via the deterministic check; it never defines its own success metric and
never fires the order. Acceptance: a discretionary strategy can be armed live within the caps, every guardrail
is exercised by tests, and the audit trail shows the admitting check + the fill.

**Tag:** (engine+web, opus — DESIGN PR first: write the spec to `docs/epics/`, get operator sign-off, THEN implement.)
