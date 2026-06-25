# intent: MAKER-EXECUTION FEASIBILITY for the #400 Polymarket intraday over-extension fade (EXPERIMENT ONLY,
# offline, keyless). The capstone (#400) found the GROSS reversion edge is REAL (+0.70c/$1 pooled, clears the
# BRUT Gate DSR=1.0) but a TAKER round-trip pays the wide CLOB spread (median 1c / mean 2.9c / p75 3c) → net
# −2.86c/$1. The ONLY door left: earn the half-spread as a MAKER (resting limit orders) instead of crossing it.
#
# HONESTY MANDATE: you CANNOT perfectly backtest maker fills offline — there is no order-book queue-position
# history and no per-order fill log on the keyless data. This is therefore NOT a fill backtest and NOT a maker
# Sharpe. It is a FEASIBILITY CHARACTERIZATION that (1) bounds the maker opportunity from the realized hourly
# path of each #400 event, (2) decomposes an honest maker-net ESTIMATE = gross + half-spread earned − adverse
# selection − fee with a best/expected/worst sensitivity band, (3) states plainly what is unknowable offline
# (queue position, partial fills, own-size impact, cancel/repost), and (4) sanity-checks spread/fill realism
# against the LIVE keyless order book + trade prints.
#
# THE ADVERSE-SELECTION CORE (the whole point):
#   A resting maker order earns the half-spread but fills ADVERSELY. To fade an UP-spike we post a resting
#   SELL-YES at/inside the touch; it gets LIFTED by aggressive buyers — i.e. it fills PREFERENTIALLY when the
#   move CONTINUES up against us (bad), and is SKIPPED when the price reverts down immediately (the good case
#   we WANTED, but never got positioned for). We classify each #400 event from its REALIZED hourly path in a
#   short post-signal fill window into:
#     FAVORABLE  — price lingered near / just past the spike (our resting order plausibly filled near entry),
#                  then reverted: we earn gross reversion + half-spread.
#     ADVERSE    — price ran FURTHER into the spike before any reversion: our resting order filled at a WORSE
#                  level (deeper in the over-extension); we earn the half-spread but eat the continuation drift
#                  to the realized fill, measured from the actual path.
#     NO-FILL    — price reverted immediately without trading back to our limit: we are SKIPPED, capture
#                  NOTHING (this removes exactly the best taker trades from the maker book — the core tax).
#
# DATA (keyless, free): reuses the #400 harness verbatim for discovery + windowed HOURLY odds + the BRUT
# scorer, then adds (a) the maker classification on the realized path and (b) a LIVE realism check on the
# CLOB /book (real depth + spread at the touch) and data-api /trades (real BUY/SELL print flow), both keyless.
#
# ZERO production impact: read-only fetches, persists NOTHING, no Gate constant touched, no cron, docs-only.
# Writes a disposable HTML table + prints a JSON summary. Run:
#   python3 apps/engine/scripts/research/polymarket_maker_feasibility.py [--max-events N] [--per-cat-budget N]

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean, median, pstdev

# Make `cosmu` importable + reuse the #400 capstone harness verbatim (discovery, windowed hourly odds, the
# Market dataclass, the BRUT scorer wrapper). This is the ONLY production touch and it is import-path plumbing
# for an offline research script (no prod behaviour). The maker layer is built entirely on top.
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
    calibrate_spread,
    discover,
    gate_stats,
    hourly_odds,
)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def _fetch(url: str, *, retries: int = 3) -> object:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 404):
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.4 * (attempt + 1))
    if last:
        raise last
    return None


