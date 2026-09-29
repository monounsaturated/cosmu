# Free-data hoard + R2 capacity — 2026-06-26

**Mandate (operator):** *"do hoard polymarket data, and other, price, etc — tons of free data to hoard now."*
**Rule it follows:** hoard FORWARD-ONLY / non-backfillable data NOW; test paid sources just-in-time (see
`docs/DATA_SUPPLIER_PROTOCOL.md`). This was a **representative, resumable** hoard pass — not a multi-hour run —
that lands real depth immediately and **accumulates** on every subsequent run via the never-shrink union pattern.

Zero production impact: read-only public/keyless fetches, no DB writes, no Gate constant touched, no runtime-path
code merged. The only new code is one standalone hoard script + this report + two protocol docs + a BACKLOG edit.

---

## TL;DR

- **~22 MB of net-new data hoarded** to R2 this pass (≈4.6 MB price bars + ≈17 MB Polymarket), across **5 prefixes**.
- **R2 now holds 340 MB of 10 GB free tier = 3.3 % used, 9.67 GB headroom.** Yes — **still free even after hoarding
  tons**, with ~29× the current footprint of room before the storage cap, and the hourly cron op-load sits at
  ~43 % of the Class-A free allowance / ~4 % of Class-B (real numbers below).
- The hoarded **books + trade prints are non-backfillable** — capturing them forward is the *only* way to ever have
  this history. That is exactly the data the operator rule says to grab now.

---

## 1 · What was hoarded

### A. Per-venue PRICE bars → `bars/<venue>/<SYMBOL>_<tf>.json`
Reuses `cosmu/data/bar_archive.py::archive_bars` — the never-shrink UNION-MERGE (read object → merge deduped-on-ts
→ write back; the fetched bar wins a ts collision). Kraken + Bybit keyless REST, the Tier-0 `PERP_UNIVERSE`
(30 deepest names) × {1d, 1h}. Each keyless window is shallow (~720 bars Kraken / ~1000 Bybit); archiving
accumulates depth the REST window can never serve in one call.

| venue / tf | series | merged bars | skipped |
|---|---:|---:|---:|
| kraken / 1d | 30 | 21,318 | 0 |
| kraken / 1h | 30 | 21,600 | 0 |
| bybit / 1d | 5 | 4,997 | 25 |
| bybit / 1h | 4 | 3,996 | 25 |
| **total** | **69** | **51,911** | — |

Kraken covered all 30 names cleanly. Bybit skipped most of `PERP_UNIVERSE` — those `…USDT` perps are not all listed
on **Bybit spot** (the keyless spot kline only serves currently-listed spot pairs); the names that *do* list (BTC,
ETH, SOL, XRP, …) archived fine. Binance is already hoarded by the live hourly `ingest` cron via `archive_universe_bars`
(`#383`), so this pass deliberately deepened the two under-covered keyless venues. **The `bars/` prefix grew 5.0 MB → 9.6 MB.**

### B. Polymarket FORWARD-ONLY data (keyless Gamma + CLOB + data-api)
New script `apps/engine/scripts/research/polymarket_hoard.py`. Discovery = the 250 most-liquid OPEN order-book
binary markets (Gamma `/markets`, liquidity-ranked). Four distinct R2 prefixes, each under the same never-shrink
discipline:

| data | endpoint (keyless) | R2 prefix | captured this pass | backfillable? |
|---|---|---|---|---|
| YES-odds history (hourly) | `clob.polymarket.com/prices-history?fidelity=60&interval=max` | `pm_odds/<cid>_60.json` | **250 markets · 101,708 rows** | partial — only as far as the venue keeps the series |
| L2 depth book snapshot | `clob.polymarket.com/book?token_id=` | `pm_book/<date>/<cid>.json` | **120 live snapshots** | **NO — a book exists only at the instant sampled** |
| real BUY/SELL trade prints | `data-api.polymarket.com/trades?market=` | `pm_trades/<cid>.json` | **92 markets · 18,778 prints** (28 thin/no-print) | **NO — public flow log is a bounded window** |
| open-market metadata | Gamma `/markets` | `pm_markets/<date>.json` | 1 daily snapshot (250 markets) | self-describing index |

The odds series UNION-MERGE on the `{t: p}` map (never shrinks). Book snapshots APPEND one point-in-time ladder per
run into a per-(date, market) list. Trade prints UNION-MERGE deduped on `(ts, side, price, size)`. Every per-market
fetch error is logged + skipped, never aborts the loop; the whole script is a loud no-op when R2 creds are absent.

