# intent: the HONEST verdict on the regime-detection lever (HANDOFF §8). It asks the only question that matters:
# does a NO-REPAINT, stride-disciplined Markov regime (research/regime.py) ADD VALUE as a GATING layer — i.e.
# beat buy-and-hold risk-adjusted NET of turnover, beat the NAIVE price-momentum gate (the "regime-momentum the
# deploy-lane TAA already captures"), and SURVIVE a dwell-preserving shuffle placebo — through promote_cohort
# BH-FDR + a REAL purged+embargoed holdout (research/equity_holdout.metrics_with_holdout). It is deliberately NOT
# aimed at the 0.95 novel-edge Gate: regime is a gating/feature layer, so the verdict we want is "does it improve
# a base book," with the price-momentum + placebo disconfirmers guarding against momentum-in-disguise / luck.
#
# Members (DISTINCT candidates in ONE BH-FDR family — every grid variant counted as a trial so deflation/FDR see
# the true inflated count, a fresh tempfile store isolates the ledger):
#   regime-gate-markov        — base book exposure tilted by the no-repaint Markov regime (grid over W/enter_z/dwell)
#   flat-buy-and-hold         — exposure ≡ 1 (the baseline the gate must beat, risk-adjusted + net)
# Pre-registered disconfirmers (their free params counted as trials too):
#   disc-price-momentum-gate  — exposure from a naive trailing-return-sign gate (classic TAA abs-momentum)
#   disc-shuffle-placebo      — the Markov exposure series shuffled preserving its run-length (dwell) distribution
# Falsified iff the Markov gate does NOT beat flat AND the price-momentum gate, or the placebo reproduces it.
#
# Exposure is LAGGED + no-repaint (sized strictly from prior bars); turnover is charged on every exposure change.

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.market import Bar, default_crypto_reference
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.equity_holdout import metrics_with_holdout
from cosmu.research.regime import RegimeConfig, regime_states

_FDR_Q = 0.10
# Regime free-param grid (slow, low-turnover horizons) — every (W, enter_z, dwell) combo is a counted trial.
_REGIME_GRID = [
    (w, ez, dw)
    for w in (30, 60, 100)
    for ez in (0.10, 0.20)
    for dw in (15, 30)
]
# Equity-cache default; env-overridable so it works off this Mac / on Modal-Railway (the §9 hardcoded-path fix).
_EQUITY_CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "/Users/device/cosmu/.cosmu/market_data/equities"))


@dataclass(frozen=True)
class MemberReport:
    name: str
    net_return: float
    deflated_sharpe_prob: float
    sharpe_ann: float
    max_drawdown: float
    recovery_factor: float  # net return / max drawdown — drawdown-aware quality the Sharpe is blind to
    holdout_dsr: float
    n_obs: int
    promoted: bool = False
    survived_fdr: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegimeCohortReport:
    asset: str
    verdict: str
    headline: str
    fdr_q: float
    members: list[MemberReport]
    disconfirmers: dict[str, str]
    regime_diag: dict[str, object]


# --------------------------------------------------------------------------- data


def load_tr_bars(symbol: str) -> list[Bar]:
    """Load a daily total-return close series (`*_tr.json`: [{ts: epoch_ms, close}]) as Bars (close only)."""
    from datetime import UTC, datetime

    rows = json.loads((_EQUITY_CACHE / f"{symbol}_tr.json").read_text())
    bars: list[Bar] = []
    for r in rows:
        c = Decimal(str(r["close"]))
        ts = datetime.fromtimestamp(r["ts"] / 1000, tz=UTC)
        bars.append(Bar(ts=ts, open=c, high=c, low=c, close=c, volume=Decimal("0")))
    return bars


def load_bars(asset: str) -> list[Bar]:
    """crypto symbols (…USDT) come from the Binance daily cache; everything else from the equity TR cache."""
    if asset.endswith("USDT"):
        return default_crypto_reference().fetch_bars(asset, "1d", limit=5000)
    return load_tr_bars(asset)


# --------------------------------------------------------------------------- exposure construction (causal)


