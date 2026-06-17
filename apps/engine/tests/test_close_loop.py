# Closing the autonomous loop: Finder survivors → each opens its OWN standalone paper track (no pooled
# wallet, no cross-track competition) → master/portfolio holds positions + marks-to-market. GET /overview reads
# the REAL persisted aggregate read-out (Σ of tracks), no fixtures.

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from fastapi.testclient import TestClient

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.orchestrator.loop import fund_tracks_from_survivors


def _significant_edge_market(n: int = 300, seed: int = 5) -> dict[str, list[Bar]]:
    """A deterministic market bearing a GENUINELY SIGNIFICANT edge — a strong, tight-noise trend whose
    per-observation Sharpe survives the finder's HONEST multiple-testing deflation, so the close-the-loop path
    has a real survivor to fund. (The modest `edge_bearing_screen_market` fixture deliberately does NOT clear
    honest deflation — see test_finder_honesty — so it can no longer stand in for a fundable winner here.)

    NOTE: it is a relentless bull, so this long-only momentum edge does NOT beat buy-and-hold — the caller opts
    the beat-BnH gate out, as the funding-plumbing test it backs is orthogonal to that gate (covered separately)."""
    rng = random.Random(seed)
    base = dt.datetime(2022, 1, 1, tzinfo=dt.UTC)
    factor = [rng.gauss(0, 0.004) for _ in range(n)]  # one shared path → correlated, realistic symbols
    out: dict[str, list[Bar]] = {}
    for k, (sym, p0) in enumerate(
        {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0, "BNBUSDT": 300.0, "SOLUSDT": 25.0, "XRPUSDT": 0.5}.items()
    ):
        bars = []
        p = p0
        for i in range(n):
            drift = 0.008 if i % 100 < 78 else -0.001  # strong bull with regular pullbacks (regime breadth)
            r = drift + 0.95 * factor[i] + rng.gauss(0, 0.0006 * (1 + k * 0.1))
            o = p
            p = max(1e-6, p * (1 + r))
            hi = max(o, p) * (1 + abs(rng.gauss(0, 0.001)))
            lo = min(o, p) * (1 - abs(rng.gauss(0, 0.001)))
            bars.append(Bar(ts=base + dt.timedelta(days=i), open=Decimal(str(o)), high=Decimal(str(hi)),
                            low=Decimal(str(lo)), close=Decimal(str(p)), volume=Decimal("5000000")))
        out[sym] = bars
    return out


class _FixtureBars:
    # Significant-edge offline market (5 catalog symbols) — a fundable winner survives the finder's honest
    # deflation, exercising the survivor → standalone-track → real-position path end-to-end.
    def __init__(self) -> None:
        self._by = _significant_edge_market()
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _store(tmp_path, *, require_beat_buy_and_hold: bool = True) -> Store:
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/loop.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=require_beat_buy_and_hold),
        )
    )


def test_survivors_open_standalone_tracks_and_real_positions(tmp_path):
    # This exercises the FUNDING PLUMBING (survivor → standalone track → real position → mark), which is
    # orthogonal to the beat-buy-and-hold gate. The significant-edge fixture is a relentless bull, so no long-only
    # strategy out-returns simply HOLDING the basket — the beat-BnH gate (covered by test_beat_buy_and_hold.py)
    # correctly refuses to fund it. Opt that one gate out here so a real survivor reaches the plumbing under test.
    store = _store(tmp_path, require_beat_buy_and_hold=False)
    fb = _FixtureBars()
    report = StrategyFinder(settings=store.settings, store=store, market_data=fb).find(seed_orb_fvg_spec(), max_variants=10)
    assert report.promoted >= 1   # at least one survivor to fund

    funding = fund_tracks_from_survivors(store, market_data=fb)
    assert funding.survivors >= 1
    assert funding.funded >= 1
    # each survivor proves on its OWN standalone track — funded count == tracks registered (no pooled competition)
    assert funding.funded == len(funding.funded_tracks)
    # H2 (deep review): funding REGISTERS the track FLAT — a real zero-qty registration row, never a static
    # long. The track's first position is opened by the paper executor when ITS OWN entry signal fires.
    rows = store.rows("SELECT qty FROM positions WHERE strategy_version_id IS NOT NULL")
    assert len(rows) >= 1
    assert all(Decimal(str(r["qty"])) == 0 for r in rows)
    # a marked snapshot was written
    assert store.rows("SELECT COUNT(*) AS n FROM portfolio_snapshots")[0]["n"] >= 1


