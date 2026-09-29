# intent: the NEGATIVE-CONTROL EMPIRICAL-NULL PANEL — the Gate's self-validation instrument (cross-disciplinary
# playbook bridge #1, from pharmaco-epidemiology / GWAS, Schuemie-OHDSI). It turns the #1 UNMEASURABLE fear —
# leakage UPSTREAM of the Gate, which the Gate structurally cannot see (it validates edge-after-costs, NOT pipeline
# honesty) — into a CONTINUOUSLY-MONITORED instrument: run PLACEBO specs (pure noise / time-shuffled real signals)
# through the EXACT finder→Gate per-combo BRUT path and MEASURE where they land. A real survivor is only credible
# if it sits in the RIGHT TAIL of this empirically-measured null. The CRITICAL CHECK: if ANY placebo CLEARS the
# Gate, the null is miscalibrated — that is a CAUGHT LEAK, reported LOUDLY (never a test to weaken). At rho≈0 the
# placebo DSR/PBO distribution IS the Gate's empirical null; the Gate constant 0.95 should sit far in its right tail.
#
# TWO placebo families (the playbook's exact prescription), both keyless + deterministic + offline:
#   (a) TIME-SHUFFLED real signal — take a REAL leading signal (each symbol's lagged momentum z-score) and PERMUTE
#       its values in time (break the time-alignment, keep the marginal distribution). The IC of a shuffled signal
#       COLLAPSES (the disconfirmers.shuffle_null property), so an honest Gate must reject it. This is the SAME
#       null the leakage_tripwire / disconfirmers apply to ONE feature's IC — lifted up to the whole finder→Gate.
#   (b) RANDOM-ENTRY matched-turnover — inject a pure-uniform-noise signal and pick the entry threshold so the
#       firing rate (turnover) MATCHES a real strategy's, so the placebo trades ENOUGH to be Gate-eligible (clears
#       the 30-trade floor) and TEMPTS the Gate by chance — the regime where an in-sample-overfit leak would bite.
#
# It runs the IDENTICAL scoring path the finder runs PER CELL: run_strategy_backtest_detailed (the real backtest,
# real fees/slippage) → metrics_for_run (each cell's OWN bar_returns + fold_returns, per-combo trial deflation) →
# promote_brut (the LOCKED DSR/PBO/min-trades/holdout gate, TrialStats(count=1)). The placebo signal is injected
# through the SAME `alt_by_symbol` point-in-time join the finder feeds funding/sentiment through — so the ONLY
# thing that differs from a real finder cell is the SIGNAL CONTENT (placebo), never the gate, never the costs.
# This VALIDATES the Gate; it LOOSENS NOTHING (the locked constants are read, never written). PROPOSE-ONLY +
# PURE: no DB, no network, no LLM, no money path. Keyless (the M2 is geo-blocked) — uses the repo's offline null
# market fixture, so the panel can RIDE EVERY COHORT later at near-zero cost (the standing instrument).
#
# Entry points:
#   placebo_specs()                         -> the ~10 deterministic placebo StrategySpecs (5 shuffled, 5 random)
#   run_placebo_panel(market=..., gates=...) -> PlaceboPanel (the measured null + did-any-clear verdict)
#   compare_survivor_to_null(dsr, panel)    -> SurvivorVsNull (where a real survivor's DSR sits in the null tail)
#   python -m cosmu.research.placebo_panel  -> run the panel OFFLINE on the keyless null market + print the report

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.backtest import metrics_for_run, run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.master.cohort import Candidate, promote_brut
from cosmu.master.scorer import BacktestMetrics
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)

# The registered alt-feature name we CARRY placebo values under. A placebo spec must compile (the strategy
# static-check validates feature names against the registry), so we reuse a REAL registered feature as the
# carrier and inject PLACEBO VALUES under it through the same `alt_by_symbol` PIT join the finder uses. The
# entry plumbing is byte-identical to a real funding/sentiment cell — only the signal CONTENT is placebo.
_CARRIER_FEATURE = "fear_greed"

