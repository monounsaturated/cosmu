# intent: the ML-READY STANDARDIZED POINT-IN-TIME panel — join the bar cache + the append-only alt store into a
# dense per-(symbol, timeframe) feature matrix where every column is z-scored using ONLY past+present data, so a
# model can train on it without leaking the future; inputs: cached `Bar`s + the alt store (read_asof, PIT) +
# the metric→provider routing; outputs: an `MLPanel` (rows of standardized features) persisted append-only and
# deduped on `ts` (a re-run writes 0 — the same idempotency the bar/alt stores enforce); invariants: NO
# look-ahead (the z-score at row t uses an EXPANDING window over rows 0..t, every one of whose values has
# available_at <= bar-close t — never a global/future mean), standardized (centered/scaled, robust to a constant
# column → 0.0, clipped), frozen + versioned (ML_PANEL_TRANSFORM_VERSION pins the transform so a trained model
# stays reproducible), and offline/pure (the store + bars are injected; no network). This COMPOSES the existing
# PIT store join (StoreBackedAltProvider routing) and the bar cache reader — it never re-implements either.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cosmu.data.altdata import _STORE_MARKET_WIDE, _STORE_PROVIDER_OF
from cosmu.data.market import Bar

# Frozen transform version — pinned into every persisted panel so a model trained on it stays reproducible.
# Bump this string if the standardization / feature-derivation logic changes.
ML_PANEL_TRANSFORM_VERSION = "ml-panel-zscore-v1"

# Price features derived from the bar itself (cheap, always-present spine of the panel). Each is z-scored PIT
# like every alt column, so the raw scale (a return vs a dollar volume) does not matter to the model.
PRICE_FEATURES: tuple[str, ...] = ("ret_1", "range_pct", "volume")

# Default alt features to join (the liquid, crypto-relevant tier0 reads + the typed event score). Missing
# series degrade to an all-None column (honest 'no data', never a fabricated value) — exactly what `verify`
# would flag as `missing`. Callers can pass their own metric list.
DEFAULT_ALT_FEATURES: tuple[str, ...] = (
    "funding_rate", "open_interest", "perp_spot_basis", "exchange_netflow",
    "fear_greed", "news_event_score", "macro_regime", "vix_level",
)

# Standardization guards.
DEFAULT_MIN_OBS = 20   # below this many observations a z-score is meaningless → emit None (honest abstention)
DEFAULT_CLIP = 8.0     # clip extreme z-scores so one outlier can't dominate a model's scaling


@dataclass(frozen=True)
class PanelRow:
    """One bar's standardized feature vector. `features` maps feature name → z-score (or None when the feature
    has no data / too little history to standardize at this bar). `available_at` == the bar close (a closed bar
    is known at its close — the panel inherits the bar's point-in-time stamp)."""

    ts: datetime
    available_at: datetime
    features: dict[str, float | None]


@dataclass(frozen=True)
class MLPanel:
    """A dense, standardized, point-in-time feature matrix for one symbol × timeframe."""

    symbol: str
    timeframe: str
    feature_names: tuple[str, ...]
    transform_version: str
    rows: list[PanelRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "transform_version": self.transform_version,
            "feature_names": list(self.feature_names),
            "rows": [
                {"ts": r.ts.isoformat(), "available_at": r.available_at.isoformat(), "features": r.features}
                for r in self.rows
            ],
        }


def standardize_pit(
    raw: list[float | None], *, min_obs: int = DEFAULT_MIN_OBS, clip: float = DEFAULT_CLIP
) -> list[float | None]:
    """Expanding (point-in-time) z-score of one feature column. At row i the mean/variance are computed over the
    NON-None values at rows 0..i INCLUSIVE — every one knowable by bar-close i — so no future statistic leaks
    backward. A column with fewer than `min_obs` observations so far → None at that row (an honest 'not enough
    history to standardize'); a constant column (std == 0) → 0.0; the z is clipped to ±`clip`. Uses Welford's
    online moments so one forward pass is exact and stable."""
    out: list[float | None] = []
    count = 0
    mean = 0.0
    m2 = 0.0  # sum of squared deviations (Welford) → population variance = m2 / count
    for x in raw:
        if x is None:
            out.append(None)
            continue
        count += 1
        delta = x - mean
        mean += delta / count
        m2 += delta * (x - mean)
        if count < min_obs:
            out.append(None)
            continue
        var = m2 / count
        std = var**0.5
        if std <= 0.0:
            out.append(0.0)
            continue
        z = (x - mean) / std
        out.append(round(max(-clip, min(clip, z)), 6))
    return out


def _price_columns(bars: list[Bar]) -> dict[str, list[float | None]]:
    """Derive the raw (pre-standardization) price columns from the bars. `ret_1` is None on the first bar (no
    prior close); `range_pct` and `volume` are defined on every bar. All raw — `standardize_pit` scales them."""
    ret_1: list[float | None] = []
    range_pct: list[float | None] = []
    volume: list[float | None] = []
    prev_close: float | None = None
    for b in bars:
        close = float(b.close)
        ret_1.append((close / prev_close - 1.0) if prev_close not in (None, 0.0) else None)
        range_pct.append(((float(b.high) - float(b.low)) / close) if close else None)
        volume.append(float(b.volume))
        prev_close = close
    return {"ret_1": ret_1, "range_pct": range_pct, "volume": volume}