# ==========================================================================================================
# THE MAKER MODEL — fill classification + maker P&L from the REALIZED hourly path (the honest core).
# ==========================================================================================================
#
# We reconstruct the #400 fade events ourselves (so we hold the full realized path around each entry, not just
# the gross/net scalars the #400 summary returns) and overlay a maker execution model.
#
# Definitions per event:
#   entry bar i: the over-extension bar (|z|>=Z_ENTRY); the fade SIDE is short_yes (z>0) / long_yes (z<0).
#   FILL WINDOW: the FILL_WINDOW_H bars immediately AFTER the signal, during which a resting limit order at the
#                touch could get filled. We read the realized path over this window to decide IF and WHERE we
#                fill.
#   adverse run: how much further the price moved in the SPIKE direction within the fill window, relative to
#                the signal price p_i (e.g. for short_yes, max(p over window) − p_i ≥ 0 is the over-run our
#                resting sell would be lifted through).
#   reversion target: the #400 exit is K_HOURS after the SIGNAL bar. For the maker we exit K_HOURS after the
#                FILL bar (a resting order that fills late holds for the same horizon from its own fill), so the
#                exit reads the realized path at fill_bar + K_HOURS.
#
# Classification from the realized path within the fill window:
#   - peak_run = the max adverse excursion (spike-direction) over the fill window (in probability units).
#   - If peak_run <= TICK (price barely moved further → our resting order at the touch plausibly filled at ~p_i
#     while the spike was still extended): FAVORABLE.  fill_p ≈ p_i (we even gain ~half-spread of price
#     improvement vs a taker who crossed).
#   - If TICK < peak_run <= ADVERSE_CAP: ADVERSE.  Our resting sell got lifted as the price ran further; the
#     realized fill price is the level the price actually reached, fill_p = p_i + frac*peak_run (frac = how far
#     up the run we got picked off; swept in the sensitivity band). We earn the half-spread but carry the
#     continuation from fill_p to the exit.
#   - If peak_run reverted within < TICK of p_i AND the subsequent path dropped below p_i quickly without ever
#     trading back up to our resting level: NO-FILL (price reverted away from our limit before lifting it). The
#     #400 "best" trades — the immediate reverters — are exactly the ones a passive order misses.
#
# Half-spread earned: a maker that posts at the touch earns ~half the quoted spread relative to a taker who
# crosses. We charge HALF of the calibrated round-trip spread as the maker CREDIT (best/expected/worst swept),
# on BOTH legs if both legs are maker, ONE leg if we assume the exit must be a taker (the conservative case).

FILL_WINDOW_H = 3       # bars after the signal during which a resting limit order can fill (the over-run window)
TICK = 0.01             # 1c price grid: a run <= one tick = "filled at the touch" (favorable)
ADVERSE_CAP = 0.20      # runs beyond 20c in the spike direction are treated as full continuation (capped)


@dataclass
class MakerEvent:
    condition_id: str
    question: str
    category: str
    signal_ts: datetime
    side: str             # short_yes / long_yes
    z: float
    p_signal: float       # price at the signal bar (what a taker would have crossed at)
    peak_run: float       # max adverse (spike-direction) excursion over the fill window, probability units
    reverted_first: bool  # True if the path reverted past p_signal BEFORE running further (→ likely NO-FILL)
    # realized prices we need for the maker P&L, read straight off the path:
    p_fill_favorable: float   # ~p_signal (fill at the touch)
    p_fill_adverse: float     # p_signal + peak_run (filled after the over-run)
    p_exit_from_signal: float # path K_HOURS after the SIGNAL bar (the taker/favorable exit)
    p_exit_from_fill: float   # path K_HOURS after the FILL bar (the adverse-fill exit; later in time)
    fill_class: str           # FAVORABLE / ADVERSE / NO_FILL (the base-case classification)
    gross_taker: float        # the #400 gross reversion (signal→exit), per $1 — for reconciliation


def _signed_gross(side: str, p_in: float, p_out: float) -> float:
    """Per-$1 reversion P&L of the fade from an entry price p_in to an exit price p_out."""
    return (p_in - p_out) if side == "short_yes" else (p_out - p_in)


