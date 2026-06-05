# fix-1 (money-path): the deployed FarmLoop must deflate each candidate's Sharpe against EVERY hypothesis ever run
# (the global trial ledger), not just its own ~len(param_space) params. It registers every screened candidate as a
# trial (source="farmloop") and scores the whole cohort against one snapshot of that ledger — so a later cohort is
# deflated against all the earlier ones, and "author more candidates per tick" can no longer manufacture a winner.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import FarmLoop
from cosmu.knowledge.store import Store
from cosmu.master.trials import register_trial


class _FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def _fixture_bars(count: int = 420, start: Decimal = Decimal("100")) -> list[Bar]:
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = start
    bars: list[Bar] = []
    for idx in range(count):
        cycle = Decimal(idx % 18)
        move = Decimal("0.012") if cycle < 9 else Decimal("-0.009")
        if idx % 53 == 0:
            move -= Decimal("0.035")
        open_ = price
        close = (price * (Decimal("1") + move)).quantize(Decimal("0.0001"))
        high = max(open_, close) * Decimal("1.006")
        low = min(open_, close) * Decimal("0.994")
        bars.append(
            Bar(
                ts=ts + dt.timedelta(days=idx),
                open=open_,
                high=high.quantize(Decimal("0.0001")),
                low=low.quantize(Decimal("0.0001")),
                close=close,
                volume=Decimal("1000") + Decimal(idx),
            )
        )
        price = close
    return bars


def _store(path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{path}.sqlite3"))


def _loop(store: Store) -> FarmLoop:
    return FarmLoop(settings=store.settings, store=store, market_data=_FixtureProvider(_fixture_bars()))


def _best_deflated(summary) -> float:  # noqa: ANN001
    return max(e.deflated_sharpe for e in (summary.survivors + summary.graveyard))


def test_every_screened_candidate_is_registered_as_a_trial(tmp_path):
    # The trial ledger must hold exactly one row per screened candidate — otherwise the deflation count is wrong.
    store = _store(tmp_path / "a")
    summary = _loop(store).run_cohort(seed=7, cohort_size=40)
    assert summary.generated > 0
    trials_rows = store.row("SELECT COUNT(*) AS n FROM trials")["n"]
    assert trials_rows == summary.generated  # rowcount == screened
    assert {r["source"] for r in store.rows("SELECT DISTINCT source FROM trials")} == {"farmloop"}


def test_prior_global_trials_deflate_a_later_cohort(tmp_path):
    # Run an IDENTICAL cohort on two fresh stores. Store B's ledger is pre-seeded with the SAME trial-Sharpe
    # distribution as the cohort itself (duplicated), so B's count is several-fold higher while its Sharpe variance
    # is unchanged. More hypotheses ⇒ a higher expected-max-Sharpe benchmark ⇒ a strictly LOWER deflated Sharpe.
    # The pre-fix code (score() with no trials=) ignored the prior ledger entirely, so B would have EQUALLED A.
    store_a = _store(tmp_path / "a")
    a = _loop(store_a).run_cohort(seed=7, cohort_size=40)

    store_b = _store(tmp_path / "b")
    cohort_sharpes = [float(r["sharpe_per_obs"]) for r in store_a.rows("SELECT sharpe_per_obs FROM trials")]
    for _ in range(3):  # mirror the cohort's own trial distribution → variance preserved, count multiplied
        for s in cohort_sharpes:
            register_trial(store_b, s, source="prior")
    b = _loop(store_b).run_cohort(seed=7, cohort_size=40)

    assert b.generated == a.generated  # same seed + fixture ⇒ the cohort itself is identical
    # the GLOBAL ledger deflated the second cohort harder:
    assert _best_deflated(b) < _best_deflated(a)


def test_sequential_cohorts_accumulate_the_ledger(tmp_path):
    # Two cohorts on the SAME store: the ledger is monotonic and additive across cohorts (the trial counter
    # never resets per-cohort), so the second cohort genuinely deflates against the first.
    store = _store(tmp_path / "a")
    loop = _loop(store)
    a = loop.run_cohort(seed=7, cohort_size=40)
    after_first = store.row("SELECT COUNT(*) AS n FROM trials")["n"]
    b = loop.run_cohort(seed=11, cohort_size=40)
    after_second = store.row("SELECT COUNT(*) AS n FROM trials")["n"]
    assert after_first == a.generated
    assert after_second == a.generated + b.generated
