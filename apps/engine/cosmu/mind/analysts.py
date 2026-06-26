# intent: the analyst panel — a TradingAgents-style team of perspectives that each read ONE family of the
# agent's existing point-in-time signals and emit a standardized Stance (lean · conviction · score · why). ML is
# a pillar, not the whole story: alongside it sit technical, macro, sentiment, social/news, positioning and OSINT
# reads. `run_panel()` turns the panel into TYPED VERDICTS: the deterministic heuristic always runs, and when an
# optional LLM `judge` seam is supplied each pillar WITH data is rubric-scored by the model (the model sets
# lean/confidence/rationale; the deterministic debate still combines them; the gate alone disposes). inputs: a
# MindContext (regime + latest alt-data values + ML model state + memory counts), gathered ONCE; outputs: one
# Stance per analyst. invariants: deterministic + offline by default (judge=None), point-in-time; a perspective
# with no ingested data ABSTAINS and is NEVER handed to the model (never fabricates); analysts never move money.

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

from cosmu.knowledge.store import Store
from cosmu.ml.regime import Regime
from cosmu.ml.survival import SurvivalModel, load_survival_model
from cosmu.mind.judge import JudgeFn
from cosmu.mind.rubric import RUBRICS

# A market Stance leans one of these. "abstain" is the honest answer when the feed isn't ingested yet.
LEANS = ("bullish", "bearish", "neutral", "abstain")

# The metrics whose latest value is SYMBOL-SPECIFIC: BTC funding ≠ ETH funding, DOGE social ≠ SOL social, each
# asset's perp/leverage state and crowd/headline flow are its own. The observe loop resolves THESE per symbol
# (from alt_data, filtered by symbol). Every OTHER metric the panel reads — fear_greed (one global crowd index),
# macro_regime + the FRED curve/rates/liquidity block, OSINT air activity — is MARKET-WIDE: a single shared value
# gathered once. Per-symbolising a global fear/greed index would be a lie, so the split is deliberate (don't
# par-symbolise the shared metrics). See docs/epics/agentic-lane.md.
PER_SYMBOL_METRICS: frozenset[str] = frozenset(
    {
        # positioning — per-asset perp/leverage state (the Positioning analyst)
        "funding_rate",
        "open_interest",
        "perp_spot_basis",
        "exchange_netflow",
        # social / news — per-asset crowd mood + headline flow (the Sentiment + Social & News analysts)
        "news_sentiment",
        "social_sentiment",
        "social_volume",
        "reddit_sentiment",
    }
)


@dataclass(frozen=True)
class Stance:
    """One perspective's standardized read. `kind` separates MARKET analysts (which vote on the directional
    consensus) from PROCESS analysts (ML + memory — they report on the machine's self-knowledge, not price).
    `weight` is how much a market stance counts in the consensus (low-confidence sources count half); process
    stances carry weight 0. `conviction` is 0 when the analyst abstains. Nothing here funds or fires."""

    perspective: str
    kind: str  # "market" | "process"
    lean: str  # one of LEANS
    conviction: float  # 0..1 — this IS the verdict's confidence
    weight: float  # consensus weight (0 for process / abstain)
    headline: str
    rationale: str
    evidence: list[str] = field(default_factory=list)
    as_of: str | None = None
    low_confidence: bool = False
    # --- the typed verdict, filled by run_panel() ---
    # `score` is the signed directional strength (-1 bearish … +1 bullish; 0 for neutral/abstain/process).
    # `source` is the verdict's provenance for audit: "heuristic" (deterministic), "llm" (a judged Verdict),
    # or "abstain" (no data). `rubric` names the rubric a market pillar was scored under (None for process).
    score: float = 0.0
    source: str = "heuristic"  # "heuristic" | "llm" | "abstain"
    rubric: str | None = None


