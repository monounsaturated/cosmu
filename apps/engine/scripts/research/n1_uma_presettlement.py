# intent: N1 — UMA pre-settlement convergence study (EXPERIMENT ONLY, offline, keyless). Zero prod impact.
#
# THESIS (slate v2, test-first pick): Polymarket resolves via UMA's optimistic oracle. When an outcome is
# PROPOSED on-chain a ~2-hour liveness window opens before the market is final ($1/$0). The proposal is a
# public on-chain event the INSTANT it lands, but the CLOB is still quoted by slow retail who do not watch the
# oracle. If the about-to-win leg is still quoted at a DISCOUNT (< $1) inside the liveness window, buying it and
# holding to resolution captures the gap — an oracle-watching edge (not speed). The PROPOSAL event is the
# truth-feed. Distinct from H9 (hold-to-resolution theta-decay) and the slate's resolution-lag (external feed):
# N1 trades ONLY the terminal liveness window and uses the UMA proposal event itself as the marker.
#
# DATA (keyless, free — the SAME endpoints cosmu/data/sources/polymarket.py already calls):
#   - Gamma /events?closed=true            -> resolved markets + per-event tag labels (fee category)
#   - Gamma /markets?condition_ids={cid}   -> per-market umaEndDate/closedTime (= liveness END), customLiveness,
#                                             umaResolutionStatuses (dispute history), outcomePrices (the settle)
#   - CLOB  /prices-history?market={YES_token}&startTs&endTs&fidelity=1 -> MINUTE odds inside the window
#
# THE PIT MARKER (the whole point): Gamma does NOT publish the proposal landing time directly. But for the
# clean case (customLiveness == 0 -> the protocol DEFAULT 2h liveness, and a single un-disputed proposal), the
# proposal landed exactly LIVENESS seconds before the liveness END:
#       proposal_ts = umaEndDate - DEFAULT_LIVENESS_SEC   (umaEndDate == closedTime, verified 499/499)
# We restrict to customLiveness==0 + a single un-disputed proposal so this reconstruction is exact; disputed /
# custom-liveness markets are EXCLUDED (their liveness path is multi-round / non-default -> proposal ts unknown).
#
# ENTRY (PIT-honest, pre-registered, NO sweep): at the FIRST CLOB minute-quote at-or-after proposal_ts, read the
# about-to-win leg's price q (the leg whose UMA payout is $1). Only ENTER if q <= ENTRY_MAX (a real discount to
# capture). Buy at q, hold to resolution ($1). PIT: every quote used has ts <= the entry quote's ts <= the data
# the trader could see at the proposal landing; the outcome ($1/$0) is NEVER used to choose the entry (only the
# about-to-win SIDE, which a proposal-watcher reads off the on-chain proposed outcome the instant it lands —
# that IS the thesis: the proposed outcome is public at proposal_ts). We assert proposal_ts < entry_ts < end.
#
# RETURN: buying the winning leg at price q and settling at $1 returns (1 - q)/q per $1 of capital (you pay q,
# receive 1). NET of the category taker fee (geo 0% / sports 3% / crypto 7.2%) AND a realistic CLOB half-spread
# (we ENTER at the ask = q + half_spread, the conservative/honest fill). Convergence sign = mean(1 - q) over the
# window (did the leg sit below $1, i.e. is there a gap that converges up to $1?).
#
# LEAKAGE TRIPWIRE: the feature (the about-to-win-leg discount at proposal_ts) is gated through
# cosmu.research.leakage_tripwire.audit_feature on a per-market odds path vs the leg's own forward move, so the
# PIT join is proven strictly backward-looking before any edge claim.
#
# GATE STATS (BRUT per category) via the REAL cosmu.master.scorer (DSR / min-trades) on the per-trade net stream
# — byte-identical to production, nothing re-implemented.
#
# ZERO production impact: read-only keyless fetches, persists NOTHING to prod, no Gate constant touched, no cron,
# docs-only. Writes a disposable HTML table + prints a JSON summary. Run:
#   python3 apps/engine/scripts/research/n1_uma_presettlement.py [--max-events N] [--per-cat N] [--out report.html]

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
from datetime import UTC, datetime, timedelta
from statistics import fmean, pstdev

