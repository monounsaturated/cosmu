# INVARIANT LOCK: settings.sim_track_capital is the SINGLE SOURCE OF TRUTH for a paper/SIM track's
# starting_capital. Every seeding path that INSERTs a `tracks` row (spine/engine.py, lab/finder.py,
# evolution/loop.py, and every research/*_arm.py) must stamp the track at settings.sim_track_capital with NO
# inline numeric literal — otherwise the cohort drifts (the $10k legacy tracks were exactly this: pre-canonical
# rows seeded before the canonical was set). This module pins the canonical default AND drives the real seeding
# code with a SENTINEL Settings(sim_track_capital=4242) so the persisted starting_capital can ONLY be 4242 if the
# value flows from the setting (a hardcoded $1000/$10000 literal would fail the assert). A final static guard
# greps every `tracks` INSERT site so a future literal can never silently re-introduce the drift.
#
# Offline-safe: the finder/spine drivers run on an in-memory SQLite Store with no market data (the conftest
# network guard fails any accidental real socket); the sentinel assertion needs no bars at all.

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, VariantResult
from cosmu.master.scorer import BacktestMetrics, ScoreVerdict
from cosmu.spine.engine import EngineFacade
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec

# A deliberately non-canonical, non-$1000/$10000 value: if ANY seeding path carries a hardcoded literal instead
# of reading the setting, the persisted starting_capital will not be this number and the assert fails loudly.
_SENTINEL = Decimal("4242")


def _sentinel_store(tmp_path) -> Store:
    """A Store whose Settings carry the SENTINEL per-track capital (and an offline SQLite url). Anything the
    seeding code persists as a track's starting_capital must equal this — proving it read the setting."""
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/capital_invariant.sqlite3",
            openrouter_api_key=None,
            sim_track_capital=_SENTINEL,
        )
    )


def test_canonical_sim_track_capital_default_is_1000():
    # The locked canonical: the per-track standalone SIM size every funder deploys. If this default ever changes,
    # the whole paper cohort's denominator changes with it — a deliberate, reviewed edit, never silent drift.
    assert Settings().sim_track_capital == Decimal("1000")


def test_finder_promotion_stamps_starting_capital_from_settings(tmp_path):
    # BEHAVIORAL DRIVER: finder._persist is the live promotion path that INSERTs the `tracks` row (gated only on
    # promoted & holdout_passed). Hand it a net-positive, holdout-passing survivor and assert the persisted
    # starting_capital == the SENTINEL — the value flowed from settings.sim_track_capital, not a literal.
    store = _sentinel_store(tmp_path)
    finder = StrategyFinder(settings=store.settings, store=store, market_data=None)

    from cosmu.lab.finder import CellResult

    spec = seed_orb_fvg_spec()
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    metrics = BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1.5"), sortino=Decimal("2.0"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.6"), num_trades=40,
        regime_returns={"bull": 0.05, "bear": -0.02},
    )
    cell = CellResult(symbol="BTCUSDT", venue_id="binance", metrics=metrics, deflated_sharpe=0.96,
                      trades=40, passed=True, holdout_passed=True)
    survivor = VariantResult(
        config_tag="cfg-sentinel", code_hash=compiled.code_hash, metrics=metrics,
        deflated_sharpe=0.96, profit_factor=2.0, net_profit=0.04, gate_passed=True, reasons=[],
        fitted_params=fitted, promoted=True, holdout_passed=True,
        per_symbol={"BTCUSDT": {"return": 0.05, "sharpe": 1.5, "max_drawdown": 0.10, "trades": 40.0}},
        cells={"BTCUSDT": cell},
    )
    finder._persist(spec, [survivor], {}, default_catalog().venue_for(spec.universe.venues))
    vid = survivor.version_id
    assert vid is not None

    row = store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert row is not None, "finder promotion must open a per-cell paper track"
    assert Decimal(str(row["starting_capital"])) == _SENTINEL, (
        "finder seeded a non-canonical starting_capital — it must read settings.sim_track_capital, not a literal"
    )
    # A track is BORN HONEST: equity == starting_capital and return_pct == 0 (the OOS lives in
    # backtests.oos_return — never seeded into the FORWARD columns). The paper clock advances these from real
    # marks (master/tracks.open_paper_track). This previously asserted equity == capital*(1 + oos), which LOCKED
    # IN a backtest-into-forward leak: an unmarked survivor displayed its OOS as forward P&L and could even read
    # live_ready off it (master/live_eligibility.paper_net_return_pct reads tracks.return_pct).
    eq = store.row("SELECT equity, return_pct FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert Decimal(str(eq["equity"])) == _SENTINEL.quantize(Decimal("0.01"))
    assert Decimal(str(eq["return_pct"])) == Decimal("0.00")


def test_spine_backtest_stamps_starting_capital_from_settings(tmp_path, monkeypatch):
    # The spine seeds a track only when its deterministic verdict passes. Force a PASS (monkeypatch the scorer the
    # spine imports) so the seeding branch is genuinely exercised, then assert the persisted starting_capital is the
    # SENTINEL — never the $100k internal sim bankroll the backtest runs on, never a literal. (live must be enabled
    # for run_backtest to execute; this is the SIM lane, no real funds.)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/spine_capital.sqlite3",
        environment="test",
        sim_track_capital=_SENTINEL,
    )
    settings.live.enabled = True

    def _pass(metrics, gates, *args, **kwargs):  # noqa: ANN001, ANN202 — test stub matching score()'s shape
        return ScoreVerdict(
            ranking_scalar=Decimal("0.99"), deflated_sharpe_prob=Decimal("0.99"), passed=True, reasons=[]
        )

    monkeypatch.setattr("cosmu.spine.engine.score", _pass)

    facade = EngineFacade.create(settings)
    result = facade.run_backtest(seed=42)
    assert result["ok"] is True
    assert result["passed"] is True  # the seeding branch was taken

    track = facade.store.row("SELECT starting_capital FROM tracks LIMIT 1")
    assert track is not None, "a passing spine backtest must open a paper track"
    assert Decimal(str(track["starting_capital"])) == _SENTINEL, (
        "spine seeded a non-canonical starting_capital — it must read settings.sim_track_capital, not a literal"
    )


def test_no_seeding_path_hardcodes_starting_capital():
    # STATIC GUARD: every site that INSERTs a `tracks` row must derive starting_capital from the setting. We scan
    # the engine package for `"starting_capital": str(<literal-number>)` — a hardcoded numeric (the exact shape of
    # the legacy $10k/$1k drift). The canonical paths all stamp `str(track_capital)` / `str(TRACK_CAPITAL)` /
    # `str(_capital)` (a NAME bound to settings.sim_track_capital), which this pattern never matches. The test
    # fixtures' own literal tracks (tests/) are intentionally excluded — they assert downstream behavior, not the
    # seeding contract.
    import re

    pkg_root = Path(__file__).resolve().parents[1] / "cosmu"
    # `"starting_capital": str( 12345 )`  or  `"starting_capital": "12345"`  — a literal number, not a name.
    literal = re.compile(
        r"""["']starting_capital["']\s*:\s*(?:str\(\s*)?["']?\d""",
    )
    offenders: list[str] = []
    for path in pkg_root.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if literal.search(line):
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "a seeding path hardcodes starting_capital with a numeric literal — it must read "
        "settings.sim_track_capital instead:\n" + "\n".join(offenders)
    )
