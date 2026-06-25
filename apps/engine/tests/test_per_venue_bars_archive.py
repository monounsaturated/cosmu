# PER-VENUE NATIVE BARS + the R2 PRICE ARCHIVE. Two flag-gated, BYTE-IDENTICAL-by-default features:
#   1. Per-venue native bars (COSMU_PER_VENUE_BARS): a cell tagged venue=kraken is SCORED on KRAKEN's own keyless
#      bars, venue=bybit on Bybit's — "each bar per venue, don't take one book as source of truth for all". OFF →
#      today's single-reference UNIFY behaviour, unchanged. The suite proves the resolver picks the right provider
#      per venue (ON), the OFF path is byte-identical, and ON each non-reference cell carries its OWN bars (missing/
#      sparse → reference fallback).
#   2. R2 price archive (bar_archive): fetched bars are union-merged into an R2 object so the shallow ~720-bar keyless
#      window ACCUMULATES into deep history. The suite proves the write+read round-trip is idempotent (union-merge
#      never shrinks), and R2-absent degrades to a graceful no-op. A FAKE in-memory S3 client stands in for R2 — no
#      network, no real bucket.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data import bar_archive
from cosmu.data.market import (
    Bar,
    BybitSpotOHLCVProvider,
    KrakenSpotOHLCVProvider,
    keyless_venue_provider,
)
from cosmu.data.price_cells import (
    REFERENCE_VENUE,
    _fallback_provider,
    build_crypto_cells,
    per_venue_bars_enabled,
)
from cosmu.data.reference import UNIFY_MIN_OVERLAP

# --------------------------------------------------------------------------- helpers (shared shape with test_universal_price)


def _bars(closes: list[float], *, start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(ts=t0 + timedelta(days=i), open=Decimal(str(c)), high=Decimal(str(c)),
            low=Decimal(str(c)), close=Decimal(str(c)), volume=Decimal("1000"))
        for i, c in enumerate(closes)
    ]


def _walk(n: int, *, seed: int, start: float = 100.0, vol: float = 0.02) -> list[float]:
    import random

    rng = random.Random(seed)
    out = [start]
    for _ in range(n):
        out.append(out[-1] * (1 + rng.uniform(-vol, vol)))
    return out


class _StubProvider:
    """A MarketDataProvider whose bars are pre-seeded per symbol (stands in for any venue's keyless OHLCV)."""

    def __init__(self, by_symbol: dict[str, list[Bar]]) -> None:
        self._by = by_symbol

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:  # noqa: ARG002
        return self._by.get(symbol, [])[-limit:]


class _FakeS3:
    """A minimal in-memory stand-in for the boto3 R2 client — get_object / put_object / list_objects_v2 over a dict.
    Proves the archive's read/merge/write contract WITHOUT touching real R2."""

    class _NoSuchKey(Exception):
        pass

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], bytes] = {}
        self.put_calls = 0

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803 — boto3 kwarg names
        if (Bucket, Key) not in self.store:
            raise self._NoSuchKey(Key)
        body = self.store[(Bucket, Key)]
        return {"Body": _Body(body)}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_kw):  # noqa: N803
        self.store[(Bucket, Key)] = Body
        self.put_calls += 1

    def list_objects_v2(self, *, Bucket: str, Prefix: str = "", **_kw):  # noqa: N803
        keys = [{"Key": k} for (b, k) in self.store if b == Bucket and k.startswith(Prefix)]
        return {"Contents": keys}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def _settings_with_r2() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:", openrouter_api_key=None,
        r2_account_id="acct", r2_access_key_id="ak", r2_secret_access_key="sk", r2_bucket="cosmu-lake",
    )


def _settings_no_r2() -> Settings:
    return Settings(database_url="sqlite:///:memory:", openrouter_api_key=None)


def _store(tmp_path):
    from cosmu.knowledge.store import Store

    return Store(Settings(database_url=f"sqlite:///{tmp_path}/pv.sqlite3", openrouter_api_key=None))


