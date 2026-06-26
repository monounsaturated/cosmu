# intent: THE REAL TEST — the #401 Polymarket intraday over-extension MAKER fade, now HELD TO RESOLUTION and
# SETTLED at the authoritative UMA $1/$0 payout (#422: ExitRules.settle_at_resolution / data/backtest.py
# settle-at-resolution + adapters/data/prediction.py resolution()). EXPERIMENT ONLY, offline, keyless, docs-only.
#
# WHY THIS RUN EXISTS. Three siblings already ran:
#   #400 (capstone): intraday over-extension fade, TAKER, exit K=6h. GROSS reversion edge REAL (+0.70c/$1
#         pooled, DSR=1.0) but a TAKER round-trip pays the wide CLOB spread → NET −2.86c. Dead as a taker.
#   #401 (maker feasibility): same fade, MAKER (earn half-spread), exit STILL K=6h (intraday time-stop). Could
#         NOT settle to resolution — it only had the hourly midpoint path, so it exited at the K-hour mark and
#         estimated a maker-net that was plausibly POSITIVE pooled (+1.68c expected) but FILL-sensitive and
#         FEE-sensitive (geopolitics-only; sports dies on the 3% fee). Verdict: "worth a small live test."
#   #422 (the join this run uses): the authoritative UMA resolution settlement now exists — a held-to-resolution
#         position can be closed at the TRUE $1/$0 payout instead of marking at the last odds quote.
#
# THE QUESTION THIS RUN ANSWERS (the one #401 explicitly deferred). Does the maker fade CLEAR THE BRUT GATE,
# net of honest costs, when the position is HELD TO RESOLUTION and settled at the real $1/$0 — instead of the
# arbitrary K-hour intraday exit #401 was forced into? This is a DIFFERENT trade from #400/#401:
#   • #400/#401 = intraday: open the fade, close it K hours later at the mid. The resolution tail is NOT in the
#     P&L (the trade is flat well before resolution). The cost is the SPREAD.
#   • THIS run = held-to-resolution: open the fade as a MAKER, then HOLD the YES/short-YES position to the
#     chain's settlement and book the true $1/$0. The resolution tail IS the P&L. The cost is the spread
#     (entry only — settlement is free, no redemption fee, no exit slippage; mirrors backtest.py:783) + fee.
#
# Holding a fade to resolution is the OPPOSITE horizon of the intraday snap-back thesis and is much closer to
# H9 (the favorite-longshot hold that DIED on the survivorship tail). So this is a genuine, adversarial test:
# the intraday gross edge was real, but does it SURVIVE being held all the way to the binary outcome? If the
# snap-back is an intraday microstructure effect, holding to resolution should GIVE IT BACK (the odds the fade
# shorted may well have been RIGHT — they converged to the outcome). We let the real $1/$0 settle that.
#
# HONESTY (same mandate as #401, tightened by the real settlement):
#   • The signal is the #400 pre-registered rule, imported BYTE-IDENTICAL (no sweep, ONE (Nσ,K) config). K_HOURS
#     here is NOT an exit — it is only the #400 fill-window/non-overlap bookkeeping; the EXIT is resolution.
#   • Execution is MAKER: earn the half-spread credit, model adverse selection via the #401 fill classification
#     on the realized fill window (FAVORABLE/ADVERSE/NO_FILL). NO_FILL events are dropped (the passive-order tax).
#   • The position then SETTLES at the true $1/$0 — read straight off each market's UMA-settled terminal_yes
#     (Gamma outcomePrices, the same authoritative label #400 already carries as `terminal_yes`). This is the
#     #422 join expressed on the offline keyless path: terminal_yes IS the resolution payout, and it is only
#     ever the resolved market's final outcome (PIT-honest: the fade entered ≥ FINAL_EXCLUDE_HOURS before the
#     deadline, and settlement is applied only at resolution, never before).
#   • Costs: maker half-spread credit (entry), category fee (geo 0% / sports 3%), settlement free (no redemption
#     fee, no slippage — exactly backtest.py:783). The spread band + the worst/expected/best fill scenarios are
#     swept exactly as #401, so the verdict is calibrated to the same declared uncertainty.
#   • LEAKAGE TRIPWIRE FIRST: before any P&L, the odds series AND the resolution settlement are gated through
#     research/prediction_tripwire.audit_prediction_cell (available_at audit + shuffle-null + forward-shift on the
#     odds; PIT-honest $1/$0 check on the resolution). A cell that fails the tripwire is EXCLUDED.
#   • BRUT GATE: judge each category on its OWN per-trade NET P&L through cosmu/master/scorer.py
#     (DSR / min-trades), the production scorer, byte-identical. NO pooling across categories for the verdict.
#
# ZERO production impact: read-only keyless fetches, persists NOTHING, no Gate constant touched, no cron,
# docs-only. Writes a disposable HTML table + prints a JSON summary. Run:
#   python3 apps/engine/scripts/research/polymarket_maker_gate.py [--max-events N] [--per-cat-budget N]

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import fmean, median, pstdev