# The per-cell min-trades floor the finder enforces (lab/finder._BRUT_MIN_TRADES). We pass the SAME floor to
# promote_brut so a placebo is judged on the EXACT gate the finder applies per cell — a placebo that trades < 30
# of its own trades is killed on `min_trades` exactly as a real thin cell would be (never a placebo-only rule).
_BRUT_MIN_TRADES = 30

# How many placebo specs of EACH family. 5 + 5 = the playbook's "~10 negative-control specs". Bounded on purpose
# (16GB M2): this is a small VALIDATION run, not a sweep — each spec is one config × a handful of keyless symbols.
_N_PER_FAMILY = 5


# --------------------------------------------------------------------------- placebo spec authoring (deterministic)


def _placebo_spec(name: str, rationale: str, *, thresh_lo: float, thresh_hi: float) -> StrategySpec:
    """One placebo StrategySpec: a single entry condition on the CARRIER feature (which we inject placebo values
    under), a plain stop/take/time-stop exit. Spot, long-only crypto. Every threshold lives in param_space (no
    magic numbers) exactly like a real seed. The thresh range differs per spec so the family is DISTINCT configs,
    not param-duplicates of one spec — a real negative-control panel, not a correlated grid."""
    return StrategySpec(
        name=name,
        rationale=rationale,
        universe=UniverseSelector(
            venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5
        ),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=10),
        entry=[Condition(feature=FeatureRef(name=_CARRIER_FEATURE), op="gt", threshold=ParamRef(param="thresh"))],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
        ),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.03, conviction=0.5),
        param_space={
            "thresh": ParamSpace(kind="float", lo=thresh_lo, hi=thresh_hi),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "take": ParamSpace(kind="float", lo=0.03, hi=0.18),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
        },
    )


@dataclass(frozen=True)
class PlaceboSpec:
    """A placebo spec + its family + the concrete params + the per-bar firing threshold. `family` is
    'time_shuffled' (a real signal with its time-alignment broken) or 'random_entry' (pure uniform noise sized
    to a target turnover). `params` are FIXED (we score ONE config per placebo, not a grid — a sweep would just
    be a denser null; one honest config per negative control is the instrument)."""

    spec: StrategySpec
    family: str
    params: dict[str, float]
    target_turnover: float  # the fraction of bars the entry signal is designed to fire on (random_entry only)


def placebo_specs(*, n_per_family: int = _N_PER_FAMILY) -> list[PlaceboSpec]:
    """The ~10 deterministic placebo specs: `n_per_family` TIME-SHUFFLED + `n_per_family` RANDOM-ENTRY.

    Each is a distinct config (its own threshold + turnover) so the panel measures a SPREAD of placebo outcomes,
    not one point. Deterministic — the same list every call (the authoring is pure; the placebo VALUES are seeded
    per run in `_inject_*`). The shuffled-signal family carries a real-marginal signal whose ALIGNMENT is broken;
    the random-entry family carries pure noise tuned to fire on `target_turnover` of the bars (so it clears the
    30-trade floor and tempts the gate by chance — the leak-zone regime)."""
    specs: list[PlaceboSpec] = []
    # (a) TIME-SHUFFLED real signal — the carrier holds a z-score-like series in [0, 1]; the threshold band sets
    # how selective the (shuffled) entry is. Different thresholds → different turnover → distinct configs.
    for i in range(n_per_family):
        thresh = 0.5 + 0.06 * i  # 0.50, 0.56, 0.62, 0.68, 0.74 — progressively more selective
        specs.append(
            PlaceboSpec(
                spec=_placebo_spec(
                    f"Placebo time-shuffled #{i + 1}",
                    "NEGATIVE CONTROL: a REAL leading signal (lagged momentum z-score) with its time-alignment "
                    "PERMUTED — marginal preserved, every signal→return relationship destroyed. An honest Gate "
                    "MUST reject it; if it clears, the null is miscalibrated (a caught leak).",
                    thresh_lo=0.4,
                    thresh_hi=0.9,
                ),
                family="time_shuffled",
                params={"thresh": round(thresh, 4), "stop": 0.05, "take": 0.1, "time_stop": 5 + i},
                target_turnover=0.0,  # set by the shuffled signal's threshold, not a turnover target
            )
        )
    # (b) RANDOM-ENTRY matched-turnover — pure uniform-noise carrier; the threshold is CHOSEN so the entry fires
    # on ~target_turnover of the bars. Turnovers span a real strategy's range (a fast scalp to a slow swing) so
    # the family covers the trade-count axis the gate's min-trades floor + DSR sample-size react to.
    for i in range(n_per_family):
        turnover = 0.20 + 0.10 * i  # 0.20, 0.30, 0.40, 0.50, 0.60 of bars fire (a uniform draw > (1 - turnover))
        thresh = round(1.0 - turnover, 4)  # uniform[0,1] > thresh fires with prob `turnover`
        specs.append(
            PlaceboSpec(
                spec=_placebo_spec(
                    f"Placebo random-entry #{i + 1}",
                    "NEGATIVE CONTROL: a PURE-NOISE entry signal (uniform draw) sized to a real strategy's "
                    "turnover, so it trades enough to be Gate-eligible and tempts the gate by chance — yet "
                    "carries NO edge. An honest Gate MUST reject it; a pass is a caught leak.",
                    thresh_lo=0.0,
                    thresh_hi=1.0,
                ),
                family="random_entry",
                params={"thresh": thresh, "stop": 0.05, "take": 0.1, "time_stop": 5},
                target_turnover=round(turnover, 4),
            )
        )
    return specs


