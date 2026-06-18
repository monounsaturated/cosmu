# intent: ONE point-in-time alt-data join used by every screen path (the FarmLoop cohort screen AND the Strategy
# Finder sweep) so a funding/leading-signal spec is evaluated identically wherever it is screened. inputs: a spec
# + the per-symbol bar series + an alt-data store; outputs: symbol → feature → {bar.ts.isoformat(): value}, the
# join `run_strategy_backtest` consumes. invariants: as-of only (align_asof keeps available_at <= bar.ts — no
# look-ahead), a missing/erroring series is simply omitted (the feature reads None, never a fabricated value),
# and the feature universe comes from the registry at runtime (price features are computed from bars, never
# joined). This is the single source of truth for "which alt features does this spec need joined".

from __future__ import annotations

from datetime import timedelta

from cosmu.config.feature_registry import feature_names
from cosmu.data.altdata import StoreBackedAltProvider
from cosmu.data.backtest import FUNDING_ACCRUAL_KEY, PRICE_FEATURES, align_asof, sum_funding_per_bar
from cosmu.data.market import Bar
from cosmu.strategy.spec import StrategySpec

# How many trailing alt points to pull per (symbol, feature) before the as-of join. Generous (covers >1yr at any
# ingest frequency) so align_asof always has its full window; bounded so a runaway series can't blow up memory.
_ALT_HISTORY_LIMIT = 100_000

# B5 staleness guard — natural cadence per alt feature, × this many cadences = the max age align_asof will carry a
# value forward (a value staler than this is a DEAD feed, read None not carried as a live constant). Sub-daily feeds
# (funding/OI/basis settle every few hours) tolerate hours; everything else is at most daily-published, so the
# default daily cadence × N gives a few business days of slack (weekends/holidays/T+1 release) before clamping.
_STALENESS_CADENCES = 5
_SUBDAILY_FEATURES = frozenset({"funding_rate", "open_interest", "perp_spot_basis", "dvol"})


def _feature_max_age(name: str) -> timedelta:
    """The oldest a carried-forward value of `name` may be before align_asof treats the feed as dead. Sub-daily
    perp metrics get an 8h cadence; every other alt feed is at most daily-published → a 1-day cadence. × the
    cadence multiplier for slack (release lag / weekends). Conservative: a too-generous age only weakens the guard."""
    cadence = timedelta(hours=8) if name in _SUBDAILY_FEATURES else timedelta(days=1)
    return cadence * _STALENESS_CADENCES


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
    funding_feat = getattr(spec, "funding_feature", None)
    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        feats: dict[str, dict[str, float]] = {}
        for name in names:
            try:
                points = provider.fetch_series(symbol, name, limit=_ALT_HISTORY_LIMIT)
            except Exception:  # noqa: BLE001 — a missing/erroring series is just no data for that feature
                points = []
            # B5 staleness cap: don't carry a value older than the feed's natural cadence × N — a dead feed must
            # read None at a bar (honest "no fresh data"), never a stale constant the gate mistakes for live signal.
            aligned = align_asof(points, bars, max_age=_feature_max_age(name))
            if aligned:
                feats[name] = aligned
            # The perp carry leg accrues the per-bar SUMMED funding (every settlement in the bar interval),
            # stored separately from the level series above (which still serves a funding-as-condition read).
            # align_asof alone under/over-counts carry 2–8x; sum_funding_per_bar is the funding-correct join.
            if name == funding_feat:
                accrual = sum_funding_per_bar(points, bars)
                if accrual:
                    feats[FUNDING_ACCRUAL_KEY] = accrual
        if feats:
            out[symbol] = feats
    return out or None


def resolve_alt_store(settings: object, store: object) -> object:
    """Pick the alt-data store the SAME way ingest/api/the loop do. COLD tier FIRST: alt_data_backend ==
    "parquet" → the DuckDB/Parquet lake (local dir or R2) — the hot/cold data stack. Else HOT: a Postgres URL →
    PgAltDataStore over the knowledge Store, else the JSONL AltDataStore. All three expose the same
    append/read_asof/read_all interface, so the gate/finder/sweep stay backend-agnostic."""
    backend = getattr(settings, "alt_data_backend", "pg")
    if backend == "parquet":
        from cosmu.data.providers.parquet_store import ParquetAltDataStore

        return ParquetAltDataStore.from_settings(settings)
    if backend in ("ducklake", "tiered"):
        from cosmu.data.providers.ducklake_store import DuckLakeAltDataStore

        lake = DuckLakeAltDataStore.from_settings(settings)
        if backend == "ducklake":
            return lake
        # "tiered": RESEARCH reads PG-hot ∪ DuckLake-cold so a retention prune never opens a blind spot. The
        # money/UI paths never reach here — they read raw hot PG directly for sub-ms latency.
        from cosmu.data.altdata import hot_alt_store
        from cosmu.data.providers.tiered_store import TieredAltDataStore

        return TieredAltDataStore(hot_alt_store(settings, store), lake)
    # HOT tier (default "pg"): the single hot_alt_store factory (postgres → PgAltDataStore over `store`, else
    # JSONL) — shared with ingest + the research loop so the read/write store choice can never diverge.
    from cosmu.data.altdata import hot_alt_store

    return hot_alt_store(settings, store)
