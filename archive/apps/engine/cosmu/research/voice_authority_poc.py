# intent: FIRST end-to-end test of the credibility / "voices" edge lane (roadmap #6) — author typed StrategySpecs
# whose ENTRY keys off the registered `authority_weighted_claim_signal` PIT feature, then route them through the
# EXACT per-combo BRUT Gate the finder uses, to prove the WIRE works (spec → backtest → metrics → Gate verdict).
# inputs: a `market` (cached/synthetic bars) + an authority series injected through the same `alt_by_symbol` PIT
# join the finder feeds funding/sentiment through; outputs: VoiceAuthorityPanel (one cell per spec×symbol with its
# DSR/PBO/trades/Gate verdict). invariants: the GATE IS UNTOUCHED (read-only GateSettings constants, locked
# DSR/PBO/min-trades), each cell is judged BRUT on its OWN data (no pooling/sibling-deflation), pure + offline +
# deterministic. The authority signal injected here is a PIPELINE-PROOF synthetic — REAL authority data does not
# exist in prod (the voice panel has never been populated; `provider='social_authority'` has ZERO alt_data rows),
# so a survivor on the synthetic carrier proves only that the PLUMBING is live, NEVER a real edge.

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.backtest import metrics_for_run, run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.master.cohort import Candidate, promote_brut
from cosmu.master.scorer import GateSettings
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import (
    Condition,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)
from cosmu.strategy.static_check import validate_spec

# The registered PIT feature this whole lane exists to test (config/feature_registry.py). It is a COHORT-COMPUTED
# feature (cosmu.mind.authority.AuthorityProvider), so the backtest reads it from the caller's `alt_by_symbol`
# join keyed by bar.ts.isoformat() — exactly the path the finder uses for funding/sentiment.
AUTHORITY_FEATURE = "authority_weighted_claim_signal"

# The synthetic-carrier min-trades floor — the SAME 30-trade pre-paper floor the finder/placebo panel apply per
# brut cell (a cell that trades < 30 is not Gate-eligible; the floor is read, never weakened).
BRUT_MIN_TRADES = 30


# --------------------------------------------------------------------------- the typed specs (entry on authority)


def _spec(
    name: str,
    rationale: str,
    *,
    op: str,
    direction: int,
    thresh_lo: float,
    thresh_hi: float,
    bar_size: str = "1h",
) -> StrategySpec:
    """One authority-entry indicator spec. The entry is a single Condition on AUTHORITY_FEATURE vs a fitted
    threshold (a ParamRef — no magic number); `direction` flips long/short. Exit is a fixed-fraction stop/take +
    a time stop (all ParamRefs). lane='explore' (a low-confidence VIBE — NOT a strict-gate claim), strategy_kind
    stays 'indicator' because the authority signal is an alt-data CONDITION on the price path, not a discrete
    MarketEvent trigger (the event lane is for typed market_events; this feature is a continuous PIT series)."""
    return StrategySpec(
        name=name,
        rationale=rationale,
        strategy_kind="indicator",
        lane="explore",
        universe=UniverseSelector(
            venues=["binance"],
            asset_classes=["crypto"],
            min_liquidity_usd=1_000_000,
            min_instruments=5,
        ),
        horizon=Horizon(bar_size=bar_size, min_hold_days=1, max_hold_days=10),
        catalyst="credibility-weighted directional consensus of high-authority voices turning before it is priced",
        entry=[
            Condition(
                feature=FeatureRef(name=AUTHORITY_FEATURE),
                op=op,  # type: ignore[arg-type]
                threshold=ParamRef(param="auth_thresh"),
            )
        ],
        exit={
            "stop_loss": ParamRef(param="stop"),
            "take_profit": ParamRef(param="take"),
            "time_stop_days": ParamRef(param="time_stop"),
        },  # type: ignore[arg-type]
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=1.0, conviction=1.0),
        param_space={
            "auth_thresh": ParamSpace(kind="float", lo=thresh_lo, hi=thresh_hi, step=0.05),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1, step=0.01),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.2, step=0.01),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
        },
        direction=direction,  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class VoiceSpec:
    """A typed authority-entry spec + the FIXED config it is scored on (ONE honest config per spec — a sweep would
    just be a denser null; the per-combo trial deflation rides on trials=1 here)."""

    spec: StrategySpec
    params: dict[str, float]


