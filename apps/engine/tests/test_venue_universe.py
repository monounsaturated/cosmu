# Offline tests for the venue-tagged, liquidity-ranked universe + survivorship calendar. Every venue fetch is
# driven through an injected `get`/`post`/`get_text` seam replaying a fixture — NO network (conftest blocks sockets).

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cosmu.config.settings import Settings
from cosmu.data.universe import load_universe, universe_symbols
from cosmu.data.universe_build import (
    build_binance_vision_delisted,
    build_universe,
    persist_universe,
)
from cosmu.data.universe_calendar import UniverseCalendar
from cosmu.data.venue_universe import (
    fetch_binance_perp,
    fetch_binance_spot,
    fetch_hyperliquid,
    fetch_kraken_futures,
    fetch_kraken_spot,
    fetch_polymarket,
    ibkr_curated_pairs,
    rank_and_tier,
)
from cosmu.knowledge.store import Store

# ---------------------------------------------------------------------------------------------------------------
# Fixtures — minimal but faithful shapes of each venue's real API response (verified against live 2026-06-17).
# ---------------------------------------------------------------------------------------------------------------
_BINANCE_SPOT_INFO = {"symbols": [
    {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT"},
    {"symbol": "ETHUSDT", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDT"},
    {"symbol": "ETHBTC", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "BTC"},      # non-USD quote → liq 0
    {"symbol": "DEADUSDT", "status": "BREAK", "baseAsset": "DEAD", "quoteAsset": "USDT"},    # not TRADING → dropped
]}
_BINANCE_SPOT_TICKER = [
    {"symbol": "BTCUSDT", "quoteVolume": "900000000"},
    {"symbol": "ETHUSDT", "quoteVolume": "400000000"},
    {"symbol": "ETHBTC", "quoteVolume": "5000"},
]
_BINANCE_PERP_INFO = {"symbols": [
    {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "baseAsset": "BTC",
     "quoteAsset": "USDT", "onboardDate": 1567965300000},
    {"symbol": "ETHUSDT", "status": "TRADING", "contractType": "PERPETUAL", "baseAsset": "ETH",
     "quoteAsset": "USDT", "onboardDate": 1569398400000},
    {"symbol": "BTCUSDT_240329", "status": "TRADING", "contractType": "CURRENT_QUARTER",  # not PERPETUAL → dropped
     "baseAsset": "BTC", "quoteAsset": "USDT", "onboardDate": 1700000000000},
]}
_BINANCE_PERP_TICKER = [
    {"symbol": "BTCUSDT", "quoteVolume": "8000000000"},
    {"symbol": "ETHUSDT", "quoteVolume": "7000000000"},
]
_KRAKEN_PAIRS = {"result": {
    "XXBTZUSD": {"altname": "XBTUSD", "base": "XXBT", "quote": "ZUSD", "status": "online"},
    "XETHZUSD": {"altname": "ETHUSD", "base": "XETH", "quote": "ZUSD", "status": "online"},
    "OLDEUR": {"altname": "OLDEUR", "base": "OLD", "quote": "ZEUR", "status": "online"},  # EUR quote → liq 0
    "DELISTED": {"altname": "DELISTED", "base": "DEL", "quote": "ZUSD", "status": "delisted"},  # dropped
}}
_KRAKEN_TICKER = {"result": {
    "XXBTZUSD": {"v": ["100", "1500"], "p": ["66000", "66000"]},   # 1500 × 66000 = 99,000,000
    "XETHZUSD": {"v": ["50", "800"], "p": ["3500", "3500"]},       # 800 × 3500 = 2,800,000
}}
_KRAKEN_FUTURES_INST = {"instruments": [
    {"symbol": "PF_XBTUSD", "type": "flexible_futures", "tradeable": True},
    {"symbol": "PF_ETHUSD", "type": "flexible_futures", "tradeable": True},
    {"symbol": "PI_XBTUSD", "type": "futures_inverse", "tradeable": True},   # inverse → dropped
    {"symbol": "PF_OLDUSD", "type": "flexible_futures", "tradeable": False},  # not tradeable → dropped
]}
_KRAKEN_FUTURES_TICK = {"tickers": [
    {"symbol": "PF_XBTUSD", "volumeQuote": "250000000"},
    {"symbol": "PF_ETHUSD", "volumeQuote": "75000000"},
]}
_HYPERLIQUID = [
    {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "GONE", "isDelisted": True}]},
    [{"dayNtlVlm": "1600000000"}, {"dayNtlVlm": "950000000"}, {"dayNtlVlm": "0"}],
]
_POLYMARKET = [
    {"conditionId": "0xaaa", "slug": "fed-cut", "liquidityNum": 25000,
     "startDate": "2025-05-02T00:00:00Z", "endDate": "2026-07-31T00:00:00Z"},
    {"conditionId": "0xbbb", "question": "Election?", "liquidityNum": 18000,
     "startDate": "2025-01-01T00:00:00Z", "endDate": "2026-11-03T00:00:00Z"},
    {"conditionId": "0xaaa", "liquidityNum": 25000},  # duplicate conditionId → deduped
]


