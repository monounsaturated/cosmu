# intent: the HONEST gate harness for the FRESH scan hypothesis "social-dominance share leadership" — judge the
# social_dom_z long book as ONE promote_cohort BH-FDR family (q=0.10) on REAL Binance daily bars + REAL LunarCrush
# social_dominance history + PIT fees, with 3 PRE-REGISTERED in-family DISCONFIRMERS. The verdict comes ONLY from
# promote_cohort's BH-FDR (NEVER gate.evaluate_cross_asset_ablation, the no-FDR/trials=5 leaky path). Every grid
# variant of every member is recorded as a trial so deflation/FDR see the true inflated count. A fresh tempfile
# store isolates the trial ledger. Deterministic for a fixed bar cache + DB snapshot.
#
# Members (ONE family):
#   social-dominance-share-leadership-long  — long when within-asset trailing-z of social_dominance is HIGH and
#                                              price momentum confirms; ~1-week hold.
# Pre-registered disconfirmers (in-family, their grids counted as trials):
#   disc-momentum-only-control   — SUBSUMPTION: the same book with social_dom_z removed (price-momentum only).
#                                  If it matches/beats the candidate, social_dom_z adds no orthogonal info.
#   disc-absolute-volume-accel   — RELATIVE-vs-ABSOLUTE: the same book with social_dom_z swapped for the absolute
#                                  social_volume_accel (which the scan found DEAD). If it matches, it's the level.
#   disc-dominance-time-shuffle  — PLACEBO: same book with a within-asset time-shuffled social_dom_z (marginal
#                                  distribution preserved, timing scrambled). If it reproduces, timing is noise.
# Falsified iff the candidate does NOT beat (deflated Sharpe) the momentum-only control AND the absolute control,
# or if the time-shuffle placebo reproduces it.

from __future__ import annotations

import glob
import math
import os
import os.path as _p
import random
import statistics
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataProvider
from cosmu.data.backtest import align_asof, run_strategy_backtest_detailed
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store
from cosmu.lab.finder import build_grid
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import cscv_pbo, score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.carry_ablation import _resolve_params
from cosmu.research.rerun_cohort import load_spec

_CANDIDATE = "social-dominance-share-leadership-long.json"
_DISC_MOM = "disc-momentum-only-control.json"
_Z_WIN = 30
_Z_MIN = 10
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
class CohortReport:
    verdict: str
    headline: str
    data_source: str
    window: str
    fdr_q: float
    members: list[MemberReport] = field(default_factory=list)
    disconfirmers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _coin(symbol: str) -> str:
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()


def _universe() -> list[str]:
    return sorted({_p.basename(f).replace("_1d.json", "") for f in glob.glob(".cosmu/market_data/binance/*_1d.json")})


# --------------------------------------------------------------------------- PIT signal transforms