# Make `cosmu` importable + reuse the #400 capstone harness verbatim (discovery, windowed hourly odds, the
# Market dataclass, spread calibration, the BRUT scorer wrapper). This is the ONLY production touch and it is
# import-path plumbing for an offline research script. The maker + resolution layers are built entirely on top.
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from scripts.research.polymarket_intraday_overextension import (  # noqa: E402
    FINAL_EXCLUDE_HOURS,
    K_HOURS,
    MAX_ENTRY_P,
    MIN_BARS_PER_MARKET,
    MIN_ENTRY_P,
    MOVE_HORIZON_H,
    Z_ENTRY,
    Z_LOOKBACK,
    Market,
    _fetch,  # noqa: F401 — kept for parity / live realism if needed
    calibrate_spread,
    discover,
    gate_stats,
    hourly_odds,
)

# The #401 maker model — fill classification + the per-scenario sensitivity band — imported BYTE-IDENTICAL.
from scripts.research.polymarket_maker_feasibility import (  # noqa: E402
    ADVERSE_CAP,  # noqa: F401 — declared for provenance
    FILL_WINDOW_H,
    SCENARIOS,
    SPREAD_BAND,
    SPREAD_PRIMARY,
    TICK,
    Scenario,
    _signed_gross,
)

_CAT_FEE = {"geopolitics": 0.0, "sports": 0.03}


# ==========================================================================================================
# THE MAKER-HELD-TO-RESOLUTION EVENT. Same #400 over-extension signal + #401 maker fill classification, but the
# EXIT is the authoritative $1/$0 settlement instead of the K-hour intraday mark. We reconstruct each #400 event
# ourselves so we hold the full realized fill window AND the terminal resolution payout.
# ==========================================================================================================
@dataclass
class MakerResolveEvent:
    condition_id: str
    question: str
    category: str
    signal_ts: datetime
    side: str               # short_yes (faded an up-spike) / long_yes (faded a down-spike)
    z: float
    p_signal: float         # odds at the signal bar (the taker entry)
    peak_run: float         # max adverse (spike-direction) excursion over the fill window (prob units)
    p_fill_favorable: float # ~p_signal (resting order fills at the touch)
    p_fill_adverse: float   # p_signal + peak_run (filled after the over-run; deeper, worse entry)
    fill_class: str         # FAVORABLE / ADVERSE / NO_FILL
    terminal_yes: float     # the UMA-settled $1/$0 YES payout (the resolution exit) — #422 settle target
    hours_to_deadline: float
    faded_winner: bool      # did we fade the side that EVENTUALLY won? (the survivorship decomposition)