def _fake_get(url: str):
    if "api.binance.com/api/v3/exchangeInfo" in url:
        return _BINANCE_SPOT_INFO
    if "api.binance.com/api/v3/ticker/24hr" in url:
        return _BINANCE_SPOT_TICKER
    if "fapi.binance.com/fapi/v1/exchangeInfo" in url:
        return _BINANCE_PERP_INFO
    if "fapi.binance.com/fapi/v1/ticker/24hr" in url:
        return _BINANCE_PERP_TICKER
    if "kraken.com/0/public/AssetPairs" in url:
        return _KRAKEN_PAIRS
    if "kraken.com/0/public/Ticker" in url:
        return _KRAKEN_TICKER
    if "futures.kraken.com" in url and "instruments" in url:
        return _KRAKEN_FUTURES_INST
    if "futures.kraken.com" in url and "tickers" in url:
        return _KRAKEN_FUTURES_TICK
    if "gamma-api.polymarket.com" in url:
        return _POLYMARKET if "offset=0" in url else []
    raise AssertionError(f"unexpected GET {url}")


def _fake_post(url: str, payload: dict):
    assert "hyperliquid" in url and payload.get("type") == "metaAndAssetCtxs"
    return _HYPERLIQUID


# --- Vision S3 listing fixtures (delisted-symbol enumeration + window probe) ------------------------------------
_VISION_LIST = (
    '<?xml version="1.0"?><ListBucketResult>'
    "<CommonPrefixes><Prefix>data/spot/monthly/klines/BTCUSDT/</Prefix></CommonPrefixes>"
    "<CommonPrefixes><Prefix>data/spot/monthly/klines/LUNAUSDT/</Prefix></CommonPrefixes>"
    "<CommonPrefixes><Prefix>data/spot/monthly/klines/FTTUSDT/</Prefix></CommonPrefixes>"
    "<IsTruncated>false</IsTruncated></ListBucketResult>"
)
_VISION_WINDOWS = {
    "LUNAUSDT": ["2020-08", "2020-09", "2022-04", "2022-05"],   # listed 2020-08, dead 2022-05
    "FTTUSDT": ["2019-07", "2022-11"],
    "BTCUSDT": ["2017-08", "2026-06"],
}


def _fake_get_text(url: str) -> str:
    if "delimiter=/" in url:
        return _VISION_LIST
    for sym, months in _VISION_WINDOWS.items():
        if f"/klines/{sym}/" in url:
            keys = "".join(
                f"<Contents><Key>data/spot/monthly/klines/{sym}/1d/{sym}-1d-{m}.zip</Key></Contents>"
                for m in months
            )
            return f"<ListBucketResult>{keys}</ListBucketResult>"
    return "<ListBucketResult></ListBucketResult>"


# ---------------------------------------------------------------------------------------------------------------
# Per-venue fetchers — shape, filtering, liquidity, listing dates.
# ---------------------------------------------------------------------------------------------------------------
def test_binance_spot_filters_and_liquidity():
    pairs = fetch_binance_spot(_fake_get)
    by = {p.symbol: p for p in pairs}
    assert set(by) == {"BTCUSDT", "ETHUSDT", "ETHBTC"}          # BREAK status dropped
    assert by["BTCUSDT"].liquidity_usd_24h == 900_000_000.0     # USDT quote → measured
    assert by["ETHBTC"].liquidity_usd_24h == 0.0               # non-USD quote → not USD-measured
    assert all(p.venue == "binance" and p.instrument_type == "spot" for p in pairs)


