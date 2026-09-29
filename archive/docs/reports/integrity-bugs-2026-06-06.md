# COSMU Integrity-Bug Report — 2026-06-06 (28-agent adversarial audit)

Hunting silent-correctness bugs that make the Gate/backtest produce a FAKE edge with no error + no failing test.
Full transcript: workflow `wxm5kcisy`. **These gate whether the "0 edges / 7 powered fails" verdict is even trustworthy.**

## P0 — Fakes the Gate verdict; MUST fix before ANY edge run
**One root bug, 4 entry points: the `risk_on` vs `pm_risk_on` name split.** Ingest stores `pm_risk_on`; consumers
still read `risk_on` → the headline cross-asset transfer feature is silently stripped from every LIVE Gate run.

- **P0-1 — `gate.py:764`** `fetch_series("MARKET","risk_on")`. `StoreBackedAltProvider` routes only `pm_risk_on`
  (`store.py:~207`) → returns `[]` (the `_STORE_METRIC_ALIAS` is keyed the wrong way, unreachable) → `_align`
  yields all-None → `_xp_riskon` (`gate.py:707`) returns True every bar → risk-on constraint = permanent no-op.
  **Fix:** query `"pm_risk_on"`; keep the feature key `f["risk_on"]`, predicate, and drop-label unchanged.
- **P0-2 — `research.py:89` (+`:105`); mirror in `evolution/loop.py`.** `_has_cross_asset_data` reads
  `risk_on` → always 0 → **production NEVER runs the live cross-asset arm; silently scores the SYNTHETIC fixture.**
  (`research/loop.py` was already fixed this session; `research.py` + `evolution/loop.py` are separate copies — fix them too.)
  **Fix:** trigger + `market_wide` set → `pm_risk_on`.
- **P0-3 — `test_cross_asset_gate.py:33,106`.** Test ingests `stored_metric="risk_on"` so test-name == gate-name →
  masks the bug; no test pairs real-ingest → store-provider → gate. **Fix:** `stored_metric="pm_risk_on"` + a NEW
  regression test that runs `evaluate_cross_asset_ablation` against a `StoreBackedAltProvider` populated under
  `pm_risk_on` and asserts `drop_one_source["risk_on"].delta != 0` on the live/store path.
- **P0-4 — `fixtures.py:395`.** Synthetic fixture stores `("MARKET","risk_on")` → offline shows a profitable
  edge (delta ~0.072), live shows 0.0, both PASS. **Fix:** store `pm_risk_on`.
- **HARDENING:** make `StoreBackedAltProvider.fetch_series` **raise/log on an unknown metric** instead of returning
  `[]` — turn this whole silent-miss class into a loud failure forever.

> Partial WIP for the social-field side of this is on branch `engine/risk_on-bridge-and-social-wiring` (UNVERIFIED;
> does NOT cover P0-2/research.py). Complete the 4 renames + hardening + the regression test, run the full suite, merge.

## P1 — none confirmed.

## P2 — latent traps (after the TOP-3 runs)
- **P2-1 — 5 enabled features with no store route** (`feature_registry.py:39,55,59,60,61`: `xasset_risk_appetite`,
  `cftc_net_positioning`, `days_to_earnings`, `insider_buy_ratio`, `short_interest_ratio`). `validate_spec` checks
  registry membership but not routability → a spec naming them validates, then reads empty. Latent (none traded
  today). **Fix:** add an offline guard test `{enabled features} ⊆ {routable}`; wire or disable the 5.
- **P2-2 — `test_catalog.py:14`** checks catalog↔routing but not registry↔routing (same gap). Add the invariant above.

**Verdict:** the Gate is NOT trustworthy on live data until P0 is fixed — the cross-asset arm is a silent no-op and
prod scores synthetic. Fix P0 + re-run before believing any edge result (incl. the 7 prior fails).
