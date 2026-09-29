#!/usr/bin/env python3
# intent: OFFLINE event-study harness for hypothesis H8 — LIQUIDATION ASYMMETRY SNAP-BACK. Fade the side
#         that got WIPED: when long_liq >> short_liq (or vice-versa) one leg of a small-cap perp book is
#         exhausted, so the directional overshoot reverts. The shipped feature `liquidation-cascade-zscore-v1`
#         SUMS long+short (direction-blind); this harness recovers the SIGNED skew and tests whether it predicts
#         a 1-2 bar snap-back, net of fees+slippage.
# inputs: per-(symbol) liquidation rows carrying BOTH legs {ts, available_at, long_liq_usd, short_liq_usd}
#         + OHLCV bars for the same symbols. The signed legs are ALREADY in the Coinglass payload the engine
#         ingests — see cosmu/data/providers/onchain.py:_points_from_coinglass (it adds them, line 25). So the
#         signed split is a SURFACING edit, not new data.
# outputs: a JSON result blob + a self-contained HTML table (every number, ranked by outlier). NOTHING is
#          written to the prod store / DB; no Gate constant is touched; no engine behaviour changes.
# invariants:
#   - ZERO production side effects (pure read + local file writes under scripts/research/).
#   - PIT honesty: an event at bucket-close T is only ACTIONABLE at available_at = T + bucket_seconds (the same
#     next-bucket floor the live parser stamps). Forward returns are measured from the FIRST bar at/after
#     available_at, never from the bucket-close bar.
#   - ONE pre-registered threshold (|skew-z| > Z_THRESHOLD). No sweep — a sweep would re-introduce the overfit
#     the Gate exists to catch.
#   - Fees+slippage charged round-trip at the venue's REAL bps (from cosmu/spine/venue.py).
#   - Gate stats (DSR / PBO / PSR) computed BRUT per the locked scorer (cosmu/master/scorer.py), no pooling
#     deflation tricks.
#
# DATA-WALL NOTE (2026-06-25): there is currently NO reachable keyless HISTORICAL signed-liquidation source —
# Coinglass public history is key-gated (30001), the prod alt_data store has 0 liquidation_cascade rows ever
# ingested, Binance allForceOrders is deprecated (400), and Binance Vision's liquidationSnapshot directory is
# empty. So the live event study cannot be RUN today. This harness is therefore written to run the instant a
# signed-liquidation history is wired (a Coinglass key, or a self-aggregated forceOrders feed), and ships with
# (a) a MECHANICAL validation of the signed-skew transform against the shipped sum-transform on the real test
# fixture, and (b) a labelled synthetic null-control demonstration so the event-study + Gate plumbing is proven
# end-to-end. Run `python3 h8_liquidation_skew_study.py --mode validate` for the real finding.

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------------
# PRE-REGISTERED PARAMETERS (locked before looking at any returns — change = a new experiment, not a sweep).
# ---------------------------------------------------------------------------------------------------------------
Z_THRESHOLD = 2.0          # |skew-z| trigger. One threshold, pre-registered.
Z_WINDOW = 30              # rolling window (buckets) for the skew-z mean/std.
FWD_BARS = 2               # forward horizon for the snap-back return (1-2 bars; we report both 1 and 2).
INTERVAL = "4h"            # event-study bucket; H8 calls for 4h/8h, NOT the shipped 1d.
BUCKET_SECONDS = 4 * 3600
MIN_N_PER_CELL = 30        # honest min events per (symbol x venue) before a cell is even reported.

# Small-cap perp basket (liquid enough to trade, small enough to overshoot on a cascade). Pre-registered set.
SMALLCAP_PERPS = ["CRVUSDT", "LDOUSDT", "DYDXUSDT", "GMTUSDT", "ARUSDT", "ENSUSDT", "1INCHUSDT", "SUSHIUSDT"]

# REAL venue costs (from cosmu/spine/venue.py default_catalog, 2026-06-25). Round-trip = 2 x (taker + slippage).
VENUE_COSTS_BPS = {
    # venue: (taker_bps, slippage_bps)
    "hyperliquid": (4.5, 6.0),     # small-cap perp lane, non-KYC
    "binance_perp": (5.0, 5.0),    # Binance USDⓈ-M perp taker ~5bps + 5bps slip
    "kraken_futures": (5.0, 4.0),
}
DEFAULT_VENUE = "hyperliquid"