def _alt_column(store: Any, symbol: str, metric: str, bar_ts: list[datetime]) -> list[float | None]:
    """Join one alt metric onto the bar grid POINT-IN-TIME: at each bar close `t` take the latest observation
    with `available_at <= t` (the store's `read_asof` does exactly this latest-wins PIT selection). Routing
    mirrors `StoreBackedAltProvider`: the provider is the canonical `_STORE_PROVIDER_OF[metric]`; market-wide
    metrics live under the `MARKET` key. A metric the store has no data for → an all-None column (honest gap)."""
    provider = _STORE_PROVIDER_OF.get(metric)
    if provider is None:
        return [None] * len(bar_ts)
    key = "MARKET" if metric in _STORE_MARKET_WIDE else symbol
    out: list[float | None] = []
    for t in bar_ts:
        try:
            pts = store.read_asof(provider, key, metric, t)
        except Exception:  # noqa: BLE001 — a store read failure must not abort the whole panel
            pts = []
        out.append(pts[-1].value if pts else None)
    return out


def build_ml_panel(
    store: Any,  # AltDataStore | PgAltDataStore — must expose read_asof
    bars: list[Bar],
    *,
    symbol: str,
    timeframe: str,
    alt_features: tuple[str, ...] = DEFAULT_ALT_FEATURES,
    price_features: tuple[str, ...] = PRICE_FEATURES,
    min_obs: int = DEFAULT_MIN_OBS,
    clip: float = DEFAULT_CLIP,
) -> MLPanel:
    """Build the standardized, point-in-time panel for one symbol × timeframe. Price columns come from the bars;
    alt columns are PIT-joined from the store; EVERY column is then z-scored with `standardize_pit` (expanding,
    no look-ahead). The result is a dense matrix a model can train on directly, with `ts`/`available_at` so the
    backtest's as-of join still applies. Deterministic for a fixed (bars, store)."""
    bars = sorted(bars, key=lambda b: b.ts)
    bar_ts = [b.ts for b in bars]
    feature_names = tuple(price_features) + tuple(alt_features)

    raw: dict[str, list[float | None]] = {}
    price = _price_columns(bars)
    for name in price_features:
        raw[name] = price.get(name, [None] * len(bars))
    for metric in alt_features:
        raw[metric] = _alt_column(store, symbol, metric, bar_ts)

    standardized = {name: standardize_pit(col, min_obs=min_obs, clip=clip) for name, col in raw.items()}

    rows: list[PanelRow] = []
    for i, b in enumerate(bars):
        rows.append(
            PanelRow(
                ts=b.ts,
                available_at=b.ts,  # a closed bar is known at its close → the panel row's PIT stamp
                features={name: standardized[name][i] for name in feature_names},
            )
        )
    return MLPanel(
        symbol=symbol, timeframe=timeframe, feature_names=feature_names,
        transform_version=ML_PANEL_TRANSFORM_VERSION, rows=rows,
    )


# --------------------------------------------------------------------------- persistence (append-only, deduped)


def ml_panel_path(panel_dir: Path | str, symbol: str, timeframe: str) -> Path:
    """The on-disk panel path for one symbol × timeframe (mirrors the bar cache's `<symbol>_<tf>.json` layout
    so the managed-data surface reads/writes one predictable place)."""
    safe = f"{symbol}_{timeframe}".replace("/", "")
    return Path(panel_dir) / f"{safe}.json"


def read_ml_panel(panel_dir: Path | str, symbol: str, timeframe: str) -> MLPanel | None:
    """Read a persisted panel (None if absent). Rows come back ascending by `ts`."""
    path = ml_panel_path(panel_dir, symbol, timeframe)
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    rows = sorted(
        (
            PanelRow(
                ts=datetime.fromisoformat(r["ts"]),
                available_at=datetime.fromisoformat(r["available_at"]),
                features=r["features"],
            )
            for r in doc.get("rows", [])
        ),
        key=lambda r: r.ts,
    )
    return MLPanel(
        symbol=doc["symbol"], timeframe=doc["timeframe"],
        feature_names=tuple(doc.get("feature_names", ())),
        transform_version=doc.get("transform_version", ML_PANEL_TRANSFORM_VERSION),
        rows=rows,
    )


def write_ml_panel(panel_dir: Path | str, panel: MLPanel) -> int:
    """Append-merge `panel` into the on-disk panel, deduped on `ts` (idempotent: a re-run with the same bars
    writes 0 new rows). This is safe BECAUSE the PIT z-score at row t depends only on rows 0..t — appending
    later bars never changes an earlier row, so an existing row is byte-identical on recompute and we keep it.
    Returns the count of genuinely-new rows."""
    path = ml_panel_path(panel_dir, panel.symbol, panel.timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_ml_panel(panel_dir, panel.symbol, panel.timeframe)
    by_ts: dict[datetime, PanelRow] = {r.ts: r for r in (existing.rows if existing else [])}
    before = len(by_ts)
    for r in panel.rows:
        by_ts.setdefault(r.ts, r)  # existing row wins → idempotent, byte-identical on recompute
    merged = sorted(by_ts.values(), key=lambda r: r.ts)
    names = tuple(dict.fromkeys((*(existing.feature_names if existing else ()), *panel.feature_names)))
    doc = MLPanel(
        symbol=panel.symbol, timeframe=panel.timeframe, feature_names=names,
        transform_version=panel.transform_version, rows=merged,
    ).to_dict()
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return len(merged) - before
