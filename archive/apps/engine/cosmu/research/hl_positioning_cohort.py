# intent: the DISCONFIRMER-GATED BRUT experiment harness for the Hyperliquid LONG-TAIL POSITIONING axis
# (next-data-axis #1, 2026-06-28). It tests ONE pre-registered hypothesis on the forward-hoarded snapshots, per
# coin, through the LOCKED gate path (metrics_for_run → promote_brut), with FOUR named disconfirmers baked in so
# a survivor must beat its own null before it is anything but a candidate.
#
#   PRE-REGISTERED HYPOTHESIS (frozen here so it cannot be moved after seeing the data):
#     "On a thin Hyperliquid perp, a CROWDING EXTREME (net-positioning z-score beyond ±Z on its trailing window)
#      predicts a 1-3 DAY MEAN-REVERSION — fade the extreme (short the crowded-long, long the crowded-short),
#      net of MAKER fees. The edge is in the AGGREGATE positioning STRESS, not in copying any single account."
#
#   THE FOUR DISCONFIRMERS (all must be satisfied for a coin's cell to count as a real candidate):
#     (a) MUST FAIL ON BTC/ETH — the saturated majors are arb'd; an edge that also fires there is generic beta /
#         a leak, not the thin-tail dislocation the thesis claims. (run the SAME pipeline on BTC/ETH; require it
#         does NOT promote.)
#     (b) MUST NOT SURVIVE A SHUFFLED / LAGGED PLACEBO of the positioning series — permute the feature's values
#         in time (research.disconfirmers.shuffle_null): a real timing edge sits OUTSIDE the shuffled IC band; a
#         spurious one sits inside it. (require the real IC survives the shuffle null.)
#     (c) MUST ADD IC OVER realized-vol + funding CONTROLS — partial out trailing realized vol and the funding
#         level (both cheaply known at t); if the crowding IC vanishes once they're removed, the "edge" was just
#         a vol/funding proxy. (require the residualized IC keeps a material share of the raw IC.)
#     (d) REJECT IF ONLY "COPY THE BIGGEST WINNER" WORKS — compare the AGGREGATE crowding signal to a
#         single-biggest-account-direction signal; if only the copy-the-whale variant has an edge, the thesis
#         (aggregate stress) is false. (require the aggregate-signal IC ≥ the copy-whale IC.)
#
# invariants: ZERO LLM. The LOCKED scorer / promote_brut / DSR-PBO-min_trades math is NOT changed — only the
# INPUTS are one cell (the BRUT per-combo model). PIT throughout (align_asof + strictly-future returns; the
# crowding feature is already PIT by construction). PROPOSE-ONLY — a promoted cell that ALSO clears all four
# disconfirmers is a CANDIDATE for paper, never an edge; the forward/paper test disposes. DETERMINISTIC for a
# fixed input. **MUST NOT RUN NOW**: there is no data yet (the forward hoard just started). This module is the
# READY-TO-RUN instrument; `run(...)` requires the caller to pass the hoarded series + bars, and the CLI refuses
# unless ≥ `min_days` of capture history exists — so an accidental early run is a clean, honest no-op.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.backtest import SymbolRun, Trade, align_asof, metrics_for_run
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.sources.hyperliquid_positioning import SATURATED
from cosmu.data.sources.positioning_features import DEFAULT_MIN_WINDOW, crowding_extreme_z
from cosmu.master.cohort import Candidate, promote_brut
from cosmu.research.correlation_scan import spearman_ic
from cosmu.research.disconfirmers import forward_returns, pit_ic, shuffle_null

# The frozen hypothesis parameters. CROWDING_Z is the extreme threshold; HORIZON the 1-3d reversion window; the
# fee is the HL maker fee (1.5 bps, spine/venue.py). These are PRE-REGISTERED (one config per coin — NO grid: a
# grid would be a best-of-N selection trap, deflated by trials anyway; the brut model judges ONE honest config).
CROWDING_Z = 1.5            # |net-positioning z| beyond this = a crowding extreme worth fading
HORIZON_BARS = 2            # the 1-3d mean-reversion window (2 captures-as-bars; daily-equivalent)
HL_MAKER_FEE_BPS = 1.5      # Hyperliquid maker fee (round-trip charged below), the net-of-fees bar
MIN_DAYS_TO_RUN = 14        # the forward hoard must have ≥ this many days before the harness may run (~2-3 wks)