def _seed_universe(store, rows: list[tuple[str, str, str, str]]) -> None:
    with store.batch() as b:
        for venue, symbol, base, quote in rows:
            b.insert("universe_pairs", {
                "id": f"{venue}:{symbol}", "venue": venue, "symbol": symbol, "base": base, "quote": quote,
                "asset_class": "crypto", "instrument_type": "spot", "liquidity_usd_24h": 1.0e9,
                "tier": 0, "rank": 0, "active": 1, "source": "live", "fetched_at": "2024-01-01T00:00:00+00:00",
            })


# ====================================================================================================================
# 1. PER-VENUE KEYLESS RESOLVER
# ====================================================================================================================


def test_keyless_venue_provider_picks_the_right_native_provider_per_venue():
    """Each crypto venue resolves to ITS OWN keyless-native provider — never one book as source of truth for all."""
    assert type(keyless_venue_provider("kraken")) is KrakenSpotOHLCVProvider
    assert type(keyless_venue_provider("bybit")) is BybitSpotOHLCVProvider
    # binance → the configured reference provider (Binance spot in the default keyless config).
    from cosmu.data.market import BinanceSpotOHLCVProvider

    assert type(keyless_venue_provider("binance")) is BinanceSpotOHLCVProvider
    # case-insensitive
    assert type(keyless_venue_provider("KRAKEN")) is KrakenSpotOHLCVProvider


def test_keyless_venue_provider_cache_only_and_unknown_are_none():
    """Hyperliquid + equity are CACHE-ONLY (no live keyless fetch) and an unknown venue has no route → None (the
    caller keeps its reference/cache path; never fabricates bars)."""
    assert keyless_venue_provider("hyperliquid") is None
    assert keyless_venue_provider("ibkr") is None
    assert keyless_venue_provider("polymarket") is None
    assert keyless_venue_provider("") is None
    assert keyless_venue_provider("nonsense") is None


def test_per_venue_bars_flag_default_off_and_truthy_parsing(monkeypatch):
    """COSMU_PER_VENUE_BARS DEFAULT OFF (byte-identical path); common truthy spellings flip it on."""
    monkeypatch.delenv("COSMU_PER_VENUE_BARS", raising=False)
    assert per_venue_bars_enabled() is False
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("COSMU_PER_VENUE_BARS", v)
        assert per_venue_bars_enabled() is True
    for v in ("0", "false", "no", "", "off"):
        monkeypatch.setenv("COSMU_PER_VENUE_BARS", v)
        assert per_venue_bars_enabled() is False


def test_fallback_provider_off_is_byte_identical_on_adds_keyless_venues(monkeypatch):
    """OFF (default): the legacy set — kraken + binance only, bybit/HL None (byte-identical). ON: bybit resolves to
    its OWN keyless provider too; hyperliquid stays cache-only (None)."""
    monkeypatch.delenv("COSMU_PER_VENUE_BARS", raising=False)
    assert type(_fallback_provider("kraken")) is KrakenSpotOHLCVProvider
    assert _fallback_provider("bybit") is None          # OFF: not in the legacy set
    assert _fallback_provider("hyperliquid") is None

    monkeypatch.setenv("COSMU_PER_VENUE_BARS", "1")
    assert type(_fallback_provider("bybit")) is BybitSpotOHLCVProvider   # ON: its own native provider
    assert type(_fallback_provider("kraken")) is KrakenSpotOHLCVProvider
    assert _fallback_provider("hyperliquid") is None    # cache-only even when ON


# ====================================================================================================================
# 2. build_crypto_cells — flag OFF byte-identical, flag ON scores per-venue native bars
# ====================================================================================================================


def _build_with_kraken_stub(store, kraken_bars, ref_bars, monkeypatch):
    """Run build_crypto_cells with kraken's FALLBACK provider stubbed to `kraken_bars` and the reference to `ref_bars`."""
    import cosmu.data.price_cells as pc
    from cosmu.data.market import UniversalOHLCVProvider

    orig = pc._fallback_provider
    monkeypatch.setattr(
        pc, "_fallback_provider",
        lambda v: _StubProvider({"XBTUSD": kraken_bars}) if v == "kraken" else orig(v),
    )
    reference = UniversalOHLCVProvider(_StubProvider({"BTCUSDT": ref_bars}))
    return build_crypto_cells(store, timeframe="1d", limit=300, enabled_venues={"binance", "kraken"},
                              reference=reference)


