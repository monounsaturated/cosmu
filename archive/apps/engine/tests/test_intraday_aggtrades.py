# Offline tests for the keyless aggTrades flow fetcher (cosmu.data.intraday_aggtrades).
# NO live network: a canned `_fetcher(url)` replays a zipped aggTrades-CSV fixture keyed by the daily Vision
# URL, exactly as data.binance.vision would serve it. Tests cover:
#   - sign convention: is_buyer_maker == "false" -> aggressive BUY ; == "true" -> aggressive SELL
#   - 1m resample: trades bucket into the minute they occurred; close == last-by-time price in the minute
#   - imbalance = (buy - sell)/total in [-1, 1]
#   - header row skipped (perp archives carry one); on-disk cache round-trip (second call needs no fetcher hit)
#   - gap day (404 -> None) skipped, never zero-filled
#   - market="perp" hits the futures/um tree

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime

from cosmu.data.intraday_aggtrades import (
    AggTradesVisionFetcher,
    fetch_1m_flow_bars,
    resample_trades_to_1m_flow,
)

_MIN_MS = 60_000


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0, sec: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, sec, tzinfo=UTC).timestamp() * 1000)


def _aggtrades_zip(rows: list[tuple[int, float, float, bool]], *, with_header: bool = True) -> bytes:
    """Build a zipped aggTrades CSV from (transact_ms, price, qty, is_buyer_maker) rows (perp schema)."""
    lines: list[str] = []
    if with_header:
        lines.append("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker")
    for i, (ts, px, qty, ibm) in enumerate(rows):
        lines.append(f"{1000 + i},{px},{qty},{i},{i},{ts},{'true' if ibm else 'false'}")
    csv_text = "\n".join(lines) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("FOO-aggTrades-2025-02-01.csv", csv_text)
    return buf.getvalue()


def test_resample_sign_convention_and_imbalance():
    base = _ms(2025, 2, 1, 0, 0, 0)
    rows = [
        (base + 1_000, 0.50, 100.0, False),  # aggressive BUY (buyer is taker)
        (base + 2_000, 0.51, 40.0, False),   # aggressive BUY
        (base + 3_000, 0.49, 60.0, True),    # aggressive SELL (buyer is maker)
    ]
    bars = resample_trades_to_1m_flow(iter(rows))
    assert len(bars) == 1
    b = bars[0]
    assert b.buy_vol == 140.0
    assert b.sell_vol == 60.0
    assert b.total_vol == 200.0
    assert b.close == 0.49  # last-by-time trade price in the minute
    # imbalance = (140 - 60) / 200 = 0.40
    assert abs(b.imbalance - 0.40) < 1e-9


def test_resample_buckets_by_minute():
    rows = [
        (_ms(2025, 2, 1, 0, 0, 10), 1.0, 10.0, False),
        (_ms(2025, 2, 1, 0, 0, 59), 1.0, 10.0, False),
        (_ms(2025, 2, 1, 0, 1, 5), 1.0, 5.0, True),
    ]
    bars = resample_trades_to_1m_flow(iter(rows))
    assert len(bars) == 2
    assert bars[0].buy_vol == 20.0 and bars[0].sell_vol == 0.0
    assert bars[1].buy_vol == 0.0 and bars[1].sell_vol == 5.0


def test_fetch_parses_zip_and_caches(tmp_path):
    base = _ms(2025, 2, 1, 0, 0, 0)
    raw = _aggtrades_zip([(base + 1_000, 0.50, 100.0, False), (base + 2_000, 0.50, 50.0, True)])
    calls = {"n": 0}

    def fetcher(url: str) -> bytes | None:
        calls["n"] += 1
        assert "futures/um/daily/aggTrades/FOO" in url  # perp tree
        return raw

    f = AggTradesVisionFetcher(str(tmp_path), market="perp", _fetcher=fetcher)
    bars = f.fetch("FOO", date(2025, 2, 1), date(2025, 2, 1))
    assert len(bars) == 1
    assert bars[0].buy_vol == 100.0 and bars[0].sell_vol == 50.0
    assert calls["n"] == 1
    # second call served from disk cache — no extra fetcher hit
    bars2 = f.fetch("FOO", date(2025, 2, 1), date(2025, 2, 1))
    assert len(bars2) == 1
    assert calls["n"] == 1


def test_gap_day_skipped_not_zero_filled(tmp_path):
    def fetcher(url: str) -> bytes | None:
        return None  # 404 every day

    bars = fetch_1m_flow_bars("FOO", date(2025, 2, 1), date(2025, 2, 2), cache_dir=str(tmp_path), market="perp", _fetcher=fetcher)
    assert bars == []  # never zero-filled


def test_spot_vs_perp_url_tree(tmp_path):
    seen = {"url": ""}

    def fetcher(url: str) -> bytes | None:
        seen["url"] = url
        return None

    AggTradesVisionFetcher(str(tmp_path), market="spot", _fetcher=fetcher).fetch_day("FOO", date(2025, 2, 1))
    assert "data/spot/daily/aggTrades/FOO" in seen["url"]
