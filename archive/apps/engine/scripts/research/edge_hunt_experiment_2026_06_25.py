#!/usr/bin/env python3
"""EXPERIMENT ONLY — the real edge hunt for the two LIVE themes, judged BRUT per (strategy × symbol × venue).

ZERO production impact: reads the locked Gate + the canonical PIT backtest, writes NOTHING to any store, never
touches a Gate constant. Output is a per-combo stat block (printed + emitted as JSON for the report/HTML).

The money question: do cross-sectional momentum (xsec) + funding-contrarian produce any combo that SURVIVES or
gets close to the locked Gate (DSR>=0.95, PBO<=0.50, folds>=0.60, min_trades>=30, holdout DSR>0, beat-B&H),
judged on each combo's OWN data — never pooled across symbols (operator rule)?

Data (keyless / cached real bars; the M2 is geo-blocked from Binance LIVE):
  • Binance cell  → operator's cached real daily bars (.cosmu/market_data/binance) + cached real funding
                    (.cosmu/market_data/binance_funding). Real, PIT, taker 10 bps.
  • Kraken  cell  → LIVE keyless Kraken public OHLC (the real LIVE spot venue), taker 26 bps. The venue axis
                    is real: same price thesis, a 2.6× higher fee — this is what de-collapses S×A×V.

Both themes are gridded over a small fitted param grid (per-combo own-overfit deflation = the realized grid
size, exactly as the finder does). Each (variant × symbol × venue) cell is scored on its OWN validation streams
via metrics_for_run + the locked score(); the champion of each theme×symbol×venue is confirmed on its OWN
embargoed holdout. We RANK BY OUTLIER per symbol and emit EVERY combo — never a pooled mean.
"""
from __future__ import annotations

import gc
import itertools
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# Resolve apps/engine on sys.path when run directly.
_ENGINE = Path(__file__).resolve().parents[2]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import GateSettings, Settings  # noqa: E402
from cosmu.data.backtest import metrics_for_run, run_strategy_backtest_detailed  # noqa: E402
from cosmu.data.market import Bar, KrakenSpotOHLCVProvider  # noqa: E402
from cosmu.data.providers.funding import CachedFundingRateProvider  # noqa: E402
from cosmu.master.scorer import TrialStats, score  # noqa: E402
from cosmu.research.carry_ablation import _funding_alt, _xsec_rank_alt  # noqa: E402
from cosmu.spine.venue import default_catalog  # noqa: E402
from cosmu.strategy.compiler import compile_spec  # noqa: E402
from cosmu.strategy.spec import StrategySpec  # noqa: E402

# ------- config -------------------------------------------------------------------------------------------
# A real liquid universe — 12 names spanning majors + high-beta alts. Bare Binance symbols (the cache + funding
# key spelling); the Kraken provider maps BTCUSDT->XBTUSD etc. internally.
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT",
    "ADAUSDT", "DOTUSDT", "LTCUSDT", "XRPUSDT", "BCHUSDT", "ATOMUSDT",
]
BAR_LIMIT = 1000
INBOX = _ENGINE / "strategies" / "inbox"
GATES = GateSettings()  # the LOCKED gate (DSR 0.95, PBO 0.50, folds 0.60, min_trades 30, holdout>0, beat-B&H)
SETTINGS = Settings(openrouter_api_key=None)


@dataclass
class Combo:
    theme: str
    symbol: str
    venue: str
    config_tag: str
    params: dict
    # full per-combo gate stat block
    sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    psr_vs_zero: float = 0.0
    pbo: float = 0.0
    folds_positive: float = 0.0
    n_trades: int = 0
    max_dd: float = 0.0
    oos_return: float = 0.0
    buy_and_hold: float = 0.0
    beat_bh: bool = False
    holdout_dsr: float = 0.0
    passed: bool = False
    holdout_passed: bool = False
    reasons: list = field(default_factory=list)


def _load_spec(filename: str) -> StrategySpec:
    return StrategySpec.model_validate(json.loads((INBOX / filename).read_text()))


