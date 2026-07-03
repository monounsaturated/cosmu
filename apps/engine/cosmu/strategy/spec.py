# intent: define the typed hypothesis format authored by the lab agent; inputs: validated LLM output; outputs: StrategySpec; invariants: no entry/exit magic numbers and final sizing remains with the deterministic master.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParamSpace(BaseModel):
    kind: Literal["int", "float", "choice"]
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    choices: list[float] | None = None


class ParamRef(BaseModel):
    param: str


class FeatureRef(BaseModel):
    name: str
    lookback: ParamRef | int | None = None


class Condition(BaseModel):
    feature: FeatureRef
    op: Literal["gt", "gte", "lt", "lte", "cross_up", "cross_down", "between"]
    threshold: ParamRef


class TakeProfitLeg(BaseModel):
    """One partial-exit leg of a multi-TP exit. `at` is the take-profit distance (a ParamRef, fit from the
    space — no magic numbers); `size_pct` is the FRACTION of the open position closed at this leg (also a
    ParamRef). Legs fill in ascending `at` order; the runner carries whatever fraction is left over."""

    at: ParamRef
    size_pct: ParamRef


class ExitPlan(BaseModel):
    """Composable, optimizer-fittable exit structure layered on top of the single stop/take. All thresholds are
    ParamRefs so the Finder/optimizer fits them — never hardcoded. None on a leaf => that behaviour is off."""

    # Partial exits: take profit in N legs (each a fraction of the position) instead of one all-or-nothing TP.
    multi_tp: list[TakeProfitLeg] = Field(default_factory=list)
    # Move the stop to break-even (entry) once the first TP leg has filled — frees the runner to ride risk-free.
    break_even_after_tp1: bool = False
    # The runner's trailing-stop distance once break-even is armed (asymmetric: tight stop, open-ended upside).
    runner_trail: ParamRef | None = None


class TrailingStop(BaseModel):
    """A STANDALONE top-level trailing stop — distinct from `ExitPlan.runner_trail` (which only arms AFTER the
    first multi-TP leg fills). This one trails the stop behind the favourable extreme from the moment it is
    armed: immediately at entry by default, or only once the trade is `arm_after_profit` in the money (a
    ParamRef profit fraction) so a fresh entry is not stopped out by ordinary noise before it has earned a
    cushion. `distance` is the trail distance as a fraction of the favourable extreme (a ParamRef — fit, never
    magic). It RAISES the fixed stop_loss only (max() for a long, min() for a short) — it never loosens it, so
    the worst-case stop is always the tighter of the fixed stop and the trail. None on ExitRules => off
    (byte-identical to specs without it). Composes with multi_tp/runner_trail: whichever stop is tighter in the
    favourable direction wins."""

    distance: ParamRef
    # Only start trailing once the position is this fraction in profit (favourable move from entry). None =>
    # arm immediately at entry. A ParamRef so the arm threshold is fit from the space like every other knob.
    arm_after_profit: ParamRef | None = None


class ExitRules(BaseModel):
    stop_loss: ParamRef
    take_profit: ParamRef
    signal_exits: list[Condition] = Field(default_factory=list)
    time_stop_days: ParamRef | None = None
    plan: ExitPlan | None = None
    # STANDALONE trailing stop (see TrailingStop) — armed at entry / after a profit cushion, independent of the
    # multi-TP runner. None => no top-level trailing stop (every existing spec is unchanged).
    trailing_stop: TrailingStop | None = None
    # ATR-multiple stop: when set, the initial stop distance is `atr_mult × ATR` (ATR as a fraction of price —
    # the `atr` registry feature) at the entry bar, INSTEAD of the fixed `stop_loss` fraction. A ParamRef so the
    # multiple is fit. None => the fixed `stop_loss` fraction is used (byte-identical to existing specs). When the
    # ATR feature is unavailable at the entry bar (warm-up / no data) the stop falls back to the fixed stop_loss
    # fraction — never an unprotected position.
    atr_mult: ParamRef | None = None
    # BINARY-CONTRACT RESOLUTION SETTLEMENT (prediction markets only). When True, a position still open when the
    # market resolves is settled at the AUTHORITATIVE $1/$0 payout (the YES share pays $1 if YES wins, $0 if NO
    # wins) instead of marking at the last odds quote. This is what makes the favorite-longshot / resolution-
    # dependent edge testable: the share's true P&L is defined BY resolution, not by odds drift before it. Only
    # the prediction backtest path honors it (it needs the per-conditionId resolution join from the alt store); a
    # price-asset backtest has no resolution and ignores the flag entirely. False (default) => the position marks
    # at the last bar's price like every other asset, so every existing spec is byte-identical. Pairs with the
    # intraday-reversion thesis being False (it exits BEFORE resolution) and the hold-to-resolution thesis True.
    settle_at_resolution: bool = False


