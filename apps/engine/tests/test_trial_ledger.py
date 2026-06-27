# The HONEST trial-count ledger (master/trial_ledger): record EVERY look the BRUT sweeps take so the Gate's
# Deflated Sharpe can deflate against the TRUE decorrelated effective-N — not the per-combo grid count alone (the
# "scariest self-deception flaw", docs/reports/cross-disciplinary-playbook-2026-06-26.md bridge #2 + red-team #1).
# These pin: (1) every look is recorded into `trial_ledger` (NOT the legacy `trials` family-counter, which the
# brut path still leaves at 0); (2) effective_n decorrelates per family via the SAME scorer haircut; (3) the
# survivor recompute makes N honest WITHOUT touching a locked Gate constant.

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, reset_trial_ledger_cache, trial_ledger_available
from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob, effective_trials
from cosmu.master.trial_ledger import (
    Look,
    effective_n,
    honest_trial_stats,
    ledger_count,
    measure_family_rho,
    recompute_dsr_at_honest_n,
    record_look,
    record_looks,
)
from cosmu.master.trials import register_trial


def _store(tmp_path, name: str = "ledger") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _looks(n: int, base_sr: float = 0.05) -> list[Look]:
    return [Look(sharpe_per_obs=base_sr * (1 + i % 3), symbol=f"S{i}", venue="binance") for i in range(n)]


# --------------------------------------------------------------------------- recording


def test_record_looks_appends_rows(tmp_path):
    store = _store(tmp_path)
    assert ledger_count(store) == 0
    written = record_looks(store, lane="finder", family="fam-a", looks=_looks(7), rho_bar=0.3)
    assert written == 7
    assert ledger_count(store) == 7
    # The columns are persisted as given (lane/family/symbol/venue/sharpe/rho).
    row = store.row("SELECT lane, family, symbol, venue, rho_bar FROM trial_ledger LIMIT 1")
    assert row["lane"] == "finder" and row["family"] == "fam-a" and row["venue"] == "binance"
    assert float(row["rho_bar"]) == 0.3


def test_record_look_singular(tmp_path):
    store = _store(tmp_path)
    assert record_look(store, lane="research", family="f", sharpe_per_obs=0.1, symbol="BTC", venue="kraken") == 1
    assert ledger_count(store) == 1


def test_empty_looks_is_a_noop(tmp_path):
    store = _store(tmp_path)
    assert record_looks(store, lane="finder", family="f", looks=[]) == 0
    assert ledger_count(store) == 0


def test_record_is_schema_probe_gated(tmp_path):
    # On a table-less (pre-migration) schema, record_looks no-ops + returns 0; effective_n falls back to legacy.
    store = _store(tmp_path)
    with store.connect() as con:
        con.execute("DROP TABLE trial_ledger")
    reset_trial_ledger_cache()
    assert trial_ledger_available(store) is False
    assert record_looks(store, lane="finder", family="f", looks=_looks(5)) == 0
    assert ledger_count(store) == 0
    reset_trial_ledger_cache()  # leave the per-DSN memo clean for any later store on this path


# --------------------------------------------------------------------------- decorrelated effective-N


def test_effective_n_empty_is_zero(tmp_path):
    assert effective_n(_store(tmp_path)) == 0.0


def test_uncorrelated_family_counts_full(tmp_path):
    # rho_bar=None ⇒ no haircut ⇒ effective_n == raw count (the conservative / stricter direction).
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="f", looks=_looks(40), rho_bar=None)
    assert effective_n(store, family="f", include_legacy_trials=False) == 40.0


def test_correlated_family_collapses(tmp_path):
    # A perfectly-correlated family of K looks is ONE effective trial: K/(1+(K-1)*1) = 1.
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="f", looks=_looks(50), rho_bar=1.0)
    assert effective_n(store, family="f", include_legacy_trials=False) == effective_trials(50.0, 1.0)
    assert effective_n(store, family="f", include_legacy_trials=False) <= 1.0 + 1e-9


def test_effective_n_sums_per_family_decorrelated(tmp_path):
    # Two families, summed independently; each decorrelated by its OWN measured rho.
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="a", looks=_looks(20), rho_bar=0.5)
    record_looks(store, lane="farmloop", family="b", looks=_looks(10), rho_bar=0.0)
    expected = effective_trials(20.0, 0.5) + effective_trials(10.0, 0.0)
    assert effective_n(store, include_legacy_trials=False) == expected


def test_legacy_trials_folded_in(tmp_path):
    # The whole-machine count folds in the legacy `trials` rows (research/FDR lanes) as independent looks.
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="a", looks=_looks(10), rho_bar=0.0)
    for i in range(5):
        register_trial(store, 0.05, source="edge_gate", label=f"t{i}")
    assert effective_n(store, include_legacy_trials=False) == 10.0
    assert effective_n(store, include_legacy_trials=True) == 15.0


def test_honest_trial_stats_count(tmp_path):
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="f", looks=_looks(33), rho_bar=0.0)
    ts = honest_trial_stats(store, family="f")
    assert isinstance(ts, TrialStats)
    assert ts.count == 33
    assert ts.sr_correlation is None  # the haircut is already baked into the count — never haircut twice


# --------------------------------------------------------------------------- measure_family_rho


def test_measure_family_rho_detects_duplicates():
    stream = [((-1) ** i) * (0.01 + 0.001 * (i % 5)) for i in range(40)]
    assert measure_family_rho([list(stream), list(stream)]) >= 0.99  # identical streams ≈ 1.0
    assert measure_family_rho([list(stream)]) is None                 # need >= 2 streams
    assert measure_family_rho([]) is None


