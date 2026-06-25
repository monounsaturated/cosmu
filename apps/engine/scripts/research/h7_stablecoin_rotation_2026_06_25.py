#!/usr/bin/env python3
"""H7 STABLECOIN CHAIN-ROTATION -> native token — EXPERIMENT ONLY, ZERO production impact.

THESIS (pre-registered): stablecoin float SHARE rotating ONTO a chain pre-positions on-chain demand
before the under-covered native token reprices. The share-CHANGE derivative (NOT the level) is the
carrier — it is what dodges the prior "on-chain LEVEL IC = cycle artifact" failure
([[orthogonal_data_round_2026-06-14]]). Niche mid-tier chains (TRON / Solana / Base) = the attention moat.

This script writes NOTHING to any prod store, touches NO Gate constant, changes NO behaviour. It is a
self-contained offline event-study that:
  (1) pulls REAL, PIT per-chain stablecoin float from the SAME free DefiLlama endpoint the wired
      `stablecoin_eth_share` feature uses (https://stablecoins.llama.fi/stablecoincharts/{Chain}),
      with available_at == ts + 1 day (a daily aggregate is finalized after the UTC day closes; the
      EARLIEST day-T is knowable is day T+1 — the EXACT PIT contract of the in-tree source, verified
      against cosmu/data/sources/stablecoin_flows.py),
  (2) computes per-chain SHARE = chain_total(T) / all_chains_total(T) in [0,1], then the 14-day
      SHARE-CHANGE  dshare(T) = share(T) - share(T-14)  (the DERIVATIVE, the pre-registered carrier),
  (3) flags a top-tercile share-INFLOW event when dshare(T) sits in the TOP THIRD of a TRAILING
      180-day distribution of that chain's dshare strictly BEFORE day T (point-in-time tercile),
  (4) labels each event by the forward N-day return on the MATCHED native token (TRON->TRX,
      Solana->SOL; Bybit keyless spot daily close), net of round-trip Bybit fees,
  (5) POOLS matched events across chains into ONE basket to clear the >=30 floor WITHOUT manufacturing
      trades, then runs the THREE honest checks (N>=30, sign>0, gross edge > 2x round-trip fee),
  (6) runs the CRITICAL DISCONFIRMERS:
        PLACEBO-CHAIN null  — the SAME TRON event-set must predict TRX, NOT a mismatched token
                              (TRON-event -> SOL) and NOT BTC. If the placebo token's net edge is
                              comparable to the matched token's, the "edge" is a market-wide cycle/beta
                              artifact => KILL.
        SHARE-CHANGE carrier — the share-CHANGE event-set must beat the share-LEVEL event-set
                              (top-tercile of the LEVEL = the prior failed axis). If level carries it
                              too, the derivative is not the source => suspect cycle => KILL.
  (7) ONLY IF the matched edge clears a/b/c AND beats the placebo AND change-carries-not-level does it
      run the matched basket through the BRUT Gate (DSR / PBO / PSR), on its OWN data, no pooling
      deflation tricks.

PRE-REGISTERED knobs (NO sweep — best-of-N is the trap):
  HORIZON_DAYS = 5 | SHARE_CHANGE_WINDOW_DAYS = 14 | TERCILE_WINDOW_DAYS = 180 | tercile = TOP THIRD
  chains = {TRON->TRX, Solana->SOL}; Base = share-denominator + placebo-discussion only (no clean
  native spot token). Reference price = Bybit keyless spot daily close. Fees = REAL Bybit (taker 10bps).

Run:  python3 scripts/research/h7_stablecoin_rotation_2026_06_25.py
Out:  scripts/research/h7_stablecoin_rotation_results_2026_06_25.json  (raw numbers for report/HTML)
"""
from __future__ import annotations

import gc
import json
import math
import ssl
import statistics
import sys
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import certifi

