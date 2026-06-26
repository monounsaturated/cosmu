# intent: the NL→strategy pipeline's GROUNDING step — map the Thinker's modern feature TERMS onto the real,
# enabled FEATURE_REGISTRY (cosmu.config.feature_registry) DETERMINISTICALLY first. A term that resolves to an
# enabled registry feature becomes a matched_feature the Author can build structure from; a term that has no
# registry home (an 'astrological era', a 'recession regime', a raw 'market regime') is an UNMAPPED CLAIM the
# SignalBuilder turns into a PrecomputedSignal spec (routed as an alt-data feature). inputs: a ThinkingReport;
# outputs: a MatcherResult(matched_features, unmapped_claims). invariants: deterministic, offline, no LLM, no
# network; only EVER references enabled=True features (a disabled/dead feature is never matched — same honesty
# rule the registry↔route guard enforces); the registry is read-only. NEVER on a money path.

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names

# Enabled registry feature names (the only legal match targets) and a per-feature lookup for metadata.
_ENABLED_NAMES = feature_names()
_FEATURE_BY_NAME = {f.name: f for f in FEATURE_REGISTRY}

# Synonym map: a Thinker TERM (modern vocab the standardizer emits) → an enabled registry feature name. The
# Thinker already speaks mostly-registry terms, so most entries are identity; the rest fold common aliases an
# old book / vibe would use onto the canonical name. Only enabled features appear as values (filtered below).
_TERM_TO_FEATURE: dict[str, str] = {
    # momentum / trend family
    "momentum": "ret_Nd", "trend": "ret_Nd", "breakout": "ret_Nd", "return": "ret_Nd",
    "moving_average": "ret_Nd", "xsec_momentum": "xsec_momentum_rank",
    # mean-reversion / oscillators
    "mean_reversion": "rsi", "rsi": "rsi", "relative_strength": "rsi",
    "bb_z": "bb_z", "bollinger": "bb_z", "bands": "bb_z",
    "adx": "adx", "atr": "atr",
    # volatility
    "vol_realized": "vol_realized", "volatility": "vol_realized", "vol": "vol_realized",
    # crypto microstructure / carry
    "funding_rate": "funding_rate", "funding": "funding_rate", "carry": "funding_rate",
    "perp_spot_basis": "perp_spot_basis", "basis": "perp_spot_basis",
    "open_interest": "open_interest", "leverage": "open_interest",
    # sentiment / crowd
    "fear_greed": "fear_greed", "news_sentiment": "news_sentiment", "sentiment": "news_sentiment",
    "reddit_sentiment": "reddit_sentiment", "social_sentiment": "social_sentiment",
    "social_volume": "social_volume",
    # macro / cross-asset
    "vix_level": "vix_level", "vix": "vix_level", "vix_term_slope": "vix_term_slope",
    "dxy": "dxy", "dollar": "dxy", "fed_funds_rate": "fed_funds_rate", "rates": "fed_funds_rate",
    "yield_curve_2s10s": "yield_curve_2s10s", "credit_spread": "credit_spread",
    "macro_regime": "macro_regime", "defi_tvl": "defi_tvl",
    "pm_risk_on": "pm_risk_on",
    # prediction-market odds
    "pm_implied_prob": "pm_implied_prob", "odds": "pm_implied_prob", "probability": "pm_implied_prob",
    # OSINT
    "osint_air_activity": "osint_air_activity",
}

# Terms that are deliberately NOT registry-mappable — complex CLAIMS routed to the SignalBuilder as a
# PrecomputedSignal spec. Listed so they are reported as unmapped_claims (not silently dropped).
_KNOWN_COMPLEX_CLAIMS = frozenset(
    {"astrological_era", "recession_regime", "market_regime", "bull_market", "bear_market", "business_cycle"}
)


@dataclass
class MatcherResult:
    """The grounding of a ThinkingReport against the real feature vocabulary.

    `matched_features` are enabled registry feature names the Author can build structure from.
    `unmapped_claims` are complex/abstract terms with no registry home → the SignalBuilder's input.
    `notes` is the audit trail (what resolved, what didn't, what was dropped as disabled).
    """

    matched_features: list[str]
    unmapped_claims: list[str]
    notes: list[str] = field(default_factory=list)


def _normalize(term: str) -> str:
    return term.strip().lower().replace(" ", "_").replace("-", "_")


def match(report) -> MatcherResult:  # noqa: ANN001 — ThinkingReport (avoid an import cycle with cosmu.mind.thinker)
    """Resolve a ThinkingReport's recommended feature terms to enabled registry features (deterministic-first).
    Unresolved terms become unmapped_claims for the SignalBuilder. Order-preserving + de-duplicated. Offline,
    never raises, only references enabled features."""
    matched: list[str] = []
    unmapped: list[str] = []
    notes: list[str] = []

    for raw_term in getattr(report, "recommended_features", []) or []:
        term = _normalize(str(raw_term))
        if not term:
            continue

        # 1) direct registry name (already canonical) — accept only if enabled.
        if term in _ENABLED_NAMES:
            if term not in matched:
                matched.append(term)
            continue

        # 2) synonym → canonical registry name.
        canonical = _TERM_TO_FEATURE.get(term)
        if canonical and canonical in _ENABLED_NAMES:
            if canonical not in matched:
                matched.append(canonical)
            continue

        # 3) the term names a registry feature that exists but is DISABLED → never match (honesty); report it.
        if term in _FEATURE_BY_NAME and term not in _ENABLED_NAMES:
            notes.append(f"term '{term}' maps to a DISABLED feature — not matched")
            if term not in unmapped:
                unmapped.append(term)
            continue
        if canonical and canonical in _FEATURE_BY_NAME and canonical not in _ENABLED_NAMES:
            notes.append(f"term '{term}'→'{canonical}' is DISABLED — not matched")
            if term not in unmapped:
                unmapped.append(term)
            continue

        # 4) no registry home → unmapped claim (the SignalBuilder turns these into PrecomputedSignal specs).
        if term not in unmapped:
            unmapped.append(term)
        if term in _KNOWN_COMPLEX_CLAIMS:
            notes.append(f"complex claim '{term}' → SignalBuilder (precomputed alt-data signal)")
        else:
            notes.append(f"unmapped term '{term}' → SignalBuilder candidate")

    if matched:
        notes.append(f"matched {len(matched)} registry feature(s): {matched}")
    return MatcherResult(matched_features=matched, unmapped_claims=unmapped, notes=notes)
