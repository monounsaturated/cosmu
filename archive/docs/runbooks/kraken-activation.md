# Runbook — activate Kraken as the keyless crypto bars venue

**Status:** PREPARED, not activated. Everything below is one set of steps the operator runs when ready.
**Scope:** flips the *keyless bars source* (the price series every backtest / paper clock reads) from
Binance to Kraken. This needs **no Kraken account** — Kraken's public OHLC endpoint is keyless. Only live
*trading* on Kraken needs API keys, and that is a separate, deferred step (not covered here).

**Why we'd flip it:** Binance geo-/regulatory-blocks our cloud IPs. The whole keyless crypto-bar source is
routed through a single flag (`COSMU_BARS_VENUE`, shipped in #360) so the swap is one variable, in one place,
with no code change.

---

## The flag (already merged — #360)

`COSMU_BARS_VENUE` is read in `apps/engine/cosmu/data/market.py::keyless_crypto_reference()`:

```python
venue = os.environ.get("COSMU_BARS_VENUE", "binance").strip().lower() or "binance"
return providers.get(venue, BinanceSpotOHLCVProvider)()
```

- Default `binance` → **byte-identical** to before the flag landed (zero behaviour change unset).
- `kraken` → swaps the whole keyless crypto-bar source to `KrakenSpotOHLCVProvider`.
- Unknown value → safe fallback to Binance.

Both providers share the **same symbol contract** (`BTCUSDT`; Kraken maps it to `XBTUSD` internally via
`_kraken_pair`) and degrade identically (offline → cache → empty), so the swap is transparent to every caller:
the screen, the paper clock, and the `/market/bars` HTTP endpoint all go through `keyless_crypto_reference()`.

### Pair-identity note (USD vs USDT)

Kraken quotes **USD** (`XBTUSD`), not USDT. This is intentional and safe:

- `cosmu/data/reference.py::_QUOTE_BUCKETS` buckets `USDT`, `USD`, `USDC` (and the other USD-dollar
  stables) into ONE canonical quote `USDT`. So Kraken `XBTUSD` and Binance `BTCUSDT` both resolve to the
  same canonical pair `BTC/USDT` → **pair identity holds** across the venue swap.
- The universal-price-layer alignment check (`reference.cross_venue_alignment` / `decision`) is exactly what
  would catch a quote that actually diverged (e.g. a depegged stable): it would FALL BACK to its own bars
  rather than silently mis-mark. The USD↔USDT basis is well inside the 25 bps UNIFY band for major pairs.

### Kraken REST limits (matters for backfill, not for the flip)

- Kraken's public OHLC returns **at most ~720 of the most-recent candles per interval** — and the `since`
  cursor only filters *within* that head window; it does **not** unlock older history (verified 2026-06-25).
  So the keyless depth ceiling is ~720 candles: **~2 years on `1d`**, ~120 days on `4h`, ~30 days on `1h`.
  For the live screen / paper clock that recent window is fine.
- **Deep multi-year history beyond ~720 candles is NOT available on Kraken's keyless public endpoint.** It
  comes from (a) the **existing Binance-sourced cache** — the provider's `_merge_bars` is a union on ts that
  **never shrinks**, so any Binance daily history already on disk is preserved and the Kraken window overlays
  the recent end; or (b) a paid deep-history vendor at the live phase. `scripts/backfill_kraken_bars.py`
  (below) pulls the full keyless Kraken window into the cache and is honest about this ceiling at runtime.

---

## Step 1 — flip the flag on the Railway engine

The Railway EU engine is the geo-unblocked box that serves `/market/bars`. Setting the flag here makes that
endpoint serve **Kraken-priced** bars. The cacheless Modal fleet then follows automatically because it reads
bars from this engine at runtime via `COSMU_BARS_URL` (see Step 2).

Set the variable on the **engine** Railway service:

- Dashboard: Railway project → the engine service → **Variables** → add
  `COSMU_BARS_VENUE = kraken` → deploy (Railway redeploys on a variable change).
- Or CLI (needs a valid project/account token linked to the engine service):

  ```bash
  railway variables --set "COSMU_BARS_VENUE=kraken"
  ```

  > Note: `RAILWAY_TOKEN` in our setup is a *project* token; confirm it is linked to the **engine** service
  > (not web/proxy) before running, or set it in the dashboard instead.

After the redeploy, the `/market/bars` endpoint serves Kraken bars. **Nothing else on Railway changes.**

---

## Step 2 — Modal fleet (cacheless mode → follows automatically)

The Modal fleet build logic lives in `apps/engine/remote/app.py`. Two modes, gated on `COSMU_BARS_URL`:

- **Cacheless mode (what prod uses):** when `COSMU_BARS_URL` is set, the screen fetches bars at RUNTIME from
  the Railway EU engine (`RemoteBarsProvider`). In this mode the build **drops** the local `.cosmu` bar
  cache from the image (see the `ignore=[... "**/.cosmu" if COSMU_BARS_URL ...]` block, and the `COSMU_BARS_SRC`
  baked-cache block is skipped because `COSMU_BARS_SRC` is unset). **No Binance cache is needed**, and because
  Modal relays whatever `/market/bars` returns, **the fleet already follows Step 1 with no Modal change** —
  once Railway serves Kraken bars, Modal serves Kraken bars.

  - **No `modal deploy` is strictly required** for the bars swap in cacheless mode. The fleet picks up Kraken
    on its next run because it fetches from Railway each tick (the `_REMOTE_BARS_MEMO` is per-container and a
    fresh container starts empty, so bars are never stale across deploys).

- **Baked-cache mode (legacy / `COSMU_BARS_URL` unset):** the image bundles a local Binance daily cache via
  `COSMU_BARS_SRC`. If the fleet is ever run this way, it would NOT follow Railway; you'd instead want to
  bake a Kraken cache and set `COSMU_BARS_VENUE=kraken` in the Modal secret/env. We do not run this way in
  prod — prefer cacheless.

**Belt-and-suspenders (recommended):** also set `COSMU_BARS_VENUE=kraken` in the Modal env/secret so any Modal
function that ever calls `keyless_crypto_reference()` directly (i.e. NOT via the remote URL) is consistent:

```bash
# from repo root, with the operator's local env (.env.local) present
# 1) add COSMU_BARS_VENUE=kraken to .env.local, then re-sync the Modal secret:
python3 scripts/sync_modal_secret.py     # = `pnpm modal:secret` — rebuilds the "cosmu-engine" Secret from .env.local

# 2) redeploy the fleet snapshot (manual — Modal has NO push-deploy):
modal deploy apps/engine/remote/app.py
```

> Reminder: the Modal fleet is a **manual snapshot** — `modal deploy` ships the current `main` checkout's
> code + secret. In cacheless mode no Binance bar cache is needed in the build context. After deploying,
> verify the snapshot matches `main` (Step 3).

---

## Step 3 — verification

Run these in order; all three should pass before declaring Kraken live.

### 3a. The Railway endpoint serves Kraken bars

```bash
curl -s -H "x-api-key: <API_SECRET_KEY>" \
  "<railway-engine-url>/market/bars?symbol=BTCUSDT&timeframe=1d&limit=2" | python3 -m json.tool
```

Expect a `bars` array of 2 rows with `ts/open/high/low/close/volume`. Sanity-check the close against a
public Kraken XBT/USD print for the same day — Kraken USD prints, so the level matches XBT/USD (within the
USD↔USDT basis), confirming the source is Kraken, not Binance.

### 3b. A paper track marks fresh

After the next paper-mark tick, confirm a held paper cell re-marks against a fresh Kraken close (its
`marked_at` / last mark advances). Quick check: `pnpm health-check` (or the `/health-check` skill) spot-checks
a random paper cell's clock + fills. The mark should be dated to the latest closed daily candle, not frozen.

### 3c. The Modal snapshot matches main

```bash
modal app history cosmu-engine          # top entry's commit == current origin/main HEAD
git -C <repo> rev-parse origin/main
```

If a `modal deploy` was run in Step 2, the top history entry's commit must equal `origin/main`. If you skipped
the deploy (pure cacheless follow), confirm the last good snapshot is still the latest `main` so the fleet
isn't running stale code unrelated to this flip.

---

## Rollback

Set `COSMU_BARS_VENUE` back to `binance` (or unset it) on the Railway engine and redeploy. The default is
byte-identical to pre-#360, so rollback is instant and total. Remove it from `.env.local` + re-sync the Modal
secret if you set it there.

---

## What is NOT in this runbook (deferred)

- **Live trading on Kraken** — needs Kraken API keys + the spot exec adapter armed. The adapter exists
  (`feat/kraken-venue`, code-only) but live arming is a separate, human-gated step. The bars off-ramp here
  is keyless and does NOT touch the money path.
- **Deep history backfill** — Kraken's public OHLC caps at ~720 most-recent candles (no `since` reach-back).
  Run `scripts/backfill_kraken_bars.py` to pull the full keyless Kraken window into the provider cache
  (idempotent, never shrinks). True multi-year depth beyond that ceiling stays on the existing
  Binance-sourced cache (preserved by the union-merge) or a paid vendor at the live phase:

  ```bash
  PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars            # wide default set, 1d
  PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars --dry-run  # fetch + count, no write
  ```