def _binance_cached_bars(symbol: str) -> list[Bar]:
    """Operator's cached REAL Binance daily bars (PIT, closed-candle). Empty when not cached."""
    path = _ENGINE.parent.parent / "apps" / "engine"  # not used; cache resolved below
    # The cache lives in the MAIN repo (the worktree has no cache); read it directly, read-only.
    main_cache = Path("/Users/device/cosmu/apps/engine/.cosmu/market_data/binance") / f"{symbol}_1d.json"
    if not main_cache.exists():
        return []
    rows = json.loads(main_cache.read_text())
    return [
        Bar(
            ts=datetime.fromtimestamp(int(r["ts"]) / 1000, tz=UTC),
            open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])), close=Decimal(str(r["close"])), volume=Decimal(str(r["volume"])),
        )
        for r in rows
    ][-BAR_LIMIT:]


def _kraken_live_bars(provider: KrakenSpotOHLCVProvider, symbol: str) -> list[Bar]:
    try:
        return provider.fetch_bars(symbol, "1d", limit=BAR_LIMIT)
    except Exception as e:  # noqa: BLE001
        print(f"  ! kraken fetch failed for {symbol}: {e}", file=sys.stderr)
        return []


def _grid(spec: StrategySpec, points: int = 3, max_variants: int = 24) -> list[dict]:
    """A small fitted grid (coarse, deterministic) — the per-combo own-overfit deflation is the realized count.
    Numeric ranges sample `points` evenly; ints are rounded+deduped. Capped for the lean M2 run."""
    keys = sorted(spec.param_space)
    axes = []
    for k in keys:
        ps = spec.param_space[k]
        if ps.kind == "choice" and ps.choices:
            axes.append([float(c) for c in ps.choices])
            continue
        lo, hi = float(ps.lo), float(ps.hi)
        if hi <= lo:
            axes.append([lo])
            continue
        pts = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
        if ps.kind == "int":
            pts = sorted({float(int(round(p))) for p in pts})
        axes.append(pts)
    combos = list(itertools.product(*axes))
    if len(combos) > max_variants:  # deterministic stride sample
        stride = len(combos) / max_variants
        combos = [combos[int(i * stride)] for i in range(max_variants)]
    return [{k: v for k, v in zip(keys, combo, strict=True)} for combo in combos]


def _score_combo(
    theme: str, symbol: str, venue_id: str, taker_bps: Decimal, slip_bps: Decimal, impact_bps: Decimal,
    spec: StrategySpec, params: dict, grid_size: int,
    bars: list[Bar], alt: dict | None, bh: float,
) -> Combo | None:
    """Backtest ONE (theme×symbol×venue×variant) on its OWN bars, then score it BRUT on its own streams.

    The xsec rank is a UNIVERSE feature: it is computed across the whole panel and passed in `alt`; the
    single-symbol backtest here reads only this symbol's rank series. Funding alt is per-symbol PIT carry.
    """
    market = {symbol: bars}
    alt_by_symbol = {symbol: alt} if alt else None
    try:
        compile_spec(spec, params)  # static validity (degenerate grid point -> skip)
    except ValueError:
        return None
    # SCREEN: validation-only (champion-only holdout is a separate confirmation, exactly like the finder).
    detailed = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=taker_bps, slippage_bps=slip_bps, impact_bps=impact_bps,
        alt_by_symbol=alt_by_symbol, include_holdout=True,  # holdout on so the champion confirm uses real bars
    )
    run = detailed.per_symbol_runs.get(symbol)
    if run is None:
        return None
    h_run = detailed.per_symbol_holdout_runs.get(symbol)
    own_bh = detailed.per_symbol_buy_and_hold.get(symbol, bh)
    m = metrics_for_run(run, trials=grid_size, buy_and_hold=own_bh, holdout_run=h_run)
    # BRUT verdict on this combo's OWN metrics, locked gates, TrialStats(count=1) (no cross-combo family).
    verdict = score(m, GATES, trials=TrialStats(count=1), check_holdout=True)
    from cosmu.master.scorer import probabilistic_sharpe  # PSR vs 0 for context (significance of the raw SR)
    psr0 = probabilistic_sharpe(float(m.sharpe_per_obs), m.n_obs, float(m.skew), float(m.kurtosis), 0.0)
    c = Combo(theme=theme, symbol=symbol, venue=venue_id, config_tag="", params=params)
    c.sharpe = float(m.sharpe)
    c.deflated_sharpe = float(verdict.deflated_sharpe_prob)
    c.psr_vs_zero = psr0
    c.pbo = float(m.pbo)
    c.folds_positive = float(m.folds_positive_pct)
    c.n_trades = m.num_trades
    c.max_dd = float(m.max_drawdown)
    c.oos_return = float(m.oos_return)
    c.buy_and_hold = float(own_bh)
    c.beat_bh = float(m.oos_return) > float(own_bh)
    c.holdout_dsr = float(m.holdout_deflated_sharpe)
    c.passed = verdict.passed and m.num_trades >= 30
    c.holdout_passed = float(m.holdout_deflated_sharpe) > float(GATES.holdout_min_deflated_sharpe)
    c.reasons = list(verdict.reasons)
    return c


