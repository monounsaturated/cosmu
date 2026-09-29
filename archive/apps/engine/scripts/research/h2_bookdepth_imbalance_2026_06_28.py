#!/usr/bin/env python3
# intent: OFFLINE kill-or-confirm experiment for hypothesis H2 — RESTING BOOK-DEPTH IMBALANCE on small-cap perps.
#         A GENUINELY DISTINCT mechanism from H1/H1b (which faded executed AGGRESSIVE trade flow and KILLED): H2
#         trades the standing PASSIVE limit-order liquidity. When resting BID depth dominates the resting ASK
#         depth within a tight ±band of mid, the book carries a support wall + queue pressure that the
#         microstructure literature (Cont-Kukanov-Stoikov 2014: order-book imbalance positively predicts the next
#         price move) says drifts price UP on a short horizon. So H2 trades WITH the depth imbalance (NOT a fade)
#         — directionally opposite to H1's fade, matching the documented OBI sign, so it is hypothesis diversity,
#         not a re-spin of the killed flow-fade.
#
# data:   Binance Vision KEYLESS historical bookDepth snapshots (futures UM perp tree), reduced to ±BAND% and
#         resampled to 1m DEPTH bars via cosmu.data.intraday_bookdepth; PRICE to mark P&L is the parallel 1m perp
#         kline close via cosmu.data.intraday_binance_vision.fetch_1m_bars(market="perp"), inner-joined on the
#         minute. bookDepth carries no price, so the join is required and is PIT-clean (both knowable at minute close).
#
# signal: ONE pre-registered signal + threshold (NO sweep — the trial count must stay honest):
#           imbalance(t) = (mean within-band BID depth - mean within-band ASK depth)/(total) over the trailing
#                          DEPTH_WINDOW minutes ending at the close of minute t (smoothing transient pulled walls).
#         entry (FOLLOW the wall): imbalance >= +ENTRY_THRESH -> LONG ; <= -ENTRY_THRESH -> SHORT.
#         horizon: HOLD_MINUTES bars; exit at the close of bar t+HOLD_MINUTES (fixed-time exit).
#
# economics: MAKER-ONLY (we do NOT play the taker/latency lane). Round-trip cost = 2*(maker_bps + slippage_bps)
#         from cosmu/spine/venue.py (Binance catalog) — the LOCKED Gate prices against this catalog number.
#         H1b found the catalog prices perps at the ~30bps SPOT schedule while a realistic perp MAKER round-trip is
#         ~14bps; the codebase has only the 30bps catalog maker, so the GATE VERDICT uses 30bps and we ALSO report
#         a transparent 14bps sensitivity (clearly labelled, NOT the gate number). The Gate is never loosened.
#
# disconfirmer (REQUIRED): SHUFFLE-NULL that breaks the TEMPORAL ALIGNMENT between the depth-imbalance series and
#         price. We CIRCULARLY ROTATE the depth-imbalance series by a random offset (preserving its full marginal
#         distribution + autocorrelation, destroying only its alignment to the price path) and re-run the strategy
#         over K_SHUFFLE permutations. A REAL book-imbalance->return edge collapses toward zero under the rotation;
#         an edge that survives is price-autocorr/noise, not a depth->price relationship -> KILL. We report the real
#         net edge vs the rotation-null distribution + a one-sided empirical p-value.
#
# gate:   route the per-(symbol x venue) NET result through the EXISTING BRUT path — build a SymbolRun from the
#         per-bar net-of-fee equity stream, metrics_for_run() it (locked formulas, own trials_counted=1), and
#         promote_brut() it against the LOCKED GateSettings. No Gate constant is touched.
#
# invariants:
#   - ZERO production side effects (pure read of keyless Vision zips + local file writes under scripts/research/
#     and a local bar cache). No DB, no prod store, no Gate-constant change, no money path.
#   - PIT honesty: the signal at minute t uses only trailing depth bars through t's close; entry at t's close
#     (knowable then); forward return is close[t+H]/close[t]-1 (short: -1*that). No look-ahead.
#   - ONE pre-registered config. No sweep.
#   - Fees+slippage charged maker round-trip at the venue's catalog bps (cosmu/spine/venue.py).
#   - Gate stats computed BRUT per the locked scorer, never pooled across symbols.
#
# usage:  python3 h2_bookdepth_imbalance_2026_06_28.py             # full pre-registered run (downloads bookDepth+klines)
#         python3 h2_bookdepth_imbalance_2026_06_28.py --self-test  # tiny synthetic end-to-end check, no network

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
from cosmu.data.intraday_binance_vision import fetch_1m_bars  # noqa: E402
from cosmu.data.intraday_bookdepth import DepthBar, fetch_1m_depth_bars  # noqa: E402
from cosmu.master.cohort import Candidate, promote_brut  # noqa: E402
from cosmu.spine.venue import default_catalog  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------
# PRE-REGISTERED PARAMETERS (locked BEFORE looking at any returns — changing one = a NEW experiment, not a sweep).
# ---------------------------------------------------------------------------------------------------------------
BAND = 2                  # ±% book region for the depth imbalance (tight enough to be near-touch, deep enough to be stable).
DEPTH_WINDOW = 15         # trailing minutes the depth-imbalance signal averages over (smooths transient walls).
ENTRY_THRESH = 0.20       # |imbalance| entry trigger. ONE threshold. (Resting-depth imbalance lives in a tighter
#                           range than executed-flow imbalance — a wall rarely 40/60-splits the near book — so the
#                           pre-registered threshold is set at 0.20, calibrated from the H1 family's logic, NOT swept.)
HOLD_MINUTES = 5          # fixed-time holding horizon (exit at close of t+HOLD).
MIN_GAP_MINUTES = HOLD_MINUTES  # no overlapping positions: a new entry must be >= HOLD past the last entry.
K_SHUFFLE = 200           # rotation-null permutations of the depth-imbalance series.
PERIODS_PER_YEAR = 365.0 * 24 * 60  # 1m bars, crypto 24/7 calendar.

