# intent: the STRATEGY × ASSET × TIMEFRAME survivor-hunt (backlog item P, the #1 search move). Runs EVERY inbox
# StrategySpec through the honest Gate (run_strategy_backtest_detailed → promote_cohort BH-FDR + REAL holdout, net
# of REAL fees) on one (asset, timeframe) slice of the deep cached data, persists the cohort verdict to
# gate_verdicts (durable experiment-memory), and reports any survivor + the best dSR/holdout. Fan this out across
# the asset/timeframe grid (locally or on Modal) to widen search beyond the exhausted current grid. ZERO LLM on
# the gate path; deterministic for fixed bars. A spec that errors or never trades on a slice is an HONEST skip,
# never a fabricated row.

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cosmu.config.settings import Settings, get_settings
from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.trials import record_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.carry_ablation import _resolve_params
from cosmu.research.regime_cohort import load_tr_bars
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec

_INBOX = Path(__file__).resolve().parents[2] / "strategies" / "inbox"


@dataclass(frozen=True)
class MatrixResult:
    asset: str
    timeframe: str
    n_specs: int
    n_traded: int
    n_promoted: int
    survivors: list[str]
    best_spec: str
    best_dsr: float
    best_holdout_dsr: float


def load_specs() -> list[StrategySpec]:
    out: list[StrategySpec] = []
    for p in sorted(_INBOX.glob("*.json")):
        try:
            out.append(StrategySpec.model_validate(json.loads(p.read_text())))
        except Exception:  # noqa: BLE001 — a malformed inbox file is skipped, never fabricated
            continue
    return out


def load_bars(asset: str, timeframe: str) -> list[Bar]:
    if asset.endswith("USDT"):
        # spot cache first, perp cache fallback (deeper mid-cap coverage)
        _binance_base = os.environ.get("COSMU_BINANCE_CACHE", "/Users/device/cosmu/.cosmu/market_data")
        for cache in (".cosmu/market_data/binance", ".cosmu/market_data/binanceperp",
                      f"{_binance_base}/binance", f"{_binance_base}/binanceperp"):
            try:
                bars = BinanceSpotOHLCVProvider(cache_dir=cache).fetch_bars(asset, timeframe, limit=5000)
                if bars:
                    return bars
            except Exception:  # noqa: BLE001
                continue
        return []
    return load_tr_bars(asset)  # equity total-return daily


def run_matrix_cell(asset: str, timeframe: str, *, persist: bool = True) -> MatrixResult:
    bars = load_bars(asset, timeframe)
    market = {asset: bars}
    specs = load_specs()
    fee_bps = default_catalog().venue("binance").taker_fee_bps
    tmp = tempfile.mkdtemp(prefix="cosmu-matrix-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/m.sqlite3", openrouter_api_key=None))

    candidates: list[Candidate] = []
    n_traded = 0
    if len(bars) >= 60:
        for spec in specs:
            try:
                res = run_strategy_backtest_detailed(spec, _resolve_params(spec), market, fee_bps=fee_bps)
            except Exception:  # noqa: BLE001 — a spec that can't run on this slice is an honest skip
                continue
            m = res.metrics
            if int(m.num_trades) <= 0:
                continue  # never traded on this slice → no candidate (honest, not a fabricated 0-edge row)
            n_traded += 1
            record_trial(store, float(m.sharpe_per_obs), source="matrix", label=f"{asset}:{timeframe}:{spec.name}")
            candidates.append(Candidate(id=spec.name, metrics=m, net_profit=float(m.oos_return),
                                        source="matrix", label=spec.name))

    if not candidates:
        return MatrixResult(asset, timeframe, len(specs), 0, 0, [], "", 0.0, 0.0)

    persist_spec = durable_persist(
        run_id=f"matrix-{asset}-{timeframe}",
        hypothesis=f"any documented inbox spec survives the honest Gate on {asset}@{timeframe}",
        source="research/matrix", asset=asset, timeframe=timeframe,
    ) if persist else None
    proms = promote_cohort(store, candidates, store.settings.gates, register=False,
                           trials=trial_stats(store), persist=persist_spec)
    survivors = [p.candidate_id for p in proms if p.promoted]
    best = max(proms, key=lambda p: p.deflated_sharpe_prob)
    best_m = next(c.metrics for c in candidates if c.id == best.candidate_id)
    return MatrixResult(
        asset, timeframe, len(specs), n_traded, len(survivors), survivors,
        best.candidate_id, round(best.deflated_sharpe_prob, 4), round(float(best_m.holdout_deflated_sharpe), 4),
    )


