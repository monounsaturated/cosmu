# intent: turn a plain-language brief into a typed, validated StrategySpec draft so a human can author/suggest strategies in chat (LLM-optional); inputs: brief text + optional feature/venue picks + optional long-term memory (graveyard RAG + distilled skills); outputs: AuthorDraft (spec + data sources + guardrail report); invariants: the draft only authors STRUCTURE — thresholds stay in param_space (no magic numbers), money-adjacent intent is flagged for approval, memory only INFORMS the proposal (avoid recently-dead structures, lean toward winners) and the scorer/gates are never in this path (they alone dispose).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cosmu.config.feature_registry import FEATURE_REGISTRY, features_for
from cosmu.evolution.seeder import (
    seed_breakout_spec,
    seed_carry_spec,
    seed_meanrev_spec,
    seed_momentum_spec,
)
from cosmu.strategy.spec import Condition, FeatureRef, ParamRef, ParamSpace, StrategySpec
from cosmu.strategy.static_check import validate_spec

if TYPE_CHECKING:
    from cosmu.knowledge.store import Store

_SOURCE_BY_FEATURE = {f.name: f.source for f in FEATURE_REGISTRY}

# brief keyword → registry feature (the LLM-free intent map; an LLM slots in here when a key is set).
# Extended to cover all major feature families so diverse theme angles produce structurally distinct specs
# that clear novelty_gate min_distance=0.25 (different feature sets → Jaccard distance ≥ 0.25).
_FEATURE_HINTS: dict[str, str] = {
    # ── price / TA ─────────────────────────────────────────────────────────────
    "rsi": "rsi", "oversold": "rsi", "overbought": "rsi",
    "momentum": "ret_Nd", "trend": "ret_Nd", "breakout": "ret_Nd", "return": "ret_Nd",
    "volatility": "vol_realized", "vol ": "vol_realized", "realized vol": "vol_realized",
    "adx": "adx", "bollinger": "bb_z", "band": "bb_z", "z-score": "bb_z", "washout": "bb_z",
    "atr": "atr", "range": "atr", "sizing": "atr",
    "cross-sectional": "xsec_momentum_rank", "rank": "xsec_momentum_rank",
    # ── perp / derivatives ─────────────────────────────────────────────────────
    "funding": "funding_rate", "basis": "perp_spot_basis", "open interest": "open_interest",
    "dvol": "dvol", "implied vol": "dvol", "options": "dvol",
    # ── macro / cross-asset ────────────────────────────────────────────────────
    "vix": "vix_level", "fear index": "vix_level",
    "dollar": "dxy", "dxy": "dxy", "usd": "dxy",
    "macro": "macro_regime", "regime": "macro_regime",
    "yield curve": "yield_curve_2s10s", "yield": "yield_curve_2s10s", "2s10s": "yield_curve_2s10s",
    "credit": "credit_spread", "spread": "credit_spread",
    "fed": "fed_funds_rate", "rates": "fed_funds_rate", "federal reserve": "fed_funds_rate",
    "gold": "gold_xau", "xau": "gold_xau",
    "oil": "wti_crude", "crude": "wti_crude", "wti": "wti_crude",
    "spx": "spx_index", "s&p": "spx_index", "equity index": "spx_index",
    "eurusd": "eurusd", "euro": "eurusd",
    "risk-on": "xasset_risk_appetite", "risk appetite": "xasset_risk_appetite", "cross-asset": "xasset_risk_appetite",
    "nfci": "nfci", "financial conditions": "nfci",
    "balance sheet": "fed_balance_sheet_usd", "fed balance": "fed_balance_sheet_usd",
    "net liquidity": "net_liquidity_usd", "liquidity": "net_liquidity_usd",
    # ── on-chain ───────────────────────────────────────────────────────────────
    "hashrate": "btc_hashrate", "hash": "btc_hashrate",
    "mempool": "btc_mempool_size",
    "active addresses": "btc_active_addresses", "addresses": "btc_active_addresses",
    "defi": "defi_tvl", "tvl": "defi_tvl",
    "stablecoin": "stablecoin_mcap", "usdt supply": "stablecoin_mcap",
    "stablecoin flow": "stablecoin_net_flow_usd", "usdc flow": "stablecoin_net_flow_usd",
    "btc dominance": "cg_btc_dominance", "dominance": "cg_btc_dominance",
    "exchange netflow": "exchange_netflow", "exchange flow": "exchange_netflow",
    # ── sentiment / social ─────────────────────────────────────────────────────
    "sentiment": "social_sentiment", "social": "social_volume", "social volume": "social_volume",
    "galaxy": "galaxy_score", "lunarcrush": "galaxy_score",
    "alt rank": "alt_rank", "alternative rank": "alt_rank",
    "reddit": "reddit_sentiment", "reddit post": "reddit_post_volume",
    "twitter": "twitter_sentiment", "x.com": "twitter_sentiment",
    "news": "news_sentiment", "headline": "news_sentiment",
    "google trends": "gtrends_search_interest", "search interest": "gtrends_search_interest",
    "wikipedia": "wiki_pageviews_zscore", "wiki": "wiki_pageviews_zscore",
    "cryptopanic": "cryptopanic_bullish_votes",
    "fear": "fear_greed", "fear & greed": "fear_greed", "fear and greed": "fear_greed",
    "social attention": "social_attention_z", "attention": "social_excess_attention_z",
    # ── polymarket / prediction ────────────────────────────────────────────────
    "odds": "pm_implied_prob", "probability": "pm_implied_prob", "polymarket": "pm_implied_prob",
    "prediction market": "pm_risk_on",
    # ── OSINT / macro-proxy ────────────────────────────────────────────────────
    "plane": "osint_air_activity", "planes": "osint_air_activity", "aircraft": "osint_air_activity",
    "flight": "osint_air_activity", "flights": "osint_air_activity", "aviation": "osint_air_activity",
    "ads-b": "osint_air_activity", "adsb": "osint_air_activity", "opensky": "osint_air_activity",
    "earthquake": "usgs_earthquake_count", "kp index": "noaa_kp_index",
}