def test_off_path_unifies_kraken_onto_reference_byte_identical(tmp_path, monkeypatch):
    """FLAG OFF: a corr~1 + tiny-spread kraken cell UNIFIES — its bars ARE the reference object (the legacy de-dup),
    reuses_reference True. This is the unchanged default behaviour."""
    monkeypatch.delenv("COSMU_PER_VENUE_BARS", raising=False)
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [("binance", "BTCUSDT", "BTC", "USDT"), ("kraken", "XBTUSD", "XBT", "ZUSD")])
    ref_closes = _walk(150, seed=10)
    cells = _build_with_kraken_stub(store, _bars([c * 1.0005 for c in ref_closes]), _bars(ref_closes), monkeypatch)
    by_venue = {c.venue_id: c for c in cells}
    assert by_venue["kraken"].reuses_reference is True
    assert by_venue["kraken"].bars is by_venue["binance"].bars       # THE de-dup: same object reused
    assert by_venue["kraken"].decision.verdict == "UNIFY"


def test_on_path_scores_kraken_on_its_own_native_bars_not_the_reference(tmp_path, monkeypatch):
    """FLAG ON: the SAME corr~1 kraken cell is now scored on KRAKEN's OWN native bars (not the reference proxy) —
    reuses_reference False, and the bars are NOT the reference object. 'Each bar per venue.'"""
    monkeypatch.setenv("COSMU_PER_VENUE_BARS", "1")
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [("binance", "BTCUSDT", "BTC", "USDT"), ("kraken", "XBTUSD", "XBT", "ZUSD")])
    ref_closes = _walk(150, seed=10)
    kraken_bars = _bars([c * 1.0005 for c in ref_closes])  # corr~1: OFF would UNIFY; ON must keep native
    cells = _build_with_kraken_stub(store, kraken_bars, _bars(ref_closes), monkeypatch)
    by_venue = {c.venue_id: c for c in cells}
    kraken = by_venue["kraken"]
    assert kraken.reuses_reference is False                          # scored on its OWN series
    assert kraken.bars is not by_venue["binance"].bars               # NOT the reference object
    assert [float(b.close) for b in kraken.bars] == [float(b.close) for b in kraken_bars]
    # The alignment verdict is still computed for inspectability (it WOULD be UNIFY), but doesn't move the bars.
    assert kraken.decision is not None and kraken.decision.verdict == "UNIFY"
    # The binance reference cell is unchanged either way.
    assert by_venue["binance"].venue_id == REFERENCE_VENUE and by_venue["binance"].reuses_reference is True


def test_on_path_sparse_native_bars_fall_back_to_reference(tmp_path, monkeypatch):
    """FLAG ON: a venue whose native series is TOO SPARSE (< the trustable-overlap floor) FALLS BACK to the reference
    series so the cell can still screen — reuses_reference True (the documented missing/sparse degrade)."""
    monkeypatch.setenv("COSMU_PER_VENUE_BARS", "1")
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [("binance", "BTCUSDT", "BTC", "USDT"), ("kraken", "XBTUSD", "XBT", "ZUSD")])
    ref_closes = _walk(150, seed=11)
    sparse = _bars(ref_closes[: UNIFY_MIN_OVERLAP - 5])  # fewer than the floor → too sparse
    cells = _build_with_kraken_stub(store, sparse, _bars(ref_closes), monkeypatch)
    by_venue = {c.venue_id: c for c in cells}
    kraken = by_venue["kraken"]
    assert kraken.reuses_reference is True                           # fell back to the reference
    assert kraken.bars is by_venue["binance"].bars                  # the shared reference object