class UniverseSelector(BaseModel):
    venues: list[str]
    asset_classes: list[Literal["crypto", "equity", "fx", "futures", "commodity", "prediction"]]
    min_liquidity_usd: float = 1_000_000
    min_instruments: int = 5


class Horizon(BaseModel):
    bar_size: Literal["1h", "4h", "1d"]
    min_hold_days: int
    max_hold_days: int
    # TIMEFRAME AS A 4th SCREEN AXIS (LOT C), OPT-IN. When None (DEFAULT) the single `bar_size` is the only timeframe
    # — so `timeframes()` returns [bar_size] and EVERY existing spec screens exactly once on its single bar_size, byte-
    # identical. When an author sets this list, the finder/loop screen the spec ONCE PER TIMEFRAME (model_copy'ing
    # bar_size per tf), making each (variant × symbol × venue × tf) its OWN brut cell. `bar_size` stays the canonical
    # single-tf value (the fallback + serialization anchor); `bar_sizes` only WIDENS the screen, never replaces it.
    bar_sizes: list[Literal["1h", "4h", "1d"]] | None = None

    def timeframes(self) -> list[str]:
        """The timeframe(s) to screen this spec on: `bar_sizes` when set (multi-tf opt-in), else just [bar_size] (the
        default → one screen, byte-identical to every existing spec). Deduped, order-preserving."""
        if not self.bar_sizes:
            return [self.bar_size]
        seen: dict[str, None] = {}
        for tf in self.bar_sizes:
            seen.setdefault(tf, None)
        return list(seen)


class RiskRules(BaseModel):
    # SANDBOX per-combo model (operator decision Q1 = "sandbox + global backstop"): a track is one wallet of
    # its allocated starting_capital and can NEVER lose more than that (master/risk enforces the per-combo
    # hard bound + kill). Sizing is the STRATEGY's own choice WITHIN its slice — an all-in mono-position spec
    # with a defined stop is legitimate — so the defaults are NEUTRAL (deploy the whole slice), NOT a stupid
    # blanket %. `max_position_pct` is a FRACTION OF THIS TRACK'S SLICE (1.0 = the whole slice), and
    # `max_concurrent_positions` only divides the slice when several positions are actually open at once
    # (see master/sizing.size_fraction — it never bridles a mono-position all-in spec). The old 0.05/0.5
    # defaults pre-date the sandbox model and bridled every spec to 2.5%; the per-combo wallet now caps loss,
    # so the spec sizes freely inside it.
    max_concurrent_positions: int = 3
    max_position_pct: float = 1.0
    conviction: float = 1.0


class MaTrendFilter(BaseModel):
    """Long-only regime filter: only allow entries when price is above its moving average (spot, long-only).
    `ma_lookback` is a ParamRef so the MA window is fit, not hardcoded."""

    ma_lookback: ParamRef


class OpeningRangeBreakout(BaseModel):
    """Upside-only opening-range breakout. `range_bars` defines the range window (a ParamRef); `anchor`
    chooses a fixed session anchor (the first N bars of each window) vs a rolling window. Entry fires when
    price breaks ABOVE the range high (long-only). `buffer` is a ParamRef break-above margin (no magic numbers)."""

    range_bars: ParamRef
    buffer: ParamRef
    anchor: Literal["session", "rolling"] = "rolling"