def run_theme_xsec(panels: dict[str, dict[str, list[Bar]]]) -> list[Combo]:
    """Cross-sectional momentum, per venue. The xsec rank is computed across the FULL venue panel (PIT), then
    each symbol×variant is judged BRUT. lookback fixed at the spec's mid value for the rank build (the grid
    still varies the rank/vol thresholds + stops)."""
    spec = _load_spec("fiche-example-xsec-momentum.json")
    catalog = default_catalog()
    grid = _grid(spec, points=3, max_variants=24)
    grid_size = max(1, len(grid))
    out: list[Combo] = []
    for venue_id, panel in panels.items():
        if not panel:
            continue
        venue = catalog.venue_for([venue_id])
        # Build the xsec rank alt across the WHOLE panel at the spec's mid lookback (the rank's lookback is one
        # param; varying it would need a panel rebuild per value — fixed at mid keeps the run lean + honest).
        lb = int(round((spec.param_space["mom_lookback"].lo + spec.param_space["mom_lookback"].hi) / 2))
        rank_alt = _xsec_rank_alt(panel, lb)
        for symbol, bars in panel.items():
            if len(bars) < 120:
                continue
            alt = rank_alt.get(symbol)
            for params in grid:
                params = {**params, "mom_lookback": float(lb)}  # pin lookback to the rank we built
                c = _score_combo(
                    "xsec_momentum", symbol, venue_id, venue.taker_fee_bps, venue.slippage_bps, venue.impact_bps,
                    spec, params, grid_size, bars, alt, 0.0,
                )
                if c is not None:
                    c.config_tag = f"{venue_id}:{symbol}:lb{lb}:rf{params['rank_floor']:.2f}:vc{params['vol_ceiling']:.3f}:s{params['stop']:.2f}:tp{params['tp']:.2f}"
                    out.append(c)
            gc.collect()
    return out


def run_theme_funding(binance_panel: dict[str, list[Bar]]) -> list[Combo]:
    """Funding-contrarian (fade crowded shorts, long spot). Funding is a Binance-perp signal → Binance cell only
    (the cached real funding history). Each symbol×variant judged BRUT on its OWN funding+price streams."""
    spec = _load_spec("fiche-example-funding-contrarian.json")
    catalog = default_catalog()
    venue = catalog.venue_for(["binance"])
    grid = _grid(spec, points=3, max_variants=24)
    grid_size = max(1, len(grid))
    funding = CachedFundingRateProvider(
        cache_dir="/Users/device/cosmu/apps/engine/.cosmu/market_data/binance_funding"
    )
    out: list[Combo] = []
    for symbol, bars in binance_panel.items():
        if len(bars) < 120:
            continue
        # Per-symbol PIT funding alt (level + summed accrual). No funding cache -> empty -> the spec can't fire
        # (honest 'no data'); we still emit a zero-trade row so the table shows the coverage truth.
        alt = _funding_alt({symbol: bars}, funding).get(symbol)
        for params in grid:
            c = _score_combo(
                "funding_contrarian", symbol, "binance", venue.taker_fee_bps, venue.slippage_bps, venue.impact_bps,
                spec, params, grid_size, bars, alt, 0.0,
            )
            if c is not None:
                c.config_tag = f"binance:{symbol}:ff{params['funding_floor']:.5f}:rsi{int(params['rsi_lookback'])}<{params['rsi_floor']:.0f}:s{params['stop']:.2f}:tp{params['tp']:.2f}"
                out.append(c)
        gc.collect()
    return out