def test_on_path_missing_native_bars_fall_back_to_reference(tmp_path, monkeypatch):
    """FLAG ON: a venue whose native fetch returns NOTHING still screens by falling back to the reference (a real
    reference exists) — reuses_reference True. With NO reference either, the cell is skipped (covered elsewhere)."""
    monkeypatch.setenv("COSMU_PER_VENUE_BARS", "1")
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [("binance", "BTCUSDT", "BTC", "USDT"), ("kraken", "XBTUSD", "XBT", "ZUSD")])
    ref_closes = _walk(150, seed=12)
    cells = _build_with_kraken_stub(store, [], _bars(ref_closes), monkeypatch)  # kraken native = empty
    by_venue = {c.venue_id: c for c in cells}
    assert by_venue["kraken"].reuses_reference is True
    assert by_venue["kraken"].bars is by_venue["binance"].bars


def test_empty_universe_path_is_byte_identical_regardless_of_flag(tmp_path, monkeypatch):
    """The empty-universe FALLBACK path (no universe_pairs rows) is byte-identical with the flag ON or OFF — it never
    builds non-reference cells, so the per-venue branch is moot. Guards the most-common screen path."""
    from cosmu.data.market import UniversalOHLCVProvider

    store = _store(tmp_path)
    store.migrate()
    closes = _walk(150, seed=13)
    ref = UniversalOHLCVProvider(_StubProvider({"BTCUSDT": _bars(closes), "ETHUSDT": _bars(closes)}))
    for flag in ("0", "1"):
        monkeypatch.setenv("COSMU_PER_VENUE_BARS", flag)
        cells = build_crypto_cells(store, timeframe="1d", limit=200, enabled_venues={"binance"},
                                   reference=ref, fallback_symbols=("BTCUSDT", "ETHUSDT"))
        assert {c.key for c in cells} == {"BTCUSDT", "ETHUSDT"}
        assert all(c.venue_id == REFERENCE_VENUE and c.reuses_reference and c.key == c.symbol for c in cells)


# ====================================================================================================================
# 3. R2 PRICE ARCHIVE — write/read round-trip, idempotent union-merge never shrinks, R2-absent no-op
# ====================================================================================================================


def test_archive_key_strips_slash_and_namespaces_by_venue():
    """The R2 key mirrors the on-disk cache filename: bars/<venue>/<SYMBOL>_<tf>.json, '/' stripped from the symbol."""
    assert bar_archive.archive_key("kraken", "XBT/USD", "1d") == "bars/kraken/XBTUSD_1d.json"
    assert bar_archive.archive_key("binance", "BTCUSDT", "1h") == "bars/binance/BTCUSDT_1h.json"


def test_archive_write_then_read_round_trips_bars():
    """archive_bars writes a series to R2; load_archived_bars reads it back identically (one PUT, then a GET)."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    bars = _bars(_walk(100, seed=1))
    merged = bar_archive.archive_bars("kraken", "XBTUSD", "1d", bars, settings=settings, s3=s3)
    assert len(merged) == len(bars)
    loaded = bar_archive.load_archived_bars("kraken", "XBTUSD", "1d", settings=settings, s3=s3)
    assert [float(b.close) for b in loaded] == [float(b.close) for b in bars]
    assert [b.ts for b in loaded] == [b.ts for b in bars]


def test_archive_union_merge_never_shrinks_and_accumulates_history():
    """The CORE invariant: a SECOND archive of a NEWER, shorter window UNION-MERGES into the stored series — it can
    only GROW. The shallow keyless window accumulates into deep history; old bars are never dropped."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    # First archive: bars Jan 1..Jan 30 (deep history already on R2).
    early = _bars(_walk(29, seed=2), start=datetime(2024, 1, 1, tzinfo=UTC))
    bar_archive.archive_bars("bybit", "BTCUSDT", "1d", early, settings=settings, s3=s3)
    # Second archive: a SHORT NEW window Jan 20..Feb 8 (overlaps the tail, extends the front) — the live ~720 window.
    later = _bars(_walk(19, seed=3), start=datetime(2024, 1, 20, tzinfo=UTC))
    merged = bar_archive.archive_bars("bybit", "BTCUSDT", "1d", later, settings=settings, s3=s3)
    # Union of the two date ranges, deduped on ts — strictly DEEPER than either input, never shorter than the first.
    ts_union = sorted({b.ts for b in early} | {b.ts for b in later})
    assert [b.ts for b in merged] == ts_union
    assert len(merged) >= len(early) and len(merged) > len(later)


