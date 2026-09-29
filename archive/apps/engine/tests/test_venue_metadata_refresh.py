# Per-venue metadata snapshot — offline, deterministic (no network, no keys, no LLM). Proves: each venue's OWN
# data adapter feeds a per-(venue,symbol) last-price + 24h notional-volume PIT snapshot (NOT one asset-class
# source), values read back correctly, an offline/empty adapter is skipped (never zero-filled), a miss reads
# None, and the default resolver wires the crypto venues that have a real adapter.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings
from cosmu.data.providers.store import AltDataStore
from cosmu.ingest.venue_metadata_refresh import (
    METRIC_PRICE,
    METRIC_VOLUME,
    _default_adapters,
    read_pit_venue_metadata,
    refresh_venue_metadata,
)
from cosmu.knowledge.store import Store
from cosmu.spine.venue import default_catalog


class _Bar:
    def __init__(self, close: float, volume: float) -> None:
        self.close = Decimal(str(close))
        self.volume = Decimal(str(volume))


class _Adapter:
    """Fake per-venue adapter: universe() yields (id, symbol) instruments; bars() returns canned bars per id
    (latest bar last). Mirrors the real DataAdapter surface refresh_venue_metadata depends on."""

    def __init__(self, rows: list[tuple[str, str, float, float]]) -> None:
        self._rows = rows  # (instrument_id, symbol, last_close, last_volume)

    def universe(self, as_of):  # noqa: ANN001, ANN201
        return [SimpleNamespace(id=i, symbol=s) for (i, s, _, _) in self._rows]

    def bars(self, instrument_id, start, end, interval):  # noqa: ANN001, ANN201
        for (i, _s, c, v) in self._rows:
            if i == instrument_id:
                return [_Bar(c * 0.99, v * 0.5), _Bar(c, v)]  # the latest bar is the snapshot
        return []


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def test_snapshots_per_venue_price_and_volume(tmp_path) -> None:
    store = _store(tmp_path, "vm")
    alt = AltDataStore(root=tmp_path / "alt")
    now = datetime(2026, 6, 15, tzinfo=UTC)
    adapters = {
        "okx": _Adapter([("crypto:okx:BTC-USDT-SWAP", "BTC-USDT-SWAP", 60000.0, 1000.0)]),
        "hyperliquid": _Adapter([("crypto:hyperliquid:BTC", "BTC", 60100.0, 800.0)]),
    }
    result = refresh_venue_metadata(store, adapters=adapters, now=now, alt_store=alt)

    assert result["instruments"] == 2
    assert result["snapshots"] == 4  # 2 metrics × 2 instruments
    assert set(result["venues"]) == {"okx", "hyperliquid"}

    # Per-venue, distinct values (the two venues are NOT collapsed to one asset-class source).
    assert read_pit_venue_metadata(store, "okx", "BTC-USDT-SWAP", METRIC_PRICE, now, alt_store=alt) == 60000.0
    assert read_pit_venue_metadata(store, "okx", "BTC-USDT-SWAP", METRIC_VOLUME, now, alt_store=alt) == 60000.0 * 1000.0
    assert read_pit_venue_metadata(store, "hyperliquid", "BTC", METRIC_PRICE, now, alt_store=alt) == 60100.0
    assert read_pit_venue_metadata(store, "hyperliquid", "BTC", METRIC_VOLUME, now, alt_store=alt) == 60100.0 * 800.0
    # An unseen symbol reads None — never fabricated.
    assert read_pit_venue_metadata(store, "okx", "NOPE", METRIC_PRICE, now, alt_store=alt) is None


def test_offline_adapter_is_skipped_not_fabricated(tmp_path) -> None:
    store = _store(tmp_path, "vm_off")
    alt = AltDataStore(root=tmp_path / "alt")
    now = datetime(2026, 6, 15, tzinfo=UTC)

    class _Empty:
        def universe(self, as_of):  # noqa: ANN001, ANN201
            return [SimpleNamespace(id="x", symbol="X")]

        def bars(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            return []  # offline / no bars

    result = refresh_venue_metadata(store, adapters={"okx": _Empty()}, now=now, alt_store=alt)
    assert result["snapshots"] == 0 and result["instruments"] == 0
    assert read_pit_venue_metadata(store, "okx", "X", METRIC_PRICE, now, alt_store=alt) is None


def test_default_adapters_cover_the_crypto_venues() -> None:
    # The default resolver wires every crypto venue that has a real per-venue data adapter.
    adapters = _default_adapters(default_catalog(), None)
    assert {"binance", "okx", "kraken_futures", "hyperliquid"} <= set(adapters)
