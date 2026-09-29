# intent: the UNIVERSAL PRICE LAYER reference resolver — de-collapse the venue axis by computing a pair's price
# ONCE (a single canonical REFERENCE series) and overlaying the per-venue fee/depth, INSTEAD of fetching a
# separate (often identical) series per venue. The #1 risk this module guards against is FALSE-UNIFY: silently
# reusing the reference for a venue whose prices actually DIVERGE is a LEAKAGE bug upstream of the Gate (a
# mispriced backtest = a fake edge). So the decision is conservative and INSPECTABLE:
#   - `pair_for(symbol, venue)`  -> the canonical pair (BTC/USDT), normalizing the venue's spelling (Kraken XBTUSD,
#     Binance BTCUSDT) AND the quote currency (USDT/USD/USDC) DELIBERATELY + visibly (one quote-bucket constant).
#   - `reference_provider(pair)` -> the keyless provider that serves the canonical reference series (crypto today
#     -> the existing Binance spot provider; no new vendor, no keys).
#   - `cross_venue_alignment(reference_bars, venue_bars, window)` -> REUSES the correlation math in
#     research/correlation_scan.py (Pearson corr of bar RETURNS) + the median absolute relative close-spread, on
#     the bars' COMMON timestamps (never positional alignment — a 1-bar offset would read a spurious ~0).
#   - `decision(...)` -> UNIFY iff corr >= UNIFY_MIN_CORR AND median_spread_bps <= UNIFY_MAX_SPREAD_BPS AND
#     n_overlap >= UNIFY_MIN_OVERLAP, else FALLBACK. BIAS TO FALLBACK: any missing data, any ambiguity, any
#     threshold miss -> FALLBACK (false-unify is the dangerous error; handling divergence is cheap).
# The decision + its two stats are PERSISTED per (pair, venue) to `price_alignment` (idempotent upsert) so the
# verdict is inspectable and NOT recomputed every screen run. invariants: PIT/leakage-safe (returns are computed
# from the bars as given; the resolver NEVER fabricates a bar); deterministic for fixed bars; offline-safe (a
# persist failure is best-effort, never raises into the screen); ZERO LLM.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cosmu.data.market import Bar

# -----------------------------------------------------------------------------------------------------------------
# UNIFY thresholds — the false-unify guard. Deliberately STRICT (bias to FALLBACK).
# -----------------------------------------------------------------------------------------------------------------
# A venue's series may be REUSED as the reference (UNIFY) only when it is, for trading purposes, the SAME price:
#   - returns track the reference essentially 1:1 (corr >= 0.99): a venue whose returns diverge even slightly is a
#     different price process (different liquidity/listing/quote) and MUST keep its own bars.
#   - the close levels sit within a tight band (median |relative spread| <= 25 bps): two venues can be highly
#     correlated yet sit at a persistent premium/discount (e.g. a Korea-premium-style basis, or a USDT-vs-USD peg
#     gap) — a level offset that big would mis-mark every entry/exit, so it FALLS BACK.
#   - enough shared bars to TRUST the two stats (n >= 60): a handful of overlapping bars can read corr~1 by luck.
UNIFY_MIN_CORR = 0.99
UNIFY_MAX_SPREAD_BPS = 25.0
UNIFY_MIN_OVERLAP = 60

# Quote-currency NORMALIZATION buckets. We treat the USD-dollar stablecoins/fiat as ONE canonical quote 'USDT'
# for the PAIR identity (so Kraken's XBT/USD and Binance's BTC/USDT resolve to the same canonical pair and CAN be
# compared) — but this normalization is DELIBERATE and VISIBLE here, and the alignment check is exactly what
# catches a quote whose price actually diverges (e.g. a depegged stablecoin): such a pair fails corr/spread and
# FALLS BACK to its own bars. A quote NOT in any bucket keeps its own spelling (no silent collapse).
_QUOTE_BUCKETS: dict[str, tuple[str, ...]] = {
    "USDT": ("USDT", "USD", "USDC", "ZUSD", "USDD", "BUSD", "TUSD", "DAI"),
}
# Base-asset spelling normalization across venues (Kraken's XBT == BTC, XDG == DOGE). Kept tiny + explicit.
_BASE_ALIASES: dict[str, str] = {"XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE", "XETH": "ETH", "XXRP": "XRP"}