_ASSET_HINTS = {
    "crypto": ("crypto", "binance"), "btc": ("crypto", "binance"), "eth": ("crypto", "binance"),
    "bitcoin": ("crypto", "binance"), "perp": ("crypto", "binance"),
    "equity": ("equity", "ibkr"), "stock": ("equity", "ibkr"), "spy": ("equity", "ibkr"), "nasdaq": ("equity", "ibkr"),
    "prediction": ("prediction", "polymarket"), "polymarket": ("prediction", "polymarket"), "election": ("prediction", "polymarket"),
}


@dataclass
class AuthorDraft:
    spec: StrategySpec
    rationale: str
    base_template: str
    features: list[str]
    data_sources: list[str]
    venues: list[str]
    valid: bool
    issues: list[str]
    requires_approval: bool
    # Who authored this draft — "human" (chat/UI), "agent" (the LLM master fanning out briefs), or "import"
    # (pine/url). Drives the novelty policy below (hard reject for agent batches, advisory for a human) and is the
    # provenance the flywheel can later grade winners by.
    authored_by: str = "human"
    # Structural-novelty verdict (deterministic, offline): did this candidate clear the novelty gate vs. recent
    # dead-ends + complexity? For an agent author a False here is a hard issue (keeps the master from flooding
    # near-duplicates into the Gate's multiple-testing budget); for a human it is advisory only.
    novelty_ok: bool = True
    novelty_reason: str = "novel"
    guardrails: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # What long-term memory told the brain (audit trail): dead structures avoided + winner patterns leaned into.
    memory_avoided: list[str] = field(default_factory=list)
    memory_leaned: list[str] = field(default_factory=list)
    # What the propose-only research bus contributed (audit trail): prior-art features folded in + their citations.
    research_features: list[str] = field(default_factory=list)
    research_citations: list[str] = field(default_factory=list)


_TEMPLATE_BUILDERS = {
    "mean_reversion": seed_meanrev_spec,
    "carry": seed_carry_spec,
    "momentum": seed_momentum_spec,
    "breakout": seed_breakout_spec,
}


def _template_from_text(text: str) -> str:
    """The deterministic intent→template matcher (the keyless fallback). An LLM proposal, when present, overrides
    this choice — but the proposal can only pick one of these same magic-number-free templates.
    Extended to detect more angle-specific priors so diverse theme angles map to different templates
    (structural distance) even when the brief text is similar."""
    if any(k in text for k in ("revert", "reversion", "oversold", "mean", "dip", "bounce",
                                "washout", "dislocation", "contrarian", "fade", "extreme print",
                                "z-score", "band", "bollinger")):
        return "mean_reversion"
    if any(k in text for k in ("funding", "carry", "basis", "leverage", "persistence",
                                "regime persist", "positive carry", "low funding", "uncrowded",
                                "carry reversal", "accumulation")):
        return "carry"
    if any(k in text for k in ("momentum", "trend", "breakout", "adx", "confirmed",
                                "dual-horizon", "dual horizon", "multi-horizon",
                                "atr sizing", "volume confirm", "continuation")):
        return "momentum"
    # divergence/gate angles → breakout template (different features + param ranges)
    return "breakout"


