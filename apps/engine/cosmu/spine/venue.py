# intent: describe tradable instruments at actual venues; inputs: static/env catalog; outputs: VenueCatalog;
# invariants: fees are REAL per-venue and volume-tiered (no fee-free paper), jurisdiction legality is explicit
# (live availability is a venue+country fact, not a global toggle), and venue names are mode-free.

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class VenueFeeTier(BaseModel):
    """A 30-day-volume fee tier. The effective schedule is the highest tier whose threshold the
    account's trailing 30d volume meets. Volume → cheaper fills is a real profit lever."""

    min_volume_30d_usd: Decimal
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal


class Venue(BaseModel):
    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    adapter: str
    # Base (retail / lowest-volume) schedule. fee_tiers, when present, override this by volume.
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    min_notional: Decimal
    lot_size: Decimal
    enabled: bool = True
    # --- per-venue fee realism + jurisdiction (the binding live-cost facts) ---
    fee_tiers: list[VenueFeeTier] = Field(default_factory=list)
    # Whether real-money execution is wired here at all. Data/paper/research venues stay False; they
    # still feed the lab, they just can't move money. (Distinct from the global live interlock.)
    live_enabled: bool = False
    # ISO-3166 alpha-2 country codes where live trading is NOT legally/operationally available to us.
    # Empty = available everywhere we operate. This is why jurisdiction PICKS the live crypto venue.
    restricted_jurisdictions: list[str] = Field(default_factory=list)

    def effective_fee(self, volume_30d_usd: Decimal | float = Decimal("0")) -> tuple[Decimal, Decimal]:
        """(maker_bps, taker_bps) for a trailing-30d USD volume — the richest tier met, else the base."""
        vol = Decimal(str(volume_30d_usd))
        eligible = [t for t in self.fee_tiers if vol >= t.min_volume_30d_usd]
        if not eligible:
            return (self.maker_fee_bps, self.taker_fee_bps)
        best = max(eligible, key=lambda t: t.min_volume_30d_usd)
        return (best.maker_fee_bps, best.taker_fee_bps)

    def live_legal_in(self, country_code: str) -> bool:
        """Can we run LIVE here from this jurisdiction? Needs live wiring AND no legal restriction."""
        return self.live_enabled and country_code.upper() not in {c.upper() for c in self.restricted_jurisdictions}


class Instrument(BaseModel):
    id: str
    venue_id: str
    symbol: str
    asset_class: Literal["crypto", "equity", "prediction"]
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("0.0001")
    min_notional: Decimal = Decimal("10")
    active: bool = True


class VenueCatalog(BaseModel):
    venues: list[Venue] = Field(default_factory=list)
    instruments: list[Instrument] = Field(default_factory=list)

    def venue(self, venue_id: str) -> Venue:
        for venue in self.venues:
            if venue.id == venue_id:
                return venue
        raise KeyError(f"unknown venue: {venue_id}")

    def instrument(self, symbol: str, venue_id: str = "binance") -> Instrument:
        for instrument in self.instruments:
            if instrument.symbol == symbol and instrument.venue_id == venue_id:
                return instrument
        raise KeyError(f"unknown instrument: {symbol}@{venue_id}")

    def venue_for(self, venues: list[str]) -> Venue:
        """The venue a spec should be PRICED against — the single source of fee truth for the screen, the
        gate, and forward-test. Returns the first declared universe venue that exists in the catalog, else
        Binance (the default crypto-spot venue). Threading fees through here is why an IBKR-equity spec is
        screened at IBKR fees, not Binance's — no hardcoded per-call-site venue."""
        for vid in venues or []:
            try:
                return self.venue(vid)
            except KeyError:
                continue
        return self.venue("binance")

    def live_legal_venues(self, country_code: str) -> list[Venue]:
        """Venues where live trading is legal/available from a given jurisdiction — the honest set the
        launch flow may offer for real capital."""
        return [v for v in self.venues if v.enabled and v.live_legal_in(country_code)]