class FairValueGap(BaseModel):
    """Upside fair-value-gap (FVG) retest setup. A bullish FVG is a 3-bar imbalance (bar[i-2].high < bar[i].low).
    Entry fires when price RETESTS the gap from above. `max_retests` (a ParamRef) caps how many times the same
    gap may be re-entered (fvg_multiple); `gap_min` is the minimum gap size as a ParamRef fraction (no magic
    numbers). Long/upside-only."""

    max_retests: ParamRef
    gap_min: ParamRef


class EntrySetup(BaseModel):
    """Composable, optimizer-fittable entry structure layered alongside `entry` conditions. Each leaf is
    optional (None => off). All setups are long/upside-only (spot). Thresholds are ParamRefs — fit, never magic."""

    ma_trend_filter: MaTrendFilter | None = None
    orb: OpeningRangeBreakout | None = None
    fvg: FairValueGap | None = None


class MetaLabel(BaseModel):
    """Triple-barrier meta-labeling (López de Prado). A SECONDARY regularized-logistic classifier predicts
    P(the primary signal's trade is a net winner) from `features` read point-in-time at entry, and gates the
    primary trade: SKIP it below `prob_threshold`, otherwise take it (optionally SIZING the notional by the
    predicted probability). It only SIZES or SKIPS — it NEVER changes `direction` (the primary signal owns the
    side). The training label for each past primary event is which of the three barriers (stop-loss /
    take-profit / time) the trade hit first, netted of round-trip cost (win=1, else 0) — the same stop/take/
    time that `ExitRules` already carries. Training is EXPANDING-WINDOW and point-in-time: at each entry only
    primary events whose barrier RESOLVED on a strictly earlier bar feed the fit, so the secondary model never
    sees its own trade's outcome (no look-ahead). Until META_MIN_TRAIN resolved events exist the trade is
    ungated (the bare primary book), so the gate can only ever subtract trades the primary would have taken.
    None on the spec => no meta-label at all (the primary book, byte-identical to the prior behaviour).

    The secondary model is a logistic on purpose: spot history is <100k rows, far too thin for a boosted tree
    to do anything but overfit (LightGBM is reserved for offline MDA feature-importance, never the live gate).
    The `features` are FeatureRefs so each names a real registry feature with its own fitted lookback (no magic
    numbers); `funding_rate` is the canonical one to include. `prob_threshold` is a ParamRef so the size/skip
    cut is fit from the param space by the Finder/Gate like every other knob — never hardcoded."""

    features: list[FeatureRef]
    prob_threshold: ParamRef
    # "skip": binary gate (take at full size iff p >= threshold). "proportional": also scale the notional by the
    # predicted win probability above the threshold (conviction sizing). Both only size/skip — never flip side.
    sizing: Literal["skip", "proportional"] = "skip"


class EventFilter(BaseModel):
    """A point-in-time predicate over a cosmu.data.events_store.MarketEvent. An entry fires on a bar when a
    matching event became KNOWN to us in that bar's interval (joined on `available_at`, never `ts` — a scraped
    archive is honestly available at scrape time, never backdated). `source` matches the event provider
    (gdelt | cryptopanic | rss | xai_twitter | polymarket | ...); None => any provider. `kind` matches the
    extractor's typed `event_type` (None => any). `min_magnitude` requires the extractor's surprise/magnitude
    in [0,1] to clear a floor (None => no magnitude floor; an unextracted event has magnitude None and is kept
    only when min_magnitude is None). `direction` requires the extractor's signed claim (-1|0|+1; None => any
    side). No magic numbers leak into entry/exit — the magnitude floor is the only knob and it lives here as a
    typed, fitted-or-fixed field, mirroring how condition thresholds stay off the price path."""

    source: str | None = None
    kind: str | None = None
    min_magnitude: float | None = None
    direction: Literal[-1, 0, 1] | None = None


