# Deribit options-inefficiency substrate

A keyless, $0 substrate for the operator's "camping bots" idea: watch many classes of options inefficiency and
fire when a real opportunity appears. **Propose-only — nothing here places an order or moves money.**

The whole design turns on one hard fact: in options, the binding wall is **fillability**, not detection. Almost
any pricing relation (put-call parity, vertical/butterfly convexity, IV vs RV) shows "violations" when computed
off the **mid**, because the off-ATM bid-ask is enormous. The only honest test is to re-price each candidate at
**our own simultaneous top-of-book** at the instant we'd have acted — which is why this ships a forward logger
*and* a scanner, not just a scanner.

## The two halves

```
deribit_client.py   keyless reader over Deribit's PUBLIC API (no key, IP-rate-limited): index, DVOL,
                    book_summary (whole chain in ONE call), order_book (L2 + greeks + sizes). Offline-injectable.
chain.py            typed, frozen OptionQuote / ChainSnapshot + parsers. Prices are COIN (× index → USD).
logger.py           FORWARD-ONLY poller: index + DVOL + whole-chain top-of-book, then a BOUNDED order-book
sink.py             enrichment of the long-tail strikes → append-only PIT rows (JSONL local; R2 mirror; DB table).
─────────────────── the scanner ──────────────────────────────────────────────────────────────────────────────
scanner.py          the "camper" framework: Camper protocol + Candidate/Leg + run_scan (deterministic, pure).
campers.py          three example campers (below).
fillability.py      the BINDING filter: re-prices a candidate at the executable touch (taker/maker) + fees + size.
fees.py             Deribit options fee model — maker==taker, 12.5%-of-premium cap.
```

### Forward logger (why forward-only, append-only, PIT)

Deribit publishes **no historical L2 order book** — you cannot reconstruct the spread/size you'd have faced after
the fact. So the substrate must *capture it live*: one poll stamps a `capture_ts` (the instant **we** observed
it — the only honest point-in-time), appends one row per instrument, and **never re-pulls** that instant. A
vendor revision is a new row at a later `capture_ts`, never an overwrite.

- **Cheap layer (whole chain):** one `get_book_summary_by_currency` call returns ~870 BTC instruments' top-of-book
  price + `mark_iv` + open interest. Covers the long tail for free.
- **Focused layer (sizes + greeks):** `get_order_book` per instrument adds the real best bid/ask **sizes**, L2,
  and greeks — but it is one call each, so the logger enriches only a **bounded** subset (default: the lowest-OI
  long-tail strikes — our sub-capacity lane), capped by `max_books_per_currency`.

Sinks: append-only local JSONL (default, $0), an R2 mirror (`upload_day_to_r2`, operator-run), and a
1:1 Postgres table (`knowledge/migrations/2026-06-29_deribit_option_quotes.sql`, **not yet applied**). A Modal
function (`remote/app.py::deribit_options_log`) is **registered but not scheduled** — Modal Free is already at its
5-cron cap, so the operator either calls it from the hourly `ingest` slot or adds a dedicated schedule off Free.

### Scanner (the "camper" pattern)

Each camper watches **one** inefficiency class on a logged `ChainSnapshot` and emits `Candidate`s valued at the
**mid** (the optimistic mirage number). `run_scan` then hands every candidate to the `FillabilityModel`, which is
**theory-agnostic**: it doesn't re-derive the camper's math, it adjusts the mid edge for the microstructure —

- **Taker** (cross now): `taker_edge = mid − Σ½-spread − fees`. Positive ⇒ a genuine **riskless lock**,
  executable this instant. Vanishingly rare; when seen it is almost always a stale quote gone in milliseconds.
- **Maker** (rest on the favorable touch): `maker_edge = mid + Σ½-spread − fees`, IF filled. A **single-leg**
  maker edge is plausibly capturable. A **multi-leg** maker edge needs *all* legs to fill as maker at once —
  that is **legging risk**, not a lock, so it is **not confirmed** by default (`allow_legging` to surface it).
- **Sizing:** `max_units = min over legs of (resting size at the touch / ratio)`. A leg with unknown size (never
  order-book-enriched) ⇒ `NO_SIZE` — we never claim a fill we can't size.

Verdicts: `RISKLESS_LOCK` ▸ `MAKER_ONLY` ▸ `RISK_PREMIUM` ▸ `MIRAGE` ▸ `NO_SIZE`.

## Which classes a NON-LATENCY maker can realistically capture