def _default_assets(settings: Settings | None = None) -> list[str]:
    """Return the sweep asset universe from config (MATRIX_SWEEP_ASSETS env fallback) or the built-in default."""
    try:
        cfg = settings or get_settings()
        if cfg.matrix_sweep_assets:
            return cfg.matrix_sweep_assets
    except Exception:  # noqa: BLE001 — offline/test context: fall through to built-in
        pass
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SPY", "QQQ"]


def _default_timeframes(settings: Settings | None = None) -> list[str]:
    """Return the sweep timeframe list from config (MATRIX_SWEEP_TIMEFRAMES env fallback) or ["1d"]."""
    try:
        cfg = settings or get_settings()
        if cfg.matrix_sweep_timeframes:
            return cfg.matrix_sweep_timeframes
    except Exception:  # noqa: BLE001
        pass
    return ["1d"]


def run_sweep(
    assets: list[str] | None = None,
    timeframes: list[str] | None = None,
    *,
    persist: bool = True,
    settings: Settings | None = None,
) -> list[MatrixResult]:
    """One-shot: gate EVERY inbox spec across a universe × timeframes, persist each verdict to the experiment
    memory, and return the results ranked by best dSR. Asset/timeframe universe defaults come from config
    (MATRIX_SWEEP_ASSETS / MATRIX_SWEEP_TIMEFRAMES) so the operator can widen the grid without code changes.
    The simple front door — `python -m cosmu.research.matrix_search --sweep`."""
    assets = assets or _default_assets(settings)
    timeframes = timeframes or _default_timeframes(settings)
    out: list[MatrixResult] = []
    for a in assets:
        for tf in timeframes:
            out.append(run_matrix_cell(a, tf, persist=persist))
    return sorted(out, key=lambda r: r.best_dsr, reverse=True)


def _main() -> int:
    import sys

    do_sweep = "--sweep" in sys.argv or os.environ.get("MATRIX_SWEEP") == "1"
    persist = os.environ.get("MATRIX_PERSIST", "1") == "1"

    # Optional CLI overrides: --assets BTC,ETH --timeframes 1d,4h
    cli_assets: list[str] | None = None
    cli_tfs: list[str] | None = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--assets" and i < len(sys.argv):
            cli_assets = [a.strip() for a in sys.argv[i + 1].split(",") if a.strip()]
        if arg == "--timeframes" and i < len(sys.argv):
            cli_tfs = [t.strip() for t in sys.argv[i + 1].split(",") if t.strip()]

    if do_sweep:
        results = run_sweep(assets=cli_assets, timeframes=cli_tfs, persist=persist)
        survivors = [r for r in results if r.n_promoted]
        print(f"MATRIX SWEEP — {len(results)} cells · {sum(r.n_promoted for r in results)} survivors · "
              f"{'SURVIVOR FOUND' if survivors else 'no honest edge (the machine refused all)'}")
        print(f"{'asset@tf':14s} {'verdict':12s} {'traded':>6s} {'promoted':>8s}  best (dsr / holdoutDSR)")
        for r in results:
            v = "SURVIVOR" if r.n_promoted else ("no-survivor" if r.n_traded else "no-data")
            print(f"  {r.asset+'@'+r.timeframe:12s} {v:12s} {r.n_traded:>6d} {r.n_promoted:>8d}  "
                  f"{r.best_spec[:34]:34s} {r.best_dsr:.3f} / {r.best_holdout_dsr:+.3f}")
        return 0

    asset = cli_assets[0] if cli_assets else os.environ.get("MATRIX_ASSET", "BTCUSDT")
    tf = cli_tfs[0] if cli_tfs else os.environ.get("MATRIX_TF", "1d")
    r = run_matrix_cell(asset, tf, persist=persist)
    verdict = "SURVIVOR" if r.n_promoted else ("no-survivor" if r.n_traded else "no-data/no-trades")
    print(f"MATRIX {asset}@{tf} — {verdict}")
    print(f"  specs={r.n_specs} traded={r.n_traded} promoted={r.n_promoted} survivors={r.survivors}")
    print(f"  best={r.best_spec} dsr={r.best_dsr} holdoutDSR={r.best_holdout_dsr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