# Known quote symbols for splitting a BARE concatenated symbol (BTCUSDT -> BTC,USDT) when the universe row
# carries no explicit base/quote. Longest-first so 'USDT'/'USDC' win over 'USD'. DELIBERATELY restricted to the
# unambiguous common quotes: the obscure stablecoins (TUSD/BUSD/USDD) are NOT suffix-split here because a base
# like 'XBT' makes 'XBTUSD' end in 'TUSD' and mis-split to base 'XB' — a real footgun. Those obscure quotes still
# normalize correctly via the quote BUCKET when an explicit `quote` is supplied (the universe-row path the screen
# actually uses); the bare fallback stays conservative. USDT before USDC before USD (no shared suffix among them).
_KNOWN_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "DAI")


def _canon_base(base: str) -> str:
    b = (base or "").strip().upper()
    return _BASE_ALIASES.get(b, b)


def canonical_quote(quote: str) -> str:
    """Normalize a quote currency to its canonical bucket (USD-dollar stables/fiat -> 'USDT'), DELIBERATELY +
    VISIBLY — this is the one place USDT/USD/USDC collapse, and the alignment check is what catches a quote that
    actually diverges. A quote in no bucket keeps its own (upper-cased) spelling."""
    q = (quote or "").strip().upper()
    for canon, members in _QUOTE_BUCKETS.items():
        if q in members:
            return canon
    return q


def _split_symbol(symbol: str) -> tuple[str, str]:
    """Best-effort (base, quote) from a bare venue symbol (BTCUSDT, BTC/USD, XBTUSD, BTC-USD). Used only when the
    universe row has no explicit base/quote columns. Returns (symbol, '') if no known quote suffix is found —
    the caller then keeps the whole thing as the base (no fabricated quote)."""
    s = (symbol or "").strip().upper()
    for sep in ("/", "-", "_"):
        if sep in s:
            base, quote = s.split(sep, 1)
            return base, quote
    for q in _KNOWN_QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)], q
    return s, ""


@dataclass(frozen=True)
class CanonicalPair:
    """A venue-agnostic pair identity. `id` is the canonical 'BASE/QUOTE' string (the cache key + the
    price_alignment key); base/quote are already normalized (XBT->BTC, USD->USDT)."""

    base: str
    quote: str

    @property
    def id(self) -> str:
        return f"{self.base}/{self.quote}"


def pair_for(  # noqa: ARG001 — `venue` kept for API symmetry / future venue-specific spelling rules
    symbol: str, venue: str, *, base: str | None = None, quote: str | None = None
) -> CanonicalPair:
    """The CANONICAL pair a (symbol, venue) trades — normalizing the base spelling (Kraken XBT -> BTC) AND the
    quote currency bucket (USD/USDC -> USDT) DELIBERATELY so kraken XBTUSD and binance BTCUSDT BOTH resolve to
    BTC/USDT and CAN be unified-or-not by the alignment check. `base`/`quote` (from a universe_pairs row) are
    preferred over parsing the bare symbol; we still normalize them. `venue` is accepted for API symmetry / future
    venue-specific spelling rules — it does not change the canonical identity today."""
    if base or quote:
        b, q = base or "", quote or ""
    else:
        b, q = _split_symbol(symbol)
    return CanonicalPair(base=_canon_base(b), quote=canonical_quote(q))


def reference_provider(pair: CanonicalPair) -> Any:
    """The keyless provider that serves `pair`'s canonical REFERENCE series. Crypto today -> the existing Binance
    spot provider (the deepest keyless book = the natural reference). No new vendor, no keys. (Equity/prediction
    pairs are out of Stage-0 scope and would route to their own reference provider when added.)"""
    from cosmu.data.market import UniversalOHLCVProvider

    return UniversalOHLCVProvider()