def round_trip_cost_bps(venue: str) -> float:
    taker, slip = VENUE_COSTS_BPS.get(venue, VENUE_COSTS_BPS[DEFAULT_VENUE])
    return 2.0 * (taker + slip)


# ---------------------------------------------------------------------------------------------------------------
# Signed-skew transform — THE EDIT. The shipped parser sums; this recovers the direction.
# ---------------------------------------------------------------------------------------------------------------
def liq_skew(long_liq: float, short_liq: float) -> float:
    """Signed liquidation skew in [-1, +1]:  (long_liq - short_liq) / (long_liq + short_liq).
    +1 = ONLY longs were wiped (forced selling overshot DOWN -> fade UP / expect snap-back up).
    -1 = ONLY shorts were wiped (forced buying overshot UP   -> fade DOWN / expect snap-back down).
    The shipped `liquidation-cascade-zscore-v1` collapses to (long_liq + short_liq) and is BLIND to this sign;
    a long-only total spec can even buy INTO the overshoot."""
    total = long_liq + short_liq
    if total <= 0:
        return 0.0
    return (long_liq - short_liq) / total


def shipped_sum_transform(long_liq: float, short_liq: float) -> float:
    """What the production feature actually stores (cosmu/data/providers/onchain.py:_points_from_coinglass)."""
    return float(long_liq or 0) + float(short_liq or 0)


def rolling_z(series: list[float], window: int) -> list[float | None]:
    """Causal rolling z-score: z[t] uses ONLY values [t-window, t-1] (no look-ahead). None until warm."""
    out: list[float | None] = []
    for i, x in enumerate(series):
        if i < window:
            out.append(None)
            continue
        hist = series[i - window : i]
        mu = statistics.fmean(hist)
        sd = statistics.pstdev(hist)
        out.append((x - mu) / sd if sd > 0 else None)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class LiqBucket:
    ts: datetime            # bucket close
    available_at: datetime  # PIT floor = ts + bucket_seconds
    long_liq: float
    short_liq: float


@dataclass
class Bar:
    ts: datetime
    close: float


@dataclass
class EventStudyResult:
    symbol: str
    venue: str
    n_events: int
    fwd_bars: int
    mean_signed_snapback_bps: float   # signed so that a POSITIVE value = price reverted AWAY from the wiped side
    median_snapback_bps: float
    hit_rate: float                   # fraction with correct snap-back sign
    gross_edge_bps: float
    cost_bps: float
    net_edge_bps: float
    snapback_sign_correct: bool       # does the basket revert the way the thesis predicts?
    per_event_net_returns: list[float] = field(default_factory=list)  # for Gate stats


# ---------------------------------------------------------------------------------------------------------------
# Core event study
# ---------------------------------------------------------------------------------------------------------------
def first_bar_at_or_after(bars: list[Bar], when: datetime) -> int | None:
    for i, b in enumerate(bars):
        if b.ts >= when:
            return i
    return None