def draft_from_brief(
    brief: str,
    *,
    features: list[str] | None = None,
    venues: list[str] | None = None,
    llm_enabled: bool = False,
    store: Store | None = None,
    prior_art: list[str] | None = None,        # features the propose-only research bus surfaced (rag prior-art)
    research_citations: list[str] | None = None,
    authored_by: str = "human",  # "human" | "agent" | "import" — drives the novelty policy (hard for agent batches)
    chat=None,  # noqa: ANN001 — injectable LLM seam (lab.llm.ChatFn); None → real OpenRouter seam from settings
) -> AuthorDraft:
    text = brief.lower()
    notes: list[str] = []
    memory_avoided: list[str] = []
    memory_leaned: list[str] = []
    research_cites = list(research_citations or [])

    # 1) pick a base template from intent. Deterministic by default; when an LLM key is set the model PROPOSES
    # the structure (template + named features + horizon) and we use it — but only ever to steer the same
    # magic-number-free templates below, so the LLM cannot smuggle a threshold in. The Gate still disposes.
    base = _template_from_text(text)
    llm_features: list[str] | None = None
    llm_bar: str | None = None
    if llm_enabled:
        # The LLM CONDITIONS on the gathered research context (prior-art features) — the agentic loop:
        # tools gather → model proposes informed structure → the deterministic Gate disposes.
        llm_brief = brief if not prior_art else f"{brief}\n\nResearch context — prior art supports these features: {', '.join(prior_art)}."
        proposal, llm_notes = _llm_propose(llm_brief, store=store, chat=chat)
        notes.extend(llm_notes)
        if proposal is not None:
            base = proposal.base_template
            llm_features = proposal.features or None
            llm_bar = proposal.bar_size
    spec = _TEMPLATE_BUILDERS[base]().model_copy(deep=True)

    # 2) retarget universe from asset intent or explicit venues
    asset_class, venue = _pick_asset(text)
    if venues:
        spec.universe.venues = venues
    elif venue:
        spec.universe.venues = [venue]
        spec.universe.asset_classes = [asset_class]

    # 3) horizon hints — the LLM's proposed bar_size (validated to 1h|4h|1d) wins; else detect from the brief.
    if llm_bar in ("1h", "4h", "1d"):
        spec.horizon.bar_size = llm_bar  # type: ignore[assignment]
    elif any(k in text for k in ("intraday", "hourly", "1h", "scalp")):
        spec.horizon.bar_size = "1h"
    elif any(k in text for k in ("daily", "swing", "1d")):
        spec.horizon.bar_size = "1d"
    if "week" in text:
        spec.horizon.max_hold_days = max(spec.horizon.max_hold_days, 21)

    # 4) risk hints (structure only — sizing stays with the deterministic master)
    if any(k in text for k in ("aggressive", "press")):
        spec.risk.max_position_pct = round(min(0.08, spec.risk.max_position_pct * 1.3), 4)
    if any(k in text for k in ("conservative", "safe", "careful", "low risk")):
        spec.risk.max_position_pct = round(max(0.01, spec.risk.max_position_pct * 0.7), 4)

    # 5) feature picks: explicit list (from UI) wins; else the LLM's proposed named features; else detected from
    # the brief. All are validated to the asset class — the LLM cannot pick a feature it isn't allowed to use.
    valid_feats = {f.name for f in features_for(spec.universe.asset_classes)}
    base_wanted = features or llm_features or _detect_features(text)
    # Fold in PRIOR-ART features the research bus surfaced (rag_read) as additional candidates — they still pass
    # validation + memory below (a prior-art feature memory has killed is still pruned), so research INFORMS but
    # never overrides the deterministic judgement. Explicit UI/LLM features stay the core; prior-art augments.
    wanted = base_wanted + [f for f in (prior_art or []) if f not in base_wanted]
    if prior_art:
        valid_prior = [f for f in prior_art if f in valid_feats]
        if valid_prior:
            notes.append(f"research: prior-art supports feature(s) {valid_prior}")
    chosen = [f for f in wanted if f in valid_feats]
    rejected = [f for f in wanted if f and f not in valid_feats]
    if rejected:
        notes.append(f"ignored features not valid for {spec.universe.asset_classes}: {rejected}")

    # 5b) consult LONG-TERM MEMORY (graveyard RAG + distilled skills) when a store is wired: AVOID structures
    # recently killed by the Gate and LEAN toward winning patterns. This only re-ranks the PROPOSAL — the
    # deterministic scorer/Gate still dispose. Offline + keyless; cold start (no memory) is a no-op.
    if store is not None:
        chosen, leaned, avoided = _apply_memory(store, brief, chosen, valid_feats)
        memory_leaned, memory_avoided = leaned, avoided
        if avoided:
            notes.append(f"memory: avoided recently-dead feature structure(s): {avoided}")
        if leaned:
            notes.append(f"memory: leaned toward winning feature pattern(s): {leaned}")

    if chosen:
        spec.entry = _entry_from_features(chosen, spec)

    spec.name = _title(brief, base)
    spec.rationale = brief.strip()[:400] or spec.rationale

    issues = validate_spec(spec)

    # Structural novelty — the "never try the same strategy twice" guard. The deterministic novelty_gate (offline,
    # keyless) rejects a candidate that is too close to a recently-killed dead-end or too complex. For the AGENT
    # batch author this is a HARD reject (so the master can fan out hundreds of briefs without flooding the Gate's
    # multiple-testing budget with near-duplicates); for a HUMAN it is advisory (a note) — re-running a known
    # structure on purpose is a legitimate human choice. Skipped with no store (cold start / tests). Advisory only:
    # a read hiccup never breaks authoring (the deterministic Gate still disposes).
    novelty_ok, novelty_reason = True, "novel"
    if store is not None:
        try:
            from cosmu.knowledge.memory import novelty_gate

            novelty_ok, novelty_reason = novelty_gate(spec, store)
        except Exception as exc:  # noqa: BLE001 — novelty is advisory plumbing; a hiccup must not break authoring
            notes.append(f"novelty check unavailable ({type(exc).__name__})")
        else:
            if not novelty_ok:
                notes.append(f"novelty: {novelty_reason}")
                if authored_by == "agent":
                    issues = [*issues, f"not_novel:{novelty_reason}"]

    entry_feats = [c.feature.name for c in spec.entry]
    sources = sorted({_SOURCE_BY_FEATURE.get(f, "parquet_bars") for f in entry_feats})
    requires_approval = any(k in text for k in ("go live", "live", "real money", "real capital", "fund", "deploy capital"))

    guardrails = [
        "structure only — thresholds live in param_space, fit from data (no magic numbers)",
        "the scorer and gates judge it; they stay out of this authoring path",
        "money-adjacent changes require explicit approval" if requires_approval else "draft is research-only; live capital stays gated",
    ]
    if not llm_enabled:
        notes.append("model router disabled (no key) — deterministic template match used")
    # The spec builder GUARANTEES no magic numbers (thresholds are ParamRefs into param_space) regardless of who
    # proposed the structure; re-validate so an LLM proposal is held to the exact same static_check bar.
    if "literal_threshold" in issues or any(i.startswith("unknown_feature") for i in issues):
        notes.append("proposed structure failed static_check — see issues")

    return AuthorDraft(
        spec=spec,
        rationale=spec.rationale,
        base_template=base,
        features=entry_feats,
        data_sources=sources,
        venues=spec.universe.venues,
        valid=not issues,
        issues=issues,
        requires_approval=requires_approval,
        authored_by=authored_by,
        novelty_ok=novelty_ok,
        novelty_reason=novelty_reason,
        guardrails=guardrails,
        notes=notes,
        memory_avoided=memory_avoided,
        memory_leaned=memory_leaned,
        research_features=[f for f in (prior_art or []) if f in entry_feats],
        research_citations=research_cites,
    )