def voice_authority_specs() -> list[VoiceSpec]:
    """The ~7 deterministic authority-entry specs: long/short × cross vs level × a couple horizons. Each is a
    distinct, falsifiable hypothesis over the SAME registered feature. The same list every call (pure authoring)."""
    out: list[VoiceSpec] = []
    # 1. LONG when authority consensus crosses up through a positive floor (credible voices turn bullish).
    out.append(VoiceSpec(
        _spec("Voice authority long cross-up (1h)",
              "Enter LONG when the credibility-weighted directional consensus crosses UP through a positive "
              "threshold — high-authority voices turning bullish before it is priced. Disconfirmer: if the signal "
              "carries no foresight the entries are random w.r.t. forward returns and the Gate rejects.",
              op="cross_up", direction=1, thresh_lo=0.1, thresh_hi=0.6),
        {"auth_thresh": 0.30, "stop": 0.05, "take": 0.10, "time_stop": 5}))
    # 2. LONG on a high POSITIVE LEVEL (strong standing bullish consensus, not just the crossing event).
    out.append(VoiceSpec(
        _spec("Voice authority long level (1h)",
              "Enter LONG while the authority-weighted consensus sits above a high positive level — a sustained "
              "credible-bull regime. Disconfirmer: a persistent level with no edge over buy-and-hold is rejected.",
              op="gt", direction=1, thresh_lo=0.2, thresh_hi=0.7),
        {"auth_thresh": 0.40, "stop": 0.05, "take": 0.12, "time_stop": 7}))
    # 3. SHORT when authority consensus crosses DOWN through a negative threshold (credible voices turn bearish).
    out.append(VoiceSpec(
        _spec("Voice authority short cross-down (1h)",
              "Enter SHORT when the consensus crosses DOWN through a negative threshold — credible voices turning "
              "bearish first. Disconfirmer: no lead → entries uncorrelated with forward drawdowns → Gate rejects.",
              op="cross_down", direction=-1, thresh_lo=-0.6, thresh_hi=-0.1),
        {"auth_thresh": -0.30, "stop": 0.05, "take": 0.10, "time_stop": 5}))
    # 4. SHORT on a low NEGATIVE LEVEL (sustained credible-bear regime).
    out.append(VoiceSpec(
        _spec("Voice authority short level (1h)",
              "Enter SHORT while the consensus sits below a low negative level — a sustained credible-bear regime.",
              op="lt", direction=-1, thresh_lo=-0.7, thresh_hi=-0.2),
        {"auth_thresh": -0.40, "stop": 0.05, "take": 0.12, "time_stop": 7}))
    # 5. LONG cross-up, SLOWER 4h horizon (the lead-lag may live on a slower clock).
    out.append(VoiceSpec(
        _spec("Voice authority long cross-up (4h)",
              "The cross-up bullish thesis on a SLOWER 4h clock — the credibility lead may be a multi-day swing, "
              "not an hourly scalp. Disconfirmer: if the edge is purely look-ahead it dies on the honest PIT join.",
              op="cross_up", direction=1, thresh_lo=0.1, thresh_hi=0.6, bar_size="4h"),
        {"auth_thresh": 0.30, "stop": 0.06, "take": 0.14, "time_stop": 8}))
    # 6. LONG on a MILD positive level (looser threshold → more trades → tests the trade-count / min-trades axis).
    out.append(VoiceSpec(
        _spec("Voice authority long mild level (1h)",
              "Enter LONG on any MILD positive consensus — a looser threshold trading more often, probing whether "
              "even weak credible bullishness leads. Disconfirmer: more trades of pure noise still must not clear.",
              op="gt", direction=1, thresh_lo=0.0, thresh_hi=0.4),
        {"auth_thresh": 0.10, "stop": 0.04, "take": 0.10, "time_stop": 4}))
    # 7. SHORT cross-down, SLOWER 4h horizon.
    out.append(VoiceSpec(
        _spec("Voice authority short cross-down (4h)",
              "The cross-down bearish thesis on a 4h clock — credible bearish turns ahead of multi-day drawdowns.",
              op="cross_down", direction=-1, thresh_lo=-0.6, thresh_hi=-0.1, bar_size="4h"),
        {"auth_thresh": -0.30, "stop": 0.06, "take": 0.14, "time_stop": 8}))
    return out


