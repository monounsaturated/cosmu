# intent: the HONEST re-run harness — judge the LOW-TURNOVER btc-social risk-on OVERLAY and the orphaned
# Polymarket positioning-risk-flip spec as ONE promote_cohort BH-FDR family (q=0.10) on REAL Binance daily bars +
# REAL social/Polymarket history + PIT fees, with 3 PRE-REGISTERED DISCONFIRMERS in the SAME family. Unlike the
# high-turnover daily trigger that already FAILED (deflated Sharpe 0.596), the overlay TILTS a slow base book's
# exposure via a per-bar market-wide size_multiplier = base*(lo+(hi-lo)*regime_t) — it adds/removes NO trades.
#
# The PASS/FAIL verdict comes ONLY from promote_cohort's BH-FDR (NOT gate.evaluate_cross_asset_ablation, which
# applies ZERO BH-FDR and hardcodes trials_counted=5 — the leaky path). Every grid variant AND every W/dwell
# regime free param is recorded as a trial so deflation/FDR see the true inflated count. A fresh tempfile store
# isolates the trial ledger so global feeds can't pollute the deflation. Deterministic for a fixed cache.
#
# Members (DISTINCT candidates in ONE family):
#   btc-social-riskon-overlay            — the slow base book TILTED by the slow btc_social_regime
#   polymarket-positioning-risk-flip     — the orphaned inbox spec (pm_implied_prob / pm_prob_velocity)
# Pre-registered disconfirmers (in-family, their W/dwell free params counted as trials):
#   disc-btc-price-regime-tilt           — the SAME book tilted by an equal-turnover BTC-PRICE regime
#   disc-flat-exposure-baseline          — the SAME book, flat exposure (no tilt)
#   disc-time-shuffle-placebo            — the SAME book tilted by a within-regime time-shuffled regime
# Falsified iff the btc-social overlay does NOT beat (deflated Sharpe) the flat baseline AND the btc-price tilt,
# or if the time-shuffle placebo reproduces it.

from __future__ import annotations

