# intent: the HONEST first-cut Gate harness for the LLM-NARRATIVE axis — score RAW GDELT news headlines with our
# OWN OpenRouter LLM (content-only, PIT) into a daily 'net narrative pressure' series, then judge the long book
# as ONE promote_cohort BH-FDR family (q=0.10) on REAL Binance daily bars + a REAL purged+embargoed holdout +
# PIT crypto fees, with TWO pre-registered in-family DISCONFIRMERS. The verdict comes ONLY from promote_cohort's
# BH-FDR (NEVER gate.evaluate_cross_asset_ablation). Every grid variant of every member is recorded as a trial so
# deflation/FDR see the true inflated count. A fresh tempfile store isolates the trial ledger. The holdout DSR is
# computed by run_strategy_backtest_detailed (the SAME real purged+embargoed last-fifth the funding/social
# cohorts use) — it is NOT stubbed.
#
# Members (ONE family, all counted as trials):
#   llm-narrative-pressure-long  — long when the LLM-scored daily news narrative is net-bullish AND price
#                                  momentum confirms; ~1-week hold; exits on narrative cross_down.
# Pre-registered disconfirmers:
#   disc-narrative-time-shuffle  — PLACEBO: same book with the LLM scores TIME-SHUFFLED (marginal distribution
#                                  preserved, timing scrambled). If it reproduces the edge, the LLM either leaked
#                                  the future or the timing is noise — either way the signal is falsified.
#   disc-momentum-only-control   — SUBSUMPTION: the same long book with the narrative leg removed (price momentum
#                                  only). If it matches/beats the candidate, the LLM narrative adds no orthogonal
#                                  information and the 'edge' is just price momentum.
# Falsified iff the time-shuffle placebo reproduces the candidate, OR the candidate does not beat the
# momentum-only control on deflated Sharpe.
#
# THE LOOK-AHEAD DEFENSE (the whole game): the LLM scores ONLY each headline's text (content_only prompt, no
# date/price/outcome), each item is stamped with its OWN publish_time, and the daily point is available_at =
# day+1 (a bar at t reads only narrative from days <= t-1). The time-shuffle disconfirmer is the EMPIRICAL proof
# that no leakage survived: a leaky score still 'predicts' after shuffling; an honest content-only score does not.

from __future__ import annotations

import os
import random
import statistics
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint
from cosmu.data.backtest import align_asof, run_strategy_backtest_detailed
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.knowledge.store import Store
from cosmu.lab.finder import build_grid
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import cscv_pbo, score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.research.carry_ablation import _resolve_params
from cosmu.research.llm_narrative_pipeline import (
    NARRATIVE_FEATURE,
    CachedNarrativeScorer,
    fetch_gdelt_headlines,
    score_headlines_to_daily,
)
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec

_FDR_Q = 0.10
_CANDIDATE = "llm-narrative-pressure-long.json"
_DISC_MOM = "disc-momentum-only-control.json"

# First cut: ONE rich, liquid name. GDELT has dense daily coverage for the majors; BTC is the deepest single
# news stream and the most liquid spot market. Scaling to a basket is the Modal path (reported upstream).
_FIRST_CUT_SYMBOL = "BTCUSDT"


@dataclass
class MemberReport:
    name: str
    net_return: float
    gross_return: float
    cost_ratio: float
    deflated_sharpe_prob: float
    holdout_deflated_sharpe: float
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
    narrative_points: int
    headlines_scored: int
    llm_calls: int
    llm_cost_usd: float
    members: list[MemberReport] = field(default_factory=list)
    disconfirmers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def load_spec(fname: str) -> StrategySpec:
    import json
    from pathlib import Path

    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    return StrategySpec.model_validate(json.loads((inbox / fname).read_text()))


def _time_shuffle(points: list[AltDataPoint], *, seed: int) -> list[AltDataPoint]:
    """PLACEBO: keep the EXACT marginal distribution of the LLM scores (same multiset of values) but randomly
    permute which day carries which value, destroying the signal's TIMING. PIT shape preserved (shuffled values
    reattach to the original ts/available_at order). If the LLM narrative carried no real, leak-free timing
    information, this placebo reproduces the edge — a placebo that matches the signal FALSIFIES it."""
    if not points:
        return points
    vals = [p.value for p in points]
    rng = random.Random(seed)
    rng.shuffle(vals)
    return [AltDataPoint(ts=p.ts, available_at=p.available_at, value=vals[i]) for i, p in enumerate(points)]