# -----------------------------------------------------------------------------------------------------------------
# Cross-venue alignment — REUSES the return-correlation math from research/correlation_scan.py.
# -----------------------------------------------------------------------------------------------------------------
def _common_returns(reference_bars: list[Bar], venue_bars: list[Bar]) -> tuple[list[float], list[float], list[float]]:
    """Inner-join the two bar series on their COMMON timestamps (NEVER positional alignment — a 1-bar offset would
    read a spurious ~0 corr / 0 spread and dangerously UNIFY) and return (ref_returns, venue_returns, abs_rel_close
    _spreads) over the shared bars. Returns are bar-to-bar close returns on the joined index; spread is the
    absolute relative close difference |c_v/c_r - 1| at each shared bar. Empty lists when fewer than 2 shared bars."""
    ref_by_ts = {b.ts: float(b.close) for b in reference_bars if b.close is not None}
    ven_by_ts = {b.ts: float(b.close) for b in venue_bars if b.close is not None}
    shared = sorted(ts for ts in ref_by_ts.keys() & ven_by_ts.keys() if ref_by_ts[ts] > 0 and ven_by_ts[ts] > 0)
    spreads = [abs(ven_by_ts[ts] / ref_by_ts[ts] - 1.0) for ts in shared]
    ref_ret: list[float] = []
    ven_ret: list[float] = []
    for i in range(1, len(shared)):
        t0, t1 = shared[i - 1], shared[i]
        r0, r1 = ref_by_ts[t0], ref_by_ts[t1]
        v0, v1 = ven_by_ts[t0], ven_by_ts[t1]
        if r0 > 0 and v0 > 0:
            ref_ret.append(r1 / r0 - 1.0)
            ven_ret.append(v1 / v0 - 1.0)
    return ref_ret, ven_ret, spreads


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation of two equal-length return series. 0.0 when degenerate (n<2 or zero variance) —
    fail-closed toward FALLBACK (a degenerate corr must NEVER read as 1.0 and unify)."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx**0.5 * vy**0.5)


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


@dataclass(frozen=True)
class AlignmentStats:
    """The two inspectable stats + the overlap count behind a UNIFY/FALLBACK verdict."""

    corr: float              # Pearson corr of bar RETURNS on the common timestamps
    median_spread_bps: float # median absolute relative close-spread (bps) on the common timestamps
    n_overlap: int           # number of shared bars


def cross_venue_alignment(reference_bars: list[Bar], venue_bars: list[Bar]) -> AlignmentStats:
    """How closely the venue's series tracks the reference, on their COMMON bars: Pearson corr of bar RETURNS
    (the same return-correlation math research/correlation_scan uses) + the median absolute relative close-spread
    (in bps) + the shared-bar count. Deterministic; fail-closed (empty/degenerate -> corr 0, huge spread)."""
    ref_ret, ven_ret, spreads = _common_returns(reference_bars, venue_bars)
    corr = _pearson(ref_ret, ven_ret)
    median_spread_bps = _median(spreads) * 10_000.0
    return AlignmentStats(corr=round(corr, 6), median_spread_bps=round(median_spread_bps, 4), n_overlap=len(spreads))


@dataclass(frozen=True)
class AlignmentDecision:
    """A persisted UNIFY/FALLBACK verdict for one (pair, venue), with the stats it was made from."""

    pair: str
    venue: str
    verdict: str  # "UNIFY" | "FALLBACK"
    stats: AlignmentStats

    @property
    def unify(self) -> bool:
        return self.verdict == "UNIFY"


def decide(stats: AlignmentStats) -> str:
    """UNIFY iff corr >= UNIFY_MIN_CORR AND median_spread_bps <= UNIFY_MAX_SPREAD_BPS AND n_overlap >=
    UNIFY_MIN_OVERLAP, else FALLBACK. BIAS TO FALLBACK — any threshold miss (incl. too-few overlap bars to trust
    the stats) is FALLBACK, because a false UNIFY is a leakage bug and divergence is cheap to handle with own
    bars."""
    if (
        stats.n_overlap >= UNIFY_MIN_OVERLAP
        and stats.corr >= UNIFY_MIN_CORR
        and stats.median_spread_bps <= UNIFY_MAX_SPREAD_BPS
    ):
        return "UNIFY"
    return "FALLBACK"


def decision(
    pair: CanonicalPair,
    venue: str,
    reference_bars: list[Bar],
    venue_bars: list[Bar],
) -> AlignmentDecision:
    """The full (pair, venue) verdict from the two series: compute the alignment stats then `decide`. Pure +
    deterministic (no DB) — persistence is a separate, opt-in step (`persist_decision`)."""
    stats = cross_venue_alignment(reference_bars, venue_bars)
    return AlignmentDecision(pair=pair.id, venue=venue, verdict=decide(stats), stats=stats)