def build_maker_events(m: Market, series: list[tuple[datetime, float]]) -> list[MakerEvent]:
    """Reconstruct the #400 non-overlapping fades AND read the realized path around each to classify the maker
    fill. PIT is inherited from #400 (z uses only bars[:i+1]); we additionally read FORWARD bars to model the
    fill + exit, which is legitimate because those bars are in the FUTURE of the entry and we are *simulating
    execution*, not the signal — the signal never peeks forward."""
    n = len(series)
    if n < MIN_BARS_PER_MARKET:
        return []
    ts = [t for t, _ in series]
    p = [v for _, v in series]
    deadline_ts = m.deadline.timestamp()
    out: list[MakerEvent] = []
    i = Z_LOOKBACK + MOVE_HORIZON_H
    # need room for the fill window AND a K-hour hold AFTER a late fill
    while i + FILL_WINDOW_H + K_HOURS < n:
        entry_t = ts[i]
        if (deadline_ts - entry_t.timestamp()) / 3600.0 <= FINAL_EXCLUDE_HOURS:
            break
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

        # --- realized path in the fill window (bars i+1 .. i+FILL_WINDOW_H) ---
        win = p[i + 1 : i + 1 + FILL_WINDOW_H]
        # adverse direction = the spike direction. short_yes faded an UP move → adverse run is price going UP.
        if side == "short_yes":
            peak_run = max((q - p_signal) for q in win) if win else 0.0   # how far UP it ran (>=0 adverse)
            trough = min((q - p_signal) for q in win) if win else 0.0     # how far DOWN (reversion)
        else:
            peak_run = max((p_signal - q) for q in win) if win else 0.0   # how far DOWN it ran (adverse)
            trough = min((p_signal - q) for q in win) if win else 0.0
        peak_run = max(0.0, peak_run)
        # did it revert past the signal (favorable direction) BEFORE running adversely? proxy: the first bar
        # after the signal already moved in our favour by > TICK while the peak adverse run stayed small.
        first_move = (p_signal - win[0]) if (side == "short_yes" and win) else ((win[0] - p_signal) if win else 0.0)
        reverted_first = (first_move > TICK) and (peak_run <= TICK)

        # --- realized exit prices off the path ---
        exit_from_signal = p[i + K_HOURS]
        # the adverse fill happens at the bar of the peak run within the window; hold K hours from THERE
        if win:
            run_levels = [(q - p_signal) if side == "short_yes" else (p_signal - q) for q in win]
            fill_off = run_levels.index(max(run_levels))  # bar within window where the over-run peaked
        else:
            fill_off = 0
        fill_bar = i + 1 + fill_off
        exit_from_fill_idx = min(fill_bar + K_HOURS, n - 1)
        exit_from_fill = p[exit_from_fill_idx]

        p_fill_favorable = p_signal
        p_fill_adverse = (p_signal + peak_run) if side == "short_yes" else (p_signal - peak_run)

        # base-case classification
        if reverted_first:
            fill_class = "NO_FILL"
        elif peak_run <= TICK:
            fill_class = "FAVORABLE"
        else:
            fill_class = "ADVERSE"

        out.append(
            MakerEvent(
                condition_id=m.condition_id, question=m.question, category=m.category,
                signal_ts=entry_t, side=side, z=z, p_signal=p_signal,
                peak_run=peak_run, reverted_first=reverted_first,
                p_fill_favorable=p_fill_favorable, p_fill_adverse=p_fill_adverse,
                p_exit_from_signal=exit_from_signal, p_exit_from_fill=exit_from_fill,
                fill_class=fill_class,
                gross_taker=_signed_gross(side, p_signal, exit_from_signal),
            )
        )
        i = fill_bar + K_HOURS + 6  # non-overlapping: next entry after this trade's maker exit + cooldown
    return out


# ==========================================================================================================
# THE DECOMPOSITION — an honest maker-net ESTIMATE with a best/expected/worst sensitivity band.
# ==========================================================================================================
#
# For each scenario we sweep THREE explicit assumptions, every one stated:
#   (A) half_spread_earned    — the maker credit per round-trip = HS_FRAC * round_trip_spread.
#                               best: earn a FULL round-trip half-spread on both legs (HS_FRAC of the
#                               round-trip ≈ the full quoted spread, i.e. we post passively in AND out and
#                               both get filled by flow). expected: ~half. worst: only the entry is maker, the
#                               exit must cross (HS_FRAC small).
#   (B) fill_mix              — what FRACTION of the would-be taker trades a passive order actually gets, and
#                               of those, how many are FAVORABLE vs ADVERSE. best: most fills favorable, few
#                               no-fills. expected: the EMPIRICAL classification from the realized path. worst:
#                               adverse-selection-heavy (we get the continuations, miss the snap-backs).
#   (C) adverse_capture       — for adverse fills, what fraction of the over-run we eat. best: we still fill
#                               near the touch (frac small). expected: we fill at the realized peak. worst: we
#                               fill at the realized peak AND hold the full continuation to the late exit.
#
# Maker P&L per FILLED event (per $1):
#   FAVORABLE:  gross(signal→exit) + half_spread_earned − fee
#   ADVERSE:    gross(fill→late_exit) + half_spread_earned − fee     [gross measured from the WORSE fill]
#   NO_FILL:    excluded from the book entirely (we captured nothing; it neither helps nor hurts P&L, but it
#               REMOVES the immediate-reverters that were the taker book's best trades — a survivorship cost we
#               surface by reporting the no-fill rate and the gross we forfeit).