| Class (camper) | Nature | Legs | Honest verdict for a sub-capacity maker |
|---|---|---|---|
| **Vertical / butterfly** (`vertical_arb`) | pure-options static no-arb | 2 | The cleanest "if it fills, it's riskless." But off-ATM the violation is almost always **inside the spread** → taker-negative; capturing it needs **resting all legs as maker simultaneously** (legging risk). Realistic only on the **long-tail strikes** where you can sit on the touch unchallenged, in small size. |
| **Put-call parity** (`put_call_parity`) | static no-arb needing a **future hedge** | 2 options (+future) | The future leg is tight/liquid, so the **option spread is the wall**. Same story: taker-negative off-ATM, maker-only with legging risk. The cleaner the pair (ATM, two-sided, tight), the smaller the residual — the residual lives where the spread is widest. |
| **IV vs RV** (`vol_risk_premium`) | **risk premium, NOT an arb** | 1 | `RISK_PREMIUM`, never a lock. Selling rich IV is a real edge *family*, but it is **directional vol exposure you must delta-hedge continuously**, and the capacity sits in the **arbed ATM majors**. Route to a vol strategy, not the arb book. |
| **Latency / fleeting quotes** | gone in ms | — | **Out of scope by design.** A `RISKLESS_LOCK` here is flagged as "verify not stale" — crossing it is a race we lose to colocated bots. This substrate is the *non-latency* lane. |

**Bottom line for the camper bots:** the realistic lane is **long-tail, low-OI strikes**, **maker-only**, **small
size**, accepting **legging risk** consciously (`allow_legging=True`) and managing it leg-by-leg. The mid-price
"hundreds of violations" are mostly mirages; the substrate exists to tell the few from the many *honestly*.

## What one real poll found (BTC, 2026-06-29)

A live keyless poll parsed **874 instruments** (839 two-sided), DVOL ≈ 45.5, index ≈ \$60k. With the **120**
lowest-OI long-tail strikes order-book-enriched, the two static-arb campers raised **495 candidates** at mid —
and **0 were confirmed** at default settings:

| Camper | Candidates | `NO_SIZE` | `MAKER_ONLY` (legging risk) | True crossable locks (`taker>0`) | Median taker edge | Median maker edge |
|---|---|---|---|---|---|---|
| `put_call_parity` | 401 | 398 | 3 | **0** | **−\$254 / unit** | +\$647 / unit |
| `vertical_arb` | 94 | 76 | 18 | **0** | **−\$2,248 / unit** | +\$2,688 / unit |

Read this carefully — it *is* the thesis:

1. **Zero** candidates were crossable for a profit (`taker_edge > 0`) out of 495. There is no free lunch you can
   grab by lifting offers.
2. The big positive **maker** edges (\$500–\$7,500/unit) are the *optimistic* "I get filled on every leg at the
   favorable touch" number. The matching **taker** edges are hugely *negative* — meaning the entire apparent edge
   is the bid-ask spread itself. Computed off the mid it looks like hundreds of arbs; priced at the touch it's a
   mirage.
3. Most candidates are `NO_SIZE` simply because we enrich only a bounded subset — a deployment widens enrichment
   on the long-tail strikes it actually wants to camp.
4. Accepting legging risk (`allow_legging=True`) "confirms" **21** multi-leg maker structures — which is exactly
   what the default *correctly refuses*. Those 21 are the real (and only) lane: rest on the long-tail touch, in
   small size, managing each leg, knowing you may end up half-legged.

## Use

```bash
python -m cosmu.options smoke                 # parse-only dry poll (health check, no write)
python -m cosmu.options poll  --root DIR       # one forward poll → append-only JSONL hoard
python -m cosmu.options scan  --realized-vol 38  # poll + campers + fillability → CONFIRMED opportunities
```

## Honest limitations

- **Discounting** is approximated `DF≈1` (short crypto tenors, ~0 rates). Immaterial: fillability, not the carry
  model, is what kills these candidates. The parity forward uses Deribit's per-instrument `underlying_price`.
- **Maker fill is optimistic:** `maker_edge` assumes you get filled at the touch you posted. Fill *probability*
  and queue position are not modeled — `allow_legging` and `min_units` are the crude knobs; a real deployment
  needs live fill telemetry (which is exactly what the forward logger starts to accumulate).
- **Fees** are the verified 2026-06-29 schedule (`fees.FEES_VERIFIED_AT`); reconfirm before any live arming.
- This is a **research substrate**. It is not wired into the Gate or the feature registry, and never trades.