def test_overview_endpoint_reads_real_rows(tmp_path):
    store = _store(tmp_path)
    fb = _FixtureBars()
    StrategyFinder(settings=store.settings, store=store, market_data=fb).find(seed_orb_fvg_spec(), max_variants=10)
    fund_tracks_from_survivors(store, market_data=fb)

    import cosmu.api.app as app_module

    app_module.store = store  # point the API at the funded store
    with TestClient(app_module.app) as client:
        resp = client.get("/overview")
        assert resp.status_code == 200
        body = resp.json()
        # the aggregate read-out is the Σ of standalone tracks — a curve, NOT a pooled allocation list
        assert "allocation" not in body
        assert body["equity_curve"]  # snapshots exist


def test_empty_state_is_honest_not_fabricated(tmp_path):
    store = _store(tmp_path)   # no survivors persisted
    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    assert funding.survivors == 0 and funding.funded == 0
    # no positions invented; equity falls back to bankroll honestly
    assert store.rows("SELECT COUNT(*) AS n FROM positions WHERE CAST(qty AS REAL) != 0")[0]["n"] == 0


# --- ASSET-AWARE FUNDING ----------------------------------------------------------------------------------------
# The funder must route each gate-passed survivor to ITS OWN asset class's venue/symbol (read from the spec), not
# hardcode binance/crypto. An equity survivor must NEVER get a Binance crypto position (mislabeled + mispriced); a
# survivor whose asset class has no funding venue wired must be SKIPPED, not forced onto crypto.