def control_arm_specs(*, n_per_family: int = _N_PER_FAMILY) -> list[StrategySpec]:
    """Pure, no-DB helper the cohort placebo RIDER uses: the bare StrategySpec list of the negative-control
    ("placebo") arm — the same specs placebo_specs() carries, without the family/params/turnover envelope. These
    are the control arms the rider runs alongside every cohort: a real edge is only credible if these known-false
    controls do NOT clear the same Gate. Deterministic + side-effect-free (no store, no network, no LLM) so it is
    safe to call inside the best-effort rider. Distinct from control_feature_names() (which names the non-causal
    astro/weather FEATURES) — this returns the placebo STRATEGY specs."""
    return [ps.spec for ps in placebo_specs(n_per_family=n_per_family)]


# --------------------------------------------------------------------------- placebo signal injection (PIT, seeded)


def _lagged_momentum_z(bars: list[Bar], lookback: int = 20) -> list[float | None]:
    """A REAL leading signal per bar: the z-score of the lagged `lookback`-bar return, mapped to [0, 1] via a
    logistic squash so it sits in the carrier feature's natural range. Lagged (uses bars STRICTLY before the
    bar) so it is point-in-time honest BEFORE we shuffle it — the shuffle is what breaks the alignment, not a
    look-ahead. None during warm-up. Pure + deterministic from the bars."""
    closes = [float(b.close) for b in bars]
    rets: list[float | None] = [None] * len(bars)
    for i in range(lookback + 1, len(bars)):
        prev = closes[i - 1 - lookback]
        rets[i] = (closes[i - 1] / prev - 1.0) if prev > 0 else None
    # z-score the available returns, then squash to [0, 1]
    vals = [r for r in rets if r is not None]
    if len(vals) < 2:
        return [None] * len(bars)
    mu = statistics.fmean(vals)
    sd = statistics.pstdev(vals) or 1.0
    out: list[float | None] = []
    for r in rets:
        if r is None:
            out.append(None)
        else:
            z = (r - mu) / sd
            out.append(1.0 / (1.0 + pow(2.718281828, -z)))  # logistic squash → (0, 1)
    return out


