# Closing the autonomous loop: Finder survivors → each opens its OWN standalone forward-test track (no pooled
# wallet, no cross-track competition) → master/portfolio holds positions + marks-to-market. GET /overview reads
# the REAL persisted aggregate read-out (Σ of tracks), no fixtures.

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from fastapi.testclient import TestClient

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.orchestrator.loop import fund_tracks_from_survivors


def _significant_edge_market(n: int = 300, seed: int = 5) -> dict[str, list[Bar]]:
    """A deterministic market bearing a GENUINELY SIGNIFICANT edge — a strong, tight-noise trend whose
    per-observation Sharpe survives the finder's HONEST multiple-testing deflation, so the close-the-loop path
    has a real survivor to fund. (The modest `edge_bearing_screen_market` fixture deliberately does NOT clear
    honest deflation — see test_finder_honesty — so it can no longer stand in for a fundable winner here.)"""
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


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/loop.sqlite3", openrouter_api_key=None))


def test_survivors_open_standalone_tracks_and_real_positions(tmp_path):
    store = _store(tmp_path)
    fb = _FixtureBars()
    report = StrategyFinder(settings=store.settings, store=store, market_data=fb).find(seed_orb_fvg_spec(), max_variants=10)
    assert report.promoted >= 1   # at least one survivor to fund

    funding = fund_tracks_from_survivors(store, market_data=fb)
    assert funding.survivors >= 1
    assert funding.funded >= 1
    # each survivor proves on its OWN standalone track — funded count == tracks opened (no pooled competition)
    assert funding.funded == len(funding.funded_tracks)
    # real positions opened (no fabricated numbers)
    positions = store.rows("SELECT COUNT(*) AS n FROM positions WHERE CAST(qty AS REAL) != 0")[0]["n"]
    assert positions >= 1
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