def _daily_returns(bars: list[Bar]) -> list[float]:
    out = []
    for i in range(1, len(bars)):
        p0, p1 = float(bars[i - 1].close), float(bars[i].close)
        out.append((p1 / p0) - 1.0 if p0 > 0 else 0.0)
    return out


def _markov_exposure(bars: list[Bar], cfg: RegimeConfig) -> dict[int, float]:
    """bar-index -> exposure ∈ {0.0, 0.5, 1.0} from the no-repaint regime state AS OF that bar's close (used to
    size the NEXT bar's return → strictly causal). bear→0, sideways→0.5, bull→1."""
    tilt = {-1: 0.0, 0: 0.5, 1: 1.0}
    states = regime_states(bars, cfg)
    base = cfg.warmup
    return {base + k: tilt[s.state] for k, s in enumerate(states)}


def _price_momentum_exposure(bars: list[Bar], window: int, dwell: int) -> dict[int, float]:
    """The NAIVE disconfirmer: classic TAA absolute-momentum gate — full exposure when the trailing `window`
    return is positive, floored at 0 otherwise, with a min-dwell. Causal (trailing close ratio only)."""
    closes = [float(b.close) for b in bars]
    out: dict[int, float] = {}
    state, held = 1.0, dwell
    for i in range(window, len(bars)):
        mom = closes[i] / closes[i - window] - 1.0
        if held >= dwell:
            want = 1.0 if mom > 0 else 0.0
            if want != state:
                state, held = want, 0
        held += 1
        out[i] = state
    return out


def _gated_returns(rets: list[float], exposure_by_bar: dict[int, float], *, fee_frac: float) -> list[float]:
    """Net daily returns of the base book under a per-bar exposure tilt. The return INTO bar j (rets[j-1]) is
    sized by the exposure AS OF bar j-1 (strictly prior → no look-ahead); a turnover fee is charged on every
    change in exposure. Bars before the first exposure read are skipped (we'd hold no view yet)."""
    out: list[float] = []
    prev_exp = None
    for j in range(1, len(rets) + 1):  # rets[j-1] is the return into bar j
        exp = exposure_by_bar.get(j - 1)
        if exp is None:
            continue
        turn = 0.0 if prev_exp is None else abs(exp - prev_exp)
        out.append(exp * rets[j - 1] - fee_frac * turn)
        prev_exp = exp
    return out


def _shuffle_preserving_dwell(exposure_by_bar: dict[int, float], *, seed: int) -> dict[int, float]:
    """Placebo: keep the EXACT run-length (dwell) structure but relocate the runs — destroys any real timing
    while preserving turnover + state distribution. Runs of each value are shuffled and re-laid in place."""
    if not exposure_by_bar:
        return {}
    keys = sorted(exposure_by_bar)
    seq = [exposure_by_bar[k] for k in keys]
    # collect run lengths
    runs: list[tuple[float, int]] = []
    cur, n = seq[0], 1
    for v in seq[1:]:
        if v == cur:
            n += 1
        else:
            runs.append((cur, n))
            cur, n = v, 1
    runs.append((cur, n))
    rng = random.Random(seed)
    rng.shuffle(runs)
    out_seq: list[float] = []
    for v, length in runs:
        out_seq.extend([v] * length)
    return dict(zip(keys, out_seq, strict=True))


# --------------------------------------------------------------------------- the cohort


def _member_metrics(rets: list[float], exposure: dict[int, float], *, fee_frac: float, trials_counted: int,
                    ppy: int, store: Store, label: str):  # noqa: ANN201
    gated = _gated_returns(rets, exposure, fee_frac=fee_frac)
    if len(gated) < 30:
        return None
    metrics, _split = metrics_with_holdout(gated, trials_counted=trials_counted, periods_per_year=ppy)
    record_trial(store, float(metrics.sharpe_per_obs), source="regime", label=label)
    return metrics, gated


