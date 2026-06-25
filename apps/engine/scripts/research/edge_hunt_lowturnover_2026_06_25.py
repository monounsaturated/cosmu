#!/usr/bin/env python3
"""EXPERIMENT ONLY — attack the ONE wall left from #391: TURNOVER COST.

ZERO production impact: reuses the locked Gate + canonical scorer primitives, writes NOTHING to any store,
never touches a Gate constant. Output is a per-config stat block (printed + emitted as JSON for the report/HTML).

THE FINDING TO ATTACK (docs/reports/edge-hunt-mktneutral-2026-06-25.md, PR #391):
  The market-neutral long-leaders / short-laggards cross-sectional momentum book broke #390's beta wall (book
  corr-to-BTC ≈ 0) and trade-count wall (3k-24k trades). The GROSS spread is real and large (+53% to +89% over
  ~3.65yr), confirming the cross-sectional momentum premium EXISTS on this universe. But every ~daily-rebalance
  config NETS DEEPLY NEGATIVE: a realistic two-leg taker (10 bps) + liquidity-tiered slippage on the ~2-3 names
  that change basket each rebalance consumes 100%+ of the gross edge. The ONLY lever left is LOWERING TURNOVER.

THE PRE-REGISTERED GRID (this script):
  rebalance ∈ {weekly (42×4h), bi-weekly (84×4h)}  ×  rank-NO-TRADE-BAND ∈ {0.00 (no band), 0.10, 0.20, 0.30}.
  (band = hysteresis width on the cross-sectional percentile rank: a name only ENTERS the long basket when its
   rank climbs above the upper edge and only EXITS when it falls below the lower edge — symmetric for the short
   leg — so names near the quantile boundary are NOT churned every period. Wider band ⇒ less turnover.)
  Held fixed (from #391's best gross corner): lookback=60 4h bars (10d), quantile=0.20 (top/bottom 20%).
  Also swept lookback ∈ {30, 60} so the reader sees the band×cadence frontier is not a single-lookback artifact.

  For EACH config: gross ret, net ret (fees+slippage), turnover (avg fraction of book that changes/rebalance),
  leg trade-count, DSR / PBO / folds / holdout-DSR, corr-to-BTC. SAME honest cost floor production charges
  (two-leg taker + `backtest._liquidity_floor_bps`). Judged BRUT per book through the LOCKED Gate. RANK BY
  OUTLIER; emit EVERY config — NEVER a pooled mean. No best-of-N cherry-pick: the full deflated picture.

THE KEY QUESTION: does ANY low-turnover deadbanded book net POSITIVE after the honest cost floor AND clear the
  Gate? If NO even at the lowest-turnover corner (bi-weekly, widest band) → crypto cross-sectional momentum is
  genuinely UNECONOMIC at our cost tier — a REAL reject (signal present, but no surviving net edge), not a
  wiring/data gap.

REUSE: the data (paginated keyless Bybit v5 4h, ~3.65yr, 12 names), funding (cached real Binance, PIT 4h accrual),
  ranks, cost floor, and scoring are imported verbatim from edge_hunt_mktneutral_2026_06_25.py — the ONLY new code
  is the deadbanded book constructor and the slow-cadence grid, so the cost/data physics is byte-identical to #391.
"""
from __future__ import annotations

import gc
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[2]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

# Reuse #391's primitives VERBATIM (same data fetch, same funding, same ranks, same cost floor, same scoring).
from edge_hunt_mktneutral_2026_06_25 import (  # noqa: E402
    BYBIT_PAGES,
    FUNDING_DIR,
    UNIVERSE,
    _avg_pairwise_corr,
    _btc_bar_returns,
    _bybit_paginated,
    _corr,
    _equity_max_dd,
    _fold_returns,
    _funding_by_bar,
    _intersect_window,
    _long_only_bh,
    _periods_per_year,
    _rank_from_trailing,
    _trailing_returns_at,
)

