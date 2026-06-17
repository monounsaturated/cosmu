# intent: the ONE venue-tagged, liquidity-ranked SOURCE of every tradable pair across our venues — fetch the live
# instrument list + 24h liquidity from each venue's PUBLIC API (no key), normalize to one `UniversePair` shape,
# and rank into liquidity tiers (Tier-0 ~20-30 / Tier-1 ~100-150 / Tier-2 deep). inputs: per-venue public REST
# (Binance spot+perp, Kraken spot+futures, Hyperliquid, Polymarket) + a CURATED IBKR/equity list (IBKR has no
# keyless public instrument feed); outputs: list[UniversePair] (venue, symbol, base/quote, asset_class,
# instrument_type, liquidity_usd_24h, listed_at, tier). invariants: REGULAR assets only (crypto/equity/FX/
# prediction — NO alt assets); REAL liquidity (24h USD quote-volume where measurable, else 0 + documented, never
# fabricated); deterministic order (rank by measured USD liquidity desc, stable tiebreak); every fetcher is
# offline-testable via an injected `get`/`post` seam (no network in CI). This is the data-side foundation for
# testing wide per (strategy × symbol × VENUE) — survivorship honesty stays the UniverseCalendar's job
# (see binance_vision_listings here + data/universe_calendar.py).

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("cosmu.data.venue_universe")

__all__ = [
    "UniversePair",
    "GetJson",
    "PostJson",
    "TIER0_N",
    "TIER1_N",
    "USD_STABLE_QUOTES",
    "fetch_binance_spot",
    "fetch_binance_perp",
    "fetch_kraken_spot",
    "fetch_kraken_futures",
    "fetch_hyperliquid",
    "fetch_polymarket",
    "ibkr_curated_pairs",
    "rank_and_tier",
    "collect_all_venues",
    "fetch_all_venues",
    "binance_vision_spot_symbols",
    "binance_vision_symbol_window",
]

# Tier sizes (operator spec): Tier-0 the ~20-30 deepest names, Tier-1 the next ~100-150, Tier-2 everything else.
# These bound the *global* liquidity rank across all measured-USD pairs — the lab can re-tier per asset class.
TIER0_N = 30
TIER1_N = 150

# Quote assets we treat as ~1 USD (so 24h quote-volume IS the USD liquidity). Non-USD quotes (EUR/GBP/BTC-quoted
# pairs) are still LISTED but get liquidity_usd_24h=0.0 — we rank on measured USD only and never fabricate an FX
# conversion. The deep USDT/USDC books that dominate the tiers are exactly the testing-wide universe we want.
USD_STABLE_QUOTES: frozenset[str] = frozenset({"USDT", "USDC", "USD", "FDUSD", "DAI", "TUSD", "BUSD", "USDD", "PYUSD", "ZUSD"})

# ---------------------------------------------------------------------------------------------------------------
# HTTP seams — stdlib only, injectable so every fetcher runs OFFLINE in tests (replay a JSON fixture).
# ---------------------------------------------------------------------------------------------------------------
GetJson = Callable[[str], Any]
PostJson = Callable[[str, dict[str, Any]], Any]


def _safe_url(url: str) -> str:
    """Percent-encode any stray non-ASCII bytes (e.g. a junk symbol in an S3 continuation marker) while leaving
    the URL's structural characters intact — urllib's ascii request encoder would otherwise raise on them."""
    import urllib.parse

    return urllib.parse.quote(url, safe=":/?&=%+,@~")