def test_archive_is_idempotent_no_redundant_put():
    """Re-archiving the SAME window is a pure no-op merge — no second PUT (one GET, no write). Idempotent by ts."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    bars = _bars(_walk(80, seed=4))
    bar_archive.archive_bars("kraken", "XBTUSD", "1d", bars, settings=settings, s3=s3)
    assert s3.put_calls == 1
    bar_archive.archive_bars("kraken", "XBTUSD", "1d", bars, settings=settings, s3=s3)  # identical re-archive
    assert s3.put_calls == 1  # no redundant write


def test_load_archived_merges_deep_history_with_live_window():
    """load_archived_bars(live=...) UNION-MERGES the deep R2 history with the shallow live window — the caller sees
    the full accumulated depth even though the live fetch is shallow. Live bars win a ts collision."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    deep = _bars([100.0 + i for i in range(40)], start=datetime(2024, 1, 1, tzinfo=UTC))  # Jan 1..Feb 9
    bar_archive.archive_bars("kraken", "XBTUSD", "1d", deep, settings=settings, s3=s3)
    # The live window is just the most-recent ~10 bars (the keyless REST window).
    live = _bars([999.0 + i for i in range(10)], start=datetime(2024, 2, 5, tzinfo=UTC))  # overlaps the tail
    out = bar_archive.load_archived_bars("kraken", "XBTUSD", "1d", live=live, settings=settings, s3=s3)
    # Full union by ts; the overlap rows take the LIVE values (a freshly closed bar repairs the archived one).
    assert len(out) == len({b.ts for b in deep} | {b.ts for b in live})
    by_ts = {b.ts: float(b.close) for b in out}
    assert by_ts[datetime(2024, 2, 5, tzinfo=UTC)] == 999.0  # live wins the collision


def test_archive_r2_absent_is_graceful_no_op():
    """R2 creds ABSENT → archive_bars returns the input UNCHANGED and load returns the live window UNCHANGED (keyless
    degradation), never crashes the caller, never touches a client."""
    settings = _settings_no_r2()
    bars = _bars(_walk(30, seed=5))
    # No s3 injected + no creds → no-op write (returns input).
    out = bar_archive.archive_bars("kraken", "XBTUSD", "1d", bars, settings=settings)
    assert out is bars
    # Read with a live window and no creds → returns the live window unchanged.
    live = _bars(_walk(5, seed=6))
    assert bar_archive.load_archived_bars("kraken", "XBTUSD", "1d", live=live, settings=settings) is live
    # Read with no archive + no live → empty.
    assert bar_archive.load_archived_bars("kraken", "XBTUSD", "1d", settings=settings) == []


# ====================================================================================================================
# 4. The sync job — push the local cache to R2 (union-merge per file), R2-absent no-op
# ====================================================================================================================


def test_sync_local_cache_uploads_every_venue_symbol_file(tmp_path):
    """sync_local_cache mirrors `<root>/<venue>/<SYMBOL>_<tf>.json` → R2 archive objects, one per series, union-merged."""
    root = tmp_path / "market_data"
    # Build a local cache: kraken + bybit, two symbols.
    for venue, sym, closes in [
        ("kraken", "XBTUSD", _walk(50, seed=1)),
        ("kraken", "ETHUSD", _walk(50, seed=2)),
        ("bybit", "BTCUSDT", _walk(50, seed=3)),
    ]:
        d = root / venue
        d.mkdir(parents=True, exist_ok=True)
        from cosmu.data.market import _bars_to_rows

        (d / f"{sym}_1d.json").write_text(json.dumps(_bars_to_rows(_bars(closes))))
    # A non-bar file is skipped, not crashed on.
    (root / "kraken" / "notes.txt").write_text("ignore me")

    s3 = _FakeS3()
    settings = _settings_with_r2()
    result = bar_archive.sync_local_cache(cache_root=root, settings=settings, s3=s3)
    assert result["synced"] == 3
    # Every series landed at its venue-namespaced key.
    keys = {k for (_b, k) in s3.store}
    assert keys == {
        "bars/kraken/XBTUSD_1d.json", "bars/kraken/ETHUSD_1d.json", "bars/bybit/BTCUSDT_1d.json",
    }


