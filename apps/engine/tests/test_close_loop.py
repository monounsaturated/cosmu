# Closing the autonomous loop: Finder survivors → capped-Kelly allocator funds the single pooled paper Wallet →
# master/portfolio holds positions + marks-to-market. GET /portfolio reads REAL persisted rows (no fixtures).

from __future__ import annotations

from fastapi.testclient import TestClient

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.orchestrator.loop import fund_wallet_from_survivors
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


def test_survivors_fund_the_wallet_and_open_real_positions(tmp_path):
    store = _store(tmp_path)
    fb = _FixtureBars()
    report = StrategyFinder(settings=store.settings, store=store, market_data=fb).find(seed_orb_fvg_spec(), max_variants=10)
    assert report.promoted >= 1   # at least one survivor to fund

    funding = fund_wallet_from_survivors(store, market_data=fb)
    assert funding.survivors >= 1
    assert funding.funded >= 1
    # capped-Kelly: each funded weight is <= the quarter-Kelly cap, sum <= 1
    weights = [a.weight for a in funding.allocations if a.weight > 0]
    assert weights and all(0 < w <= 0.25 + 1e-9 for w in weights) and sum(weights) <= 1 + 1e-9
    # real positions opened in the Wallet (no fabricated numbers)
    positions = store.rows("SELECT COUNT(*) AS n FROM positions WHERE CAST(qty AS REAL) != 0")[0]["n"]
    assert positions >= 1
    # a marked snapshot was written
    assert store.rows("SELECT COUNT(*) AS n FROM portfolio_snapshots")[0]["n"] >= 1


def test_portfolio_endpoint_reads_real_rows(tmp_path):
    store = _store(tmp_path)
    fb = _FixtureBars()
    StrategyFinder(settings=store.settings, store=store, market_data=fb).find(seed_orb_fvg_spec(), max_variants=10)
    fund_wallet_from_survivors(store, market_data=fb)

    import cosmu.api.app as app_module

    app_module.store = store  # point the API at the funded store
    with TestClient(app_module.app) as client:
        resp = client.get("/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        # the allocation list reflects real open positions (notional-weighted), not a fixture
        assert isinstance(body["allocation"], list)
        assert body["equity_curve"]  # snapshots exist


def test_empty_wallet_is_honest_not_fabricated(tmp_path):
    store = _store(tmp_path)   # no survivors persisted
    funding = fund_wallet_from_survivors(store, market_data=_FixtureBars())
    assert funding.survivors == 0 and funding.funded == 0
    # no positions invented; equity falls back to bankroll honestly
    assert store.rows("SELECT COUNT(*) AS n FROM positions WHERE CAST(qty AS REAL) != 0")[0]["n"] == 0