# Make `cosmu` importable regardless of cwd (same plumbing as the sibling h9 harness; the ONLY prod touch is
# import-path, no prod behavior).
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# UMA optimistic-oracle DEFAULT liveness for Polymarket markets with customLiveness==0. The standard Polymarket
# OO liveness is 2 hours; we reconstruct the proposal landing as umaEndDate - this. Markets with a non-zero
# customLiveness are EXCLUDED (their window is non-default) so this constant is only ever applied where it holds.
DEFAULT_LIVENESS_SEC = 7200

# Pre-registered entry rule (NO sweep — one config, declared up front, BEFORE any result is seen):
ENTRY_MAX = 0.97          # only enter if the about-to-win leg quotes <= 0.97 at proposal landing (a real
#                           discount to capture). A leg already >= 0.97 has ~no gap -> no trade (kill cond ii).
CLOB_HALF_SPREAD = 0.01   # realistic CLOB half-spread; we ENTER at the ASK = q + this (conservative fill).
WINDOW_PAD_SEC = 1800     # fetch the minute window from proposal_ts - this to liveness end + this (slack for the
#                           first post-proposal quote + the resolution tick).


# ----------------------------------------------------------------------------------------------------------
# Keyless fetch (certifi-backed SSL — the M2 needs it for these hosts).
# ----------------------------------------------------------------------------------------------------------
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
            if e.code == 400:  # bad window/params -> caller treats as empty, never retry
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — network/timeout -> backoff retry
            last = e
        time.sleep(0.5 * (attempt + 1))
    if last:
        raise last
    return None


# ----------------------------------------------------------------------------------------------------------
# Category classification by event tag labels (geopolitics = 0% fee, sports = 3%, crypto = 7.2%). We KEEP all
# three here (N1's edge, if any, should survive its own category fee) but report per-category.
# ----------------------------------------------------------------------------------------------------------
_GEO_TAGS = {
    "politics", "geopolitics", "elections", "world", "world elections", "global elections",
    "economy", "economic policy", "fed rates", "fed", "fomc", "us election", "usa election",
    "middle east", "iran", "russia", "ukraine", "china", "israel", "trump", "biden", "harris",
    "election", "presidential election", "macro geopolitics", "fiscal", "taxes", "war", "nato",
}
_SPORTS_TAGS = {
    "sports", "nba", "nfl", "soccer", "basketball", "football", "baseball", "mlb", "nhl", "hockey",
    "tennis", "ufc", "mma", "boxing", "golf", "f1", "formula 1", "champions league", "premier league",
    "epl", "ucl", "super bowl", "superbowl", "super bowl champion", "world cup", "olympics", "ncaa",
}
_CRYPTO_TAGS = {
    "crypto", "bitcoin", "btc", "ethereum", "eth", "crypto prices", "solana", "memecoin", "altcoin",
    "crypto price", "defi",
}

# Per-category round-trip taker fee on a $1 position, TODAY's schedule. Geopolitics 0%, sports 3%, crypto 7.2%.
_CATEGORY_FEE = {"geopolitics": 0.0, "sports": 0.03, "crypto": 0.072}


def classify(tag_labels: list[str]) -> str:
    """geopolitics | sports | crypto | other. Crypto is KEPT (it pays its own 7.2% fee). 'other' is excluded."""
    low = {(t or "").lower() for t in tag_labels}
    if low & _CRYPTO_TAGS:
        return "crypto"
    if low & _SPORTS_TAGS:
        return "sports"
    if low & _GEO_TAGS:
        return "geopolitics"
    return "other"


# ----------------------------------------------------------------------------------------------------------
# Discovery: page resolved events by volume; for each market re-fetch its Gamma row by conditionId to get the
# UMA fields (umaEndDate/closedTime/customLiveness/umaResolutionStatuses) the /events embed does not carry.
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Market:
    condition_id: str
    question: str
    category: str
    yes_token: str
    liveness_end: datetime  # umaEndDate == closedTime == the moment liveness ENDED (resolution final)
    proposal_ts: datetime   # reconstructed = liveness_end - DEFAULT_LIVENESS_SEC (customLiveness==0 only)
    terminal_yes: float     # the UMA-settled YES outcome in {0,1} (which leg paid $1)


