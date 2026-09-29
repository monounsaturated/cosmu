#!/usr/bin/env python3
# intent: OFFLINE kill-experiment for hypothesis H1 — AGGRESSIVE-TRADE-IMBALANCE REVERSAL on small-cap perps.
#         Fade an exhausted one-sided aggressive flow: when the trailing taker-buy/taker-sell imbalance is
#         extreme, the directional overshoot is hypothesized to revert on a thin small-cap book. This is the
#         #1 recommended experiment from the intraday order-flow feasibility spike (docs/reports/
#         intraday-orderflow-feasibility-2026-06-28.md). It is the FIRST genuinely-new, reachable signal axis
#         (daily price/calendar/attention are exhausted, 0/96 survive).
#
# data:   Binance Vision KEYLESS historical aggTrades (futures UM perp tree), resampled to 1m flow bars via
#         cosmu.data.intraday_aggtrades. The signed aggressor is the `is_buyer_maker` flag:
#           is_buyer_maker == False -> aggressive BUY ; == True -> aggressive SELL (confirmed from the data).
#
# signal: ONE pre-registered signal + threshold (NO sweep — the trial count must stay honest):
#           imbalance(t) = (sum taker-buy vol - sum taker-sell vol) / sum total vol, over the trailing
#                          IMB_WINDOW minutes ending at the close of minute t.
#         entry (FADE the extreme):  imbalance >= +ENTRY_THRESH -> SHORT ;  <= -ENTRY_THRESH -> LONG.
#         horizon: HOLD_MINUTES bars; exit at the close of bar t+HOLD_MINUTES (a fixed-time exit).
#
# economics: MAKER-ONLY (we do NOT play the taker/latency lane). Round-trip cost = 2*(maker_bps + slippage_bps)
#         from cosmu/spine/venue.py (Binance catalog). We are HONEST that maker fills are not guaranteed at this
#         cadence; the result is reported as an upper-bound on a maker-only book and a clean KILL is declared if
#         it cannot clear ~10-bps-class round-trip economics net of fees AND stay distinguishable from the
#         shuffle-null.
#
# disconfirmer (REQUIRED): SHUFFLE-NULL on the aggressor labels — randomly re-sign each trade (break the
#         buy/sell signing, preserve total volume per minute), recompute the imbalance signal + the strategy net
#         edge over K_SHUFFLE permutations. A REAL order-flow edge collapses toward zero under the shuffle; a
#         signal that survives the shuffle is price-autocorr/noise, not order-flow -> KILL. We report the real
#         net edge vs the shuffle-null distribution + an empirical p-value.
#
# gate:   route the per-(symbol x venue) NET result through the EXISTING BRUT path — build a SymbolRun from the
#         per-bar net-of-fee equity stream, metrics_for_run() it (locked formulas, own trials_counted=1), and
#         promote_brut() it against the LOCKED GateSettings (DSR 0.95, min_trades, beat-buy-and-hold, PBO,
#         folds). No Gate constant is touched.
#
# invariants:
#   - ZERO production side effects (pure read of keyless Vision zips + local file writes under scripts/research/
#     and a local bar cache). No DB, no prod store, no Gate-constant change, no money path.
#   - PIT honesty: the signal at minute t uses only trailing data through t's close; entry is at t's close
#     (knowable then); the forward return is close[t+H]/close[t]-1 (or short: -1*that). No look-ahead.
#   - ONE pre-registered threshold. No sweep.
#   - Fees+slippage charged maker round-trip at the venue's REAL bps (from cosmu/spine/venue.py).
#   - Gate stats computed BRUT per the locked scorer, never pooled across symbols.
#
# usage:  python3 h1_orderflow_imbalance_2026_06_28.py            # full pre-registered run (downloads aggTrades)
#         python3 h1_orderflow_imbalance_2026_06_28.py --self-test  # tiny synthetic end-to-end check, no network

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
# PRE-REGISTERED PARAMETERS (locked BEFORE looking at any returns — changing one = a NEW experiment, not a sweep).
# ---------------------------------------------------------------------------------------------------------------
IMB_WINDOW = 15          # trailing minutes for the aggressive-imbalance signal.
ENTRY_THRESH = 0.40      # |imbalance| entry trigger (fade the extreme one-sided flow). ONE threshold.
HOLD_MINUTES = 5         # fixed-time holding horizon (exit at close of t+HOLD).
MIN_GAP_MINUTES = HOLD_MINUTES  # no overlapping positions: a new entry must be >= HOLD past the last entry.
K_SHUFFLE = 200          # shuffle-null permutations of the aggressor labels.
PERIODS_PER_YEAR = 365.0 * 24 * 60  # 1m bars, crypto 24/7 calendar.

