# intent: derive a strategy's faceted taxonomy (signal-family, asset class, venue, timeframe, edge-type)
# from its typed spec — NEVER from a manual tag. inputs: a StrategySpec (or its dict form) + the version
# origin; outputs: a flat Facets record the leaderboard surfaces. invariants: signal-family is a pure
# function of the named features the spec references (feature_registry → source), so it can never drift
# from the strategy's actual inputs; price-only strategies fall back to Math/Price.

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from cosmu.config.feature_registry import FEATURE_REGISTRY

SignalFamily = Literal["social", "news_events", "math_price", "macro_positioning", "onchain_flow"]

# Human labels for the five signal-families (the primary leaderboard filter, VISION taxonomy).
SIGNAL_FAMILY_LABELS: dict[str, str] = {
    "social": "Social",
    "news_events": "News/Events",
    "math_price": "Math/Price",
    "macro_positioning": "Macro/Positioning",
    "onchain_flow": "On-chain/Flow",
}

# Source → signal-family. The feature_registry already records every feature's `source`; we classify the
# source once, so adding a feature under a known source inherits its family for free. A handful of feature
# NAMES override the source default where one source mints features of two families (e.g. llm_index mints
# a regulatory-news index AND a macro risk-on/off index; fundamentals_vendor mints an earnings DATE event
# alongside positioning ratios).
_SOURCE_FAMILY: dict[str, SignalFamily] = {
    # On-chain / flow: leverage, positioning plumbing, and money movement on crypto venues.
    "ccxt": "onchain_flow",
    "exchange": "onchain_flow",
    "coinglass": "onchain_flow",
    "defillama": "onchain_flow",
    "polymarket": "onchain_flow",
    "polymarket_clob": "onchain_flow",
    # Math / price: features computed purely from the bar tape.
    "parquet_bars": "math_price",
    # Macro / positioning: rates, the dollar, cross-asset levels, vol indices, regulated positioning reports.
    "fred": "macro_positioning",
    "fred/cboe": "macro_positioning",
    "cboe": "macro_positioning",
    "stooq": "macro_positioning",
    "cftc": "macro_positioning",
    "deribit": "macro_positioning",
    "fundamentals_vendor": "macro_positioning",
    "sec_edgar": "macro_positioning",
    # Social: crowd sentiment feeds.
    "reddit": "social",
    "lunarcrush": "social",
    "xai": "social",
    "alternative.me": "social",
    # News / events: headlines, geopolitical tone, LLM narrative indices.
    "news": "news_events",
    "news_headlines": "news_events",
    "gdelt": "news_events",
    "llm_index": "news_events",
}

# Feature-name overrides where one source spans two families.
_FEATURE_FAMILY_OVERRIDE: dict[str, SignalFamily] = {
    "risk_on_off": "macro_positioning",   # llm_index, but a cross-asset macro regime tag
    "pm_risk_on": "macro_positioning",    # polymarket odds used as a risk-regime tag, not flow
    "days_to_earnings": "news_events",    # fundamentals_vendor, but an event-calendar feature
}

_FEATURE_TO_SOURCE: dict[str, str] = {f.name: f.source for f in FEATURE_REGISTRY}


def family_of_feature(name: str) -> SignalFamily | None:
    """The signal-family a single named feature belongs to, or None if it isn't in the registry."""
    if name in _FEATURE_FAMILY_OVERRIDE:
        return _FEATURE_FAMILY_OVERRIDE[name]
    source = _FEATURE_TO_SOURCE.get(name)
    if source is None:
        return None
    return _SOURCE_FAMILY.get(source)


class Facets(BaseModel):
    """The faceted taxonomy a leaderboard row carries. Every field is DERIVED from the spec — none is a
    hand-applied tag — so the Strategies filters always reflect the strategy's real inputs and structure."""

    signal_family: SignalFamily
    signal_family_label: str
    features: list[str]
    asset_class: str
    venue: str
    timeframe: str
    origin: str
    edge_type: str


def _referenced_features(spec: dict[str, Any]) -> list[str]:
    """Every named feature the spec references: entry conditions, exit signal-exits, and the funding leg.
    Order-preserving, de-duplicated — this is the evidence the signal-family is derived from."""
    names: list[str] = []

    def _push(name: Any) -> None:
        if isinstance(name, str) and name and name not in names:
            names.append(name)

    def _feat_name(cond: Any) -> None:
        feature = cond.get("feature") if isinstance(cond, dict) else None
        if isinstance(feature, dict):
            _push(feature.get("name"))

    entry = spec.get("entry")
    for cond in entry if isinstance(entry, list) else []:
        _feat_name(cond)
    exit_rules = spec.get("exit") if isinstance(spec.get("exit"), dict) else {}
    sig_exits = exit_rules.get("signal_exits")
    for cond in sig_exits if isinstance(sig_exits, list) else []:
        _feat_name(cond)
    _push(spec.get("funding_feature"))
    return names