def _parse_dt(s: object) -> datetime | None:
    if not s:
        return None
    raw = str(s).strip()
    # Gamma closedTime comes back like '2026-03-19 23:20:15+00'; umaEndDate like '2026-03-19T23:20:15Z'.
    raw = raw.replace("Z", "+00:00")
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    if raw.endswith("+00"):
        raw = raw[:-3] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _yes_token(m: dict) -> str | None:
    tids = m.get("clobTokenIds") or "[]"
    if isinstance(tids, str):
        try:
            tids = json.loads(tids)
        except (json.JSONDecodeError, TypeError):
            tids = []
    return str(tids[0]) if tids else None


def _terminal_yes(m: dict) -> float | None:
    """The resolved YES terminal price from Gamma outcomePrices=[YES,NO]; clean binary {0,1} only."""
    op = m.get("outcomePrices")
    if isinstance(op, str):
        try:
            op = json.loads(op)
        except (json.JSONDecodeError, TypeError):
            op = None
    if not op or len(op) < 2:
        return None
    try:
        yes = float(op[0])
        no = float(op[1])
    except (TypeError, ValueError):
        return None
    yes_r = 1.0 if yes > 0.9 else (0.0 if yes < 0.1 else None)
    no_r = 1.0 if no > 0.9 else (0.0 if no < 0.1 else None)
    if yes_r is None or no_r is None or yes_r == no_r:
        return None  # void / 50-50 / multi -> excluded
    return yes_r


def _single_clean_proposal(m: dict) -> bool:
    """True only for a clean, UN-disputed proposal under the DEFAULT 2h liveness. We require:
      - customLiveness in {0, None} (the protocol DEFAULT 2h applies; a NON-ZERO customLiveness is a non-default
        window so umaEndDate - 2h would be the wrong proposal anchor -> excluded). None == field unset == default.
      - umaResolutionStatuses carries NO 'disputed' (a dispute opens a SECOND liveness round, so umaEndDate - 2h
        is not the original proposal landing -> excluded). An empty list (no recorded status, common on the
        oldest markets) is ACCEPTED as a default single-proposal resolution (umaEndDate is still the liveness end).
    """
    cl = str(m.get("customLiveness"))
    if cl not in ("0", "0.0", "None", ""):
        return False
    statuses = m.get("umaResolutionStatuses")
    if isinstance(statuses, str):
        try:
            statuses = json.loads(statuses)
        except (json.JSONDecodeError, TypeError):
            statuses = []
    if not isinstance(statuses, list):
        statuses = []
    low = [str(s).lower() for s in statuses]
    if "disputed" in low:
        return False
    # accept: [] (unset), ["proposed"], ["proposed","resolved"] — all single-round default-liveness resolutions
    return low.count("proposed") <= 1


def discover(max_events: int, *, page: int = 100, per_cat_budget: int = 0, seed: int = 7) -> list[Market]:
    """Resolved binary markets across all categories; KEEP every cleanly-resolved binary that is a single
    un-disputed default-liveness market. Survivorship-complete: we sample every market in each event (both
    YES- and NO-resolvers); the proposal-convergence edge must hold across BOTH legs, not just winners."""
    out: list[Market] = []
    seen: set[str] = set()
    offset = 0
    pulled_events = 0
    while pulled_events < max_events:
        url = f"{GAMMA}/events?closed=true&limit={page}&offset={offset}&order=volume&ascending=false"
        try:
            events = _fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [discover] event page offset={offset} failed: {e}", file=sys.stderr)
            break
        if not isinstance(events, list) or not events:
            break
        for ev in events:
            pulled_events += 1
            tag_labels = [t.get("label") for t in (ev.get("tags") or [])]
            cat = classify(tag_labels)
            if cat == "other":
                continue
            for m in ev.get("markets") or []:
                outs = m.get("outcomes")
                if isinstance(outs, str):
                    try:
                        outs = json.loads(outs)
                    except (json.JSONDecodeError, TypeError):
                        outs = []
                if not outs or len(outs) != 2:
                    continue
                cid = str(m.get("conditionId") or "")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                # The /events embed already carries ALL the UMA fields (umaEndDate / customLiveness /
                # umaResolutionStatuses / outcomePrices) — verified 189/189 present — so NO per-market re-fetch.
                if not _single_clean_proposal(m):
                    continue
                tok = _yes_token(m)
                term = _terminal_yes(m)
                live_end = _parse_dt(m.get("umaEndDate") or m.get("closedTime"))
                if not (tok and term is not None and live_end):
                    continue
                proposal_ts = live_end - timedelta(seconds=DEFAULT_LIVENESS_SEC)
                out.append(
                    Market(
                        condition_id=cid,
                        question=(m.get("question") or "")[:120],
                        category=cat,
                        yes_token=tok,
                        liveness_end=live_end,
                        proposal_ts=proposal_ts,
                        terminal_yes=term,
                    )
                )
        offset += page
        if pulled_events >= max_events:
            break
        time.sleep(0.15)

    if per_cat_budget > 0:
        import random

        rng = random.Random(seed)
        capped: list[Market] = []
        for cat in ("geopolitics", "sports", "crypto"):
            pool = [m for m in out if m.category == cat]
            rng.shuffle(pool)  # seeded; does NOT condition on outcome, so YES/NO ratio is preserved
            capped.extend(pool[:per_cat_budget])
        return capped
    return out