# --------------------------------------------------------------------------- synthetic authority injection (PIT)


# How many bars ahead the 'strong_lead' carrier looks when it leads the FORWARD-HOLD return (so the lead lines up
# with a multi-bar hold, not just the next bar). Kept small; it is an OPENLY-LABELLED look-ahead for plumbing only.
_LEAD_HORIZON_BARS = 24


def inject_synthetic_authority(
    market: dict[str, list[Bar]],
    *,
    seed: int,
    regime: str = "null",
) -> dict[str, dict[str, dict[str, float]]]:
    """Build the `alt_by_symbol` PIT join carrying a SYNTHETIC `authority_weighted_claim_signal` per bar — the
    SAME shape the finder's real alt-join produces (symbol → feature → {bar.ts.isoformat(): value}). The value sits
    in [-1, +1] like the real authority signal.

    PIPELINE-PROOF ONLY — there is NO real authority data in prod, so this synthetic carrier exists purely to drive
    the wire end-to-end. Three regimes:
      * 'null' (DEFAULT): pure noise in [-1, 1], independent of returns — an honest Gate must reject every cell
        (a pass under the permutation-null market would be a CAUGHT LEAK).
      * 'leading': the NEXT bar's signed return + modest noise (a realistic, imperfect one-bar lead). It SHIFTS the
        DSR (the wire reacts to signal content) but a one-bar lead rarely survives a multi-day hold + fees.
      * 'strong_lead': the signed FORWARD-HOLD return over `_LEAD_HORIZON_BARS` with LOW noise — a deliberate,
        clearly-labelled look-ahead aligned to the hold so a spec CAN reach a Gate PASS. This proves the verdict
        path is fully connected; it is NOT, in any way, a claim of edge.
    Deterministic for a fixed (market, seed, regime); pure-Python."""
    if regime not in ("null", "leading", "strong_lead"):
        raise ValueError(f"regime must be 'null'|'leading'|'strong_lead', got {regime!r}")
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sym, bars in market.items():
        rng = random.Random(f"voice-auth-{seed}-{sym}-{regime}")
        series: dict[str, float] = {}
        closes = [float(b.close) for b in bars]
        n = len(bars)
        for i, b in enumerate(bars):
            if regime == "leading" and i + 1 < n and closes[i] > 0:
                fwd = closes[i + 1] / closes[i] - 1.0
                val = math.tanh(40.0 * fwd) + rng.gauss(0.0, 0.25)
            elif regime == "strong_lead" and i + _LEAD_HORIZON_BARS < n and closes[i] > 0:
                fwd = closes[i + _LEAD_HORIZON_BARS] / closes[i] - 1.0
                # signed forward-hold return with LOW noise → a clean, openly-injected look-ahead carrier.
                val = math.tanh(60.0 * fwd) + rng.gauss(0.0, 0.05)
            else:
                val = rng.uniform(-1.0, 1.0)
            series[b.ts.isoformat()] = max(-1.0, min(1.0, val))
        out[sym] = {AUTHORITY_FEATURE: series}
    return out


# --------------------------------------------------------------------------- the plumbing-PASS demo market


