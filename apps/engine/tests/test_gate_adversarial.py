# Adversarial validation of the discovery → Gate → FDR path, end-to-end through the FINDER.
#
# The module-level controls live elsewhere and are NOT duplicated here:
#   - test_adversarial_validation.py  pins the GATE VARIANTS (single-signal · ablation · cross-asset) on
#     no-edge / shuffled / known-edge inputs.
#   - test_finder_permutation_null.py (#51) pins the finder PROMOTING 0 on a price-label permutation null.
#
# What neither asserts — and what this module adds — is the PAIRED A/B that proves the finder's full
# discovery+promotion pipeline (grid → screen on bars → register every trial → honest deflation →
# cluster-dedupe → BH-FDR → purged/embargoed holdout → promote) DISCRIMINATES:
#
#   (1) NO-EDGE  (permutation-null bars, every signal→return relationship destroyed) → 0 survivors AND
#       0 gate-passers. Guards the multiple-testing / overfit leak from the discovery side.
#   (2) KNOWN-EDGE (a real, simple momentum edge baked into the bars themselves) → ≥ 1 survivor promoted.
#       Guards the opposite failure: a gate so strict NOTHING can ever pass (the nulls in (1) and in #51
#       would then "reject" vacuously and prove nothing).
#
# Both arms run the SAME finder, SAME seed spec, SAME variant cap and SAME gate settings — only the bars
# differ — so the contrast isolates the bars' edge as the single cause of promotion. Everything is
# deterministic, offline (the market provider is injected; conftest blocks real sockets), and LLM-free.

from __future__ import annotations

import pytest

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.research.fixtures import edge_bearing_screen_market, permutation_null_market

# One variant cap for BOTH arms so the only difference between them is the bars' edge, not grid density
# (density is its own axis, exercised by test_finder_honesty.py). Kept modest so the paired run stays fast.
_MAX_VARIANTS = 64


class _Bars:
    """Inject a fixed market dict as the finder's provider — fully offline, no network, no cache."""

    def __init__(self, market: dict[str, list[Bar]]):
        self._m = market

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._m.get(symbol, next(iter(self._m.values())))[-limit:]


def _finder(tmp_path, market: dict[str, list[Bar]], name: str) -> StrategyFinder:
    # No openrouter_api_key → the whole path runs offline (CI has no keys; the LLM is never in this path).
    # These probe STATISTICAL edge-vs-noise discrimination (DSR/PBO/FDR/holdout). The edge fixtures are strong
    # uptrends where holding the basket out-returns any long-only strategy, so the beat-buy-and-hold gate (a
    # separate concern, covered by test_beat_buy_and_hold.py) would mask the statistical signal — and disabling it
    # only RELAXES promotion, so the no-edge null arms must still reject on the statistics alone (the sharper claim).
    store = Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/{name}.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=False),
        )
    )
    return StrategyFinder(settings=store.settings, store=store, market_data=_Bars(market))


# ---- (1) NO-EDGE: permutation-null bars → the finder promotes nothing -------------------------------
# The companion to #51 from the FINDER PROMOTION angle. permutation_null_market preserves each symbol's
# marginal return distribution (drift, vol, fat tails) but PERMUTES the returns in time, so momentum /
# mean-reversion / breakout — everything a TA grid could monetize — is gone. A non-leaky finder promotes
# 0 and flags 0 gate-passers no matter how tempting individual variants look in-sample. `correlated=True`
# is the adversarial regime where a naive trial count would inflate.


@pytest.mark.parametrize("correlated,seed", [(False, 13), (True, 13), (True, 29)])
def test_no_edge_finder_promotes_zero(tmp_path, correlated, seed):
    spec = seed_orb_fvg_spec()
    market = permutation_null_market(correlated=correlated, n=600, seed=seed)
    rep = _finder(tmp_path, market, name=f"noedge-{int(correlated)}-{seed}").find(
        spec, max_variants=_MAX_VARIANTS, persist=False
    )
    assert rep.screened > 0  # the grid actually ran (not a vacuous empty pass)
    assert rep.gate_passed == 0, f"no-edge bars produced {rep.gate_passed} gate-passers — LEAK"
    assert rep.promoted == 0, f"no-edge bars produced {rep.promoted} survivors — LEAK"
    # The leaderboard's best deflated Sharpe stays under the promotion bar (no spurious near-miss either).
    bar = float(Settings(openrouter_api_key=None).gates.min_deflated_sharpe_prob)
    assert max((r.deflated_sharpe for r in rep.leaderboard), default=0.0) < bar


# ---- (2) KNOWN-EDGE: real momentum baked into the bars → the finder promotes a survivor --------------
# The positive control. edge_bearing_screen_market builds bars with positively autocorrelated returns (a
# real momentum signal) — NO synthetic return is injected into the backtest; the deterministic
# screen/scorer/gate judge the bars honestly. If this ever promotes 0, the nulls above (and #51) are
# meaningless: a finder that can never promote trivially "rejects" every null.


def test_known_edge_finder_promotes_a_survivor(tmp_path):
    spec = seed_orb_fvg_spec()
    market = edge_bearing_screen_market()
    rep = _finder(tmp_path, market, name="edge").find(spec, max_variants=_MAX_VARIANTS, persist=False)
    assert rep.gate_passed >= 1, "known-edge bars passed 0 variants — the gate may be over-strict"
    assert rep.promoted >= 1, "known-edge bars promoted 0 survivors — the gate may be over-strict"
    # A promoted survivor must carry through BOTH halves of the promotion contract: cohort BH-FDR
    # (promoted) AND the purged/embargoed one-shot holdout (holdout_passed).
    assert all(s.promoted and s.holdout_passed for s in rep.survivors)


# ---- (3) Discrimination: the SAME finder separates edge from no-edge ---------------------------------
# The two arms above, run as ONE paired comparison with identical finder config — only the bars differ.
# This is the sharp anti-leak / anti-vacuity statement: promotion tracks the bars' edge, full stop.


def test_finder_discriminates_edge_from_noise(tmp_path):
    spec = seed_orb_fvg_spec()
    edge = _finder(tmp_path, edge_bearing_screen_market(), name="disc-edge").find(
        spec, max_variants=_MAX_VARIANTS, persist=False
    )
    noise = _finder(tmp_path, permutation_null_market(correlated=True, n=600, seed=13), name="disc-noise").find(
        spec, max_variants=_MAX_VARIANTS, persist=False
    )
    assert edge.promoted >= 1 and noise.promoted == 0
    assert edge.gate_passed > noise.gate_passed == 0