def inject_time_shuffled(market: dict[str, list[Bar]], *, seed: int) -> dict[str, dict[str, dict[str, float]]]:
    """Build the `alt_by_symbol` join for the TIME-SHUFFLED family: a REAL lagged-momentum-z signal whose VALUES
    are PERMUTED in time per symbol (independent permutations). The marginal distribution is preserved exactly;
    every temporal alignment to forward returns is destroyed — the shuffle null. Keyed by bar.ts.isoformat()
    under the carrier feature, the SAME shape the finder's alt-join produces. Deterministic for a fixed seed."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sym, bars in market.items():
        signal = _lagged_momentum_z(bars)
        # collect (ts, value) where the signal is defined, then PERMUTE the values across those bars
        defined = [(b.ts.isoformat(), v) for b, v in zip(bars, signal, strict=True) if v is not None]
        values = [v for _ts, v in defined]
        rng = random.Random(f"placebo-shuffle-{seed}-{sym}")  # str seed is process-stable
        rng.shuffle(values)
        series = {ts: val for (ts, _v), val in zip(defined, values, strict=True)}
        out[sym] = {_CARRIER_FEATURE: series}
    return out


def inject_random_entry(market: dict[str, list[Bar]], *, seed: int) -> dict[str, dict[str, dict[str, float]]]:
    """Build the `alt_by_symbol` join for the RANDOM-ENTRY family: a pure uniform[0, 1] draw per bar per symbol,
    keyed by bar.ts.isoformat() under the carrier feature. The spec's threshold (1 - target_turnover) then makes
    the entry fire on ~target_turnover of the bars — pure noise, no return relationship. Deterministic per seed."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sym, bars in market.items():
        rng = random.Random(f"placebo-random-{seed}-{sym}")
        out[sym] = {_CARRIER_FEATURE: {b.ts.isoformat(): rng.random() for b in bars}}
    return out


# --------------------------------------------------------------------------- the panel run (finder→Gate, per cell)


@dataclass(frozen=True)
class PlaceboCell:
    """One placebo CELL (one placebo spec × one symbol), scored on the EXACT finder→Gate BRUT path. `dsr` is its
    deflated-Sharpe probability (the gate's ranking scalar); `pbo` its overfit proxy; `cleared` is whether
    promote_brut PROMOTED it (== it cleared the LOCKED stats gate on its own streams AND the min-trades floor).
    `cleared=True` for ANY placebo cell is a CAUGHT LEAK."""

    spec_name: str
    family: str
    symbol: str
    dsr: float
    pbo: float
    trades: int
    cleared: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlaceboPanel:
    """The measured empirical null + the did-any-placebo-clear verdict. `cells` is every placebo cell scored;
    the DSR/PBO summaries describe the null DISTRIBUTION; `any_cleared` is the CRITICAL CHECK — True means a
    placebo passed the Gate, i.e. an upstream leak the Gate cannot see is present (report LOUDLY). The gate
    constant `gate_dsr_floor` is carried so a reader can see the floor (0.95) against the measured null tail."""

    cells: list[PlaceboCell]
    gate_dsr_floor: float
    n_specs: int
    n_cells: int
    # null DSR distribution (across ALL placebo cells)
    dsr_mean: float
    dsr_p50: float
    dsr_p95: float
    dsr_max: float
    # null PBO distribution
    pbo_mean: float
    pbo_p50: float
    pbo_min: float
    any_cleared: bool
    cleared_cells: list[PlaceboCell] = field(default_factory=list)

    @property
    def null_dsrs(self) -> list[float]:
        return [c.dsr for c in self.cells]

    def render(self) -> str:
        """A human-readable multi-line report (the CLI body + the cohort-rider log line)."""
        verdict = "LEAK CAUGHT" if self.any_cleared else "CLEAN"
        lines = [
            f"PLACEBO NULL PANEL — {verdict}  "
            f"({self.n_specs} placebo specs, {self.n_cells} cells, gate floor DSR>{self.gate_dsr_floor})",
            f"  measured null DSR: mean={self.dsr_mean:.4f} p50={self.dsr_p50:.4f} "
            f"p95={self.dsr_p95:.4f} MAX={self.dsr_max:.4f}",
            f"  measured null PBO: mean={self.pbo_mean:.4f} p50={self.pbo_p50:.4f} min={self.pbo_min:.4f}",
            f"  gate DSR floor {self.gate_dsr_floor} sits at the "
            f"{self._floor_percentile():.1f}th percentile of the placebo null "
            f"(headroom over null MAX = {self.gate_dsr_floor - self.dsr_max:+.4f})",
        ]
        if self.any_cleared:
            lines.append(f"  *** {len(self.cleared_cells)} PLACEBO CELL(S) CLEARED THE GATE — UPSTREAM LEAK ***")
            for c in self.cleared_cells:
                lines.append(f"      LEAK: {c.spec_name} · {c.symbol} · DSR={c.dsr:.4f} · trades={c.trades}")
        else:
            lines.append("  -> no placebo cleared the Gate: the null is calibrated, the Gate is leak-free here.")
        return "\n".join(lines)

    def _floor_percentile(self) -> float:
        """Where the gate DSR floor sits among the placebo cells' DSRs (100.0 = above every placebo)."""
        dsrs = self.null_dsrs
        if not dsrs:
            return 100.0
        below = sum(1 for d in dsrs if d < self.gate_dsr_floor)
        return 100.0 * below / len(dsrs)


