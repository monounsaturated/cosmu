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