def test_sync_local_cache_r2_absent_is_no_op(tmp_path):
    """R2 creds absent → sync is a loud no-op ({'synced': 0, ...}), never crashes."""
    root = tmp_path / "market_data" / "kraken"
    root.mkdir(parents=True)
    from cosmu.data.market import _bars_to_rows

    (root / "XBTUSD_1d.json").write_text(json.dumps(_bars_to_rows(_bars(_walk(10, seed=1)))))
    result = bar_archive.sync_local_cache(cache_root=tmp_path / "market_data", settings=_settings_no_r2())
    assert result == {"synced": 0, "skipped": 0, "files": 0, "archived_bars": 0}


def test_parse_cache_filename_handles_symbol_and_timeframe():
    """The cache-filename splitter peels the LAST '_<tf>' token (symbols have no '_'); non-bar names → None."""
    assert bar_archive._parse_cache_filename("BTCUSDT_1d.json") == ("BTCUSDT", "1d")
    assert bar_archive._parse_cache_filename("XBTUSD_4h.json") == ("XBTUSD", "4h")
    assert bar_archive._parse_cache_filename("notes.txt") is None
    assert bar_archive._parse_cache_filename("nounderscore.json") is None


# ====================================================================================================================
# 5. archive_universe_bars — the HOARD step: gather Tier-0/1 crypto bars from the keyless venues into R2
# ====================================================================================================================


def _stub_provider_for(by_venue_symbol: dict[tuple[str, str], list[Bar]], *, raise_on=None):
    """A `provider_for(venue)` factory: returns a _StubProvider whose bars are keyed by symbol for `venue`, or None
    when the venue has no entry (mirrors keyless_venue_provider's cache-only/unknown → None). `raise_on` is a set of
    (venue, symbol) pairs whose fetch RAISES — to prove one fetch error is skipped, never aborts the loop."""
    raise_on = raise_on or set()

    class _Prov:
        def __init__(self, venue: str) -> None:
            self._venue = venue

        def fetch_bars(self, symbol: str, timeframe: str, *, limit: int):  # noqa: ARG002
            if (self._venue, symbol) in raise_on:
                raise RuntimeError(f"boom {self._venue}:{symbol}")
            return by_venue_symbol.get((self._venue, symbol), [])[-limit:]

    venues_present = {v for (v, _s) in by_venue_symbol} | {v for (v, _s) in raise_on}

    def factory(venue: str):
        return _Prov(venue) if venue in venues_present else None

    return factory


def test_archive_universe_bars_writes_per_venue_and_symbol():
    """The hoard fetches each (venue, symbol) keyless window and archives it under bars/<venue>/<SYMBOL>_<tf>.json.
    With two venues × two symbols, four R2 objects land — the deep-history seed the cacheless fleet accumulates."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    bars = _bars(_walk(50, seed=1))
    pf = _stub_provider_for({
        ("kraken", "BTCUSDT"): bars, ("kraken", "ETHUSDT"): bars,
        ("binance", "BTCUSDT"): bars, ("binance", "ETHUSDT"): bars,
    })
    result = bar_archive.archive_universe_bars(
        store=None, venues=("kraken", "binance"), timeframes=("1d",),
        settings=settings, s3=s3, provider_for=pf,
        # store=None → PERP_UNIVERSE fallback; cap to the two symbols our stub serves so the assert is exact.
        max_symbols=2,
    )
    assert result["archived"] == 4
    keys = {k for (_b, k) in s3.store}
    assert keys == {
        "bars/kraken/BTCUSDT_1d.json", "bars/kraken/ETHUSDT_1d.json",
        "bars/binance/BTCUSDT_1d.json", "bars/binance/ETHUSDT_1d.json",
    }


def test_archive_universe_bars_is_idempotent_across_runs():
    """Two identical hoard passes leave the stored series unchanged — the SECOND pass is a pure no-op merge (one GET,
    no PUT per series). This is what makes the hourly cron accumulate without ever re-writing settled history."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    pf = _stub_provider_for({("kraken", "BTCUSDT"): _bars(_walk(40, seed=2))})
    common = dict(store=None, venues=("kraken",), timeframes=("1d",), max_symbols=1,
                  settings=settings, s3=s3, provider_for=pf)
    bar_archive.archive_universe_bars(**common)
    puts_after_first = s3.put_calls
    assert puts_after_first == 1
    bar_archive.archive_universe_bars(**common)  # identical second pass
    assert s3.put_calls == puts_after_first  # no redundant write — idempotent