def moderate_trend_market(*, seed: int = 2, n: int = 1400, drift: float = 0.0008) -> dict[str, list[Bar]]:
    """A deterministic MODERATE-trend market for the 'strong_lead' plumbing-PASS demo. Unlike the explosive
    edge_bearing_screen_market (per-fold returns so large the PBO proxy saturates), this carries a MILD positively
    autocorrelated trend so a hold-aligned look-ahead carrier can clear ALL the Gate's locked legs at once — DSR ≥
    0.95, PBO < 0.50, ≥ 30 trades, and beats buy-and-hold — proving the verdict path is fully connected to a PASS.
    The default seed (2) is the one where the 'mild level' spec clears cleanly (empty reasons) — pinned so the
    plumbing-PASS demo is reproducible. PIPELINE-PROOF ONLY: real authority data does not exist; this is a plumbing
    fixture, not an edge. Daily bars on the same 5 entity-mapped symbols the voices lane routes (ENTITY_BARS_SYMBOL)."""
    rng = random.Random(f"voice-mod-{seed}")
    start = datetime(2021, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 100.0
    trend = 0.0
    for i in range(n):
        d = drift if i % 90 < 60 else -drift * 0.6  # ~2/3 mild bull, 1/3 shallow pullback — net up, regime breadth
        ret = d + 0.12 * trend + rng.gauss(0, 0.011)  # mild momentum: returns positively autocorrelated
        trend = ret
        o = price
        price = max(0.01, price * (1 + ret))
        bars.append(Bar(
            ts=start + timedelta(days=i),
            open=Decimal(str(round(o, 6))),
            high=Decimal(str(round(max(o, price) * 1.002, 6))),
            low=Decimal(str(round(min(o, price) * 0.998, 6))),
            close=Decimal(str(round(price, 6))),
            volume=Decimal("5000000"),
        ))
    return {sym: bars for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")}


# --------------------------------------------------------------------------- the panel run (finder→Gate, per cell)


@dataclass(frozen=True)
class VoiceAuthorityCell:
    """One cell (one authority spec × one symbol) scored on the EXACT finder→Gate BRUT path. `cleared=True` means
    promote_brut PROMOTED it (cleared the LOCKED stats gate on its own streams + the min-trades floor)."""

    spec_name: str
    symbol: str
    direction: int
    dsr: float
    pbo: float
    trades: int
    net_return: float
    cleared: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VoiceAuthorityPanel:
    """The end-to-end result. `regime` ∈ {'null','leading','strong_lead'} labels which synthetic carrier drove it.
    `any_cleared` is the headline: under 'null' a True is a CAUGHT LEAK (report loudly); under 'strong_lead' a True
    proves the WIRE is live (a spec CAN enter on authority → backtest → reach a Gate PASS). `wire_fired` is True iff
    at least one cell actually traded (>0 trades) — the minimal proof the feature reached the entry path at all."""

    regime: str
    cells: list[VoiceAuthorityCell]
    gate_dsr_floor: float
    n_specs: int
    n_cells: int

    @property
    def total_trades(self) -> int:
        return sum(c.trades for c in self.cells)

    @property
    def wire_fired(self) -> bool:
        return self.total_trades > 0

    @property
    def any_cleared(self) -> bool:
        return any(c.cleared for c in self.cells)


def run_voice_authority_panel(
    *,
    market: dict[str, list[Bar]],
    regime: str = "null",
    gates: GateSettings | None = None,
    venue_id: str = "binance",
    seed: int = 7,
) -> VoiceAuthorityPanel:
    """Score every authority-entry spec on the EXACT finder→Gate BRUT path, injecting the synthetic authority
    carrier through `alt_by_symbol` (the same PIT join the finder feeds funding/sentiment through). `regime`
    selects the carrier: 'null' (pure noise — Gate must reject), 'leading' (a labelled one-bar forward lead), or
    'strong_lead' (a labelled forward-hold look-ahead that proves a PASS is reachable end-to-end). The Gate is
    UNTOUCHED: run_strategy_backtest_detailed (real fees/slippage, include_holdout=False — the screen path) →
    metrics_for_run (each cell's OWN streams, trials=1) → promote_brut (the LOCKED DSR/PBO/min-trades gate,
    TrialStats(count=1), the SAME min_trades floor the finder uses)."""
    if regime not in ("null", "leading", "strong_lead"):
        raise ValueError(f"regime must be 'null'|'leading'|'strong_lead', got {regime!r}")
    gates = gates or Settings(openrouter_api_key=None).gates
    venue = default_catalog().venue(venue_id)

    cells: list[VoiceAuthorityCell] = []
    specs = voice_authority_specs()
    for vs in specs:
        alt = inject_synthetic_authority(market, seed=seed, regime=regime)
        detailed = run_strategy_backtest_detailed(
            vs.spec,
            vs.params,
            market,
            fee_bps=venue.taker_fee_bps,
            slippage_bps=venue.slippage_bps,
            impact_bps=venue.impact_bps,
            alt_by_symbol=alt,
            include_holdout=False,
        )
        candidates: list[Candidate] = []
        metric_by_sym = {}
        for sym, run in detailed.per_symbol_runs.items():
            m = metrics_for_run(
                run, trials=1, buy_and_hold=detailed.per_symbol_buy_and_hold.get(sym, 0.0)
            )
            metric_by_sym[sym] = (m, run)
            candidates.append(Candidate(id=sym, metrics=m, net_profit=run.total_return, source="voice_authority"))
        proms = {p.candidate_id: p for p in promote_brut(candidates, gates, min_trades=BRUT_MIN_TRADES)}
        for sym, (m, run) in metric_by_sym.items():
            p = proms[sym]
            cells.append(VoiceAuthorityCell(
                spec_name=vs.spec.name,
                symbol=sym,
                direction=vs.spec.direction,
                dsr=round(p.deflated_sharpe_prob, 6),
                pbo=round(float(m.pbo), 6),
                trades=m.num_trades,
                net_return=round(run.total_return, 6),
                cleared=p.promoted,
                reasons=list(p.reasons),
            ))
    return VoiceAuthorityPanel(
        regime=regime,
        cells=cells,
        gate_dsr_floor=float(gates.min_deflated_sharpe_prob),
        n_specs=len(specs),
        n_cells=len(cells),
    )


def validate_all_specs() -> dict[str, list[str]]:
    """Run every authored spec through the real `validate_spec` — proves the specs are LEGAL (the authority feature
    is registered, no magic numbers, valid horizon/universe). Returns spec_name → issues ([] == valid)."""
    return {vs.spec.name: validate_spec(vs.spec) for vs in voice_authority_specs()}


def _summary_line(panel: VoiceAuthorityPanel) -> str:
    cleared = sum(1 for c in panel.cells if c.cleared)
    dsrs = [c.dsr for c in panel.cells]
    med_dsr = round(statistics.median(dsrs), 4) if dsrs else 0.0
    return (
        f"regime={panel.regime} specs={panel.n_specs} cells={panel.n_cells} "
        f"trades={panel.total_trades} wire_fired={panel.wire_fired} "
        f"cleared={cleared}/{panel.n_cells} median_dsr={med_dsr} floor={panel.gate_dsr_floor}"
    )


def _main(argv: list[str] | None = None) -> int:
    """CLI: validate the specs, then run BOTH regimes on the keyless permutation-null market (the M2 is
    geo-blocked, so no live bars) and print the end-to-end verdict. Read-only; never moves money."""
    import argparse

    from cosmu.research.fixtures import permutation_null_market

    argparse.ArgumentParser(description="Voice-authority specs → BRUT Gate POC (synthetic carrier, $0).").parse_args(argv)

    issues = validate_all_specs()
    bad = {k: v for k, v in issues.items() if v}
    print(f"VALIDATE — {len(issues)} specs, {len(bad)} invalid")
    for name, iss in bad.items():
        print(f"  INVALID {name}: {iss}")

    # NULL + LEADING run on the permutation-NULL market (no exploitable return structure): the leak check — even a
    # one-bar lead must NOT clear. STRONG_LEAD runs on the MODERATE-trend market (real positive return
    # autocorrelation) where a hold-aligned look-ahead carrier CAN clear ALL the Gate's legs — the plumbing-PASS demo.
    null_market = permutation_null_market(n=600, seed=13)
    demo_market = moderate_trend_market()
    for regime, market in (("null", null_market), ("leading", null_market), ("strong_lead", demo_market)):
        panel = run_voice_authority_panel(market=market, regime=regime)
        print(f"{regime.upper():<12}", _summary_line(panel))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