import os
import random
import statistics
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataProvider
from cosmu.data.backtest import (
    align_asof,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar, default_crypto_reference
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store
from cosmu.lab.finder import build_grid
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import cscv_pbo, score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.research.carry_ablation import _real_market, _resolve_params
from cosmu.research.social_norm import _accel, slow_social_regime
from cosmu.research.social_signal_cohort import _clip_to_social_window
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec

# The base-book spec the overlay tilts, and the orphaned Polymarket spec wired in as a distinct candidate.
_BASE_BOOK = "btc-social-riskon-overlay.json"
_POLYMARKET = "polymarket-positioning-risk-flip.json"
# Polymarket features the orphaned spec reads (joined market-wide as a PIT alt series).
_PM_METRICS = ("pm_implied_prob", "pm_prob_velocity")

# The regime (W, min-dwell) free params swept — counted as TRIALS in build_grid (each combo is a distinct
# size-series the base book is screened under, recorded as a trial so deflation/FDR see the true count). W in
# the 20-40d band the overlay is specified at; dwell large enough for a handful of flips/yr (low-turnover).
_REGIME_GRID = ((20, 20), (30, 20), (30, 30), (40, 30), (40, 45))
# The exposure tilt: size_multiplier = LO + (HI-LO)*regime_t. Risk-off floors exposure at LO, risk-on at HI.
_TILT_LO = 0.3
_TILT_HI = 1.0
_FDR_Q = 0.10


@dataclass
class MemberReport:
    name: str
    net_return: float
    gross_return: float
    cost_ratio: float
    deflated_sharpe_prob: float
    cscv_pbo: float
    beat_buy_and_hold: bool
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    survived_fdr: bool = False
    promoted: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class RerunReport:
    verdict: str
    headline: str
    data_source: str
    window: str
    fdr_q: float
    regime_flips_per_yr: float
    members: list[MemberReport] = field(default_factory=list)
    disconfirmers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def load_spec(fname: str) -> StrategySpec:
    import json
    from pathlib import Path

    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    return StrategySpec.model_validate(json.loads((inbox / fname).read_text()))


# --------------------------------------------------------------------------- regime → per-bar size series


def _btc_price_regime(btc_bars: list[Bar], *, ewma_days: int, min_dwell_days: int) -> list[AltDataPoint]:
    """The EQUAL-TURNOVER BTC-PRICE disconfirmer regime: the SAME slow_social_regime pipeline (EWMA → within-
    sample z → hysteresis + min-dwell) applied to BTC daily LOG-RETURN instead of social_volume_accel. Same W
    and dwell as the social regime, so its flip count (turnover) matches by construction — the only difference
    is what drives it (price momentum vs social attention). available_at = the bar close (price is known then)."""
    import math

    closes = [float(b.close) for b in btc_bars]
    logret: list[AltDataPoint] = []
    for i in range(1, len(btc_bars)):
        if closes[i - 1] > 0 and closes[i] > 0:
            logret.append(AltDataPoint(ts=btc_bars[i].ts, available_at=btc_bars[i].ts,
                                       value=math.log(closes[i] / closes[i - 1])))
    return slow_social_regime(logret, ewma_days=ewma_days, min_dwell_days=min_dwell_days)


def _shuffle_regime_preserving_dwell(regime: list[AltDataPoint], *, seed: int) -> list[AltDataPoint]:
    """Within-regime time-shuffle PLACEBO: keep the EXACT dwell-run-length distribution (the same on-runs and
    off-runs, so the flip count / turnover is IDENTICAL) but randomly re-order the runs along the timeline. The
    on-runs and off-runs are shuffled SEPARATELY and re-interleaved in the original on/off alternation, so two
    same-value runs never merge (which would have lowered turnover) — the placebo's on-fraction and flip count
    match the real regime exactly; only the TIMING of the risk-on stretches is scrambled. If the slow regime
    carried no real timing information, this placebo reproduces the overlay's edge — so a placebo that MATCHES
    the signal falsifies it. PIT shape preserved (values reattached to the original ts/availability order)."""
    if not regime:
        return regime
    vals = [p.value for p in regime]
    runs: list[tuple[float, int]] = []  # (value, run_length), in original alternation order
    cur, n = vals[0], 1
    for v in vals[1:]:
        if v == cur:
            n += 1
        else:
            runs.append((cur, n))
            cur, n = v, 1
    runs.append((cur, n))
    rng = random.Random(seed)
    # Shuffle run-LENGTHS within each value class, then re-lay them in the ORIGINAL value-alternation pattern,
    # so the sequence of on/off transitions (the turnover) is byte-identical and only the dwell lengths move.
    lengths_by_val: dict[float, list[int]] = {}
    for v, length in runs:
        lengths_by_val.setdefault(v, []).append(length)
    for v in lengths_by_val:
        rng.shuffle(lengths_by_val[v])
    idx_by_val: dict[float, int] = dict.fromkeys(lengths_by_val, 0)
    shuffled: list[float] = []
    for v, _orig_len in runs:
        length = lengths_by_val[v][idx_by_val[v]]
        idx_by_val[v] += 1
        shuffled.extend([v] * length)
    # The total length is preserved (same multiset of lengths per value), so values reattach 1:1 to the timeline.
    return [AltDataPoint(ts=p.ts, available_at=p.available_at, value=shuffled[i]) for i, p in enumerate(regime)]


def _size_series_from_regime(regime: list[AltDataPoint], bars: list[Bar]) -> dict[str, float]:
    """Map a {0,1} regime series to a per-bar size_multiplier keyed by bar.ts.isoformat(), via the PIT as-of
    join (each bar reads the latest regime value available by it): size = LO + (HI-LO)*regime_t. Bars before the
    first regime point read LO (risk-off default — we would not yet have a risk-on read)."""
    joined = align_asof(regime, bars)
    out: dict[str, float] = {}
    for b in bars:
        r = joined.get(b.ts.isoformat())
        r = 0.0 if r is None else max(0.0, min(1.0, r))
        out[b.ts.isoformat()] = _TILT_LO + (_TILT_HI - _TILT_LO) * r
    return out


def _flips_per_year(regime: list[AltDataPoint]) -> float:
    if len(regime) < 2:
        return 0.0
    flips = sum(1 for i in range(1, len(regime)) if regime[i].value != regime[i - 1].value)
    days = (regime[-1].ts - regime[0].ts).days or 1
    return flips / (days / 365.25)


# --------------------------------------------------------------------------- per-member screening


def _screen_book_under_tilt(
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
    label: str,
    size_series: dict[str, float] | None,
) -> tuple[dict, object, list[list[float]]]:
    """Screen the base book's param GRID under a FIXED per-bar size tilt (size_series), recording every variant
    as a trial (so deflation/FDR see the true count), returning the gate-best variant's params, detailed result,
    and the per-variant validation-return streams (for a real CSCV-PBO). Mirrors social_signal_cohort._spec_best
    but threads the market-wide size_series instead of a scalar multiplier."""
    grid = build_grid(spec, max_variants=64)
    best_params = _resolve_params(spec)
    best_result = None
    best_key = (-1, -1.0)
    variant_streams: list[list[float]] = []
    for variant in grid:
        res = run_strategy_backtest_detailed(
            spec, variant.params, market, fee_bps=fee_bps, alt_by_symbol=alt, size_series=size_series
        )
        m = res.metrics
        record_trial(store, float(m.sharpe_per_obs), source="rerun", label=f"{label}:{variant.config_tag}")
        v = score(m, gates, trials=trial_stats(store))
        if res.val_returns:
            variant_streams.append(res.val_returns)
        key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
        if key > best_key or best_result is None:
            best_key, best_params, best_result = key, variant.params, res
    if best_result is None:
        best_result = run_strategy_backtest_detailed(
            spec, best_params, market, fee_bps=fee_bps, alt_by_symbol=alt, size_series=size_series
        )
    return best_params, best_result, variant_streams


def _make_member(
    sid: str,
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
    size_series: dict[str, float] | None,
) -> tuple[Candidate, MemberReport]:
    """Screen a member (base book under a tilt, or a standalone spec) and assemble its Candidate + report. The
    gross arm reruns the gate-best params under the SAME tilt with ZERO transaction cost → cost_ratio = net/gross."""
    params, res, streams = _screen_book_under_tilt(
        spec, market, fee_bps=fee_bps, alt=alt, store=store, gates=gates, label=sid, size_series=size_series
    )
    m = res.metrics
    gross = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"), impact_bps=Decimal("0"),
        alt_by_symbol=alt, size_series=size_series,
    ).metrics
    net_return = float(m.oos_return)
    gross_return = float(gross.oos_return)
    cost_ratio = float(m.cost_ratio)
    if cost_ratio == 0.0 and gross_return:
        cost_ratio = net_return / gross_return
    usable = [s for s in streams if s]
    pbo = cscv_pbo(usable) if len(usable) >= 2 else float(m.pbo)
    var = statistics.pvariance(res.val_returns) if len(res.val_returns) > 1 else 1.0
    dsr = float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob)
    cand = Candidate(id=sid, metrics=m, net_profit=net_return, source="rerun", label=sid, return_variance=var or 1.0)
    rep = MemberReport(
        name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
        cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(dsr, 6), cscv_pbo=round(pbo, 6),
        beat_buy_and_hold=net_return > float(m.buy_and_hold_return),
        regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0),
        num_trades=m.num_trades, max_drawdown=round(float(m.max_drawdown), 6),
    )
    return cand, rep