def test_archive_universe_bars_accumulates_deep_history_across_runs():
    """The CORE hoard invariant: a later pass returning a NEWER, shorter keyless window UNION-MERGES into the deep R2
    series — it only GROWS. The shallow keyless window accumulates into history the single REST call can't serve."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    early = _bars(_walk(29, seed=3), start=datetime(2024, 1, 1, tzinfo=UTC))
    later = _bars(_walk(19, seed=4), start=datetime(2024, 1, 20, tzinfo=UTC))
    bar_archive.archive_universe_bars(
        store=None, venues=("kraken",), timeframes=("1d",), max_symbols=1,
        settings=settings, s3=s3, provider_for=_stub_provider_for({("kraken", "BTCUSDT"): early}),
    )
    bar_archive.archive_universe_bars(
        store=None, venues=("kraken",), timeframes=("1d",), max_symbols=1,
        settings=settings, s3=s3, provider_for=_stub_provider_for({("kraken", "BTCUSDT"): later}),
    )
    stored = bar_archive.load_archived_bars("kraken", "BTCUSDT", "1d", settings=settings, s3=s3)
    ts_union = sorted({b.ts for b in early} | {b.ts for b in later})
    assert [b.ts for b in stored] == ts_union
    assert len(stored) > len(later)  # strictly deeper than the latest shallow window


def test_archive_universe_bars_r2_absent_is_no_op():
    """R2 creds ABSENT → the hoard is a loud no-op ({'archived': 0, ...}), never touches a provider or a client."""
    pf = _stub_provider_for({("kraken", "BTCUSDT"): _bars(_walk(10, seed=5))})
    result = bar_archive.archive_universe_bars(
        store=None, venues=("kraken",), timeframes=("1d",), max_symbols=1,
        settings=_settings_no_r2(), provider_for=pf,  # no s3 + no creds → must short-circuit before any fetch
    )
    assert result == {"archived": 0, "skipped": 0, "cells": 0, "archived_bars": 0, "venues": 0, "symbols": 0}


def test_archive_universe_bars_is_bounded_by_max_cells():
    """The hard cell ceiling bounds one run: with 5 symbols × 2 venues but max_cells=3, exactly 3 fetches happen and
    the loop stops — so a wide universe can never fan out past the cost cap in a single pass."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    # store=None → the static PERP_UNIVERSE fallback (BTCUSDT, ETHUSDT, BNBUSDT, …) drives the symbol order; seed the
    # stub for the first 5 so every fetched cell has bars and the only stop reason is the max_cells ceiling.
    from cosmu.data.universe import PERP_UNIVERSE

    syms = list(PERP_UNIVERSE[:5])
    by = {(v, s): _bars(_walk(20, seed=hash((v, s)) % 1000)) for v in ("kraken", "binance") for s in syms}
    result = bar_archive.archive_universe_bars(
        store=None, venues=("kraken", "binance"), timeframes=("1d",),
        max_symbols=5, max_cells=3, settings=settings, s3=s3, provider_for=_stub_provider_for(by),
    )
    assert result["cells"] == 3
    assert result["archived"] == 3  # all three fetched cells had bars
    assert len(s3.store) == 3  # exactly three series written — the ceiling held


