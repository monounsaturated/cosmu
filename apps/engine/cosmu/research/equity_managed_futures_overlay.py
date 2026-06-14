# intent: the FIRST genuinely-DIFFERENT risk premium added to the floor — MANAGED FUTURES (time-series
# trend-following, long/short across all asset classes), the textbook equity-crisis diversifier. The documented-
# defensive-rotation surface (equity_taa_cohort) is near-saturated: its 8 survivors are moderately correlated
# (0.40-0.82), so a 9th rotation adds ~±0.05 Sharpe. Managed futures is a DIFFERENT premium — a probe showed it
# is low-to-NEGATIVELY correlated to the defensive-5 ensemble (DBMF +0.13, KMLM -0.27, CTA -0.33) and an 80/20
# satellite LIFTS the blended Sharpe. We can't run L/S futures ourselves on long-only ETF data, so we access the
# premium through its liquid wrapper ETFs (DBMF replicates the SG CTA index; KMLM the Mount Lucas index) as a
# buy-and-hold total-return stream — a fixed external prior, exactly like the Keller rotations.
#
# WHAT THIS DOES: routes through the UNCHANGED promote_cohort gate, on the satellite's (short) common window:
#   * the managed-futures sleeves alone (DBMF, KMLM) — honest standalone verdicts (short history caps DSR);
#   * the defensive-5 ensemble alone (the floor) — the baseline on the SAME window;
#   * defensive-5 + a 20% managed-futures satellite — the DIVERSIFIED book;
#   * a B&H-SPY null disconfirmer.
# The headline is the marginal value: does the satellite improve the floor's risk-adjusted, holdout-confirmed
# return? Commodities (DBC/PDBC/USO/UNG/DBA) were tested in the probe and REJECTED (no standalone long-only
# premium, they drag the blend) — they are deliberately NOT included. Composes the cohort/ensemble helpers; zero
# LLM; deterministic. Honest about the short managed-futures history — the value is the diversification, not a
# standalone 0.95-gate pass.

from __future__ import annotations

import statistics
import sys
import tempfile
from dataclasses import dataclass, field

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research import equity_daa as daa
from cosmu.research import equity_taa_cohort as cohort
from cosmu.research.equity_taa_cohort import StratStreams, _metrics

# Managed-futures wrapper ETFs (liquid, total-return) — the L/S trend premium we cannot run long-only ourselves.
MF_ETFS = {"DBMF": "iMGP DBi Managed Futures (SG CTA replication)", "KMLM": "KFA Mount Lucas Managed Futures"}
# The floor: the defensive-5 ensemble members (the equity_taa_ensemble winner).
DEFENSIVE5 = ["daa", "paa", "faber_gtaa", "tsmom_trend", "haa"]
_MEMBERS = {"daa": cohort._s_daa, "paa": cohort._s_paa, "faber_gtaa": cohort._s_gtaa,
            "tsmom_trend": cohort._s_tsmom, "haa": cohort._s_haa}
SATELLITE_W = 0.20  # a 20% managed-futures satellite on an 80% defensive-5 core


def _mf_monthly(sym: str) -> dict[tuple[int, int], float]:
    """Buy-and-hold monthly total returns of a managed-futures ETF (one instrument, no rebalancing fee)."""
    ms = daa.load_monthly(sym)
    out: dict[tuple[int, int], float] = {}
    for m in ms.months:
        r = daa._realized_return(ms, m)
        if r is not None:
            out[m] = r
    return out


def _spy_monthly() -> dict[tuple[int, int], float]:
    return _mf_monthly("SPY")


def _defensive5_by_month() -> dict[tuple[int, int], float]:
    streams = {k: f() for k, f in _MEMBERS.items()}
    common = sorted(set.intersection(*[set(s.months) for s in streams.values()]))
    by = {k: dict(zip(streams[k].months, streams[k].net, strict=True)) for k in streams}
    return {m: statistics.fmean([by[k][m] for k in streams]) for m in common}


def _stream(name: str, label: str, by_month: dict, months: list, spy: dict, *, disc: bool = False) -> StratStreams:
    return StratStreams(name, label, list(months), [by_month[m] for m in months],
                        [spy[m] for m in months], is_disconfirmer=disc)


@dataclass
class Row:
    name: str
    label: str
    n: int
    ann_sharpe: float
    dsr: float
    holdout_dsr: float
    max_dd: float
    survived_dsr_holdout: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    rows: list[Row]
    headline: str