# Pre-registered small-cap perp basket — the SAME 7 names as H1 (comparability), all verified to have keyless
# Binance Vision futures-UM bookDepth archives.
SMALLCAP_PERPS = ["SEIUSDT", "ARBUSDT", "FILUSDT", "GALAUSDT", "RUNEUSDT", "JUPUSDT", "OPUSDT"]

# Pre-registered window. M2-discipline: ~2 months (a fuller 6-month / wider-universe run belongs on Modal).
START = date(2025, 2, 1)
END = date(2025, 3, 31)

VENUE_ID = "binance"  # the venue we price against (cosmu/spine/venue.py). Binance is the perp DATA venue.
SEED = 20260628       # deterministic rotation-null.

# Realistic perp-maker sensitivity (NOT the gate number): the codebase catalog only carries Binance's ~10bps SPOT
# maker; a real USDⓈ-M perp maker is ~2bps. We report the strategy net AT this fee transparently as a sensitivity.
PERP_MAKER_BPS_SENSITIVITY = 2.0

_RESULTS_JSON = Path(__file__).resolve().parent / "h2_bookdepth_imbalance_results_2026_06_28.json"


# ---------------------------------------------------------------------------------------------------------------
# Joined 1m bar: depth imbalance (from bookDepth) + close price (from klines), on the same minute.
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class JoinedBar:
    open_ms: int
    close: float
    imbalance: float       # within-band resting-depth imbalance at this minute (mean over the minute's snapshots)
    n_snaps: int

    @property
    def ts(self) -> datetime:
        return datetime.fromtimestamp(self.open_ms / 1000, tz=UTC)