def _default_get_json(url: str) -> Any:
    import urllib.request

    from cosmu.data.market import _ssl_context

    req = urllib.request.Request(_safe_url(url), headers={"User-Agent": "cosmu-universe/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 - public venue APIs
        return json.loads(resp.read())


def _default_post_json(url: str, payload: dict[str, Any]) -> Any:
    import urllib.request

    from cosmu.data.market import _ssl_context

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _safe_url(url), data=data, headers={"Content-Type": "application/json", "User-Agent": "cosmu-universe/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 - public venue APIs
        return json.loads(resp.read())


def _default_get_text(url: str) -> str:
    import urllib.request

    from cosmu.data.market import _ssl_context

    req = urllib.request.Request(_safe_url(url), headers={"User-Agent": "cosmu-universe/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 - public S3 listing
        return resp.read().decode("utf-8", "replace")


def _ms_to_dt(ms: Any) -> datetime | None:
    try:
        v = int(ms)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return datetime.fromtimestamp(v / 1000, tz=UTC)


def _iso_to_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------------------------------------------
# The normalized unit — one row per (venue, symbol). `id` = "venue:symbol" is the stable primary key.
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class UniversePair:
    venue: str
    symbol: str               # the venue's own spelling (BTCUSDT / BTC/USD / PF_XBTUSD / BTC / conditionId)
    base: str
    quote: str
    asset_class: str          # "crypto" | "equity" | "prediction"
    instrument_type: str      # "spot" | "perp" | "equity" | "prediction"
    liquidity_usd_24h: float  # measured 24h USD volume / book depth; 0.0 when not USD-measurable (still listed)
    source: str               # "live" | "curated"
    listed_at: datetime | None = None
    delisted_at: datetime | None = None
    active: bool = True
    tier: int | None = None   # 0/1/2 — assigned by rank_and_tier; None until ranked
    rank: int | None = None   # global liquidity rank (0 = deepest); None until ranked
    # Curated pairs (IBKR equities) have no measured USD liquidity — this hint keeps them out of Tier-2 by
    # default. Only used when liquidity_usd_24h <= 0; measured pairs always rank by their real liquidity.
    tier_hint: int | None = None

    @property
    def id(self) -> str:
        return f"{self.venue}:{self.symbol}"


# ---------------------------------------------------------------------------------------------------------------
# Binance — spot + USDⓈ-M perpetuals (api.binance.com / fapi.binance.com public exchangeInfo + ticker/24hr).
# ---------------------------------------------------------------------------------------------------------------
def fetch_binance_spot(get: GetJson | None = None) -> list[UniversePair]:
    """Every TRADING Binance spot pair + its 24h quote-volume. USD-stable-quoted pairs get a measured USD
    liquidity (quoteVolume); other quotes stay listed at 0.0 (ranked low, never FX-fabricated)."""
    get = get or _default_get_json
    info = get("https://api.binance.com/api/v3/exchangeInfo?permissions=SPOT")
    tickers = get("https://api.binance.com/api/v3/ticker/24hr")
    qv = {t["symbol"]: _f(t.get("quoteVolume")) for t in tickers if isinstance(t, dict) and "symbol" in t}
    out: list[UniversePair] = []
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        quote = s.get("quoteAsset", "")
        liq = qv.get(s["symbol"], 0.0) if quote in USD_STABLE_QUOTES else 0.0
        out.append(
            UniversePair(
                venue="binance", symbol=s["symbol"], base=s.get("baseAsset", ""), quote=quote,
                asset_class="crypto", instrument_type="spot", liquidity_usd_24h=liq, source="live",
            )
        )
    return out


def fetch_binance_perp(get: GetJson | None = None) -> list[UniversePair]:
    """Binance USDⓈ-M PERPETUAL contracts. `onboardDate` is a real listing date → listed_at (PIT honesty)."""
    get = get or _default_get_json
    info = get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    tickers = get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    qv = {t["symbol"]: _f(t.get("quoteVolume")) for t in tickers if isinstance(t, dict) and "symbol" in t}
    out: list[UniversePair] = []
    for s in info.get("symbols", []):
        if s.get("contractType") != "PERPETUAL" or s.get("status") != "TRADING":
            continue
        quote = s.get("quoteAsset", "")
        liq = qv.get(s["symbol"], 0.0) if quote in USD_STABLE_QUOTES else 0.0
        out.append(
            UniversePair(
                venue="binanceperp", symbol=s["symbol"], base=s.get("baseAsset", ""), quote=quote,
                asset_class="crypto", instrument_type="perp", liquidity_usd_24h=liq, source="live",
                listed_at=_ms_to_dt(s.get("onboardDate")),
            )
        )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Kraken — spot AssetPairs + futures (linear perpetuals, PF_ prefix).
# ---------------------------------------------------------------------------------------------------------------
def fetch_kraken_spot(get: GetJson | None = None) -> list[UniversePair]:
    """Online Kraken spot pairs + 24h USD volume. Ticker `v[1]` is 24h base volume, `p[1]` is 24h VWAP →
    USD volume = base_vol × vwap for USD-stable quotes (Kraken's Z-prefixed fiats normalized)."""
    get = get or _default_get_json
    pairs = (get("https://api.kraken.com/0/public/AssetPairs") or {}).get("result", {})
    ticker = (get("https://api.kraken.com/0/public/Ticker") or {}).get("result", {})
    out: list[UniversePair] = []
    for key, p in pairs.items():
        if p.get("status") != "online":
            continue
        base = _kraken_asset(p.get("base", ""))
        quote = _kraken_asset(p.get("quote", ""))
        t = ticker.get(key, {})
        liq = 0.0
        if quote in USD_STABLE_QUOTES and isinstance(t.get("v"), list) and isinstance(t.get("p"), list):
            liq = _f(t["v"][1]) * _f(t["p"][1])  # 24h base volume × 24h VWAP ≈ USD volume
        out.append(
            UniversePair(
                venue="kraken", symbol=p.get("altname", key), base=base, quote=quote,
                asset_class="crypto", instrument_type="spot", liquidity_usd_24h=liq, source="live",
            )
        )
    return out


def _kraken_asset(code: str) -> str:
    """Kraken prefixes legacy fiats/metals with Z/X (ZUSD, XXBT). Strip to the common ticker, map XBT→BTC."""
    if len(code) == 4 and code[0] in {"Z", "X"}:
        code = code[1:]
    return "BTC" if code == "XBT" else code


def fetch_kraken_futures(get: GetJson | None = None) -> list[UniversePair]:
    """Kraken Futures LINEAR perpetuals (PF_ prefix; PI_ inverse skipped). Ticker volumeQuote is 24h USD."""
    get = get or _default_get_json
    instruments = (get("https://futures.kraken.com/derivatives/api/v3/instruments") or {}).get("instruments", [])
    tickers = (get("https://futures.kraken.com/derivatives/api/v3/tickers") or {}).get("tickers", [])
    vol = {t.get("symbol", "").upper(): _f(t.get("volumeQuote")) for t in tickers}
    out: list[UniversePair] = []
    for inst in instruments:
        sym = str(inst.get("symbol", "")).upper()
        if not sym.startswith("PF_") or not inst.get("tradeable", False):
            continue
        base = sym[3:].replace("USD", "", 1).replace("XBT", "BTC") or sym
        out.append(
            UniversePair(
                venue="kraken_futures", symbol=sym, base=base, quote="USD",
                asset_class="crypto", instrument_type="perp",
                liquidity_usd_24h=vol.get(sym, 0.0), source="live",
            )
        )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Hyperliquid — on-chain perp DEX. `metaAndAssetCtxs` gives the universe + per-asset `dayNtlVlm` (24h USD notional).
# ---------------------------------------------------------------------------------------------------------------
def fetch_hyperliquid(post: PostJson | None = None) -> list[UniversePair]:
    post = post or _default_post_json
    data = post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    universe = (data[0].get("universe", []) if isinstance(data, list) and data else [])
    ctxs = data[1] if isinstance(data, list) and len(data) > 1 else []
    out: list[UniversePair] = []
    for i, u in enumerate(universe):
        if u.get("isDelisted"):
            continue
        ctx = ctxs[i] if i < len(ctxs) else {}
        name = u.get("name", "")
        out.append(
            UniversePair(
                venue="hyperliquid", symbol=name, base=name, quote="USD",
                asset_class="crypto", instrument_type="perp",
                liquidity_usd_24h=_f(ctx.get("dayNtlVlm")), source="live",
            )
        )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Polymarket — prediction markets via the public Gamma API (USD book liquidity + start/end dates for PIT).
# ---------------------------------------------------------------------------------------------------------------
def fetch_polymarket(get: GetJson | None = None, *, limit: int = 500, pages: int = 2) -> list[UniversePair]:
    """The most-liquid OPEN Polymarket markets (by USD book liquidity). `liquidityNum` is current book depth in
    USD — the honest liquidity measure for a thin event market (not a 24h flow). startDate/endDate → PIT window."""
    get = get or _default_get_json
    out: list[UniversePair] = []
    seen: set[str] = set()
    for page in range(max(1, pages)):
        url = (
            "https://gamma-api.polymarket.com/markets?closed=false&active=true"
            f"&order=liquidityNum&ascending=false&limit={limit}&offset={page * limit}"
        )
        markets = get(url)
        if not isinstance(markets, list) or not markets:
            break
        for m in markets:
            cid = m.get("conditionId")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(
                UniversePair(
                    venue="polymarket", symbol=cid,
                    base=(m.get("slug") or m.get("question") or cid)[:64], quote="USDC",
                    asset_class="prediction", instrument_type="prediction",
                    liquidity_usd_24h=_f(m.get("liquidityNum")), source="live",
                    listed_at=_iso_to_dt(m.get("startDate")), delisted_at=_iso_to_dt(m.get("endDate")),
                )
            )
    return out


# ---------------------------------------------------------------------------------------------------------------
# IBKR / US equities — IBKR has NO keyless public instrument feed (it needs an authenticated TWS/Gateway session),
# so the equity universe is a CURATED liquid US large-cap + ETF list. Tagged source="curated" and tiered by the
# `tier_hint` here (NOT a measured USD volume) so the honesty is explicit: these are picked, not liquidity-ranked.
# ---------------------------------------------------------------------------------------------------------------
# Tier-0 equities: the deepest, most-liquid US tape (mega-caps + the broad-index/sector ETFs the deploy lane uses).
_IBKR_TIER0 = (
    "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "TSLA", "AMD", "NFLX", "AVGO", "JPM", "BRK B", "XLF", "XLK", "XLE", "GLD",
)
# Tier-1 equities: the rest of the liquid S&P large-caps + the full sector/factor/bond ETF complex.
_IBKR_TIER1 = (
    "GOOG", "BAC", "WMT", "V", "MA", "UNH", "JNJ", "PG", "HD", "COST",
    "XOM", "CVX", "KO", "PEP", "ABBV", "MRK", "LLY", "PFE", "TMO", "ABT",
    "CRM", "ADBE", "ORCL", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU",
    "DIS", "CMCSA", "VZ", "T", "NKE", "MCD", "SBUX", "LOW", "TGT", "BKNG",
    "GS", "MS", "WFC", "C", "AXP", "BLK", "SCHW", "CAT", "BA", "GE",
    "HON", "UPS", "RTX", "LMT", "DE", "MMM", "F", "GM", "PYPL", "SQ",
    "PLTR", "COIN", "UBER", "ABNB", "SHOP", "SNOW", "MU", "AMAT", "LRCX", "ADI",
    "EFA", "EEM", "VEA", "VWO", "AGG", "BND", "TLT", "IEF", "SHY", "LQD",
    "HYG", "TIP", "BIL", "DBC", "SLV", "USO", "VNQ", "XLB", "XLC", "XLI",
    "XLP", "XLRE", "XLU", "XLV", "XLY", "SMH", "SOXX", "ARKK", "VTI", "VOO",
)


def ibkr_curated_pairs() -> list[UniversePair]:
    """Curated liquid US equity/ETF universe for IBKR (no keyless enumeration). tier_hint is set, liquidity is 0
    (unmeasured) — honest: these are picked names, not USD-liquidity-ranked like the crypto venues."""
    out: list[UniversePair] = []
    for tier, names in ((0, _IBKR_TIER0), (1, _IBKR_TIER1)):
        for name in names:
            out.append(
                UniversePair(
                    venue="ibkr", symbol=name, base=name, quote="USD",
                    asset_class="equity", instrument_type="equity",
                    liquidity_usd_24h=0.0, source="curated", tier_hint=tier,
                )
            )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Ranking + tiering — the ONE liquidity-ranked source. Measured-USD pairs rank by real 24h liquidity (desc);
# curated/unmeasured pairs keep their tier_hint (default Tier-2) and sort after the measured tape.
# ---------------------------------------------------------------------------------------------------------------
def rank_and_tier(pairs: list[UniversePair], *, tier0_n: int = TIER0_N, tier1_n: int = TIER1_N) -> list[UniversePair]:
    """Assign a global liquidity rank + a 0/1/2 tier to every pair. Deterministic: sort by measured USD liquidity
    desc, then venue/symbol for a stable tiebreak. Measured pairs (liquidity>0) tier by rank position; unmeasured
    curated pairs keep tier_hint (so a curated mega-cap is Tier-0/1, not buried in Tier-2)."""
    measured = sorted(
        (p for p in pairs if (p.liquidity_usd_24h or 0.0) > 0.0),
        key=lambda p: (-(p.liquidity_usd_24h or 0.0), p.venue, p.symbol),
    )
    unmeasured = sorted(
        (p for p in pairs if (p.liquidity_usd_24h or 0.0) <= 0.0),
        key=lambda p: (p.tier_hint if p.tier_hint is not None else 9, p.venue, p.symbol),
    )
    out: list[UniversePair] = []
    for i, p in enumerate(measured):
        tier = 0 if i < tier0_n else 1 if i < tier1_n else 2
        out.append(replace(p, tier=tier, rank=i))
    base_rank = len(measured)
    for j, p in enumerate(unmeasured):
        tier = p.tier_hint if p.tier_hint is not None else 2
        out.append(replace(p, tier=tier, rank=base_rank + j))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Orchestrator — fetch every venue, guard each (one venue down never sinks the run), rank + tier the union.
# ---------------------------------------------------------------------------------------------------------------
def collect_all_venues(
    *, get: GetJson | None = None, post: PostJson | None = None, include_curated: bool = True
) -> list[UniversePair]:
    """Union every venue's tradable pairs WITHOUT ranking (so a caller can add Vision-delisted rows before the
    single re-rank). Each venue is guarded — a venue API failure logs a warning and contributes [] so the run
    still completes with whatever is reachable."""
    sources: list[tuple[str, Callable[[], list[UniversePair]]]] = [
        ("binance_spot", lambda: fetch_binance_spot(get)),
        ("binance_perp", lambda: fetch_binance_perp(get)),
        ("kraken_spot", lambda: fetch_kraken_spot(get)),
        ("kraken_futures", lambda: fetch_kraken_futures(get)),
        ("hyperliquid", lambda: fetch_hyperliquid(post)),
        ("polymarket", lambda: fetch_polymarket(get)),
    ]
    pairs: list[UniversePair] = []
    for name, fn in sources:
        try:
            got = fn()
            logger.info("venue_universe: %s → %d pairs", name, len(got))
            pairs.extend(got)
        except Exception as e:  # noqa: BLE001 — one venue down must not sink the union
            logger.warning("venue_universe: %s fetch failed: %s", name, e)
    if include_curated:
        curated = ibkr_curated_pairs()
        logger.info("venue_universe: ibkr_curated → %d pairs", len(curated))
        pairs.extend(curated)
    return pairs


def fetch_all_venues(
    *,
    get: GetJson | None = None,
    post: PostJson | None = None,
    include_curated: bool = True,
    tier0_n: int = TIER0_N,
    tier1_n: int = TIER1_N,
) -> list[UniversePair]:
    """The single foundation call: union every venue's tradable pairs, rank by measured USD liquidity, tier."""
    pairs = collect_all_venues(get=get, post=post, include_curated=include_curated)
    return rank_and_tier(pairs, tier0_n=tier0_n, tier1_n=tier1_n)


# ---------------------------------------------------------------------------------------------------------------
# Survivorship backbone — enumerate EVERY Binance spot symbol that ever had data (delisted included) from the
# FREE Binance Vision S3 archive, and read each symbol's listed/delisted window from its monthly-kline key range.
# This is the source the UniverseCalendar needs so a historical backtest sees that date's tradable set, not the
# current-survivors set projected backwards. Heavy (one S3 list per symbol for the window) → operator/Modal-run.
# ---------------------------------------------------------------------------------------------------------------
# The S3 REST listing host for the public archive (the data.binance.vision root serves an HTML browser instead).
_VISION_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def binance_vision_spot_symbols(get_text: Callable[[str], str] | None = None, *, max_pages: int = 10) -> list[str]:
    """Every spot symbol dir under the Vision monthly-klines archive — the FULL historical set including delisted
    coins (the survivorship superset). Paginated S3 XML (1000 prefixes/page, marker-continued)."""
    import re

    get_text = get_text or _default_get_text
    prefix = "data/spot/monthly/klines/"
    symbols: list[str] = []
    marker = ""
    for _ in range(max_pages):
        url = f"{_VISION_S3}?delimiter=/&prefix={prefix}"
        if marker:
            url += f"&marker={marker}"
        xml = get_text(url)
        page = re.findall(rf"<Prefix>{re.escape(prefix)}([^/]+)/</Prefix>", xml)
        symbols.extend(page)
        truncated = (re.search(r"<IsTruncated>(\w+)</IsTruncated>", xml) or [None, "false"])[1] == "true"
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", xml)
        if not truncated or not page:
            break
        marker = nm.group(1) if nm else f"{prefix}{page[-1]}/"
    # Keep only real venue spellings (uppercase alphanumeric) — drops any stray/non-ASCII CommonPrefix so a junk
    # entry can't become a universe row or break URL encoding downstream. De-dup, order-preserving.
    seen: set[str] = set()
    return [s for s in symbols if s.isascii() and s.isalnum() and s.isupper() and not (s in seen or seen.add(s))]


def binance_vision_symbol_window(
    symbol: str, *, market: str = "spot", timeframe: str = "1d", get_text: Callable[[str], str] | None = None
) -> tuple[datetime | None, datetime | None]:
    """(first_month, last_month) UTC for a symbol from its monthly-kline archive keys — NO bar download, just the
    S3 key listing. first ≈ listed_at; last (when it ends well before now) ≈ delisted_at. Returns (None, None)
    when the symbol has no archive (caller treats that as 'no Vision history')."""
    import re

    get_text = get_text or _default_get_text
    tree = "spot" if market == "spot" else "futures/um"
    prefix = f"data/{tree}/monthly/klines/{symbol}/{timeframe}/"
    xml = get_text(f"{_VISION_S3}?prefix={prefix}")
    months = sorted(set(re.findall(rf"{re.escape(symbol)}-{re.escape(timeframe)}-(\d{{4}}-\d{{2}})\.zip", xml)))
    if not months:
        return (None, None)
    first = datetime.strptime(months[0] + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    # last month's data spans that whole month; mark the window end at the FIRST of the NEXT month (exclusive).
    ly, lm = (int(x) for x in months[-1].split("-"))
    last = datetime(ly + (lm // 12), (lm % 12) + 1, 1, tzinfo=UTC)
    return (first, last)