class _FlatBars:
    """Deterministic, offline price provider keyed by symbol — one flat close per symbol, no network. Serves BOTH
    the crypto leg (Binance) and the equity leg (Yahoo) of a PricingRouter so the funder resolves real prices for
    every asset class without touching the wire."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        px = self._prices.get(symbol)
        if px is None:
            return []
        p = Decimal(str(px))
        return [Bar(ts=dt.datetime(2024, 1, 1, tzinfo=dt.UTC), open=p, high=p, low=p, close=p, volume=Decimal("1"))]


def _persist_survivor(store: Store, *, name: str, asset_classes: list[str], venues: list[str]) -> str:
    """Persist a gate-passed paper survivor (strategies + strategy_versions + screen backtest + track) whose
    spec declares the given asset class/venues — the exact rows fund_tracks_from_survivors reads. Returns the
    version_id."""
    now = "2024-01-01T00:00:00Z"
    strategy_id = store.insert("strategies", {"name": name, "thesis": "t", "origin": "finder", "created_at": now})
    version_id = store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id,
            "parent_id": None,
            "spec": {
                "name": name,
                "rationale": "r",
                "universe": {"venues": venues, "asset_classes": asset_classes, "min_instruments": 1},
                "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 10},
                "entry": [], "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}},
                "risk": {}, "param_space": {}, "direction": 1,
            },
            "generated_code": "# test", "code_hash": f"hash-{name}", "params": {},
            "mutation_operator": None, "mutation_rationale": None, "origin": "finder",
            "status": "paper", "created_at": now, "killed_at": None, "kill_reason": None,
        },
    )
    store.insert(
        "tracks",
        {"strategy_version_id": version_id, "starting_capital": "10000", "equity": "10000",
         "return_pct": "0", "updated_at": now},
    )
    store.insert(
        "backtests",
        {"strategy_version_id": version_id, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5",
         "sortino": "1.5", "deflated_sharpe": "1.5", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 30,
         "pbo": "0.0", "trials_counted": 1, "regime_label": "mixed", "folds_positive": 5,
         "passed_gates": 1, "holdout_passed": 1, "created_at": now},
    )
    return version_id


def test_equity_survivor_never_gets_a_binance_crypto_position(tmp_path):
    # BUG GUARD: a gate-passed EQUITY survivor must NOT be forced onto a Binance crypto symbol (mislabeled +
    # mispriced). It must route to its OWN asset class's venue (equity → IBKR) and an equity instrument.
    store = _store(tmp_path)
    equity_vid = _persist_survivor(store, name="EquityMomo", asset_classes=["equity"], venues=["ibkr"])

    from cosmu.orchestrator.loop import PricingRouter
    from cosmu.spine.venue import default_catalog

    cat = default_catalog()
    # One flat provider serving both legs: any IBKR equity instrument (SPY/QQQ/...) + the Binance crypto symbols.
    prices = {i.symbol: 400.0 for i in cat.instruments if i.venue_id == "ibkr" and i.asset_class == "equity"}
    prices.update({i.symbol: 30000.0 for i in cat.instruments if i.venue_id == "binance" and i.asset_class == "crypto"})
    bars = _FlatBars(prices)
    router = PricingRouter(cat, crypto=bars, equity=bars)

    funding = fund_tracks_from_survivors(store, catalog=cat, router=router)
    assert funding.survivors == 1 and funding.funded == 1

    rows = store.rows(
        "SELECT symbol, venue, instrument_id FROM positions WHERE strategy_version_id = ?",
        (equity_vid,),
    )
    assert len(rows) == 1
    pos = rows[0]
    # registered (flat) on the EQUITY venue/instrument, NOT a Binance crypto symbol. Equity now funds on ALPACA
    # (the venue with a real exec adapter — see orchestrator/loop._FUNDING_VENUE_BY_ASSET_CLASS), so the instrument
    # is the Alpaca-mirrored equity, never IBKR (data-only, no live leg) and never a crypto symbol.
    crypto_symbols = {i.symbol for i in cat.instruments if i.venue_id == "binance" and i.asset_class == "crypto"}
    equity_symbols = {i.symbol for i in cat.instruments if i.venue_id == "alpaca" and i.asset_class == "equity"}
    assert pos["symbol"] not in crypto_symbols, f"equity survivor mislabeled onto a Binance crypto symbol: {pos['symbol']}"
    assert pos["symbol"] in equity_symbols
    assert pos["instrument_id"].endswith("-alpaca")


def test_survivor_with_no_funding_venue_is_skipped_not_forced_onto_crypto(tmp_path):
    # A survivor whose asset class has NO funding venue wired (prediction markets have no execution path) must be
    # SKIPPED rather than mislabeled onto a Binance crypto symbol.
    store = _store(tmp_path)
    pred_vid = _persist_survivor(store, name="PredMarket", asset_classes=["prediction"], venues=["polymarket"])

    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    assert funding.survivors == 0   # not routable → not counted as a fundable survivor
    assert funding.funded == 0
    assert store.rows(
        "SELECT COUNT(*) AS n FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (pred_vid,)
    )[0]["n"] == 0


def test_crypto_survivors_fund_on_their_screened_universe(tmp_path):
    """H3 (deep review): a crypto survivor paper-trades on a symbol its gate evidence actually covered — the
    screened universe (CRYPTO_SCREEN_UNIVERSE), round-robined ACROSS that pool for multiple survivors — never
    an arbitrary catalog rotation onto an instrument it was never screened on."""
    from cosmu.evolution.loop import CRYPTO_SCREEN_UNIVERSE

    store = _store(tmp_path)
    vid_a = _persist_survivor(store, name="CryptoA", asset_classes=["crypto"], venues=["binance"])
    vid_b = _persist_survivor(store, name="CryptoB", asset_classes=["crypto"], venues=["binance"])

    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    assert funding.funded == 2

    rows = store.rows(
        "SELECT symbol FROM positions WHERE strategy_version_id IN (?, ?)", (vid_a, vid_b)
    )
    symbols = {r["symbol"] for r in rows}
    assert symbols <= set(CRYPTO_SCREEN_UNIVERSE), f"funded outside the screened universe: {symbols}"
    assert len(symbols) == 2  # round-robin spreads survivors across the screened pool, not onto one symbol


def test_crypto_survivor_still_routes_to_binance(tmp_path):
    # NO REGRESSION: a crypto survivor must still fund a Binance crypto position exactly as before.
    store = _store(tmp_path)
    crypto_vid = _persist_survivor(store, name="CryptoMomo", asset_classes=["crypto"], venues=["binance"])

    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    assert funding.survivors == 1 and funding.funded == 1

    rows = store.rows(
        "SELECT venue, instrument_id FROM positions WHERE strategy_version_id = ?",
        (crypto_vid,),
    )
    assert len(rows) == 1
    assert rows[0]["instrument_id"].endswith("-binance")