**Why this matters:** the `pm_book` ladder and `pm_trades` prints are the two things the #400/#405 maker-feasibility
study flagged as *unknowable offline* (queue position, real fill flow). They cannot be reconstructed after the fact —
nobody serves historical Polymarket books. Hoarding them forward is the only path to ever testing a maker fill model
honestly. (Existing `polymarket_research/` from the 2026-06-21 exec study is untouched; these are new, ongoing prefixes.)

### Net-new this pass
≈**22 MB** ( bars +4.6 MB · `pm_trades` 14.8 MB · `pm_odds` 1.85 MB · `pm_book` 0.21 MB · `pm_markets` 0.08 MB ).

---

## 2 · R2 capacity — "still free even after hoarding tons?"  → **YES**

Current usage (sum of object sizes across all prefixes, measured this run):

| prefix | size | objects |
|---|---:|---:|
| backups | 100.88 MB | 14 |
| alt_lake | 69.86 MB | 139 |
| alt_data | 63.83 MB | 58 |
| positioning | 47.39 MB | 216 |
| polymarket_research | 20.03 MB | 32 |
| **pm_trades** (new) | 14.78 MB | 92 |
| bars | 9.59 MB | 120 |
| universe | 8.59 MB | 10 |
| astro_lab | 2.84 MB | 60 |
| **pm_odds** (new) | 1.85 MB | 250 |
| **pm_book** (new) | 0.21 MB | 120 |
| research_registry | 0.12 MB | 20 |
| **pm_markets** (new) | 0.08 MB | 1 |
| **TOTAL** | **340.0 MB** | **1,132** |

### Cloudflare R2 free tier (official, current)
| resource | free / month | rate beyond free |
|---|---|---|
| Standard storage | **10 GB-month** | $0.015 / GB-mo |
| Class A ops (PUT/LIST/POST) | **1,000,000** | $4.50 / million |
| Class B ops (GET/HEAD) | **10,000,000** | $0.36 / million |
| **Egress** | **unlimited, free** | $0 — always |

### Headroom verdict
- **Storage: 340 MB / 10,240 MB = 3.32 % used → 9.67 GB free.** ~29× the current footprint before the cap. Even a
  20× blow-up of *everything* (6.8 GB) stays free. R2 egress is free forever, so reading the hoard back for
  backtests costs nothing.
- **Operations (the only thing a frequent hoard can stress):** one full hoard pass ≈ **584 Class-A** (PUTs + a few
  LISTs) + **580 Class-B** (read-before-merge GETs). At an **hourly** cron (~730 runs/mo) that is **~426 k Class-A
  (42.6 % of free)** and **~423 k Class-B (4.2 % of free)** — and the real number is *lower*, because the odds
  union-merge only PUTs when the series actually changed (a re-archive of a stable window is a pure GET, no PUT).
- **Bottom line:** the hoard is comfortably free at hourly cadence today. The first knob to watch is **Class-A ops**,
  not storage — if the market count or cadence grows, batch writes or drop the cadence before storage ever bites.

---

## 3 · How to re-run / extend (resumable + idempotent)

```bash
cd apps/engine
# price bars (existing machinery, already on the hourly ingest cron for Binance):
python -m cosmu.data.bar_archive hoard
# polymarket forward-only data (new):
python scripts/research/polymarket_hoard.py \
    --max-markets 300 --book-sample 150 --trades-sample 150 --fidelity 60
```

Both are idempotent (re-running merges, never shrinks) and bounded by their caps, so they are safe to schedule.
**Recommended next step:** add `polymarket_hoard.py` to the hourly Modal `ingest` cron alongside the bar hoard so
the books + trade-print history accumulates continuously — that is the forward capture the maker-feasibility lane
needs, and it stays inside the free tier per §2.

---

## Provenance
- Price archive: `cosmu/data/bar_archive.py` (`archive_bars`, never-shrink union), `cosmu/data/market.py`
  (`KrakenSpotOHLCVProvider`, `BybitSpotOHLCVProvider`), `cosmu/data/universe.py::PERP_UNIVERSE`.
- Polymarket: `apps/engine/scripts/research/polymarket_hoard.py` (new); endpoint contracts inherited from
  `cosmu/data/sources/polymarket.py` + the #400/#405 maker-feasibility harness.
- R2 limits: Cloudflare R2 pricing docs (storage 10 GB / Class A 1 M / Class B 10 M / egress free; rates
  $0.015 GB-mo, $4.50 / M Class-A, $0.36 / M Class-B).
- All numbers from a live run on 2026-06-26.