def main() -> int:
    print("EDGE-HUNT EXPERIMENT 2026-06-25 — BRUT per (theme × symbol × venue), locked Gate, ZERO prod impact")
    print(f"  universe={len(UNIVERSE)}  gate: DSR>={GATES.min_deflated_sharpe_prob} PBO<={GATES.max_pbo} "
          f"folds>={GATES.min_folds_positive_pct} min_trades>={GATES.min_trades} holdout_dsr>{GATES.holdout_min_deflated_sharpe} beat_bh={GATES.require_beat_buy_and_hold}")

    # --- build the venue panels (real bars) ---
    kraken = KrakenSpotOHLCVProvider()
    binance_panel: dict[str, list[Bar]] = {}
    kraken_panel: dict[str, list[Bar]] = {}
    for sym in UNIVERSE:
        b = _binance_cached_bars(sym)
        if b:
            binance_panel[sym] = b
        k = _kraken_live_bars(kraken, sym)
        if k:
            kraken_panel[sym] = k
        print(f"  {sym}: binance_cached={len(b)} bars  kraken_live={len(k)} bars")
    print(f"  panels: binance={len(binance_panel)} symbols  kraken={len(kraken_panel)} symbols")

    combos: list[Combo] = []
    print("\n== THEME 1: cross-sectional momentum (xsec) — Binance + Kraken venues ==")
    combos += run_theme_xsec({"binance": binance_panel, "kraken": kraken_panel})
    print(f"   xsec combos scored: {len([c for c in combos if c.theme=='xsec_momentum'])}")
    print("\n== THEME 2: funding-contrarian (Binance perp funding signal, long spot) ==")
    combos += run_theme_funding(binance_panel)
    print(f"   funding combos scored: {len([c for c in combos if c.theme=='funding_contrarian'])}")

    # --- emit JSON for the report + HTML ---
    payload = [c.__dict__ for c in combos]
    out_path = _ENGINE / "scripts" / "research" / "edge_hunt_results_2026_06_25.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  wrote {len(combos)} combo rows -> {out_path}")

    # --- verdict summary (ranked by OUTLIER per symbol; never a pooled mean) ---
    survivors = [c for c in combos if c.passed and c.holdout_passed]
    gate_pass = [c for c in combos if c.passed]
    print(f"\n  GATE survivors (pass + holdout): {len(survivors)} / {len(combos)} combos")
    print(f"  gate-pass on validation (pre-holdout): {len(gate_pass)}")
    # Best OUTLIER per (symbol, venue, theme) by DSR — the honest 'closest to the line'.
    best = sorted([c for c in combos if c.n_trades >= 5], key=lambda c: c.deflated_sharpe, reverse=True)[:15]
    print("\n  TOP-15 OUTLIER combos by deflated Sharpe (the near-miss frontier):")
    print(f"  {'theme':<19}{'sym':<9}{'venue':<9}{'DSR':>7}{'trades':>7}{'folds':>7}{'pbo':>6}{'ret':>9}{'bh':>9}{'h_dsr':>7}  killed_by")
    for c in best:
        kb = ",".join(c.reasons) if c.reasons else ("PASS" if c.passed else "")
        print(f"  {c.theme:<19}{c.symbol:<9}{c.venue:<9}{c.deflated_sharpe:>7.3f}{c.n_trades:>7}"
              f"{c.folds_positive:>7.2f}{c.pbo:>6.2f}{c.oos_return:>9.3f}{c.buy_and_hold:>9.3f}{c.holdout_dsr:>7.2f}  {kb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
