# intent: the NL→strategy pipeline's REASONING step — read the parsed DocumentChunk(s) and STANDARDIZE the prose
# (a vibe, an abstract, a passage from an old trading book) into modern, computable terms: a thesis, an explicit
# edge hypothesis, a regime tag, a list of recommended (modern, named) features, and — non-negotiable — a
# disconfirmer (what would prove the edge ISN'T real). inputs: chunks + an OPTIONAL llm callable (gated behind a
# plain `prompt -> json-text` arg so the step is fully offline-testable); outputs: a typed ThinkingReport.
# invariants: the LLM ONLY translates language → it never sees the gate/scorer and cannot smuggle a threshold
# (it proposes named features + prose, the deterministic Matcher/Author downstream own structure); a missing/
# failing LLM degrades to a deterministic keyword-driven report so the pipeline runs with NO key/network; the
# disconfirmer is ALWAYS populated (the lesson from the astro studies: every hypothesis ships with its own kill
# condition). NEVER on a money path — advisory standardization only.

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cosmu.ingest.document_handler import DocumentChunk

# The LLM seam for this step: a prompt → raw JSON string (or None on failure/no-key). This is intentionally
# narrower than lab.llm.ChatFn so tests can inject a one-line lambda; the real wiring (nlp_intake) adapts a
# ChatFn to this shape. Offline → None → deterministic fallback.
InterpretFn = Callable[[str], str | None]

# Deterministic prose→modern-term hints (the keyless fallback brain). Maps language a human would use in a vibe
# or an old book to the modern, computable vocabulary the Matcher then resolves to the FEATURE_REGISTRY. This is
# NOT the registry mapping (that is the Matcher's job, deterministic-first) — it is the "what is this idea even
# about" standardizer, kept here so a no-key run still produces a usable, honest report.
_REGIME_HINTS: dict[str, str] = {
    "bull": "bull", "uptrend": "bull", "risk-on": "bull", "rally": "bull", "greed": "bull",
    "bear": "bear", "downtrend": "bear", "risk-off": "bear", "selloff": "bear", "crash": "bear", "fear": "bear",
    "recession": "recession", "contraction": "recession", "slowdown": "recession",
    "high vol": "high_volatility", "volatile": "high_volatility", "turbulent": "high_volatility",
    "sideways": "range", "chop": "range", "range-bound": "range", "consolidation": "range",
}

# prose phrase → modern recommended feature term (the Thinker's vocabulary; the Matcher resolves these to the
# registry deterministically-first). Phrases an OLD book or a vibe note would use, mapped to today's named series.
_FEATURE_TERM_HINTS: dict[str, str] = {
    "moving average": "momentum", "trend": "momentum", "momentum": "momentum", "breakout": "momentum",
    "mean revert": "mean_reversion", "reversion": "mean_reversion", "oversold": "rsi", "overbought": "rsi",
    "relative strength": "rsi", "rsi": "rsi",
    "overextend": "bb_z", "bands": "bb_z", "bollinger": "bb_z",
    "volatility": "vol_realized", "vol": "vol_realized",
    "funding": "funding_rate", "carry": "funding_rate", "basis": "perp_spot_basis",
    "open interest": "open_interest", "leverage": "open_interest",
    "fear": "fear_greed", "greed": "fear_greed", "sentiment": "news_sentiment", "headline": "news_sentiment",
    "vix": "vix_level", "dollar": "dxy", "rates": "fed_funds_rate", "yield curve": "yield_curve_2s10s",
    "credit": "credit_spread", "macro": "macro_regime",
    # complex / non-registry CLAIMS the Thinker still surfaces — the SignalBuilder turns these into a
    # PrecomputedSignal spec (routed as an alt-data feature) rather than a registry lookup.
    "astrolog": "astrological_era", "lunar": "astrological_era", "planet": "astrological_era",
    "era": "astrological_era", "cycle": "astrological_era",
    "recession": "recession_regime", "business cycle": "recession_regime",
    "bull market": "market_regime", "bear market": "market_regime",
}

_PROMPT = """You standardize a trading idea written in plain language (a vibe, an abstract, or a passage from an
old trading book) into MODERN, COMPUTABLE terms. Return STRICT JSON with keys:
  thesis (one sentence), edge_hypothesis (why an edge could exist, one sentence),
  regime (one of: bull, bear, recession, high_volatility, range, any),
  recommended_features (list of modern named-feature TERMS, e.g. momentum, rsi, funding_rate, fear_greed),
  disconfirmer (one sentence: what observation would prove this edge is NOT real).
Do NOT propose thresholds or numbers. Translate language only.

IDEA:
{text}

JSON:"""


@dataclass
class ThinkingReport:
    """The standardized, computable read of a document — the Matcher/SignalBuilder's input."""

    thesis: str
    edge_hypothesis: str
    regime: str  # bull | bear | recession | high_volatility | range | any
    recommended_features: list[str]
    disconfirmer: str
    source_chunks: list[str] = field(default_factory=list)  # chunk_ids this report distilled
    notes: list[str] = field(default_factory=list)
    via: str = "deterministic"  # "llm" | "deterministic" — audit trail of which brain produced it


