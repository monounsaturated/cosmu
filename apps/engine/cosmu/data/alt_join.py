# intent: ONE point-in-time alt-data join used by every screen path (the FarmLoop cohort screen AND the Strategy
# Finder sweep) so a funding/leading-signal spec is evaluated identically wherever it is screened. inputs: a spec
# + the per-symbol bar series + an alt-data store; outputs: symbol → feature → {bar.ts.isoformat(): value}, the
# join `run_strategy_backtest` consumes. invariants: as-of only (align_asof keeps available_at <= bar.ts — no
# look-ahead), a missing/erroring series is simply omitted (the feature reads None, never a fabricated value),
# and the feature universe comes from the registry at runtime (price features are computed from bars, never
# joined). This is the single source of truth for "which alt features does this spec need joined".

from __future__ import annotations

from cosmu.config.feature_registry import feature_names
from cosmu.data.altdata import StoreBackedAltProvider
from cosmu.data.backtest import PRICE_FEATURES, align_asof
from cosmu.data.market import Bar
from cosmu.strategy.spec import StrategySpec

# How many trailing alt points to pull per (symbol, feature) before the as-of join. Generous (covers >1yr at any
# ingest frequency) so align_asof always has its full window; bounded so a runaway series can't blow up memory.
_ALT_HISTORY_LIMIT = 100_000


def alt_feature_universe() -> set[str]:
    """The leading-signal (alt-data) feature names: every enabled registry feature MINUS the ones the backtest
    computes itself from bars (PRICE_FEATURES). Read from the registry at runtime so a newly registered+ingested
    feature is wired automatically, and the price/alt split has a single source of truth (PRICE_FEATURES)."""
    return feature_names() - PRICE_FEATURES


def spec_alt_feature_names(spec: StrategySpec) -> set[str]:
    """Every alt-data feature THIS spec needs joined: entry + signal-exit condition features, the perp-funding
    carry leg (`funding_feature`), AND the secondary meta-label model's features — intersected with the alt
    universe (price features are computed, not joined). The meta-label inclusion is what lets the secondary
    classifier read funding (and any other alt feature) point-in-time; without it the gate would see None and
    stay inert."""
    used = {c.feature.name for c in [*spec.entry, *spec.exit.signal_exits]}
    funding = getattr(spec, "funding_feature", None)
    if funding:
        used.add(funding)
    meta = getattr(spec, "meta_label", None)
    if meta is not None:
        used |= {ref.name for ref in meta.features}
    return used & alt_feature_universe()


def build_alt_by_symbol(
    alt_store: object, spec: StrategySpec, market: dict[str, list[Bar]]
) -> dict[str, dict[str, dict[str, float]]] | None:
    """Build the per-symbol point-in-time alt-data join for every alt feature `spec` uses. `alt_store` is the
    resolved store (JSONL or Postgres). Returns None when the spec needs no alt features or no store is usable
    (price-only screen, unchanged). A feature with no provider route or no stored data is omitted (the backtest
    reads None and its condition / meta feature simply can't contribute — honest, never fabricated). Never
    raises: a per-feature fetch error degrades to no data for that feature, not a crashed screen."""
    names = spec_alt_feature_names(spec)
    if not names:
        return None
    try:
        provider = StoreBackedAltProvider(alt_store)
    except Exception:  # noqa: BLE001 — no usable alt store → price-only screen, never abort
        return None
    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        feats: dict[str, dict[str, float]] = {}
        for name in names:
            try:
                points = provider.fetch_series(symbol, name, limit=_ALT_HISTORY_LIMIT)
            except Exception:  # noqa: BLE001 — a missing/erroring series is just no data for that feature
                points = []
            aligned = align_asof(points, bars)
            if aligned:
                feats[name] = aligned
        if feats:
            out[symbol] = feats
    return out or None


def resolve_alt_store(settings: object, store: object) -> object:
    """Pick the alt-data store the SAME way ingest/api/the loop do: a Postgres URL → PgAltDataStore over the
    knowledge Store, else the JSONL AltDataStore."""
    url = getattr(settings, "database_url", "") or ""
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        from cosmu.data.altdata import PgAltDataStore

        return PgAltDataStore(store)
    from cosmu.data.altdata import AltDataStore

    return AltDataStore()