SPREAD_BAND = {"optimistic_1c": 0.01, "base_3c": 0.03, "conservative_5c": 0.05}
SPREAD_PRIMARY = "base_3c"
_CAT_FEE = {"geopolitics": 0.0, "sports": 0.03}


@dataclass
class Scenario:
    name: str
    hs_frac: float       # (A) fraction of the round-trip spread earned back as maker credit
    favorable_keep: float  # (B) fraction of FAVORABLE-classified events that actually fill favorably
    adverse_keep: float    # (B) fraction of ADVERSE-classified events that actually fill (the rest = no-fill)
    nofill_rescue: float   # (B) fraction of NO_FILL events that DO fill (favorably) — best case only
    adverse_capture: float # (C) fraction of the over-run eaten on adverse fills (1.0 = full realized run)


SCENARIOS = [
    # name              hs_frac fav_keep adv_keep nofill_rescue adv_capture
    Scenario("worst",    0.25,   0.70,    1.00,    0.00,         1.00),   # earn little spread; keep all adverse, miss reverters, eat full run
    Scenario("expected", 0.50,   0.90,    1.00,    0.00,         1.00),   # earn half-spread; empirical fill mix; full realized over-run
    Scenario("best",     1.00,   1.00,    0.85,    0.30,         0.50),   # earn full half-spread both legs; skip some adverse; rescue some reverters; half the over-run
]


