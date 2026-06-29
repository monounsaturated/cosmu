#!/usr/bin/env python3
# intent: OFFLINE follow-up to H1 (#468) — LOW-TURNOVER aggressive-trade-imbalance FADE on small-cap perps.
#         H1 proved the 1m-cadence imbalance fade is a KILL ON ECONOMICS (gross edge <=2bps, annihilated by the
#         maker round-trip) but NOT on signal absence: the calibrated shuffle-null detected a faint REAL ~2bps
#         order-flow signal on 2/7 cells (FIL p=0.040, OP p=0.075). Order-flow information demonstrably exists in
#         the tape — it is TURNOVER-bound. H1b's single attack: cut round-trips ~10-40x so the real ~2bps gross
#         can survive the fee. If it monetizes -> a genuine survivor on a NEW axis; if it still can't pay even at
#         low turnover -> a decisive KILL of the order-flow-fade family at ANY tradeable cadence.
#
# data:   REUSES the exact H1 cached 1m flow bars (cosmu.data.intraday_aggtrades; same small-cap perps, same
#         period, same disk cache). NO new fetch is required when the H1 cache is present.
#
# signal: ONE pre-registered LOW-TURNOVER config (NO sweep — the trial count stays honest). Engineered for low
#         turnover three ways at once vs H1:
#           (a) COARSER decision bar: resample the 1m flow bars to 15m flow bars (fewer decision points).
#           (b) RARE-TAIL entry threshold: |imbalance| >= 0.40 on a single 15m bar (~p98 of the 15m distribution
#               — the rarest 2% of coarse bars; the reachable coarse-bar analog of "the most extreme flow").
#           (c) LONGER holding horizon: hold HOLD_BARS 15m-bars (= 6 hours), not 1 minute.
#         imbalance(t) = (sum taker-buy vol - sum taker-sell vol) / sum total vol, over the trailing IMB_BARS
#                        15m-bar(s) ending at the close of 15m-bar t. (See the CALIBRATION NOTE below: a first
#                        2h-window/0.70-thresh pre-reg was structurally unreachable -> 0 trades; re-locked on the
#                        signal distribution only, never on a return.)
#         entry (FADE the extreme):  imbalance >= +ENTRY_THRESH -> SHORT ;  <= -ENTRY_THRESH -> LONG.
#         horizon: HOLD_BARS 15m-bars; exit at the close of bar t+HOLD_BARS (a fixed-time exit). No overlap.
#
# economics: MAKER-ONLY (we do NOT play the taker/latency lane), IDENTICAL fee path to H1. Round-trip cost =
#         2*(maker_bps + slippage_bps) from cosmu/spine/venue.py (Binance catalog: 10+5 -> 30bps RT). The H1
#         report notes the real USDⓈ-M perp maker is ~2bps so 30bps is CONSERVATIVE; we keep the catalog fee so
#         the locked Gate prices the cell against venue.py, never a hand-tuned number.
#
# disconfirmer (REQUIRED): the SAME shuffle-null as H1 — re-sign each 15m-bar's aggressor split (preserve TOTAL
#         volume, destroy the buy/sell SIGN), recompute the signal + the strategy NET edge over K_SHUFFLE perms,
#         report the real net edge vs the shuffle-null distribution + an empirical p-value. A real order-flow
#         edge stays distinguishable from the re-signed null; price-autocorr noise does not.
#
# gate:   route the per-(symbol x venue) NET result through the EXISTING BRUT path — _symbol_metrics ->
#         metrics_for_run(trials=1, buy_and_hold=<own net B&H>) -> promote_brut(GateSettings()). No Gate constant
#         is touched. min_trades=30 is the binding low-turnover constraint: a cell with <30 trades fails the Gate
#         on trade count (honest — we do not lower it).
#
# invariants: ZERO production side effects (read of the H1 cache + local file writes only). PIT honesty (signal
#         at bar t uses only the trailing window through t's close; entry at t's close; forward return
#         close[t+H]/close[t]-1). ONE pre-registered config, no sweep. Fees maker round-trip at venue.py bps.
#         Gate stats BRUT per the locked scorer, never pooled across symbols.
#
# usage:  python3 h1b_orderflow_lowturnover_2026_06_28.py            # pre-registered run (reuses H1 cache)
#         python3 h1b_orderflow_lowturnover_2026_06_28.py --self-test  # tiny synthetic end-to-end, no network

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

