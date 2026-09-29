# intent: the fee-optimizing VENUE ROUTER — "know where to send". For a base asset, find every venue that
# lists it, compare effective fees (catalog volume-tiers OR a fresh point-in-time venue_fees snapshot when the
# daily refresh has written one), and pick the CHEAPEST venue that is legal in the operator's jurisdiction.
# inputs: the venue catalog + trailing-30d volume + jurisdiction (+ optional PIT fee store); outputs: a ranked
# Route list / the single best Route / a full cross-venue comparison matrix. invariants: deterministic,
# legality-aware (restricted_jurisdictions — a French resident never routes to a venue restricted for FR),
# maker/taker explicit, base-asset normalization so BTCUSDT@binance and BTC@hyperliquid compare as one asset.
# PURE PLANNING — this never sends an order or touches the money path; it tells the live lane where the
# cheapest legal fill is. The daily refresh job (ingest/venue_fees_refresh.py) keeps the fee snapshots fresh.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cosmu.spine.venue import VenueCatalog, default_catalog

# Quote currencies + perp markers stripped to recover the BASE asset (the cross-venue comparison key).
_QUOTES = ("USDT", "USDC", "BUSD", "USD", "EUR")
_PERP_SUFFIXES = ("-USDT-SWAP", "-USD-SWAP", "-SWAP")
_PERP_PREFIXES = ("PF_",)
# Per-venue ticker aliases → the canonical base asset, so the same coin groups across venues (Kraken/Kraken
# Futures call Bitcoin XBT; Binance/OKX call it BTC). Without this a venue's BTC perp wouldn't compare.
_BASE_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}


def base_asset(symbol: str) -> str:
    """Normalize any venue symbol to its BASE asset so the same asset is comparable across venues:
    BTCUSDT→BTC · BTC-USDT→BTC · BTC/USD→BTC · PF_BTCUSD→BTC · BTC-USDT-SWAP→BTC · BTC→BTC."""
    s = symbol.upper().strip()
    for p in _PERP_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
    for suf in _PERP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = s.replace("-", "").replace("/", "").replace("_", "")
    for q in _QUOTES:
        if s.endswith(q) and len(s) > len(q):
            s = s[: -len(q)]
            break
    return _BASE_ALIASES.get(s, s)


@dataclass(frozen=True)
class Route:
    """One venue's quote for a base asset: the fill venue, its symbol there, the fee, and whether it's legal
    in our jurisdiction + exec-wired today."""

    base: str
    venue_id: str
    symbol: str
    fee_bps: float
    side: str          # "maker" | "taker"
    legal: bool        # not restricted in our jurisdiction
    live_wired: bool   # venue.live_enabled — an exec adapter exists (else it's a planning-only target)


def _effective_fee_bps(venue: Any, *, side: str, volume_30d: float, store: Any, symbol: str) -> float:
    """The fee (bps) for one venue × symbol: a FRESH point-in-time venue_fees snapshot if the daily refresh
    wrote one (so live tier changes/promos are honored), else the catalog's volume-tier fee. Never raises."""
    metric = "venue_fees_maker" if side == "maker" else "venue_fees_taker"
    if store is not None:
        try:
            from cosmu.data.altdata import read_pit_fee

            bps = read_pit_fee(store, venue.id, symbol, metric, datetime.now(tz=UTC), fallback_bps=None)
            if bps is not None:
                return float(bps)
        except Exception:  # noqa: BLE001 — no snapshot / unreachable store → fall back to the catalog tier
            pass
    maker, taker = venue.effective_fee(volume_30d)
    return float(maker if side == "maker" else taker)


def routes_for(
    catalog: VenueCatalog, base: str, *, side: str = "taker", volume_30d: float = 0.0,
    jurisdiction: str = "FR", store: Any = None,
) -> list[Route]:
    """Every venue that lists `base`, ranked cheapest-fee first (legality + live-wiring flagged, not filtered)."""
    rows: list[Route] = []
    for inst in catalog.instruments:
        if base_asset(inst.symbol) != base.upper():
            continue
        try:
            v = catalog.venue(inst.venue_id)
        except KeyError:
            continue
        rows.append(Route(
            base=base.upper(), venue_id=v.id, symbol=inst.symbol,
            fee_bps=_effective_fee_bps(v, side=side, volume_30d=volume_30d, store=store, symbol=inst.symbol),
            side=side,
            legal=jurisdiction.upper() not in {c.upper() for c in v.restricted_jurisdictions},
            live_wired=v.live_enabled,
        ))
    return sorted(rows, key=lambda r: (r.fee_bps, r.venue_id))


def best_venue(
    catalog: VenueCatalog, base: str, *, side: str = "taker", volume_30d: float = 0.0,
    jurisdiction: str = "FR", store: Any = None, require_legal: bool = True, require_live: bool = False,
) -> Route | None:
    """The cheapest venue to send `base` to. require_legal drops venues restricted in our jurisdiction (default
    on — a French resident never routes to an FR-restricted venue); require_live drops venues with no exec
    adapter yet (default off — the router also PLANS for venues we'll wire later). None when nothing qualifies."""
    rows = [
        r for r in routes_for(catalog, base, side=side, volume_30d=volume_30d, jurisdiction=jurisdiction, store=store)
        if (not require_legal or r.legal) and (not require_live or r.live_wired)
    ]
    return rows[0] if rows else None


def crypto_base_assets(catalog: VenueCatalog) -> list[str]:
    """All crypto base assets in the catalog (the routable universe), deduped + sorted."""
    bases = set()
    for inst in catalog.instruments:
        try:
            if catalog.venue(inst.venue_id).kind == "crypto":
                bases.add(base_asset(inst.symbol))
        except KeyError:
            continue
    return sorted(bases)


def fee_matrix(
    catalog: VenueCatalog | None = None, bases: list[str] | None = None, *, side: str = "taker",
    volume_30d: float = 0.0, jurisdiction: str = "FR", store: Any = None,
) -> dict[str, dict]:
    """base → {by_venue: {venue: fee_bps}, best: venue_id, best_fee_bps} — the cross-venue comparison the daily
    job logs and the UI shows. Defaults to every crypto base asset in the catalog."""
    catalog = catalog or default_catalog()
    bases = bases or crypto_base_assets(catalog)
    out: dict[str, dict] = {}
    for b in bases:
        rows = routes_for(catalog, b, side=side, volume_30d=volume_30d, jurisdiction=jurisdiction, store=store)
        legal = [r for r in rows if r.legal]
        out[b] = {
            "by_venue": {r.venue_id: round(r.fee_bps, 3) for r in rows},
            "best": legal[0].venue_id if legal else None,
            "best_fee_bps": round(legal[0].fee_bps, 3) if legal else None,
        }
    return out