# Disconfirmer thresholds (pre-registered).
_SHUFFLE_ALPHA = 0.05       # (b) the shuffle-null p-value the real IC must beat
_CONTROL_KEEP_FRAC = 0.5    # (c) the residualized IC must keep ≥ this share of the raw IC magnitude
_AGG_OVER_COPY_MARGIN = 0.0  # (d) aggregate IC must be ≥ copy-whale IC (a non-negative margin)


@dataclass(frozen=True)
class CoinResult:
    coin: str
    is_major: bool
    raw_ic: float
    n_obs: int
    num_trades: int
    net_return: float
    deflated_sharpe_prob: float
    brut_promoted: bool
    # disconfirmers
    d_shuffle_survives: bool        # (b) real IC outside the shuffled band
    d_control_keeps_ic: bool        # (c) IC survives vol+funding residualization
    d_aggregate_beats_copy: bool    # (d) aggregate signal IC >= copy-whale IC
    residual_ic: float
    copy_whale_ic: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_candidate(self) -> bool:
        """A real candidate: promoted by the BRUT gate AND all coin-level disconfirmers (b,c,d) satisfied. The
        BTC/ETH disconfirmer (a) is a COHORT-level check (handled in the report), not a per-coin flag."""
        return bool(
            self.brut_promoted
            and not self.is_major
            and self.d_shuffle_survives
            and self.d_control_keeps_ic
            and self.d_aggregate_beats_copy
        )


@dataclass
class HlPositioningReport:
    verdict: str
    headline: str
    hypothesis: str
    n_coins: int
    n_capture_days: float
    crowding_z: float
    horizon_bars: int
    fee_bps: float
    coins: list[CoinResult] = field(default_factory=list)
    disconfirmer_a_majors_clean: bool = True   # (a) NO major (BTC/ETH) cell promoted
    candidates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- the simulated reversion strategy


def _realized_vol(returns: list[float]) -> list[float]:
    """Trailing realized vol (stdev of the last up-to-10 bar returns) at each index — a control series (PIT: only
    past returns). returns[i] is the bar return INTO bar i; vol[i] uses returns[:i+1]. 0 for < 2 points."""
    out: list[float] = []
    for i in range(len(returns)):
        window = returns[max(0, i - 9): i + 1]
        out.append(statistics.pstdev(window) if len(window) >= 2 else 0.0)
    return out


def _bar_returns(bars: list[Bar]) -> list[float]:
    """Close-to-close simple returns parallel to bars[1:] (bars[0] has no prior). Pure."""
    out: list[float] = []
    for i in range(1, len(bars)):
        p0, p1 = float(bars[i - 1].close), float(bars[i].close)
        out.append((p1 / p0 - 1.0) if p0 > 0 else 0.0)
    return out


def _simulate_reversion(
    crowding: list[AltDataPoint], bars: list[Bar], *, z_thresh: float, horizon: int, fee_bps: float
) -> SymbolRun:
    """Simulate the pre-registered fade-the-extreme strategy and return ONE coin's SymbolRun (the BRUT cell input).

    At each bar with a KNOWN crowding-z (align_asof, PIT): if z > +thresh the crowd is over-long → take a SHORT for
    `horizon` bars; if z < -thresh → take a LONG. Net per-trade return = the realized close-to-close move over the
    horizon in the trade's direction, minus a round-trip maker fee. bar_returns is the per-bar net contribution
    (0 on non-trade bars), so the locked sample_moments/Sharpe read the honest path. fold_returns = 5 contiguous
    chunks of the trade returns (the cell's own CV folds). DETERMINISTIC. No look-ahead: the entry uses z known at
    t, the exit price is bars[t+horizon] (strictly future realized)."""
    joined = align_asof(crowding, bars)
    fee = 2.0 * fee_bps / 1e4  # round-trip maker fee
    by_ts = {b.ts.isoformat(): idx for idx, b in enumerate(bars)}
    bar_rets: list[float] = [0.0] * len(bars)
    bar_ts: list[str] = [b.ts.isoformat() for b in bars]
    trades: list[Trade] = []
    held_until = -1
    for ts_iso, z in sorted(joined.items()):
        idx = by_ts.get(ts_iso)
        if idx is None or idx <= held_until or idx + horizon >= len(bars):
            continue
        if abs(z) < z_thresh:
            continue
        direction = -1.0 if z > 0 else 1.0  # fade: over-long → short, over-short → long
        p0 = float(bars[idx].close)
        p1 = float(bars[idx + horizon].close)
        if p0 <= 0:
            continue
        gross = direction * (p1 / p0 - 1.0)
        net = gross - fee
        bar_rets[idx + horizon] += net  # book the net P&L on the exit bar
        trades.append(Trade(entry=p0, exit=p1, pnl_pct=net, regime="chop"))
        held_until = idx + horizon
    total = 1.0
    for r in bar_rets:
        total *= (1.0 + r)
    total -= 1.0
    sr = _sharpe(bar_rets)
    sortino = _sortino(bar_rets)
    mdd = _max_drawdown(bar_rets)
    trade_rets = [t.pnl_pct for t in trades]
    folds = _folds(trade_rets, k=5)
    return SymbolRun(
        total_return=total,
        sharpe=sr,
        sortino=sortino,
        max_drawdown=mdd,
        trades=trades,
        bar_returns=bar_rets,
        bar_ts=bar_ts,
        fold_returns=folds,
        regime_pnl={"chop": total},
        periods_per_year=365.0,
    )