def _best_markov(bars: list[Bar], rets: list[float], *, fee_frac: float, ppy: int, store: Store, gates):  # noqa: ANN001,ANN201
    """Screen the Markov-regime exposure across the (W, enter_z, dwell) grid; every variant a counted trial;
    return the gate-best (by dSR) variant's (metrics, exposure, cfg)."""
    best = None
    for w, ez, dw in _REGIME_GRID:
        cfg = RegimeConfig(window=w, enter_z=ez, exit_z=ez / 3, min_dwell=dw)
        exp = _markov_exposure(bars, cfg)
        got = _member_metrics(rets, exp, fee_frac=fee_frac, trials_counted=len(_REGIME_GRID), ppy=ppy,
                              store=store, label=f"markov:w{w}_ez{ez}_dw{dw}")
        if got is None:
            continue
        m, _ = got
        dsr = float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob)
        if best is None or dsr > best[0]:
            best = (dsr, m, exp, cfg)
    return best


def _best_price_momentum(bars: list[Bar], rets: list[float], *, fee_frac: float, ppy: int, store: Store, gates):  # noqa: ANN001,ANN201
    best = None
    for w in (30, 60, 100, 150, 200):
        for dw in (15, 30):
            exp = _price_momentum_exposure(bars, w, dw)
            got = _member_metrics(rets, exp, fee_frac=fee_frac, trials_counted=10, ppy=ppy, store=store,
                                  label=f"pricemom:w{w}_dw{dw}")
            if got is None:
                continue
            m, _ = got
            dsr = float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob)
            if best is None or dsr > best[0]:
                best = (dsr, m, exp)
    return best


def run_regime_cohort(asset: str, bars: list[Bar], store: Store, *, fee_bps: float = 2.0,
                      ppy: int = 252, fdr_q: float = _FDR_Q, persist: bool = False) -> RegimeCohortReport:
    """`persist=True` writes the verdict to durable experiment-memory (gate_verdicts) via the real configured
    store — _main sets it on real runs; tests leave it False so they never touch the durable store."""
    from cosmu.research.regime import regime_summary

    gates = store.settings.gates
    fee_frac = fee_bps / 10_000.0
    rets = _daily_returns(bars)

    markov = _best_markov(bars, rets, fee_frac=fee_frac, ppy=ppy, store=store, gates=gates)
    pricemom = _best_price_momentum(bars, rets, fee_frac=fee_frac, ppy=ppy, store=store, gates=gates)
    if markov is None or pricemom is None:
        return RegimeCohortReport(asset, "ABSTAIN", "too few bars for an honest regime cohort", fdr_q, [], {}, {})

    _, m_markov, exp_markov, cfg_markov = markov
    _, m_pricemom, _exp_pm = pricemom

    # flat buy-and-hold (exposure ≡ 1, no turnover) — the baseline the gate must beat.
    flat_exp = {i: 1.0 for i in range(len(bars))}
    m_flat, _ = _member_metrics(rets, flat_exp, fee_frac=fee_frac, trials_counted=1, ppy=ppy, store=store, label="flat")  # type: ignore[misc]

    # placebo: the Markov exposure shuffled preserving its run-length structure.
    placebo_exp = _shuffle_preserving_dwell(exp_markov, seed=12345)
    m_placebo, _ = _member_metrics(rets, placebo_exp, fee_frac=fee_frac, trials_counted=1, ppy=ppy, store=store, label="placebo")  # type: ignore[misc]

    specs = [
        ("regime-gate-markov", m_markov),
        ("flat-buy-and-hold", m_flat),
        ("disc-price-momentum-gate", m_pricemom),
        ("disc-shuffle-placebo", m_placebo),
    ]
    candidates = [
        Candidate(id=name, metrics=m, net_profit=float(m.oos_return), source="regime", label=name)
        for name, m in specs
    ]
    persist_spec = durable_persist(
        run_id=f"regime-{asset}",
        hypothesis=f"a no-repaint Markov regime gate adds value over buy-and-hold on {asset} (vs price-momentum, leak-controlled)",
        source="research/regime", asset=asset, fee_bps=fee_bps,
    ) if persist else None
    promotions = {p.candidate_id: p for p in promote_cohort(
        store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store), persist=persist_spec
    )}

    members = [
        MemberReport(
            name=name, net_return=round(float(m.oos_return), 6),
            deflated_sharpe_prob=round(promotions[name].deflated_sharpe_prob, 6),
            sharpe_ann=round(float(m.sharpe), 4), max_drawdown=round(float(m.max_drawdown), 6),
            recovery_factor=round(m.recovery_factor, 3), holdout_dsr=round(float(m.holdout_deflated_sharpe), 6), n_obs=int(m.n_obs),
            promoted=promotions[name].promoted, survived_fdr=promotions[name].survived_fdr,
            reasons=promotions[name].reasons,
        )
        for name, m in specs
    ]
    by = {x.name: x for x in members}
    markov_dsr = by["regime-gate-markov"].deflated_sharpe_prob
    beats_flat = by["regime-gate-markov"].sharpe_ann > by["flat-buy-and-hold"].sharpe_ann
    beats_pricemom = markov_dsr > by["disc-price-momentum-gate"].deflated_sharpe_prob
    placebo_reproduces = by["disc-shuffle-placebo"].deflated_sharpe_prob >= markov_dsr
    disc = {
        "beat_buy_and_hold_riskadj": f"{'PASS' if beats_flat else 'FAIL'} "
                                     f"(markov annSR {by['regime-gate-markov'].sharpe_ann:.3f} vs flat {by['flat-buy-and-hold'].sharpe_ann:.3f})",
        "beat_naive_price_momentum": f"{'PASS' if beats_pricemom else 'FAIL'} "
                                     f"(markov dsr {markov_dsr:.3f} vs price-mom {by['disc-price-momentum-gate'].deflated_sharpe_prob:.3f})",
        "shuffle_placebo": f"{'PASS' if not placebo_reproduces else 'FAIL-reproduces'} "
                           f"(markov dsr {markov_dsr:.3f} vs placebo {by['disc-shuffle-placebo'].deflated_sharpe_prob:.3f})",
    }
    falsified = (not beats_flat) or (not beats_pricemom) or placebo_reproduces
    if by["regime-gate-markov"].promoted and not falsified:
        verdict = "PASS"
        headline = "the no-repaint Markov regime gate beat buy-and-hold + the naive price-momentum gate AND survived the placebo through BH-FDR + holdout."
    elif by["regime-gate-markov"].promoted and falsified:
        verdict = "FAIL-DISCONFIRMED"
        headline = "the regime gate cleared BH-FDR but a disconfirmer fired — it is momentum-in-disguise (no edge beyond the naive price-momentum gate / a placebo reproduced it)."
    else:
        verdict = "FAIL"
        headline = f"no regime gate survived the cohort gate + BH-FDR (q={fdr_q}); best dsr {markov_dsr:.3f}."

    return RegimeCohortReport(asset, verdict, headline, fdr_q, members, disc,
                              regime_summary(bars, cfg_markov))