def _trailing_z(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """Within-asset TRAILING z of a level series — uses only points up to & including each point (no look-ahead)."""
    out: list[AltDataPoint] = []
    vals: list[float] = []
    for p in points:
        vals.append(p.value)
        if len(vals) >= _Z_MIN:
            window = vals[-_Z_WIN:]
            mu = statistics.fmean(window)
            sd = statistics.pstdev(window)
            if sd > 0:
                out.append(AltDataPoint(ts=p.ts, available_at=p.available_at, value=(p.value - mu) / sd))
    return out


def _accel(points: list[AltDataPoint]) -> list[AltDataPoint]:
    out: list[AltDataPoint] = []
    for i in range(1, len(points)):
        a, b = points[i - 1].value, points[i].value
        if a > 0 and b > 0:
            out.append(AltDataPoint(ts=points[i].ts, available_at=points[i].available_at, value=math.log(b / a)))
    return out


def _time_shuffle(points: list[AltDataPoint], *, seed: int) -> list[AltDataPoint]:
    """PLACEBO: keep the EXACT marginal distribution of the z-series (same multiset of values) but randomly
    permute which timestamp carries which value, destroying the signal's TIMING. PIT shape preserved (the
    shuffled values reattach to the original ts/available_at order). If social_dom_z carried no real timing
    information, this placebo reproduces the edge — a placebo that matches the signal falsifies it."""
    if not points:
        return points
    vals = [p.value for p in points]
    rng = random.Random(seed)
    rng.shuffle(vals)
    return [AltDataPoint(ts=p.ts, available_at=p.available_at, value=vals[i]) for i, p in enumerate(points)]


def _join(transformed: dict[str, list[AltDataPoint]], market: dict[str, list[Bar]], feat: str) -> dict[str, dict[str, dict[str, float]]]:
    """Build alt_by_symbol = {symbol: {feat: {bar.ts.isoformat(): value}}} via the PIT as-of join."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for s, pts in transformed.items():
        j = align_asof(pts, market[s])
        if j:
            out[s] = {feat: j}
    return out


# --------------------------------------------------------------------------- per-member screening


def _screen(
    spec,  # noqa: ANN001
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
    label: str,
):
    """build_grid → screen every variant on REAL bars/social/fees, RECORD each as a trial, return gate-best
    params, its detailed result, and the per-variant validation streams (for a real CSCV-PBO)."""
    grid = build_grid(spec, max_variants=64)
    best_params = _resolve_params(spec)
    best_result = None
    best_key = (-1, -1.0)
    most_trades = -1
    most_trading = None
    variant_streams: list[list[float]] = []
    for variant in grid:
        res = run_strategy_backtest_detailed(spec, variant.params, market, fee_bps=fee_bps, alt_by_symbol=alt)
        m = res.metrics
        record_trial(store, float(m.sharpe_per_obs), source="social_dom", label=f"{label}:{variant.config_tag}")
        v = score(m, gates, trials=trial_stats(store))
        if res.val_returns:
            variant_streams.append(res.val_returns)
        key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
        if key > best_key or best_result is None or (key == best_key and m.num_trades > best_result.metrics.num_trades):
            best_key, best_params, best_result = key, variant.params, res
        if m.num_trades > most_trades:
            most_trades, most_trading = m.num_trades, (variant.params, res)
    if best_result is not None and best_result.metrics.num_trades == 0 and most_trades > 0 and most_trading:
        best_params, best_result = most_trading
    if best_result is None:
        best_result = run_strategy_backtest_detailed(spec, best_params, market, fee_bps=fee_bps, alt_by_symbol=alt)
    return best_params, best_result, variant_streams


def _make_member(
    sid: str,
    spec,  # noqa: ANN001
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
) -> tuple[Candidate, MemberReport]:
    params, res, streams = _screen(spec, market, fee_bps=fee_bps, alt=alt, store=store, gates=gates, label=sid)
    m = res.metrics
    gross = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"), impact_bps=Decimal("0"),
        alt_by_symbol=alt,
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
    cand = Candidate(id=sid, metrics=m, net_profit=net_return, source="social_dom", label=sid, return_variance=var or 1.0)
    rep = MemberReport(
        name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
        cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(dsr, 6), cscv_pbo=round(pbo, 6),
        beat_buy_and_hold=net_return > float(m.buy_and_hold_return),
        regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0),
        num_trades=m.num_trades, max_drawdown=round(float(m.max_drawdown), 6),
    )
    return cand, rep


# --------------------------------------------------------------------------- the cohort


def run_cohort(
    market: dict[str, list[Bar]],
    provider: AltDataProvider,
    store: Store,
    *,
    data_source: str = "live-db",
    fdr_q: float = _FDR_Q,
    persist: bool = False,
) -> CohortReport:
    """`persist=True` records the cohort verdict to durable experiment-memory (gate_verdicts) via the real
    configured store — _main sets it on real runs; tests leave it False so they never touch the durable store."""
    gates = store.settings.gates
    fee_bps = default_catalog_taker()

    win_lo = win_hi = None
    for bars in market.values():
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"
    notes: list[str] = []

    # Raw PIT social series per symbol (stored under the bare COIN symbol).
    raw_dom: dict[str, list[AltDataPoint]] = {}
    raw_vol: dict[str, list[AltDataPoint]] = {}
    for s in market:
        coin = _coin(s)
        d = provider.fetch_series(coin, "social_dominance", limit=len(market[s]) + 2400)
        v = provider.fetch_series(coin, "social_volume", limit=len(market[s]) + 2400)
        if d:
            raw_dom[s] = d
        if v:
            raw_vol[s] = v
    if not raw_dom:
        return CohortReport("INSUFFICIENT-DATA", "no social_dominance history in store", data_source, window,
                            fdr_q, notes=["social_dominance empty — run the LunarCrush backfill"])

    # The candidate feature + the three disconfirmer features, each PIT-joined under the SPEC's feature names.
    dom_z = {s: _trailing_z(p) for s, p in raw_dom.items()}
    alt_candidate = _join(dom_z, market, "social_dom_z")
    alt_placebo = _join({s: _time_shuffle(_trailing_z(p), seed=4242 + i) for i, (s, p) in enumerate(raw_dom.items())}, market, "social_dom_z")
    alt_absolute = _join({s: _accel(p) for s, p in raw_vol.items()}, market, "social_dom_z")  # absolute accel masquerading under the candidate's feature name → tests if it's the level not the share

    cand_spec = load_spec(_CANDIDATE)
    mom_spec = load_spec(_DISC_MOM)

    candidates: list[Candidate] = []
    reports: list[MemberReport] = []

    # 1) the real candidate — social_dom_z long book.
    c0, r0 = _make_member("social-dominance-share-leadership-long", cand_spec, market, fee_bps=fee_bps, alt=alt_candidate, store=store, gates=gates)
    candidates.append(c0)
    reports.append(r0)

    # 2) DISCONFIRMER — momentum-only control (no social signal at all; alt empty so its ret_Nd legs are native).
    c1, r1 = _make_member("disc-momentum-only-control", mom_spec, market, fee_bps=fee_bps, alt={}, store=store, gates=gates)
    candidates.append(c1)
    reports.append(r1)

    # 3) DISCONFIRMER — absolute social_volume_accel swapped in under the social_dom_z name (relative vs absolute).
    c2, r2 = _make_member("disc-absolute-volume-accel", cand_spec, market, fee_bps=fee_bps, alt=alt_absolute, store=store, gates=gates)
    candidates.append(c2)
    reports.append(r2)

    # 4) DISCONFIRMER — within-asset time-shuffle placebo of social_dom_z (timing scrambled).
    c3, r3 = _make_member("disc-dominance-time-shuffle", cand_spec, market, fee_bps=fee_bps, alt=alt_placebo, store=store, gates=gates)
    candidates.append(c3)
    reports.append(r3)

    # COHORT BH-FDR across the whole family — register=False + the shared trial_stats so deflation/FDR see the
    # true (grid-inflated) count. THIS is the verdict (NEVER gate.evaluate_cross_asset_ablation).
    persist_spec = durable_persist(
        run_id=f"social-dominance-{data_source}",
        hypothesis="social_dominance share-leadership carries a gate-clearing edge on Binance spot (vs momentum, leak-controlled)",
        source="research/social_dominance", data_source=data_source, fdr_q=fdr_q,
    ) if persist else None
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store), persist=persist_spec)
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.reasons = p.reasons
            r.deflated_sharpe_prob = round(p.deflated_sharpe_prob, 6)

    cand_dsr = r0.deflated_sharpe_prob
    disc: dict[str, str] = {}
    beats_mom = cand_dsr > r1.deflated_sharpe_prob
    beats_abs = cand_dsr > r2.deflated_sharpe_prob
    placebo_reproduces = r3.deflated_sharpe_prob >= cand_dsr
    disc["beat_momentum_only"] = f"{'PASS' if beats_mom else 'FAIL'} (cand dsr {cand_dsr:.3f} vs momentum {r1.deflated_sharpe_prob:.3f})"
    disc["beat_absolute_accel"] = f"{'PASS' if beats_abs else 'FAIL'} (cand dsr {cand_dsr:.3f} vs absolute {r2.deflated_sharpe_prob:.3f})"
    disc["time_shuffle_placebo"] = f"{'PASS' if not placebo_reproduces else 'FAIL-reproduces'} (cand dsr {cand_dsr:.3f} vs placebo {r3.deflated_sharpe_prob:.3f})"
    falsified = (not beats_mom) or (not beats_abs) or placebo_reproduces

    promoted = [r for r in reports if r.promoted and not r.name.startswith("disc-")]
    if promoted and not falsified:
        verdict = "PASS"
        headline = (f"{len(promoted)} member(s) survived the cohort gate + BH-FDR (q={fdr_q}) AND passed all "
                    f"disconfirmers: " + ", ".join(r.name for r in promoted))
    elif promoted and falsified:
        verdict = "FAIL-DISCONFIRMED"
        headline = ("candidate survived BH-FDR but a pre-registered disconfirmer FAILED — the edge is not the "
                    "claimed relative-attention-share signal (likely price-momentum subsumption)")
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        headline = (f"no member survived the cohort gate + BH-FDR (q={fdr_q}); best DSR "
                    f"{best.deflated_sharpe_prob:.3f} ({best.name})" if best else "no candidates")

    return CohortReport(verdict, headline, data_source, window, fdr_q, members=reports, disconfirmers=disc, notes=notes)


def default_catalog_taker() -> Decimal:
    from cosmu.spine.venue import default_catalog

    return default_catalog().venue("binance").taker_fee_bps


def _main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    tmp = tempfile.mkdtemp(prefix="cosmu-socdom-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/socdom.sqlite3", openrouter_api_key=None))
    if db_url:
        data_store = Store(Settings(database_url=db_url, openrouter_api_key=None))
        provider: AltDataProvider = StoreBackedAltProvider(PgAltDataStore(data_store))
    else:
        from cosmu.data.providers.store import AltDataStore

        provider = StoreBackedAltProvider(AltDataStore())

    prov = BinanceSpotOHLCVProvider()
    market: dict[str, list[Bar]] = {}
    for s in _universe():
        try:
            bars = prov.fetch_bars(s, "1d", limit=1000)
            if bars:
                market[s] = bars
        except Exception:  # noqa: BLE001
            continue

    report = run_cohort(market, provider, store, persist=True)

    print(f"SOCIAL-DOMINANCE SHARE-LEADERSHIP COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  symbols={len(market)}")
    print(f"  cohort BH-FDR q={report.fdr_q}")
    for m in report.members:
        flag = "PROMOTED" if m.promoted else ("fdr-only" if m.survived_fdr else "stop")
        print(f"  [{flag:>8}] {m.name:<38} net={m.net_return:+.4f} gross={m.gross_return:+.4f} "
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