def _llm_propose(brief: str, *, store: Store | None, chat):  # noqa: ANN001, ANN202
    """Ask the model (via the tier router) for a STRUCTURED proposal. Returns (LlmProposal | None, notes). Never
    raises into authoring — any failure degrades to the deterministic path. Reads the OpenRouter key from
    settings (server-side) unless an explicit `chat` seam is injected (tests). Structure-only; Gate disposes."""
    try:
        from cosmu.config.settings import get_settings
        from cosmu.lab.router import route_and_propose

        # Vocab the model is allowed to pick from — the full registry (the spec builder re-validates per asset).
        valid_features = [f.name for f in FEATURE_REGISTRY if f.enabled]
        settings = store.settings if store is not None else get_settings()
        result = route_and_propose(
            brief,
            valid_features=valid_features,
            spend=settings.spend,
            api_key=settings.llm_api_key,        # xAI (Grok) if set, else OpenRouter — centralized in settings
            provider=settings.llm_provider,
            chat=chat,
            store=store,  # records llm_calls row; best-effort, None-safe
        )
        return result.proposal, result.notes
    except Exception as exc:  # noqa: BLE001 — the LLM seam is advisory; a hiccup falls back to the template path
        return None, [f"llm proposal unavailable ({type(exc).__name__}) — deterministic fallback"]