def _signal_family(features: list[str]) -> SignalFamily:
    """Pick the strategy's PRIMARY signal-family from its referenced features. Price/math features are
    ubiquitous (almost every strategy uses ATR/RSI to shape entries), so the defining family is the most
    common NON-price alt-data family it references; a strategy that touches only the bar tape is Math/Price."""
    counts: dict[SignalFamily, int] = {}
    for name in features:
        family = family_of_feature(name)
        if family is None or family == "math_price":
            continue
        counts[family] = counts.get(family, 0) + 1
    if not counts:
        return "math_price"
    # Most-referenced alt-data family wins; ties break by a stable family order so the result is deterministic.
    order: list[SignalFamily] = ["onchain_flow", "macro_positioning", "news_events", "social"]
    return max(counts, key=lambda fam: (counts[fam], -order.index(fam)))


def _edge_type(spec: dict[str, Any], features: list[str]) -> str:
    """A best-effort, deterministic read of the trade's STRUCTURAL edge from the spec — what kind of bet it
    is, orthogonal to which data it reads. Heuristic and honest (it inspects setup legs, the funding leg,
    and the referenced features in priority order), never a hand-applied label."""
    feature_set = set(features)
    setup = spec.get("setup") or {}
    # Carry: a funding leg or basis/OI plumbing is the P&L driver.
    if spec.get("funding_feature") or feature_set & {"funding_rate", "perp_spot_basis", "open_interest"}:
        return "carry"
    # Breakout: an opening-range or fair-value-gap setup leg.
    if setup.get("orb") or setup.get("fvg"):
        return "breakout"
    # Event-driven: a dated catalyst feature.
    if feature_set & {"news_event_score", "news_sentiment", "days_to_earnings", "reg_risk_crypto", "liquidation_cascade"}:
        return "event"
    # Mean-reversion: overextension / crowd-fear features fading a move.
    if feature_set & {"rsi", "bb_z", "fear_greed", "putcall_ratio", "social_sentiment", "reddit_sentiment"}:
        return "mean-reversion"
    # Momentum / trend: relative-strength, trend, or a trend filter.
    if setup.get("ma_trend_filter") or feature_set & {"ret_Nd", "xsec_momentum_rank", "adx"}:
        return "momentum"
    return "structural"


def _primary(values: list[str]) -> str:
    """One representative value for a list facet (asset class / venue): the single value, or 'multi'."""
    cleaned = [v for v in values if isinstance(v, str) and v]
    if not cleaned:
        return "—"
    if len(set(cleaned)) == 1:
        return cleaned[0]
    return "multi"


def derive_facets(spec: dict[str, Any] | None, origin: str | None) -> Facets:
    """Derive the full faceted taxonomy from a spec dict + the version's origin. Tolerant of partial specs
    (returns honest '—' placeholders) so a malformed row still renders rather than crashing the leaderboard."""
    if not isinstance(spec, dict):
        spec = {}
    try:
        # Nested fields can be STRINGS on a double-encoded spec row (a prod write-path quirk). Coerce each to its
        # expected type so a malformed row degrades to honest '—' placeholders rather than 500-ing the leaderboard
        # (the FLOOR display must never crash on one bad spec).
        universe = spec.get("universe") if isinstance(spec.get("universe"), dict) else {}
        horizon = spec.get("horizon") if isinstance(spec.get("horizon"), dict) else {}
        features = _referenced_features(spec)
        family = _signal_family(features)
        return Facets(
            signal_family=family,
            signal_family_label=SIGNAL_FAMILY_LABELS[family],
            features=features,
            asset_class=_primary(universe.get("asset_classes") or []),
            venue=_primary(universe.get("venues") or []),
            timeframe=str(horizon.get("bar_size") or "—"),
            origin=origin or "template",
            edge_type=_edge_type(spec, features),
        )
    except Exception:  # noqa: BLE001 — never let a malformed spec crash the leaderboard; show honest placeholders.
        fam = _signal_family([])
        return Facets(
            signal_family=fam, signal_family_label=SIGNAL_FAMILY_LABELS[fam], features=[],
            asset_class="—", venue="—", timeframe="—", origin=origin or "template", edge_type="—",
        )