@dataclass(frozen=True)
class MindContext:
    """Everything the analysts read, gathered once so the panel runs in a single pass. `values` maps a metric
    name to its latest point-in-time (value, available_at). `regime` is the current market regime from a REAL
    reference series (None when no price history is available — the technical analyst then abstains)."""

    regime: Regime | None
    values: dict[str, tuple[float, str | None]]
    ml: SurvivalModel
    memory: dict[str, int]
    as_of: str | None


# --------------------------------------------------------------------------- context gathering


def gather_context(store: Store, *, reference_bars=None) -> MindContext:
    """Read the current point-in-time state once. Defensive throughout: a missing table / empty store yields an
    abstaining panel, never an error. `reference_bars` is a REAL close series (the API passes live Binance bars);
    when absent the regime is left None and the technical analyst abstains rather than inventing a regime."""
    from cosmu.ml.regime import current_regime

    regime = current_regime(reference_bars) if reference_bars else None
    values = _latest_values(store)
    try:
        ml = load_survival_model(store)
    except Exception:  # noqa: BLE001 — cold store: fall back to an untrained model
        ml = SurvivalModel(trained=False, backend="heuristic", n_labels=0)
    memory = _memory_counts(store)
    as_of = None
    for _, available_at in values.values():
        if available_at and (as_of is None or available_at > as_of):
            as_of = available_at
    return MindContext(regime=regime, values=values, ml=ml, memory=memory, as_of=as_of)


def context_for_symbol(store: Store, base: MindContext, symbol: str) -> MindContext:
    """Derive the per-PRODUCT context for one `symbol` from the shared market-wide `base` (gathered ONCE via
    gather_context). Keep the market-wide metrics as-is, but STRIP the per-symbol metrics out of the shared
    values — the market-wide read carries whichever symbol's per-symbol row was newest, so without this strip a
    per-symbol metric with no data for THIS symbol would silently inherit another symbol's value — and overlay
    this symbol's own latest per-symbol values read from alt_data. regime / ml / memory are market-wide / process
    self-knowledge and pass through unchanged. as_of is recomputed over the merged values so it reflects the
    actual product context. Offline-safe: a cold store yields the market-wide base minus per-symbol metrics (an
    honest abstain for funding/sentiment), never a fabricated or cross-symbol value."""
    from cosmu.ingest.alt_summary import latest_value_per_metric_for_symbol

    shared = {m: v for m, v in base.values.items() if m not in PER_SYMBOL_METRICS}
    per_symbol = latest_value_per_metric_for_symbol(store, symbol, sorted(PER_SYMBOL_METRICS))
    merged = {**shared, **per_symbol}
    as_of: str | None = None
    for _, available_at in merged.values():
        if available_at and (as_of is None or available_at > as_of):
            as_of = available_at
    return replace(base, values=merged, as_of=as_of)


def _latest_values(store: Store) -> dict[str, tuple[float, str | None]]:
    """Latest available value per metric (point-in-time: newest available_at wins). Reads the tiny
    alt_data_provider_summary rollup (one row per provider/metric, value of the newest row carried
    incrementally on ingest) instead of a JOIN+GROUP-BY over the ~17M-row alt_data table — the same
    full-scan perf trap fixed for /intelligence and /scores. Returns {} on any error / empty summary so a
    store without the rollup degrades to an abstaining panel (honest, never fabricated)."""
    from cosmu.ingest.alt_summary import latest_value_per_metric

    return latest_value_per_metric(store)


def _memory_counts(store: Store) -> dict[str, int]:
    def count(sql: str) -> int:
        try:
            row = store.row(sql)
            return int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001
            return 0

    return {
        "dead_ends": count("SELECT COUNT(*) AS n FROM research_notes WHERE kind = 'dead_end'"),
        "winners": count("SELECT COUNT(*) AS n FROM research_notes WHERE kind = 'winner'"),
        "skills": count("SELECT COUNT(*) AS n FROM skills"),
    }


# --------------------------------------------------------------------------- helpers


