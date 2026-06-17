# intent: the SINGLE source of truth for the liquid perp universe the data layer + carry/xsec research screen —
# one deduped, ordered list so widening the universe (5 → 20–50) happens in exactly one place; inputs: a curated
# set of liquid Binance USDⓈ-M perp symbols; outputs: the canonical `PERP_UNIVERSE` tuple + a `dedupe_symbols`
# normalizer reused everywhere a symbol list is accepted; invariants: deduped (no symbol appears twice),
# order-preserving (deterministic backfill/verify order), upper-cased (the venue's spelling), and free of any
# survivorship claim — membership is "what we fetch data for", not "what was tradable at time t" (that stays the
# point-in-time UniverseCalendar's job). The carry verdict (docs/reports/phase0-carry-verdict.md) named a 5-asset
# universe as too thin for a real cross-sectional rank; this widens it to ~30 liquid perps so the NEXT gate re-run
# has the data depth — deeper history alone could not help (carry entries are rare per-symbol).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Global liquidity tiers for the venue-tagged universe (see venue_universe.py). Tier-0 = the ~20-30 deepest
# names, Tier-1 = the next ~100-150, Tier-2 = the deep tail. Imported here so the ONE liquidity-ranked source
# (the universe_pairs table + load_universe below) and the fetch/rank layer share the same tier definition.
TIER0_N = 30
TIER1_N = 150


def dedupe_symbols(symbols: Iterable[str], *, upper: bool = True) -> tuple[str, ...]:
    """Order-preserving dedupe + normalize for any accepted symbol list. Upper-cases (the venue spelling),
    strips whitespace, drops blanks, and keeps the FIRST occurrence of each — so a caller that concatenates a
    wide universe with an operator's extra symbols can never double-fetch a duplicate (the same idempotency
    discipline the bar/alt stores enforce on `ts`, applied one level up at the symbol list)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        sym = raw.strip()
        if upper:
            sym = sym.upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return tuple(out)


# The widened liquid perp universe (~30 Binance USDⓈ-M symbols, by sustained perp volume / open interest).
# Deduped at definition time so this constant is the canonical, already-normalized list. Widening from the prior
# 5-asset set (BTC/ETH/BNB/SOL/XRP) is the carry-verdict next action: 5 assets is too few for a real
# cross-sectional rank; 20–50 liquid perps is where xsec-neutral momentum has documented headroom.
PERP_UNIVERSE: tuple[str, ...] = dedupe_symbols(
    (
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "TRXUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "UNIUSDT",
        "ATOMUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT",
        "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "AAVEUSDT",
        "ETCUSDT", "XLMUSDT", "ICPUSDT", "RUNEUSDT", "GALAUSDT",
    )
)

# The original 5-asset screen, kept as a NAMED slice so a caller that wants the cheap/legacy set is explicit
# about it (not a magic literal). Carry/xsec now default to the WIDE universe; this is for narrow smoke runs.
CORE_PERP_UNIVERSE: tuple[str, ...] = PERP_UNIVERSE[:5]


def perp_universe(n: int | None = None) -> list[str]:
    """The canonical perp universe as a fresh list, optionally truncated to the first `n` (deterministic — the
    list is volume-ordered, so `perp_universe(10)` is the 10 deepest). `n=None` → the full universe."""
    syms = list(PERP_UNIVERSE)
    return syms if n is None else syms[: max(0, n)]


# ----------------------------------------------------------------------------------------------------------------
# The DB-backed liquidity-ranked source — reads the venue-tagged `universe_pairs` table (populated by
# data/universe_build.py from the live venues). This is the ONE source the lab tests wide over; the static
# PERP_UNIVERSE above stays the deterministic, network-free FALLBACK for any caller without a populated store.
# ----------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class UniverseRow:
    """One persisted universe pair as the lab/research layer reads it (a thin view over a universe_pairs row)."""

    venue: str
    symbol: str
    base: str
    quote: str
    asset_class: str
    instrument_type: str
    liquidity_usd_24h: float
    tier: int | None
    rank: int | None
    active: bool

    @property
    def id(self) -> str:
        return f"{self.venue}:{self.symbol}"


def load_universe(
    store: Any,
    *,
    asset_class: str | None = None,
    venue: str | None = None,
    instrument_type: str | None = None,
    tier: int | None = None,
    active_only: bool = True,
    limit: int | None = None,
) -> list[UniverseRow]:
    """Liquidity-ranked pairs from the universe_pairs table (deepest first). Filters compose (asset_class / venue /
    instrument_type / tier). `active_only` excludes delisted rows (the live tradable set); pass False for the
    point-in-time superset. Returns [] when the table is empty/absent — the caller falls back to PERP_UNIVERSE."""
    where = ["1=1"]
    params: list[Any] = []
    if active_only:
        where.append("active = 1")
    if asset_class is not None:
        where.append("asset_class = ?")
        params.append(asset_class)
    if venue is not None:
        where.append("venue = ?")
        params.append(venue)
    if instrument_type is not None:
        where.append("instrument_type = ?")
        params.append(instrument_type)
    if tier is not None:
        where.append("tier = ?")
        params.append(tier)
    sql = (
        "SELECT venue, symbol, base, quote, asset_class, instrument_type, liquidity_usd_24h, tier, rank, active "
        f"FROM universe_pairs WHERE {' AND '.join(where)} "
        "ORDER BY liquidity_usd_24h DESC, venue, symbol"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    try:
        rows = store.rows(sql, tuple(params))
    except Exception:  # noqa: BLE001 — table not yet created (fresh store) → empty, caller uses the fallback
        return []
    return [
        UniverseRow(
            venue=r["venue"], symbol=r["symbol"], base=r["base"] or "", quote=r["quote"] or "",
            asset_class=r["asset_class"], instrument_type=r["instrument_type"],
            liquidity_usd_24h=float(r["liquidity_usd_24h"] or 0.0),
            tier=r["tier"], rank=r["rank"], active=bool(r["active"]),
        )
        for r in rows
    ]


def universe_symbols(store: Any, *, fallback: tuple[str, ...] = PERP_UNIVERSE, **filters: Any) -> list[str]:
    """The liquidity-ranked SYMBOLS from the universe_pairs table (deepest first), or the static PERP_UNIVERSE
    fallback when the table is empty. Accepts the same filters as load_universe (asset_class/venue/tier/limit)."""
    rows = load_universe(store, **filters)
    return [r.symbol for r in rows] if rows else list(fallback)