# -----------------------------------------------------------------------------------------------------------------
# Persistence — idempotent upsert to `price_alignment` so the verdict is inspectable + NOT recomputed per run.
# -----------------------------------------------------------------------------------------------------------------
_ALIGNMENT_COLS = ("id", "pair", "venue", "verdict", "corr", "median_spread_bps", "n_overlap", "decided_at")


def persist_decision(store: Any, decision_: AlignmentDecision, *, now: str | None = None) -> None:
    """BEST-EFFORT idempotent UPSERT of one verdict to `price_alignment` (keyed on the pair:venue id). Never raises
    into the screen — a DB hiccup (or an unmigrated table) must not crash a run (the decision is also returned
    in-memory). Re-deciding the same (pair, venue) REFRESHES the verdict + BOTH stats so the row always reflects
    the latest inspected alignment. ON CONFLICT DO UPDATE works byte-identically on SQLite and Postgres here."""
    from cosmu.knowledge.store import utcnow

    stamp = now or utcnow()
    values = (
        f"{decision_.pair}:{decision_.venue}",
        decision_.pair,
        decision_.venue,
        decision_.verdict,
        float(decision_.stats.corr),
        float(decision_.stats.median_spread_bps),
        int(decision_.stats.n_overlap),
        stamp,
    )
    update = ", ".join(f"{c} = excluded.{c}" for c in _ALIGNMENT_COLS if c != "id")
    sql = (
        f"INSERT INTO price_alignment ({', '.join(_ALIGNMENT_COLS)}) "
        f"VALUES ({', '.join('?' for _ in _ALIGNMENT_COLS)}) "
        f"ON CONFLICT (id) DO UPDATE SET {update}"
    )
    try:
        with store.batch() as writer:
            writer.execute(sql, values)
    except Exception:  # noqa: BLE001 — persistence is best-effort + offline-safe; never break the screen
        pass


# -----------------------------------------------------------------------------------------------------------------
# PER-CELL DATA PROVENANCE — make a backtest cell state EXACTLY what data it ran on (operator: "a backtest result
# must never be a black box"). This is a DISPLAY/AUDIT record only: it READS the bars + the alignment decision the
# backtest already assembled and is NEVER a gate input, so the locked scorer/FDR/cohort math is byte-unchanged.
# -----------------------------------------------------------------------------------------------------------------
# Divergence FLAG threshold: a cell whose price came from a FALLBACK reference source (a source ≠ the live venue's
# own book) is flagged when the source's returns track the live venue too loosely OR the close-levels sit too far
# apart to mark the cell honestly. Reuses the SAME corr/spread the alignment check computes (so the flag agrees with
# the UNIFY/FALLBACK verdict's spirit) — a deliberately LOOSE display threshold (the strict gate is UNIFY_*): we
# flag a cell for the operator to inspect, we never silently move a number. corr below / spread above → flag.
PROVENANCE_FLAG_MIN_CORR = 0.95
PROVENANCE_FLAG_MAX_SPREAD_BPS = 50.0


