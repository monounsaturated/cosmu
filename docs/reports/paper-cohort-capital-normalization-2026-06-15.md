# Paper cohort `starting_capital` normalization — 2026-06-15

## Decision: (a) normalize the legacy $10k tracks down to the $1k canonical

The Paper cohort had an inconsistent per-track `starting_capital`: **8 legacy tracks seeded at $10,000**, the
rest at the canonical **$1,000** (`settings.sim_track_capital`). This was **pre-canonical drift** — those rows
were written before `sim_track_capital` became the standard — **not** a position-sizing experiment:

- All capital-*setting* paths already stamp `settings.sim_track_capital`: `spine/engine.py:199`,
  `lab/finder.py:536`, `evolution/loop.py:496`, and every `research/*_arm.py`. The system can no longer *produce*
  a $10k track, so the mix was orphaned.
- A repo-wide grep found **zero** `$10k` literal tied to track capital and **zero** "sizing experiment" reference
  in code or docs.
- Fees are linear in notional (`fee = notional · taker_fee_bps/10000`, no fixed component), and the stored
  positions already hold 8-decimal fractional shares (violating `lot_size=1`), so the larger notional was not
  "more execution-realistic". A flat track encodes identical information at $10k or $1k.

Option (b) — keep the mix and document a rationale — was rejected: there is no real experiment to document, and
inventing one would violate the project's honesty bar. The mix actively corrupted the only numbers the operator
watches: `/overview` sums `starting_capital` for the Paper hero (each $10k track counted 10×), and
`leaderboard`/`costs`/detail showed $10k-vs-$1k deltas for economically identical **flat** tracks.

## Why it is point-in-time honest (no fabricated equity)

Every one of the 8 legacy tracks was **flat at rebase**: `realized_pnl = 0` on all 15 position legs, and the
latest marked `scope='track'` snapshot equalled `starting_capital` (mark == basis, no fresh tick), `return_pct =
0`. A **uniform rescale by `factor = canonical / old_start` (= 0.1)** is therefore exactly return-preserving:

```
(k · equity) / (k · start) − 1  ==  equity / start − 1  ==  0%
```

No equity is fabricated — a $0-P&L track stays a $0-P&L track, just restated at the canonical $1k notional. The
migration **refuses (exit 2)** to touch any track carrying realized P&L, so it can never silently restate a real
result. `return_pct` (the backtest OOS %, a ratio) is left unchanged.

## What was changed (one atomic transaction, idempotent, backed up first)

`scripts/normalize_paper_cohort_capital.py` — dry-run by default; `--apply` to execute. For each track where
`|starting_capital − canonical| > 1e-6`, with `factor = canonical/old_start`:

| Table | Columns rescaled | Notes |
|---|---|---|
| `tracks` | `starting_capital` → exact `$1000`, `equity` × factor | `return_pct` preserved |
| `positions` | `qty`, `realized_pnl` × factor | `avg_price` **not** rescaled (per-unit price); notional then scales correctly |
| `executions` | `qty` × factor | synthetic `kickstart_backfill` seed fills (fee=0); keeps the detail-sheet blotter coherent with the rebased position |
| `portfolio_snapshots` (scope='track') | `equity`, `positions_value` × factor | `cash`/`pnl`/`drawdown` are structurally 0 for track scope |
| `events` | append one `track_rebased` event per track | old/new capital, factor, per-table row counts, `flat_at_rebase` |

Not touched (verified correct): `scope='aggregate'` snapshots (the hero rebuilds from the bankroll-independent
`pnl`, which is 0 both sides and self-heals on the next mark), `backtests`/`runs` (scale-free), historical event
payloads (append-only). The pre-existing $1k tracks (DAA, PAA, Faber, Perp) were untouched — they retain their
backtest seed equity and real marked values.

### Applied result (live prod, Supabase eu-west-3)

- **8 tracks rebased**, 351 `scope='track'` snapshots + 15 positions + 15 executions rescaled; 8 `track_rebased`
  events written.
- `tracks.starting_capital` histogram after: **`{'1000': 12}`** — whole cohort consistent.
- `/overview` Paper hero allocated: **~$73k → $10k** (10 paper tracks × $1k).
- Re-running `--apply` is a clean no-op ("nothing to do"). Backup: `.cosmu/paper_cohort_capital_backup_*.json`
  (gitignored; pre-image rows keyed by id — factor is exactly invertible ×10).

## Single-source-of-truth guard

`settings.sim_track_capital` is confirmed the sole source of truth, and a regression test locks it:
`apps/engine/tests/test_track_capital_invariant.py` (4 tests, green) —

1. pins `Settings().sim_track_capital == Decimal("1000")`;
2. drives the real `finder._persist` promotion with a **sentinel** `Settings(sim_track_capital=4242)` and asserts
   the persisted `starting_capital == 4242` (proves the value flows from the setting, not a literal);
3. same for the spine seeding branch (`EngineFacade.run_backtest`, scorer forced to pass);
4. a static guard that greps the whole `cosmu/` package for any `"starting_capital": <numeric literal>` — the
   exact shape of the legacy drift — and fails on it (mutation-tested: canonical name-based forms pass, literal
   forms are caught).

`kickstart_paper_fills` (which gave the legacy tracks their synthetic paper fills) derives qty *from* `positions`
and is idempotent, so it is downstream of capital and cannot reintroduce a non-canonical size.