def _abstain(perspective: str, kind: str, reason: str, *, low_confidence: bool = False) -> Stance:
    return Stance(
        perspective=perspective,
        kind=kind,
        lean="abstain",
        conviction=0.0,
        weight=0.0,
        headline="No data yet",
        rationale=reason,
        evidence=[],
        low_confidence=low_confidence,
        score=0.0,
        source="abstain",
    )


def _val(ctx: MindContext, metric: str) -> tuple[float, str | None] | None:
    return ctx.values.get(metric)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------------------------------------------------------- market analysts


def technical_analyst(ctx: MindContext) -> Stance:
    """Reads the current market regime (trend × realized-vol tercile) off a REAL reference series."""
    r = ctx.regime
    if r is None:
        return _abstain("Technical", "market", "No price history available to read a regime.")
    lean = {"bull": "bullish", "bear": "bearish", "chop": "neutral"}.get(r.trend, "neutral")
    conviction = {"low": 0.7, "mid": 0.55, "high": 0.4}.get(r.vol_bucket, 0.5)
    return Stance(
        perspective="Technical",
        kind="market",
        lean=lean,
        conviction=conviction,
        weight=1.0,
        headline=f"{r.trend.capitalize()} trend, {r.vol_bucket} volatility",
        rationale="Trend sign × realized-volatility tercile on the reference series (point-in-time).",
        evidence=[f"trend={r.trend}", f"vol={r.vol_bucket}"],
        as_of=ctx.as_of,
    )


def sentiment_analyst(ctx: MindContext) -> Stance:
    """Crowd fear/greed (0–100) — buy fear, fade greed (a swing-horizon mean-reversion prior) — with Reddit
    crowd chatter as a low-confidence cross-check. Fear & Greed drives the lean when present; Reddit-only is a
    last-resort, low-confidence read. Abstains only when NEITHER feed is ingested."""
    fg = _val(ctx, "fear_greed")
    reddit = _val(ctx, "reddit_sentiment")
    if fg is None and reddit is None:
        return _abstain("Sentiment", "market", "Fear & Greed / Reddit sentiment not ingested yet.")
    evidence: list[str] = []
    asof: str | None = None
    low_conf = False
    if fg is not None:
        value, asof = fg
        distance = abs(value - 50.0) / 50.0
        conviction = _clamp01(0.35 + distance * 0.65)
        if value <= 45:
            lean, label = "bullish", "fear"
        elif value >= 55:
            lean, label = "bearish", "greed"
        else:
            lean, label, conviction = "neutral", "balanced", 0.4
        headline = f"Crowd reads {int(value)}/100 — {label}"
        evidence.append(f"fear_greed={value:.0f}")
    else:
        # Reddit-only fallback: bullish chatter leans bullish, bearish bearish — explicitly low-confidence.
        rv, asof = reddit
        low_conf = True
        conviction = _clamp01(0.3 + abs(rv) * 0.5)
        if rv > 0.1:
            lean = "bullish"
        elif rv < -0.1:
            lean = "bearish"
        else:
            lean, conviction = "neutral", 0.35
        headline = f"Reddit crowd {rv:+.2f}"
    if reddit is not None:
        rv, ra = reddit
        evidence.append(f"reddit_sentiment={rv:+.2f}")
        asof = ra if (asof is None or (ra and ra > asof)) else asof
    return Stance(
        perspective="Sentiment",
        kind="market",
        lean=lean,
        conviction=round(conviction, 3),
        weight=1.0,
        headline=headline,
        rationale="Buy fear, fade greed: sentiment extremes mean-revert at the swing horizon; Reddit crowd chatter is a low-confidence cross-check.",
        evidence=evidence,
        as_of=asof,
        low_confidence=low_conf,
    )