def _apply_memory(
    store: Store,
    brief: str,
    chosen: list[str],
    valid_feats: set[str],
) -> tuple[list[str], list[str], list[str]]:
    """Re-rank the candidate feature set against long-term memory. DROP a feature that appears in a recalled
    DEAD-END structure (unless it is also in a recalled winner — a feature can be good in a different structure);
    LEAN toward (append) features from recalled WINNER patterns and from high-grade distilled skills, validated
    to the asset class. Returns (chosen, leaned, avoided). Deterministic; never raises into the author."""
    try:
        from cosmu.knowledge.memory import GraveyardMemory
        from cosmu.lab.curator import skill_feature_priors

        recall = GraveyardMemory(store).recall(brief, k=5)
    except Exception:  # noqa: BLE001 — memory is advisory; a read hiccup must not break authoring
        return chosen, [], []

    dead_feats: set[str] = set()
    for hit in recall.dead_ends:
        dead_feats.update(hit.structure.get("entry_features", []))
    winner_feats: list[str] = []
    for hit in recall.winners:
        for f in hit.structure.get("entry_features", []):
            if f in valid_feats and f not in winner_feats:
                winner_feats.append(f)

    # A feature is only "dead" if memory has NOT also seen it win — that keeps the brain from over-pruning.
    avoid = sorted({f for f in chosen if f in dead_feats and f not in winner_feats})
    kept = [f for f in chosen if f not in avoid]

    # Lean: winner-pattern features first, then high-grade skill features, deduped and asset-class-validated.
    leaned: list[str] = []
    skill_priors = skill_feature_priors(store)
    skill_feats = [f for f, _ in sorted(skill_priors.items(), key=lambda kv: kv[1], reverse=True)]
    for f in [*winner_feats, *skill_feats]:
        if f in valid_feats and f not in kept and f not in avoid and f not in leaned:
            leaned.append(f)

    new_chosen = kept + leaned
    # Never leave the entry empty AND never silently re-walk the dead structure: if avoidance emptied the set and
    # memory offered no winner/skill lean, steer to a neutral, gate-agnostic momentum feature (ret_Nd) that is
    # valid for the asset class — a different structure than the dead one. Only if THAT is unavailable do we keep
    # the original (the author still produced a valid proposal; the Gate disposes).
    if not new_chosen:
        if avoid and "ret_Nd" in valid_feats:
            new_chosen = ["ret_Nd"]
            leaned = leaned or ["ret_Nd"]
        else:
            new_chosen = leaned or chosen
    return new_chosen, leaned, avoid


def _pick_asset(text: str) -> tuple[str, str | None]:
    for key, (asset, venue) in _ASSET_HINTS.items():
        if key in text:
            return asset, venue
    return "crypto", None


def _detect_features(text: str) -> list[str]:
    out: list[str] = []
    for key, feature in _FEATURE_HINTS.items():
        if key in text and feature not in out:
            out.append(feature)
    return out


def _entry_from_features(features: list[str], spec: StrategySpec) -> list[Condition]:
    conditions: list[Condition] = []
    new_space: dict[str, ParamSpace] = {}
    for i, feature in enumerate(features[:4]):
        pname = f"th_{feature}_{i}"
        op = "lt" if feature in {"rsi"} else "gt"
        lo, hi = (15.0, 45.0) if feature in {"rsi", "adx"} else (-1.0, 1.0)
        conditions.append(Condition(feature=FeatureRef(name=feature), op=op, threshold=ParamRef(param=pname)))
        new_space[pname] = ParamSpace(kind="float", lo=lo, hi=hi)
    # keep exit params, replace entry params
    for key in list(spec.param_space):
        if key.startswith("th_") or key in {"entry_ret", "lookback", "mom_floor", "rsi_floor"}:
            continue
        new_space[key] = spec.param_space[key]
    spec.param_space = new_space
    return conditions


def _title(brief: str, base: str) -> str:
    words = brief.strip().split()
    short = " ".join(words[:6]) if words else base.replace("_", " ").title()
    return f"{short[:48]} (chat)"