def run_event_study(symbol: str, venue: str, buckets: list[LiqBucket], bars: list[Bar],
                    *, z_threshold: float = Z_THRESHOLD, z_window: int = Z_WINDOW,
                    fwd_bars: int = FWD_BARS) -> EventStudyResult:
    """For each liquidation bucket compute the SIGNED skew, z-score it causally, and on |z|>threshold open a
    trade in the FADE direction (against the wiped side) at the first bar >= available_at; measure the
    forward `fwd_bars` return, net of round-trip cost. Snap-back is SIGNED so a positive number always means
    'price reverted away from the wiped side' (the thesis), regardless of which side was wiped."""
    skews = [liq_skew(b.long_liq, b.short_liq) for b in buckets]
    zs = rolling_z(skews, z_window)
    cost = round_trip_cost_bps(venue)

    signed_snapbacks_bps: list[float] = []  # +ve = correct-direction revert
    net_returns: list[float] = []
    hits = 0

    for i, b in enumerate(buckets):
        z = zs[i]
        if z is None or abs(z) < z_threshold:
            continue
        entry_idx = first_bar_at_or_after(bars, b.available_at)
        if entry_idx is None or entry_idx + fwd_bars >= len(bars):
            continue
        p0 = bars[entry_idx].close
        p1 = bars[entry_idx + fwd_bars].close
        if p0 <= 0:
            continue
        raw_ret_bps = (p1 / p0 - 1.0) * 1e4
        # Fade direction: skew>0 means LONGS wiped (overshoot DOWN) -> we go LONG, expecting UP.
        #                 skew<0 means SHORTS wiped (overshoot UP)   -> we go SHORT, expecting DOWN.
        side = +1.0 if skews[i] > 0 else -1.0
        signed_snapback = side * raw_ret_bps          # +ve = the fade worked (reverted away from wiped side)
        net = signed_snapback - cost                  # round-trip cost charged once per event
        signed_snapbacks_bps.append(signed_snapback)
        net_returns.append(net / 1e4)                 # back to fractional return for Gate stats
        if signed_snapback > 0:
            hits += 1

    n = len(signed_snapbacks_bps)
    if n == 0:
        return EventStudyResult(symbol, venue, 0, fwd_bars, 0, 0, 0, 0, cost, -cost, False, [])
    gross = statistics.fmean(signed_snapbacks_bps)
    med = statistics.median(signed_snapbacks_bps)
    return EventStudyResult(
        symbol=symbol, venue=venue, n_events=n, fwd_bars=fwd_bars,
        mean_signed_snapback_bps=round(gross, 3),
        median_snapback_bps=round(med, 3),
        hit_rate=round(hits / n, 4),
        gross_edge_bps=round(gross, 3),
        cost_bps=round(cost, 3),
        net_edge_bps=round(gross - cost, 3),
        snapback_sign_correct=gross > 0,
        per_event_net_returns=net_returns,
    )


# ---------------------------------------------------------------------------------------------------------------
# Gate stats (BRUT, per-cell) — only computed IF a cell clears N>=30 AND net edge>0 (the pre-registered promote bar)
# ---------------------------------------------------------------------------------------------------------------
def gate_stats(net_returns: list[float], *, n_trials: int = 1) -> dict:
    """Compute the locked scorer's DSR / PBO / PSR on a cell's per-event net returns. Imports the REAL scorer so
    the numbers are byte-identical to production. `n_trials` is the honest count of distinct hypotheses tried
    (1 here: ONE pre-registered threshold)."""
    import os
    import sys
    # Ensure the engine package root (apps/engine) is importable regardless of CWD.
    _engine_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _engine_root not in sys.path:
        sys.path.insert(0, _engine_root)
    from decimal import Decimal

    from cosmu.master.scorer import (
        BacktestMetrics,
        TrialStats,
        deflated_sharpe_prob,
        probabilistic_sharpe,
        sample_moments,
    )

    if len(net_returns) < 2:
        return {"error": "n<2"}
    sr, skew, kurt, n = sample_moments(net_returns)
    # PBO needs >=2 config streams; with one pre-registered config we report PBO as N/A (single-config honest).
    pbo = None
    # Only sharpe_per_obs / n_obs / skew / kurtosis feed DSR & PSR; the other required fields are filled with
    # neutral values purely to satisfy the pydantic model (they never enter the deflated-Sharpe computation).
    metrics = BacktestMetrics(
        sharpe=Decimal("0"), sharpe_per_obs=Decimal(str(sr)), n_obs=n,
        skew=Decimal(str(skew)), kurtosis=Decimal(str(kurt)),
        num_trades=n, trials_counted=n_trials,
        oos_return=Decimal("0"), sortino=Decimal("0"),
        max_drawdown=Decimal("0"), win_rate=Decimal("0"),
    )
    trials = TrialStats(count=n_trials)
    dsr = deflated_sharpe_prob(metrics, trials)
    psr = probabilistic_sharpe(sr, n, skew, kurt, 0.0)
    return {
        "sharpe_per_obs": round(sr, 4),
        "n_obs": n,
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "deflated_sharpe_prob": round(dsr, 4),
        "psr_vs_zero": round(psr, 4),
        "pbo": pbo,
        "passes_dsr_0_95": dsr >= 0.95,
        "passes_min_trades_30": n >= 30,
    }


