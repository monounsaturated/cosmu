# The Strategy Finder: grid-search a spec's param space → screen each variant deterministically → rank by
# profit_factor (displayed) while the Gate + FDR + one-shot holdout decide promotion (no top-of-leaderboard
# picking) → every variant counts as a trial → winners persisted to the config library (origin='finder').

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, build_grid
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
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/finder.sqlite3", openrouter_api_key=None))


def _finder(tmp_path) -> StrategyFinder:
    store = _store(tmp_path)
    return StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())


def test_build_grid_spans_space_and_is_bounded():
    spec = seed_orb_fvg_spec()
    grid = build_grid(spec, max_variants=16)
    assert 1 <= len(grid) <= 16
    # every variant resolves every param in the space (no missing params → compiler would reject)
    for v in grid:
        assert set(v.params) == set(spec.param_space)
    # config tags are stable + unique per param combination
    tags = [v.config_tag for v in grid]
    assert len(set(tags)) == len(tags)


def test_finder_screens_ranks_by_profit_factor_and_counts_trials(tmp_path):
    finder = _finder(tmp_path)
    report = finder.find(seed_orb_fvg_spec(), max_variants=10)
    assert report.screened > 0
    # leaderboard is the gate-passers sorted by profit_factor descending (displayed secondary metric)
    pfs = [r.profit_factor for r in report.leaderboard]
    assert pfs == sorted(pfs, reverse=True)
    # EVERY screened variant was registered as a trial (deflation validity) — choke point, no bypass
    n_trials = finder.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"]
    assert n_trials == report.screened


def test_finder_persists_config_library_and_holdout_before_promotion(tmp_path):
    finder = _finder(tmp_path)
    report = finder.find(seed_orb_fvg_spec(), max_variants=10)
    # config library: finder-origin versions persisted, tagged with a config_tag in params
    versions = finder.store.rows("SELECT params FROM strategy_versions WHERE origin = 'finder'")
    assert versions and all('"config_tag"' in v["params"] for v in versions)
    # promotion requires the one-shot holdout, never raw in-sample PF order
    assert all(s.promoted and s.holdout_passed for s in report.survivors)
    # one-shot holdout ledger recorded for gate-passers (cannot silently re-pick)
    if report.gate_passed:
        assert finder.store.rows("SELECT COUNT(*) AS n FROM holdout_ledger")[0]["n"] >= 1


def test_finder_is_idempotent(tmp_path):
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)
    before = finder.store.rows("SELECT COUNT(*) AS n FROM strategy_versions WHERE origin = 'finder'")[0]["n"]
    finder.find(seed_orb_fvg_spec(), max_variants=8)  # same grid → same code_hashes → no new versions
    after = finder.store.rows("SELECT COUNT(*) AS n FROM strategy_versions WHERE origin = 'finder'")[0]["n"]
    assert after == before
