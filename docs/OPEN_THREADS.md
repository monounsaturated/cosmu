# COSMU — Open Threads & Ideas Registry (don't forget any)

Updated 2026-06-07. The single place tracking active work, open PRs, parked ideas, and known fixes — so nothing
is lost across the campaign. Pair with `docs/DECISIONS.md` (what we concluded) + `docs/STRATEGIES.md` (what we tested).

## 🔴 NEXT — resume here (2 tracks, efficient — search phase is DONE)
Crypto + equity *factor* search are honestly exhausted (the machine is proven: ~18 audited verdicts, 0 false positives, it audited itself). Forward = TWO tracks, no more exploratory price-factor waves:
- **🟢 Track 1 — the FLOOR (live pilot):** a documented robust strategy (dual-momentum / trend) armed in LIVE paper = the first tradeable output. (Agent a4c4eef was arming it; verify it's live + watchable on `/explorer`.)
- **🔭 Track 2 — the UPSIDE (LLM-narrative):** machinery built + leak-proof (PR #143). Next = pull a DEEP raw-text corpus (GDELT GKG via BigQuery, or CryptoPanic/news archive, 2-3yr, liquid names) → score on **MODAL** (~$ few, content-hash cached) → materialize to `alt_data` → run the harness unchanged → real verdict.
- **✅ Merge the wins:** #134 (unify-simulators), #140 (Explorer), #142 (REAL equity holdout), #143 (LLM-narrative machinery).
- **⚡ Efficiency rule:** Modal for heavy/parallel (corpus scoring, wide sweeps); Claude/parallel agents only for genuinely-new space. Stop re-searching exhausted surfaces.

## 🟡 OPEN PRs — reconcile, don't leave dangling
- **#134 unify-simulators** → **MERGE** (profit-critical — makes every verdict trustworthy; low-risk). *Priority.*
- **#135 conversational-box** → **RECONCILE**: operator pivoted to "lean DISPLAY, not a chat box." Keep the `/lab/author` wiring; the new frontend strategy-explorer supersedes the chat UI. Do NOT merge the chat box as-is.
- **#136 broaden-ingest** → review/merge (free data depth across the universe).
- **#137 L/S-neutral research record** → keep (the realest crypto signal, dSR 0.25 — revisit if a maker-rebate/cheaper venue appears).
- **#139 cross-venue funding + 5.7yr Bybit funding data** → keep (reusable data + harness).

## 🟠 KNOWN ISSUES / FIXES (queued)
- **🚨 STUBBED HOLDOUT in the equity cohorts (correctness — fix before trusting ANY equity survivor).** `research/equity_reversal_cohort.py:321` + `equity_lowvol_bab_cohort.py:459` hardcode `holdout_deflated_sharpe = Decimal('0.0001')` → always clears `>0` → DSR/PBO/FDR run on the SAME in-sample stream, no held-out window. So the equity waves ran a *weaker* gate than crypto. **Our equity NO-survivor conclusions are SAFE** (a weaker gate still failed → a real holdout fails harder), **but** wire a real purged+embargoed holdout (mirror the crypto `backtest.py` / momentum cohort path) before promoting any equity candidate to paper.
- **Stooq paywalled — the real scope is SMALL (my "macro broken" claim was FALSE).** Cross-asset PRICE-LEVEL series (spx/ndx/gold/eurusd) ALREADY migrated to Yahoo (`ingest/run.py:125`, done 2026-06-05, commit 042d952). True macro (macro_regime/vix/dxy/yield_curve/fed_funds) is **FRED, never Stooq** (`store.py:131-143`) — unaffected. Remaining stale: only `EquityDataAdapter` default (`adapters/data/equity.py:49`) + `StooqBarBackfiller` default (`ingest/manage.py:59`) still point at dead Stooq → swap to the existing `YahooDailyBarsProvider` (`market.py:243`). **Non-blocking** (live equities research reads the Yahoo cache directly). *(The equity Yahoo cache was produced by ad-hoc run wf_301fb14b, not a committed `backfill_equities.py`.)*
- **venue_fees → wire REAL France-accessible venues:** IBKR (equities ✅ FR), **Kraken Futures** (perps — Binance derivs geoblocked for FR retail), Kraken/Binance (spot). Stop using guessed fees.
- **Survivorship validation:** any EQUITY survivor MUST be re-validated on a **PIT survivorship-free universe** before paper (the 73-name set is *today's* survivors → long-only returns are inflated/uninvestable).
- **git hygiene:** every workflow agent MUST be `isolation:'worktree'` (a non-isolated agent drifted the main checkout once).

## 🔵 KEEP-FOR-LATER (do NOT discard — compare/revisit)
- **LLM-formatting** — unstructured text (news/social/filings) → LLM signal + confidence score → backtest through the Gate. Heavy LLM → **Modal** (`OPENROUTER_API_KEY` is in the secret). Next big build; plays to the operator's narrative edge.
- **PEAD / earnings-drift** — best-documented equity survivor in the literature; blocked on a **PIT earnings-date feed** (`add-data-source`).
- **OI/LSR/funding/intraday ACCRUAL** — record forward for months → re-mine crypto crowding/intraday at the resolution where that edge actually lives.
- **r/algotrading idea-ingestion** — scrape threads → low-confidence hypotheses → the Gate kills the noise.
- **Strategy × asset × timeframe matrix** (FDR-disciplined) — a wide sweep on **Modal** when a near-miss warrants it.
- **Maker-rebate venue / prediction-market mispricing** — alternative fee/edge surfaces (flip the taker-fee sign).
- **Intraday equity data** — the overnight/reversal edges may live below daily resolution.

## ✅ DONE / BANKED
- Crypto-retail searched out (5 waves / ~16 spaces / 0 edges, all audited) — a *successful negative*; the machine = 0 false positives.
- Equities pivot underway (deeper Yahoo data, lower IBKR fees, documented-survivable anomalies, the fee-realism insight).
- Cache-truncation footgun fixed + merged (#138). Memory + DECISIONS + STRATEGIES docs current.