def macro_analyst(ctx: MindContext) -> Stance:
    """Shared macro regime (FRED curve/rates/liquidity) — risk-on vs risk-off across asset classes.
    Reads macro_regime plus supplementary FRED series (DXY, yield curve, credit spread, VIX term slope)."""
    hit = _val(ctx, "macro_regime")
    dxy = _val(ctx, "dxy")
    curve = _val(ctx, "yield_curve_2s10s")
    credit = _val(ctx, "credit_spread")
    vix_slope = _val(ctx, "vix_term_slope")
    vix = _val(ctx, "vix_level")
    ffr = _val(ctx, "fed_funds_rate")
    if hit is None and dxy is None and curve is None and credit is None:
        return _abstain("Macro", "market", "Macro regime (FRED) not ingested yet.")
    evidence: list[str] = []
    score = 0.0
    asof: str | None = None
    if hit is not None:
        value, asof = hit
        score += math.tanh(value)
        evidence.append(f"macro_regime={value:+.2f}")
    if dxy is not None:
        v, a = dxy
        evidence.append(f"dxy={v:.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if curve is not None:
        v, a = curve
        score += math.tanh(v) * 0.3
        evidence.append(f"yield_curve_2s10s={v:+.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if credit is not None:
        v, a = credit
        score -= math.tanh(v / 3.0) * 0.2
        evidence.append(f"credit_spread={v:.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if vix_slope is not None:
        v, a = vix_slope
        evidence.append(f"vix_term_slope={v:.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if vix is not None:
        v, a = vix
        evidence.append(f"vix_level={v:.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if ffr is not None:
        v, a = ffr
        evidence.append(f"fed_funds_rate={v:.2f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    conviction = round(_clamp01(0.4 + abs(score) * 0.5), 3)
    if score > 0.15:
        lean, label = "bullish", "risk-on"
    elif score < -0.15:
        lean, label = "bearish", "risk-off"
    else:
        lean, label, conviction = "neutral", "neutral", 0.4
    return Stance(
        perspective="Macro",
        kind="market",
        lean=lean,
        conviction=conviction,
        weight=1.0,
        headline=f"Macro regime {label}",
        rationale="Curve slope, real rates and liquidity condition risk premia across every asset class.",
        evidence=evidence,
        as_of=asof,
    )


def social_news_analyst(ctx: MindContext) -> Stance:
    """News-flow sentiment (LLM-standardized to a number at ingest only) plus LunarCrush social metrics. A
    positive flow shift precedes continuation before it is fully priced. News drives the directional lean
    (known [-1,1] scale); social_sentiment is a half-weight cross-check, social_volume is attention (evidence
    only, not direction). A tier-1 source — half weight, low-confidence — abstains only when NONE are ingested."""
    news = _val(ctx, "news_sentiment")
    social_sent = _val(ctx, "social_sentiment")
    social_vol = _val(ctx, "social_volume")
    if news is None and social_sent is None and social_vol is None:
        return _abstain("Social & News", "market", "News-flow / LunarCrush social not ingested yet.", low_confidence=True)
    evidence: list[str] = []
    asof: str | None = None
    score = 0.0
    if news is not None:
        v, asof = news
        score += v
        evidence.append(f"news_sentiment={v:+.2f}")
    if social_sent is not None:
        v, a = social_sent
        # LunarCrush v4 social_sentiment is a 0..100 bullish share → center to a signed [-1,1] nudge (half weight).
        signed = max(-1.0, min(1.0, (v - 50.0) / 50.0))
        score += signed * 0.5
        evidence.append(f"social_sentiment={v:.0f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if social_vol is not None:
        v, a = social_vol
        evidence.append(f"social_volume={v:.0f}")  # attention/intensity, not direction → evidence only
        asof = a if (asof is None or (a and a > asof)) else asof
    conviction = round(_clamp01(0.3 + abs(score) * 0.6), 3)
    if score > 0.1:
        lean = "bullish"
    elif score < -0.1:
        lean = "bearish"
    else:
        lean, conviction = "neutral", 0.35
    return Stance(
        perspective="Social & News",
        kind="market",
        lean=lean,
        conviction=conviction,
        weight=0.5,
        headline=f"Social/news flow {score:+.2f}",
        rationale="A positive news/social-flow shift precedes multi-day continuation before it is fully priced; LunarCrush social adds a low-confidence cross-check.",
        evidence=evidence,
        as_of=asof,
        low_confidence=True,
    )


def positioning_analyst(ctx: MindContext) -> Stance:
    """Crowded-leverage read: perp funding (z), open interest, basis, and exchange netflow. Extreme positive
    funding = crowded longs (cautious). (The liquidation-cascade leg was dropped 2026-06-26 — that feature is
    graveyarded: direction-blind + data-starved, no keyless signed source; see config/feature_registry.py.)"""
    funding = _val(ctx, "funding_rate")
    oi = _val(ctx, "open_interest")
    basis = _val(ctx, "perp_spot_basis")
    netflow = _val(ctx, "exchange_netflow")
    if funding is None and oi is None and basis is None and netflow is None:
        return _abstain("Positioning", "market", "Positioning feeds not ingested yet.")
    evidence: list[str] = []
    score = 0.0
    asof: str | None = None
    if funding is not None:
        fz, fa = funding
        evidence.append(f"funding_z={fz:+.2f}")
        score -= math.tanh(fz)
        asof = fa
    if oi is not None:
        v, a = oi
        evidence.append(f"open_interest={v:.0f}")
        asof = a if (asof is None or (a and a > asof)) else asof
    if basis is not None:
        v, a = basis
        evidence.append(f"perp_spot_basis={v:+.4f}")
        score -= math.tanh(v * 100) * 0.3
        asof = a if (asof is None or (a and a > asof)) else asof
    if netflow is not None:
        v, a = netflow
        evidence.append(f"exchange_netflow={v:+.3f}")
        score += math.tanh(v) * 0.2
        asof = a if (asof is None or (a and a > asof)) else asof
    conviction = round(_clamp01(0.35 + abs(score) * 0.5), 3)
    if score > 0.15:
        lean, label = "bullish", "room to run"
    elif score < -0.15:
        lean, label = "bearish", "crowded longs"
    else:
        lean, label, conviction = "neutral", "balanced", 0.4
    return Stance(
        perspective="Positioning",
        kind="market",
        lean=lean,
        conviction=conviction,
        weight=1.0,
        headline=f"Leverage {label}",
        rationale="Funding extremes proxy crowded leverage; OI/basis/netflow confirm the positioning read.",
        evidence=evidence,
        as_of=asof,
    )


def osint_analyst(ctx: MindContext) -> Stance:
    """Best-effort OSINT (aircraft activity as a crude macro risk-appetite proxy). LOW confidence by design —
    it abstains until ingested and never weighs more than half. The honest 'watching planes' lens."""
    hit = _val(ctx, "osint_air_activity")
    if hit is None:
        return _abstain("OSINT", "market", "OSINT (air activity) not ingested yet.", low_confidence=True)
    value, asof = hit
    lean = "bullish" if value > 0 else "bearish" if value < 0 else "neutral"
    return Stance(
        perspective="OSINT",
        kind="market",
        lean=lean,
        conviction=0.25,
        weight=0.5,
        headline="Crude risk-appetite proxy",
        rationale="Aircraft activity as a low-confidence economic-activity proxy — must earn its place via OOS.",
        evidence=[f"air_activity={value:+.2f}"],
        as_of=asof,
        low_confidence=True,
    )


# --------------------------------------------------------------------------- process analysts (ML + memory)


def ml_analyst(ctx: MindContext) -> Stance:
    """The ML pillar — the survival model that ORDERS which candidates get validated first (never vetoes).
    Reports the machine's confidence in its OWN selectivity, not a price call: trained backend + OOS AUROC +
    how many labeled outcomes it has learned from."""
    ml = ctx.ml
    if ml.trained:
        auroc = ml.auroc if ml.auroc is not None else 0.5
        conviction = round(_clamp01((auroc - 0.5) * 2.0), 3)
        headline = f"Trained ({ml.backend}, AUROC {auroc:.2f})"
        rationale = f"Learned edge-persistence from {ml.n_labels} labeled outcomes; orders validation, never vetoes."
    else:
        conviction = round(_clamp01(ml.n_labels / 30.0), 3)
        headline = f"Calibrating ({ml.n_labels}/30 outcomes)"
        rationale = "Cold-start heuristic until 30 labeled outcomes exist — a thin model cannot prioritize."
    return Stance(
        perspective="ML survival",
        kind="process",
        lean="neutral",
        conviction=conviction,
        weight=0.0,
        headline=headline,
        rationale=rationale,
        evidence=[f"backend={ml.backend}", f"labels={ml.n_labels}"],
        as_of=ctx.as_of,
    )


def memory_analyst(ctx: MindContext) -> Stance:
    """Long-term memory — the graveyard/winner RAG. Reports how much the machine has learned: dead ends to
    avoid, winning structures to reuse, distilled skills."""
    m = ctx.memory
    learned = m["dead_ends"] + m["winners"]
    conviction = round(_clamp01(learned / 50.0), 3)
    headline = f"{m['dead_ends']} dead ends · {m['winners']} winners · {m['skills']} skills"
    return Stance(
        perspective="Memory",
        kind="process",
        lean="neutral",
        conviction=conviction,
        weight=0.0,
        headline=headline,
        rationale="Avoids re-walking dead structures and leans toward what cleared the gate before.",
        evidence=[f"dead_ends={m['dead_ends']}", f"winners={m['winners']}", f"skills={m['skills']}"],
        as_of=ctx.as_of,
    )


# The panel, in display order: market perspectives first, then the process (self-knowledge) pillars.
ALL_ANALYSTS: tuple[Callable[[MindContext], Stance], ...] = (
    technical_analyst,
    macro_analyst,
    sentiment_analyst,
    social_news_analyst,
    positioning_analyst,
    osint_analyst,
    ml_analyst,
    memory_analyst,
)


# --------------------------------------------------------------------------- the panel → typed verdicts


def _signed(lean: str, conviction: float) -> float:
    """Signed directional strength for a heuristic read: + for bullish, - for bearish, 0 otherwise."""
    if lean == "bullish":
        return round(conviction, 3)
    if lean == "bearish":
        return round(-conviction, 3)
    return 0.0


def run_panel(ctx: MindContext, *, judge: JudgeFn | None = None) -> list[Stance]:
    """Run every analyst into a TYPED VERDICT. Each market pillar first produces its deterministic read (the
    point-in-time facts + a heuristic lean/conviction). When a `judge` seam is supplied AND the pillar has data,
    the LLM RE-SCORES that evidence under the pillar's rubric into a structured Verdict — the model sets the
    lean/confidence/rationale, the deterministic math (debate) still combines them, and the gate alone disposes.
    A pillar with no data ABSTAINS and is never handed to the model (no fabrication); the process pillars (ML,
    memory) are self-knowledge and are never judged. `judge=None` (the default) keeps the panel fully
    deterministic and offline. Every returned stance carries its verdict provenance for audit."""
    out: list[Stance] = []
    for analyst in ALL_ANALYSTS:
        stance = analyst(ctx)
        rubric = RUBRICS.get(stance.perspective)
        judgeable = judge is not None and rubric is not None and stance.kind == "market" and stance.lean != "abstain"
        if judgeable:
            verdict = judge(rubric, stance.evidence, stance.lean)  # type: ignore[misc]
            if verdict is not None:
                out.append(
                    replace(
                        stance,
                        lean=verdict.lean,
                        conviction=round(verdict.confidence, 3),
                        rationale=verdict.rationale,
                        score=round(verdict.score, 3),
                        source="llm",
                        rubric=rubric.pillar,
                    )
                )
                continue
        # Heuristic / abstain / process: finalize the signed score + the rubric label without an LLM.
        out.append(
            replace(
                stance,
                score=_signed(stance.lean, stance.conviction) if stance.kind == "market" else 0.0,
                source=stance.source if stance.lean == "abstain" else "heuristic",
                rubric=rubric.pillar if rubric is not None else stance.rubric,
            )
        )
    return out