from cosmu.config.settings import GateSettings  # noqa: E402
from cosmu.data.backtest import _liquidity_floor_bps  # noqa: E402
from cosmu.data.market import Bar  # noqa: E402
from cosmu.data.providers.funding import CachedFundingRateProvider  # noqa: E402
from cosmu.master.scorer import (  # noqa: E402
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    effective_trials,
    expected_max_sharpe,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.spine.venue import default_catalog  # noqa: E402

GATES = GateSettings()
RESULTS_JSON = _ENGINE / "scripts" / "research" / "edge_hunt_lowturnover_results_2026_06_25.json"


# --------------------------------------------------------------------------- the DEADBANDED market-neutral book
@dataclass
class Config:
    label: str
    lookback: int
    quantile: float
    rebalance_every: int     # rebalance the book every N 4h bars (42=weekly, 84=bi-weekly)
    band: float              # rank hysteresis half-width [0,1]; 0 = #391's no-band behaviour
    sharpe_ann: float = 0.0
    deflated_sharpe: float = 0.0
    psr_vs_zero: float = 0.0
    pbo: float = 0.0
    folds_positive: float = 0.0
    n_rebalances: int = 0
    n_trades: int = 0
    n_obs: int = 0
    max_dd: float = 0.0
    book_return: float = 0.0          # net-of-cost validation return
    gross_return: float = 0.0         # SAME book, cost-free (isolates the cost wall)
    long_only_bh: float = 0.0
    cash_benchmark: float = 0.0
    beat_cash: bool = False
    beat_long_bh: bool = False
    holdout_dsr: float = 0.0
    cost_ratio: float = 0.0
    turnover_per_reb: float = 0.0     # avg fraction of the held book that changes each rebalance
    avg_corr_to_btc: float = 0.0
    passed: bool = False
    holdout_passed: bool = False
    reasons: list = field(default_factory=list)


def _book_bar_returns_deadband(
    panel: dict[str, list[Bar]],
    ranks: dict[str, dict[str, float]],
    funding_by_sym: dict[str, dict[str, float]],
    *,
    quantile: float,
    rebalance_every: int,
    band: float,
    taker_bps: float,
    charge_costs: bool,
) -> tuple[list[float], list[str], int, int, float]:
    """Construct the market-neutral book's per-bar NET return stream WITH a rank no-trade band (hysteresis).

    Identical physics to #391's `_book_bar_returns` (same funding sign convention, same fee + liquidity-tiered
    slippage on names that change basket, same amortization across basket gross notional) EXCEPT the basket
    membership rule has a rank no-trade band (hysteresis):

      • FIXED basket size k = round(quantile·m) names per leg (the same k as #391's hard-quantile book) — the
        band does NOT shrink the basket on a small universe; it only governs WHEN a held name is swapped out.
      • Swap rule with band of half-width `band`: at a rebalance, the LONG leg's target set is the top-k by
        rank. A currently-held long name is swapped out for a higher-ranked candidate ONLY if the candidate's
        rank exceeds the held name's rank by more than `band` (and the held name has fallen out of the top-k).
        A held name that is still within the top-k is always kept. Symmetric (mirror) for the short leg on the
        bottom-k. So a name oscillating around the k-th rank boundary is NOT churned each period unless a clearly
        better-ranked (by > band) name displaces it — exactly the lever that cuts turnover. band=0 reduces to the
        #391 hard top-k / bottom-k membership.

    Returns (bar_returns, bar_ts, n_rebalances, n_trades, avg_turnover_fraction).
    """
    any_sym = next(iter(panel))
    ts_seq = [b.ts.isoformat() for b in panel[any_sym]]
    close_by_sym: dict[str, dict[str, float]] = {
        s: {b.ts.isoformat(): float(b.close) for b in bars} for s, bars in panel.items()
    }
    vol_by_sym: dict[str, dict[str, float]] = {
        s: {b.ts.isoformat(): float(b.close) * float(b.volume) for b in bars} for s, bars in panel.items()
    }
    fee = taker_bps / 10000.0

    bar_returns: list[float] = []
    bar_ts: list[str] = []
    cur_long: set[str] = set()
    cur_short: set[str] = set()
    n_rebalances = 0
    n_trades = 0
    turnover_samples: list[float] = []

    def _slip_for(sym: str, ts: str) -> float:
        if not charge_costs:
            return 0.0
        adv = vol_by_sym[sym].get(ts, 0.0)
        floor = max(5.0, _liquidity_floor_bps(adv))  # 5bps deep-book floor or liquidity-tiered, whichever larger
        return floor / 10000.0

    for i in range(len(ts_seq) - 1):
        ts = ts_seq[i]
        nxt = ts_seq[i + 1]
        turn_cost = 0.0
        if i % rebalance_every == 0:
            ranked = [(s, ranks[s][ts]) for s in panel if ts in ranks.get(s, {})]
            m = len(ranked)
            if m >= 4:
                k = max(1, int(round(m * quantile)))     # FIXED basket size per leg (same as #391)
                by_rank = {s: r for s, r in ranked}
                asc = sorted(ranked, key=lambda x: x[1])         # ascending rank (worst..best)
                top_k = {s for s, _ in asc[-k:]}                 # leaders (LONG target)
                bot_k = {s for s, _ in asc[:k]}                  # laggards (SHORT target)

                def _swap_band(held: set[str], target: set[str], leg_pool: list[str], leader: bool) -> set[str]:
                    """Apply the no-trade band: keep held names that are still in the top-k/bottom-k; for those
                    that fell out, swap them for the best target candidate ONLY if its rank beats (by > band) the
                    held name being displaced. `leg_pool` is ranked best-first for the leg (highest rank for the
                    long leg, lowest rank for the short leg)."""
                    new = {s for s in held if s in target}       # held names still on-target are always kept
                    # candidates = target names not yet held, ordered best-first for this leg
                    cands = [s for s in leg_pool if s in target and s not in new]
                    # held names that fell out of target, ordered worst-first (most deserving to be dropped)
                    fell = sorted((s for s in held if s not in target),
                                  key=lambda s: by_rank[s], reverse=not leader)
                    ci = 0
                    while len(new) < k and ci < len(cands):
                        cand = cands[ci]
                        ci += 1
                        if not fell:
                            new.add(cand)                        # empty slot — fill it (a real entry)
                            continue
                        held_out = fell[0]
                        margin = (by_rank[cand] - by_rank[held_out]) if leader else (by_rank[held_out] - by_rank[cand])
                        if margin > band:
                            new.add(cand)                        # candidate clearly better → swap in
                            fell.pop(0)
                        else:
                            new.add(held_out)                    # band not crossed → keep the held name
                            fell.pop(0)
                    # if still short of k (band kept everyone), top up with remaining held fallen names then cands
                    for s in fell:
                        if len(new) >= k:
                            break
                        new.add(s)
                    for s in cands[ci:]:
                        if len(new) >= k:
                            break
                        new.add(s)
                    return new

                long_pool = [s for s, _ in sorted(ranked, key=lambda x: x[1], reverse=True)]   # best-first
                short_pool = [s for s, _ in asc]                                               # worst-first
                new_long = _swap_band(cur_long, top_k, long_pool, leader=True) if cur_long else set(top_k)
                new_short = _swap_band(cur_short, bot_k, short_pool, leader=False) if cur_short else set(bot_k)
                new_short -= new_long                            # a name can't be on both legs (long precedence)

                changed = (new_long ^ cur_long) | (new_short ^ cur_short)
                prev_book_n = max(1, len(cur_long) + len(cur_short))
                for s in changed:
                    if s in close_by_sym and ts in close_by_sym[s]:
                        turn_cost += fee + _slip_for(s, ts)
                        n_trades += 1
                turnover_samples.append(len(changed) / prev_book_n)
                cur_long, cur_short = new_long, new_short
                n_rebalances += 1
                basket_n = max(1, len(cur_long) + len(cur_short))
            else:
                basket_n = max(1, len(cur_long) + len(cur_short))
        else:
            basket_n = max(1, len(cur_long) + len(cur_short))

        def _leg_ret(basket: set[str], side: int) -> float | None:
            rs: list[float] = []
            for s in basket:
                c0 = close_by_sym[s].get(ts)
                c1 = close_by_sym[s].get(nxt)
                if c0 and c1 and c0 > 0:
                    px = c1 / c0 - 1.0
                    f = funding_by_sym.get(s, {}).get(nxt, 0.0)
                    rs.append(px - (f if side == 1 else -f))
            return statistics.fmean(rs) if rs else None

        long_r = _leg_ret(cur_long, 1)
        short_r = _leg_ret(cur_short, -1)
        if long_r is None or short_r is None:
            continue
        book_r = long_r - short_r
        book_r -= turn_cost / basket_n
        bar_returns.append(book_r)
        bar_ts.append(nxt)

    avg_turnover = statistics.fmean(turnover_samples) if turnover_samples else 0.0
    return bar_returns, bar_ts, n_rebalances, n_trades, avg_turnover


def run_lowturnover_book(
    panel: dict[str, list[Bar]],
    funding_by_sym: dict[str, dict[str, float]],
    interval: str,
    taker_bps: float,
    venue: str,
) -> list[Config]:
    """Grid the deadbanded neutral book over (lookback × cadence × band), score each config's OWN book equity
    curve BRUT through the locked Gate, confirm the champion on its OWN embargoed holdout. PBO is the true CSCV
    across the grid's per-bar config streams (multiple-testing honest). RANK BY OUTLIER; emit EVERY config."""
    lookbacks = [30, 60]            # 4h: 5d / 10d trailing-momentum windows (#391's best corner was lb60)
    quantile = 0.20                 # top/bottom 20% (held fixed at #391's best gross corner)
    cadences = [42, 84]             # weekly (42×4h) / bi-weekly (84×4h) — the low-turnover lever
    bands = [0.0, 0.10, 0.20, 0.30] # rank no-trade band (hysteresis half-width)
    ppy = _periods_per_year(interval)

    rank_by_lb = {lb: _rank_from_trailing(_trailing_returns_at(panel, lb)) for lb in lookbacks}

    streams: list[tuple[Config, list[float], list[str]]] = []
    for lb in lookbacks:
        for cad in cadences:
            for band in bands:
                ranks = rank_by_lb[lb]
                br, bts, n_reb, n_tr, turn = _book_bar_returns_deadband(
                    panel, ranks, funding_by_sym, quantile=quantile, rebalance_every=cad, band=band,
                    taker_bps=taker_bps, charge_costs=True,
                )
                if len(br) < 40:
                    continue
                cfg = Config(
                    label=f"{venue}:{interval}:lb{lb}:q{quantile}:reb{cad}:band{band}",
                    lookback=lb, quantile=quantile, rebalance_every=cad, band=band,
                )
                cfg.n_rebalances = n_reb
                cfg.n_trades = n_tr
                cfg.turnover_per_reb = turn
                streams.append((cfg, br, bts))

    configs: list[Config] = []
    if not streams:
        return configs
    grid_size = max(1, len(streams))
    common_len = min(len(s[1]) for s in streams)
    cfg_block_returns = [s[1][-common_len:] for s in streams]
    grid_pbo = float(cscv_pbo(cfg_block_returns)) if len(streams) >= 2 else 1.0
    rho = _avg_pairwise_corr([s[1][-common_len:] for s in streams])

    for cfg, br, bts in streams:
        split = max(40, int(len(br) * 0.8))
        val_r, hold_r = br[:split], br[split + 1:]
        val_ts = bts[:split]
        sr_obs, skew, kurt, n_obs = sample_moments(val_r)
        trials = TrialStats(count=grid_size, sr_correlation=rho)
        sr_var = (1.0 + 0.5 * sr_obs * sr_obs) / (n_obs - 1) if n_obs > 1 else 0.0
        n_eff = effective_trials(float(grid_size), rho)
        sr0 = expected_max_sharpe(sr_var, n_eff)
        dsr = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, sr0)
        psr0 = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, 0.0)
        folds = _fold_returns(val_r)
        folds_pos = (sum(1 for f in folds if f > 0) / len(folds)) if folds else 0.0
        book_ret = math.prod(1.0 + r for r in val_r) - 1.0
        # Gross book (no costs) over the same val window for cost_ratio.
        ranks = rank_by_lb[cfg.lookback]
        gbr, _, _, _, _ = _book_bar_returns_deadband(
            panel, ranks, funding_by_sym, quantile=cfg.quantile, rebalance_every=cfg.rebalance_every,
            band=cfg.band, taker_bps=taker_bps, charge_costs=False,
        )
        gross_ret = math.prod(1.0 + r for r in gbr[:split]) - 1.0
        cost_ratio = (book_ret / gross_ret) if gross_ret != 0.0 else 0.0
        h_sr, h_skew, h_kurt, h_n = sample_moments(hold_r)
        holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
        long_bh = _long_only_bh(panel, val_ts, taker_bps)
        btc_r = _btc_bar_returns(panel, val_ts[1:] if val_ts else [])
        corr_btc = _corr(val_r[1:] if len(val_r) > 1 else val_r, btc_r)

        cfg.sharpe_ann = sr_obs * math.sqrt(ppy)
        cfg.deflated_sharpe = dsr
        cfg.psr_vs_zero = psr0
        cfg.pbo = grid_pbo
        cfg.folds_positive = folds_pos
        cfg.n_obs = n_obs
        cfg.max_dd = _equity_max_dd(val_r)
        cfg.book_return = book_ret
        cfg.gross_return = gross_ret
        cfg.cost_ratio = cost_ratio
        cfg.long_only_bh = long_bh
        cfg.cash_benchmark = 0.0
        cfg.beat_cash = book_ret > 0.0
        cfg.beat_long_bh = book_ret > long_bh
        cfg.holdout_dsr = holdout_dsr
        cfg.avg_corr_to_btc = corr_btc

        m = BacktestMetrics(
            oos_return=Decimal(str(round(book_ret, 8))),
            buy_and_hold_return=Decimal("0"),     # neutral book's honest hurdle = cash/0
            sharpe=Decimal(str(round(cfg.sharpe_ann, 6))),
            sortino=Decimal("0"),
            max_drawdown=Decimal(str(round(cfg.max_dd, 6))),
            win_rate=Decimal("0"),
            num_trades=cfg.n_trades,
            sharpe_per_obs=Decimal(str(round(sr_obs, 8))),
            skew=Decimal(str(round(skew, 6))),
            kurtosis=Decimal(str(round(kurt, 6))),
            n_obs=n_obs,
            pbo=Decimal(str(round(grid_pbo, 6))),
            trials_counted=grid_size,
            folds_positive_pct=Decimal(str(round(folds_pos, 6))),
            holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
            regime_returns={},
        )
        verdict = score(m, GATES, trials=trials, check_holdout=True)
        cfg.passed = verdict.passed and cfg.n_trades >= GATES.min_trades
        cfg.holdout_passed = holdout_dsr > float(GATES.holdout_min_deflated_sharpe)
        cfg.reasons = list(verdict.reasons)
        configs.append(cfg)
        gc.collect()
    return configs