@dataclass(frozen=True)
class CellProvenance:
    """EXACTLY what data ONE backtest cell (symbol × venue) ran on — the anti-black-box record. Additive +
    display-only: it READS the assembled bars + the alignment decision and is NO gate input, so attaching it
    cannot move a backtest number, the Gate, or the money path.

    Fields:
      - symbol / venue        : the canonical pair + the LIVE venue this cell's fee/depth prices against.
      - bar_source            : WHERE the scored bars came from (the provider/venue book, e.g. 'binance-reference',
                                'kraken-keyless', 'bybit', 'hyperliquid', 'polymarket-odds') — NOT necessarily the
                                live venue (a FALLBACK cell is scored on the reference book, surfaced plainly here).
      - bar_interval          : the bar size the cell was scored at ('1h', '1d', …).
      - first_bar_ts/last_bar_ts: ISO range of the actual bars scored (None when the cell has no bars).
      - n_bars                : how many bars were scored.
      - holdout_split_index   : the index into the bar series where validation ends and the embargoed holdout
                                begins (the last ~20% is the holdout; None when the cell is too short to hold out).
      - fee_bps/slippage_bps/impact_bps : the TODAY's-schedule cost overlay charged on every fill (fees-always-today
                                rule) — the exact per-venue numbers the backtest used, recorded not re-typed.
      - reuses_reference      : True when bar_source is a SHARED reference book the cell did NOT natively trade on
                                (a price-source ≠ live-venue situation worth surfacing); False = native venue bars.
      - source_is_fallback    : True when the price SOURCE differs from the live VENUE (a FALLBACK reference was
                                used) — the headline 'backtested on <source> → live venue <venue>' divergence case.
      - align_corr/align_spread_bps/align_overlap : the divergence metric of the source-vs-live-venue price
                                (Pearson corr of returns + median |spread| in bps + shared-bar count), straight
                                from the alignment decision. None for a native-venue (reference) cell with no
                                cross-venue check to make.
    """

    symbol: str
    venue: str
    bar_source: str
    bar_interval: str
    n_bars: int
    fee_bps: float
    slippage_bps: float
    impact_bps: float
    reuses_reference: bool
    source_is_fallback: bool
    first_bar_ts: str | None = None
    last_bar_ts: str | None = None
    holdout_split_index: int | None = None
    align_corr: float | None = None
    align_spread_bps: float | None = None
    align_overlap: int | None = None

    @property
    def divergence_flagged(self) -> bool:
        """True when the price SOURCE differs from the live VENUE (a fallback was used) AND the source tracks the
        venue too loosely to be silently trusted (corr below / spread above the LOOSE display thresholds, or the
        overlap was too thin to even estimate). A native-venue cell (source == venue, no fallback) is NEVER flagged
        — its own book is the truth. This is an INSPECT-ME flag for the operator, never a gate action."""
        if not self.source_is_fallback:
            return False
        if self.align_corr is None or self.align_spread_bps is None:
            return True  # a fallback with no measurable alignment is the most suspect case → flag
        return self.align_corr < PROVENANCE_FLAG_MIN_CORR or self.align_spread_bps > PROVENANCE_FLAG_MAX_SPREAD_BPS

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable view (the shape persisted on an event payload / served on an API field)."""
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "bar_source": self.bar_source,
            "bar_interval": self.bar_interval,
            "n_bars": self.n_bars,
            "first_bar_ts": self.first_bar_ts,
            "last_bar_ts": self.last_bar_ts,
            "holdout_split_index": self.holdout_split_index,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "impact_bps": self.impact_bps,
            "reuses_reference": self.reuses_reference,
            "source_is_fallback": self.source_is_fallback,
            "align_corr": self.align_corr,
            "align_spread_bps": self.align_spread_bps,
            "align_overlap": self.align_overlap,
            "divergence_flagged": self.divergence_flagged,
        }

    def log_line(self) -> str:
        """A one-line human-readable provenance summary for the backtest log — states EXACTLY what the cell ran on,
        plainly names the price source vs the live venue, and FLAGS a divergent fallback so a backtest is never a
        black box. E.g.:
          'PROVENANCE BTC/USDT@kraken: backtested on kraken-keyless price → live venue kraken | 1h | 1200 bars
           2024-01-01T00:00:00→2024-02-19T00:00:00 | holdout@960 | fees 40.0bps slip 7.0/55.0bps | aligned'
          '… backtested on binance-reference price → live venue bybit | … | FALLBACK source (corr 0.91 spread
           62.0bps over 800 bars) ⚠ DIVERGENT'"""
        rng = (
            f"{self.first_bar_ts}→{self.last_bar_ts}"
            if self.first_bar_ts and self.last_bar_ts
            else "no-bars"
        )
        holdout = f"holdout@{self.holdout_split_index}" if self.holdout_split_index is not None else "no-holdout"
        fees = f"fees {self.fee_bps}bps slip {self.slippage_bps}/{self.impact_bps}bps"
        if self.source_is_fallback:
            if self.align_corr is not None and self.align_spread_bps is not None:
                align = (
                    f"FALLBACK source (corr {self.align_corr} spread {self.align_spread_bps}bps "
                    f"over {self.align_overlap} bars)"
                )
            else:
                align = "FALLBACK source (alignment unmeasured)"
            if self.divergence_flagged:
                align += " ⚠ DIVERGENT"
        else:
            align = "aligned (native venue source)"
        return (
            f"PROVENANCE {self.symbol}@{self.venue}: backtested on {self.bar_source} price "
            f"→ live venue {self.venue} | {self.bar_interval} | {self.n_bars} bars {rng} | "
            f"{holdout} | {fees} | {align}"
        )