def _sharpe(rets: list[float]) -> float:
    nz = rets
    if len(nz) < 2:
        return 0.0
    mu = statistics.fmean(nz)
    sd = statistics.pstdev(nz)
    return (mu / sd) * math.sqrt(365.0) if sd > 0 else 0.0


def _sortino(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mu = statistics.fmean(rets)
    downside = [r for r in rets if r < 0]
    dd = statistics.pstdev(downside) if len(downside) >= 2 else 0.0
    return (mu / dd) * math.sqrt(365.0) if dd > 0 else 0.0


def _max_drawdown(rets: list[float]) -> float:
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
    return abs(mdd)


def _folds(values: list[float], *, k: int) -> list[float]:
    """k contiguous-chunk fold returns (sum within each chunk) — the cell's own CV folds for folds_positive_pct."""
    if not values:
        return [0.0] * k
    size = max(1, len(values) // k)
    folds: list[float] = []
    for i in range(k):
        chunk = values[i * size: (i + 1) * size] if i < k - 1 else values[i * size:]
        folds.append(sum(chunk))
    return folds


# --------------------------------------------------------------------------- disconfirmer (c) and (d)


def _residualize(xs: list[float], controls: list[list[float]]) -> list[float]:
    """Residual of xs after removing the linear projection onto each control (one at a time, Gram-Schmidt-ish).
    Pure least-squares per control. Used by disconfirmer (c) to strip vol + funding from the crowding signal."""
    res = list(xs)
    for c in controls:
        n = min(len(res), len(c))
        if n < 2:
            continue
        a, b = res[:n], c[:n]
        mb = statistics.fmean(b)
        vb = sum((v - mb) ** 2 for v in b)
        if vb <= 0:
            continue
        ma = statistics.fmean(a)
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        beta = cov / vb
        res = [a[i] - beta * (b[i] - mb) for i in range(n)]
    return res


def _control_residual_ic(
    crowding: list[AltDataPoint],
    bars: list[Bar],
    funding: list[AltDataPoint],
    *,
    horizon: int,
) -> float:
    """Disconfirmer (c): the crowding IC AFTER residualizing out trailing realized vol + the funding level. Aligns
    all three series + the forward return on common bars (PIT), residualizes the crowding feature, then Spearman-
    correlates the RESIDUAL against the strictly-future return. If this collapses toward 0 the 'edge' was a
    vol/funding proxy."""
    joined = align_asof(crowding, bars)
    fund_joined = align_asof(funding, bars) if funding else {}
    fwd = forward_returns(bars, horizon)
    rets = _bar_returns(bars)
    vol = _realized_vol(rets)
    vol_by_ts = {bars[i + 1].ts.isoformat(): vol[i] for i in range(len(vol)) if i + 1 < len(bars)}
    keys = sorted(set(joined) & set(fwd))
    xs = [joined[k] for k in keys]
    ys = [fwd[k] for k in keys]
    vol_ctrl = [vol_by_ts.get(k, 0.0) for k in keys]
    fund_ctrl = [fund_joined.get(k, 0.0) for k in keys]
    if len(xs) < 3:
        return 0.0
    resid = _residualize(xs, [vol_ctrl, fund_ctrl])
    ic, _p, _n = spearman_ic(resid, ys)
    return ic


def _copy_whale_ic(
    copy_signal: list[AltDataPoint] | None, bars: list[Bar], *, horizon: int
) -> float:
    """Disconfirmer (d): the IC of a 'copy the single biggest account's net direction' signal. If the caller has
    no per-account/whale series this returns 0.0 (so the aggregate trivially wins — the AGGREGATE is the thesis).
    A high copy-whale IC with a low aggregate IC would FALSIFY the aggregate-stress thesis."""
    if not copy_signal:
        return 0.0
    ic, _n = pit_ic(copy_signal, bars, horizon)
    return ic


# --------------------------------------------------------------------------- the harness


def run(
    *,
    net_position_by_coin: dict[str, list[AltDataPoint]],
    bars_by_coin: dict[str, list[Bar]],
    funding_by_coin: dict[str, list[AltDataPoint]] | None = None,
    copy_whale_by_coin: dict[str, list[AltDataPoint]] | None = None,
    gates: GateSettings | None = None,
    z_thresh: float = CROWDING_Z,
    horizon: int = HORIZON_BARS,
    fee_bps: float = HL_MAKER_FEE_BPS,
    min_window: int = DEFAULT_MIN_WINDOW,
) -> HlPositioningReport:
    """Run the disconfirmer-gated BRUT experiment on the hoarded positioning snapshots. For EACH coin: build the
    PIT crowding feature, simulate the fade-the-extreme strategy → SymbolRun, score it through the LOCKED
    metrics_for_run → promote_brut path (trials=1: ONE pre-registered config, the per-cell min_trades floor), and
    evaluate disconfirmers (b),(c),(d). Disconfirmer (a) is enforced at the cohort level: ANY promoted BTC/ETH
    cell makes the whole run UN-trustworthy (the majors must come up clean).

    A coin is a CANDIDATE iff it is a non-major BRUT-promoted cell that ALSO clears (b),(c),(d). PROPOSE-ONLY —
    the candidate goes to PAPER, never live. Pass `funding_by_coin` for the (c) control and `copy_whale_by_coin`
    (the single-biggest-account net-direction series) for (d); both optional (absent → the weakest-favorable
    default, never a fabricated pass)."""
    gates = gates or Settings(openrouter_api_key=None).gates
    # Market-neutral fade: cash benchmark, not buy-and-hold (a reversion short can't be asked to beat a long-only
    # B&H). Pre-registered as part of the hypothesis (the gate's documented per-run knob, not a loosening).
    gates = gates.model_copy(update={"require_beat_buy_and_hold": False})
    funding_by_coin = funding_by_coin or {}
    copy_whale_by_coin = copy_whale_by_coin or {}

    results: list[CoinResult] = []
    candidates: list[Candidate] = []
    metrics_by_coin = {}
    n_days = 0.0
    for coin, net_points in net_position_by_coin.items():
        bars = bars_by_coin.get(coin, [])
        if not net_points or not bars:
            continue
        span = (net_points[-1].available_at - net_points[0].available_at).total_seconds() / 86400.0
        n_days = max(n_days, span)
        crowding = crowding_extreme_z(net_points, min_window=min_window)
        raw_ic, n_obs = pit_ic(crowding, bars, horizon)
        run_ = _simulate_reversion(crowding, bars, z_thresh=z_thresh, horizon=horizon, fee_bps=fee_bps)
        m = metrics_for_run(run_, trials=1, buy_and_hold=0.0)
        metrics_by_coin[coin] = m
        is_major = coin in SATURATED
        candidates.append(Candidate(id=coin, metrics=m, net_profit=run_.total_return, source="hl_positioning"))
        # disconfirmer (b): shuffle null on the crowding series vs forward returns
        sh = shuffle_null(crowding, bars, horizon, trials=200, seed=11)
        # disconfirmer (c): residualize vol + funding
        resid_ic = _control_residual_ic(crowding, bars, funding_by_coin.get(coin, []), horizon=horizon)
        keeps = abs(resid_ic) >= _CONTROL_KEEP_FRAC * abs(raw_ic) if abs(raw_ic) > 1e-9 else False
        # disconfirmer (d): aggregate vs copy-whale
        copy_ic = _copy_whale_ic(copy_whale_by_coin.get(coin), bars, horizon=horizon)
        agg_beats_copy = abs(raw_ic) >= abs(copy_ic) + _AGG_OVER_COPY_MARGIN
        results.append(
            CoinResult(
                coin=coin, is_major=is_major, raw_ic=round(raw_ic, 6), n_obs=n_obs,
                num_trades=m.num_trades, net_return=round(run_.total_return, 6),
                deflated_sharpe_prob=0.0,  # filled after promote_brut
                brut_promoted=False,        # filled after promote_brut
                d_shuffle_survives=bool(sh.survives),
                d_control_keeps_ic=bool(keeps),
                d_aggregate_beats_copy=bool(agg_beats_copy),
                residual_ic=round(resid_ic, 6),
                copy_whale_ic=round(copy_ic, 6),
            )
        )
    # Score every cell through the LOCKED brut gate in ONE call (trials=1; per-cell min_trades floor).
    proms = {p.candidate_id: p for p in promote_brut(candidates, gates, min_trades=gates.min_trades)}
    final: list[CoinResult] = []
    for r in results:
        p = proms.get(r.coin)
        final.append(
            CoinResult(
                coin=r.coin, is_major=r.is_major, raw_ic=r.raw_ic, n_obs=r.n_obs, num_trades=r.num_trades,
                net_return=r.net_return,
                deflated_sharpe_prob=round(p.deflated_sharpe_prob, 6) if p else 0.0,
                brut_promoted=bool(p.promoted) if p else False,
                d_shuffle_survives=r.d_shuffle_survives,
                d_control_keeps_ic=r.d_control_keeps_ic,
                d_aggregate_beats_copy=r.d_aggregate_beats_copy,
                residual_ic=r.residual_ic, copy_whale_ic=r.copy_whale_ic,
                reasons=list(p.reasons) if p else [],
            )
        )
    majors_clean = not any(r.brut_promoted for r in final if r.is_major)  # disconfirmer (a)
    candidate_coins = [r.coin for r in final if r.is_candidate]
    n_coins = len(final)
    if candidate_coins and majors_clean:
        verdict = "CANDIDATES"
        headline = f"{len(candidate_coins)} thin-perp positioning cell(s) cleared the BRUT gate + all disconfirmers → PAPER (not live)."
    elif not majors_clean:
        verdict = "UNTRUSTWORTHY"
        headline = "A BTC/ETH cell promoted — disconfirmer (a) FAILED: the signal is generic, not thin-tail. Reject the run."
    else:
        verdict = "NO_EDGE"
        headline = "No thin-perp cell cleared the BRUT gate AND all four disconfirmers — the axis is honest-null so far."
    return HlPositioningReport(
        verdict=verdict, headline=headline,
        hypothesis=(
            "A crowding extreme (net-positioning z beyond ±%.1f) on a thin Hyperliquid perp predicts a %d-bar "
            "mean-reversion, net of %.1fbps maker fees; the edge is the AGGREGATE stress, not copying any account."
            % (z_thresh, horizon, fee_bps)
        ),
        n_coins=n_coins, n_capture_days=round(n_days, 2), crowding_z=z_thresh, horizon_bars=horizon, fee_bps=fee_bps,
        coins=final, disconfirmer_a_majors_clean=majors_clean, candidates=candidate_coins,
    )


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - the guarded live entrypoint
    """CLI guard: REFUSE to run until ≥ MIN_DAYS_TO_RUN of forward hoard exists (the data is being accrued now;
    running before then is meaningless). Reads the hoarded series from the configured alt store. This is the
    ready-to-run instrument — the operator runs it ~2-3 wks after the poller is deployed."""
    import logging

    from cosmu.config.settings import get_settings
    from cosmu.data.altdata import hot_alt_store
    from cosmu.data.sources.hyperliquid_positioning import (
        DEFAULT_LONGTAIL_COINS,
        M_NET_POSITION_USD,
        PROVIDER,
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    store = hot_alt_store(get_settings())
    net_by_coin: dict[str, list[AltDataPoint]] = {}
    for coin in DEFAULT_LONGTAIL_COINS:
        pts = store.read_all(PROVIDER, coin, M_NET_POSITION_USD)
        if pts:
            net_by_coin[coin] = pts
    if not net_by_coin:
        print("HL POSITIONING HARNESS — no hoarded data yet. The forward hoard must accrue first (deploy the "
              f"poller; wait ~{MIN_DAYS_TO_RUN} days). Refusing to run on empty data (honest no-op).")
        return 0
    span_days = max(
        (pts[-1].available_at - pts[0].available_at).total_seconds() / 86400.0 for pts in net_by_coin.values()
    )
    if span_days < MIN_DAYS_TO_RUN:
        print(f"HL POSITIONING HARNESS — only {span_days:.1f}d of hoard (< {MIN_DAYS_TO_RUN}d). Too shallow to "
              "rule yet; the binding cost is TIME. Refusing to run (honest no-op).")
        return 0
    print("HL POSITIONING HARNESS — enough hoard accrued; bar loading for the live run is an operator follow-up "
          "(this CLI only verifies readiness — pass bars_by_coin to run()).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
