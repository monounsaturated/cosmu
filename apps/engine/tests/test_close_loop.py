# Closing the autonomous loop: Finder survivors → each opens its OWN standalone forward-test track (no pooled
# wallet, no cross-track competition) → master/portfolio holds positions + marks-to-market. GET /overview reads
# the REAL persisted aggregate read-out (Σ of tracks), no fixtures.

from __future__ import annotations

from fastapi.testclient import TestClient

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.orchestrator.loop import fund_tracks_from_survivors
from cosmu.research.fixtures import edge_bearing_screen_market


class _FixtureBars:
    # Small, fast offline market: 2 catalog symbols x ~280 edge-bearing bars (enough for the screen's 80-bar
    # floor + holdout split) so finder grids stay quick in CI.
    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
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