def maker_pnls_for_scenario(events: list[MakerEvent], spread_rt: float, sc: Scenario) -> list[float]:
    """The list of per-$1 maker P&Ls under one scenario + one round-trip-spread level. NO_FILL events drop out
    of the book (except a best-case rescue fraction). Each assumption is applied explicitly and traceably."""
    credit = sc.hs_frac * spread_rt  # the maker spread credit earned per filled round-trip
    pnls: list[float] = []
    for e in events:
        fee = _CAT_FEE[e.category]
        if e.fill_class == "FAVORABLE":
            # earn gross(signal->exit) + credit, but only `favorable_keep` of them actually fill at the touch;
            # the rest behave as no-fills (the price never quite traded to our resting level).
            if sc.favorable_keep >= 1.0 or (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.favorable_keep:
                g = _signed_gross(e.side, e.p_signal, e.p_exit_from_signal)
                pnls.append(g + credit - fee)
        elif e.fill_class == "ADVERSE":
            if sc.adverse_keep >= 1.0 or (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.adverse_keep:
                # fill at p_signal + adverse_capture*peak_run; hold to the late exit off the realized path
                run = sc.adverse_capture * e.peak_run
                fill_p = (e.p_signal + run) if e.side == "short_yes" else (e.p_signal - run)
                g = _signed_gross(e.side, fill_p, e.p_exit_from_fill)
                pnls.append(g + credit - fee)
        else:  # NO_FILL
            if sc.nofill_rescue > 0.0 and (hash((e.condition_id, e.signal_ts)) % 100) / 100.0 < sc.nofill_rescue:
                # best-case: a few of the immediate reverters DID lift our resting order at the touch → the
                # dream trade (full reversion + credit).
                g = _signed_gross(e.side, e.p_signal, e.p_exit_from_signal)
                pnls.append(g + credit - fee)
    return pnls


def summarize_maker(events: list[MakerEvent], category: str | None) -> dict:
    evs = events if category is None else [e for e in events if e.category == category]
    n = len(evs)
    if n == 0:
        return {"category": category or "ALL", "n": 0}
    classes = Counter(e.fill_class for e in evs)
    fee_note = "mixed" if category is None else f"{_CAT_FEE[category]*100:.0f}%"
    # gross taker reconciliation (should track #400)
    gross_taker = [e.gross_taker for e in evs]
    # the no-fill survivorship cost: gross we FORFEIT by missing the immediate reverters
    nofill_gross = [e.gross_taker for e in evs if e.fill_class == "NO_FILL"]
    # adverse drift: how much worse the adverse fills are vs the signal price (mean over-run we get picked at)
    adverse_runs = [e.peak_run for e in evs if e.fill_class == "ADVERSE"]

    out = {
        "category": category or "ALL", "n": n, "fee": fee_note,
        "fill_class_counts": dict(classes),
        "fill_class_pct": {k: round(v / n, 4) for k, v in classes.items()},
        "mean_gross_taker": fmean(gross_taker),
        "n_nofill": len(nofill_gross),
        "mean_gross_forfeited_to_nofill": fmean(nofill_gross) if nofill_gross else 0.0,
        "n_adverse": len(adverse_runs),
        "mean_adverse_overrun": fmean(adverse_runs) if adverse_runs else 0.0,
        "median_adverse_overrun": median(adverse_runs) if adverse_runs else 0.0,
        "scenarios": {},
    }
    spread_rt = SPREAD_BAND[SPREAD_PRIMARY]
    for sc in SCENARIOS:
        pnls = maker_pnls_for_scenario(evs, spread_rt, sc)
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
            "passes_gate": gate.get("passes_gate"),
            "assumptions": {
                "hs_frac": sc.hs_frac, "favorable_keep": sc.favorable_keep,
                "adverse_keep": sc.adverse_keep, "nofill_rescue": sc.nofill_rescue,
                "adverse_capture": sc.adverse_capture, "spread_rt": spread_rt,
            },
        }
    # also report the maker-net at each spread level for the EXPECTED scenario (spread sensitivity)
    expected = next(s for s in SCENARIOS if s.name == "expected")
    out["expected_by_spread"] = {}
    for name, s in SPREAD_BAND.items():
        pnls = maker_pnls_for_scenario(evs, s, expected)
        out["expected_by_spread"][name] = round(fmean(pnls), 6) if pnls else None

    # CONSERVATIVE CONTROL — strip the half-spread credit ENTIRELY (hs_frac=0): the maker P&L from the
    # realized FILL prices alone, every event that fills kept (favorable + ALL adverse, no rescue, full
    # over-run). This isolates whether the FILL-PRICE structure alone (entering adverse fills at a deeper,
    # better fade level) is net-positive BEFORE any spread credit — the most honest floor. If even +credit
    # can't lift this above zero net of fees, the half-spread gain is being eaten by adverse selection.
    no_credit = Scenario("no_credit", hs_frac=0.0, favorable_keep=1.0, adverse_keep=1.0,
                         nofill_rescue=0.0, adverse_capture=1.0)
    nc_pnls = maker_pnls_for_scenario(evs, SPREAD_BAND[SPREAD_PRIMARY], no_credit)
    if nc_pnls:
        nc_gate = gate_stats(nc_pnls)
        out["no_credit_control"] = {
            "n_filled": len(nc_pnls), "mean_maker_net": fmean(nc_pnls),
            "win_rate": sum(1 for x in nc_pnls if x > 0) / len(nc_pnls),
            "deflated_sharpe_prob": nc_gate.get("deflated_sharpe_prob"),
            "passes_gate": nc_gate.get("passes_gate"),
            "note": "maker P&L from realized fill prices with ZERO spread credit (the floor before any "
                    "half-spread gain). The expected/best maker-net minus this = the spread credit's "
                    "contribution; if this is already >0, the fill-price structure helps on its own.",
        }
    return out


# ==========================================================================================================
# LIVE REALISM CHECK — keyless CLOB /book (real depth + touch spread) + data-api /trades (real BUY/SELL flow).
# Sanity-checks (a) the spread the maker would actually post into and (b) the fill-direction realism behind
# the adverse-selection story (does aggressive flow really lift the offer when price ticks up?).
# ==========================================================================================================
def live_realism_check(sample_markets: int = 40, trade_markets: int = 12) -> dict:
    """Pull live two-sided OPEN books (real depth at the touch) and recent trade prints to ground the model."""
    books: list[dict] = []
    cond_tokens: list[tuple[str, str]] = []  # (conditionId, yesToken) for the trade-flow check
    for off in range(0, 400, 100):
        try:
            ev = _fetch(f"{GAMMA}/events?closed=false&active=true&limit=100&offset={off}&order=volume&ascending=false")
        except Exception:  # noqa: BLE001
            break
        if not isinstance(ev, list) or not ev:
            break
        for e in ev:
            for m in e.get("markets") or []:
                tids = m.get("clobTokenIds") or "[]"
                if isinstance(tids, str):
                    try:
                        tids = json.loads(tids)
                    except (json.JSONDecodeError, TypeError):
                        tids = []
                if not tids:
                    continue
                yes = str(tids[0])
                cid = str(m.get("conditionId") or "")
                try:
                    bb = float(m.get("bestBid"))
                    ba = float(m.get("bestAsk"))
                except (TypeError, ValueError):
                    continue
                mid = (bb + ba) / 2.0
                w = ba - bb
                if 0.05 <= mid <= 0.95 and 0.0 < w < 0.20:
                    # pull the real book to measure depth AT the touch (the queue our maker order joins)
                    depth_bid = depth_ask = None
                    if len(books) < sample_markets:
                        try:
                            b = _fetch(f"{CLOB}/book?token_id={yes}")
                            bids = sorted((float(x["price"]), float(x["size"])) for x in b.get("bids", []))
                            asks = sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))
                            if bids:
                                depth_bid = bids[-1][1]
                            if asks:
                                depth_ask = asks[0][1]
                        except Exception:  # noqa: BLE001
                            pass
                    books.append({"spread": w, "mid": mid, "depth_bid": depth_bid, "depth_ask": depth_ask})
                    if cid and len(cond_tokens) < trade_markets:
                        cond_tokens.append((cid, yes))
        time.sleep(0.1)

    spreads = sorted(b["spread"] for b in books)
    depths = [b["depth_bid"] for b in books if b["depth_bid"]] + [b["depth_ask"] for b in books if b["depth_ask"]]

    # --- trade-flow check: when the mid ticks UP between prints, are the aggressors BUYs? (the adverse-fill
    # mechanism: a resting SELL is lifted by aggressive BUYs preferentially when price is rising). We measure
    # the conditional P(aggressor=BUY | price rose since prior print) on real prints. >0.5 confirms the
    # mechanism qualitatively. ---
    up_buy = up_n = down_sell = down_n = 0
    flow_markets = 0
    for cid, _yes in cond_tokens:
        try:
            tr = _fetch(f"{DATA}/trades?market={cid}&limit=500")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(tr, list) or len(tr) < 20:
            continue
        flow_markets += 1
        # data-api returns newest-first; sort ascending by ts for the price-change direction
        rows = sorted(
            ({"ts": int(x.get("timestamp", 0)), "side": x.get("side"), "price": float(x.get("price", 0))}
             for x in tr if x.get("timestamp")),
            key=lambda r: r["ts"],
        )
        for a, b in zip(rows, rows[1:]):
            if b["price"] > a["price"]:
                up_n += 1
                if b["side"] == "BUY":
                    up_buy += 1
            elif b["price"] < a["price"]:
                down_n += 1
                if b["side"] == "SELL":
                    down_sell += 1

    def pct(p: float) -> float:
        return spreads[int(p / 100 * (len(spreads) - 1))] if spreads else 0.0

    return {
        "n_books": len(books),
        "spread_cents": {
            "p25": round(pct(25) * 100, 2), "median": round(pct(50) * 100, 2),
            "mean": round(fmean(spreads) * 100, 2) if spreads else 0.0,
            "p75": round(pct(75) * 100, 2), "p90": round(pct(90) * 100, 2),
        },
        "touch_depth_shares": {
            "n": len(depths),
            "median": round(median(depths), 1) if depths else None,
            "mean": round(fmean(depths), 1) if depths else None,
        },
        "trade_flow": {
            "markets": flow_markets,
            "p_buy_when_price_rose": round(up_buy / up_n, 4) if up_n else None,
            "p_sell_when_price_fell": round(down_sell / down_n, 4) if down_n else None,
            "n_up": up_n, "n_down": down_n,
            "note": "P>0.5 confirms the adverse-fill mechanism qualitatively: aggressive flow lifts the offer "
                    "when price is rising, so a resting SELL (our short-YES fade of an up-spike) fills "
                    "preferentially INTO continued upward pressure.",
        },
    }