# Make the engine importable when run from scripts/research/.
_ENGINE_ROOT = Path(__file__).resolve().parents[2]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from cosmu.config.settings import GateSettings  # noqa: E402
from cosmu.data.backtest import Trade as BTTrade  # noqa: E402
from cosmu.data.backtest import _symbol_metrics, metrics_for_run  # noqa: E402
from cosmu.data.intraday_aggtrades import FlowBar, fetch_1m_flow_bars  # noqa: E402
from cosmu.master.cohort import Candidate, promote_brut  # noqa: E402
from cosmu.spine.venue import default_catalog  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------
# PRE-REGISTERED PARAMETERS (locked BEFORE looking at any RETURN — changing one = a NEW experiment, not a sweep).
# The single H1b attack on the H1 KILL: cut turnover ~10-40x so the confirmed ~2bps gross signal can clear the
# maker round-trip. Three low-turnover levers at once: coarser bar + rarer (tail) threshold + much longer hold.
#
# CALIBRATION NOTE (honest, recorded in the report): the FIRST pre-registration used IMB_BARS=8 (a 2-hour
# trailing window) with ENTRY_THRESH=0.70. That combo is STRUCTURALLY UNREACHABLE: averaging signed flow over 2h
# mean-reverts |imbalance| toward 0 (observed MAX |imb_2h| ~= 0.30-0.39 across the basket), so it produced ZERO
# trades on every cell — an uninformative non-result, NOT a test of the hypothesis. We re-locked the trigger
# geometry against the signal's DISTRIBUTION ONLY (never its P&L): IMB_BARS=1 (the freshest single 15m bar's own
# buy/sell split — where the coarse-bar flow can actually reach an extreme) and ENTRY_THRESH=0.40, which sits at
# ~the 98th percentile of the 15m |imbalance| distribution (vs H1's 0.40, which was only ~p62 on 1m bars). This
# is the legitimate coarse-bar analog of "the rarest, most extreme imbalances", and it yields a GATEABLE,
# low-turnover trade count (~30-100/cell, ~10-40x fewer round-trips than H1's 387-1480). This re-calibration
# read only the imbalance histogram, never a strategy return.
# ---------------------------------------------------------------------------------------------------------------
BAR_MINUTES = 15         # COARSER decision bar: resample 1m flow bars to 15m flow bars (vs H1's 1m).
IMB_BARS = 1             # imbalance = the freshest single 15m bar's own signed buy/sell split (reachable extreme).
ENTRY_THRESH = 0.40      # |imbalance| trigger at ~p98 of the 15m distribution — the rarest 2% of coarse bars.
HOLD_BARS = 24           # LONGER hold: 24 x 15m = 6 hours (vs H1's 5 x 1m). Fixed-time exit at close of t+HOLD.
MIN_GAP_BARS = HOLD_BARS  # no overlapping positions: a new entry must be >= HOLD bars past the last entry.
K_SHUFFLE = 200          # shuffle-null permutations of the aggressor labels (same as H1).
PERIODS_PER_YEAR = 365.0 * 24 * (60 / BAR_MINUTES)  # 15m bars, crypto 24/7 calendar.

# Pre-registered small-cap perp basket — IDENTICAL to H1 (reuse the cached fetch verbatim).
SMALLCAP_PERPS = ["SEIUSDT", "ARBUSDT", "FILUSDT", "GALAUSDT", "RUNEUSDT", "JUPUSDT", "OPUSDT"]

# Pre-registered window — IDENTICAL to H1 (reuse the cached fetch). M2-discipline: ~2 months.
START = date(2025, 2, 1)
END = date(2025, 3, 31)

VENUE_ID = "binance"  # the venue we price against (cosmu/spine/venue.py). Same as H1.
SEED = 20260628       # deterministic shuffle-null (same seed family as H1).