def test_archive_universe_bars_one_fetch_error_is_skipped_not_aborted():
    """One (venue, symbol) fetch that RAISES is logged + skipped — the loop continues and the OTHER symbols still
    archive. A flaky venue can never abort the whole hoard."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    bars = _bars(_walk(30, seed=7))
    # store=None → the first 3 PERP_UNIVERSE names (BTCUSDT, ETHUSDT, BNBUSDT); raise on the MIDDLE one.
    pf = _stub_provider_for(
        {("kraken", "BTCUSDT"): bars, ("kraken", "ETHUSDT"): bars, ("kraken", "BNBUSDT"): bars},
        raise_on={("kraken", "ETHUSDT")},  # the middle symbol blows up
    )
    result = bar_archive.archive_universe_bars(
        store=None, venues=("kraken",), timeframes=("1d",), max_symbols=3,
        settings=settings, s3=s3, provider_for=pf,
    )
    assert result["cells"] == 3
    assert result["archived"] == 2 and result["skipped"] == 1  # the error was skipped, the loop continued
    keys = {k for (_b, k) in s3.store}
    assert keys == {"bars/kraken/BTCUSDT_1d.json", "bars/kraken/BNBUSDT_1d.json"}  # ETHUSDT absent


def test_archive_universe_bars_skips_cache_only_venue_with_no_route():
    """A venue with no keyless route (provider_for → None, like hyperliquid/equity) is skipped honestly — never
    fabricates bars, never crashes — while the live-route venue still hoards."""
    s3 = _FakeS3()
    settings = _settings_with_r2()
    pf = _stub_provider_for({("kraken", "BTCUSDT"): _bars(_walk(20, seed=8))})  # only kraken has a route
    result = bar_archive.archive_universe_bars(
        store=None, venues=("kraken", "hyperliquid"), timeframes=("1d",), max_symbols=1,
        settings=settings, s3=s3, provider_for=pf,
    )
    assert result["archived"] == 1  # only kraken archived; hyperliquid had no route → skipped
    assert {k for (_b, k) in s3.store} == {"bars/kraken/BTCUSDT_1d.json"}


def test_archive_universe_bars_reads_tier01_symbols_from_the_store(tmp_path):
    """When a store is given, the hoard pulls the Tier-0/1 liquidity-ranked crypto symbols from universe_pairs (not
    the static fallback). Seed two Tier-0 rows + one Tier-2 row; only the Tier-0/1 names are fetched/archived."""
    store = _store(tmp_path)
    store.migrate()
    # Tier-0 (hoarded) BTC/ETH + a Tier-2 (NOT hoarded) tail name, all on binance spot.
    with store.batch() as b:
        for sym, tier, liq in [("BTCUSDT", 0, 9e9), ("ETHUSDT", 0, 8e9), ("TAILUSDT", 2, 1e6)]:
            b.insert("universe_pairs", {
                "id": f"binance:{sym}", "venue": "binance", "symbol": sym, "base": sym[:-4], "quote": "USDT",
                "asset_class": "crypto", "instrument_type": "spot", "liquidity_usd_24h": liq,
                "tier": tier, "rank": 0, "active": 1, "source": "live", "fetched_at": "2024-01-01T00:00:00+00:00",
            })
    s3 = _FakeS3()
    bars = _bars(_walk(20, seed=9))
    pf = _stub_provider_for({("binance", s): bars for s in ("BTCUSDT", "ETHUSDT", "TAILUSDT")})
    result = bar_archive.archive_universe_bars(
        store=store, venues=("binance",), timeframes=("1d",),
        settings=_settings_with_r2(), s3=s3, provider_for=pf,
    )
    # Only the two Tier-0 names hoarded; the Tier-2 tail name is excluded by the Tier-0/1 filter.
    assert result["archived"] == 2
    assert {k for (_b, k) in s3.store} == {"bars/binance/BTCUSDT_1d.json", "bars/binance/ETHUSDT_1d.json"}