# ==========================================================================================================
# HTML (disposable — surfaces every event + the decomposition, per the surface-all-compute rule).
# ==========================================================================================================
def render_html(events: list[MakerEvent], cats: list[dict], pooled: dict, meta: dict, realism: dict) -> str:
    def f(x, d=4):
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else str(x)

    def scen_cell(s: dict, key: str) -> str:
        if not s.get("scenarios", {}).get(key, {}).get("n_filled"):
            return "<td>—</td><td>—</td><td>—</td>"
        sc = s["scenarios"][key]
        cls = "pass" if sc.get("passes_gate") else ("pos" if sc["mean_maker_net"] > 0 else "neg")
        return (f"<td class='{cls}'><b>{f(sc['mean_maker_net'])}</b></td>"
                f"<td>{f(sc['fill_rate'],2)}</td><td>{f(sc.get('deflated_sharpe_prob') or 0,3)}</td>")

    cat_rows = []
    for s in cats + [pooled]:
        if s.get("n", 0) == 0:
            continue
        fc = s["fill_class_pct"]
        cat_rows.append(
            f"<tr><td><b>{s['category']}</b></td><td>{s['n']}</td><td>{s['fee']}</td>"
            f"<td>{f(fc.get('FAVORABLE',0),2)}/{f(fc.get('ADVERSE',0),2)}/{f(fc.get('NO_FILL',0),2)}</td>"
            f"<td>{f(s['mean_gross_taker'])}</td>"
            f"<td>{f(s['mean_adverse_overrun'])}</td>"
            f"<td>{f(s['mean_gross_forfeited_to_nofill'])}</td>"
            + scen_cell(s, "worst") + scen_cell(s, "expected") + scen_cell(s, "best")
            + "</tr>"
        )

    rows = []
    for e in sorted(events, key=lambda x: (x.category, x.fill_class, -abs(x.z)))[:4000]:
        cls = {"FAVORABLE": "rev", "ADVERSE": "adv", "NO_FILL": "nf"}[e.fill_class]
        rows.append(
            f"<tr class='{cls}'><td>{e.category}</td><td class='q'>{e.question}</td>"
            f"<td>{e.signal_ts.strftime('%Y-%m-%d %H:%M')}</td><td>{e.side}</td><td>{f(e.z,2)}</td>"
            f"<td>{f(e.p_signal,3)}</td><td>{f(e.peak_run,3)}</td><td>{f(e.p_exit_from_signal,3)}</td>"
            f"<td>{f(e.p_exit_from_fill,3)}</td><td><b>{e.fill_class}</b></td><td>{f(e.gross_taker)}</td></tr>"
        )

    rf = realism
    tf = rf.get("trade_flow", {})
    sc = rf.get("spread_cents", {})
    return f"""<!doctype html><meta charset=utf-8>
<title>Polymarket MAKER feasibility — {meta['generated']}</title>
<style>
 body{{font:13px/1.5 -apple-system,system-ui,sans-serif;margin:24px;color:#111;background:#fafafa}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:26px}}
 table{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0;font-size:12px}}
 th,td{{border:1px solid #ddd;padding:4px 7px;text-align:right}} td.q{{text-align:left;max-width:280px}}
 th{{background:#f0f0f0}} td:first-child,td.q{{text-align:left}}
 tr.rev{{background:#f5fbf5}} tr.adv{{background:#fff4f4}} tr.nf{{background:#f4f4ff}}
 td.pass{{background:#bff0bf;font-weight:700}} td.pos{{background:#eafbea;font-weight:700}} td.neg{{background:#f8d8d8;font-weight:700}}
 .meta{{color:#555;font-size:12px}} .k{{font-weight:700}}
</style>
<h1>Polymarket intraday over-extension — MAKER execution FEASIBILITY (EXPERIMENT ONLY)</h1>
<p class=meta>Generated {meta['generated']} · the #400 GROSS reversion edge is real (+0.70c/$1 pooled, DSR=1.0)
but a TAKER round-trip pays the spread → net −2.86c. This bounds whether a MAKER (resting limit, earning the
half-spread) could be net-positive AFTER adverse selection. NOT a fill backtest — a feasibility
characterization off the realized hourly path. {meta['n_markets']} resolved binaries, {meta['n_events']}
over-extension events. Keyless Gamma+CLOB+data-api · ZERO prod impact.</p>

<h2>Live realism check (keyless)</h2>
<p class=meta>Real two-sided books N={rf.get('n_books',0)}: touch spread (cents) p25={sc.get('p25')}
median={sc.get('median')} mean={sc.get('mean')} p75={sc.get('p75')} p90={sc.get('p90')}.
Touch depth (shares) median={rf.get('touch_depth_shares',{}).get('median')}.
Trade-flow ({tf.get('markets',0)} markets): <span class=k>P(aggressor=BUY | price rose) =
{tf.get('p_buy_when_price_rose')}</span> (n={tf.get('n_up')}), P(SELL | price fell) =
{tf.get('p_sell_when_price_fell')} (n={tf.get('n_down')}). P&gt;0.5 confirms the adverse-fill mechanism: a
resting SELL is lifted by aggressive BUYs when price is rising.</p>

<h2>Per-category maker decomposition — worst / expected / best (BRUT, primary spread {SPREAD_BAND[SPREAD_PRIMARY]*100:.0f}c)</h2>
<table><tr><th>cat</th><th>N</th><th>fee</th><th>fav/adv/nofill %</th><th>mean GROSS taker</th>
<th>mean adverse over-run</th><th>gross forfeited to no-fill</th>
<th>worst net</th><th>worst fill%</th><th>worst DSR</th>
<th>exp net</th><th>exp fill%</th><th>exp DSR</th>
<th>best net</th><th>best fill%</th><th>best DSR</th></tr>
{''.join(cat_rows)}</table>
<p class=meta>maker net = gross(from realized fill) + half-spread credit − fee, per $1. fav/adv/nofill = the
realized-path fill classification. The over-run is how far the price ran into the spike before our resting
order was lifted (the adverse-selection price). "gross forfeited to no-fill" = the mean #400 taker gross of
the immediate-reverter events a passive order MISSES — the survivorship tax of going passive.</p>

<h2>Every over-extension event ({meta['n_events']}, capped 4000 shown)</h2>
<table><tr><th>cat</th><th>question</th><th>signal (UTC)</th><th>side</th><th>z</th><th>p signal</th>
<th>peak run</th><th>exit (from signal)</th><th>exit (from fill)</th><th>fill class</th><th>gross taker</th></tr>
{''.join(rows)}</table>
"""