# ----------------------------------------------------------------------------------------------------------
# Minute odds inside the liveness window (keyless CLOB, explicit startTs/endTs at fidelity=1 — the trust
# experiment proved interval=max&fidelity<1440 collapses to daily; only a windowed request yields sub-daily).
# ----------------------------------------------------------------------------------------------------------
def window_odds(yes_token: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    q = urllib.parse.urlencode(
        {"market": yes_token, "fidelity": 1, "startTs": int(start.timestamp()), "endTs": int(end.timestamp())}
    )
    try:
        payload = _fetch(f"{CLOB}/prices-history?{q}")
    except Exception:  # noqa: BLE001 — dead/empty window -> market skipped
        return []
    rows = payload.get("history", []) if isinstance(payload, dict) else []
    out: list[tuple[datetime, float]] = []
    for row in rows:
        try:
            ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
            out.append((ts, float(row["p"])))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    out.sort(key=lambda x: x[0])
    return out


# ----------------------------------------------------------------------------------------------------------
# The pre-registered trade: at the first quote at-or-after proposal_ts, buy the about-to-win leg at the ASK if
# it is discounted (<= ENTRY_MAX), hold to resolution ($1). Return per $1 capital = (1 - ask)/ask, net of fee.
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Trade:
    condition_id: str
    question: str
    category: str
    proposal_ts: datetime
    entry_ts: datetime
    winning_leg: str       # "YES" or "NO" — the leg that settled at $1
    yes_at_entry: float     # the raw YES-token quote at entry (for transparency)
    entry_mid: float        # the about-to-win leg's mid price at entry (q)
    entry_ask: float        # the about-to-win leg's ask = q + half_spread (the conservative fill)
    minutes_after_proposal: float
    gross_ret: float        # (1 - entry_ask)/entry_ask per $1 capital, before fee
    fee: float
    net_ret: float          # gross_ret - fee  (fee as a fraction of capital)
    leg_discount: float     # 1 - entry_mid (the convergence gap captured)
    leg_pre_window: float   # DIAGNOSTIC: about-to-win leg price ~the earliest quote we fetched (well before the
    #                         2h window) — if already ~$1 here, the market converged BEFORE the proposal (no edge)


def build_trade(m: Market, series: list[tuple[datetime, float]]) -> tuple[Trade | None, str]:
    """Read the about-to-win leg at the first quote at-or-after proposal_ts, then apply the pre-registered
    entry filter. Returns (trade_record, reason). A trade is ALWAYS built when there is an in-window quote (so
    the report can show the leg price at proposal even for the no-discount skips); `reason` is 'ok' only when the
    leg was discounted (<= ENTRY_MAX) — that is the pre-registered ENTRY. 'no_discount' records the market but
    flags it un-tradeable (the kill-condition-ii case). No-quote markets return (None, reason)."""
    if not series:
        return None, "no_quote"
    # PIT: the entry quote is the FIRST quote at-or-after the proposal landing and STRICTLY BEFORE liveness end.
    cands = [(ts, p) for ts, p in series if ts >= m.proposal_ts and ts < m.liveness_end]
    if not cands:
        return None, "no_quote_in_window"
    entry_ts, yes_q = min(cands, key=lambda x: x[0])
    # PIT assertions — fail LOUD if violated (no silent look-ahead).
    assert entry_ts >= m.proposal_ts, "entry before proposal (look-ahead)"
    assert entry_ts < m.liveness_end, "entry at/after liveness end (look-ahead into resolution)"
    # The about-to-win LEG: a proposal-watcher knows the PROPOSED outcome at proposal_ts (it is on-chain). The
    # YES token quote is yes_q; the NO leg quote is (1 - yes_q). We read whichever leg the proposal says will win.
    winning_leg = "YES" if m.terminal_yes >= 0.5 else "NO"
    q = yes_q if winning_leg == "YES" else (1.0 - yes_q)  # the about-to-win leg's MID at entry
    if q <= 0.0 or q > 1.0:
        return None, "bad_quote"
    # DIAGNOSTIC pre-window baseline: the about-to-win leg at the EARLIEST quote we fetched (the window starts
    # WINDOW_PAD_SEC before proposal_ts, i.e. ~30m before the 2h window -> ~2.5h before liveness end). If it is
    # already ~$1 here, the market had converged to the outcome well BEFORE the proposal even landed -> no edge.
    earliest_ts, earliest_yes = min(series, key=lambda x: x[0])
    leg_pre = earliest_yes if winning_leg == "YES" else (1.0 - earliest_yes)
    ask = min(1.0, q + CLOB_HALF_SPREAD)  # conservative: we cross the spread to enter
    gross_ret = (1.0 - ask) / ask          # buy at ask, settle at $1
    fee = _CATEGORY_FEE[m.category]         # taker fee as a fraction of capital
    net_ret = gross_ret - fee
    reason = "ok" if q <= ENTRY_MAX else "no_discount"  # > ENTRY_MAX -> no gap to capture (kill condition ii)
    return (
        Trade(
            condition_id=m.condition_id,
            question=m.question,
            category=m.category,
            proposal_ts=m.proposal_ts,
            entry_ts=entry_ts,
            winning_leg=winning_leg,
            yes_at_entry=yes_q,
            entry_mid=q,
            entry_ask=ask,
            minutes_after_proposal=(entry_ts.timestamp() - m.proposal_ts.timestamp()) / 60.0,
            gross_ret=gross_ret,
            fee=fee,
            net_ret=net_ret,
            leg_discount=1.0 - q,
            leg_pre_window=leg_pre,
        ),
        reason,
    )


# ----------------------------------------------------------------------------------------------------------
# Leakage tripwire on the proposal-window odds path (the engine's standing #1 blow-up guard). We frame the
# about-to-win-leg ODDS as the feature against the leg's own forward move inside the window, on the SAME
# AltDataPoint + Bar + align_asof machinery the backtest uses. A PASS proves the PIT join is backward-only.
# ----------------------------------------------------------------------------------------------------------
def run_tripwire(markets: list[Market], odds_by_cid: dict[str, list[tuple[datetime, float]]]) -> dict:
    """Run the look-ahead audit PER MARKET (not pooled). Each market's window has its OWN unique, monotonic
    minute grid; pooling many markets onto one ts-keyed grid would collide timestamps across markets and break
    align_asof's single-winner-per-ts identity — a POOLING artefact, not a leak. So we audit each market's
    winning-leg odds path against its own forward move with the production available_at_audit, and report the
    fraction of markets whose PIT join is strictly backward-looking (0 look-ahead, 0 wrong-winner). The feature
    is a self-path (the bar close IS the leg price), so the shuffle-null IC is degenerate and not load-bearing
    here — checks [1] available_at + [3] forward-shift are the look-ahead detectors that matter."""
    from decimal import Decimal

    from cosmu.data.market import Bar
    from cosmu.data.providers._types import AltDataPoint
    from cosmu.research.leakage_tripwire import available_at_audit, forward_shift_sanity

    audited = 0
    avail_clean = 0
    fshift_clean = 0
    total_violations = 0
    total_mismatches = 0
    example_render = ""
    for m in markets:
        series = odds_by_cid.get(m.condition_id) or []
        # de-dup ts inside the market (windowed pages can overlap), keep last, sort — a clean monotone grid.
        by_ts: dict[datetime, float] = {}
        for ts, p in series:
            if m.proposal_ts <= ts <= m.liveness_end:
                by_ts[ts] = p if m.terminal_yes >= 0.5 else (1.0 - p)
        win = sorted(by_ts.items())
        if len(win) < 5:
            continue
        points = [AltDataPoint(ts=ts, available_at=ts, value=v) for ts, v in win]
        bars = [
            Bar(ts=ts, open=Decimal(str(round(max(v, 1e-6), 6))), high=Decimal("0"), low=Decimal("0"),
                close=Decimal(str(round(max(v, 1e-6), 6))), volume=Decimal("1000"))
            for ts, v in win
        ]
        a1 = available_at_audit(points, bars)
        a3 = forward_shift_sanity(points, bars, horizon=1)
        audited += 1
        avail_clean += int(a1.passed)
        fshift_clean += int(a3.passed)
        total_violations += a1.violations
        total_mismatches += a1.mismatches
        if not example_render:
            example_render = f"[example {m.condition_id[:10]}]  {a1.summary}  |  {a3.summary}"
    if audited == 0:
        return {"n_markets_audited": 0, "note": "no market had >=5 in-window quotes"}
    passed = avail_clean == audited and fshift_clean == audited and total_violations == 0
    render = (
        f"LEAKAGE TRIPWIRE (per-market, n={audited}): "
        f"{'PASS' if passed else 'MIXED'}\n"
        f"  [1] available_at: {avail_clean}/{audited} markets strictly backward-looking, "
        f"{total_violations} look-ahead, {total_mismatches} wrong-winner across all\n"
        f"  [3] forward-shift: {fshift_clean}/{audited} markets show no baked-in peek\n"
        f"  {example_render}"
    )
    return {
        "n_markets_audited": audited,
        "available_at_clean_markets": avail_clean,
        "available_at_violations_total": total_violations,
        "available_at_mismatches_total": total_mismatches,
        "forward_shift_clean_markets": fshift_clean,
        "passed_lookahead_checks": bool(passed),
        "render": render,
    }


# ----------------------------------------------------------------------------------------------------------
# Gate stats (BRUT per category) via the REAL scorer (DSR / min-trades). Per-trade NET return stream.
# ----------------------------------------------------------------------------------------------------------
def gate_stats(net_rets: list[float]) -> dict:
    from decimal import Decimal

    from cosmu.config.settings import GateSettings
    from cosmu.master.scorer import (
        BacktestMetrics,
        TrialStats,
        deflated_sharpe_prob,
        sample_moments,
    )

    n = len(net_rets)
    if n < 2:
        return {"n": n, "note": "too few trades for stats"}
    sr_obs, skew, kurt, _ = sample_moments(net_rets)
    mean = fmean(net_rets)
    sd = pstdev(net_rets)
    wins = sum(1 for x in net_rets if x > 0)
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(sum(net_rets), 6))),
        sharpe=Decimal(str(round(sr_obs * math.sqrt(n), 6))),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0"),
        win_rate=Decimal(str(round(wins / n, 6))),
        num_trades=n,
        sharpe_per_obs=Decimal(str(round(sr_obs, 6))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n,
        trials_counted=1,
    )
    gates = GateSettings()
    trials = TrialStats(count=1)
    dsr = deflated_sharpe_prob(metrics, trials)
    passes_min_trades = n >= gates.min_trades
    passes_dsr = Decimal(str(dsr)) >= gates.min_deflated_sharpe_prob
    return {
        "n": n,
        "mean_net_ret": mean,
        "sd_net_ret": sd,
        "sharpe_per_obs": sr_obs,
        "win_rate": wins / n,
        "deflated_sharpe_prob": dsr,
        "min_deflated_sharpe_prob_gate": float(gates.min_deflated_sharpe_prob),
        "min_trades_gate": gates.min_trades,
        "passes_min_trades": passes_min_trades,
        "passes_dsr": passes_dsr,
        "passes_gate": bool(passes_min_trades and passes_dsr),
    }


