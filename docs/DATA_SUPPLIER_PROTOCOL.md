# Data Supplier Protocol

How COSMU decides where data comes from — when to hoard, when to shop, when to pay. One page; read before adding
any new feed. Companion to `docs/DATA_INDEX.md` (where data *lives*) and the `add-data-source` / `profile-source`
skills (how to *wire and vet* it).

---

## The two-track rule (the whole protocol in one line)

> **Hoard FORWARD-ONLY data NOW. Shop for everything else JUST-IN-TIME, when a hypothesis needs it.**

1. **HOARD NOW — forward-only / non-backfillable data.** If a source's history is *lost forever* once the moment
   passes — order books, live trade prints, funding snapshots, live odds, sentiment-at-the-time — capture it
   continuously **starting today**, even before a hypothesis needs it. You cannot buy 2026's order book in 2027.
   This is cheap (keyless/free for our current sources) and the storage is effectively free (R2 free tier — see
   `docs/reports/data-hoard-2026-06-26.md`). Examples already hoarded: per-venue price bars (`bars/`), Polymarket
   odds/books/trades (`pm_odds/`, `pm_book/`, `pm_trades/`).

2. **SHOP JIT — everything backfillable.** If a source can be pulled deep at any later date (most vendor price/
   fundamental/macro history), **do not** pre-buy or pre-ingest it. Test it only **when a specific hypothesis needs
   it** — the JIT default keeps spend and clutter down and avoids paying for data no edge ever consumes.

The cheap-when-cheap, paid-when-it-pays asymmetry: hoarding free forward data has near-zero cost and unbounded
optionality, so do it now. Buying backfillable data has real cost and we can always get it later, so wait for a
proven need.

---

## When we want a NEW data source — the shopping procedure

When a hypothesis (or a research pass) calls for a source we don't have:

1. **BROWSE the web.** Find the real suppliers — APIs, vendors, free public endpoints, datasets. Don't assume; look.
2. **COMPARE on six axes.** For each candidate supplier, capture:
   - **Price** — free / metered / flat; cost at our expected call volume.
   - **Quality** — accuracy, revision behavior, point-in-time honesty (no look-ahead), survivorship completeness.
   - **Coverage** — which assets / venues / markets / history depth.
   - **Frequency** — update cadence (tick / minute / hourly / daily) vs what the hypothesis needs.
   - **Latency** — how fast after the real-world event the data is available (the live-trading constraint).
   - **Licensing** — redistribution / commercial-use terms; ToS compatibility (no account-rotation hacks).
3. **SUGGEST free-vs-paid with the WHY and the expected IMPACT.** Present the operator a short comparison plus a
   recommendation that names the *reason* (e.g. "paid X gives delisted-name coverage the free feed lacks → fixes
   the survivorship hole on the momentum lane") and the *expected impact on edge/profit*, not just specs.
4. **OK to PAY when it measurably helps impact.** Paying is allowed and encouraged **when the incremental data
   demonstrably improves an edge or unblocks a real hypothesis**. Never overpay for no incremental value — if the
   free feed is good enough for the hypothesis, use the free feed.

### Decision shorthand
| situation | action |
|---|---|
| forward-only / non-backfillable | **HOARD NOW** (free, continuous) |
| backfillable, no hypothesis needs it yet | **WAIT** (don't buy, don't ingest) |
| hypothesis needs it, free feed suffices | use the **free** feed |
| hypothesis needs it, paid feed adds measurable edge | **PAY** (with the why + impact stated) |
| paid feed adds nothing the free one lacks | **don't pay** |

---

## Before a new source becomes a feature

Vet it first — an untrusted feed must not silently become a backtest input:
- Run the **`profile-source`** skill → GO / REVIEW / NO-GO on coverage · gaps · staleness · look-ahead · PIT-lag
  honesty · revision safety.
- Then wire it with **`add-data-source`** (registry + feature_registry + catalog + PIT bridges, the lock-step).
- Honor the leakage guard: point-in-time `available_at` lag, no look-ahead, deterministic. (See the vibe-coding
  leakage note — the #1 blow-up is a leak *upstream* of the Gate.)

---

## Storage placement (where the hoard lands)

State → Supabase. History / lake / backups / hoard → **Cloudflare R2** (`cosmu-lake`, egress-free, 10 GB free tier).
Use the never-shrink UNION-MERGE pattern (`cosmu/data/bar_archive.py`) so a shallow keyless window accumulates into
deep history and a re-run can only ADD or REPAIR rows, never remove one. See `docs/DATA_INDEX.md` for the full map.

---

## Current forward-only hoards (keep these running)
| data | prefix | cadence | non-backfillable? |
|---|---|---|---|
| per-venue price bars (Kraken/Bybit/Binance) | `bars/` | hourly ingest cron | window-limited |
| Polymarket YES-odds history | `pm_odds/` | hourly (recommended) | partially |
| Polymarket L2 book snapshots | `pm_book/` | hourly (recommended) | **yes** |
| Polymarket real trade prints | `pm_trades/` | hourly (recommended) | **yes** |

Re-run / extend: `python scripts/research/polymarket_hoard.py` and `python -m cosmu.data.bar_archive hoard`
(both idempotent + bounded). See `docs/reports/data-hoard-2026-06-26.md`.