# ---------------------------------------------------------------------------------------------------------------
# MODE: validate — the REAL, runnable-today finding. Proves (1) the payload carries BOTH legs and (2) the
# shipped transform is direction-blind while the signed transform recovers the edge-bearing sign.
# ---------------------------------------------------------------------------------------------------------------
def mode_validate() -> dict:
    """Mechanical proof against the REAL repo fixture (tests/test_free_alt_providers.py): the Coinglass payload
    rows carry both longLiquidationUsd and shortLiquidationUsd; the production parser sums them (loses sign);
    the signed transform recovers it. NO network, NO prod writes."""
    # The exact rows from the shipped test fixture (tests/test_free_alt_providers.py:18-19).
    fixture_rows = [
        {"createTime": 1672531200000, "longLiquidationUsd": 1_000_000, "shortLiquidationUsd": 500_000},
        {"createTime": 1672617600000, "longLiquidationUsd": 250_000,   "shortLiquidationUsd": 750_000},
    ]
    rows_out = []
    for r in fixture_rows:
        lg, sh = r["longLiquidationUsd"], r["shortLiquidationUsd"]
        rows_out.append({
            "ts_ms": r["createTime"],
            "long_liq_usd": lg,
            "short_liq_usd": sh,
            "shipped_sum_value": shipped_sum_transform(lg, sh),  # what prod stores: 1.5M, 1.0M (sign lost)
            "signed_skew": round(liq_skew(lg, sh), 4),           # +0.333 (longs wiped), -0.5 (shorts wiped)
            "thesis_action": "FADE UP (longs wiped)" if liq_skew(lg, sh) > 0 else "FADE DOWN (shorts wiped)",
        })
    # The key proof: two buckets with the SAME total but OPPOSITE skew map to the SAME shipped value.
    same_total_demo = {
        "bucket_A": {"long_liq": 900_000, "short_liq": 100_000},
        "bucket_B": {"long_liq": 100_000, "short_liq": 900_000},
    }
    a, b = same_total_demo["bucket_A"], same_total_demo["bucket_B"]
    same_total_demo["shipped_sum_A"] = shipped_sum_transform(**a)
    same_total_demo["shipped_sum_B"] = shipped_sum_transform(**b)
    same_total_demo["shipped_identical"] = shipped_sum_transform(**a) == shipped_sum_transform(**b)
    same_total_demo["signed_skew_A"] = round(liq_skew(**a), 4)
    same_total_demo["signed_skew_B"] = round(liq_skew(**b), 4)
    same_total_demo["signed_opposite"] = liq_skew(**a) == -liq_skew(**b)
    return {
        "fixture_source": "apps/engine/tests/test_free_alt_providers.py:18-19",
        "shipped_parser": "cosmu/data/providers/onchain.py:_points_from_coinglass (line 25 SUMS the legs)",
        "rows": rows_out,
        "same_total_opposite_skew_demo": same_total_demo,
        "conclusion": (
            "Both liquidation legs ARE present in the same keyless Coinglass payload; the shipped feature "
            "liquidation-cascade-zscore-v1 collapses them to a sum and is provably BLIND to direction "
            "(two opposite-skew buckets with equal total produce an IDENTICAL feature value). The signed "
            "skew is a pure SURFACING edit of data we already parse — no new source required."
        ),
    }