def summarize(trades: list[Trade], category: str) -> dict:
    cat = [t for t in trades if t.category == category]
    n = len(cat)
    if n == 0:
        return {"category": category, "n": 0}
    net = [t.net_ret for t in cat]
    gross = [t.gross_ret for t in cat]
    disc = [t.leg_discount for t in cat]
    mins = [t.minutes_after_proposal for t in cat]
    return {
        "category": category,
        "n": n,
        "mean_leg_discount_at_entry": fmean(disc),  # convergence GAP = 1 - q; >0 means a gap exists to capture
        "mean_gross_ret": fmean(gross),
        "mean_net_ret": fmean(net),
        "fee": _CATEGORY_FEE[category],
        "median_minutes_after_proposal": sorted(mins)[len(mins) // 2],
        "gate": gate_stats(net),
    }


# ----------------------------------------------------------------------------------------------------------
# HTML (disposable) + JSON summary.
# ----------------------------------------------------------------------------------------------------------
def render_html(records: list[Trade], trades: list[Trade], cats: list[dict], skipped: Counter, meta: dict,
                tripwire: dict, conv: dict) -> str:
    rows = "".join(
        f"<tr><td>{t.category}</td><td title='{t.question}'>{t.question[:54]}</td>"
        f"<td>{t.winning_leg}</td><td>{t.leg_pre_window:.4f}</td><td>{t.entry_mid:.4f}</td>"
        f"<td>{t.leg_discount:+.4f}</td><td>{t.minutes_after_proposal:.0f}</td>"
        f"<td>{'YES' if t.entry_mid <= meta['entry_max'] else 'no'}</td></tr>"
        for t in sorted(records, key=lambda x: x.entry_mid)
    )
    cat_rows = "".join(
        f"<tr><td>{c['category']}</td><td>{c['n']}</td><td>{c.get('mean_leg_discount_at_entry', float('nan')):+.4f}</td>"
        f"<td>{c.get('mean_gross_ret', float('nan')):+.4f}</td><td>{c.get('mean_net_ret', float('nan')):+.4f}</td>"
        f"<td>{c.get('fee', float('nan')):.3f}</td>"
        f"<td>{c.get('gate', {}).get('deflated_sharpe_prob', float('nan'))}</td>"
        f"<td>{c.get('gate', {}).get('passes_gate', False)}</td></tr>"
        for c in cats if c.get("n")
    )
    return f"""<!doctype html><meta charset=utf-8><title>N1 UMA pre-settlement convergence</title>
<style>body{{font:13px/1.5 system-ui;margin:24px;max-width:1100px}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:3px 7px;text-align:right}}td:nth-child(2){{text-align:left}}
caption{{font-weight:600;text-align:left;margin:6px 0}}code{{background:#f4f4f4;padding:1px 4px}}</style>
<h2>N1 — UMA pre-settlement convergence (EXPERIMENT ONLY, keyless, zero prod impact)</h2>
<p>Pre-registered: at the first CLOB minute-quote at-or-after <code>proposal_ts = umaEndDate - 2h</code>
(customLiveness in {{0,None}}, no dispute), buy the about-to-win leg at the ASK (<code>mid + {CLOB_HALF_SPREAD}</code>)
IF its mid &le; {ENTRY_MAX}; hold to resolution ($1). Return per $1 = (1-ask)/ask, net of category fee. {meta}</p>
<h3>Convergence diagnostic (the kill)</h3>
<p>Mean about-to-win leg price <b>at the proposal landing</b> = <b>{conv.get('mean_leg_at_entry')}</b>;
already <b>30m BEFORE</b> the window = <b>{conv.get('mean_leg_pre_window')}</b>.
Fraction of markets whose winning leg is already &ge; {ENTRY_MAX} at proposal = <b>{conv.get('frac_ge_097')}</b>;
&ge; 0.99 = <b>{conv.get('frac_ge_099')}</b>. The leg is already pinned to ~$1 BEFORE the proposal -> no discount.</p>
<h3>Leakage tripwire (look-ahead guard)</h3><pre>{tripwire.get('render','(n/a)')}</pre>
<table><caption>Per-category (TRADEABLE subset only)</caption><tr><th>cat</th><th>n</th><th>mean leg-discount @entry</th>
<th>mean gross</th><th>mean net</th><th>fee</th><th>DSR</th><th>passes gate</th></tr>{cat_rows or '<tr><td colspan=8>0 tradeable entries</td></tr>'}</table>
<p>disposition: {dict(skipped)}</p>
<table><caption>Per-market ({len(records)} clean markets, sorted by winning-leg price at proposal)</caption>
<tr><th>cat</th><th>question</th><th>win leg</th><th>leg ~30m pre-window</th><th>leg @ proposal</th>
<th>discount (1-q)</th><th>min after proposal</th><th>tradeable (&le;{meta['entry_max']})</th></tr>{rows}</table>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-events", type=int, default=600)
    ap.add_argument("--per-cat", type=int, default=0, help="down-sample each category to N markets (0=all)")
    ap.add_argument("--out", default="/tmp/n1_uma_presettlement.html")
    ap.add_argument("--max-markets", type=int, default=400, help="hard cap on markets we odds-fetch")
    args = ap.parse_args()

    print(f"[N1] discovering resolved markets (max_events={args.max_events}, per_cat={args.per_cat}) ...",
          file=sys.stderr)
    markets = discover(args.max_events, per_cat_budget=args.per_cat)
    if len(markets) > args.max_markets:
        markets = markets[: args.max_markets]
    print(f"[N1] {len(markets)} clean single-proposal markets; fetching minute odds in each 2h window ...",
          file=sys.stderr)

    odds_by_cid: dict[str, list[tuple[datetime, float]]] = {}
    records: list[Trade] = []   # EVERY clean market with an in-window quote (ok + no_discount) — for the leg-price
    #                             distribution. The "show every number" rule: a no_discount skip is still data.
    skipped: Counter = Counter()
    for i, m in enumerate(markets, 1):
        start = m.proposal_ts - timedelta(seconds=WINDOW_PAD_SEC)
        end = m.liveness_end + timedelta(seconds=WINDOW_PAD_SEC)
        series = window_odds(m.yes_token, start, end)
        odds_by_cid[m.condition_id] = series
        tr, reason = build_trade(m, series)
        skipped[reason] += 1
        if tr is not None:
            records.append(tr)  # carries the entry leg price; `reason` distinguishes ok vs no_discount
        if i % 25 == 0:
            print(f"  [N1] {i}/{len(markets)} markets, {len(records)} records so far", file=sys.stderr)
        time.sleep(0.05)

    # TRADES = the pre-registered ENTRY subset: about-to-win leg discounted (mid <= ENTRY_MAX) at proposal.
    trades = [t for t in records if t.entry_mid <= ENTRY_MAX]
    cats = [summarize(trades, c) for c in ("geopolitics", "sports", "crypto")]
    pooled = gate_stats([t.net_ret for t in trades]) if trades else {"n": 0}
    tripwire = run_tripwire(markets, odds_by_cid)

    # The convergence diagnostic across ALL records (tradeable or not): how close to $1 was the about-to-win leg
    # at the proposal landing, and already 30m BEFORE the window? If both ~$1, the market converged pre-proposal.
    legs_at_entry = [t.entry_mid for t in records]
    legs_pre_window = [t.leg_pre_window for t in records]
    frac_ge_097 = (sum(1 for x in legs_at_entry if x >= ENTRY_MAX) / len(legs_at_entry)) if legs_at_entry else None
    frac_ge_099 = (sum(1 for x in legs_at_entry if x >= 0.99) / len(legs_at_entry)) if legs_at_entry else None

    meta = {
        "n_markets_clean": len(markets),
        "n_records_with_window_quote": len(records),
        "n_trades": len(trades),
        "entry_max": ENTRY_MAX,
        "clob_half_spread": CLOB_HALF_SPREAD,
        "default_liveness_sec": DEFAULT_LIVENESS_SEC,
    }
    out_html = render_html(records, trades, cats, skipped, meta, tripwire,
                           {"frac_ge_097": frac_ge_097, "frac_ge_099": frac_ge_099,
                            "mean_leg_at_entry": fmean(legs_at_entry) if legs_at_entry else None,
                            "mean_leg_pre_window": fmean(legs_pre_window) if legs_pre_window else None})
    with open(args.out, "w") as f:
        f.write(out_html)

    summary = {
        "meta": meta,
        "skipped": dict(skipped),
        "convergence_diagnostic": {
            "mean_winning_leg_at_proposal": fmean(legs_at_entry) if legs_at_entry else None,
            "mean_winning_leg_30m_before_window": fmean(legs_pre_window) if legs_pre_window else None,
            "frac_leg_ge_0.97_at_proposal": frac_ge_097,
            "frac_leg_ge_0.99_at_proposal": frac_ge_099,
            "interpretation": (
                "winning leg already ~$1 at AND before proposal -> converged pre-proposal -> no discount to capture"
            ),
        },
        "per_category": cats,
        "pooled_gate": pooled,
        "tripwire": {k: v for k, v in tripwire.items() if k != "render"},
        "convergence_sign": (
            "up_to_$1 (gap exists, tradeable)" if trades and fmean([t.leg_discount for t in trades]) > 0
            else "no_gap (already converged before proposal)"
        ),
        "mean_net_ret_pooled": fmean([t.net_ret for t in trades]) if trades else None,
        "mean_leg_discount_pooled": fmean([t.leg_discount for t in trades]) if trades else None,
        "html": args.out,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
