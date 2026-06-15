# intent: the NL→strategy pipeline's CLAIM-GROUNDING step — turn a complex, non-registry claim the Matcher
# couldn't resolve ('astrological eras', 'bull/bear regime', 'recession') into a TYPED PrecomputedSignal SPEC:
# a description of an alt-data feature to compute LATER, not the computation itself. inputs: an unmapped claim
# (plus the ThinkingReport for context); outputs: a PrecomputedSignal (name + the alt-data provider/metric route
# + a frozen-once transform_version stub + a prior + a disconfirmer). invariants: NO HEAVY COMPUTE here (the
# 16GB M2 must never run an ephemeris / regime-fit in this path) — it EMITS the spec only; the route follows the
# alt-data feature convention (a provider/metric a real ingest source would later fill); offline, deterministic,
# no LLM, no network; every emitted signal ships its OWN disconfirmer (the astro lesson — a periodic/deterministic
# claim must be tested for non-causality before it earns a place). NEVER on a money path.

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Known complex-claim families → a typed alt-data signal route. Each entry is a (provider, metric, prior,
# disconfirmer) the SignalBuilder stamps onto the PrecomputedSignal. These are SPECS — a real ingest source must
# still be wired before the feature carries any data; until then it is dormant (the registry↔route honesty rule).
# The astro family carries a HARD non-causal-control disconfirmer because periodic deterministic inputs are the
# classic spurious-regression trap (see the astro deep-dive: lead-lag symmetry, rotation null, OOS sign-flip).
_CLAIM_FAMILIES: dict[str, dict] = {
    "astrological_era": {
        "provider": "ephemeris",
        "metric": "astro_era_phase",
        "asset_classes": ["crypto", "equity"],
        "prior": "An 'astrological era' is a deterministic calendar phase; treated as a NON-CAUSAL control feature — must beat a phase-shifted null before it earns a place.",
        "disconfirmer": "Effect is identical at lead and lag (lead-lag SYMMETRY) or vanishes under a phase-rotation null and OOS split — i.e. spurious periodic regression, not an edge.",
    },
    "recession_regime": {
        "provider": "fred",
        "metric": "recession_regime_flag",
        "asset_classes": ["equity", "crypto"],
        "prior": "A recession/contraction regime tag derived from macro releases (e.g. NBER-style indicators); conditions risk premia rather than timing a single asset.",
        "disconfirmer": "Conditioning on the regime adds no out-of-sample IC over the unconditional baseline, or the regime is only knowable with hindsight (look-ahead in the dating).",
    },
    "market_regime": {
        "provider": "parquet_bars",
        "metric": "bull_bear_regime",
        "asset_classes": ["crypto", "equity"],
        "prior": "A bull/bear regime tag derived point-in-time from trailing price (e.g. trend/drawdown state); a conditioning context, not a standalone trigger.",
        "disconfirmer": "The regime split adds no OOS edge over the unconditional return, or the labeling peeks at future bars (the regime must be computed from PAST data only).",
    },
}

# Aliases so the Matcher's varied claim spellings land on a family.
_CLAIM_ALIASES: dict[str, str] = {
    "astrological_era": "astrological_era", "astrology": "astrological_era", "lunar": "astrological_era",
    "planetary": "astrological_era", "zodiac": "astrological_era", "era": "astrological_era", "cycle": "astrological_era",
    "recession": "recession_regime", "recession_regime": "recession_regime", "contraction": "recession_regime",
    "business_cycle": "recession_regime",
    "market_regime": "market_regime", "bull_market": "market_regime", "bear_market": "market_regime",
    "bull_bear": "market_regime", "regime": "market_regime",
}

# Frozen-once transform-version stub: pins the (future) computation of a precomputed signal so a gate-passed
# survivor that rests on it stays re-runnable byte-for-byte (mirrors the registry's transform_version contract).
_TRANSFORM_PREFIX = "nl-precomputed"


@dataclass
class PrecomputedSignal:
    """A TYPED SPEC for an alt-data feature to compute later — NOT the computation.

    `name` is the proposed feature name (alt-data route). `provider`/`metric` name where a real ingest source
    would write it (the alt-data feature convention). `asset_classes` scopes it. `prior` is the hypothesis,
    `disconfirmer` its kill condition. `transform_version` pins the (future) transform. `source_claim` is the
    raw Matcher claim it grounds (audit trail). `computed` is ALWAYS False here — this path emits specs only.
    """

    name: str
    provider: str
    metric: str
    asset_classes: list[str]
    prior: str
    disconfirmer: str
    transform_version: str
    source_claim: str
    computed: bool = False
    notes: list[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "claim"


def _resolve_family(claim: str) -> str | None:
    norm = _slug(claim)
    if norm in _CLAIM_FAMILIES:
        return norm
    if norm in _CLAIM_ALIASES:
        return _CLAIM_ALIASES[norm]
    # substring fallback (an old book says 'planets align' → astrological_era)
    for alias, family in _CLAIM_ALIASES.items():
        if alias in norm:
            return family
    return None


def build_signal(claim: str, report=None) -> PrecomputedSignal:  # noqa: ANN001 — optional ThinkingReport context
    """Turn ONE unmapped claim into a typed PrecomputedSignal spec. A known claim family gets its canonical
    route + prior + hard disconfirmer; an unknown claim becomes a generic, low-confidence alt-data spec that
    MUST earn its place out-of-sample. Deterministic, offline, emits a spec only — never computes anything."""
    family = _resolve_family(claim)
    notes: list[str] = []
    if family is not None:
        meta = _CLAIM_FAMILIES[family]
        notes.append(f"claim '{claim}' → known family '{family}'")
        return PrecomputedSignal(
            name=f"nl_{family}",
            provider=meta["provider"],
            metric=meta["metric"],
            asset_classes=list(meta["asset_classes"]),
            prior=meta["prior"],
            disconfirmer=meta["disconfirmer"],
            transform_version=f"{_TRANSFORM_PREFIX}-{family}-v1",
            source_claim=claim,
            notes=notes,
        )

    # Unknown claim → a generic, low-confidence alt-data spec (honest: no real source yet, must earn OOS).
    slug = _slug(claim)
    disconfirmer = (
        getattr(report, "disconfirmer", "") if report is not None else ""
    ) or "No out-of-sample IC net of fees, or the signal is non-causal (symmetric lead-lag) — then drop it."
    notes.append(f"claim '{claim}' has no known family → generic low-confidence alt-data spec (dormant until a source is wired)")
    return PrecomputedSignal(
        name=f"nl_{slug}",
        provider="nl_precomputed",
        metric=slug,
        asset_classes=["crypto", "equity"],
        prior=f"Operator/document claim '{claim}' — low-confidence; routed as an alt-data feature that must earn its place out-of-sample.",
        disconfirmer=disconfirmer[:280],
        transform_version=f"{_TRANSFORM_PREFIX}-{slug}-v1",
        source_claim=claim,
        notes=notes,
    )


def build_signals(claims: list[str], report=None) -> list[PrecomputedSignal]:  # noqa: ANN001
    """Map every unmapped claim to a PrecomputedSignal spec, de-duplicated by emitted name (the same family from
    two phrasings collapses to one spec)."""
    out: list[PrecomputedSignal] = []
    seen: set[str] = set()
    for claim in claims or []:
        if not str(claim).strip():
            continue
        sig = build_signal(str(claim), report=report)
        if sig.name in seen:
            continue
        seen.add(sig.name)
        out.append(sig)
    return out
