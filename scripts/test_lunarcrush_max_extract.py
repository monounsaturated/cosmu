"""Offline tests for lunarcrush_max_extract.py — zero network calls, zero API spend.

Tests assert:
  - rate-limit sleep is enforced between calls
  - dedup/resume: already-stored entities are skipped (manifest + store both checked)
  - dry-run spends 0 API calls
  - PIT available_at = ts + 1 day is stamped on every stored point
  - daily quota hard-cap stops the run and resumes are coherent
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# Allow running from repo root: python3 scripts/test_lunarcrush_max_extract.py
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_ENGINE = _SCRIPTS.parent / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lunarcrush_max_extract import (  # noqa: E402
    SLEEP_BETWEEN_CALLS,
    Extractor,
    Manifest,
    _COIN_FIELDS,
    _rows_to_points,
    main,
    run_extract,
)
from cosmu.data.providers.store import AltDataStore  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _make_rows(n: int = 5, start: datetime = _T0) -> list[dict]:
    """Synthetic LunarCrush v4 daily rows."""
    return [
        {
            "time": int((start + timedelta(days=i)).timestamp()),
            "interactions": 1000 + i * 100,
            "sentiment": 60 + i,
            "galaxy_score": 70 + i,
            "alt_rank": 10 - i,
            "market_cap": 1e9 + i * 1e6,
            "volume_24h": 5e8,
            "price": 50000.0 + i,
        }
        for i in range(n)
    ]


def _fake_fetch(coin: str) -> list[dict]:
    return _make_rows()


# ---------------------------------------------------------------------------
# _rows_to_points: PIT stamp
# ---------------------------------------------------------------------------

def test_pit_available_at_is_next_day() -> None:
    """available_at must be exactly ts + 1 day (no look-ahead)."""
    rows = _make_rows(3)
    by_metric = _rows_to_points(rows, _COIN_FIELDS, datetime.now(tz=UTC))
    for metric, points in by_metric.items():
        for pt in points:
            assert pt.available_at == pt.ts + timedelta(days=1), f"{metric}: {pt.ts} → {pt.available_at}"


def test_rows_to_points_skips_null_fields() -> None:
    """Rows with None for a field should not produce a point for that metric."""
    rows = [{"time": int(_T0.timestamp()), "interactions": None, "sentiment": 42.0}]
    by_metric = _rows_to_points(rows, _COIN_FIELDS, datetime.now(tz=UTC))
    assert by_metric["social_volume"] == []
    assert len(by_metric["social_sentiment"]) == 1
    assert by_metric["social_sentiment"][0].value == 42.0


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_marks_and_skips(tmp_path: Path) -> None:
    m = Manifest(tmp_path / "manifest.json")
    assert not m.is_done("coin:BTC")
    m.mark_done("coin:BTC")
    assert m.is_done("coin:BTC")


def test_manifest_daily_counter_increments(tmp_path: Path) -> None:
    m = Manifest(tmp_path / "manifest.json")
    assert m.calls_today == 0
    m.increment_calls(5)
    assert m.calls_today == 5


def test_manifest_persists_across_reload(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    m1 = Manifest(p)
    m1.mark_done("stock:AAPL")
    m1.increment_calls(3)

    m2 = Manifest(p)
    assert m2.is_done("stock:AAPL")
    assert m2.calls_today == 3


def test_manifest_resets_calls_on_new_day(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    # Write a manifest that looks like it was from yesterday
    yesterday = (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    p.write_text(json.dumps({"done": ["coin:BTC"], "calls_today": 1500, "day": yesterday}))

    m = Manifest(p)
    # Done set preserved, counter reset
    assert m.is_done("coin:BTC")
    assert m.calls_today == 0


# ---------------------------------------------------------------------------
# Dry-run spends zero calls
# ---------------------------------------------------------------------------

def test_dry_run_spends_zero_calls(tmp_path: Path) -> None:
    store = AltDataStore(tmp_path / "alt")
    manifest = Manifest(tmp_path / "manifest.json")

    with patch("lunarcrush_max_extract._list_coins") as lc, \
         patch("lunarcrush_max_extract._list_stocks") as ls, \
         patch("lunarcrush_max_extract._list_topics") as lt, \
         patch("lunarcrush_max_extract._list_categories") as lcat, \
         patch("lunarcrush_max_extract._fetch_coin_series") as fc, \
         patch("lunarcrush_max_extract._fetch_stock_series") as fst, \
         patch("lunarcrush_max_extract._fetch_topic_series") as ftp, \
         patch("lunarcrush_max_extract._fetch_category_series") as fca:

        run_extract(
            api_key="test-key",
            store=store,
            manifest=manifest,
            n_coins=3,
            n_stocks=2,
            n_topics=2,
            n_categories=1,
            dry_run=True,
        )

    # None of the list OR time-series fetchers should have been called
    lc.assert_not_called()
    ls.assert_not_called()
    lt.assert_not_called()
    lcat.assert_not_called()
    fc.assert_not_called()
    fst.assert_not_called()
    ftp.assert_not_called()
    fca.assert_not_called()

    # No calls were charged to manifest
    assert manifest.calls_today == 0


# ---------------------------------------------------------------------------
# Resume / dedup: already-stored entities are skipped
# ---------------------------------------------------------------------------

def test_resume_skips_already_done_entities(tmp_path: Path) -> None:
    store = AltDataStore(tmp_path / "alt")
    manifest = Manifest(tmp_path / "manifest.json")
    # Pre-mark BTC as done
    manifest.mark_done("coin:BTC")
    manifest.mark_done("coin:ETH")

    call_log: list[str] = []

    def fake_fetch(api_key: str, coin: str) -> list[dict]:
        call_log.append(coin)
        return _make_rows()

    extractor = Extractor(
        api_key="test-key",
        store=store,
        manifest=manifest,
        daily_quota=100,
        sleep_between=0,  # no sleep in tests
        dry_run=False,
    )

    entities = [("coin:BTC", "BTC"), ("coin:ETH", "ETH"), ("coin:SOL", "SOL")]
    with patch("lunarcrush_max_extract._fetch_coin_series", side_effect=fake_fetch):
        extractor._run_bucket("coin", entities, _COIN_FIELDS, fake_fetch, 3, 0)

    # Only SOL should have been fetched
    assert call_log == ["SOL"]


# ---------------------------------------------------------------------------
# Rate-limit: sleep is enforced between calls
# ---------------------------------------------------------------------------

def test_sleep_enforced_between_calls(tmp_path: Path) -> None:
    store = AltDataStore(tmp_path / "alt")
    manifest = Manifest(tmp_path / "manifest.json")
    sleep_duration = 0.05  # fast but measurable

    extractor = Extractor(
        api_key="test-key",
        store=store,
        manifest=manifest,
        daily_quota=100,
        sleep_between=sleep_duration,
        dry_run=False,
    )

    entities = [("coin:BTC", "BTC"), ("coin:ETH", "ETH"), ("coin:SOL", "SOL")]
    sleep_calls: list[float] = []

    def fake_fetch(api_key: str, coin: str) -> list[dict]:
        return _make_rows()

    with patch("lunarcrush_max_extract.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        extractor._run_bucket("coin", entities, _COIN_FIELDS, fake_fetch, 3, 0)

    # Sleep should be called between entities (N-1 times for N entities)
    assert len(sleep_calls) == 2
    assert all(s == sleep_duration for s in sleep_calls)


# ---------------------------------------------------------------------------
# Quota hard-cap stops the run
# ---------------------------------------------------------------------------

def test_quota_cap_stops_run(tmp_path: Path) -> None:
    store = AltDataStore(tmp_path / "alt")
    manifest = Manifest(tmp_path / "manifest.json")
    # Set calls_today to 1 below the cap
    manifest.increment_calls(9)

    call_log: list[str] = []

    def fake_fetch(api_key: str, entity_id: str) -> list[dict]:
        call_log.append(entity_id)
        return _make_rows()

    extractor = Extractor(
        api_key="test-key",
        store=store,
        manifest=manifest,
        daily_quota=10,
        sleep_between=0,
        dry_run=False,
    )

    entities = [(f"coin:{c}", c) for c in ["BTC", "ETH", "SOL", "XRP", "ADA"]]
    with patch("lunarcrush_max_extract.time.sleep"):
        extractor._run_bucket("coin", entities, _COIN_FIELDS, fake_fetch, 5, 0)

    # Only 1 call should have been made before the cap
    assert len(call_log) == 1
    assert manifest.calls_today == 10


# ---------------------------------------------------------------------------
# PIT is correctly stored in the alt-data store
# ---------------------------------------------------------------------------

def test_pit_stored_in_altdata(tmp_path: Path) -> None:
    store = AltDataStore(tmp_path / "alt")
    manifest = Manifest(tmp_path / "manifest.json")

    extractor = Extractor(
        api_key="test-key",
        store=store,
        manifest=manifest,
        daily_quota=100,
        sleep_between=0,
        dry_run=False,
    )

    with patch("lunarcrush_max_extract._fetch_coin_series", return_value=_make_rows(3)), \
         patch("lunarcrush_max_extract.time.sleep"):
        extractor._spend("coin:BTC", "coin", "BTC", _COIN_FIELDS, lambda key, e: _make_rows(3))

    # Read back and confirm PIT stamp
    points = store.read_all("lunarcrush", "BTC", "social_volume")
    assert len(points) == 3
    for pt in points:
        assert pt.available_at == pt.ts + timedelta(days=1), "PIT stamp wrong"


# ---------------------------------------------------------------------------
# main() exits 1 with no key and no dry-run
# ---------------------------------------------------------------------------

def test_main_exits_1_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
    # Also ensure .env.local doesn't accidentally provide a key
    with patch("lunarcrush_max_extract._load_env_local"):
        rc = main(["--coins", "0", "--stocks", "0", "--topics", "0", "--categories", "0"])
    assert rc == 1


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