class EventEntrySignal(BaseModel):
    """The entry leg of an event strategy: a single EventFilter whose match opens a position on the NEXT bar
    (same prior-bar-signal / next-bar-fill discipline as every indicator entry). `cooldown_bars` suppresses
    re-entry for N bars after a fired entry so one clustered news burst is one trade, not a flurry (>=0;
    0 => no suppression, the prior-firing-per-bar default)."""

    filter: EventFilter
    cooldown_bars: int = 0


class EventRegimeShift(BaseModel):
    """OPTIONAL slow-regime overlay for event strategies (strategy_kind='regime' reserved): a matching event
    TILTS exposure for `hold_bars` bars rather than opening a discrete trade. Typed now so the discriminator
    has all three lanes; the backtest treats it as a long-lived entry filter. None on the EventSetup => a
    discrete event-entry strategy (the default)."""

    filter: EventFilter
    hold_bars: int


class EventSetup(BaseModel):
    """The event-strategy payload hung off StrategySpec.event (None for every indicator spec, so existing specs
    are byte-identical). `entry` is the discrete event-entry signal; `regime` is the reserved slow-tilt overlay.
    Exactly one of them is the active leg — `entry` for strategy_kind='event', `regime` for 'regime'."""

    entry: EventEntrySignal | None = None
    regime: EventRegimeShift | None = None