def build_maker_resolve_events(m: Market, series: list[tuple[datetime, float]]) -> list[MakerResolveEvent]:
    """Reconstruct the #400 non-overlapping fades, classify the #401 maker fill on the realized fill window, and
    attach the market's authoritative terminal_yes as the resolution EXIT. PIT: the z-score at entry uses ONLY
    bars[:i+1]; the fill window reads FORWARD bars (legitimate — that is execution simulation, not the signal);
    the resolution payout is the chain's terminal outcome, applied only at settlement (the fade entered
    ≥ FINAL_EXCLUDE_HOURS before the deadline, so the entry never peeks the outcome)."""
    n = len(series)
    if n < MIN_BARS_PER_MARKET:
        return []
    ts = [t for t, _ in series]
    p = [v for _, v in series]
    deadline_ts = m.deadline.timestamp()
    out: list[MakerResolveEvent] = []
    i = Z_LOOKBACK + MOVE_HORIZON_H
    # need room for the fill window AFTER the signal (the resolution exit is in the far future, no bar needed)
    while i + FILL_WINDOW_H < n:
        entry_t = ts[i]
        if (deadline_ts - entry_t.timestamp()) / 3600.0 <= FINAL_EXCLUDE_HOURS:
            break  # never enter inside the final convergence window (same #400 disconfirmer-2 control)
        moves = [p[j] - p[j - MOVE_HORIZON_H] for j in range(i - Z_LOOKBACK + 1, i + 1)]
        assert ts[i] == entry_t, "z-window peeked past the entry bar (look-ahead)"
        mu = fmean(moves)
        sd = pstdev(moves)
        if sd <= 1e-9:
            i += 1
            continue
        z = (p[i] - p[i - MOVE_HORIZON_H] - mu) / sd
        p_signal = p[i]
        if not (MIN_ENTRY_P <= p_signal <= MAX_ENTRY_P) or abs(z) < Z_ENTRY:
            i += 1
            continue
        side = "short_yes" if z > 0 else "long_yes"

        # --- #401 maker fill classification on the realized fill window (bars i+1 .. i+FILL_WINDOW_H) ---
        win = p[i + 1 : i + 1 + FILL_WINDOW_H]
        if side == "short_yes":
            peak_run = max((q - p_signal) for q in win) if win else 0.0   # how far UP it ran (adverse)
        else:
            peak_run = max((p_signal - q) for q in win) if win else 0.0   # how far DOWN it ran (adverse)
        peak_run = max(0.0, peak_run)
        first_move = (
            (p_signal - win[0]) if (side == "short_yes" and win) else ((win[0] - p_signal) if win else 0.0)
        )
        reverted_first = (first_move > TICK) and (peak_run <= TICK)
        if reverted_first:
            fill_class = "NO_FILL"
        elif peak_run <= TICK:
            fill_class = "FAVORABLE"
        else:
            fill_class = "ADVERSE"

        p_fill_favorable = p_signal
        p_fill_adverse = (p_signal + peak_run) if side == "short_yes" else (p_signal - peak_run)

        faded_winner = (side == "short_yes" and m.terminal_yes >= 0.5) or (
            side == "long_yes" and m.terminal_yes < 0.5
        )

        out.append(
            MakerResolveEvent(
                condition_id=m.condition_id, question=m.question, category=m.category,
                signal_ts=entry_t, side=side, z=z, p_signal=p_signal,
                peak_run=peak_run,
                p_fill_favorable=p_fill_favorable, p_fill_adverse=p_fill_adverse,
                fill_class=fill_class, terminal_yes=m.terminal_yes,
                hours_to_deadline=(deadline_ts - entry_t.timestamp()) / 3600.0,
                faded_winner=faded_winner,
            )
        )
        # non-overlapping per market: next entry only after a cooldown past the fill window (the resolution exit
        # is shared across the market's life, so we just space the entries the way #400 spaced its trades).
        i = i + 1 + FILL_WINDOW_H + K_HOURS + 6
    return out


# ==========================================================================================================
# THE P&L — maker fill price (entry) → TRUE $1/$0 settlement (exit), net of the half-spread credit + fee.
# ==========================================================================================================
#
# Per FILLED event, per $1 of YES notional:
#   entry price = the maker fill price (FAVORABLE: ~p_signal; ADVERSE: p_signal + capture*peak_run — a deeper,
#                 worse over-extension level we got picked off at).
#   exit = the authoritative terminal_yes ∈ {1.0, 0.0} (the #422 settlement; free, no slippage, no redemption fee).
#   gross(fill→resolution) = (fill_p − terminal_yes) for short_yes ; (terminal_yes − fill_p) for long_yes.
#   maker credit = hs_frac × round_trip_spread, earned ONCE (the entry is the only maker leg — the exit is the
#                  chain settlement, which is free and not a maker fill, so there is no second half-spread to earn).
#   fee = category fee (geo 0% / sports 3%), charged once on the round-trip notional (today's schedule).
#   NET = gross(fill→resolution) + maker_credit − fee.
# NO_FILL events drop out of the book (the passive-order tax — those were the immediate reverters a resting order
# misses; here, held-to-resolution, they would have settled too, but a passive order never positioned for them).