def test_binance_perp_only_perpetual_with_onboard_date():
    pairs = fetch_binance_perp(_fake_get)
    assert {p.symbol for p in pairs} == {"BTCUSDT", "ETHUSDT"}  # the dated quarterly is excluded
    btc = next(p for p in pairs if p.symbol == "BTCUSDT")
    assert btc.instrument_type == "perp" and btc.venue == "binanceperp"
    assert btc.listed_at == datetime.fromtimestamp(1567965300000 / 1000, tz=UTC)


def test_kraken_spot_normalizes_assets_and_usd_volume():
    pairs = fetch_kraken_spot(_fake_get)
    by = {p.symbol: p for p in pairs}
    assert set(by) == {"XBTUSD", "ETHUSD", "OLDEUR"}            # delisted dropped
    assert by["XBTUSD"].base == "BTC" and by["XBTUSD"].quote == "USD"  # X/Z stripped, XBT→BTC
    assert by["XBTUSD"].liquidity_usd_24h == pytest.approx(99_000_000.0)
    assert by["OLDEUR"].liquidity_usd_24h == 0.0               # EUR quote not USD-measured


def test_kraken_futures_linear_only():
    pairs = fetch_kraken_futures(_fake_get)
    assert {p.symbol for p in pairs} == {"PF_XBTUSD", "PF_ETHUSD"}  # inverse + untradeable dropped
    assert all(p.instrument_type == "perp" for p in pairs)
    assert next(p for p in pairs if p.symbol == "PF_XBTUSD").liquidity_usd_24h == 250_000_000.0


def test_hyperliquid_drops_delisted():
    pairs = fetch_hyperliquid(_fake_post)
    assert {p.symbol for p in pairs} == {"BTC", "ETH"}         # GONE isDelisted dropped
    assert next(p for p in pairs if p.symbol == "BTC").liquidity_usd_24h == 1_600_000_000.0


def test_polymarket_dedupes_and_dates():
    pairs = fetch_polymarket(_fake_get, pages=1)
    assert {p.symbol for p in pairs} == {"0xaaa", "0xbbb"}     # duplicate conditionId collapsed
    aaa = next(p for p in pairs if p.symbol == "0xaaa")
    assert aaa.asset_class == "prediction" and aaa.listed_at is not None and aaa.delisted_at is not None


def test_ibkr_curated_is_tiered():
    pairs = ibkr_curated_pairs()
    # All are curated; asset_class is equity OR futures (expanded universe includes futures + EU equities)
    assert all(p.source == "curated" and p.asset_class in ("equity", "futures") for p in pairs)
    # Key equities present
    assert {p.symbol for p in pairs} >= {"SPY", "AAPL", "NVDA"}
    assert next(p for p in pairs if p.symbol == "SPY").tier_hint == 0
    # Futures carry a multiplier; equities/ETFs do not
    futures = [p for p in pairs if p.instrument_type == "future"]
    assert futures, "expected futures pairs in the IBKR universe"
    assert all(p.multiplier is not None and p.multiplier > 0 for p in futures)
    equity_pairs = [p for p in pairs if p.instrument_type in ("equity", "etf")]
    assert all(p.multiplier is None for p in equity_pairs)
    # ~200+ total instruments
    assert len(pairs) >= 200


# ---------------------------------------------------------------------------------------------------------------
# Ranking + tiering — deterministic, measured-first, curated keeps its hint.
# ---------------------------------------------------------------------------------------------------------------
def test_rank_and_tier_is_deterministic_and_measured_first():
    pairs = (
        fetch_binance_spot(_fake_get) + fetch_binance_perp(_fake_get)
        + fetch_hyperliquid(_fake_post) + ibkr_curated_pairs()
    )
    ranked = rank_and_tier(pairs, tier0_n=3, tier1_n=6)
    measured = [p for p in ranked if p.liquidity_usd_24h > 0]
    # Measured pairs are rank-ordered by liquidity desc (perp BTC 8e9 is the deepest).
    assert measured[0].symbol == "BTCUSDT" and measured[0].venue == "binanceperp"
    assert [p.rank for p in measured] == sorted(p.rank for p in measured)
    assert all(measured[i].liquidity_usd_24h >= measured[i + 1].liquidity_usd_24h for i in range(len(measured) - 1))
    # Top-3 measured → tier 0.
    assert all(p.tier == 0 for p in measured[:3])
    # Curated equities keep their tier_hint regardless of (zero) liquidity.
    spy = next(p for p in ranked if p.symbol == "SPY")
    assert spy.tier == 0 and spy.liquidity_usd_24h == 0.0
    # Determinism: re-rank → identical id→rank map.
    again = rank_and_tier(pairs, tier0_n=3, tier1_n=6)
    assert {p.id: p.rank for p in ranked} == {p.id: p.rank for p in again}


