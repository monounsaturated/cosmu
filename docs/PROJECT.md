# COSMU — read this first (the whole project in one page)

**A self-running quant research machine + a tradeable floor.** It invents trading strategies, tests them through
a deterministic Gate that *cannot be fooled or tuned to pass*, deploys the robust ones, and remembers every
result. **The machine that never lies is the asset.** North star: profit net of fees.

## ✅ What it DOES (live today)
- **Tests any strategy honestly** — a spec/idea → backtest on real data, net of REAL fees, through BH-FDR + a
  purged out-of-sample holdout → PASS/FAIL. No look-ahead, no tuning to pass, an honest FAIL is valid.
- **Runs a live floor** — 9 documented strategies (GEM, TSMOM, Faber GTAA…) forward-testing on real data; you arm
  the matured winners. Modest, real, crash-protected (GEM = half SPY's drawdown).
- **Remembers everything** — every theory + verdict on the **Theories** page (the experiment memory).
- **Mines data for signals** — a correlation engine scans 61 features × assets for honest (PIT, stride-sampled,
  FDR-controlled) forward-return correlations → candidate hypotheses for the Gate.

## ❌ What it does NOT do (honest)
- No magic edge yet — **64+ theories tested, 0 survived** (crypto/equity-daily is honestly exhausted).
- Never moves money on its own — **you** arm live, always.
- No deep-ML on thin data — it overfits; deliberately avoided. *Better data > model cleverness.*

## 🖥️ How to use it (two ways)
1. **The app:** Overview (status) · **Strategies** (the floor = the money) · **Theories** (what's been tested) ·
   Lab (drop an idea) · Mind (what it knows) · Costs.
2. **Chat in Claude Code (local):** *"test a funding-gated momentum strategy on majors"* → it authors specs,
   gates them, shows verdicts. `python -m cosmu.research.matrix_search --sweep` tries the whole universe at once.

## 💪 Good at  ·  ⚠️ Flaw
- **Good:** honesty (0 false positives), speed (parallel agents/Modal), a real floor, total memory.
- **Flaw:** no edge yet — the binding limit is **DATA** (crypto-daily is thin/exhausted). Fix = new ORTHOGONAL
  data, NOT more search. And we don't yet *surface* the data/correlation analysis visually enough.

## 🎯 THE ONE PLAN — stop circling
The **floor IS the product** — let it compound, arm matured winners. The **swing** = add **ONE new data axis at
a time** (intraday → on-chain → SEC filings) → the correlation engine + Gate test it automatically → results land
in Theories. **Never re-search exhausted data.** Expect most theories to FAIL — that's the machine working.

## 🔭 Next builds (finite — pick top-down)
1. **Surface the power** — a "Signals" view (correlation-scan results) + the data/analysis made visible, so it
   *feels* powerful (today the analysis is real but only legible in Claude Code).
2. **Add ONE new data source** (intraday bars first) via `add-data-source` + `profile-source`.
3. **Deeper testing** — wire `master/cpcv.py` (banked) into the Gate; stress survivors with `data/slippage.py`.
4. **Smoother chat-to-test** — the `strategize` front door, end-to-end QA.

## ⚙️ Operating rules
- **LOCAL agents (this Mac) for testing/QA** — they have `.env.local` (keys), the data cache, and can run the
  Gate + `railway run` (prod). **CLOUD/separate sessions only for isolated parallel BUILDS** (they lack secrets/data).
- Heavy compute → **Modal**. Always-on/crons → **Railway**. Orchestration → **this local session**.
- Live: **cosmu.up.railway.app** (engine) · Vercel (web) · Supabase (store).

*Detail: `docs/HANDOFF_NEXT.md` (full state) · `docs/DECISIONS.md` (every verdict) · `docs/STRATEGIES.md` (what's tested).*