def main() -> int:
    print("EDGE-HUNT LOW-TURNOVER 2026-06-25 — deadbanded weekly/bi-weekly market-neutral xsec book, BRUT, ZERO prod impact")
    print(f"  gate: DSR>={GATES.min_deflated_sharpe_prob} PBO<={GATES.max_pbo} folds>={GATES.min_folds_positive_pct} "
          f"min_trades>={GATES.min_trades} holdout_dsr>{GATES.holdout_min_deflated_sharpe} beat_benchmark={GATES.require_beat_buy_and_hold}")

    catalog = default_catalog()
    taker_bps = float(catalog.venue("binance").taker_fee_bps)
    funding = CachedFundingRateProvider(cache_dir=FUNDING_DIR)

    interval = "240"
    print(f"\n== fetching paginated keyless Bybit 4h ({BYBIT_PAGES} pages) for {len(UNIVERSE)} names ==")
    panel: dict[str, list[Bar]] = {}
    for sym in UNIVERSE:
        bars = _bybit_paginated(sym, interval, BYBIT_PAGES)
        if bars:
            panel[sym] = bars
        span = (bars[-1].ts - bars[0].ts).days if bars else 0
        print(f"  {sym}: {len(bars)} 4h bars  span={span}d  {bars[0].ts.date() if bars else None}..{bars[-1].ts.date() if bars else None}")
    panel = _intersect_window(panel)
    n_common = len(next(iter(panel.values()))) if panel else 0
    span_common = (next(iter(panel.values()))[-1].ts - next(iter(panel.values()))[0].ts).days if panel else 0
    print(f"  COMMON window: {len(panel)} names × {n_common} bars  span={span_common}d")

    funding_by_sym = {sym: _funding_by_bar(sym, bars, funding) for sym, bars in panel.items()}
    fund_cov = {s: sum(1 for v in d.values() if v != 0.0) for s, d in funding_by_sym.items()}
    print(f"  funding coverage (non-zero 4h accruals): {fund_cov}")

    print("\n== deadbanded market-neutral cross-sectional momentum BOOK (weekly / bi-weekly × rank no-trade band) ==")
    book_cfgs = run_lowturnover_book(panel, funding_by_sym, interval, taker_bps, "bybit")
    print(f"   book configs scored: {len(book_cfgs)}")

    payload = {
        "meta": {
            "interval": "4h", "pages": BYBIT_PAGES, "universe": UNIVERSE,
            "common_bars": n_common, "common_span_days": span_common, "taker_bps": taker_bps,
            "funding_coverage": fund_cov,
            "grid": "lookback{30,60} × quantile0.20 × cadence{weekly=42×4h, bi-weekly=84×4h} × band{0,0.10,0.20,0.30}",
        },
        "book": [c.__dict__ for c in book_cfgs],
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  wrote results -> {RESULTS_JSON}")

    survivors = [c for c in book_cfgs if c.passed and c.holdout_passed]
    print(f"\n  GATE survivors (pass + holdout): {len(survivors)} / {len(book_cfgs)}")
    # best NET config (rank by net book return — the economic question)
    by_net = sorted(book_cfgs, key=lambda c: c.book_return, reverse=True)
    if by_net:
        b = by_net[0]
        print(f"  BEST NET config: {b.label}  net={b.book_return:+.3f}  gross={b.gross_return:+.3f}  "
              f"turnover/reb={b.turnover_per_reb:.3f}  trades={b.n_trades}  DSR={b.deflated_sharpe:.3f}  "
              f"holdout_dsr={b.holdout_dsr:+.3f}  killed_by={','.join(b.reasons) if b.reasons else 'PASS'}")

    print("\n  ALL deadbanded book configs (ranked by NET return — the economic frontier):")
    hdr = (f"  {'config':<40}{'net':>8}{'gross':>8}{'turn':>7}{'trades':>7}{'reb':>5}"
           f"{'DSR':>7}{'folds':>7}{'pbo':>6}{'h_dsr':>7}{'corrBTC':>8}  killed_by")
    print(hdr)
    for c in by_net:
        kb = ",".join(c.reasons) if c.reasons else ("PASS" if c.passed else "")
        print(f"  {c.label:<40}{c.book_return:>8.3f}{c.gross_return:>8.3f}{c.turnover_per_reb:>7.3f}"
              f"{c.n_trades:>7}{c.n_rebalances:>5}{c.deflated_sharpe:>7.3f}{c.folds_positive:>7.2f}"
              f"{c.pbo:>6.2f}{c.holdout_dsr:>7.2f}{c.avg_corr_to_btc:>8.3f}  {kb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
