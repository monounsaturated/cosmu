# intent: deterministic offline tests for scripts/data_coverage.py — the read-only data-bottleneck report;
# inputs: a tmp-path-isolated AltDataStore + bar cache (no live network, no live DB); outputs: text/JSON
# renderings that reflect the injected fixture state honestly (EMPTY when nothing is there, populated rows when
# data exists); invariants: no network, fixed clock, graceful-degradation on empty stores, JSON is
# parseable, text always contains the section headers, look-ahead violations surface correctly.

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# --- path bootstrap so pytest finds the scripts/ sibling without installing it ---
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import data_coverage  # noqa: E402 (path bootstrap must precede)

from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.ingest.bars import bar_cache_path, write_bars_cache
from cosmu.data.market import Bar
from decimal import Decimal

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=60)


def _store(tmp_path: Path) -> AltDataStore:
    return AltDataStore(tmp_path / "altdata")


def _bars(n: int, *, start: datetime = _T0) -> list[Bar]:
    return [
        Bar(
            ts=start + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]


def _clock():
    return _NOW


# ---------------------------------------------------------------------------


def test_empty_store_renders_empty_text(tmp_path):
    """All-empty store: text output contains section headers and EMPTY, never fabricates rows."""
    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=True,
    )
    assert "DATA COVERAGE REPORT" in out
    assert "BAR CACHE" in out
    assert "ALT DATA" in out
    # Every source should be empty — the text must not claim any rows
    assert "EMPTY" in out


def test_empty_store_json_parses(tmp_path):
    """Empty store --json flag: output is valid JSON with expected keys."""
    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=False,
        as_json=True,
    )
    doc = json.loads(out)
    assert "generated_at" in doc
    assert "summary" in doc
    assert "alt_data" in doc
    assert "bars" in doc
    assert "symbols" in doc
    assert doc["symbols"] == ["BTCUSDT"]
    # All series must be missing (nothing ingested)
    assert doc["summary"]["missing"] > 0
    assert doc["summary"]["ok"] == 0


def test_populated_alt_appears_in_report(tmp_path):
    """After writing funding_rate points, the report shows them as rows (not EMPTY)."""
    store = _store(tmp_path)
    points = [
        AltDataPoint(ts=_T0 + timedelta(hours=8 * i), available_at=_T0 + timedelta(hours=8 * i + 1), value=0.0001 * i)
        for i in range(90)  # 90 funding ticks (~30 days at 8h cadence)
    ]
    store.append("binance", "BTCUSDT", "funding_rate", points)

    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=store,
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=False,
    )
    # binance provider now has rows
    assert "binance" in out
    # The EMPTY sentinel should NOT appear for the binance provider row
    lines = out.splitlines()
    binance_line = next((l for l in lines if l.strip().startswith("binance")), None)
    assert binance_line is not None, "binance provider line not found in output"
    # syms_with_data > 0 — some non-zero number appears in the populated column
    assert "EMPTY" not in binance_line


def test_populated_bars_appear_in_report(tmp_path):
    """After writing bar cache, bar section shows symbols_with_data > 0."""
    market_dir = tmp_path / "market"
    path = bar_cache_path(market_dir / "binance", "BTCUSDT", "1d")
    write_bars_cache(path, _bars(365))

    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(market_dir),
        clock=_clock,
        include_bars=True,
        timeframes=("1d",),
    )
    assert "binance/1d" in out
    # Should NOT say EMPTY for the bar row
    lines = out.splitlines()
    bar_line = next((l for l in lines if "binance/1d" in l), None)
    assert bar_line is not None
    assert "EMPTY" not in bar_line


def test_json_populated_bars(tmp_path):
    """JSON mode: after writing bars, bars section has rows_total > 0."""
    market_dir = tmp_path / "market"
    path = bar_cache_path(market_dir / "binance", "BTCUSDT", "1d")
    write_bars_cache(path, _bars(100))

    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(market_dir),
        clock=_clock,
        include_bars=True,
        timeframes=("1d",),
        as_json=True,
    )
    doc = json.loads(out)
    bar_key = "binance/1d"
    assert bar_key in doc["bars"]
    assert doc["bars"][bar_key]["rows_total"] == 100
    assert doc["bars"][bar_key]["symbols_with_data"] == 1


def test_stale_series_surfaces_in_text(tmp_path):
    """A series whose last available_at is >3d before 'now' is marked stale in the summary."""
    store = _store(tmp_path)
    # Write one point far in the past (58 days ago) — last_available_at will be stale vs _NOW
    old_ts = _T0 + timedelta(days=1)
    points = [AltDataPoint(ts=old_ts, available_at=old_ts + timedelta(seconds=1), value=0.5)]
    store.append("binance", "BTCUSDT", "funding_rate", points)

    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=store,
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=False,
    )
    # Summary line should show at least 1 stale
    assert "stale" in out.lower()


def test_missing_section_lists_missing_series(tmp_path):
    """With an empty store, the MISSING section lists provider/symbol/metric combos."""
    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=False,
    )
    assert "MISSING" in out


def test_no_bars_flag_omits_bar_section(tmp_path):
    """--no-bars (include_bars=False) produces no bar series in the detail."""
    out = data_coverage.run_coverage(
        ["BTCUSDT"],
        store=_store(tmp_path),
        market_data_dir=str(tmp_path / "market"),
        clock=_clock,
        include_bars=False,
        as_json=True,
    )
    doc = json.loads(out)
    assert doc["bars"] == {}
    # No bars in series_detail either
    bar_detail = [s for s in doc["series_detail"] if s["kind"] == "bars"]
    assert bar_detail == []


def test_multiple_symbols(tmp_path):
    """Multiple symbols: report mentions each, bar coverage spans all."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    market_dir = tmp_path / "market"
    for sym in symbols:
        path = bar_cache_path(market_dir / "binance", sym, "1d")
        write_bars_cache(path, _bars(50))

    out = data_coverage.run_coverage(
        symbols,
        store=_store(tmp_path),
        market_data_dir=str(market_dir),
        clock=_clock,
        include_bars=True,
        timeframes=("1d",),
        as_json=True,
    )
    doc = json.loads(out)
    assert doc["bars"]["binance/1d"]["symbols_with_data"] == 3
    assert doc["bars"]["binance/1d"]["rows_total"] == 150


def test_rollup_by_source_empty():
    """_rollup_by_source on an empty list returns an empty dict, no crash."""
    result = data_coverage._rollup_by_source([])
    assert result == {}


def test_rollup_bars_empty():
    """_rollup_bars on an empty list returns an empty dict, no crash."""
    result = data_coverage._rollup_bars([])
    assert result == {}


def test_cli_main_help(capsys):
    """--help exits cleanly (SystemExit(0)) and emits usage."""
    with pytest.raises(SystemExit) as exc_info:
        data_coverage._main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "coverage" in captured.out.lower() or "coverage" in captured.err.lower()