def maker_resolve_pnls(events: list[MakerResolveEvent], spread_rt: float, sc: Scenario) -> list[float]:
    """The per-$1 maker-held-to-resolution NET P&L under one scenario + one round-trip-spread level. Each #401
    fill assumption is applied explicitly and traceably (the SAME deterministic hash-based fill-keep as #401, so
    the scenario fill mixes are byte-comparable across the two studies). The EXIT differs: it is always the
    authoritative $1/$0 terminal payout, never a K-hour intraday mark."""
    credit = sc.hs_frac * spread_rt  # the maker spread credit earned on the (single) maker entry leg
    pnls: list[float] = []
    for e in events:
        fee = _CAT_FEE[e.category]
        payout = e.terminal_yes  # the true $1/$0 resolution exit (#422 settlement)
        if e.fill_class == "FAVORABLE":
            if sc.favorable_keep >= 1.0 or (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.favorable_keep:
                g = _signed_gross(e.side, e.p_fill_favorable, payout)
                pnls.append(g + credit - fee)
        elif e.fill_class == "ADVERSE":
            if sc.adverse_keep >= 1.0 or (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.adverse_keep:
                run = sc.adverse_capture * e.peak_run
                fill_p = (e.p_signal + run) if e.side == "short_yes" else (e.p_signal - run)
                g = _signed_gross(e.side, fill_p, payout)
                pnls.append(g + credit - fee)
        else:  # NO_FILL
            if sc.nofill_rescue > 0.0 and (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.nofill_rescue:
                g = _signed_gross(e.side, e.p_fill_favorable, payout)
                pnls.append(g + credit - fee)
    return pnls


def summarize(events: list[MakerResolveEvent], category: str | None) -> dict:
    evs = events if category is None else [e for e in events if e.category == category]
    n = len(evs)
    if n == 0:
        return {"category": category or "ALL", "n": 0}
    classes = Counter(e.fill_class for e in evs)
    fee_note = "mixed" if category is None else f"{_CAT_FEE[category]*100:.0f}%"

    # The GROSS held-to-resolution edge (taker view: fill at p_signal, settle at $1/$0), the honest baseline the
    # maker credit then adds to. This is the number that tells you whether holding the fade to resolution GIVES
    # the intraday gross edge BACK or KEEPS it.
    gross_taker_resolve = [_signed_gross(e.side, e.p_signal, e.terminal_yes) for e in evs]
    fw = [_signed_gross(e.side, e.p_signal, e.terminal_yes) for e in evs if e.faded_winner]
    fl = [_signed_gross(e.side, e.p_signal, e.terminal_yes) for e in evs if not e.faded_winner]
    adverse_runs = [e.peak_run for e in evs if e.fill_class == "ADVERSE"]
    nofill = [e for e in evs if e.fill_class == "NO_FILL"]
    nofill_gross = [_signed_gross(e.side, e.p_signal, e.terminal_yes) for e in nofill]

    out = {
        "category": category or "ALL", "n": n, "fee": fee_note,
        "fill_class_counts": dict(classes),
        "fill_class_pct": {k: round(v / n, 4) for k, v in classes.items()},
        "mean_gross_taker_resolve": fmean(gross_taker_resolve),
        "reverts_to_resolution": fmean(gross_taker_resolve) > 0,
        "n_faded_winner": len(fw), "n_faded_loser": len(fl),
        "mean_gross_faded_winner": fmean(fw) if fw else 0.0,
        "mean_gross_faded_loser": fmean(fl) if fl else 0.0,
        "n_adverse": len(adverse_runs),
        "mean_adverse_overrun": fmean(adverse_runs) if adverse_runs else 0.0,
        "n_nofill": len(nofill_gross),
        "mean_gross_forfeited_to_nofill": fmean(nofill_gross) if nofill_gross else 0.0,
        "scenarios": {},
    }
    spread_rt = SPREAD_BAND[SPREAD_PRIMARY]
    for sc in SCENARIOS:
        pnls = maker_resolve_pnls(evs, spread_rt, sc)
        if not pnls:
            out["scenarios"][sc.name] = {"n_filled": 0}
            continue
        gate = gate_stats(pnls)
        out["scenarios"][sc.name] = {
            "n_filled": len(pnls),
            "fill_rate": round(len(pnls) / n, 4),
            "mean_maker_net": fmean(pnls),
            "median_maker_net": median(pnls),
            "win_rate": sum(1 for x in pnls if x > 0) / len(pnls),
            "deflated_sharpe_prob": gate.get("deflated_sharpe_prob"),
            "passes_min_trades": gate.get("passes_min_trades"),
            "passes_dsr": gate.get("passes_dsr"),
            "passes_gate": gate.get("passes_gate"),
            "assumptions": {
                "hs_frac": sc.hs_frac, "favorable_keep": sc.favorable_keep,
                "adverse_keep": sc.adverse_keep, "nofill_rescue": sc.nofill_rescue,
                "adverse_capture": sc.adverse_capture, "spread_rt": spread_rt,
            },
        }
    # spread sensitivity for the EXPECTED scenario (maker credit RISES with spread — the passive economics)
    expected = next(s for s in SCENARIOS if s.name == "expected")
    out["expected_by_spread"] = {
        name: (round(fmean(maker_resolve_pnls(evs, s, expected)), 6)
               if maker_resolve_pnls(evs, s, expected) else None)
        for name, s in SPREAD_BAND.items()
    }
    # NO-CREDIT FLOOR — strip the half-spread credit entirely (hs_frac=0). The maker P&L from the realized fill
    # prices → true settlement alone, every fill kept. If even +credit can't lift this above zero net of fees,
    # the spread gain is being eaten. This is the most honest floor.
    no_credit = Scenario("no_credit", hs_frac=0.0, favorable_keep=1.0, adverse_keep=1.0,
                         nofill_rescue=0.0, adverse_capture=1.0)
    nc = maker_resolve_pnls(evs, SPREAD_BAND[SPREAD_PRIMARY], no_credit)
    if nc:
        nc_gate = gate_stats(nc)
        out["no_credit_floor"] = {
            "n_filled": len(nc), "mean_maker_net": fmean(nc),
            "win_rate": sum(1 for x in nc if x > 0) / len(nc),
            "deflated_sharpe_prob": nc_gate.get("deflated_sharpe_prob"),
            "passes_gate": nc_gate.get("passes_gate"),
        }
    return out


# ==========================================================================================================
# LEAKAGE TRIPWIRE — gate the odds + resolution series through research/prediction_tripwire BEFORE any P&L.
# We build AltDataPoint odds + a single $1/$0 resolution point per cell from the SAME series the backtest reads,
# then run audit_prediction_cell (available_at audit + shuffle-null + forward-shift on the odds; PIT-honest
# binary settlement check on the resolution). A cell that FAILS is excluded from the gate population.
# ==========================================================================================================
def tripwire_cell(m: Market, series: list[tuple[datetime, float]]) -> dict:
    """Run the prediction-lane leakage tripwire on ONE market's odds + resolution series. Returns a dict verdict.
    The odds AltDataPoints are stamped available_at == ts (CLOB quotes are known at quote time, no lag — exactly
    the PredictionDataAdapter contract). The resolution point is the terminal $1/$0 at the deadline, available
    only AT resolution (available_at == deadline >= ts) — the PIT-honest settlement the tripwire requires."""
    from cosmu.data.market import Bar
    from cosmu.data.providers._types import AltDataPoint
    from cosmu.research.prediction_tripwire import audit_prediction_cell

    if len(series) < MIN_BARS_PER_MARKET:
        return {"condition_id": m.condition_id, "passed": False, "reasons": ("too_few_bars",)}
    odds_points = [AltDataPoint(ts=t, available_at=t, value=v) for t, v in series]
    bars = [
        Bar(ts=t, open=v, high=v, low=v, close=v, volume=0.0)  # odds bar (the share price IS the probability)
        for t, v in series
    ]
    # the resolution settlement point — the authoritative $1/$0, knowable ONLY at the resolution time (deadline).
    res_points = [AltDataPoint(ts=m.deadline, available_at=m.deadline, value=float(m.terminal_yes))]
    try:
        r = audit_prediction_cell(
            condition_id=m.condition_id, odds_points=odds_points, bars=bars,
            resolution_points=res_points, metric="odds_60", horizon=1, shuffle_trials=120, seed=0,
        )
    except Exception as exc:  # noqa: BLE001 — a tripwire crash on a degenerate series = exclude, never bless
        return {"condition_id": m.condition_id, "passed": False, "reasons": (f"tripwire_error:{exc}",)}
    return {
        "condition_id": m.condition_id,
        "passed": bool(r.passed),
        "resolution_pit_ok": bool(r.resolution_pit_ok),
        "reasons": tuple(r.reasons),
        "real_ic": (r.odds_report.real_ic if r.odds_report else None),
        "shuffle_survives": (r.odds_report.shuffle.survives if r.odds_report else None),
        "available_at_pass": (r.odds_report.available_at.passed if r.odds_report else None),
        "forward_shift_pass": (r.odds_report.forward_shift.passed if r.odds_report else None),
    }


# ==========================================================================================================
# HTML (disposable — surfaces every event + the decomposition, per the surface-all-compute rule).
# ==========================================================================================================
def render_html(events: list[MakerResolveEvent], cats: list[dict], pooled: dict, meta: dict, tw: dict) -> str:
    def f(x, d=4):
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else str(x)

    def scen_cell(s: dict, key: str) -> str:
        sc = s.get("scenarios", {}).get(key, {})
        if not sc.get("n_filled"):
            return "<td>—</td><td>—</td><td>—</td>"
        cls = "pass" if sc.get("passes_gate") else ("pos" if sc["mean_maker_net"] > 0 else "neg")
        return (f"<td class='{cls}'><b>{f(sc['mean_maker_net'])}</b></td>"
                f"<td>{f(sc['fill_rate'],2)}</td><td>{f(sc.get('deflated_sharpe_prob') or 0,3)}</td>")

    cat_rows = []
    for s in cats + [pooled]:
        if s.get("n", 0) == 0:
            continue
        fc = s["fill_class_pct"]
        ncf = s.get("no_credit_floor", {})
        cat_rows.append(
            f"<tr><td><b>{s['category']}</b></td><td>{s['n']}</td><td>{s['fee']}</td>"
            f"<td>{f(fc.get('FAVORABLE',0),2)}/{f(fc.get('ADVERSE',0),2)}/{f(fc.get('NO_FILL',0),2)}</td>"
            f"<td><b>{f(s['mean_gross_taker_resolve'])}</b><br>"
            f"<span class=sub>{'reverts' if s['reverts_to_resolution'] else 'ADVERSE@resolution'}</span></td>"
            f"<td>{f(s['mean_gross_faded_winner'])} / {f(s['mean_gross_faded_loser'])}</td>"
            f"<td>{f(ncf.get('mean_maker_net',0))}</td>"
            + scen_cell(s, "worst") + scen_cell(s, "expected") + scen_cell(s, "best")
            + "</tr>"
        )

    rows = []
    for e in sorted(events, key=lambda x: (x.category, x.fill_class, -abs(x.z)))[:4000]:
        cls = {"FAVORABLE": "rev", "ADVERSE": "adv", "NO_FILL": "nf"}[e.fill_class]
        g = _signed_gross(e.side, e.p_signal, e.terminal_yes)
        rows.append(
            f"<tr class='{cls}'><td>{e.category}</td><td class='q'>{e.question}</td>"
            f"<td>{e.signal_ts.strftime('%Y-%m-%d %H:%M')}</td><td>{f(e.hours_to_deadline,0)}</td>"
            f"<td>{e.side}</td><td>{f(e.z,2)}</td><td>{f(e.p_signal,3)}</td>"
            f"<td>{f(e.peak_run,3)}</td><td>{int(e.terminal_yes)}</td>"
            f"<td>{'WIN' if e.faded_winner else 'lose'}</td>"
            f"<td><b>{e.fill_class}</b></td><td>{f(g)}</td></tr>"
        )

    twc = tw.get("counts", {})
    return f"""<!doctype html><meta charset=utf-8>
<title>Polymarket MAKER held-to-resolution — Gate test — {meta['generated']}</title>
<style>
 body{{font:13px/1.5 -apple-system,system-ui,sans-serif;margin:24px;color:#111;background:#fafafa}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:26px}}
 table{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0;font-size:12px}}
 th,td{{border:1px solid #ddd;padding:4px 7px;text-align:right}} td.q{{text-align:left;max-width:280px}}
 th{{background:#f0f0f0}} td:first-child,td.q{{text-align:left}}
 tr.rev{{background:#f5fbf5}} tr.adv{{background:#fff4f4}} tr.nf{{background:#f4f4ff}}
 td.pass{{background:#bff0bf;font-weight:700}} td.pos{{background:#eafbea;font-weight:700}} td.neg{{background:#f8d8d8;font-weight:700}}
 .meta{{color:#555;font-size:12px}} .sub{{color:#888;font-size:10px}} .k{{font-weight:700}}
</style>
<h1>Polymarket over-extension MAKER fade — HELD TO RESOLUTION — BRUT Gate test (EXPERIMENT ONLY)</h1>
<p class=meta>Generated {meta['generated']} · the #400 GROSS intraday reversion edge is real but a TAKER pays the
spread (net −2.86c) and #401's MAKER estimate was plausibly positive but exited at an arbitrary K-hour mark and
<b>could not settle to resolution</b>. THIS run holds the maker fade to the authoritative UMA <b>$1/$0
settlement</b> (#422) — the real test. {meta['n_markets']} resolved binaries, {meta['n_with_series']} with hourly
series, <b>{meta['n_events']} over-extension events</b> after the leakage tripwire. Keyless Gamma+CLOB · ZERO prod
impact.</p>

<h2>Leakage tripwire (gated BEFORE any P&L)</h2>
<p class=meta>Cells audited={tw.get('n_audited',0)} · <span class=k>PASS={twc.get('pass',0)}</span> ·
FAIL={twc.get('fail',0)}. Odds series: available_at audit + shuffle-null + forward-shift; resolution: PIT-honest
$1/$0 settlement. Only PASS cells enter the gate population. Top failure reasons: {tw.get('top_reasons','—')}.</p>

<h2>Per-category MAKER-held-to-resolution decomposition — worst / expected / best (BRUT, spread {SPREAD_BAND[SPREAD_PRIMARY]*100:.0f}c)</h2>
<table><tr><th>cat</th><th>N</th><th>fee</th><th>fav/adv/nofill %</th>
<th>GROSS taker→$1/$0</th><th>gross faded win/lose</th><th>no-credit floor</th>
<th>worst net</th><th>worst fill%</th><th>worst DSR</th>
<th>exp net</th><th>exp fill%</th><th>exp DSR</th>
<th>best net</th><th>best fill%</th><th>best DSR</th></tr>
{''.join(cat_rows)}</table>
<p class=meta>GROSS taker→$1/$0 = the raw held-to-resolution edge per $1 (fade entry at p_signal, exit at the true
settlement). Sign &gt;0 = the fade STILL profits held to resolution; &lt;0 = the intraday snap-back is given back
when the odds converge to the outcome. faded win/lose = gross when we faded the eventual WINNER vs LOSER (a real
edge profits on BOTH; if only the loser leg pays, it is longshot bias, not reversion). maker net = gross(from the
realized maker fill) + half-spread credit − fee. no-credit floor strips the spread credit to isolate the
fill-price structure.</p>

<h2>Every over-extension event ({meta['n_events']}, capped 4000 shown)</h2>
<table><tr><th>cat</th><th>question</th><th>signal (UTC)</th><th>h→dl</th><th>side</th><th>z</th>
<th>p signal</th><th>peak run</th><th>$1/$0</th><th>faded</th><th>fill class</th><th>gross→resolution</th></tr>
{''.join(rows)}</table>
"""


# ==========================================================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-events", type=int, default=1200)
    ap.add_argument("--per-cat-budget", type=int, default=300)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="/tmp/polymarket_maker_gate.html")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--no-tripwire", action="store_true", help="skip the leakage tripwire (debug only)")
    args = ap.parse_args()

    t0 = time.time()
    print("[MAKER-GATE] spread calibration (reuse #400 live books)...", file=sys.stderr)
    spread_cal = calibrate_spread()
    print(f"[MAKER-GATE] spread cal: {spread_cal}", file=sys.stderr)

    print(f"[MAKER-GATE] discovering resolved binaries (max_events={args.max_events})...", file=sys.stderr)
    markets = discover(args.max_events, per_cat_budget=args.per_cat_budget)
    print(f"[MAKER-GATE] discovered/sampled {len(markets)}: "
          f"{dict(Counter(m.category for m in markets))}", file=sys.stderr)

    from concurrent.futures import ThreadPoolExecutor

    all_events: list[MakerResolveEvent] = []
    tw_results: list[dict] = []
    n_with_series = 0
    n_tw_pass = 0
    done = 0

    def _one(m: Market) -> tuple[bool, dict | None, list[MakerResolveEvent]]:
        series = hourly_odds(m.yes_token, m.created_at, m.deadline)
        if len(series) < MIN_BARS_PER_MARKET:
            return (False, None, [])
        tw = None if args.no_tripwire else tripwire_cell(m, series)
        if tw is not None and not tw["passed"]:
            return (True, tw, [])  # had series, tripwire FAILED → excluded from the gate population
        return (True, tw, build_maker_resolve_events(m, series))

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for had, tw, evs in ex.map(_one, markets):
            done += 1
            if had:
                n_with_series += 1
            if tw is not None:
                tw_results.append(tw)
                if tw["passed"]:
                    n_tw_pass += 1
            all_events.extend(evs)
            if done % 50 == 0:
                print(f"[MAKER-GATE]  {done}/{len(markets)}, {n_with_series} w/ series, "
                      f"{n_tw_pass} tripwire-pass, {len(all_events)} events", file=sys.stderr)

    # tripwire roll-up
    tw_counts = Counter("pass" if r["passed"] else "fail" for r in tw_results)
    reason_counter: Counter = Counter()
    for r in tw_results:
        if not r["passed"]:
            for reason in r.get("reasons", ()):  # bucket the leading reason token
                reason_counter[str(reason).split(":")[0]] += 1
    tw_summary = {
        "n_audited": len(tw_results),
        "counts": dict(tw_counts),
        "top_reasons": ", ".join(f"{k}={v}" for k, v in reason_counter.most_common(5)) or "—",
        "reasons_full": dict(reason_counter),
    }

    cats = [summarize(all_events, c) for c in ("geopolitics", "sports")]
    pooled = summarize(all_events, None)

    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_markets": len(markets), "n_with_series": n_with_series, "n_events": len(all_events),
        "n_tripwire_pass": n_tw_pass,
        "elapsed_s": round(time.time() - t0, 1),
        "model": {
            "exit": "HELD_TO_RESOLUTION (true $1/$0 settlement, #422)",
            "fill_window_h": FILL_WINDOW_H, "tick": TICK,
            "z_entry": Z_ENTRY, "z_lookback": Z_LOOKBACK, "move_horizon_h": MOVE_HORIZON_H,
            "final_exclude_hours": FINAL_EXCLUDE_HOURS, "entry_band": [MIN_ENTRY_P, MAX_ENTRY_P],
            "spread_band": SPREAD_BAND, "spread_primary": SPREAD_PRIMARY,
            "scenarios": {s.name: vars(s) for s in SCENARIOS},
            "category_fee": _CAT_FEE,
        },
        "spread_calibration": spread_cal,
    }

    html = render_html(all_events, cats, pooled, meta, tw_summary)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)

    summary = {"meta": meta, "tripwire": tw_summary, "pooled": pooled, "categories": cats}
    out_json = json.dumps(summary, indent=2, default=str)
    print(out_json)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(out_json)
    print(f"\n[MAKER-GATE] HTML -> {args.out}  ({meta['elapsed_s']}s, {n_with_series}/{len(markets)} series, "
          f"{n_tw_pass} tripwire-pass, {len(all_events)} events)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