def _best_over_regime_grid(
    sid: str,
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    btc_bars: list[Bar],
    *,
    kind: str,  # "social" | "price" | "placebo"
    base_accel: list[AltDataPoint],
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
) -> tuple[Candidate, MemberReport]:
    """Screen the base book across the (W, dwell) REGIME GRID — each combo is a distinct size-series tilt the
    book is screened under, every variant recorded as a trial so the regime free params inflate the FDR count.
    Returns the gate-best (Candidate, report) across all (W,dwell)×param-grid variants for this disconfirmer arm."""
    best_cand: Candidate | None = None
    best_rep: MemberReport | None = None
    best_dsr = -1.0
    for w, dwell in _REGIME_GRID:
        if kind == "social":
            regime = slow_social_regime(base_accel, ewma_days=w, min_dwell_days=dwell)
        elif kind == "price":
            regime = _btc_price_regime(btc_bars, ewma_days=w, min_dwell_days=dwell)
        elif kind == "placebo":
            social = slow_social_regime(base_accel, ewma_days=w, min_dwell_days=dwell)
            regime = _shuffle_regime_preserving_dwell(social, seed=1000 + w * 100 + dwell)
        else:
            raise ValueError(kind)
        size_series = _size_series_from_regime(regime, btc_bars) if regime else None
        cand, rep = _make_member(
            f"{sid}", spec, market, fee_bps=fee_bps, alt=alt, store=store, gates=gates, size_series=size_series,
        )
        if rep.deflated_sharpe_prob > best_dsr:
            best_dsr, best_cand, best_rep = rep.deflated_sharpe_prob, cand, rep
    assert best_cand is not None and best_rep is not None
    return best_cand, best_rep


# --------------------------------------------------------------------------- the cohort