_RESULTS_JSON = Path(__file__).resolve().parent / "h1b_orderflow_lowturnover_results_2026_06_28.json"


# ---------------------------------------------------------------------------------------------------------------
# 1m -> 15m flow-bar resample (PURE; no network). Aggregates the signed-aggressor split + last-trade close.
# ---------------------------------------------------------------------------------------------------------------
def resample_flow_bars(bars: list[FlowBar], bar_minutes: int) -> list[FlowBar]:
    """Aggregate ascending 1m FlowBars into coarser `bar_minutes`-minute FlowBars. Each coarse bar SUMS the
    aggressive buy/sell volume and trade count of the 1m bars whose open falls in the coarse minute bucket, and
    carries the LAST (latest-open) 1m close as the coarse close (the mark knowable at the coarse bar's close).
    Missing 1m minutes are simply absent (never zero-filled — same gap discipline as the 1m fetcher). The coarse
    `open_ms` is the bucket's floor; the coarse bar is PIT-knowable at open_ms + bar_minutes*60_000."""
    if bar_minutes <= 1:
        return list(bars)
    width_ms = bar_minutes * 60_000
    buckets: dict[int, dict[str, float]] = {}
    for b in bars:
        floor = (b.open_ms // width_ms) * width_ms
        agg = buckets.get(floor)
        if agg is None:
            agg = {"buy": 0.0, "sell": 0.0, "n": 0.0, "last_open": -1.0, "close": 0.0}
            buckets[floor] = agg
        agg["buy"] += b.buy_vol
        agg["sell"] += b.sell_vol
        agg["n"] += b.n_trades
        if b.open_ms >= agg["last_open"]:  # latest 1m close in the bucket = coarse bar's close
            agg["last_open"] = float(b.open_ms)
            agg["close"] = b.close
    return [
        FlowBar(open_ms=m, close=a["close"], buy_vol=a["buy"], sell_vol=a["sell"], n_trades=int(a["n"]))
        for m, a in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------------------------------------------
# Signal + simulation (pure functions on a list of coarse FlowBars). Identical logic to H1, parameterized for the
# coarse-bar / long-hold / rare-threshold low-turnover config.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class CellResult:
    symbol: str
    venue: str
    n_bars: int                # number of COARSE (15m) bars
    n_trades: int
    turnover_ratio_vs_h1: float  # informational: this cell's trades as a fraction of H1's same-cell trade count
    gross_edge: float          # mean per-trade GROSS return (sum of signed forward returns / n_trades)
    net_edge: float            # mean per-trade NET return (after maker round-trip cost)
    gross_total_return: float  # compounded gross total return over the window
    net_total_return: float    # compounded net total return over the window
    buy_and_hold: float        # net buy-and-hold of the symbol over the same window
    shuffle_mean_net_edge: float
    shuffle_p_value: float     # P(shuffle net edge >= real net edge); high => indistinguishable from null
    promoted: bool
    deflated_sharpe_prob: float
    gate_reasons: list[str] = field(default_factory=list)


def _trailing_imbalance(bars: list[FlowBar], window: int) -> list[float | None]:
    """imbalance[t] = (sum buy - sum sell)/(sum total) over bars[t-window+1 .. t]. None during warm-up (the
    first `window-1` bars). Rolling O(n). PIT-safe (only trailing data through t). Identical to H1."""
    n = len(bars)
    out: list[float | None] = [None] * n
    buy = sell = 0.0
    for t in range(n):
        buy += bars[t].buy_vol
        sell += bars[t].sell_vol
        if t >= window:
            buy -= bars[t - window].buy_vol
            sell -= bars[t - window].sell_vol
        if t >= window - 1:
            tot = buy + sell
            out[t] = (buy - sell) / tot if tot > 0 else 0.0
    return out


def _simulate(
    bars: list[FlowBar],
    imbalance: list[float | None],
    *,
    cost_bps_round_trip: float,
) -> tuple[list[BTTrade], list[float], list[str], list[float]]:
    """Walk the coarse bars; at each non-warm-up bar t with a CLOSED forward window (t+HOLD_BARS in range), if
    |imbalance[t]| >= ENTRY_THRESH and no position is open within MIN_GAP_BARS, FADE: short an extreme positive
    imbalance, long an extreme negative one. Hold HOLD_BARS, exit at close[t+HOLD_BARS]. The maker round-trip
    cost is charged once per round-trip, folded into the exit bar's marked return. Returns trades / per-bar NET
    equity / ISO timestamps / gross-per-trade. Identical mechanics to H1, only the bar/hold/gap are coarse."""
    cost = cost_bps_round_trip / 10_000.0
    n = len(bars)
    trades: list[BTTrade] = []
    gross_per_trade: list[float] = []
    equity = [100_000.0]
    equity_ts = [bars[0].ts.isoformat()] if bars else []

    pos_dir = 0          # +1 long, -1 short, 0 flat
    entry_close = 0.0
    exit_idx = -1
    last_entry_idx = -10**9
    last_mark = bars[0].close if bars else 0.0

    for t in range(1, n):
        bar = bars[t]
        ret_this_bar = 0.0
        if pos_dir != 0 and last_mark:
            px_ret = bar.close / last_mark - 1.0
            ret_this_bar = pos_dir * px_ret
        last_mark = bar.close

        if pos_dir != 0 and t >= exit_idx:
            gross = pos_dir * (bar.close / entry_close - 1.0)
            net = gross - cost
            trades.append(BTTrade(entry=entry_close, exit=bar.close, pnl_pct=net, regime="chop"))
            gross_per_trade.append(gross)
            ret_this_bar -= cost
            pos_dir = 0

        equity.append(equity[-1] * (1.0 + ret_this_bar))
        equity_ts.append(bar.ts.isoformat())

        if pos_dir == 0 and (t - last_entry_idx) >= MIN_GAP_BARS and (t + HOLD_BARS) < n:
            sig = imbalance[t]
            if sig is not None and abs(sig) >= ENTRY_THRESH:
                pos_dir = -1 if sig > 0 else 1  # FADE: short extreme buys, long extreme sells
                entry_close = bar.close
                exit_idx = t + HOLD_BARS
                last_entry_idx = t
                last_mark = bar.close
    return trades, equity, equity_ts, gross_per_trade


def _net_buy_and_hold(bars: list[FlowBar], cost_bps_round_trip: float) -> float:
    """The symbol's net buy-and-hold over the window: one round-trip cost on a single open+close. Same as H1."""
    if len(bars) < 2 or not bars[0].close:
        return 0.0
    gross = bars[-1].close / bars[0].close - 1.0
    return gross - cost_bps_round_trip / 10_000.0


def _shuffle_net_edge(bars: list[FlowBar], cost_bps_round_trip: float, rng: random.Random) -> float:
    """ONE shuffle-null draw: re-sign each coarse bar's aggressor split (preserve TOTAL volume, randomly
    re-allocate to buy/sell so the SIGN carries no real info), re-run the signal + sim, return mean per-trade NET
    edge. A genuine order-flow edge collapses toward 0 under this; price-autocorr noise survives. Same as H1."""
    shuffled: list[FlowBar] = []
    for b in bars:
        tot = b.total_vol
        if tot > 0:
            frac_buy = rng.random()
            buy = tot * frac_buy
            sell = tot - buy
        else:
            buy = sell = 0.0
        shuffled.append(FlowBar(open_ms=b.open_ms, close=b.close, buy_vol=buy, sell_vol=sell, n_trades=b.n_trades))
    imb = _trailing_imbalance(shuffled, IMB_BARS)
    trades, _equity, _ts, _gross = _simulate(shuffled, imb, cost_bps_round_trip=cost_bps_round_trip)
    if not trades:
        return 0.0
    return statistics.fmean(t.pnl_pct for t in trades)


# H1's own per-cell trade counts (from docs/reports/h1-orderflow-imbalance-2026-06-28.md table) — used ONLY for
# the informational turnover-cut ratio, NOT for any gate decision.
_H1_TRADES = {
    "SEIUSDT": 1480, "ARBUSDT": 905, "FILUSDT": 831, "GALAUSDT": 778,
    "RUNEUSDT": 1080, "JUPUSDT": 677, "OPUSDT": 387,
}


def _run_cell(symbol: str, coarse_bars: list[FlowBar], *, maker_round_trip_bps: float, gates: GateSettings) -> CellResult | None:
    if len(coarse_bars) < IMB_BARS + HOLD_BARS + 5:
        return None
    imbalance = _trailing_imbalance(coarse_bars, IMB_BARS)
    trades, equity, equity_ts, gross_per_trade = _simulate(coarse_bars, imbalance, cost_bps_round_trip=maker_round_trip_bps)
    if not trades:
        return None

    net_edge = statistics.fmean(t.pnl_pct for t in trades)
    gross_edge = statistics.fmean(gross_per_trade)
    net_total = equity[-1] / 100_000.0 - 1.0
    gross_total = math.prod(1.0 + g for g in gross_per_trade) - 1.0
    bnh = _net_buy_and_hold(coarse_bars, maker_round_trip_bps)
    h1_n = _H1_TRADES.get(symbol, 0)
    turnover_ratio = (len(trades) / h1_n) if h1_n else float("nan")

    # --- shuffle-null disconfirmer (same construction + seed family as H1) ---
    rng = random.Random(f"{SEED}:{symbol}")
    shuffle_edges = [_shuffle_net_edge(coarse_bars, maker_round_trip_bps, rng) for _ in range(K_SHUFFLE)]
    shuffle_mean = statistics.fmean(shuffle_edges) if shuffle_edges else 0.0
    ge_count = sum(1 for s in shuffle_edges if s >= net_edge)
    p_value = (ge_count + 1) / (len(shuffle_edges) + 1)  # one-sided, +1 smoothing

    # --- BRUT Gate via the locked path (unchanged) ---
    run = _symbol_metrics(equity, trades, periods_per_year=PERIODS_PER_YEAR, equity_ts=equity_ts)
    metrics = metrics_for_run(run, trials=1, buy_and_hold=bnh, holdout_run=None)
    candidate = Candidate(
        id=f"h1b-lowturnover-fade::{symbol}@{VENUE_ID}",
        metrics=metrics,
        net_profit=net_total,
        source="h1b_orderflow_lowturnover_2026_06_28",
        label=f"H1b lowturnover-fade {symbol}",
    )
    promo = promote_brut([candidate], gates)[0]

    return CellResult(
        symbol=symbol, venue=VENUE_ID, n_bars=len(coarse_bars), n_trades=len(trades),
        turnover_ratio_vs_h1=turnover_ratio,
        gross_edge=gross_edge, net_edge=net_edge,
        gross_total_return=gross_total, net_total_return=net_total, buy_and_hold=bnh,
        shuffle_mean_net_edge=shuffle_mean, shuffle_p_value=p_value,
        promoted=promo.promoted, deflated_sharpe_prob=promo.deflated_sharpe_prob,
        gate_reasons=list(promo.reasons),
    )


def _maker_round_trip_bps(catalog, venue_id: str) -> tuple[float, float, float]:
    """(maker_bps, slippage_bps, round_trip_bps) for the venue from cosmu/spine/venue.py — maker-only. Same as H1."""
    v = catalog.venue(venue_id)
    maker = float(v.maker_fee_bps)
    slip = float(v.slippage_bps)
    return maker, slip, 2.0 * (maker + slip)


def run(symbols: list[str] | None = None, start: date = START, end: date = END) -> dict:
    catalog = default_catalog()
    maker_bps, slip_bps, rt_bps = _maker_round_trip_bps(catalog, VENUE_ID)
    gates = GateSettings()  # LOCKED defaults — never modified.
    syms = symbols or SMALLCAP_PERPS

    cells: list[CellResult] = []
    for symbol in syms:
        print(f"[H1b] {symbol}: loading H1 cached aggTrades {start}..{end} (perp) + resampling to {BAR_MINUTES}m ...", flush=True)
        bars_1m = fetch_1m_flow_bars(symbol, start, end, market="perp")
        coarse = resample_flow_bars(bars_1m, BAR_MINUTES)
        print(f"[H1b] {symbol}: {len(bars_1m)} 1m -> {len(coarse)} {BAR_MINUTES}m flow bars", flush=True)
        cell = _run_cell(symbol, coarse, maker_round_trip_bps=rt_bps, gates=gates)
        if cell is None:
            print(f"[H1b] {symbol}: SKIP (insufficient bars/trades)", flush=True)
            continue
        cells.append(cell)
        print(
            f"[H1b] {symbol}: trades={cell.n_trades} (={cell.turnover_ratio_vs_h1:.3f}x H1) "
            f"gross_edge={cell.gross_edge*1e4:.2f}bps net_edge={cell.net_edge*1e4:.2f}bps "
            f"shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps p={cell.shuffle_p_value:.3f} "
            f"net_total={cell.net_total_return*100:.2f}% bnh={cell.buy_and_hold*100:.2f}% "
            f"DSR={cell.deflated_sharpe_prob:.3f} promoted={cell.promoted} reasons={cell.gate_reasons}",
            flush=True,
        )

    any_promoted = any(c.promoted for c in cells)
    # A cell is a genuine survivor only if it clears the BRUT Gate AND its real net edge is distinguishable from
    # its shuffle-null (p<=0.05, one-sided) AND positive net total return. Distinguishable-but-not-gated cells
    # are flagged separately (real signal, still not monetizable).
    distinguishable = [c for c in cells if c.shuffle_p_value <= 0.05 and c.net_edge > c.shuffle_mean_net_edge]
    survivors = [c for c in cells if c.promoted and c.shuffle_p_value <= 0.05 and c.net_total_return > 0]
    shuffle_killed = len(distinguishable) == 0

    result = {
        "experiment": "H1b LOW-TURNOVER aggressive-trade-imbalance fade on small-cap perps",
        "stacked_on": "H1 (#468) — monetize the confirmed ~2bps order-flow signal past the fee wall",
        "date": "2026-06-28",
        "axis": "intraday microstructure (aggressive trade flow) — LOW-TURNOVER variant of H1",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "pre_registered": {
            "bar_minutes": BAR_MINUTES, "imb_bars": IMB_BARS, "imb_window_minutes": IMB_BARS * BAR_MINUTES,
            "entry_thresh": ENTRY_THRESH, "hold_bars": HOLD_BARS, "hold_minutes": HOLD_BARS * BAR_MINUTES,
            "k_shuffle": K_SHUFFLE, "symbols": syms, "venue": VENUE_ID, "trials_per_cell": 1,
            "low_turnover_levers": (
                "coarser 15m bar + |imb|>=0.40 at ~p98 of the 15m distribution (rarest 2%) + 6h hold "
                "(vs H1 1m bar / 0.40@~p62 / 5m hold)"
            ),
            "calibration_note": (
                "First pre-reg (IMB_BARS=8 / 2h window, thresh 0.70) was structurally unreachable (max |imb_2h| "
                "~0.30-0.39 -> 0 trades). Re-locked on the signal DISTRIBUTION only (never a return): IMB_BARS=1, "
                "thresh 0.40 = ~p98 of the 15m |imbalance| histogram."
            ),
        },
        "economics": {
            "lane": "MAKER-ONLY (no taker/latency lane)",
            "maker_bps": maker_bps, "slippage_bps": slip_bps, "round_trip_bps": rt_bps,
            "note": (
                "Identical fee path to H1: catalog maker=10bps (spot schedule), real USDⓈ-M perp maker ~2bps so "
                "30bps RT is CONSERVATIVE. Locked Gate prices against venue.py."
            ),
        },
        "gate": {
            "path": "_symbol_metrics -> metrics_for_run(trials=1) -> promote_brut (locked GateSettings)",
            "min_deflated_sharpe_prob": float(gates.min_deflated_sharpe_prob),
            "min_trades": gates.min_trades,
            "require_beat_buy_and_hold": gates.require_beat_buy_and_hold,
        },
        "cells": [c.__dict__ for c in cells],
        "verdict": {
            "any_cell_cleared_brut_gate": any_promoted,
            "survivor_cells": [c.symbol for c in survivors],
            "distinguishable_from_shuffle_cells": [c.symbol for c in distinguishable],
            "shuffle_null_killed_it": shuffle_killed,
            "survivor": len(survivors) > 0,
            "kill": len(survivors) == 0,
        },
    }
    _RESULTS_JSON.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n[H1b] wrote {_RESULTS_JSON}")
    v = result["verdict"]
    print(
        f"[H1b] VERDICT: {'SURVIVOR' if v['survivor'] else 'KILL'} | "
        f"cleared_gate={v['any_cell_cleared_brut_gate']} | survivors={v['survivor_cells']} | "
        f"distinguishable={v['distinguishable_from_shuffle_cells']} | shuffle_killed={v['shuffle_null_killed_it']}"
    )
    return result


# ---------------------------------------------------------------------------------------------------------------
# Tiny synthetic self-test: proves the resample + signal/sim/shuffle/Gate plumbing end-to-end with NO network.
# ---------------------------------------------------------------------------------------------------------------
def _self_test() -> None:
    rng = random.Random(7)
    bars: list[FlowBar] = []
    price = 100.0
    open_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    # Build 1m bars where a SUSTAINED one-sided buy imbalance (held long enough to fill the coarse trailing
    # window AFTER resampling) is followed by a small DOWN move — a real fade edge at the coarse cadence. The
    # phase must exceed (IMB_BARS+HOLD_BARS) coarse bars worth of minutes so the coarse signal crosses thresh.
    coarse_cycle_bars = IMB_BARS + HOLD_BARS + 8       # coarse bars per cycle
    cycle = coarse_cycle_bars * BAR_MINUTES            # in minutes
    up_minutes = (IMB_BARS + 4) * BAR_MINUTES
    snap_minutes = up_minutes + HOLD_BARS * BAR_MINUTES
    n_minutes = cycle * 40
    for i in range(n_minutes):
        phase = i % cycle
        drift = rng.gauss(0, 0.0003)
        if phase < up_minutes:        # sustained aggressive-buy overshoot -> price drifts up
            buy, sell = 900.0, 100.0
            drift += 0.0004
        elif phase < snap_minutes:    # the snap-back down (the fade pays here, over the 6h hold)
            buy, sell = 250.0, 250.0
            drift += -0.0006
        else:                         # neutral background
            buy = max(1.0, rng.gauss(200, 50))
            sell = max(1.0, rng.gauss(200, 50))
        price *= 1.0 + drift
        bars.append(FlowBar(open_ms=open_ms + i * 60_000, close=price, buy_vol=buy, sell_vol=sell, n_trades=int(buy + sell)))
    coarse = resample_flow_bars(bars, BAR_MINUTES)
    assert len(coarse) == math.ceil(n_minutes / BAR_MINUTES) or len(coarse) == n_minutes // BAR_MINUTES, "resample bar count"
    gates = GateSettings()
    cell = _run_cell("SYNTH", coarse, maker_round_trip_bps=4.0, gates=gates)  # tiny cost so the injected edge shows
    assert cell is not None, "self-test: cell should run"
    assert cell.n_trades > 0, "self-test: should generate trades"
    print(
        f"[self-test] coarse_bars={len(coarse)} trades={cell.n_trades} "
        f"gross_edge={cell.gross_edge*1e4:.2f}bps net_edge={cell.net_edge*1e4:.2f}bps "
        f"shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps p={cell.shuffle_p_value:.3f} "
        f"promoted={cell.promoted} reasons={cell.gate_reasons}"
    )
    # the planted edge must beat its OWN shuffle-null (sign carries real info here)
    assert cell.net_edge > cell.shuffle_mean_net_edge, "self-test: planted edge should beat shuffle-null"
    assert cell.shuffle_p_value < 0.5, "self-test: planted edge should be distinguishable from shuffle"
    print("[self-test] OK — resample/signal/sim/shuffle/Gate plumbing verified end-to-end (no network).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="H1b LOW-TURNOVER aggressive-trade-imbalance fade on small-cap perps.")
    ap.add_argument("--self-test", action="store_true", help="tiny synthetic end-to-end check, no network")
    ap.add_argument("--symbols", nargs="*", default=None, help="override the symbol set (debug)")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    else:
        run(symbols=args.symbols)