def _join(points: list[AltDataPoint], bars: list[Bar], symbol: str, feat: str) -> dict[str, dict[str, dict[str, float]]]:
    """alt_by_symbol = {symbol: {feat: {bar.ts.isoformat(): value}}} via the PIT as-of join."""
    j = align_asof(points, bars)
    return {symbol: {feat: j}} if j else {}


def _screen(
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
    label: str,
):
    """build_grid → screen every variant on REAL bars/narrative/fees, RECORD each as a trial (so deflation/FDR
    see the true count), return gate-best params, its detailed result, and the per-variant validation streams."""
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
        record_trial(store, float(m.sharpe_per_obs), source="llm_narrative", label=f"{label}:{variant.config_tag}")
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
    spec: StrategySpec,
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
    cand = Candidate(id=sid, metrics=m, net_profit=net_return, source="llm_narrative", label=sid, return_variance=var or 1.0)
    rep = MemberReport(
        name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
        cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(dsr, 6),
        holdout_deflated_sharpe=round(float(m.holdout_deflated_sharpe), 6), cscv_pbo=round(pbo, 6),
        beat_buy_and_hold=net_return > float(m.buy_and_hold_return),
        regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0),
        num_trades=m.num_trades, max_drawdown=round(float(m.max_drawdown), 6),
    )
    return cand, rep


def run_cohort(
    market: dict[str, list[Bar]],
    narrative_points: list[AltDataPoint],
    store: Store,
    *,
    symbol: str = _FIRST_CUT_SYMBOL,
    data_source: str = "gdelt+openrouter",
    fdr_q: float = _FDR_Q,
    headlines_scored: int = 0,
    llm_calls: int = 0,
    llm_cost_usd: float = 0.0,
) -> CohortReport:
    gates = store.settings.gates
    fee_bps = default_catalog().venue("binance").taker_fee_bps

    bars = market.get(symbol, [])
    win = f"{bars[0].ts.date()}..{bars[-1].ts.date()}" if bars else "n/a"
    notes: list[str] = []

    if not narrative_points:
        return CohortReport("INSUFFICIENT-DATA", "no LLM-scored narrative points (no key / no headlines)",
                            data_source, win, fdr_q, 0, headlines_scored, llm_calls, llm_cost_usd,
                            notes=["narrative series empty — set OPENROUTER_API_KEY and ensure GDELT returned headlines"])

    # Clip bars to the narrative window so the book is judged only where the signal could actually be read.
    lo = min(p.available_at for p in narrative_points)
    hi = max(p.available_at for p in narrative_points)
    clipped = {symbol: [b for b in bars if lo <= b.ts <= hi]}
    if len(clipped[symbol]) < 80:
        notes.append(
            f"narrative window yields only {len(clipped[symbol])} tradeable bars (< 80 the backtest needs for a "
            f"holdout) — GDELT's free ~3-month doc-API depth is the binding constraint, NOT look-ahead. The "
            f"approach is wired end-to-end; a real verdict needs a deeper raw-text pull (Modal path)."
        )
        # Fall back to the FULL bar window joined with whatever narrative exists (PIT join still drops pre-signal
        # bars to None), so the harness still RUNS and reports honest numbers rather than aborting.
        clipped = {symbol: bars}

    # candidate join (real LLM scores) + the time-shuffle placebo (same values, scrambled timing).
    alt_candidate = _join(narrative_points, clipped[symbol], symbol, NARRATIVE_FEATURE)
    alt_placebo = _join(_time_shuffle(narrative_points, seed=4242), clipped[symbol], symbol, NARRATIVE_FEATURE)

    cand_spec = load_spec(_CANDIDATE)
    mom_spec = load_spec(_DISC_MOM)

    candidates: list[Candidate] = []
    reports: list[MemberReport] = []

    # 1) the real candidate — LLM-narrative long book.
    c0, r0 = _make_member("llm-narrative-pressure-long", cand_spec, clipped, fee_bps=fee_bps, alt=alt_candidate, store=store, gates=gates)
    candidates.append(c0)
    reports.append(r0)

    # 2) DISCONFIRMER — time-shuffle placebo (timing scrambled; MUST destroy the edge).
    c1, r1 = _make_member("disc-narrative-time-shuffle", cand_spec, clipped, fee_bps=fee_bps, alt=alt_placebo, store=store, gates=gates)
    candidates.append(c1)
    reports.append(r1)

    # 3) DISCONFIRMER — momentum-only control (no narrative leg; alt empty so its ret_Nd legs are native).
    c2, r2 = _make_member("disc-momentum-only-control", mom_spec, clipped, fee_bps=fee_bps, alt={}, store=store, gates=gates)
    candidates.append(c2)
    reports.append(r2)

    # COHORT BH-FDR across the whole family — register=False + the shared trial_stats so deflation/FDR see the
    # true (grid-inflated) count. THIS is the verdict (NEVER gate.evaluate_cross_asset_ablation).
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store))
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.reasons = p.reasons
            r.deflated_sharpe_prob = round(p.deflated_sharpe_prob, 6)

    cand_dsr = r0.deflated_sharpe_prob
    placebo_reproduces = r1.deflated_sharpe_prob >= cand_dsr
    beats_mom = cand_dsr > r2.deflated_sharpe_prob
    disc = {
        "time_shuffle_placebo": f"{'PASS' if not placebo_reproduces else 'FAIL-reproduces'} "
                                f"(cand dsr {cand_dsr:.3f} vs placebo {r1.deflated_sharpe_prob:.3f})",
        "beat_momentum_only": f"{'PASS' if beats_mom else 'FAIL'} "
                              f"(cand dsr {cand_dsr:.3f} vs momentum {r2.deflated_sharpe_prob:.3f})",
    }
    falsified = placebo_reproduces or (not beats_mom)

    promoted = [r for r in reports if r.promoted and not r.name.startswith("disc-")]
    if promoted and not falsified:
        verdict = "PASS"
        headline = (f"LLM-narrative long survived the cohort gate + BH-FDR (q={fdr_q}) AND passed both "
                    f"disconfirmers — a real, leak-free narrative edge (first cut, single name).")
    elif promoted and falsified:
        verdict = "FAIL-DISCONFIRMED"
        headline = ("candidate survived BH-FDR but a pre-registered disconfirmer FAILED — the 'edge' is not a "
                    "leak-free LLM narrative signal (time-shuffle reproduced it, or it's price-momentum subsumption).")
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        headline = (f"no member survived the cohort gate + BH-FDR (q={fdr_q}); best DSR "
                    f"{best.deflated_sharpe_prob:.3f} ({best.name})" if best else "no candidates")

    return CohortReport(verdict, headline, data_source, win, fdr_q, len(narrative_points), headlines_scored,
                        llm_calls, llm_cost_usd, members=reports, disconfirmers=disc, notes=notes)