def _main() -> int:
    import tempfile

    asset = os.environ.get("REGIME_ASSET", "SPY")
    bars = load_bars(asset)
    fee_bps = float(os.environ.get("REGIME_FEE_BPS", "5.0" if asset.endswith("USDT") else "2.0"))
    tmp = tempfile.mkdtemp(prefix="cosmu-regime-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/regime.sqlite3", openrouter_api_key=None))
    rep = run_regime_cohort(asset, bars, store, fee_bps=fee_bps, persist=True)

    print(f"REGIME-GATE COHORT — {asset} — {rep.verdict}")
    print(f"  {rep.headline}")
    print(f"  bars={len(bars)}  fee_bps={fee_bps}  fdr_q={rep.fdr_q}")
    print(f"  regime diag: {rep.regime_diag}")
    for m in rep.members:
        flag = "PROMOTED" if m.promoted else ("fdr-cut" if not m.survived_fdr else "rejected")
        print(f"    {m.name:26s} dsr={m.deflated_sharpe_prob:.4f} annSR={m.sharpe_ann:+.3f} "
              f"recovery={m.recovery_factor:.2f} holdoutDSR={m.holdout_dsr:+.4f} maxDD={m.max_drawdown:.3f} n={m.n_obs} [{flag}] {m.reasons}")
    print("  disconfirmers:")
    for k, v in rep.disconfirmers.items():
        print(f"    {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