# --------------------------------------------------------------------------- the survivor recompute (bridge #2)


def _survivor_metrics(trials_counted: int = 1) -> BacktestMetrics:
    # A modest per-observation edge: clears the DSR gate against a handful of trials, NOT against thousands.
    return BacktestMetrics(
        oos_return=Decimal("0.1"), sharpe=Decimal("1.5"), sortino=Decimal("1.5"),
        max_drawdown=Decimal("0.1"), win_rate=Decimal("0.55"), num_trades=60,
        sharpe_per_obs=Decimal("0.18"), skew=Decimal("0"), kurtosis=Decimal("3"), n_obs=250,
        trials_counted=trials_counted, folds_positive_pct=Decimal("0.8"),
    )


def test_recompute_flips_verdict_at_honest_n(tmp_path):
    # The headline: a survivor that clears at its undercounted N (per-combo grid count) NO LONGER clears once the
    # Gate deflates against the TRUE number of looks the machine took for that family. Only N changes; the locked
    # DSR 0.95 gate is untouched.
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="edge", looks=_looks(3000), rho_bar=0.0)  # honest N ≈ 3000
    rec = recompute_dsr_at_honest_n(_survivor_metrics(trials_counted=1), store, family="edge")
    assert rec.raw_n == 1
    assert rec.effective_n == 3000.0
    assert rec.honest_n == 3000
    assert rec.clears_naive is True            # clears at the dishonest N
    assert rec.clears_honest is False          # fails at the honest N
    assert rec.still_clears is False
    assert rec.dsr_honest < rec.dsr_naive
    assert rec.threshold == 0.95


def test_recompute_honest_n_never_below_raw(tmp_path):
    # The honest count can only RAISE the bar: a near-empty ledger never deflates a survivor by LESS than the
    # per-combo count it already faced. With no looks, honest_n == raw_n and the DSR is unchanged.
    store = _store(tmp_path)
    rec = recompute_dsr_at_honest_n(_survivor_metrics(trials_counted=64), store, family="edge")
    assert rec.honest_n == 64
    assert rec.dsr_naive == rec.dsr_honest


def test_recompute_matches_direct_deflation(tmp_path):
    # Parity: the recompute's honest DSR is exactly deflated_sharpe_prob at the honest TrialStats — it reuses the
    # locked scorer, it does not re-implement the math.
    store = _store(tmp_path)
    record_looks(store, lane="finder", family="edge", looks=_looks(500), rho_bar=0.2)
    m = _survivor_metrics(trials_counted=1)
    rec = recompute_dsr_at_honest_n(m, store, family="edge")
    direct = deflated_sharpe_prob(m, TrialStats(count=rec.honest_n))
    assert rec.dsr_honest == direct


def test_recompute_uses_locked_gate_constant(tmp_path):
    # The threshold is read from GateSettings (0.95) — the audit never invents its own bar.
    store = _store(tmp_path)
    rec = recompute_dsr_at_honest_n(_survivor_metrics(), store, GateSettings(), family="x")
    assert rec.threshold == float(GateSettings().min_deflated_sharpe_prob)


# --------------------------------------------------------------------------- finder integration (brut contract)

_SYMS = {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0}


def _correlated_market(mu: float, n: int = 300, seed: int = 7) -> dict[str, list[Bar]]:
    rng = random.Random(seed)
    base = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)
    factor = [rng.gauss(0, 0.010) for _ in range(n)]
    out: dict[str, list[Bar]] = {}
    for s, p0 in _SYMS.items():
        p = p0
        bars = []
        for i in range(n):
            r = mu + 0.9 * factor[i] + rng.gauss(0, 0.004)
            o = p
            p = max(1e-6, p * (1 + r))
            hi = max(o, p) * (1 + abs(rng.gauss(0, 0.002)))
            lo = min(o, p) * (1 - abs(rng.gauss(0, 0.002)))
            bars.append(Bar(ts=base + dt.timedelta(hours=i), open=Decimal(str(o)), high=Decimal(str(hi)),
                            low=Decimal(str(lo)), close=Decimal(str(p)), volume=Decimal("1000")))
        out[s] = bars
    return out


class _Bars:
    def __init__(self, market):
        self._m = market

    def fetch_bars(self, symbol, timeframe, *, limit):
        return self._m.get(symbol, [])[-limit:]


def test_finder_records_looks_but_no_legacy_trials(tmp_path):
    # BRUT contract preserved: the finder still registers NO rows in the legacy `trials` family-counter (the
    # research/FDR gate's input is untouched). But it now records every (variant × symbol × venue) look into the
    # HONEST `trial_ledger`, so the survivor DSR audit can deflate against the true number of trials.
    from cosmu.evolution.seeder import seed_orb_fvg_spec
    from cosmu.lab.finder import StrategyFinder

    store = _store(tmp_path, "finder")
    finder = StrategyFinder(settings=store.settings, store=store, market_data=_Bars(_correlated_market(0.002)))
    finder.find(seed_orb_fvg_spec(), max_variants=8, persist=False)

    assert store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"] == 0          # brut: no legacy family trials
    assert ledger_count(store) > 0                                              # but every look IS in the ledger
    fam = store.row("SELECT DISTINCT family FROM trial_ledger LIMIT 1")["family"]
    assert fam == seed_orb_fvg_spec().name
    assert effective_n(store) > 0.0
