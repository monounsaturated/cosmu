---
name: profile-source
description: Data-trust audit for a NEW alt-data source — auto-profile its point-in-time history (coverage · gaps · staleness · look-ahead · PIT-lag honesty · revision safety) into a GO / REVIEW / NO-GO verdict BEFORE it becomes a feature. Use to vet an untrusted feed before wiring it into the feature registry.
---

# profile-source

A new data feed is **guilty until proven point-in-time**. Before a source is allowed to influence the gate — before it earns a `FeatureDefinition` and starts shaping which strategies get funded — it must pass a **data-trust audit**. This skill is that audit: it profiles the source's *already-ingested* point-in-time history and returns a single **GO / REVIEW / NO-GO** verdict, so a leaky or hollow feed never silently becomes an edge.

**Review-only.** The audit only *recommends* — it wires nothing, mutates no store, moves no money. A human still does the wiring (via **add-data-source**). It is out of the gate path and out of the money path.

## When to use
- You just ingested a candidate alt-source (funding, sentiment, on-chain, macro, OSINT, …) and ask: *"can the gate trust this point-in-time, or will it leak?"*
- Before promoting a `tier1` feed, or before relying on a vendor you haven't vetted.
- As a pre-flight inside **add-data-source** (audit the feed before adding the `FeatureDefinition`).

## Run (from repo root; `PYTHONPATH=apps/engine`)
```bash
PYTHONPATH=apps/engine python3 -m cosmu.ingest.profile_source <provider> <symbol> <metric> \
    --declared-lag-hours 24            # the release lag from the source's as-of semantics (next-day = 24)
PYTHONPATH=apps/engine python3 -m cosmu.ingest.profile_source alternative.me MARKET fear_greed --declared-lag-hours 24
PYTHONPATH=apps/engine python3 -m cosmu.ingest.profile_source binance BTCUSDT funding_rate --json
```
Need data first? Ingest the candidate with **manage-data** (`fetch <source>` / `backfill`) so the append-only PIT store has its history, then audit. Exit code is non-zero on **NO-GO** (so it can gate a script/CI step).

## The six checks (composes `ingest/coverage.py` — never re-implements gap/staleness/look-ahead)
| Check | Severity | NO-GO / REVIEW when |
|-------|----------|---------------------|
| **coverage_depth** | soft → REVIEW | < 60 rows or < 30 days span — too shallow to judge an edge OOS |
| **gaps** | soft → REVIEW | > 10% of the expected bucket grid is missing |
| **staleness** | soft → REVIEW | freshest point older than 3d (or 3× the series' own cadence) |
| **look_ahead** | **hard → NO-GO** | any row with `available_at < ts` — a point-in-time leak |
| **pit_lag** | **hard → NO-GO** | declares a release lag (e.g. next-day) but is stamped available much sooner — a **latent** leak the raw look-ahead check can't see |
| **revision_safety** | soft → REVIEW | many silent same-`ts` restatements (vendor rewrites history) — only safe behind the append-only PIT store |

Roll-up: **any hard fail → NO-GO**; else **any soft fail → REVIEW**; else **GO**. An empty feed is **NO-GO** ("no data — nothing to trust"). The PIT-lag check is the value-add over plain coverage: a feed that *claims* it's known sooner than it really is will read the future in a backtest, so it is a hard stop.

## Verdict → action
- **GO** — deep, fresh, dense, point-in-time honest. Safe to wire as a `FeatureDefinition` (start `tier1`; it still has to earn its place OOS through the gate).
- **REVIEW** — usable but caveated: deepen history (**manage-data** `backfill`), close gaps, or accept the revision/staleness caveat consciously before adding.
- **NO-GO** — do **not** make it a feature. Fix the ingest (correct the `available_at` stamping so it reflects real release time) and re-audit, or drop the source.

## Invariants
- **Pure + offline + deterministic** — the clock is injected (never wall-time), no network, read-only on the store.
- **Review-only** — recommends a verdict; it never wires a feature or moves money. Out of the gate/money path.
- **Point-in-time law** — `available_at >= ts` is enforced as a hard stop; a feed that can't be trusted PIT never becomes an edge.

## Verify
- `cd apps/engine && PYTHONPATH=. python3 -m pytest tests/test_profile_source.py -q`
