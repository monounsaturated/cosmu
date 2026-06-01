# intent: turn a plain-language brief into a typed, validated StrategySpec draft so a human can author/suggest strategies in chat (LLM-optional); inputs: brief text + optional feature/venue picks; outputs: AuthorDraft (spec + data sources + guardrail report); invariants: the draft only authors STRUCTURE — thresholds stay in param_space (no magic numbers), money-adjacent intent is flagged for approval, and the scorer/gates are never in this path.

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.config.feature_registry import FEATURE_REGISTRY, features_for
from cosmu.evolution.seeder import (
    seed_breakout_spec,
    seed_carry_spec,
    seed_meanrev_spec,
    seed_momentum_spec,
)
from cosmu.strategy.spec import Condition, FeatureRef, ParamRef, ParamSpace, StrategySpec
from cosmu.strategy.static_check import validate_spec

_SOURCE_BY_FEATURE = {f.name: f.source for f in FEATURE_REGISTRY}

# brief keyword → registry feature (the LLM-free intent map; an LLM slots in here when a key is set)
_FEATURE_HINTS: dict[str, str] = {
    "rsi": "rsi", "oversold": "rsi", "overbought": "rsi",
    "funding": "funding_rate", "basis": "perp_spot_basis", "open interest": "open_interest",
    "momentum": "ret_Nd", "trend": "ret_Nd", "breakout": "ret_Nd", "return": "ret_Nd",
    "volatility": "vol_realized", "vol": "vol_realized",
    "adx": "adx", "bollinger": "bb_z", "band": "bb_z", "atr": "atr",
    "vix": "vix_term_slope", "dollar": "dxy", "dxy": "dxy",
    "odds": "pm_implied_prob", "probability": "pm_implied_prob",
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
    guardrails: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def draft_from_brief(
    brief: str,
    *,
    features: list[str] | None = None,
    venues: list[str] | None = None,
    llm_enabled: bool = False,
) -> AuthorDraft:
    text = brief.lower()
    notes: list[str] = []

    # 1) pick a base template from intent
    if any(k in text for k in ("revert", "reversion", "oversold", "mean", "dip", "bounce")):
        spec, base = seed_meanrev_spec(), "mean_reversion"
    elif any(k in text for k in ("funding", "carry", "basis", "leverage")):
        spec, base = seed_carry_spec(), "carry"
    elif any(k in text for k in ("momentum", "trend", "breakout")):
        spec, base = seed_momentum_spec(), "momentum"
    else:
        spec, base = seed_breakout_spec(), "breakout"
    spec = spec.model_copy(deep=True)

    # 2) retarget universe from asset intent or explicit venues
    asset_class, venue = _pick_asset(text)
    if venues:
        spec.universe.venues = venues
    elif venue:
        spec.universe.venues = [venue]
        spec.universe.asset_classes = [asset_class]

    # 3) horizon hints
    if any(k in text for k in ("intraday", "hourly", "1h", "scalp")):
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

    # 5) feature picks: explicit list (from UI) or detected from the brief, validated to the asset class
    valid_feats = {f.name for f in features_for(spec.universe.asset_classes)}
    wanted = features or _detect_features(text)
    chosen = [f for f in wanted if f in valid_feats]
    rejected = [f for f in wanted if f and f not in valid_feats]
    if rejected:
        notes.append(f"ignored features not valid for {spec.universe.asset_classes}: {rejected}")
    if chosen:
        spec.entry = _entry_from_features(chosen, spec)

    spec.name = _title(brief, base)
    spec.rationale = brief.strip()[:400] or spec.rationale

    issues = validate_spec(spec)
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
        guardrails=guardrails,
        notes=notes,
    )


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