def join_depth_and_price(depth_bars: list[DepthBar], price_bars) -> list[JoinedBar]:
    """Inner-join 1m DEPTH bars (bookDepth) with 1m PRICE bars (klines) on the minute open_ms. Only minutes present
    in BOTH survive (a missing depth snapshot OR a missing kline is a gap, never fabricated). Returns ascending
    JoinedBars carrying the minute close + the minute's resting-depth imbalance. PIT-clean: both inputs are
    knowable at the minute's close."""
    price_by_min: dict[int, float] = {}
    for b in price_bars:
        open_ms = int(b.ts.timestamp() * 1000)
        price_by_min[(open_ms // 60_000) * 60_000] = float(b.close)
    out: list[JoinedBar] = []
    for d in depth_bars:
        px = price_by_min.get(d.open_ms)
        if px is None or px <= 0:
            continue
        out.append(JoinedBar(open_ms=d.open_ms, close=px, imbalance=d.imbalance, n_snaps=d.n_snaps))
    out.sort(key=lambda b: b.open_ms)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Signal + simulation (pure functions on a list of JoinedBars).
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class CellResult:
    symbol: str
    venue: str
    n_bars: int
    n_snaps_total: int
    n_trades: int
    gross_edge: float          # mean per-trade GROSS return
    net_edge: float            # mean per-trade NET return (after maker round-trip cost at the GATE fee)
    gross_total_return: float
    net_total_return: float
    buy_and_hold: float
    shuffle_mean_net_edge: float
    shuffle_p_value: float     # P(rotation-null net edge >= real net edge); high => indistinguishable from null
    net_edge_14bps: float      # mean per-trade NET return at the realistic ~14bps perp-maker RT (SENSITIVITY only)
    net_total_14bps: float
    promoted: bool             # BRUT Gate verdict at the LOCKED catalog (30bps) fee
    deflated_sharpe_prob: float
    gate_reasons: list[str] = field(default_factory=list)


def _trailing_imbalance(bars: list[JoinedBar], window: int) -> list[float | None]:
    """imbalance[t] = mean of bars[t-window+1 .. t].imbalance. None during warm-up (first window-1 bars) so the
    signal is never read before a full trailing window. Pure, PIT-safe. Rolling O(n)."""
    n = len(bars)
    out: list[float | None] = [None] * n
    acc = 0.0
    for t in range(n):
        acc += bars[t].imbalance
        if t >= window:
            acc -= bars[t - window].imbalance
        if t >= window - 1:
            out[t] = acc / window
    return out


def _simulate(
    bars: list[JoinedBar],
    imbalance: list[float | None],
    *,
    cost_bps_round_trip: float,
) -> tuple[list[BTTrade], list[float], list[str], list[float]]:
    """Walk the bars; at each non-warm-up minute t with a CLOSED forward window (t+HOLD in range), if
    |imbalance[t]| >= ENTRY_THRESH and no position is open within MIN_GAP, FOLLOW the wall: long a positive
    (bid-dominant) imbalance, short a negative (ask-dominant) one. The position holds HOLD_MINUTES, exiting at
    close[t+HOLD]. Returns trades (gross pnl_pct per trade for the Gate's count+regime split), the NET-of-fee
    per-bar equity curve (base 100_000) marked each bar, parallel ISO timestamps, and gross per-trade returns
    (for the rotation-null comparison). Maker round-trip cost charged once per round-trip (at the exit bar)."""
    cost = cost_bps_round_trip / 10_000.0
    n = len(bars)
    trades: list[BTTrade] = []
    gross_per_trade: list[float] = []
    equity = [100_000.0]
    equity_ts = [bars[0].ts.isoformat()] if bars else []

    pos_dir = 0
    entry_close = 0.0
    exit_idx = -1
    last_entry_idx = -10**9
    last_mark = bars[0].close if bars else 0.0

    for t in range(1, n):
        bar = bars[t]
        ret_this_bar = 0.0
        if pos_dir != 0 and last_mark:
            ret_this_bar = pos_dir * (bar.close / last_mark - 1.0)
        last_mark = bar.close

        if pos_dir != 0 and t >= exit_idx:
            gross = pos_dir * (bar.close / entry_close - 1.0)
            net = gross - cost
            trades.append(BTTrade(entry=entry_close, exit=bar.close, pnl_pct=net, regime="chop"))
            gross_per_trade.append(gross)
            ret_this_bar -= cost  # realize the round-trip cost at the exit bar
            pos_dir = 0

        equity.append(equity[-1] * (1.0 + ret_this_bar))
        equity_ts.append(bar.ts.isoformat())

        if pos_dir == 0 and (t - last_entry_idx) >= MIN_GAP_MINUTES and (t + HOLD_MINUTES) < n:
            sig = imbalance[t]
            if sig is not None and abs(sig) >= ENTRY_THRESH:
                pos_dir = 1 if sig > 0 else -1  # FOLLOW: long a bid wall, short an ask wall
                entry_close = bar.close
                exit_idx = t + HOLD_MINUTES
                last_entry_idx = t
                last_mark = bar.close
    return trades, equity, equity_ts, gross_per_trade


def _net_buy_and_hold(bars: list[JoinedBar], cost_bps_round_trip: float) -> float:
    """The symbol's net buy-and-hold over the window (one round-trip cost on a single open+close)."""
    if len(bars) < 2 or not bars[0].close:
        return 0.0
    gross = bars[-1].close / bars[0].close - 1.0
    return gross - cost_bps_round_trip / 10_000.0


def _rotate_imbalance(bars: list[JoinedBar], offset: int) -> list[JoinedBar]:
    """Return bars with the IMBALANCE series circularly rotated by `offset` (price + timestamps untouched). This
    preserves the imbalance marginal distribution AND its autocorrelation, destroying ONLY its temporal alignment
    to the price path — the cleanest disconfirmer for a depth->price relationship. Pure."""
    n = len(bars)
    if n == 0:
        return bars
    off = offset % n
    rotated_imb = [bars[(i - off) % n].imbalance for i in range(n)]
    return [
        JoinedBar(open_ms=b.open_ms, close=b.close, imbalance=rotated_imb[i], n_snaps=b.n_snaps)
        for i, b in enumerate(bars)
    ]


def _shuffle_net_edge(bars: list[JoinedBar], cost_bps_round_trip: float, rng: random.Random) -> float:
    """ONE rotation-null draw: circularly rotate the depth-imbalance series by a random offset (>= a full holding
    window so the alignment is genuinely broken), re-run the signal + sim, return the mean per-trade NET edge. A
    genuine book-imbalance->return edge collapses toward 0 under this; price-autocorr noise survives."""
    n = len(bars)
    if n < (HOLD_MINUTES + DEPTH_WINDOW + 2):
        return 0.0
    offset = rng.randint(HOLD_MINUTES + 1, n - HOLD_MINUTES - 1)
    rotated = _rotate_imbalance(bars, offset)
    imb = _trailing_imbalance(rotated, DEPTH_WINDOW)
    trades, _e, _t, _g = _simulate(rotated, imb, cost_bps_round_trip=cost_bps_round_trip)
    if not trades:
        return 0.0
    return statistics.fmean(t.pnl_pct for t in trades)


def _run_cell(
    symbol: str,
    bars: list[JoinedBar],
    *,
    maker_round_trip_bps: float,
    rt_bps_14: float,
    gates: GateSettings,
) -> CellResult | None:
    if len(bars) < DEPTH_WINDOW + HOLD_MINUTES + 5:
        return None
    imbalance = _trailing_imbalance(bars, DEPTH_WINDOW)
    trades, equity, equity_ts, gross_per_trade = _simulate(bars, imbalance, cost_bps_round_trip=maker_round_trip_bps)
    if not trades:
        return None

    net_edge = statistics.fmean(t.pnl_pct for t in trades)
    gross_edge = statistics.fmean(gross_per_trade)
    net_total = equity[-1] / 100_000.0 - 1.0
    gross_total = math.prod(1.0 + g for g in gross_per_trade) - 1.0
    bnh = _net_buy_and_hold(bars, maker_round_trip_bps)

    # 14bps sensitivity (NOT the gate number): same trades, cheaper round-trip.
    cost14 = rt_bps_14 / 10_000.0
    net_edge_14 = statistics.fmean(g - cost14 for g in gross_per_trade)
    net_total_14 = math.prod(1.0 + (g - cost14) for g in gross_per_trade) - 1.0

    # --- rotation-null disconfirmer ---
    rng = random.Random(f"{SEED}:{symbol}")
    shuffle_edges = [_shuffle_net_edge(bars, maker_round_trip_bps, rng) for _ in range(K_SHUFFLE)]
    shuffle_mean = statistics.fmean(shuffle_edges) if shuffle_edges else 0.0
    ge_count = sum(1 for s in shuffle_edges if s >= net_edge)
    p_value = (ge_count + 1) / (len(shuffle_edges) + 1)  # one-sided, +1 smoothing

    # --- BRUT Gate via the locked path (at the catalog 30bps fee) ---
    run = _symbol_metrics(equity, trades, periods_per_year=PERIODS_PER_YEAR, equity_ts=equity_ts)
    metrics = metrics_for_run(run, trials=1, buy_and_hold=bnh, holdout_run=None)
    candidate = Candidate(
        id=f"h2-depth-follow::{symbol}@{VENUE_ID}",
        metrics=metrics,
        net_profit=net_total,
        source="h2_bookdepth_imbalance_2026_06_28",
        label=f"H2 depth-follow {symbol}",
    )
    promo = promote_brut([candidate], gates)[0]

    n_snaps_total = sum(b.n_snaps for b in bars)
    return CellResult(
        symbol=symbol, venue=VENUE_ID, n_bars=len(bars), n_snaps_total=n_snaps_total, n_trades=len(trades),
        gross_edge=gross_edge, net_edge=net_edge,
        gross_total_return=gross_total, net_total_return=net_total, buy_and_hold=bnh,
        shuffle_mean_net_edge=shuffle_mean, shuffle_p_value=p_value,
        net_edge_14bps=net_edge_14, net_total_14bps=net_total_14,
        promoted=promo.promoted, deflated_sharpe_prob=promo.deflated_sharpe_prob,
        gate_reasons=list(promo.reasons),
    )


def _maker_round_trip_bps(catalog, venue_id: str) -> tuple[float, float, float]:
    """(maker_bps, slippage_bps, round_trip_bps) for the venue from cosmu/spine/venue.py — maker-only (we do NOT
    play the taker lane). Round-trip = 2*(maker + slippage)."""
    v = catalog.venue(venue_id)
    maker = float(v.maker_fee_bps)
    slip = float(v.slippage_bps)
    return maker, slip, 2.0 * (maker + slip)


def run(symbols: list[str] | None = None, start: date = START, end: date = END) -> dict:
    catalog = default_catalog()
    maker_bps, slip_bps, rt_bps = _maker_round_trip_bps(catalog, VENUE_ID)
    rt_bps_14 = 2.0 * (PERP_MAKER_BPS_SENSITIVITY + slip_bps)  # realistic perp-maker RT for the sensitivity column
    gates = GateSettings()  # LOCKED defaults — never modified.
    syms = symbols or SMALLCAP_PERPS

    cells: list[CellResult] = []
    for symbol in syms:
        print(f"[H2] {symbol}: fetching bookDepth (±{BAND}%) + klines {start}..{end} (perp) ...", flush=True)
        depth_bars = fetch_1m_depth_bars(symbol, start, end, band=BAND)
        price_bars = fetch_1m_bars(symbol, start, end, market="perp")
        joined = join_depth_and_price(depth_bars, price_bars)
        print(
            f"[H2] {symbol}: {len(depth_bars)} depth bars, {len(price_bars)} price bars -> {len(joined)} joined",
            flush=True,
        )
        cell = _run_cell(symbol, joined, maker_round_trip_bps=rt_bps, rt_bps_14=rt_bps_14, gates=gates)
        if cell is None:
            print(f"[H2] {symbol}: SKIP (insufficient bars/trades)", flush=True)
            continue
        cells.append(cell)
        print(
            f"[H2] {symbol}: trades={cell.n_trades} gross_edge={cell.gross_edge*1e4:.2f}bps "
            f"net_edge(30bps)={cell.net_edge*1e4:.2f}bps net_edge(14bps)={cell.net_edge_14bps*1e4:.2f}bps "
            f"shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps p={cell.shuffle_p_value:.3f} "
            f"net_total={cell.net_total_return*100:.2f}% bnh={cell.buy_and_hold*100:.2f}% "
            f"DSR={cell.deflated_sharpe_prob:.3f} promoted={cell.promoted} reasons={cell.gate_reasons}",
            flush=True,
        )

    any_promoted = any(c.promoted for c in cells)
    # rotation-null verdict: the edge is "killed by the null" if no cell's real net edge is distinguishable from
    # its rotation-null at the conventional 0.05 one-sided level AND above the null mean.
    distinguishable = [c for c in cells if c.shuffle_p_value <= 0.05 and c.net_edge > c.shuffle_mean_net_edge]
    shuffle_killed = len(distinguishable) == 0
    survivors = [c for c in cells if c.promoted and c.shuffle_p_value <= 0.05 and c.net_edge > c.shuffle_mean_net_edge]

    result = {
        "experiment": "H2 resting-book-depth imbalance (FOLLOW the wall) on small-cap perps",
        "date": "2026-06-28",
        "axis": "intraday microstructure (RESTING book depth) — distinct from H1 executed-flow fade",
        "mechanism": (
            "Resting BID-depth dominance within ±BAND% of mid (a support wall + queue pressure) drifts price UP "
            "on a short horizon (Cont-Kukanov-Stoikov OBI sign). Trade WITH the imbalance (long a bid wall, short "
            "an ask wall) — directionally OPPOSITE H1's executed-flow fade, so it is hypothesis diversity."
        ),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "pre_registered": {
            "band_pct": BAND, "depth_window_minutes": DEPTH_WINDOW, "entry_thresh": ENTRY_THRESH,
            "hold_minutes": HOLD_MINUTES, "k_shuffle": K_SHUFFLE, "disconfirmer": "circular-rotation null on the imbalance series",
            "symbols": syms, "venue": VENUE_ID,
        },
        "economics": {
            "lane": "MAKER-ONLY (no taker/latency lane)",
            "gate_maker_bps": maker_bps, "slippage_bps": slip_bps, "gate_round_trip_bps": rt_bps,
            "sensitivity_perp_maker_bps": PERP_MAKER_BPS_SENSITIVITY, "sensitivity_round_trip_bps": rt_bps_14,
            "note": (
                "GATE VERDICT uses the codebase catalog fee (Binance maker 10bps spot schedule + 5bps slippage = "
                "30bps round-trip). The 14bps column (2bps realistic perp maker + 5bps slippage = 14bps RT) is a "
                "TRANSPARENT SENSITIVITY only — it is NEVER the gate number. The Gate is never loosened."
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
            "survivor_cells": [c.symbol for c in survivors],
            "kill": (not survivors),
        },
    }
    _RESULTS_JSON.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n[H2] wrote {_RESULTS_JSON}")
    v = result["verdict"]
    print(
        f"[H2] VERDICT: {'KILL' if v['kill'] else 'SURVIVOR'} | "
        f"cleared_gate={v['any_cell_cleared_brut_gate']} | shuffle_killed={v['shuffle_null_killed_it']} | "
        f"survivors={v['survivor_cells']}"
    )
    return result


# ---------------------------------------------------------------------------------------------------------------
# Tiny synthetic self-test: proves the signal/sim/rotation/Gate plumbing end-to-end with NO network.
# ---------------------------------------------------------------------------------------------------------------
def _self_test() -> None:
    rng = random.Random(1)
    bars: list[JoinedBar] = []
    price = 100.0
    open_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    # Construct a stream where a SUSTAINED bid-depth wall (held > DEPTH_WINDOW so the trailing mean crosses
    # ENTRY_THRESH) is followed by a small UP move — a real FOLLOW edge. Phase length must exceed DEPTH_WINDOW.
    cycle = 40
    for i in range(3000):
        phase = i % cycle
        drift = rng.gauss(0, 0.0004)
        if phase < 20:        # sustained bid wall -> imbalance positive -> price drifts UP (the follow edge pays)
            imb = 0.45
            drift += 0.0012
        elif phase < 26:      # neutral relax
            imb = 0.0
        else:                 # background noise
            imb = rng.gauss(0, 0.05)
        price *= 1.0 + drift
        bars.append(JoinedBar(open_ms=open_ms + i * 60_000, close=price, imbalance=imb, n_snaps=2))
    gates = GateSettings()
    cell = _run_cell("SYNTH", bars, maker_round_trip_bps=4.0, rt_bps_14=4.0, gates=gates)  # tiny cost so the injected edge shows
    assert cell is not None, "self-test: cell should run"
    assert cell.n_trades > 0, "self-test: should generate trades"
    print(
        f"[self-test] trades={cell.n_trades} net_edge={cell.net_edge*1e4:.2f}bps "
        f"shuffle_mean={cell.shuffle_mean_net_edge*1e4:.2f}bps p={cell.shuffle_p_value:.3f} "
        f"promoted={cell.promoted} reasons={cell.gate_reasons}"
    )
    # the planted edge must beat its OWN rotation-null (alignment carries real info here)
    assert cell.net_edge > cell.shuffle_mean_net_edge, "self-test: planted edge should beat rotation-null"
    assert cell.shuffle_p_value < 0.5, "self-test: planted edge should be distinguishable from the rotation-null"
    print("[self-test] OK — signal/sim/rotation/Gate plumbing verified end-to-end (no network).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="H2 resting-book-depth imbalance (follow) on small-cap perps.")
    ap.add_argument("--self-test", action="store_true", help="tiny synthetic end-to-end check, no network")
    ap.add_argument("--symbols", nargs="*", default=None, help="override the symbol set (debug)")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    else:
        run(symbols=args.symbols)