def _join_text(chunks: list["DocumentChunk"]) -> str:
    return "\n\n".join(c.text for c in chunks if c.text).strip()


def _detect_regime(text: str) -> str:
    low = text.lower()
    for phrase, tag in _REGIME_HINTS.items():
        if phrase in low:
            return tag
    return "any"


def _detect_feature_terms(text: str) -> list[str]:
    low = text.lower()
    out: list[str] = []
    for phrase, term in _FEATURE_TERM_HINTS.items():
        if phrase in low and term not in out:
            out.append(term)
    return out


def _first_sentence(text: str, fallback: str) -> str:
    text = text.strip()
    if not text:
        return fallback
    m = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    return (m[0] if m else text).strip()[:280] or fallback


def _deterministic_report(text: str, chunk_ids: list[str], notes: list[str]) -> ThinkingReport:
    regime = _detect_regime(text)
    feats = _detect_feature_terms(text)
    thesis = _first_sentence(text, "Unstructured idea — no explicit thesis extracted.")
    edge = (
        f"Possible edge from {', '.join(feats[:3])}."
        if feats
        else "No computable edge term detected; idea needs a clearer hypothesis."
    )
    disconfirmer = (
        "Edge disappears (IC→0, sign-inconsistent across folds) when tested out-of-sample net of fees, "
        "or the effect is symmetric in lead-lag (non-causal)."
    )
    return ThinkingReport(
        thesis=thesis,
        edge_hypothesis=edge,
        regime=regime,
        recommended_features=feats,
        disconfirmer=disconfirmer,
        source_chunks=chunk_ids,
        notes=notes,
        via="deterministic",
    )


def _coerce_report(data: dict, chunk_ids: list[str], notes: list[str]) -> ThinkingReport | None:
    """Validate + coerce a parsed LLM JSON object into a ThinkingReport. Returns None when it isn't usable so the
    caller falls back to the deterministic brain. The disconfirmer is FORCED present (never let the model ship a
    hypothesis without its kill condition)."""
    if not isinstance(data, dict):
        return None
    feats = data.get("recommended_features") or []
    if isinstance(feats, str):
        feats = [f.strip() for f in re.split(r"[,;]", feats) if f.strip()]
    feats = [str(f).strip().lower() for f in feats if str(f).strip()]
    regime = str(data.get("regime") or "any").strip().lower()
    if regime not in {"bull", "bear", "recession", "high_volatility", "range", "any"}:
        regime = "any"
    disconfirmer = str(data.get("disconfirmer") or "").strip()
    if not disconfirmer:
        disconfirmer = (
            "Edge disappears out-of-sample net of fees, or is symmetric in lead-lag (non-causal)."
        )
        notes.append("llm omitted a disconfirmer — forced the default kill condition")
    return ThinkingReport(
        thesis=str(data.get("thesis") or "").strip()[:280] or "LLM returned no thesis.",
        edge_hypothesis=str(data.get("edge_hypothesis") or "").strip()[:280] or "LLM returned no edge hypothesis.",
        regime=regime,
        recommended_features=feats,
        disconfirmer=disconfirmer[:280],
        source_chunks=chunk_ids,
        notes=notes,
        via="llm",
    )


def _extract_json(raw: str) -> dict | None:
    raw = raw.strip()
    # Strip a ```json fence if the model wrapped it.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    # Else grab the first balanced-looking object.
    if not raw.startswith("{"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def interpret(chunks: list["DocumentChunk"], llm: InterpretFn | None = None) -> ThinkingReport:
    """Standardize parsed chunks into a ThinkingReport. When `llm` is provided it translates the prose into modern
    computable terms (prompt → JSON text); any failure (no key, network hiccup, malformed JSON, missing fields)
    degrades to the deterministic keyword brain so the pipeline ALWAYS produces a usable, honest report. The LLM
    never touches structure/thresholds — it only translates language. Offline-safe; never raises."""
    text = _join_text(chunks)
    chunk_ids = [c.chunk_id for c in chunks]
    notes: list[str] = []

    if not text:
        notes.append("no extractable text in document — empty report")
        rep = _deterministic_report("", chunk_ids, notes)
        rep.notes.append("document had no parsable content")
        return rep

    if llm is None:
        notes.append("no LLM seam — deterministic standardization used")
        return _deterministic_report(text, chunk_ids, notes)

    try:
        raw = llm(_PROMPT.format(text=text[:8000]))
    except Exception as exc:  # noqa: BLE001 — the LLM is advisory; a hiccup falls back to the keyword brain
        notes.append(f"llm interpret unavailable ({type(exc).__name__}) — deterministic fallback")
        return _deterministic_report(text, chunk_ids, notes)

    if not raw:
        notes.append("llm returned nothing — deterministic fallback")
        return _deterministic_report(text, chunk_ids, notes)

    obj = _extract_json(raw)
    report = _coerce_report(obj, chunk_ids, notes) if obj is not None else None
    if report is None:
        notes.append("llm output was not usable JSON — deterministic fallback")
        return _deterministic_report(text, chunk_ids, notes)
    return report