# A bar series' validation/holdout split mirrors _purged_embargoed_split (last ~20% held out): split index =
# max(40, int(0.8 * n)). Recorded for provenance ONLY (the real split lives in data/backtest); None when the series
# is too short to leave a holdout. This is a read, never a re-implementation of the gate's split logic.
def _provenance_holdout_split(n_bars: int) -> int | None:
    if n_bars < 80:
        return None
    return max(40, int(n_bars * 0.8))


def cell_provenance(
    *,
    symbol: str,
    venue: str,
    bar_source: str,
    bar_interval: str,
    bars: list[Bar],
    fee_bps: float,
    slippage_bps: float,
    impact_bps: float,
    reuses_reference: bool,
    decision_: AlignmentDecision | None,
    is_reference_venue: bool,
) -> CellProvenance:
    """Assemble ONE cell's provenance record from the bars it ran on + the cost overlay + the alignment decision.

    `bar_source` is the human name of WHERE the scored bars came from (the provider/venue book). `reuses_reference`
    is the PriceCell leakage-guard flag: True when the cell was scored on a SHARED reference series rather than its
    own native venue book. `is_reference_venue` is True iff this cell's live venue IS the reference venue itself (so
    reusing the reference is just scoring on its own book — NOT a divergence).

    `source_is_fallback` is the headline divergence case — the price SOURCE differs from the live VENUE: True iff the
    cell reuses the reference AND its live venue is NOT the reference venue (a non-reference venue scored on the
    shared reference book; covers BOTH the UNIFY path, with a measured alignment, AND the per-venue-mode 'native bars
    missing → fall back to reference' path, where no alignment was measured). The corr/spread come straight from the
    alignment decision (None for a native cell, or a fallback whose alignment wasn't measured). Pure + display-only."""
    n = len(bars)
    first_ts = bars[0].ts.isoformat() if n else None
    last_ts = bars[-1].ts.isoformat() if n else None
    stats = decision_.stats if decision_ is not None else None
    return CellProvenance(
        symbol=symbol,
        venue=venue,
        bar_source=bar_source,
        bar_interval=bar_interval,
        n_bars=n,
        fee_bps=round(float(fee_bps), 4),
        slippage_bps=round(float(slippage_bps), 4),
        impact_bps=round(float(impact_bps), 4),
        reuses_reference=reuses_reference,
        # A cell is a SOURCE≠VENUE fallback iff it reuses a shared reference book AND its live venue is NOT the
        # reference venue. The reference venue's OWN cell reuses the reference too, but that is its own book — not a
        # fallback. (decision_ may be None on the per-venue 'native missing → reference' fallback; still a fallback.)
        source_is_fallback=bool(reuses_reference and not is_reference_venue),
        first_bar_ts=first_ts,
        last_bar_ts=last_ts,
        holdout_split_index=_provenance_holdout_split(n),
        align_corr=(stats.corr if stats is not None else None),
        align_spread_bps=(stats.median_spread_bps if stats is not None else None),
        align_overlap=(stats.n_overlap if stats is not None else None),
    )


def load_decision(store: Any, pair: CanonicalPair, venue: str) -> AlignmentDecision | None:
    """Read a previously-persisted verdict for (pair, venue), or None when absent/unreadable (the caller then
    decides fresh). So the verdict is NOT recomputed every run — the screen reads the inspected decision."""
    try:
        r = store.row(
            "SELECT pair, venue, verdict, corr, median_spread_bps, n_overlap FROM price_alignment WHERE id = ?",
            (f"{pair.id}:{venue}",),
        )
    except Exception:  # noqa: BLE001 — table absent / DB hiccup → decide fresh
        return None
    if not r:
        return None
    return AlignmentDecision(
        pair=r["pair"],
        venue=r["venue"],
        verdict=r["verdict"],
        stats=AlignmentStats(
            corr=float(r["corr"] or 0.0),
            median_spread_bps=float(r["median_spread_bps"] or 0.0),
            n_overlap=int(r["n_overlap"] or 0),
        ),
    )