def _summ(values: list[float], q: float) -> float:
    """The q-quantile of `values` (nearest-rank), 0.0 for an empty list. Pure, dependency-free."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def run_placebo_panel(
    *,
    market: dict[str, list[Bar]],
    gates: GateSettings | None = None,
    venue_id: str = "binance",
    seed: int = 7,
    n_per_family: int = _N_PER_FAMILY,
) -> PlaceboPanel:
    """Run the negative-control panel: score EVERY placebo cell on the EXACT finder→Gate BRUT path and measure
    the resulting DSR/PBO null + the did-any-clear verdict.

    For each placebo spec, the placebo SIGNAL is injected through `alt_by_symbol` (the same PIT join the finder
    feeds funding/sentiment through), then run_strategy_backtest_detailed produces each symbol's OWN validation
    run, metrics_for_run builds that cell's BacktestMetrics (own bar_returns + fold_returns, per-combo trial
    deflation — trials=1 here since we score ONE config per placebo), and promote_brut applies the LOCKED gate
    (DSR/PBO/min-trades, TrialStats(count=1), the same min_trades floor the finder uses). NOTHING about the gate
    is altered — only the signal content is placebo. Deterministic for a fixed (market, seed). Pure + offline."""
    gates = gates or Settings(openrouter_api_key=None).gates
    venue = default_catalog().venue(venue_id)
    placebos = placebo_specs(n_per_family=n_per_family)

    cells: list[PlaceboCell] = []
    for ps in placebos:
        if ps.family == "time_shuffled":
            alt = inject_time_shuffled(market, seed=seed)
        else:
            alt = inject_random_entry(market, seed=seed)
        # The SAME backtest the finder runs per variant (real fees/slippage), include_holdout=False (the screen
        # path — the brut gate scores validation evidence; the placebo never needs the one-shot champion holdout).
        detailed = run_strategy_backtest_detailed(
            ps.spec,
            ps.params,
            market,
            fee_bps=venue.taker_fee_bps,
            slippage_bps=venue.slippage_bps,
            impact_bps=venue.impact_bps,
            alt_by_symbol=alt,
            include_holdout=False,
        )
        # Build one cell per symbol from its OWN run + score on the EXACT brut gate (trials=1: ONE config).
        cell_metrics: dict[str, BacktestMetrics] = {}
        for sym, run in detailed.per_symbol_runs.items():
            cell_metrics[sym] = metrics_for_run(
                run, trials=1, buy_and_hold=detailed.per_symbol_buy_and_hold.get(sym, 0.0)
            )
        candidates = [
            Candidate(id=sym, metrics=m, net_profit=0.0, source="placebo") for sym, m in cell_metrics.items()
        ]
        proms = {p.candidate_id: p for p in promote_brut(candidates, gates, min_trades=_BRUT_MIN_TRADES)}
        for sym, m in cell_metrics.items():
            p = proms[sym]
            cells.append(
                PlaceboCell(
                    spec_name=ps.spec.name,
                    family=ps.family,
                    symbol=sym,
                    dsr=round(p.deflated_sharpe_prob, 6),
                    pbo=round(float(m.pbo), 6),
                    trades=m.num_trades,
                    cleared=p.promoted,
                    reasons=list(p.reasons),
                )
            )

    dsrs = [c.dsr for c in cells]
    pbos = [c.pbo for c in cells]
    cleared = [c for c in cells if c.cleared]
    gate_floor = float((gates).min_deflated_sharpe_prob)
    return PlaceboPanel(
        cells=cells,
        gate_dsr_floor=gate_floor,
        n_specs=len(placebos),
        n_cells=len(cells),
        dsr_mean=round(statistics.fmean(dsrs), 6) if dsrs else 0.0,
        dsr_p50=round(_summ(dsrs, 0.50), 6),
        dsr_p95=round(_summ(dsrs, 0.95), 6),
        dsr_max=round(max(dsrs), 6) if dsrs else 0.0,
        pbo_mean=round(statistics.fmean(pbos), 6) if pbos else 0.0,
        pbo_p50=round(_summ(pbos, 0.50), 6),
        pbo_min=round(min(pbos), 6) if pbos else 0.0,
        any_cleared=bool(cleared),
        cleared_cells=cleared,
    )


def placebo_inflation(panel: PlaceboPanel) -> float:
    """A CONTINUOUS genomic-inflation-factor-style read of how far the placebo null is inflated TOWARD the Gate —
    NOT the binary any_cleared flag. Under a well-calibrated Gate the placebo DSRs should cluster FAR BELOW the
    locked floor; the closer the null's central mass creeps to the floor, the more an upstream leak is bleeding
    into the finder→Gate path (the GWAS λ-inflation intuition: observed test statistics that ride HIGHER than the
    null expects).

    Defined as the median placebo DSR divided by the Gate DSR floor: λ = p50(placebo DSR) / gate_dsr_floor.
      * λ ≈ (a small fraction) — healthy: placebos sit well below the floor, the null is calibrated.
      * λ → 1 — the placebo mass is riding UP to the floor: an upstream leak inflating the null.
      * λ ≥ 1 — the median placebo already clears the floor: a gross leak (any_cleared is almost surely True too).
    Monotone in injected leak strength (a stronger baked-in leak lifts every placebo DSR → the median rises). Pure
    + dependency-free; reads only the panel (never a Gate constant). 0.0 for an empty panel."""
    floor = panel.gate_dsr_floor or 1.0
    return round(panel.dsr_p50 / floor, 6) if panel.n_cells else 0.0


# --------------------------------------------------------------------------- survivor-vs-null comparison


@dataclass(frozen=True)
class SurvivorVsNull:
    """Where a real survivor's DSR sits relative to the measured placebo null. `percentile` is the fraction of
    placebo cells the survivor's DSR exceeds (100.0 = above EVERY placebo); `empirical_p` is the add-one
    corrected P(a placebo's DSR >= the survivor's) — the survivor's credibility AGAINST the measured null (low
    is good); `right_tail` is whether the survivor clears the empirical-null p95 AND the gate floor."""

    survivor_dsr: float
    null_p95: float
    null_max: float
    percentile: float
    empirical_p: float
    beats_null_max: bool
    right_tail: bool

    def render(self) -> str:
        verdict = "RIGHT-TAIL (credible vs the empirical null)" if self.right_tail else "INSIDE the null band"
        return (
            f"SURVIVOR vs PLACEBO NULL — {verdict}\n"
            f"  survivor DSR={self.survivor_dsr:.4f}  (null p95={self.null_p95:.4f}, null MAX={self.null_max:.4f})\n"
            f"  survivor sits at the {self.percentile:.1f}th percentile of the placebo null, "
            f"empirical p={self.empirical_p:.4f}  (beats null MAX: {self.beats_null_max})"
        )


def compare_survivor_to_null(survivor_dsr: float, panel: PlaceboPanel) -> SurvivorVsNull:
    """Place a real survivor's deflated-Sharpe against the measured placebo null. The survivor is credible only
    if its DSR sits in the RIGHT TAIL of the empirical null (above the placebo p95 AND above the locked gate
    floor) — replication's "the null is empirical, not assumed" lesson applied to the Gate's own output. Pure."""
    dsrs = panel.null_dsrs
    n = len(dsrs)
    p95 = panel.dsr_p95
    nmax = panel.dsr_max
    percentile = (100.0 * sum(1 for d in dsrs if d < survivor_dsr) / n) if n else 100.0
    ge = sum(1 for d in dsrs if d >= survivor_dsr)
    empirical_p = (1 + ge) / (1 + n) if n else 1.0
    return SurvivorVsNull(
        survivor_dsr=round(survivor_dsr, 6),
        null_p95=p95,
        null_max=nmax,
        percentile=round(percentile, 4),
        empirical_p=round(empirical_p, 6),
        beats_null_max=bool(survivor_dsr > nmax),
        right_tail=bool(survivor_dsr > p95 and survivor_dsr >= panel.gate_dsr_floor),
    )


__all__ = [
    "PlaceboCell",
    "PlaceboPanel",
    "PlaceboSpec",
    "SurvivorVsNull",
    "compare_survivor_to_null",
    "control_arm_specs",
    "inject_random_entry",
    "placebo_inflation",
    "inject_time_shuffled",
    "placebo_specs",
    "run_placebo_panel",
]


# --------------------------------------------------------------------------- CLI (offline; keyless; no DB/network)


def _offline_null_market(*, n: int = 600, seed: int = 11) -> dict[str, list[Bar]]:
    """The keyless offline market the panel runs on: the repo's permutation-null market (each symbol's returns
    permuted in time → no price-path signal either). Running the placebos on a NULL price path is the strictest
    negative control — there is no edge ANYWHERE (neither in the injected signal NOR the bars), so the only way
    a placebo could clear is a leak. Keyless + deterministic (the M2 is geo-blocked; no Binance fetch)."""
    from cosmu.research.fixtures import permutation_null_market

    return permutation_null_market(correlated=False, n=n, seed=seed)


def _main(argv: list[str] | None = None) -> int:
    """`python -m cosmu.research.placebo_panel` — run the negative-control panel OFFLINE on the keyless null
    market and print the measured null + the did-any-placebo-clear verdict. `--demo-survivor D` also prints
    where a hypothetical survivor with DSR=D would sit in the measured null (e.g. --demo-survivor 0.97). No
    network, no DB, no Binance — the harness is pure so the instrument runs anywhere.

    The real cohort-rider does NOT use the offline market: it passes the SAME real bars the finder screened (so
    the placebo null is measured on the SAME tape the real survivors were found on). The CLI is the offline
    demonstrator + the manual spot-check."""
    import argparse

    parser = argparse.ArgumentParser(description="Negative-control empirical-null placebo panel (Gate self-validation).")
    parser.add_argument("--n", type=int, default=600, help="bars per symbol in the offline null market")
    parser.add_argument("--seed", type=int, default=7, help="deterministic seed for placebo injection")
    parser.add_argument("--demo-survivor", type=float, default=None, help="also compare a hypothetical survivor DSR to the null")
    args = parser.parse_args(argv)

    market = _offline_null_market(n=args.n)
    panel = run_placebo_panel(market=market, seed=args.seed)
    print(panel.render())
    if args.demo_survivor is not None:
        print()
        print(compare_survivor_to_null(args.demo_survivor, panel).render())
    # exit non-zero iff a placebo cleared the Gate — so a CI/cron rider FAILS LOUDLY on a caught leak.
    return 1 if panel.any_cleared else 0


if __name__ == "__main__":
    raise SystemExit(_main())