class StrategySpec(BaseModel):
    name: str
    rationale: str
    # First-class strategy TYPE discriminator the router uses to pick the evaluator path: "indicator" = the
    # price/TA + alt-condition backtest (every existing spec — the default keeps them all valid and unchanged);
    # "event" = entries fire on a typed MarketEvent matching `event.entry.filter` (point-in-time on available_at)
    # and route through cosmu/data/event_backtest.py; "regime" = the reserved slow-tilt overlay (event.regime).
    # The same downstream gate scores all three — only the entry-generation path differs.
    strategy_kind: Literal["indicator", "event", "regime"] = "indicator"
    # The event/alt payload — REQUIRED when strategy_kind is "event"/"regime", None for indicator specs (so a
    # plain indicator spec is byte-identical to before). See EventSetup.
    event: EventSetup | None = None
    # Evaluation lane — the TYPED discriminator the master uses to pick the correct evaluator path, so routing is
    # explicit on the spec instead of an accident of which function a runner happens to call (the silent mis-routing
    # that killed long-only equity in the gate-lane). "gate" = a NOVEL in-sample-mined hypothesis: judged by the
    # honest 0.95 deflated-Sharpe bar + BH-FDR cohort gate (promote_cohort). "deploy" = an externally-documented
    # strategy with decades of OOS/live evidence: judged by the positive-OOS deployment bar (taa.validate-style),
    # NOT the 0.95 in-sample Gate. "explore" = a low-confidence VIBE (NL-pipeline / loose idea): it is NOT judged
    # by the strict gate — it enters a ZERO-CAPITAL paper/explore disposition where the SAME SIM executor runs its
    # own logic forward (observe-only), and it GRADUATES to the gate-lane only if it later actually clears the
    # honest 0.95 gate. The explore lane NEVER loosens or bypasses the gate — it routes a vibe to paper observation
    # and lets the unchanged gate dispose at graduation. Default "gate" preserves ALL current behaviour.
    lane: Literal["gate", "deploy", "explore"] = "gate"
    # Strategy MODEL — the top-level discriminator for which VALIDATION + EXECUTION path applies. "quant" = a typed
    # StrategySpec judged by the deterministic Gate A (DSR/PBO/BH-FDR) and run by the compiled backtest/executor —
    # the only model today, so default "quant" keeps EVERY existing spec byte-identical. "llm" is reserved for the
    # agentic/NL model (a Mind reasoning loop → typed Decision) validated by the scientific-flexible Gate B
    # (score+evidence, no backtest) — that artifact is a separate AgentSpec (see docs/epics/agentic-lane.md), so on a
    # StrategySpec this stays "quant" in practice; it exists here so the kind axis is uniform end-to-end (spec → the
    # strategy_versions.kind column → UI). ORTHOGONAL to strategy_kind (indicator/event/regime, the entry-generation
    # path) and to lane (gate/deploy/explore, the evaluator); status + lane are SHARED across both kinds. Enforced by
    # this Literal + a guard test, matching the repo's no-DB-CHECK convention (knowledge/lifecycle_status.py).
    kind: Literal["quant", "llm"] = "quant"
    # REALISTIC EXECUTION MODE — declared at CREATION, the discriminator the backtest uses to charge the right
    # fee + fill realism so a strategy is never scored on a fill it could not actually get. "taker" (DEFAULT) =
    # the order CROSSES the spread to fill immediately — the conservative ALWAYS-FILL floor every existing spec
    # uses (entry pays the half-spread + size-aware impact + the venue TAKER fee), byte-identical to before.
    # "maker" = the order POSTS PASSIVELY: it pays the lower venue MAKER fee and avoids paying the half-spread,
    # BUT the backtest applies HONEST passive-fill realism (a no-fill rate + adverse selection + queue position —
    # a resting order only fills when the market moves AGAINST it, and not every touched order fills) and NEVER
    # credits the spread (the "no-spread-credit floor"), so this is not a free spread-capture cheat. This is the
    # mode that un-hides the reversion / fade / spread family (real at maker, dead at taker) and the future
    # options scanner. "both" = the edge is feasible either way; it is screened TAKER (the conservative gate
    # floor), with maker as an upside a later pass scores. Only "maker" activates the passive-fill realism; the
    # urgent EXIT legs (stop / time-stop / forced liquidation) always cross as a TAKER even in maker mode — you
    # cannot passively guarantee an urgent exit. See data/backtest.MakerFillModel + spine/asset_fees maker
    # resolvers. The creation_playbook enforces maker/taker LOGIC coherence + venue feasibility BEFORE the Gate.
    execution_mode: Literal["taker", "maker", "both"] = "taker"
    universe: UniverseSelector
    horizon: Horizon
    catalyst: str | None = None
    # The NAMED DISCONFIRMER — the single observation that would prove this hypothesis WRONG (e.g. "no edge if the
    # signal's IC is ≤ a shuffled-null control" / "kill if it loses to buy-and-hold net of fees on its own cell").
    # Optional on the type so every existing spec stays valid, but the creation_playbook REQUIRES one (in this
    # field or named in the rationale) before a NEW authored strategy may reach the Gate — a disconfirmable thesis
    # is what the Gate is actually testing. None => fall back to scanning the rationale for a disconfirmer cue.
    disconfirmer: str | None = None
    entry: list[Condition]
    exit: ExitRules
    risk: RiskRules
    param_space: dict[str, ParamSpace]
    setup: EntrySetup | None = None
    # Trade side: +1 = long (the spot/upside-only default — existing specs are unchanged), -1 = short (the
    # perp/short leg; entry conditions fire a short, stop is ABOVE entry, take-profit BELOW), 0 = the signal
    # decides per bar (reserved; treated as long until per-bar direction signals land). Entry CONDITIONS are
    # unchanged — `direction` only flips which way the resulting position is taken, so the long-only assumption
    # baked into the backtest is lifted without rewriting any condition logic.
    direction: Literal[-1, 0, 1] = 1
    # Funding rate (perp carry) accrues to the open position as P&L each bar when set. The value names the
    # alt-data feature carrying the point-in-time periodic funding rate (e.g. "funding_rate"); None => no
    # funding leg (spot — exactly the prior behaviour). A long pays funding when the rate is positive; a short
    # receives it. No magic numbers: the rate comes from the PIT alt-data join, not a constant.
    funding_feature: str | None = None
    # Triple-barrier meta-labeling: a secondary logistic gate that SIZES/SKIPS the primary trade by its predicted
    # win probability (never flips direction). None => no meta-label, byte-identical to the prior behaviour. See
    # MetaLabel for the full point-in-time / no-look-ahead contract.
    meta_label: MetaLabel | None = None