# Pre-registered small-cap perp basket (liquid enough to trade, small enough to overshoot on one-sided flow;
# all verified to have keyless Binance Vision futures-UM aggTrades archives). 7 symbols.
SMALLCAP_PERPS = ["SEIUSDT", "ARBUSDT", "FILUSDT", "GALAUSDT", "RUNEUSDT", "JUPUSDT", "OPUSDT"]

# Pre-registered window. M2-discipline: ~2 months (a fuller 6-month / wider-universe run belongs on Modal).
START = date(2025, 2, 1)
END = date(2025, 3, 31)

VENUE_ID = "binance"  # the venue we price against (cosmu/spine/venue.py). Binance is the perp DATA venue.
SEED = 20260628       # deterministic shuffle-null.

_RESULTS_JSON = Path(__file__).resolve().parent / "h1_orderflow_imbalance_results_2026_06_28.json"


# ---------------------------------------------------------------------------------------------------------------
# Signal + simulation (pure functions on a list of 1m FlowBars).
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class CellResult:
    symbol: str
    venue: str
    n_bars: int
    n_trades: int
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
    first `window-1` bars) so the signal is never read before it has a full trailing window. Pure, PIT-safe.
    Rolling O(n) (add the entering bar, subtract the leaving bar) — identical values to the naive O(n*window)
    sum, fast enough for K_SHUFFLE permutations on ~85k bars."""
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
    """Walk the bars; at each non-warm-up minute t with a CLOSED forward window (t+HOLD in range), if
    |imbalance[t]| >= ENTRY_THRESH and no position is open within MIN_GAP, FADE: short an extreme positive
    imbalance, long an extreme negative one. The position holds HOLD_MINUTES, exiting at close[t+HOLD]. Returns:
      - trades: BTTrade list (gross pnl_pct per trade, for the Gate's trade-count + regime split)
      - equity: NET-of-fee per-bar equity curve (base 100_000) — one point per BAR, position marked each bar
      - equity_ts: ISO timestamps parallel to equity
      - gross_per_trade: gross signed forward returns per trade (for the shuffle-null comparison)
    The equity is bar-by-bar marked so the Gate's per-bar Sharpe/DSR see the real held-position path, with the
    maker round-trip cost charged once per round-trip (split across entry+exit bars)."""
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
        # per-bar mark-to-market of any open position (gross), charge no fee on a hold bar
        ret_this_bar = 0.0
        if pos_dir != 0 and last_mark:
            px_ret = bar.close / last_mark - 1.0
            ret_this_bar = pos_dir * px_ret
        last_mark = bar.close

        # close at the scheduled exit bar (charge the round-trip cost here, once per trade)
        if pos_dir != 0 and t >= exit_idx:
            gross = pos_dir * (bar.close / entry_close - 1.0)
            net = gross - cost
            trades.append(BTTrade(entry=entry_close, exit=bar.close, pnl_pct=net, regime="chop"))
            gross_per_trade.append(gross)
            # the cost is realized at the exit bar -> fold it into this bar's marked return
            ret_this_bar -= cost
            pos_dir = 0

        equity.append(equity[-1] * (1.0 + ret_this_bar))
        equity_ts.append(bar.ts.isoformat())

        # consider a NEW entry only when flat and the full forward window is in range
        if pos_dir == 0 and (t - last_entry_idx) >= MIN_GAP_MINUTES and (t + HOLD_MINUTES) < n:
            sig = imbalance[t]
            if sig is not None and abs(sig) >= ENTRY_THRESH:
                pos_dir = -1 if sig > 0 else 1  # FADE: short extreme buys, long extreme sells
                entry_close = bar.close
                exit_idx = t + HOLD_MINUTES
                last_entry_idx = t
                last_mark = bar.close
    return trades, equity, equity_ts, gross_per_trade


def _net_buy_and_hold(bars: list[FlowBar], cost_bps_round_trip: float) -> float:
    """The symbol's net buy-and-hold over the window: one round-trip cost on a single open+close of the whole
    window (the Gate compares the strategy's total return against simply holding the basket, net of fees)."""
    if len(bars) < 2 or not bars[0].close:
        return 0.0
    gross = bars[-1].close / bars[0].close - 1.0
    return gross - cost_bps_round_trip / 10_000.0


def _shuffle_net_edge(bars: list[FlowBar], cost_bps_round_trip: float, rng: random.Random) -> float:
    """ONE shuffle-null draw: re-sign each minute's aggressor split (preserve TOTAL volume, randomly re-allocate
    it to buy/sell) and re-run the signal + sim; return the mean per-trade NET edge. Re-signing is done by
    drawing a fresh imbalance from a symmetric Beta-ish split per minute keyed to that minute's total volume, so
    the VOLUME (and thus which minutes can trigger) is preserved but the SIGN carries no real information.
    A genuine order-flow edge collapses toward 0 under this; price-autocorr noise survives."""
    shuffled: list[FlowBar] = []
    for b in bars:
        tot = b.total_vol
        if tot > 0:
            frac_buy = rng.random()  # random split, sign-information destroyed, total volume preserved
            buy = tot * frac_buy
            sell = tot - buy
        else:
            buy = sell = 0.0
        shuffled.append(FlowBar(open_ms=b.open_ms, close=b.close, buy_vol=buy, sell_vol=sell, n_trades=b.n_trades))
    imb = _trailing_imbalance(shuffled, IMB_WINDOW)
    trades, _equity, _ts, _gross = _simulate(shuffled, imb, cost_bps_round_trip=cost_bps_round_trip)
    if not trades:
        return 0.0
    return statistics.fmean(t.pnl_pct for t in trades)


def _run_cell(symbol: str, bars: list[FlowBar], *, maker_round_trip_bps: float, gates: GateSettings) -> CellResult | None:
    if len(bars) < IMB_WINDOW + HOLD_MINUTES + 5:
        return None
    imbalance = _trailing_imbalance(bars, IMB_WINDOW)
    trades, equity, equity_ts, gross_per_trade = _simulate(bars, imbalance, cost_bps_round_trip=maker_round_trip_bps)
    if not trades:
        return None

    net_edge = statistics.fmean(t.pnl_pct for t in trades)
    gross_edge = statistics.fmean(gross_per_trade)
    net_total = equity[-1] / 100_000.0 - 1.0
    gross_total = math.prod(1.0 + g for g in gross_per_trade) - 1.0
    bnh = _net_buy_and_hold(bars, maker_round_trip_bps)

    # --- shuffle-null disconfirmer ---
    rng = random.Random(f"{SEED}:{symbol}")
    shuffle_edges = [_shuffle_net_edge(bars, maker_round_trip_bps, rng) for _ in range(K_SHUFFLE)]
    shuffle_mean = statistics.fmean(shuffle_edges) if shuffle_edges else 0.0
    ge_count = sum(1 for s in shuffle_edges if s >= net_edge)
    p_value = (ge_count + 1) / (len(shuffle_edges) + 1)  # one-sided, +1 smoothing

    # --- BRUT Gate via the locked path ---
    run = _symbol_metrics(equity, trades, periods_per_year=PERIODS_PER_YEAR, equity_ts=equity_ts)
    metrics = metrics_for_run(run, trials=1, buy_and_hold=bnh, holdout_run=None)
    candidate = Candidate(
        id=f"h1-imbalance-fade::{symbol}@{VENUE_ID}",
        metrics=metrics,
        net_profit=net_total,
        source="h1_orderflow_imbalance_2026_06_28",
        label=f"H1 imbalance-fade {symbol}",
    )
    promo = promote_brut([candidate], gates)[0]

    return CellResult(
        symbol=symbol, venue=VENUE_ID, n_bars=len(bars), n_trades=len(trades),
        gross_edge=gross_edge, net_edge=net_edge,
        gross_total_return=gross_total, net_total_return=net_total, buy_and_hold=bnh,
        shuffle_mean_net_edge=shuffle_mean, shuffle_p_value=p_value,
        promoted=promo.promoted, deflated_sharpe_prob=promo.deflated_sharpe_prob,
        gate_reasons=list(promo.reasons),
    )


def _maker_round_trip_bps(catalog, venue_id: str) -> tuple[float, float, float]:
    """(maker_bps, slippage_bps, round_trip_bps) for the venue from cosmu/spine/venue.py — maker-only, since we
    do NOT play the taker lane. Round-trip = 2*(maker + slippage)."""
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
        print(f"[H1] {symbol}: fetching aggTrades {start}..{end} (perp) ...", flush=True)
        bars = fetch_1m_flow_bars(symbol, start, end, market="perp")
        print(f"[H1] {symbol}: {len(bars)} 1m flow bars", flush=True)
        cell = _run_cell(symbol, bars, maker_round_trip_bps=rt_bps, gates=gates)
        if cell is None:
            print(f"[H1] {symbol}: SKIP (insufficient bars/trades)", flush=True)
            continue
        cells.append(cell)
        print(
            f"[H1] {symbol}: trades={cell.n_trades} gross_edge={cell.gross_edge*1e4:.2f}bps "
            f"net_edge={cell.net_edge*1e4:.2f}bps shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps "
            f"p={cell.shuffle_p_value:.3f} net_total={cell.net_total_return*100:.2f}% "
            f"bnh={cell.buy_and_hold*100:.2f}% DSR={cell.deflated_sharpe_prob:.3f} "
            f"promoted={cell.promoted} reasons={cell.gate_reasons}",
            flush=True,
        )

    any_promoted = any(c.promoted for c in cells)
    # shuffle-null verdict: the edge is "killed by shuffle" if no cell's real net edge is distinguishable from
    # its shuffle-null at the conventional 0.05 one-sided level, OR the mean real net edge is <= the mean shuffle.
    distinguishable = [c for c in cells if c.shuffle_p_value <= 0.05 and c.net_edge > c.shuffle_mean_net_edge]
    shuffle_killed = len(distinguishable) == 0

    result = {
        "experiment": "H1 aggressive-trade-imbalance reversal on small-cap perps",
        "date": "2026-06-28",
        "axis": "intraday microstructure (aggressive trade flow) — NEW reachable axis",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "pre_registered": {
            "imb_window_minutes": IMB_WINDOW, "entry_thresh": ENTRY_THRESH,
            "hold_minutes": HOLD_MINUTES, "k_shuffle": K_SHUFFLE,
            "symbols": syms, "venue": VENUE_ID,
        },
        "economics": {
            "lane": "MAKER-ONLY (no taker/latency lane)",
            "maker_bps": maker_bps, "slippage_bps": slip_bps, "round_trip_bps": rt_bps,
            "note": (
                "Binance catalog maker = 10bps (spot schedule); for USDⓈ-M perps the REAL maker is ~2bps, so "
                "this round-trip (30bps) is CONSERVATIVE vs a real perp maker book (~14bps RT). Reported result "
                "uses the catalog venue.py fee — the locked Gate prices against it."
            ),
        },
        "gate": {
            "path": "metrics_for_run -> promote_brut (locked GateSettings)",
            "min_deflated_sharpe_prob": float(gates.min_deflated_sharpe_prob),
            "min_trades": gates.min_trades,
            "require_beat_buy_and_hold": gates.require_beat_buy_and_hold,
        },
        "cells": [c.__dict__ for c in cells],
        "verdict": {
            "any_cell_cleared_brut_gate": any_promoted,
            "shuffle_null_killed_it": shuffle_killed,
            "distinguishable_from_shuffle_cells": [c.symbol for c in distinguishable],
            "kill": (not any_promoted) or shuffle_killed,
        },
    }
    _RESULTS_JSON.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n[H1] wrote {_RESULTS_JSON}")
    v = result["verdict"]
    print(
        f"[H1] VERDICT: {'KILL' if v['kill'] else 'SURVIVOR'} | "
        f"cleared_gate={v['any_cell_cleared_brut_gate']} | shuffle_killed={v['shuffle_null_killed_it']}"
    )
    return result


# ---------------------------------------------------------------------------------------------------------------
# Tiny synthetic self-test: proves the signal/sim/shuffle/Gate plumbing end-to-end with NO network.
# ---------------------------------------------------------------------------------------------------------------
def _self_test() -> None:
    rng = random.Random(1)
    bars: list[FlowBar] = []
    price = 100.0
    open_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    # Construct a stream where a SUSTAINED one-sided buy imbalance (held long enough to fill the trailing
    # IMB_WINDOW) is followed by a small DOWN move — a real fade edge. The phase length must exceed IMB_WINDOW
    # so the trailing imbalance actually crosses ENTRY_THRESH (this tests the plumbing, not the real-data edge).
    cycle = 40  # > IMB_WINDOW + HOLD_MINUTES
    for i in range(3000):
        phase = i % cycle
        drift = rng.gauss(0, 0.0004)
        if phase < 20:  # sustained aggressive-buy overshoot (fills the trailing window) -> price drifts up
            buy, sell = 900.0, 100.0
            drift += 0.0010
        elif phase < 26:  # the snap-back down (the short-the-extreme-buy edge pays here)
            buy, sell = 200.0, 200.0
            drift += -0.0035
        else:  # neutral background
            buy = max(1.0, rng.gauss(200, 50))
            sell = max(1.0, rng.gauss(200, 50))
        price *= 1.0 + drift
        bars.append(FlowBar(open_ms=open_ms + i * _min_ms(), close=price, buy_vol=buy, sell_vol=sell, n_trades=int(buy + sell)))
    gates = GateSettings()
    cell = _run_cell("SYNTH", bars, maker_round_trip_bps=4.0, gates=gates)  # tiny cost so the injected edge shows
    assert cell is not None, "self-test: cell should run"
    assert cell.n_trades > 0, "self-test: should generate trades"
    print(
        f"[self-test] trades={cell.n_trades} net_edge={cell.net_edge*1e4:.2f}bps "
        f"shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps p={cell.shuffle_p_value:.3f} "
        f"promoted={cell.promoted} reasons={cell.gate_reasons}"
    )
    # the planted edge must beat its OWN shuffle-null (sign carries real info here)
    assert cell.net_edge > cell.shuffle_mean_net_edge, "self-test: planted edge should beat shuffle-null"
    assert cell.shuffle_p_value < 0.5, "self-test: planted edge should be distinguishable from shuffle"
    print("[self-test] OK — signal/sim/shuffle/Gate plumbing verified end-to-end (no network).")


def _min_ms() -> int:
    return 60_000


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="H1 aggressive-trade-imbalance reversal on small-cap perps.")
    ap.add_argument("--self-test", action="store_true", help="tiny synthetic end-to-end check, no network")
    ap.add_argument("--symbols", nargs="*", default=None, help="override the symbol set (debug)")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    else:
        run(symbols=args.symbols)