_ENGINE = Path(__file__).resolve().parents[2]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import GateSettings  # noqa: E402
from cosmu.data.market import Bar, BybitSpotOHLCVProvider  # noqa: E402
from cosmu.master.scorer import (  # noqa: E402
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    deflated_sharpe_prob,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.spine.venue import default_catalog  # noqa: E402

# ----------------------------------------------------------------------------------------------------
# PRE-REGISTERED config (locked before looking at any result)
# ----------------------------------------------------------------------------------------------------
HORIZON_DAYS = 5               # forward N-day return on the matched native token
SHARE_CHANGE_WINDOW_DAYS = 14  # the share-CHANGE derivative window (the pre-registered carrier)
TERCILE_WINDOW_DAYS = 180      # trailing window the top-tercile cut is computed over (PIT: strictly before T)
TERCILE = "top"                # top third = INFLOW event
AVAILABILITY_LAG_DAYS = 1      # PIT: a daily aggregate is knowable day T+1 (mirrors the wired source)

# Matched chain -> native token. DefiLlama chain spelling | Bybit keyless spot base.
# Base is an L2 with no clean native gas token tradeable as keyless spot -> excluded from the matched
# study (kept only as a share denominator + named in the placebo discussion).
MATCHED = {
    "Tron":   {"token": "TRXUSDT", "placebo_token": "SOLUSDT"},
    "Solana": {"token": "SOLUSDT", "placebo_token": "TRXUSDT"},
}
# Chains that contribute to the per-chain share series we study (denominator is always the 'all' total).
STUDY_CHAINS = ("Tron", "Solana", "Base")
PLACEBO_MARKET = "BTCUSDT"     # the market-wide beta placebo (every chain-event also tested vs BTC)

CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/{chain}"
ALL_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

GATES = GateSettings()  # LOCKED: DSR>=0.95 PBO<=0.50 folds>=0.60 min_trades>=30 holdout>=0 beat-B&H
OUT_JSON = _ENGINE / "scripts" / "research" / "h7_stablecoin_rotation_results_2026_06_25.json"


def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def _day(ts: datetime) -> datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


# ----------------------------------------------------------------------------------------------------
# data: per-chain stablecoin float (PIT) + matched native token spot
# ----------------------------------------------------------------------------------------------------
def _extract_total(row: dict) -> float | None:
    """Total circulating USD from a stablecoincharts row (mirrors cosmu/data/sources/stablecoin_flows.py)."""
    for key in ("totalCirculatingUSD", "totalCirculating"):
        val = row.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            try:
                s = sum(float(v) for v in val.values() if v is not None)
            except (ValueError, TypeError):
                continue
            return s if s > 0 else None
        try:
            f = float(val)
        except (ValueError, TypeError):
            continue
        return f if f > 0 else None
    return None


def _daily_totals(payload, ctx_url: str) -> dict[datetime, float]:
    """Parse a stablecoincharts payload into {midnight-UTC day -> total_usd}. Missing/non-positive dropped."""
    if not isinstance(payload, list):
        print(f"  ! unexpected payload shape from {ctx_url}", file=sys.stderr)
        return {}
    out: dict[datetime, float] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        if raw_date is None:
            continue
        try:
            raw = datetime.fromtimestamp(int(raw_date), tz=UTC)
        except (ValueError, TypeError, OSError, OverflowError):
            continue
        ts = datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
        total = _extract_total(row)
        if total is None or total <= 0:
            continue
        out[ts] = total
    return out


def _fetch_json(url: str, ctx) -> object:  # noqa: ANN001
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as resp:  # noqa: S310 — fixed DefiLlama host
        return json.loads(resp.read().decode("utf-8"))


def build_share_series(ctx) -> tuple[dict, dict, dict]:  # noqa: ANN001
    """Return (share_by_chain, dshare_by_chain, coverage).

    share_by_chain[chain]  = {day -> chain_total(day) / all_total(day)}        (the LEVEL)
    dshare_by_chain[chain] = {day -> share(day) - share(day - 14d)}            (the CHANGE = carrier)
    Both are PIT: a day-T value is knowable only day T+1 (handled at event-build time)."""
    all_totals = _daily_totals(_fetch_json(ALL_URL, ctx), ALL_URL)
    share_by_chain: dict[str, dict[datetime, float]] = {}
    dshare_by_chain: dict[str, dict[datetime, float]] = {}
    coverage: dict[str, dict] = {}
    for chain in STUDY_CHAINS:
        chain_totals = _daily_totals(_fetch_json(CHART_URL.format(chain=chain), ctx), chain)
        share: dict[datetime, float] = {}
        for ts, ct in chain_totals.items():
            whole = all_totals.get(ts)
            if whole and whole > 0:
                s = ct / whole
                share[ts] = max(0.0, min(1.0, s))
        # 14d share-CHANGE — only when BOTH endpoints exist (never invent across a gap).
        dshare: dict[datetime, float] = {}
        for ts in share:
            past = ts - timedelta(days=SHARE_CHANGE_WINDOW_DAYS)
            if past in share:
                dshare[ts] = share[ts] - share[past]
        share_by_chain[chain] = share
        dshare_by_chain[chain] = dshare
        days = sorted(share)
        coverage[chain] = {
            "share_days": len(share),
            "dshare_days": len(dshare),
            "from": str(days[0].date()) if days else None,
            "to": str(days[-1].date()) if days else None,
            "last_share_pct": round(share[days[-1]] * 100, 2) if days else None,
        }
        print(f"  {chain:8s}: share={len(share)}d dshare={len(dshare)}d "
              f"{coverage[chain]['from']}..{coverage[chain]['to']} last_share={coverage[chain]['last_share_pct']}%")
        gc.collect()
    coverage["_all_total_days"] = len(all_totals)
    return share_by_chain, dshare_by_chain, coverage


def token_daily_close(provider: BybitSpotOHLCVProvider, symbol: str) -> dict[datetime, float]:
    """Bybit keyless spot daily CLOSE keyed by day. Real, keyless, PIT (closed daily candle)."""
    try:
        bars: list[Bar] = provider.fetch_bars(symbol, "1d", limit=1000)
    except Exception as e:  # noqa: BLE001
        print(f"  ! bybit spot failed {symbol}: {e}", file=sys.stderr)
        return {}
    return {_day(b.ts): float(b.close) for b in bars}


# ----------------------------------------------------------------------------------------------------
# event study
# ----------------------------------------------------------------------------------------------------
@dataclass
class Event:
    chain: str
    day: str
    dshare: float           # the 14d share-CHANGE that triggered the event
    share_level: float      # the share LEVEL that day (for the carrier disconfirmer)
    tercile_cut: float      # the trailing-180d top-tercile threshold that day (PIT)
    matched_token: str
    matched_net: float      # forward-N-day return on the matched token, NET of round-trip fee
    placebo_net: float      # same window, MISMATCHED token (cross-chain), NET
    btc_net: float          # same window, BTC (market beta placebo), NET
    level_event: bool       # would the LEVEL top-tercile also fire here? (carrier check, per-event)


@dataclass
class Report:
    config: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    fees: dict = field(default_factory=dict)
    n_events: int = 0
    per_chain: dict = field(default_factory=dict)
    matched_mean_bps: float = 0.0
    matched_median_bps: float = 0.0
    matched_frac_pos: float = 0.0
    placebo_mean_bps: float = 0.0       # mismatched-token pooled mean
    btc_mean_bps: float = 0.0           # BTC pooled mean
    level_matched_mean_bps: float = 0.0  # share-LEVEL event-set matched mean (carrier disconfirmer)
    level_n: int = 0
    # UNCONDITIONAL-DRIFT disconfirmer (the decisive one): the matched token's forward-N-day mean over
    # ALL days vs the event-conditional mean. If event <= unconditional, the "edge" is just being long a
    # token that drifted up — no chain-rotation signal. Reported per-chain as LIFT = event - unconditional.
    drift_lift_by_chain: dict = field(default_factory=dict)
    pooled_lift_bps: float = 0.0        # event-mean minus matched-token unconditional drift, pooled
    drift_killed: bool = False          # True = no positive lift over unconditional drift => artifact
    # independence: top-tercile fires ~1/3 of days, so 5d windows overlap ~4x; report non-overlap count.
    n_nonoverlap: int = 0
    roundtrip_fee_bps: float = 0.0
    fee_hurdle_bps: float = 0.0
    check_a_min30: bool = False
    check_b_sign: bool = False
    check_c_edge_gt_2xfee: bool = False
    placebo_killed: bool = False        # True = placebo comparable/bigger => artifact
    level_carries: bool = False         # True = LEVEL carries it too => not the change => suspect
    gate: dict = field(default_factory=dict)
    verdict: str = ""
    events: list = field(default_factory=list)


def _fwd_net(prices: dict[datetime, float], d: datetime, fee_frac: float) -> float | None:
    """Forward HORIZON-day LONG return on `prices`, net of one round-trip fee. None if no entry/exit."""
    entry = prices.get(d)
    exit_px = prices.get(d + timedelta(days=HORIZON_DAYS))
    if entry is None or exit_px is None or entry <= 0:
        return None
    return (exit_px / entry - 1.0) - fee_frac


def _top_tercile_cut(values: list[float]) -> float | None:
    """Top-tercile (66.7th pct) threshold of a trailing distribution. None if too thin to be stable."""
    if len(values) < 20:
        return None
    s = sorted(values)
    idx = int(round((len(s) - 1) * (2.0 / 3.0)))
    return s[idx]


def _unconditional_fwd_drift_bps(prices: dict[datetime, float]) -> tuple[float, int]:
    """Mean GROSS forward-HORIZON-day return over ALL days (the token's own drift baseline). The decisive
    disconfirmer: a real chain-rotation edge must beat simply being long this token unconditionally."""
    rets = []
    for d in prices:
        e = prices.get(d)
        x = prices.get(d + timedelta(days=HORIZON_DAYS))
        if e and x and e > 0:
            rets.append(x / e - 1.0)
    if not rets:
        return float("nan"), 0
    return statistics.fmean(rets) * 10_000, len(rets)


def run_event_study(
    share_by_chain: dict, dshare_by_chain: dict, token_prices: dict, fee_frac: float, fee_bps: float
) -> Report:
    rep = Report()
    rep.config = {
        "horizon_days": HORIZON_DAYS, "share_change_window_days": SHARE_CHANGE_WINDOW_DAYS,
        "tercile_window_days": TERCILE_WINDOW_DAYS, "tercile": TERCILE,
        "availability_lag_days": AVAILABILITY_LAG_DAYS,
        "matched": {c: m["token"] for c, m in MATCHED.items()},
        "study_chains": list(STUDY_CHAINS), "placebo_market": PLACEBO_MARKET,
        "reference_price": "bybit_spot_daily_close", "carrier": "14d_share_change (NOT level)",
    }
    rep.roundtrip_fee_bps = round(fee_bps, 2)
    rep.fee_hurdle_bps = round(2.0 * fee_bps, 2)  # the thesis bar: gross > 2x round-trip

    matched_rets: list[float] = []
    matched_gross: list[float] = []          # GROSS (no fee) — compared apples-to-apples vs unconditional drift
    placebo_rets: list[float] = []
    btc_rets: list[float] = []
    level_matched_rets: list[float] = []
    per_chain_rets: dict[str, list[float]] = defaultdict(list)
    per_chain_gross: dict[str, list[float]] = defaultdict(list)
    event_days_by_chain: dict[str, list[datetime]] = defaultdict(list)
    events: list[Event] = []

    btc_prices = token_prices.get(PLACEBO_MARKET, {})
    # matched-token unconditional forward drift (the decisive baseline) per chain.
    uncond_by_chain = {
        chain: _unconditional_fwd_drift_bps(token_prices.get(meta["token"], {}))
        for chain, meta in MATCHED.items()
    }

    for chain, meta in MATCHED.items():
        dshare = dshare_by_chain.get(chain, {})
        share = share_by_chain.get(chain, {})
        matched_px = token_prices.get(meta["token"], {})
        placebo_px = token_prices.get(meta["placebo_token"], {})
        if not dshare or not matched_px:
            continue
        days = sorted(dshare)
        for d in days:
            # PIT availability: a day-T aggregate is knowable only T+1, so an event is ACTABLE the
            # next day. We enter on the matched token's close at d+1 (entry day = d + lag).
            entry_day = d + timedelta(days=AVAILABILITY_LAG_DAYS)
            # trailing top-tercile of dshare strictly BEFORE day d (PIT)
            window = [
                dshare[d - timedelta(days=k)]
                for k in range(1, TERCILE_WINDOW_DAYS + 1)
                if (d - timedelta(days=k)) in dshare
            ]
            cut = _top_tercile_cut(window)
            if cut is None:
                continue
            if dshare[d] <= cut:
                continue  # only top-tercile INFLOW days fire
            # matched forward net (entered the actable day after the signal)
            mnet = _fwd_net(matched_px, entry_day, fee_frac)
            if mnet is None:
                continue
            mgross = mnet + fee_frac  # add the fee back for the gross-vs-unconditional comparison
            pnet = _fwd_net(placebo_px, entry_day, fee_frac)
            bnet = _fwd_net(btc_prices, entry_day, fee_frac)
            # carrier disconfirmer: would the LEVEL top-tercile ALSO have fired on this day?
            lvl_window = [
                share[d - timedelta(days=k)]
                for k in range(1, TERCILE_WINDOW_DAYS + 1)
                if (d - timedelta(days=k)) in share
            ]
            lvl_cut = _top_tercile_cut(lvl_window)
            level_fire = lvl_cut is not None and share.get(d, -1) > lvl_cut
            ev = Event(
                chain=chain, day=str(d.date()), dshare=round(dshare[d], 6),
                share_level=round(share.get(d, float("nan")), 6), tercile_cut=round(cut, 6),
                matched_token=meta["token"], matched_net=mnet,
                placebo_net=pnet if pnet is not None else float("nan"),
                btc_net=bnet if bnet is not None else float("nan"),
                level_event=bool(level_fire),
            )
            events.append(ev)
            matched_rets.append(mnet)
            matched_gross.append(mgross)
            per_chain_rets[chain].append(mnet)
            per_chain_gross[chain].append(mgross)
            event_days_by_chain[chain].append(d)
            if pnet is not None:
                placebo_rets.append(pnet)
            if bnet is not None:
                btc_rets.append(bnet)

    # SEPARATE level-event-set (share LEVEL top-tercile -> matched token) for the carrier disconfirmer.
    for chain, meta in MATCHED.items():
        share = share_by_chain.get(chain, {})
        matched_px = token_prices.get(meta["token"], {})
        if not share or not matched_px:
            continue
        for d in sorted(share):
            entry_day = d + timedelta(days=AVAILABILITY_LAG_DAYS)
            window = [
                share[d - timedelta(days=k)]
                for k in range(1, TERCILE_WINDOW_DAYS + 1)
                if (d - timedelta(days=k)) in share
            ]
            cut = _top_tercile_cut(window)
            if cut is None or share[d] <= cut:
                continue
            mnet = _fwd_net(matched_px, entry_day, fee_frac)
            if mnet is not None:
                level_matched_rets.append(mnet)

    rep.n_events = len(events)
    rep.events = [asdict(e) for e in events]
    if not events:
        rep.verdict = "KILL — zero top-tercile share-INFLOW events with a valid forward price."
        return rep

    rep.matched_mean_bps = statistics.fmean(matched_rets) * 10_000
    rep.matched_median_bps = statistics.median(matched_rets) * 10_000
    rep.matched_frac_pos = sum(1 for x in matched_rets if x > 0) / len(matched_rets)
    rep.placebo_mean_bps = statistics.fmean(placebo_rets) * 10_000 if placebo_rets else float("nan")
    rep.btc_mean_bps = statistics.fmean(btc_rets) * 10_000 if btc_rets else float("nan")
    rep.level_n = len(level_matched_rets)
    rep.level_matched_mean_bps = (
        statistics.fmean(level_matched_rets) * 10_000 if level_matched_rets else float("nan")
    )
    rep.per_chain = {
        c: {
            "n": len(r), "mean_bps": round(statistics.fmean(r) * 10_000, 2),
            "median_bps": round(statistics.median(r) * 10_000, 2),
            "frac_pos": round(sum(1 for x in r if x > 0) / len(r), 3),
        }
        for c, r in sorted(per_chain_rets.items()) if r
    }

    # --- UNCONDITIONAL-DRIFT disconfirmer (the decisive one) ---
    # Per chain: event-conditional GROSS mean vs the matched token's GROSS unconditional forward drift.
    # LIFT = event - unconditional. A real rotation edge must have a positive lift; otherwise the "edge"
    # is just being long a token that drifted up over the window (per-token beta, not a chain signal).
    pooled_lift_num = 0.0
    pooled_lift_den = 0
    for chain, g in per_chain_gross.items():
        uc_bps, uc_n = uncond_by_chain.get(chain, (float("nan"), 0))
        ev_bps = statistics.fmean(g) * 10_000
        lift = ev_bps - uc_bps
        rep.drift_lift_by_chain[chain] = {
            "event_gross_bps": round(ev_bps, 2),
            "unconditional_gross_bps": round(uc_bps, 2),
            "lift_bps": round(lift, 2),
            "n": len(g),
        }
        pooled_lift_num += lift * len(g)
        pooled_lift_den += len(g)
    rep.pooled_lift_bps = round(pooled_lift_num / pooled_lift_den, 2) if pooled_lift_den else float("nan")
    # KILL unless the lift over unconditional drift is positive on EVERY matched chain. A real
    # chain-rotation edge must GENERALIZE across chains, not live on one high-beta name (SOL) whose
    # "inflow" days coincide with its own bull phase. A single positive chain pooling against a flat/
    # negative one is precisely the per-token-beta artifact the placebo test is too weak to catch when
    # one matched token out-drifts the placebo universe over the window.
    all_chains_positive = bool(rep.drift_lift_by_chain) and all(
        v["lift_bps"] > 0 for v in rep.drift_lift_by_chain.values()
    )
    rep.drift_killed = (not all_chains_positive) or (rep.pooled_lift_bps <= 0)

    # independence: count non-overlapping events (>= HORIZON days apart) per chain, pooled.
    nonoverlap = 0
    for days in event_days_by_chain.values():
        last = None
        for d in sorted(days):
            if last is None or (d - last).days >= HORIZON_DAYS:
                nonoverlap += 1
                last = d
    rep.n_nonoverlap = nonoverlap

    # --- three honest checks ---
    rep.check_a_min30 = rep.n_events >= GATES.min_trades
    rep.check_b_sign = rep.matched_mean_bps > 0
    rep.check_c_edge_gt_2xfee = rep.matched_mean_bps > rep.fee_hurdle_bps

    # --- disconfirmers ---
    # PLACEBO killed if the matched edge is NOT clearly bigger than the placebo/BTC mean (artifact).
    # Require matched to beat BOTH the mismatched-token mean AND BTC by a clear margin (>= the matched's
    # own half-mean, a conservative "specifically predicts" bar). NaN placebo => cannot clear => suspect.
    placebo_ref = max(
        rep.placebo_mean_bps if not math.isnan(rep.placebo_mean_bps) else -1e9,
        rep.btc_mean_bps if not math.isnan(rep.btc_mean_bps) else -1e9,
    )
    rep.placebo_killed = not (rep.matched_mean_bps > 0 and rep.matched_mean_bps > placebo_ref + abs(rep.matched_mean_bps) * 0.5)
    # LEVEL carries it if the level-event matched mean is >= the change-event matched mean (derivative
    # is then NOT the source of the edge => suspect cycle).
    rep.level_carries = (
        not math.isnan(rep.level_matched_mean_bps)
        and rep.level_matched_mean_bps >= rep.matched_mean_bps
    )

    rep.gate = {
        "check_a_min30": rep.check_a_min30, "check_b_sign": rep.check_b_sign,
        "check_c_edge_gt_2xfee": rep.check_c_edge_gt_2xfee,
        "placebo_killed": rep.placebo_killed, "level_carries": rep.level_carries,
        "drift_killed": rep.drift_killed, "pooled_lift_bps": rep.pooled_lift_bps,
    }

    promote = (
        rep.check_a_min30 and rep.check_b_sign and rep.check_c_edge_gt_2xfee
        and not rep.placebo_killed and not rep.level_carries and not rep.drift_killed
    )
    if promote:
        net = matched_rets
        sr, skew, kurt, n = sample_moments(net)
        days_sorted = sorted({e.day for e in events})
        span_days = max(1, (datetime.fromisoformat(days_sorted[-1]) - datetime.fromisoformat(days_sorted[0])).days)
        ev_per_year = len(net) / (span_days / 365.25)
        ann_sharpe = sr * math.sqrt(ev_per_year) if ev_per_year > 0 else 0.0
        psr0 = probabilistic_sharpe(sr, n, skew, kurt, 0.0)
        config_returns = _horizon_family_returns(share_by_chain, dshare_by_chain, token_prices, fee_frac)
        pbo = cscv_pbo(config_returns) if len(config_returns) >= 2 else 1.0
        folds = _folds_positive(net, k=5)
        metrics = BacktestMetrics(
            oos_return=Decimal(str(sum(net))), buy_and_hold_return=Decimal("0"),
            sharpe=Decimal(str(round(ann_sharpe, 4))), sortino=Decimal("0"), max_drawdown=Decimal("0"),
            win_rate=Decimal(str(round(rep.matched_frac_pos, 4))), num_trades=n,
            sharpe_per_obs=Decimal(str(round(sr, 6))), skew=Decimal(str(round(skew, 6))),
            kurtosis=Decimal(str(round(kurt, 6))), n_obs=n,
            pbo=Decimal(str(round(pbo, 4))), trials_counted=len(config_returns) or 1,
            folds_positive_pct=Decimal(str(round(folds, 4))), holdout_deflated_sharpe=Decimal("0"),
        )
        verdict = score(metrics, GATES, trials=TrialStats(count=max(len(config_returns), 1)), check_holdout=False)
        dsr = deflated_sharpe_prob(metrics, TrialStats(count=max(len(config_returns), 1)))
        rep.gate.update({
            "sharpe_per_obs": round(sr, 4), "ann_sharpe": round(ann_sharpe, 3),
            "psr_vs_zero": round(psr0, 4), "deflated_sharpe": round(dsr, 4),
            "pbo": round(pbo, 4), "folds_positive": round(folds, 4),
            "ev_per_year": round(ev_per_year, 1), "gate_passed": bool(verdict.passed),
            "killed_by": list(verdict.reasons),
        })
        rep.verdict = ("GO — cleared a/b/c + survived placebo + change-carries; "
                       + ("Gate PASS" if verdict.passed else f"Gate FAIL (killed_by={verdict.reasons})"))
    else:
        fails = []
        if not rep.check_a_min30:
            fails.append("a:>=30")
        if not rep.check_b_sign:
            fails.append("b:sign")
        if not rep.check_c_edge_gt_2xfee:
            fails.append("c:edge>2xfee")
        if rep.placebo_killed:
            fails.append("PLACEBO (matched not specific vs mismatched/BTC)")
        if rep.level_carries:
            fails.append("LEVEL-carries (derivative not the source)")
        if rep.drift_killed:
            fails.append("DRIFT (no lift over matched token's unconditional forward drift)")
        rep.verdict = (f"KILL — failed {fails}. matched={rep.matched_mean_bps:.1f}bps "
                       f"vs hurdle {rep.fee_hurdle_bps:.0f}bps; pooled_lift_over_drift={rep.pooled_lift_bps:.1f}bps; "
                       f"placebo(mismatch)={rep.placebo_mean_bps:.1f}bps BTC={rep.btc_mean_bps:.1f}bps "
                       f"level={rep.level_matched_mean_bps:.1f}bps")
    return rep


def _horizon_family_returns(share_by_chain, dshare_by_chain, token_prices, fee_frac):  # noqa: ANN001
    """Per-config matched-net return series for horizon in {3,5,7} — the CSCV-PBO config family.
    Robustness probe ONLY; the pre-registered point estimate stays HORIZON_DAYS=5."""
    out: list[list[float]] = []
    for h in (3, 5, 7):
        rets: list[float] = []
        for chain, meta in MATCHED.items():
            dshare = dshare_by_chain.get(chain, {})
            matched_px = token_prices.get(meta["token"], {})
            if not dshare or not matched_px:
                continue
            for d in sorted(dshare):
                entry_day = d + timedelta(days=AVAILABILITY_LAG_DAYS)
                window = [dshare[d - timedelta(days=k)] for k in range(1, TERCILE_WINDOW_DAYS + 1)
                          if (d - timedelta(days=k)) in dshare]
                cut = _top_tercile_cut(window)
                if cut is None or dshare[d] <= cut:
                    continue
                entry = matched_px.get(entry_day)
                exit_px = matched_px.get(entry_day + timedelta(days=h))
                if entry and exit_px and entry > 0:
                    rets.append((exit_px / entry - 1.0) - fee_frac)
        if len(rets) >= 4:
            out.append(rets)
        gc.collect()
    if out:
        n = min(len(r) for r in out)
        out = [r[:n] for r in out]
    return out


def _folds_positive(returns: list[float], k: int = 5) -> float:
    if len(returns) < k:
        return 0.0
    fold = len(returns) // k
    pos = 0
    for i in range(k):
        seg = returns[i * fold:(i + 1) * fold] if i < k - 1 else returns[i * fold:]
        if seg and statistics.fmean(seg) > 0:
            pos += 1
    return pos / k


def main() -> int:
    ctx = _ctx()
    print("H7 STABLECOIN CHAIN-ROTATION -> native token — EXPERIMENT ONLY, ZERO prod impact")
    print(f"  pre-registered: horizon={HORIZON_DAYS}d  share_change_window={SHARE_CHANGE_WINDOW_DAYS}d  "
          f"tercile=TOP/{TERCILE_WINDOW_DAYS}d  chains={list(MATCHED)}  ref=bybit_spot")
    print("  building per-chain stablecoin SHARE + 14d CHANGE (REAL, PIT, DefiLlama)...")
    share_by_chain, dshare_by_chain, coverage = build_share_series(ctx)

    print("  fetching matched + placebo token spot (Bybit keyless)...")
    bybit = BybitSpotOHLCVProvider()
    needed = sorted({m["token"] for m in MATCHED.values()}
                    | {m["placebo_token"] for m in MATCHED.values()} | {PLACEBO_MARKET})
    token_prices: dict[str, dict[datetime, float]] = {}
    for sym in needed:
        token_prices[sym] = token_daily_close(bybit, sym)
        days = sorted(token_prices[sym])
        cov = {"days": len(days), "from": str(days[0].date()) if days else None,
               "to": str(days[-1].date()) if days else None}
        coverage[f"token:{sym}"] = cov
        print(f"  {sym:10s} {cov['days']}d {cov['from']}..{cov['to']}")

    cat = default_catalog()
    by = cat.venue_for(["bybit"])
    fee_bps = float(by.taker_fee_bps)
    slip_bps = float(by.slippage_bps)
    roundtrip = 2.0 * fee_bps + 2.0 * slip_bps  # round-trip taker + entry/exit slippage
    fee_frac = roundtrip / 10_000.0

    rep = run_event_study(share_by_chain, dshare_by_chain, token_prices, fee_frac, roundtrip)
    rep.coverage = coverage
    rep.fees = {"bybit_taker_bps": fee_bps, "bybit_slippage_bps": slip_bps,
                "roundtrip_all_in_bps": round(roundtrip, 2), "hurdle_2x_bps": round(2.0 * roundtrip, 2)}

    OUT_JSON.write_text(json.dumps(asdict(rep), indent=2, default=str))
    print(f"\n  events N = {rep.n_events}  (non-overlapping >= {HORIZON_DAYS}d apart = {rep.n_nonoverlap})")
    print(f"  matched mean = {rep.matched_mean_bps:.1f} bps  median = {rep.matched_median_bps:.1f} bps  "
          f"frac_pos = {rep.matched_frac_pos:.2%}")
    print(f"  PLACEBO: mismatched-token mean = {rep.placebo_mean_bps:.1f} bps  BTC mean = {rep.btc_mean_bps:.1f} bps")
    print(f"  LEVEL  : level-event matched mean = {rep.level_matched_mean_bps:.1f} bps (n={rep.level_n})")
    print("  DRIFT (decisive): event-gross vs matched-token unconditional forward drift —")
    for c, v in rep.drift_lift_by_chain.items():
        print(f"     {c:8s} event={v['event_gross_bps']:.1f}bps  uncond={v['unconditional_gross_bps']:.1f}bps  "
              f"LIFT={v['lift_bps']:.1f}bps  (n={v['n']})")
    print(f"     pooled LIFT over drift = {rep.pooled_lift_bps:.1f} bps")
    print(f"  checks: a(>=30)={rep.check_a_min30} b(sign)={rep.check_b_sign} c(edge>{rep.fee_hurdle_bps:.0f}bps)={rep.check_c_edge_gt_2xfee}")
    print(f"  disconfirmers: placebo_killed={rep.placebo_killed}  level_carries={rep.level_carries}  drift_killed={rep.drift_killed}")
    if "gate_passed" in rep.gate:
        print(f"  GATE: DSR={rep.gate['deflated_sharpe']} PBO={rep.gate['pbo']} folds={rep.gate['folds_positive']} "
              f"passed={rep.gate['gate_passed']} killed_by={rep.gate['killed_by']}")
    print(f"\n  VERDICT: {rep.verdict}")
    print(f"  wrote -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
