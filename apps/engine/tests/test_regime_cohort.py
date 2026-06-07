# The regime-gate cohort: a leak-controlled, returns-based BH-FDR family (regime-gate vs flat vs price-momentum
# vs shuffle-placebo) judged on a REAL purged+embargoed holdout. Smoke + causality coverage with NO network and
# NO durable-store writes (persist defaults False).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research.regime_cohort import _gated_returns, run_regime_cohort
from cosmu.data.market import Bar


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/regime.sqlite3", openrouter_api_key=None))


def _bars(closes: list[float]) -> list[Bar]:
    t0 = datetime(2015, 1, 1, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("0")))
    return out


def _cycle(blocks: int, block_len: int, daily: float) -> list[float]:
    closes, p = [], 100.0
    for b in range(blocks):
        d = daily if b % 2 == 0 else -daily
        for i in range(block_len):
            p *= 1 + d + (0.003 if i % 2 == 0 else -0.003)
            closes.append(p)
    return closes


def test_gated_returns_are_strictly_causal():
    """The return INTO bar j (rets[j-1]) is sized by the exposure AS OF bar j-1 — never bar j. A future-only
    exposure spike must not touch earlier gated returns."""
    rets = [0.01, -0.02, 0.03, -0.01, 0.02]
    exp = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}
    base = _gated_returns(rets, exp, fee_frac=0.0)
    exp_future = dict(exp)
    exp_future[4] = 0.0  # change only the LAST bar's exposure
    after = _gated_returns(rets, exp_future, fee_frac=0.0)
    assert base[:-1] == after[:-1]  # earlier gated returns unchanged → no look-ahead


def test_turnover_fee_charged_on_exposure_change():
    rets = [0.0, 0.0, 0.0]
    exp = {0: 0.0, 1: 1.0, 2: 1.0}  # one flip 0->1 between bar0 and bar1
    out = _gated_returns(rets, exp, fee_frac=0.001)
    # return into bar1 (rets[0]) sized by exp[0]=0 (no flip charged yet, prev=None); into bar2 (rets[1]) sized by
    # exp[1]=1, turnover |1-0|=1 → -0.001; into bar3 (rets[2]) sized by exp[2]=1, no change.
    assert out == [0.0, -0.001, 0.0]


def test_cohort_runs_and_reports_four_members_without_persisting(tmp_path):
    bars = _bars(_cycle(8, 90, 0.01))  # ~720 bars, multi-cycle
    store = _store(tmp_path)
    rep = run_regime_cohort("TEST", bars, store, fee_bps=2.0, ppy=252)  # persist defaults False
    names = {m.name for m in rep.members}
    assert names == {"regime-gate-markov", "flat-buy-and-hold", "disc-price-momentum-gate", "disc-shuffle-placebo"}
    assert rep.verdict in ("PASS", "FAIL", "FAIL-DISCONFIRMED", "ABSTAIN")
    assert set(rep.disconfirmers) == {"beat_buy_and_hold_riskadj", "beat_naive_price_momentum", "shuffle_placebo"}
    # persist=False → the durable store is untouched (this run's store is the tempfile; gate_verdicts stays empty)
    assert store.rows("SELECT COUNT(*) AS n FROM gate_verdicts")[0]["n"] == 0