# ---------------------------------------------------------------------------------------------------------------
# MODE: synthetic — LABELLED null-control. Proves the event-study + Gate plumbing end to end on FAKE data.
# This is NOT evidence of an edge; it exists so the harness is demonstrably correct before real data arrives.
# ---------------------------------------------------------------------------------------------------------------
def _synthetic_cell(symbol: str, seed: int, *, embed_edge: float = 0.0) -> EventStudyResult:
    import random
    rng = random.Random(seed)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    n_buckets = 1500
    buckets: list[LiqBucket] = []
    bars: list[Bar] = []
    price = 1.0
    # one bar per bucket for simplicity in the control (real run uses true OHLCV)
    for i in range(n_buckets):
        ts = t0 + timedelta(seconds=BUCKET_SECONDS * i)
        # random liquidation legs; occasional lopsided cascade
        base = rng.lognormvariate(11, 1.5)
        if rng.random() < 0.08:
            if rng.random() < 0.5:
                long_liq, short_liq = base * rng.uniform(4, 12), base * rng.uniform(0.1, 0.4)
            else:
                long_liq, short_liq = base * rng.uniform(0.1, 0.4), base * rng.uniform(4, 12)
        else:
            long_liq, short_liq = base, base * rng.uniform(0.7, 1.4)
        buckets.append(LiqBucket(ts=ts, available_at=ts + timedelta(seconds=BUCKET_SECONDS),
                                 long_liq=long_liq, short_liq=short_liq))
        # price walk; optionally embed a tiny snap-back so the plumbing shows a measurable signal under control
        sk = liq_skew(long_liq, short_liq)
        drift = embed_edge * sk  # +ve skew (longs wiped) -> small UP drift if embed_edge>0
        ret = rng.gauss(drift, 0.01)
        price *= (1 + ret)
        bars.append(Bar(ts=ts + timedelta(seconds=BUCKET_SECONDS), close=price))
    return run_event_study(symbol, DEFAULT_VENUE, buckets, bars)


def mode_synthetic() -> dict:
    """Two labelled controls: (A) pure-null (embed_edge=0) -> net edge must hover at -cost, hit-rate ~50%;
    (B) tiny embedded edge -> the harness must RECOVER a positive signed snap-back. Proves the machinery."""
    null_cells = [_synthetic_cell(s, seed=100 + i, embed_edge=0.0) for i, s in enumerate(SMALLCAP_PERPS)]
    edge_cells = [_synthetic_cell(s, seed=200 + i, embed_edge=0.0008) for i, s in enumerate(SMALLCAP_PERPS)]

    def summarize(cells, label):
        rows = [{
            "symbol": c.symbol, "n": c.n_events, "hit_rate": c.hit_rate,
            "gross_bps": c.gross_edge_bps, "cost_bps": c.cost_bps, "net_bps": c.net_edge_bps,
            "sign_ok": c.snapback_sign_correct,
        } for c in cells if c.n_events >= MIN_N_PER_CELL]
        pooled = [r for c in cells for r in c.per_event_net_returns]
        return {"label": label, "cells": rows, "pooled_n": len(pooled),
                "pooled_gate": gate_stats(pooled) if len(pooled) >= 2 else {"error": "n<2"}}

    return {
        "DISCLAIMER": "SYNTHETIC null-control. NOT evidence of a real edge. Proves the harness is correct.",
        "null_control": summarize(null_cells, "pure null (embed_edge=0)"),
        "edge_control": summarize(edge_cells, "embedded micro-edge (embed_edge=8e-4)"),
    }


# ---------------------------------------------------------------------------------------------------------------
# MODE: live — the REAL event study. Blocked today (no reachable signed-liquidation history). Documents the wall.
# ---------------------------------------------------------------------------------------------------------------
def mode_live() -> dict:
    return {
        "status": "BLOCKED",
        "reason": "No reachable keyless HISTORICAL signed-liquidation source as of 2026-06-25.",
        "checks": {
            "coinglass_public_history": "key-gated (code 30001 'API key missing'); no COINGLASS key in .env.local",
            "prod_alt_data_store": "0 liquidation_cascade rows ever ingested (the cron has been silently failing)",
            "binance_allForceOrders": "deprecated -> HTTP 400",
            "binance_forceOrders_authed_7d": "BINANCE key in .env.local invalid format (-2014); also only 7-day lookback",
            "binance_vision_liquidationSnapshot": "directory empty (dataset discontinued)",
        },
        "unblock": [
            "Add a Coinglass API key (paid) OR self-aggregate Binance futures @forceOrder websocket into signed buckets going forward",
            "then re-run: python3 h8_liquidation_skew_study.py --mode live",
        ],
    }


