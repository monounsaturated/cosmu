# The headline adversarial proof for the finder-honesty fix: a PERMUTATION NULL (shuffled return labels) run
# through the FULL finder grid must promote 0 survivors AND flag 0 gate-passers. The marginal return
# distribution is preserved but every signal→return relationship is destroyed, so there is NO real edge — yet
# many variants still LOOK profitable in-sample by chance. An honest finder (true trial count + correlation
# haircut + real CSCV-PBO + purged/embargoed holdout + per-symbol trades + dedupe-before-FDR) rejects all of
# them. A survivor — or even a gate-pass — here is a significance leak, never a test to relax.
#
# The leak is a DENSITY effect: the pre-fix finder deflated against ~len(param_space) with the cross-sectional
# Sharpe variance taken over the WHOLE grid, so as near-duplicate variants piled in the observed variance
# collapsed → the benchmark SR0 fell → the Deflated Sharpe ROSE. Measured on this exact null at n=800 /
# correlated / 256 variants, the pre-#35 finder flagged 56 pure-noise variants as gate-passing edges; the
# honest finder flags 0. The guard below therefore runs IN that leak zone — a thinner grid would pass
# vacuously (the variance hasn't collapsed yet) and catch no regression.
#
# Complements test_finder_honesty.py (which pins each closed leak in isolation): this exercises the closed
# leaks END-TO-END on pure noise, at the grid density where the leak actually bit.

from __future__ import annotations

import pytest

from cosmu.config.settings import Settings
from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, build_grid
from cosmu.research.fixtures import permutation_null_market
from cosmu.spine.venue import default_catalog


class _Bars:
    def __init__(self, market: dict[str, list[Bar]]):
        self._m = market

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._m.get(symbol, next(iter(self._m.values())))[-limit:]


def _finder(tmp_path, market, name="null") -> StrategyFinder:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))
    return StrategyFinder(settings=store.settings, store=store, market_data=_Bars(market))


# ----------------------------------------------------------------- the null is not vacuous


@pytest.mark.parametrize("correlated", [False, True])
def test_permutation_null_actually_trades_and_tempts(correlated):
    # Guard against a vacuous pass: a null that promotes 0 only because nothing ever trades would prove
    # nothing. Here the grid DOES trade and a real chunk of variants look profitable in-sample (PF > 1), some
    # with enough trades to be gate-eligible — so the 0 below is the gate rejecting tempting-but-spurious
    # edges, not an empty backtest or a min_trades artifact.
    spec = seed_orb_fvg_spec()
    market = permutation_null_market(correlated=correlated, n=400, seed=13)
    venue = default_catalog().venue("binance")
    gates = Settings(openrouter_api_key=None).gates

    profitable_looking = 0
    gate_eligible_winners = 0
    grid = build_grid(spec, max_variants=128)
    for v in grid:
        d = run_strategy_backtest_detailed(spec, v.params, market, fee_bps=venue.taker_fee_bps)
        if float(d.metrics.profit_factor) > 1.0:
            profitable_looking += 1
            if d.metrics.num_trades >= gates.min_trades:
                gate_eligible_winners += 1
    assert profitable_looking >= 10  # a real chunk of variants look like winners in-sample (by chance)
    assert gate_eligible_winners >= 1  # …and some are profitable-looking AND trade enough to be gate-eligible


# ----------------------------------------------------------------- 0 survivors at the density the leak bit


def test_permutation_null_zero_survivors_in_the_leak_zone(tmp_path):
    # THE guard. n=800 / correlated / 256 variants is the regime where the pre-#35 finder leaked: it flagged
    # 56 pure-noise variants as gate-passing edges (and they fed the leaderboard + the refine-seed selection).
    # The honest finder flags 0 and promotes 0. If any honesty mechanism regresses — the true trial count, the
    # variance-over-representatives, the real CSCV-PBO, the purged holdout, per-symbol trades, or the
    # dedupe-before-FDR — gate_passed climbs back above 0 and this fails.
    spec = seed_orb_fvg_spec()
    market = permutation_null_market(correlated=True, n=800, seed=13)
    rep = _finder(tmp_path, market, name="leakzone").find(spec, max_variants=256, persist=False)
    assert rep.screened == 256  # every variant screened + registered as a trial (the true count)
    assert rep.gate_passed == 0  # not one spurious in-sample edge survives the honest deflation
    assert rep.promoted == 0  # noise in → nothing promoted out
    # even the densest noise grid's best leaderboard Deflated Sharpe stays far under the promotion bar
    bar = float(Settings(openrouter_api_key=None).gates.min_deflated_sharpe_prob)
    best = max((r.deflated_sharpe for r in rep.leaderboard), default=0.0)
    assert best < bar


# ----------------------------------------------------------------- robust across regimes + seeds (fast)


@pytest.mark.parametrize("correlated,seed", [(False, 13), (True, 29), (True, 101)])
def test_permutation_null_promotes_zero_across_regimes_and_seeds(tmp_path, correlated, seed):
    # Determinism + robustness: 0 survivors is not a single lucky seed or regime.
    spec = seed_orb_fvg_spec()
    market = permutation_null_market(correlated=correlated, n=400, seed=seed)
    rep = _finder(tmp_path, market, name=f"r-{int(correlated)}-{seed}").find(
        spec, max_variants=96, persist=False
    )
    assert rep.promoted == 0
    assert rep.gate_passed == 0