def _pm_alt(market: dict[str, list[Bar]], provider: AltDataProvider) -> dict[str, dict[str, dict[str, float]]]:
    """Join the market-wide Polymarket series (pm_implied_prob / pm_prob_velocity) onto every symbol's bars,
    point-in-time (align_asof on available_at). Market-wide: the SAME odds series is read by every symbol."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        feats: dict[str, dict[str, float]] = {}
        for metric in _PM_METRICS:
            pts = provider.fetch_series(symbol, metric, limit=len(bars) + 2400)
            joined = align_asof(pts, bars)
            if joined:
                feats[metric] = joined
        if feats:
            out[symbol] = feats
    return out


def run_rerun_cohort(
    market: dict[str, list[Bar]],
    provider: AltDataProvider,
    store: Store,
    *,
    data_source: str = "live-db",
    fdr_q: float = _FDR_Q,
) -> RerunReport:
    gates = store.settings.gates
    fee_bps = default_catalog().venue("binance").taker_fee_bps

    win_lo = win_hi = None
    for bars in market.values():
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"

    btc_bars = market.get("BTCUSDT")
    notes: list[str] = []
    if not btc_bars:
        return RerunReport("INSUFFICIENT-DATA", "no BTCUSDT bars in cache — overlay needs BTC", data_source,
                           window, fdr_q, 0.0, notes=["BTCUSDT absent — cannot build the btc-social regime"])

    btc_vol = provider.fetch_series("BTCUSDT", "social_volume", limit=len(btc_bars) + 2400)
    base_accel = _accel(btc_vol)
    if not base_accel:
        return RerunReport("INSUFFICIENT-DATA", "no BTC social history — overlay regime undefined", data_source,
                           window, fdr_q, 0.0, notes=["BTC social_volume empty — run the LunarCrush backfill"])
    default_social_regime = slow_social_regime(base_accel)
    flips_per_yr = _flips_per_year(align_asof_regime(default_social_regime, btc_bars))

    base_spec = load_spec(_BASE_BOOK)
    candidates: list[Candidate] = []
    reports: list[MemberReport] = []

    # 1) the real candidate — base book tilted by the slow btc-social regime (best across the W/dwell grid).
    c_social, r_social = _best_over_regime_grid(
        "btc-social-riskon-overlay", base_spec, market, btc_bars, kind="social", base_accel=base_accel,
        fee_bps=fee_bps, alt={}, store=store, gates=gates,
    )
    candidates.append(c_social)
    reports.append(r_social)

    # 2) DISCONFIRMER A1 — same book, equal-turnover BTC-PRICE regime tilt.
    c_price, r_price = _best_over_regime_grid(
        "disc-btc-price-regime-tilt", base_spec, market, btc_bars, kind="price", base_accel=base_accel,
        fee_bps=fee_bps, alt={}, store=store, gates=gates,
    )
    candidates.append(c_price)
    reports.append(r_price)

    # 3) DISCONFIRMER A2 — same book, FLAT exposure (no tilt at all; size_series=None → scalar 1.0).
    c_flat, r_flat = _make_member(
        "disc-flat-exposure-baseline", base_spec, market, fee_bps=fee_bps, alt={}, store=store, gates=gates,
        size_series=None,
    )
    candidates.append(c_flat)
    reports.append(r_flat)

    # 4) DISCONFIRMER B — within-regime time-shuffle placebo (same dwell distribution, shuffled order).
    c_plac, r_plac = _best_over_regime_grid(
        "disc-time-shuffle-placebo", base_spec, market, btc_bars, kind="placebo", base_accel=base_accel,
        fee_bps=fee_bps, alt={}, store=store, gates=gates,
    )
    candidates.append(c_plac)
    reports.append(r_plac)

    # 5) the orphaned Polymarket spec — its own grid on the pm alt-join (a DISTINCT candidate in the SAME family).
    pm_alt = _pm_alt(market, provider)
    pm_points = sum(len(provider.fetch_series("MARKET", m, limit=4000)) for m in _PM_METRICS)
    if pm_alt and pm_points:
        pm_spec = load_spec(_POLYMARKET)
        c_pm, r_pm = _make_member(
            "polymarket-positioning-risk-flip", pm_spec, market, fee_bps=fee_bps, alt=pm_alt, store=store,
            gates=gates, size_series=None,
        )
        candidates.append(c_pm)
        reports.append(r_pm)
    else:
        notes.append("Polymarket series empty/too thin in store — family run btc-social-overlay-only.")

    # COHORT BH-FDR across the whole family — register=False + the shared trial_stats so deflation/FDR see the
    # true (grid + regime-free-param inflated) count. THIS is the verdict (never gate.evaluate_cross_asset_ablation).
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store))
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.reasons = p.reasons
            # Use the FINAL deflated Sharpe from promote_cohort — deflated against the FULL inflated trial
            # ledger (every member × W/dwell × grid variant). The mid-run score() value used while building
            # the member saw a SMALLER trial count, so it overstated significance; this is the honest number
            # the family verdict is actually computed on.
            r.deflated_sharpe_prob = round(p.deflated_sharpe_prob, 6)

    # Disconfirmer verdicts (read off deflated Sharpe — the per-candidate significance the FDR ranks).
    social_dsr = r_social.deflated_sharpe_prob
    disc: dict[str, str] = {}
    beats_flat = social_dsr > r_flat.deflated_sharpe_prob
    beats_price = social_dsr > r_price.deflated_sharpe_prob
    placebo_reproduces = r_plac.deflated_sharpe_prob >= social_dsr
    disc["beat_flat_baseline"] = (
        f"{'PASS' if beats_flat else 'FAIL'} (social dsr {social_dsr:.3f} vs flat {r_flat.deflated_sharpe_prob:.3f})"
    )
    disc["beat_btc_price_regime"] = (
        f"{'PASS' if beats_price else 'FAIL'} (social dsr {social_dsr:.3f} vs price {r_price.deflated_sharpe_prob:.3f})"
    )
    disc["time_shuffle_placebo"] = (
        f"{'PASS' if not placebo_reproduces else 'FAIL-reproduces'} "
        f"(social dsr {social_dsr:.3f} vs placebo {r_plac.deflated_sharpe_prob:.3f})"
    )
    falsified = (not beats_flat) or (not beats_price) or placebo_reproduces

    promoted = [r for r in reports if r.promoted and not r.name.startswith("disc-")]
    if promoted and not falsified:
        verdict = "PASS"
        headline = (f"{len(promoted)} member(s) survived the cohort gate + BH-FDR (q={fdr_q}) AND passed all "
                    f"disconfirmers: " + ", ".join(r.name for r in promoted))
    elif promoted and falsified:
        verdict = "FAIL-DISCONFIRMED"
        headline = (f"{len(promoted)} member(s) survived BH-FDR but a pre-registered disconfirmer FAILED — "
                    f"the edge is not the claimed one (likely look-ahead/regime artifact, not btc-social timing)")
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        headline = (f"no member survived the cohort gate + BH-FDR (q={fdr_q}); best DSR "
                    f"{best.deflated_sharpe_prob:.3f} ({best.name})" if best else "no candidates")

    return RerunReport(verdict, headline, data_source, window, fdr_q, round(flips_per_yr, 2),
                       members=reports, disconfirmers=disc, notes=notes)


def align_asof_regime(regime: list[AltDataPoint], bars: list[Bar]) -> list[AltDataPoint]:
    """Restrict a regime series to the trading-bar window (for the flips/yr turnover report) — the regime points
    whose ts falls inside [first bar, last bar]. Turnover is reported on what the book actually traded over."""
    if not regime or not bars:
        return regime
    lo, hi = bars[0].ts, bars[-1].ts
    return [p for p in regime if lo <= p.ts <= hi]


def _main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    tmp = tempfile.mkdtemp(prefix="cosmu-rerun-")
    # Fresh tempfile trial-ledger store so global feeds can't pollute the deflation (mirror social_nonobvious).
    store = Store(Settings(database_url=f"sqlite:///{tmp}/rerun.sqlite3", openrouter_api_key=None))
    # The DATA store (social + Polymarket) is the production Postgres alt_data table; read-only here.
    if db_url:
        data_store = Store(Settings(database_url=db_url, openrouter_api_key=None))
        provider: AltDataProvider = StoreBackedAltProvider(PgAltDataStore(data_store))
    else:
        from cosmu.data.providers.store import AltDataStore
        provider = StoreBackedAltProvider(AltDataStore())

    market = _clip_to_social_window(_real_market(default_crypto_reference()), provider)
    report = run_rerun_cohort(market, provider, store)

    print(f"HONEST RE-RUN COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  btc-social regime flips/yr={report.regime_flips_per_yr}")
    print(f"  cohort BH-FDR q={report.fdr_q}")
    for m in report.members:
        flag = "PROMOTED" if m.promoted else ("fdr-only" if m.survived_fdr else "stop")
        print(f"  [{flag:>8}] {m.name:<34} net={m.net_return:+.4f} gross={m.gross_return:+.4f} "
              f"cost_ratio={m.cost_ratio:.3f} dsr={m.deflated_sharpe_prob:.3f} pbo={m.cscv_pbo:.3f} "
              f"reg+={m.regimes_positive} trades={m.num_trades} maxDD={m.max_drawdown:.3f} "
              f"beatBH={'Y' if m.beat_buy_and_hold else 'N'} fdr={'Y' if m.survived_fdr else 'N'}")
        if m.reasons:
            print(f"             reasons: {', '.join(m.reasons)}")
    print("  DISCONFIRMERS:")
    for k, v in report.disconfirmers.items():
        print(f"    {k}: {v}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