def _main() -> int:
    symbol = os.environ.get("NARRATIVE_SYMBOL", _FIRST_CUT_SYMBOL)
    days_back = int(os.environ.get("NARRATIVE_DAYS_BACK", "90"))

    prov = BinanceSpotOHLCVProvider()
    bars = prov.fetch_bars(symbol, "1d", limit=1000)
    market = {symbol: bars}

    # Pull RAW GDELT headlines (cached), then score each content-only/PIT into a daily narrative series.
    items = fetch_gdelt_headlines(symbol, days_back=days_back)
    scorer = CachedNarrativeScorer()
    points = score_headlines_to_daily(items, scorer)

    tmp = tempfile.mkdtemp(prefix="cosmu-llmnarr-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/llmnarr.sqlite3", openrouter_api_key=None))
    report = run_cohort(
        market, points, store, symbol=symbol,
        headlines_scored=len(items), llm_calls=scorer.calls, llm_cost_usd=scorer.cost_usd,
    )

    print(f"LLM-NARRATIVE FIRST-CUT COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  symbol={symbol}  window={report.window}  fdr_q={report.fdr_q}")
    print(f"  headlines_scored={report.headlines_scored}  narrative_days={report.narrative_points}  "
          f"llm_live_calls={report.llm_calls}  llm_cost=${report.llm_cost_usd:.4f}")
    for r in report.members:
        flag = "PROMOTED" if r.promoted else ("fdr-only" if r.survived_fdr else "stop")
        print(f"  [{flag:>8}] {r.name:<30} net={r.net_return:+.4f} gross={r.gross_return:+.4f} "
              f"cost_ratio={r.cost_ratio:.3f} dsr={r.deflated_sharpe_prob:.3f} holdoutDSR={r.holdout_deflated_sharpe:+.3f} "
              f"pbo={r.cscv_pbo:.3f} reg+={r.regimes_positive} trades={r.num_trades} maxDD={r.max_drawdown:.3f} "
              f"b&h={'Y' if r.beat_buy_and_hold else 'N'} fdr={'Y' if r.survived_fdr else 'N'}")
        if r.reasons:
            print(f"             reasons: {', '.join(r.reasons)}")
    print("  DISCONFIRMERS:")
    for k, v in report.disconfirmers.items():
        print(f"    {k}: {v}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