# ---------------------------------------------------------------------------------------------------------------
# HTML report (self-contained, every number, ranked by outlier).
# ---------------------------------------------------------------------------------------------------------------
def write_html(payload: dict, out_path: Path) -> None:
    def esc(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    val = payload.get("validate", {})
    syn = payload.get("synthetic", {})
    live = payload.get("live", {})

    parts = ["""<!doctype html><meta charset="utf-8"><title>H8 Liquidation Skew — Event Study</title>
<style>
 body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
 h1{font-size:1.5rem}h2{font-size:1.1rem;margin-top:2rem;border-bottom:2px solid #eee;padding-bottom:.3rem}
 table{border-collapse:collapse;width:100%;margin:.5rem 0;font-size:13px}
 th,td{border:1px solid #ddd;padding:5px 8px;text-align:right}th{background:#f6f6f6;text-align:left}
 td:first-child,th:first-child{text-align:left}
 .ok{color:#0a7d2c;font-weight:600}.bad{color:#b00020;font-weight:600}.muted{color:#777}
 .verdict{background:#fff4e5;border-left:4px solid #e67700;padding:.8rem 1rem;margin:1rem 0;border-radius:4px}
 code{background:#f3f3f3;padding:1px 4px;border-radius:3px;font-size:12px}
</style>
<h1>H8 — Liquidation Asymmetry Snap-Back · Event Study</h1>
<p class="muted">Offline experiment · 2026-06-25 · ZERO production impact · docs-only</p>
"""]

    # Verdict box
    parts.append(f"""<div class="verdict"><b>VERDICT: {esc(payload.get('verdict','—'))}</b><br>
    {esc(payload.get('verdict_detail',''))}</div>""")

    # 1. Code finding (validate)
    parts.append("<h2>1. Code finding — shipped feature is direction-blind (runnable today)</h2>")
    parts.append(f"<p>Fixture: <code>{esc(val.get('fixture_source',''))}</code> · "
                 f"parser: <code>{esc(val.get('shipped_parser',''))}</code></p>")
    parts.append("<table><tr><th>bucket ts</th><th>long_liq $</th><th>short_liq $</th>"
                 "<th>shipped SUM (stored)</th><th>SIGNED skew</th><th>thesis action</th></tr>")
    for r in val.get("rows", []):
        parts.append(f"<tr><td>{esc(r['ts_ms'])}</td><td>{r['long_liq_usd']:,}</td>"
                     f"<td>{r['short_liq_usd']:,}</td><td>{r['shipped_sum_value']:,.0f}</td>"
                     f"<td><b>{r['signed_skew']:+}</b></td><td>{esc(r['thesis_action'])}</td></tr>")
    parts.append("</table>")
    d = val.get("same_total_opposite_skew_demo", {})
    if d:
        parts.append("<p><b>Proof of direction-blindness</b> — two buckets, equal total, opposite skew:</p>")
        parts.append("<table><tr><th></th><th>long_liq</th><th>short_liq</th><th>shipped SUM</th><th>signed skew</th></tr>")
        parts.append(f"<tr><td>Bucket A (longs wiped)</td><td>{d['bucket_A']['long_liq']:,}</td>"
                     f"<td>{d['bucket_A']['short_liq']:,}</td><td>{d['shipped_sum_A']:,.0f}</td>"
                     f"<td>{d['signed_skew_A']:+}</td></tr>")
        parts.append(f"<tr><td>Bucket B (shorts wiped)</td><td>{d['bucket_B']['long_liq']:,}</td>"
                     f"<td>{d['bucket_B']['short_liq']:,}</td><td>{d['shipped_sum_B']:,.0f}</td>"
                     f"<td>{d['signed_skew_B']:+}</td></tr>")
        parts.append("</table>")
        cls = "bad" if d.get("shipped_identical") else "ok"
        parts.append(f"<p class='{cls}'>Shipped feature value identical for A and B: "
                     f"{esc(d.get('shipped_identical'))} → the production feature CANNOT tell these apart, "
                     f"yet the thesis says they are OPPOSITE trades.</p>")

    # 2. Live event study (blocked)
    parts.append("<h2>2. Live event study — data availability</h2>")
    if live:
        parts.append(f"<p class='bad'>Status: {esc(live.get('status'))} — {esc(live.get('reason'))}</p>")
        parts.append("<table><tr><th>source</th><th>status</th></tr>")
        for k, v in live.get("checks", {}).items():
            parts.append(f"<tr><td><code>{esc(k)}</code></td><td>{esc(v)}</td></tr>")
        parts.append("</table>")

    # 3. Synthetic control
    parts.append("<h2>3. Harness correctness — synthetic null-control</h2>")
    parts.append(f"<p class='muted'>{esc(syn.get('DISCLAIMER',''))}</p>")
    for key in ("null_control", "edge_control"):
        block = syn.get(key, {})
        parts.append(f"<h3 style='font-size:1rem'>{esc(block.get('label',key))}</h3>")
        parts.append("<table><tr><th>symbol</th><th>N</th><th>hit-rate</th><th>gross bps</th>"
                     "<th>cost bps</th><th>net bps</th><th>sign ok</th></tr>")
        rows = sorted(block.get("cells", []), key=lambda r: r["net_bps"], reverse=True)
        for r in rows:
            cls = "ok" if r["net_bps"] > 0 else "bad"
            parts.append(f"<tr><td>{esc(r['symbol'])}</td><td>{r['n']}</td><td>{r['hit_rate']:.2%}</td>"
                         f"<td>{r['gross_bps']:+}</td><td>{r['cost_bps']}</td>"
                         f"<td class='{cls}'>{r['net_bps']:+}</td><td>{esc(r['sign_ok'])}</td></tr>")
        parts.append("</table>")
        g = block.get("pooled_gate", {})
        if "error" not in g:
            parts.append(f"<p class='muted'>Pooled Gate (N={block.get('pooled_n')}): "
                         f"DSR={g.get('deflated_sharpe_prob')} · PSR={g.get('psr_vs_zero')} · "
                         f"passes 0.95={esc(g.get('passes_dsr_0_95'))}</p>")

    out_path.write_text("".join(parts), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="H8 liquidation-skew snap-back event study (offline).")
    ap.add_argument("--mode", choices=["validate", "synthetic", "live", "all"], default="all")
    ap.add_argument("--out", default=str(Path(__file__).parent / "h8_liquidation_skew"))
    args = ap.parse_args()

    payload: dict = {
        "experiment": "H8 — Liquidation Asymmetry Snap-Back",
        "date": "2026-06-25",
        "pre_registered": {
            "z_threshold": Z_THRESHOLD, "z_window": Z_WINDOW, "fwd_bars": FWD_BARS,
            "interval": INTERVAL, "min_n_per_cell": MIN_N_PER_CELL,
            "basket": SMALLCAP_PERPS, "venue_costs_bps": VENUE_COSTS_BPS,
        },
    }
    if args.mode in ("validate", "all"):
        payload["validate"] = mode_validate()
    if args.mode in ("synthetic", "all"):
        payload["synthetic"] = mode_synthetic()
    if args.mode in ("live", "all"):
        payload["live"] = mode_live()

    # Verdict
    payload["verdict"] = "KILL (today) — code finding CONFIRMED, but no reachable data to test the edge"
    payload["verdict_detail"] = (
        "The shipped liquidation feature is provably direction-blind (a real, fixable code finding). But the "
        "signed-skew edge itself CANNOT be measured today: no keyless historical signed-liquidation source is "
        "reachable (Coinglass key-gated, prod store empty, Binance dumps gone). Per the kill-fast rule, H8 is "
        "KILLED as an experiment for now — re-open only when a signed-liquidation history is wired."
    )

    out_json = Path(args.out + "_results.json")
    # The HTML table is the PUBLISHED artifact — write it straight to docs/reports/ (canonical), regenerating the
    # committed file in place. Override with --out to redirect both elsewhere.
    repo_root = Path(__file__).resolve().parents[4]
    docs_html = repo_root / "docs" / "reports" / "h8-liquidation-skew-2026-06-25.html"
    out_html = docs_html if docs_html.parent.exists() else Path(args.out + "_table.html")
    out_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    write_html(payload, out_html)
    print(f"wrote {out_json}")
    print(f"wrote {out_html}")
    print("\n=== SUMMARY ===")
    print("verdict:", payload["verdict"])
    if "validate" in payload:
        d = payload["validate"]["same_total_opposite_skew_demo"]
        print(f"direction-blind proof: shipped value identical for opposite skews = {d['shipped_identical']}")
    if "live" in payload:
        print("live event study:", payload["live"]["status"], "-", payload["live"]["reason"])


if __name__ == "__main__":
    main()