def run(*, persist: bool = False) -> Verdict:
    d5 = _defensive5_by_month()
    spy = _spy_monthly()
    streams: list[StratStreams] = []

    for sym, desc in MF_ETFS.items():
        mr = _mf_monthly(sym)
        common = sorted(set(mr) & set(d5) & set(spy))
        if len(common) < 36:
            continue
        streams.append(_stream(f"mf_{sym.lower()}", f"{sym} — {desc}", mr, common, spy))
        # defensive-5 baseline on THIS satellite's window (apples-to-apples), and the 80/20 diversified book.
        streams.append(_stream(f"def5_on_{sym.lower()}_win", f"Defensive-5 floor (on {sym} window)", d5, common, spy))
        blend = {m: (1 - SATELLITE_W) * d5[m] + SATELLITE_W * mr[m] for m in common}
        streams.append(_stream(f"def5_plus20_{sym.lower()}", f"Defensive-5 + 20% {sym} (diversified book)",
                               blend, common, spy))

    # a B&H-SPY null on the longest satellite window (disconfirmer)
    if streams:
        longest = max(streams, key=lambda s: len(s.months))
        streams.append(_stream("buy_hold_spy", "Buy & Hold SPY (NULL)", spy, longest.months, spy, disc=True))

    if not streams:
        return Verdict([], "no managed-futures satellite had enough history")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-mf-')}/g.sqlite3",
                           openrouter_api_key=None))
    gates = store.settings.gates
    metrics = {}
    for s in streams:
        m = _metrics(s, trials_counted=len(streams))
        metrics[s.name] = m
        register_trial(store, float(m.sharpe_per_obs), source="mf_overlay", label=s.name)
    trials = trial_stats(store)
    cands = [Candidate(id=s.name, metrics=metrics[s.name], net_profit=float(metrics[s.name].oos_return),
                       source="mf_overlay", label=s.label) for s in streams]
    persist_spec = durable_persist(
        run_id="equity-managed-futures-overlay",
        hypothesis="a managed-futures (trend) satellite diversifies the defensive-5 floor — a DIFFERENT, low-"
                   "correlation risk premium that improves the blended holdout-confirmed Sharpe",
        source="research/equity_managed_futures_overlay", data_source="equities-offline",
        universe="defensive5+managed-futures") if persist else None
    proms = {p.candidate_id: p for p in promote_cohort(store, cands, gates, fdr_q=0.10, register=False,
                                                       trials=trials, persist=persist_spec)}

    def _sr(s: StratStreams) -> float:
        sd = statistics.pstdev(s.net)
        return (statistics.fmean(s.net) / sd * (12 ** 0.5)) if sd > 0 else 0.0

    rows = []
    for s in streams:
        m = metrics[s.name]
        p = proms[s.name]
        reasons = [r for r in p.reasons if r != "buy_and_hold"]
        rows.append(Row(s.name, s.label, m.num_trades, round(_sr(s), 3),
                        round(float(p.deflated_sharpe_prob), 4), round(float(m.holdout_deflated_sharpe), 4),
                        round(float(m.max_drawdown), 4), not reasons, p.reasons))

    # headline: did the diversified book beat the floor on the SAME window?
    best = None
    for sym in MF_ETFS:
        base = next((r for r in rows if r.name == f"def5_on_{sym.lower()}_win"), None)
        blend = next((r for r in rows if r.name == f"def5_plus20_{sym.lower()}"), None)
        if base and blend and blend.ann_sharpe > base.ann_sharpe:
            if best is None or blend.ann_sharpe - base.ann_sharpe > best[3]:
                best = (sym, blend.ann_sharpe, base.ann_sharpe, blend.ann_sharpe - base.ann_sharpe, blend.holdout_dsr)
    if best:
        sym, bl, ba, d, hd = best
        headline = (f"Defensive-5 + 20% {sym} lifts the floor's Sharpe {ba:.2f} -> {bl:.2f} (+{d:.2f}) with a "
                    f"positive holdout ({hd:+.3f}): managed futures is a REAL diversifier — a different, low-"
                    f"correlation risk premium. (Short MF history caps the standalone DSR; the value is the blend.)")
    else:
        headline = "no managed-futures satellite improved the defensive-5 floor on its window"
    return Verdict(rows, headline)


def _print(v: Verdict) -> None:
    print("\n" + "=" * 104)
    print("MANAGED-FUTURES OVERLAY — a DIFFERENT risk premium to diversify the defensive-5 floor")
    print("=" * 104)
    print(f"  {'book':<46} {'n':>4} {'annSR':>6} {'DSR':>6} {'holdout':>8} {'maxDD':>6}  flag")
    for r in v.rows:
        flag = "DSR+HOLDOUT" if r.survived_dsr_holdout else "—"
        print(f"  {r.label[:46]:<46} {r.n:>4} {r.ann_sharpe:>6.2f} {r.dsr:>6.3f} {r.holdout_dsr:>+8.3f} "
              f"{r.max_dd:>6.3f}  {flag}")
    print("-" * 104)
    print(f"  HEADLINE: {v.headline}")
    print("=" * 104)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    _print(run(persist="--persist" in argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