# Curated operating jurisdictions the UI offers as a pick-list (ISO-3166 alpha-2 → label), ordered for a
# crypto/tech digital-nomad: low-friction, crypto-legal hubs first, the US (Binance-restricted) last. Live
# legality per venue stays the catalog's `restricted_jurisdictions` — this is only the standardized choices,
# so picking a country is ONE setting, not free text. Extend by adding a code here (+ a venue restriction if
# the venue isn't legal there). FR is the default until the operator picks.
SUPPORTED_JURISDICTIONS: dict[str, str] = {
    "FR": "France",
    "NL": "Netherlands",
    "GB": "United Kingdom",
    "DE": "Germany",
    "PT": "Portugal",
    "CH": "Switzerland",
    "AE": "United Arab Emirates",
    "SG": "Singapore",
    "US": "United States",
}


def default_catalog() -> VenueCatalog:
    return VenueCatalog(
        venues=[
            # Crypto — Binance: deepest liquidity + best funding/OI → our DATA/RESEARCH venue. Live is legal in
            # much of the world but NOT the US; jurisdiction decides whether it can also be a live venue.
            Venue(
                id="binance", name="Binance", kind="crypto", adapter="nautilus.binance",
                maker_fee_bps=Decimal("10"), taker_fee_bps=Decimal("10"),
                min_notional=Decimal("10"), lot_size=Decimal("0.0001"),
                live_enabled=True, restricted_jurisdictions=["US"],
                fee_tiers=[
                    VenueFeeTier(min_volume_30d_usd=Decimal("0"), maker_fee_bps=Decimal("10"), taker_fee_bps=Decimal("10")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("1000000"), maker_fee_bps=Decimal("9"), taker_fee_bps=Decimal("10")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("5000000"), maker_fee_bps=Decimal("8"), taker_fee_bps=Decimal("9")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("20000000"), maker_fee_bps=Decimal("6"), taker_fee_bps=Decimal("7")),
                ],
            ),
            # Crypto — Kraken: US-legal crypto live venue. Fees are WORSE than Binance (the real finding):
            # ~16/26 bps retail, only reaching Binance-like levels at high volume.
            Venue(
                id="kraken", name="Kraken", kind="crypto", adapter="nautilus.kraken",
                maker_fee_bps=Decimal("16"), taker_fee_bps=Decimal("26"),
                min_notional=Decimal("10"), lot_size=Decimal("0.0001"),
                live_enabled=True, restricted_jurisdictions=[],
                fee_tiers=[
                    VenueFeeTier(min_volume_30d_usd=Decimal("0"), maker_fee_bps=Decimal("16"), taker_fee_bps=Decimal("26")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("100000"), maker_fee_bps=Decimal("14"), taker_fee_bps=Decimal("24")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("1000000"), maker_fee_bps=Decimal("12"), taker_fee_bps=Decimal("20")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("10000000"), maker_fee_bps=Decimal("0"), taker_fee_bps=Decimal("10")),
                ],
            ),
            # Crypto — Coinbase Advanced Trade: US-legal but the most expensive (~40/60 bps retail). Confirms the
            # finding: forced off Binance for US live crypto, the fee wall gets HIGHER, not lower.
            Venue(
                id="coinbase", name="Coinbase", kind="crypto", adapter="nautilus.coinbase",
                maker_fee_bps=Decimal("40"), taker_fee_bps=Decimal("60"),
                min_notional=Decimal("1"), lot_size=Decimal("0.000001"),
                live_enabled=True, restricted_jurisdictions=[],
                fee_tiers=[
                    VenueFeeTier(min_volume_30d_usd=Decimal("0"), maker_fee_bps=Decimal("40"), taker_fee_bps=Decimal("60")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("10000"), maker_fee_bps=Decimal("25"), taker_fee_bps=Decimal("40")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("1000000"), maker_fee_bps=Decimal("15"), taker_fee_bps=Decimal("25")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("100000000"), maker_fee_bps=Decimal("0"), taker_fee_bps=Decimal("5")),
                ],
            ),
            # Equity — IBKR: our LIVE stocks venue. Tiered/fixed pricing nets to well under a basis point on
            # liquid names — the cheapest live venue we have, and why equities are the better live edge.
            Venue(
                id="ibkr", name="IBKR", kind="equity", adapter="nautilus.ibkr",
                maker_fee_bps=Decimal("0.5"), taker_fee_bps=Decimal("0.5"),
                min_notional=Decimal("1"), lot_size=Decimal("1"),
                live_enabled=True, restricted_jurisdictions=[],
            ),
            # Equity — Alpaca: commission-free DATA + paper (forward-test) venue. Not a live execution path yet,
            # so live_enabled stays False — it feeds the lab and the incubation clock, it does not move money.
            Venue(
                id="alpaca", name="Alpaca", kind="equity", adapter="nautilus.alpaca",
                maker_fee_bps=Decimal("0"), taker_fee_bps=Decimal("0"),
                min_notional=Decimal("1"), lot_size=Decimal("1"),
                live_enabled=False, restricted_jurisdictions=[],
            ),
            # Crypto — OKX: MiCA-compliant EU entity (OKX Europe Ltd, Malta). Spot + perp data source;
            # cheaper than Binance at high volume (spot: 8/10 bps retail, 2/3 bps at >$400M).
            # NOT live yet — execution wired only once live interlock + 5 gates pass.
            # Legality: available EU/FR via OKX Europe; restricted for US persons (no FinCEN/CFTC reg).
            Venue(
                id="okx", name="OKX", kind="crypto", adapter="nautilus.okx",
                maker_fee_bps=Decimal("8"), taker_fee_bps=Decimal("10"),
                min_notional=Decimal("1"), lot_size=Decimal("0.00001"),
                live_enabled=False, restricted_jurisdictions=["US"],
                fee_tiers=[
                    VenueFeeTier(min_volume_30d_usd=Decimal("0"),         maker_fee_bps=Decimal("8"),   taker_fee_bps=Decimal("10")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("1000000"),   maker_fee_bps=Decimal("7"),   taker_fee_bps=Decimal("9")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("5000000"),   maker_fee_bps=Decimal("6"),   taker_fee_bps=Decimal("8")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("20000000"),  maker_fee_bps=Decimal("5"),   taker_fee_bps=Decimal("7")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("100000000"), maker_fee_bps=Decimal("3"),   taker_fee_bps=Decimal("5")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("400000000"), maker_fee_bps=Decimal("2"),   taker_fee_bps=Decimal("3")),
                ],
            ),
            # Derivatives — Kraken Futures: linear perpetuals (PF_ prefix) via Crypto Facilities Ltd
            # (FCA UK) + Payward Europe Ltd (MiCA EU). Retail-perp fees are cheap: 2/5 bps at base,
            # maker rebate at >$100M. NOT live — execution wired only after live interlock + 5 gates.
            # Legality: available EU/FR (MiCA entity); US retail restricted (no CFTC retail perp license).
            Venue(
                id="kraken_futures", name="Kraken Futures", kind="crypto", adapter="nautilus.kraken_futures",
                maker_fee_bps=Decimal("2"), taker_fee_bps=Decimal("5"),
                min_notional=Decimal("1"), lot_size=Decimal("1"),
                live_enabled=False, restricted_jurisdictions=["US"],
                fee_tiers=[
                    VenueFeeTier(min_volume_30d_usd=Decimal("0"),         maker_fee_bps=Decimal("2"),    taker_fee_bps=Decimal("5")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("1000000"),   maker_fee_bps=Decimal("1.5"),  taker_fee_bps=Decimal("4")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("10000000"),  maker_fee_bps=Decimal("1"),    taker_fee_bps=Decimal("3")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("50000000"),  maker_fee_bps=Decimal("0"),    taker_fee_bps=Decimal("2.5")),
                    VenueFeeTier(min_volume_30d_usd=Decimal("100000000"), maker_fee_bps=Decimal("-1"),   taker_fee_bps=Decimal("2")),
                ],
            ),
            # Prediction — Polymarket: research / cross-asset signal source (no live wiring).
            Venue(
                id="polymarket", name="Polymarket", kind="prediction", adapter="nautilus.polymarket",
                maker_fee_bps=Decimal("0"), taker_fee_bps=Decimal("0"),
                min_notional=Decimal("1"), lot_size=Decimal("1"),
                live_enabled=False, restricted_jurisdictions=["US"],
            ),
        ],
        instruments=[
            Instrument(id="btc-usdt-binance", venue_id="binance", symbol="BTCUSDT", asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.00001"), min_notional=Decimal("10")),
            Instrument(id="eth-usdt-binance", venue_id="binance", symbol="ETHUSDT", asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.0001"), min_notional=Decimal("10")),
            Instrument(id="btc-usd-kraken", venue_id="kraken", symbol="BTC/USD", asset_class="crypto", tick_size=Decimal("0.1"), lot_size=Decimal("0.00001"), min_notional=Decimal("10")),
            Instrument(id="btc-usd-coinbase", venue_id="coinbase", symbol="BTC-USD", asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.000001"), min_notional=Decimal("1")),
            Instrument(id="spy-ibkr", venue_id="ibkr", symbol="SPY", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="qqq-ibkr", venue_id="ibkr", symbol="QQQ", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="aapl-ibkr", venue_id="ibkr", symbol="AAPL", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="msft-ibkr", venue_id="ibkr", symbol="MSFT", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="tsla-ibkr", venue_id="ibkr", symbol="TSLA", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            # Deploy-lane fleet ETFs (GEM/Faber/VAA/ADM/TSMOM/risk-parity/sector/dual-mom) — equity @ IBKR
            Instrument(id="efa-ibkr", venue_id="ibkr", symbol="EFA", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="eem-ibkr", venue_id="ibkr", symbol="EEM", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="agg-ibkr", venue_id="ibkr", symbol="AGG", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="bnd-ibkr", venue_id="ibkr", symbol="BND", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="bil-ibkr", venue_id="ibkr", symbol="BIL", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="shy-ibkr", venue_id="ibkr", symbol="SHY", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="ief-ibkr", venue_id="ibkr", symbol="IEF", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="tlt-ibkr", venue_id="ibkr", symbol="TLT", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="lqd-ibkr", venue_id="ibkr", symbol="LQD", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="hyg-ibkr", venue_id="ibkr", symbol="HYG", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="tip-ibkr", venue_id="ibkr", symbol="TIP", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="gld-ibkr", venue_id="ibkr", symbol="GLD", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="dbc-ibkr", venue_id="ibkr", symbol="DBC", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="vnq-ibkr", venue_id="ibkr", symbol="VNQ", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="iwm-ibkr", venue_id="ibkr", symbol="IWM", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlb-ibkr", venue_id="ibkr", symbol="XLB", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlc-ibkr", venue_id="ibkr", symbol="XLC", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xle-ibkr", venue_id="ibkr", symbol="XLE", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlf-ibkr", venue_id="ibkr", symbol="XLF", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xli-ibkr", venue_id="ibkr", symbol="XLI", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlk-ibkr", venue_id="ibkr", symbol="XLK", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlp-ibkr", venue_id="ibkr", symbol="XLP", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlre-ibkr", venue_id="ibkr", symbol="XLRE", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlu-ibkr", venue_id="ibkr", symbol="XLU", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xlv-ibkr", venue_id="ibkr", symbol="XLV", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="xly-ibkr", venue_id="ibkr", symbol="XLY", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="spy-alpaca", venue_id="alpaca", symbol="SPY", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            # OKX spot
            Instrument(id="btc-usdt-okx",      venue_id="okx", symbol="BTC-USDT",      asset_class="crypto", tick_size=Decimal("0.1"),  lot_size=Decimal("0.00001"), min_notional=Decimal("1")),
            Instrument(id="eth-usdt-okx",      venue_id="okx", symbol="ETH-USDT",      asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.0001"),  min_notional=Decimal("1")),
            # OKX perpetual swaps — 20-asset universe for the funding-dispersion strategy.
            # tick_size/lot_size sourced from OKX public instrument API; min_notional=1 USDT for all.
            Instrument(id="btc-usdt-swap-okx",   venue_id="okx", symbol="BTC-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.1"),      lot_size=Decimal("0.001"),    min_notional=Decimal("1")),
            Instrument(id="eth-usdt-swap-okx",   venue_id="okx", symbol="ETH-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.01"),     lot_size=Decimal("0.01"),     min_notional=Decimal("1")),
            Instrument(id="sol-usdt-swap-okx",   venue_id="okx", symbol="SOL-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.01"),     lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="xrp-usdt-swap-okx",   venue_id="okx", symbol="XRP-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.0001"),   lot_size=Decimal("10"),       min_notional=Decimal("1")),
            Instrument(id="link-usdt-swap-okx",  venue_id="okx", symbol="LINK-USDT-SWAP",  asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="avax-usdt-swap-okx",  venue_id="okx", symbol="AVAX-USDT-SWAP",  asset_class="crypto", tick_size=Decimal("0.01"),     lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="ada-usdt-swap-okx",   venue_id="okx", symbol="ADA-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.0001"),   lot_size=Decimal("10"),       min_notional=Decimal("1")),
            Instrument(id="dot-usdt-swap-okx",   venue_id="okx", symbol="DOT-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("1"),        min_notional=Decimal("1")),
            Instrument(id="pol-usdt-swap-okx",   venue_id="okx", symbol="POL-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.0001"),   lot_size=Decimal("10"),       min_notional=Decimal("1")),
            Instrument(id="atom-usdt-swap-okx",  venue_id="okx", symbol="ATOM-USDT-SWAP",  asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="ltc-usdt-swap-okx",   venue_id="okx", symbol="LTC-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.01"),     lot_size=Decimal("0.01"),     min_notional=Decimal("1")),
            Instrument(id="bch-usdt-swap-okx",   venue_id="okx", symbol="BCH-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.1"),      lot_size=Decimal("0.01"),     min_notional=Decimal("1")),
            Instrument(id="doge-usdt-swap-okx",  venue_id="okx", symbol="DOGE-USDT-SWAP",  asset_class="crypto", tick_size=Decimal("0.00001"),  lot_size=Decimal("100"),      min_notional=Decimal("1")),
            Instrument(id="near-usdt-swap-okx",  venue_id="okx", symbol="NEAR-USDT-SWAP",  asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("1"),        min_notional=Decimal("1")),
            Instrument(id="uni-usdt-swap-okx",   venue_id="okx", symbol="UNI-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="fil-usdt-swap-okx",   venue_id="okx", symbol="FIL-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("1"),        min_notional=Decimal("1")),
            Instrument(id="inj-usdt-swap-okx",   venue_id="okx", symbol="INJ-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("0.1"),      min_notional=Decimal("1")),
            Instrument(id="op-usdt-swap-okx",    venue_id="okx", symbol="OP-USDT-SWAP",    asset_class="crypto", tick_size=Decimal("0.0001"),   lot_size=Decimal("1"),        min_notional=Decimal("1")),
            Instrument(id="arb-usdt-swap-okx",   venue_id="okx", symbol="ARB-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.0001"),   lot_size=Decimal("1"),        min_notional=Decimal("1")),
            Instrument(id="ton-usdt-swap-okx",   venue_id="okx", symbol="TON-USDT-SWAP",   asset_class="crypto", tick_size=Decimal("0.001"),    lot_size=Decimal("1"),        min_notional=Decimal("1")),
            # Kraken Futures linear perpetuals (PF_ = linear; PI_ = inverse, not wired yet).
            # Fees: 2/5 bps retail (cheapest perp venue we have), maker rebate at >$100M.
            # FR-legal via Payward Europe Ltd (MiCA EU entity). live_enabled=False until live interlock.
            Instrument(id="xbt-usd-kf",   venue_id="kraken_futures", symbol="PF_XBTUSD",  asset_class="crypto", tick_size=Decimal("0.5"),   lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="eth-usd-kf",   venue_id="kraken_futures", symbol="PF_ETHUSD",  asset_class="crypto", tick_size=Decimal("0.05"),  lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="sol-usd-kf",   venue_id="kraken_futures", symbol="PF_SOLUSD",  asset_class="crypto", tick_size=Decimal("0.01"),  lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="xrp-usd-kf",   venue_id="kraken_futures", symbol="PF_XRPUSD",  asset_class="crypto", tick_size=Decimal("0.0001"),lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="link-usd-kf",  venue_id="kraken_futures", symbol="PF_LINKUSD", asset_class="crypto", tick_size=Decimal("0.001"), lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="avax-usd-kf",  venue_id="kraken_futures", symbol="PF_AVAXUSD", asset_class="crypto", tick_size=Decimal("0.01"),  lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="ada-usd-kf",   venue_id="kraken_futures", symbol="PF_ADAUSD",  asset_class="crypto", tick_size=Decimal("0.0001"),lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="dot-usd-kf",   venue_id="kraken_futures", symbol="PF_DOTUSD",  asset_class="crypto", tick_size=Decimal("0.001"), lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="doge-usd-kf",  venue_id="kraken_futures", symbol="PF_DOGEUSD", asset_class="crypto", tick_size=Decimal("0.00001"),lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="ltc-usd-kf",   venue_id="kraken_futures", symbol="PF_LTCUSD",  asset_class="crypto", tick_size=Decimal("0.01"),  lot_size=Decimal("1"),  min_notional=Decimal("1")),
            Instrument(id="pm-fed-cut", venue_id="polymarket", symbol="PM-FED-CUT-2026", asset_class="prediction", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
        ],
    )
