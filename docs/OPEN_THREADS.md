# COSMU — Open Threads & Ideas Registry (don't forget any)

Updated 2026-06-07. The single place tracking active work, open PRs, parked ideas, and known fixes — so nothing
is lost across the campaign. Pair with `docs/DECISIONS.md` (what we concluded) + `docs/STRATEGIES.md` (what we tested).

## 🔴 ACTIVE (running now)
- **Fee re-run at REAL IBKR fees** (reversal / BAB) — the potential *survivor unlock* (wave-1 fees were too conservative).
- **Equities wave 2** — low-turnover reversal · low-vol/BAB · sector-neutral · vol-targeted momentum.
- **Crypto-ML combinatorial method** — parallel long-shot (ML-found feature combos vs the hand-search).
- **Frontend strategy-explorer** — TradingView `lightweight-charts`: pick venue/asset, overlay, gross+net curves, explicit stats.

## 🟡 OPEN PRs — reconcile, don't leave dangling
- **#134 unify-simulators** → **MERGE** (profit-critical — makes every verdict trustworthy; low-risk). *Priority.*
- **#135 conversational-box** → **RECONCILE**: operator pivoted to "lean DISPLAY, not a chat box." Keep the `/lab/author` wiring; the new frontend strategy-explorer supersedes the chat UI. Do NOT merge the chat box as-is.
- **#136 broaden-ingest** → review/merge (free data depth across the universe).
- **#137 L/S-neutral research record** → keep (the realest crypto signal, dSR 0.25 — revisit if a maker-rebate/cheaper venue appears).
- **#139 cross-venue funding + 5.7yr Bybit funding data** → keep (reusable data + harness).

## 🟠 KNOWN ISSUES / FIXES (queued)
- **Stooq is DEAD (paywalled)** → `StooqDailyBarsProvider` + the multiasset macro series (spx/ndx/gold/eurusd/…) in `data/sources/multiasset.py` + `data/market.py` + `store.py` are **BROKEN**. Replace Stooq→**Yahoo v8** (the `backfill_equities.py` pattern). *Important — macro data is silently broken.*
- **venue_fees → wire REAL France-accessible venues:** IBKR (equities ✅ FR), **Kraken Futures** (perps — Binance derivs geoblocked for FR retail), Kraken/Binance (spot). Stop using guessed fees.
- **Survivorship validation:** any EQUITY survivor MUST be re-validated on a **PIT survivorship-free universe** before forward-test (the 73-name set is *today's* survivors → long-only returns are inflated/uninvestable).
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
