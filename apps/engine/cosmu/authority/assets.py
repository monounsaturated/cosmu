# intent: ASSET → TAPE resolution for the AUTHORITY scorer. Signal accounts call CRYPTO, but also EQUITIES/ETFs
# and COMMODITIES; each call needs a price series to resolve against, and V1 only mapped crypto → so every stock or
# commodity call read "no_data". This module is the ONE place an asset is mapped to a reference tape source, plus a
# thin router that fetches the right tape per asset class: crypto via the keyless crypto reference; equities &
# commodities via FREE Stooq/Yahoo daily bars (discovery-grade — survivorship-biased, declared, fine for proving a
# call corroborated the tape, not for deployable capacity). Commodities resolve through a liquid, free ETF PROXY
# (GOLD→GLD, OIL→USO, …) so they ride the same free equity provider. invariants: PURE mapping + a thin fetch seam
# (providers are INJECTED, so tests need no network); OFFLINE-SAFE (an unmapped or unfetchable asset is OMITTED →
# its calls resolve no_data → the account reads UNTESTED, never guessed); never fabricates a price; the tape dict
# is keyed by the call's ORIGINAL asset string (the price-join key the scorer uses).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol

from cosmu.authority.models import PricePoint

AssetClass = Literal["crypto", "equity", "commodity"]


class _BarProvider(Protocol):
    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list: ...  # noqa: ANN001


@dataclass(frozen=True)
class AssetRef:
    """One asset resolved to a fetchable reference: `asset` is the call's ticker as stored (BTC, AAPL, GOLD),
    `asset_class` routes it to the right provider, `symbol` is what that provider fetches (BTCUSDT, AAPL, GLD)."""

    asset: str
    asset_class: AssetClass
    symbol: str


# Crypto asset → reference venue symbol (the keyless crypto reference's contract, e.g. Binance 'BTCUSDT'). This is
# the canonical crypto map (run.py re-exports it as DEFAULT_ASSET_SYMBOL). Extend as new crypto calls appear.
CRYPTO_SYMBOLS: dict[str, str] = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT", "LINK": "LINKUSDT", "DOT": "DOTUSDT",
    "LTC": "LTCUSDT", "MATIC": "MATICUSDT", "TON": "TONUSDT", "TRX": "TRXUSDT",
}

# Commodity (and FX-metal) call → a liquid, free, survivorship-OK ETF PROXY served by the equity provider. A "GOLD"
# / "$XAU" / "oil" call resolves against the proxy's tape. Proxies, not futures, on purpose: free + no roll/expiry.
COMMODITY_SYMBOLS: dict[str, str] = {
    "GOLD": "GLD", "XAU": "GLD", "XAUUSD": "GLD", "GLD": "GLD",
    "SILVER": "SLV", "XAG": "SLV", "XAGUSD": "SLV", "SLV": "SLV",
    "OIL": "USO", "CRUDE": "USO", "WTI": "USO", "USO": "USO",
    "NATGAS": "UNG", "NATURALGAS": "UNG", "UNG": "UNG",
    "COPPER": "CPER", "CPER": "CPER",
    "URANIUM": "URA", "URA": "URA",
    "PLATINUM": "PPLT", "PALLADIUM": "PALL",
    "WHEAT": "WEAT", "CORN": "CORN",
}

# Common index / nickname aliases for equities → the tradable ETF or ticker the free provider serves.
EQUITY_ALIASES: dict[str, str] = {
    "SPX": "SPY", "SP500": "SPY", "SPX500": "SPY", "ES": "SPY", "SPY": "SPY",
    "NDX": "QQQ", "NASDAQ": "QQQ", "NQ": "QQQ", "QQQ": "QQQ",
    "DJI": "DIA", "DOW": "DIA", "DIA": "DIA",
    "RUSSELL": "IWM", "RUT": "IWM", "IWM": "IWM",
    "VIX": "VIXY",
}

# An equity ticker is 1-5 uppercase letters, optionally a dot share-class (BRK.B). Anything matching this and not
# already claimed by crypto/commodity/alias is treated as an equity and fetched AS-IS — this is what lets a plain
# STOCK call ("AAPL", "NVDA", "TSLA") resolve without enumerating every ticker. A non-ticker just returns no bars.
_EQUITY_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def normalize_asset(asset: str) -> str:
    """The corpus-canonical asset key: trimmed, upper-cased, leading '$' stripped (matches ingest._norm_asset)."""
    return (asset or "").strip().upper().lstrip("$")


def resolve_asset(asset: str) -> AssetRef | None:
    """Map an asset string to a fetchable reference, or None if nothing sensible matches (→ no_data, never guessed).
    Precedence: crypto map → commodity proxy → equity alias → bare equity-ticker shape. Crypto wins over the
    equity-ticker fallback so 'BTC' never routes to a stock named BTC."""
    a = normalize_asset(asset)
    if not a:
        return None
    if a in CRYPTO_SYMBOLS:
        return AssetRef(a, "crypto", CRYPTO_SYMBOLS[a])
    if a in COMMODITY_SYMBOLS:
        return AssetRef(a, "commodity", COMMODITY_SYMBOLS[a])
    if a in EQUITY_ALIASES:
        return AssetRef(a, "equity", EQUITY_ALIASES[a])
    if _EQUITY_TICKER_RE.match(a):
        return AssetRef(a, "equity", a)
    return None


def _prices_from_bars(bars: Iterable) -> list[PricePoint]:
    """Bar (cosmu.data.market.Bar) → the scorer's PricePoint tape (close price). Kept local so this module needs no
    store import (assets stays a leaf)."""
    return [PricePoint(ts=b.ts, price=float(b.close)) for b in bars]


def build_tape(
    assets: Iterable[str],
    *,
    crypto_provider: _BarProvider,
    equity_provider: _BarProvider,
    limit: int = 400,
    crypto_symbol_override: dict[str, str] | None = None,
) -> dict[str, list[PricePoint]]:
    """Route each asset to its reference tape and return {asset: [PricePoint,…]} keyed by the call's ORIGINAL asset
    string. Crypto → `crypto_provider`; equities & commodities → `equity_provider` (commodities via their ETF
    proxy). OFFLINE-SAFE: an unmapped or unfetchable asset is OMITTED (no_data → UNTESTED, never guessed); a
    provider that raises is treated as empty (degrade, never crash the pass). `crypto_symbol_override` lets a caller
    pin/extend the crypto symbol map (keys normalized like the corpus); it only ever routes through the crypto
    provider. Providers are injected, so this is fully unit-testable without network."""
    overrides = {normalize_asset(k): v for k, v in (crypto_symbol_override or {}).items()}
    out: dict[str, list[PricePoint]] = {}
    for asset in sorted({a for a in assets if a}):
        a = normalize_asset(asset)
        override_sym = overrides.get(a)
        if override_sym is not None:
            provider, symbol = crypto_provider, override_sym
        else:
            ref = resolve_asset(asset)
            if ref is None:
                continue
            provider = crypto_provider if ref.asset_class == "crypto" else equity_provider
            symbol = ref.symbol
        try:
            bars = provider.fetch_bars(symbol, "1d", limit=limit)
        except Exception:  # noqa: BLE001 — offline / throttled / bad symbol: this asset is no_data this pass
            bars = []
        if bars:
            out[asset] = _prices_from_bars(bars)
    return out


__all__ = [
    "COMMODITY_SYMBOLS",
    "CRYPTO_SYMBOLS",
    "EQUITY_ALIASES",
    "AssetClass",
    "AssetRef",
    "build_tape",
    "normalize_asset",
    "resolve_asset",
]
