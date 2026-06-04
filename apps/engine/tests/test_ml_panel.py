# Offline tests for the ML-ready standardized point-in-time panel. Everything is pure/injected (an AltDataStore
# on tmp_path + hand-built bars) — no network. The make-or-break property proven here is NO LOOK-AHEAD: the
# z-score at row t depends only on rows 0..t, so a future value never leaks backward into an earlier row.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.data.market import Bar
from cosmu.ingest.ml_panel import (
    ML_PANEL_TRANSFORM_VERSION,
    build_ml_panel,
    read_ml_panel,
    standardize_pit,
    write_ml_panel,
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(closes: list[float]) -> list[Bar]:
    out: list[Bar] = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=_T0 + timedelta(days=i), open=d, high=d * Decimal("1.01"),
                       low=d * Decimal("0.99"), close=d, volume=Decimal("1000")))
    return out


# --------------------------------------------------------------------------- standardize_pit (the core)


def test_standardize_pit_has_no_lookahead():
    """The defining property: standardizing a PREFIX yields the SAME values as standardizing the full series and
    slicing — i.e. a later (even huge) value never changes an earlier row's z-score."""
    col = [1.0, 2.0, 3.0, 4.0, 5.0, 1000.0, 6.0]
    full = standardize_pit(col, min_obs=2)
    for k in range(2, len(col)):
        prefix = standardize_pit(col[:k], min_obs=2)
        assert prefix == full[:k], f"row {k - 1} changed when future data was appended — look-ahead leak"


def test_standardize_pit_constant_and_missing():
    # A constant column → 0.0 once min_obs is reached (std == 0, honest neutral), None before.
    out = standardize_pit([5.0, 5.0, 5.0, 5.0], min_obs=3)
    assert out == [None, None, 0.0, 0.0]
    # None passes through (a gap stays a gap; it is not counted toward the running stats).
    out2 = standardize_pit([1.0, None, 2.0, None, 3.0], min_obs=2)
    assert out2[1] is None and out2[3] is None
    assert out2[0] is None  # only 1 obs so far
    assert out2[2] is not None  # 2 obs → standardized


def test_standardize_pit_is_clipped():
    # A point's expanding z-score (window includes itself) is bounded by sqrt(n-1); here sqrt(30) ≈ 5.48 > clip.
    col = [0.0] * 30 + [1e9]  # a wild outlier after a flat run
    out = standardize_pit(col, min_obs=5, clip=4.0)
    assert out[-1] == 4.0  # clipped to the cap, never an unbounded z


# --------------------------------------------------------------------------- build_ml_panel (PIT join + shape)


def test_panel_alt_join_is_point_in_time():
    """An alt observation whose `available_at` is AFTER a bar close must NOT appear on that bar (no look-ahead);
    it only becomes visible on the first bar at/after its availability."""
    store = AltDataStore(tmp := _tmp())
    bars = _bars([100.0 + i for i in range(6)])
    # funding_rate published with a one-day availability LAG (known the day AFTER its ts).
    pts = [AltDataPoint(ts=b.ts, available_at=b.ts + timedelta(days=1), value=0.001 * (i + 1)) for i, b in enumerate(bars)]
    store.append("binance", "BTCUSDT", "funding_rate", pts)

    panel = build_ml_panel(store, bars, symbol="BTCUSDT", timeframe="1d", alt_features=("funding_rate",), min_obs=2)
    fund = [r.features["funding_rate"] for r in panel.rows]
    # Row 0: the only funding row (ts day0) is available day1 > day0 → no data yet → None.
    assert fund[0] is None
    # Standardization needs min_obs=2 observations → first non-None appears only once 2 lagged points exist.
    assert any(v is not None for v in fund), "later bars must see the lagged funding once available"
    _ = tmp


def test_panel_missing_feature_is_all_none():
    store = AltDataStore(_tmp())
    bars = _bars([10.0 + i for i in range(5)])
    panel = build_ml_panel(store, bars, symbol="BTCUSDT", timeframe="1d", alt_features=("funding_rate",), min_obs=2)
    # No funding data in the store → an honest all-None column (never a fabricated value).
    assert all(r.features["funding_rate"] is None for r in panel.rows)
    # Price features are always derivable; ret_1 is None only on the first bar (no prior close).
    assert panel.rows[0].features["ret_1"] is None
    assert "range_pct" in panel.feature_names and "volume" in panel.feature_names
    assert panel.transform_version == ML_PANEL_TRANSFORM_VERSION


def test_panel_persist_is_idempotent():
    store = AltDataStore(_tmp())
    bars = _bars([100.0 * (1.01**i) for i in range(40)])
    panel_dir = _tmp()
    p = build_ml_panel(store, bars, symbol="BTCUSDT", timeframe="1d", alt_features=("funding_rate",))
    n1 = write_ml_panel(panel_dir, p)
    assert n1 == 40
    # Re-running with the SAME bars writes 0 (dedup on ts; PIT rows are byte-identical on recompute).
    n2 = write_ml_panel(panel_dir, p)
    assert n2 == 0
    # Appending a longer panel only writes the genuinely-new tail rows.
    longer = build_ml_panel(store, _bars([100.0 * (1.01**i) for i in range(45)]), symbol="BTCUSDT", timeframe="1d", alt_features=("funding_rate",))
    n3 = write_ml_panel(panel_dir, longer)
    assert n3 == 5
    back = read_ml_panel(panel_dir, "BTCUSDT", "1d")
    assert back is not None and len(back.rows) == 45


def _tmp():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp(prefix="cosmu-mlpanel-"))