# ==========================================================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-events", type=int, default=1200)
    ap.add_argument("--per-cat-budget", type=int, default=300)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="/tmp/polymarket_maker_feasibility.html")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    t0 = time.time()
    print("[MAKER] live realism check (books + trade flow)...", file=sys.stderr)
    realism = live_realism_check()
    print(f"[MAKER] realism: {json.dumps(realism)[:400]}", file=sys.stderr)

    print("[MAKER] spread calibration (reuse #400)...", file=sys.stderr)
    spread_cal = calibrate_spread()

    print(f"[MAKER] discovering resolved binaries (max_events={args.max_events})...", file=sys.stderr)
    markets = discover(args.max_events, per_cat_budget=args.per_cat_budget)
    print(f"[MAKER] discovered/sampled {len(markets)}: {dict(Counter(m.category for m in markets))}", file=sys.stderr)

    from concurrent.futures import ThreadPoolExecutor

    all_events: list[MakerEvent] = []
    n_with_series = 0
    done = 0

    def _one(m: Market) -> tuple[bool, list[MakerEvent]]:
        series = hourly_odds(m.yes_token, m.created_at, m.deadline)
        if len(series) < MIN_BARS_PER_MARKET:
            return (False, [])
        return (True, build_maker_events(m, series))

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for had, evs in ex.map(_one, markets):
            done += 1
            if had:
                n_with_series += 1
            all_events.extend(evs)
            if done % 50 == 0:
                print(f"[MAKER]  {done}/{len(markets)}, {n_with_series} w/ series, {len(all_events)} events",
                      file=sys.stderr)

    cats = [summarize_maker(all_events, c) for c in ("geopolitics", "sports")]
    pooled = summarize_maker(all_events, None)

    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_markets": len(markets), "n_with_series": n_with_series, "n_events": len(all_events),
        "elapsed_s": round(time.time() - t0, 1),
        "model": {
            "fill_window_h": FILL_WINDOW_H, "tick": TICK, "adverse_cap": ADVERSE_CAP,
            "k_hours": K_HOURS, "z_entry": Z_ENTRY,
            "spread_band": SPREAD_BAND, "spread_primary": SPREAD_PRIMARY,
            "scenarios": {s.name: vars(s) for s in SCENARIOS},
        },
        "spread_calibration": spread_cal,
    }

    html = render_html(all_events, cats, pooled, meta, realism)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)

    summary = {"meta": meta, "realism": realism, "pooled": pooled, "categories": cats}
    out_json = json.dumps(summary, indent=2, default=str)
    print(out_json)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(out_json)
    print(f"\n[MAKER] HTML -> {args.out}  ({meta['elapsed_s']}s, {n_with_series}/{len(markets)} series, "
          f"{len(all_events)} events)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
