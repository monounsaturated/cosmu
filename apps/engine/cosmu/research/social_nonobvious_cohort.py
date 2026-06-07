# intent: route the THREE non-obvious social specs (social-accel-uncrowded-momentum, galaxy-altitude-drawdown-
# avoidance, btc-social-contagion-alt-lead) through the EXISTING deterministic scorer + promote_cohort BH-FDR
# (q=0.10) on REAL Binance daily bars + the REAL backfilled LunarCrush history, as ONE cohort. Unlike the failed
# generic cohort, these read the NORMALIZED social features (cosmu/research/social_norm.py) so the fitted
# thresholds actually bind (the phase0-social-signal §4 fix). inputs: cached real daily bars + the on-disk
# LunarCrush JSONL store + a Store for the shared trial ledger; outputs: a CohortReport printed to stdout.
# invariants: ZERO LLM; the scorer thresholds + q=0.10 are NOT changed (we only INTERPRET); features are derived
# point-in-time (available_at inherited from the raw points, no look-ahead); every grid variant recorded as a
# trial so deflation/FDR see the true count. Reuses the social_signal_cohort run loop verbatim — only the
# alt-join (normalized instead of raw) and the spec list differ.

from __future__ import annotations

from cosmu.data.altdata import AltDataStore, StoreBackedAltProvider
from cosmu.data.market import BinanceSpotOHLCVProvider
from cosmu.research.carry_ablation import _real_market
from cosmu.research.social_norm import derive_social_alt
from cosmu.research.social_signal_cohort import _clip_to_social_window, run_cohort

_SPECS = [
    "social-accel-uncrowded-momentum.json",
    "social-excess-attention-week-continuation.json",
    "btc-social-contagion-alt-lead.json",
]


def load_specs():
    import json
    from pathlib import Path

    from cosmu.strategy.spec import StrategySpec

    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    return [(f, StrategySpec.model_validate(json.loads((inbox / f).read_text()))) for f in _SPECS]


def _main() -> int:
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    tmp = tempfile.mkdtemp(prefix="cosmu-social-nonobvious-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/social.sqlite3", openrouter_api_key=None))
    specs = load_specs()
    provider = StoreBackedAltProvider(AltDataStore())
    market = _clip_to_social_window(_real_market(BinanceSpotOHLCVProvider()), provider)

    # NORMALIZED alt-join (the only seam that differs from social_signal_cohort): scale-stable, PIT.
    norm_alt = derive_social_alt(market, provider)
    report = run_cohort(
        specs, market, provider, store, override_alt=norm_alt,
        persist=True, persist_source="research/social_nonobvious",
        persist_hypothesis="a NON-OBVIOUS normalized-social spec carries a gate-clearing edge on Binance spot",
    )

    print(f"PHASE-0 SOCIAL NON-OBVIOUS COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  regimes={report.regimes_covered}")
    print(f"  social symbols with normalized data: {sum(1 for v in norm_alt.values() if v)}/{len(market)}")
    print(f"  cohort BH-FDR q={report.fdr_q}")
    for a in report.specs:
        flag = "PROMOTED" if a.promoted else ("fdr-only" if a.survived_fdr else "stop")
        print(f"  [{flag:>8}] {a.name:<40} net={a.net_return:+.4f} gross={a.gross_return:+.4f} "
              f"cost_ratio={a.cost_ratio:.3f} dsr={a.deflated_sharpe_prob:.3f} pbo={a.cscv_pbo:.3f} "
              f"reg+={a.regimes_positive} trades={a.num_trades} maxDD={a.max_drawdown:.3f} skew={a.skew:+.2f} "
              f"fdr={'Y' if a.survived_fdr else 'N'}")
        if a.reasons:
            print(f"             reasons: {', '.join(a.reasons)}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