# ---------------------------------------------------------------------------------------------------------------
# Vision survivorship — historical superset, delisted diff, listed/delisted windows.
# ---------------------------------------------------------------------------------------------------------------
def test_vision_delisted_backfill_windows():
    # Current TRADING set has BTCUSDT only → LUNAUSDT + FTTUSDT are delisted.
    delisted = build_binance_vision_delisted({"BTCUSDT"}, get_text=_fake_get_text, quotes=("USDT",))
    by = {p.symbol: p for p in delisted}
    assert set(by) == {"LUNAUSDT", "FTTUSDT"}
    luna = by["LUNAUSDT"]
    assert luna.active is False and luna.source == "vision"
    assert luna.listed_at == datetime(2020, 8, 1, tzinfo=UTC)
    assert luna.delisted_at == datetime(2022, 6, 1, tzinfo=UTC)   # last month 2022-05 → window ends next-month-1st


def test_build_universe_with_vision_delisted():
    result = build_universe(
        get=_fake_get, post=_fake_post, get_text=_fake_get_text,
        include_curated=True, vision_delisted=True, delisted_quotes=("USDT",),
    )
    assert result.delisted == 2
    assert result.per_venue.get("binance", 0) >= 3   # spot live + delisted vision rows
    assert "binanceperp" in result.per_venue and "hyperliquid" in result.per_venue
    # Every ranked pair carries a tier.
    assert all(p.tier is not None for p in result.pairs)


# ---------------------------------------------------------------------------------------------------------------
# Persistence + the DB-backed liquidity source + the PIT calendar.
# ---------------------------------------------------------------------------------------------------------------
def _store(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/u.sqlite3", openrouter_api_key=None, _env_file=None))
    store.migrate()
    return store


def test_persist_and_load_universe_is_idempotent(tmp_path):
    store = _store(tmp_path)
    result = build_universe(get=_fake_get, post=_fake_post, include_curated=True)
    n1 = persist_universe(store, result.pairs)
    n2 = persist_universe(store, result.pairs)   # re-run upserts, no duplicate rows
    assert n1 == n2 == len(result.pairs)
    total = store.row("SELECT count(*) AS c FROM universe_pairs")["c"]
    assert total == len(result.pairs)

    rows = load_universe(store)
    assert rows and rows[0].liquidity_usd_24h >= rows[-1].liquidity_usd_24h  # ranked deepest-first
    crypto = load_universe(store, asset_class="crypto")
    assert crypto and all(r.asset_class == "crypto" for r in crypto)
    perps = load_universe(store, instrument_type="perp")
    assert perps and all(r.instrument_type == "perp" for r in perps)
    tier0 = load_universe(store, tier=0)
    assert tier0 and all(r.tier == 0 for r in tier0)


def test_universe_symbols_falls_back_when_empty(tmp_path):
    store = _store(tmp_path)   # migrated but unpopulated
    from cosmu.data.universe import PERP_UNIVERSE

    assert universe_symbols(store) == list(PERP_UNIVERSE)   # empty table → static fallback
    persist_universe(store, build_universe(get=_fake_get, post=_fake_post, include_curated=False).pairs)
    syms = universe_symbols(store, asset_class="crypto")
    assert syms and syms != list(PERP_UNIVERSE)             # now DB-ranked


def test_pit_calendar_from_universe_pairs(tmp_path):
    store = _store(tmp_path)
    result = build_universe(
        get=_fake_get, post=_fake_post, get_text=_fake_get_text, vision_delisted=True, include_curated=False,
    )
    persist_universe(store, result.pairs)
    cal = UniverseCalendar.from_universe_pairs(store, venue="binance", asset_class="crypto")
    # LUNAUSDT was tradable in 2021 but NOT in 2026 — the survivorship fix.
    assert cal.is_eligible("LUNAUSDT", datetime(2021, 6, 1, tzinfo=UTC))
    assert not cal.is_eligible("LUNAUSDT", datetime(2026, 1, 1, tzinfo=UTC))
    # An empty table → empty calendar (no crash, nothing excluded).
    empty = UniverseCalendar.from_universe_pairs(_store(tmp_path / "x"))
    assert empty.eligible(datetime(2026, 1, 1, tzinfo=UTC)) == []
