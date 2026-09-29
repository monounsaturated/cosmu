# Per-market Polymarket odds ingest: the PerMarketOddsSource resolves a conditionId to its YES clobTokenId via
# Gamma, fetches the CLOB /prices-history, and the ingest stores the series keyed by conditionId under
# (provider="polymarket", metric="odds") — the exact shape PredictionDataAdapter reads back. Idempotent
# (append-only, no dup). All hermetic: the CLOB + Gamma are mocked.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataStore
from cosmu.data.sources.polymarket import PerMarketOddsSource
from cosmu.ingest.polymarket_odds import (
    PerMarketIngestResult,
    ingest_per_market_odds,
    ingest_per_market_odds_hourly,
    top_liquid_condition_ids,
)
from cosmu.knowledge.store import Store

_CID = "0xCONDITION_A"
_CID_B = "0xCONDITION_B"
_YES_TOKEN = "111yes"
_YES_TOKEN_B = "222yes"

# A bucket-of-3 daily history (unix t, midpoint p). 2024-01-01..03.
_HIST = {"history": [
    {"t": 1704067200, "p": 0.40},
    {"t": 1704153600, "p": 0.45},
    {"t": 1704240000, "p": 0.55},
]}


def _gamma_for(cid_to_token: dict[str, str]):
    def fetcher(url: str):
        # url shape: .../markets?condition_ids=<cid>
        cid = url.rsplit("condition_ids=", 1)[-1]
        token = cid_to_token.get(cid)
        if token is None:
            return []
        return [{"conditionId": cid, "clobTokenIds": [token, "no_token"]}]
    return fetcher


def _clob_for(token_to_hist: dict[str, dict]):
    def fetcher(url: str):
        # url shape: .../prices-history?market=<token>&...
        token = url.split("market=", 1)[-1].split("&", 1)[0]
        return token_to_hist.get(token, {"history": []})
    return fetcher


def _source(cid_to_token, token_to_hist) -> PerMarketOddsSource:
    return PerMarketOddsSource(
        _gamma_fetcher=_gamma_for(cid_to_token),
        _clob_fetcher=_clob_for(token_to_hist),
    )


# --------------------------------------------------------------------------- source

def test_source_resolves_condition_to_yes_token():
    src = _source({_CID: _YES_TOKEN}, {})
    assert src.yes_token_for(_CID) == _YES_TOKEN
    assert src.yes_token_for("0xUNKNOWN") is None


def test_source_fetch_odds_two_hop_condition_to_history():
    src = _source({_CID: _YES_TOKEN}, {_YES_TOKEN: _HIST})
    points = src.fetch_odds(_CID)
    assert [round(p.value, 2) for p in points] == [0.40, 0.45, 0.55]
    # PIT look-ahead fix (scout #385 Fix-C5): available_at = ts + ONE BUCKET (here daily), so a backtest only
    # sees a bucket after it has fully closed — never the entry bar's own same-bucket price.
    assert all(p.available_at == p.ts + timedelta(days=1) for p in points)
    assert points[0].ts == datetime(2024, 1, 1, tzinfo=UTC)


def test_source_fetch_odds_hourly_fidelity_and_bucket_lag():
    # fidelity=60 (hourly) → the CLOB url carries fidelity=60 AND the PIT lag is one HOUR (not one day).
    seen: dict[str, str] = {}

    def clob(url: str):
        seen["url"] = url
        token = url.split("market=", 1)[-1].split("&", 1)[0]
        return {_YES_TOKEN: _HIST}.get(token, {"history": []})

    src = PerMarketOddsSource(_gamma_fetcher=_gamma_for({_CID: _YES_TOKEN}), _clob_fetcher=clob)
    points = src.fetch_odds(_CID, fidelity=60)
    assert "fidelity=60" in seen["url"]  # hourly variant hits the CLOB at fidelity=60
    assert all(p.available_at == p.ts + timedelta(hours=1) for p in points)  # +1-bucket lag scales with fidelity


def test_source_hourly_uses_windowed_startts_endts_not_interval_max():
    # DO #4 (readiness 2026-06-26): the trust experiment proved `interval=max&fidelity=60` silently returns
    # daily-or-NOTHING; true hourly spacing needs explicit startTs/endTs WINDOWS. The hourly path must therefore
    # NOT carry interval=max — it must carry startTs + endTs, paged across the market's life.
    urls: list[str] = []

    def clob(url: str):
        urls.append(url)
        # Serve ONE window's worth of hourly rows for the first page, then empty (so paging terminates).
        if "startTs" in url and len([u for u in urls if "startTs" in u]) == 1:
            base = 1709251200  # 2024-03-01
            return {"history": [{"t": base + 3600 * h, "p": 0.40 + 0.001 * h} for h in range(24)]}
        return {"history": []}

    src = PerMarketOddsSource(_gamma_fetcher=_gamma_for({_CID: _YES_TOKEN}), _clob_fetcher=clob)
    points = src.fetch_odds(_CID, fidelity=60)
    assert points, "hourly windowed fetch returned rows"
    # Hourly path: every URL is a windowed request (startTs+endTs+fidelity=60), NEVER interval=max.
    assert all("startTs=" in u and "endTs=" in u and "fidelity=60" in u for u in urls)
    assert all("interval=max" not in u for u in urls)
    # True hourly spacing: consecutive ts are 3600s apart.
    assert (points[1].ts - points[0].ts) == timedelta(hours=1)
    # +1-bucket PIT lag scales with the hourly bucket.
    assert all(p.available_at == p.ts + timedelta(hours=1) for p in points)


def test_source_daily_still_uses_interval_max():
    # The DAILY path is unchanged: the single interval=max call (NO windowing) — byte-identical to before.
    seen: list[str] = []

    def clob(url: str):
        seen.append(url)
        token = url.split("market=", 1)[-1].split("&", 1)[0]
        return {_YES_TOKEN: _HIST}.get(token, {"history": []})

    src = PerMarketOddsSource(_gamma_fetcher=_gamma_for({_CID: _YES_TOKEN}), _clob_fetcher=clob)
    points = src.fetch_odds(_CID)  # fidelity defaults to 1440 (daily)
    assert [round(p.value, 2) for p in points] == [0.40, 0.45, 0.55]
    assert len(seen) == 1 and "interval=max" in seen[0] and "startTs" not in seen[0]


def test_source_empty_on_unresolvable_token():
    src = _source({}, {_YES_TOKEN: _HIST})  # gamma resolves nothing
    assert src.fetch_odds(_CID) == []


def test_source_empty_on_dead_clob_fetch():
    def boom(_url: str):
        raise RuntimeError("network down")
    src = PerMarketOddsSource(_gamma_fetcher=_gamma_for({_CID: _YES_TOKEN}), _clob_fetcher=boom)
    assert src.fetch_odds(_CID) == []  # one dead fetch → [] for that market, never a raise


# --------------------------------------------------------------------------- ingest

def _store(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/pm.sqlite3", openrouter_api_key=None))
    return store


def _seed_universe(store: Store, rows: list[tuple[str, float]]) -> None:
    with store.batch() as w:
        w.insert_many(
            "universe_pairs",
            ["id", "venue", "symbol", "asset_class", "instrument_type", "liquidity_usd_24h", "active", "source", "fetched_at"],
            [(f"polymarket:{cid}", "polymarket", cid, "prediction", "prediction", liq, 1, "live", "2026-06-18T00:00:00+00:00") for cid, liq in rows],
            ignore_duplicates=True,
        )


def test_top_liquid_condition_ids_ranks_by_liquidity_desc(tmp_path):
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 100.0), (_CID_B, 500.0)])
    assert top_liquid_condition_ids(store, max_markets=10) == [_CID_B, _CID]  # most-liquid first
    assert top_liquid_condition_ids(store, max_markets=1) == [_CID_B]


def test_ingest_stores_odds_keyed_by_condition_id(tmp_path):
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 500.0)])
    alt = AltDataStore(root=tmp_path / "alt")
    src = _source({_CID: _YES_TOKEN}, {_YES_TOKEN: _HIST})

    results = ingest_per_market_odds(alt, store, source=src, max_markets=10)
    assert results == [PerMarketIngestResult(condition_id=_CID, written=3, total=3)]
    # Stored under the conditionId — exactly the key PredictionDataAdapter.bars() reads.
    stored = alt.read_all("polymarket", _CID, "odds")
    assert [round(p.value, 2) for p in stored] == [0.40, 0.45, 0.55]


def test_ingest_is_idempotent(tmp_path):
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 500.0)])
    alt = AltDataStore(root=tmp_path / "alt")
    src = _source({_CID: _YES_TOKEN}, {_YES_TOKEN: _HIST})

    first = ingest_per_market_odds(alt, store, source=src, max_markets=10)
    second = ingest_per_market_odds(alt, store, source=src, max_markets=10)
    assert first[0].written == 3
    assert second[0].written == 0  # re-run writes nothing new (append-only, ts-deduped)
    assert len(alt.read_all("polymarket", _CID, "odds")) == 3  # no duplicate rows


def test_ingest_isolates_per_market_failure(tmp_path):
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 500.0), (_CID_B, 400.0)])
    alt = AltDataStore(root=tmp_path / "alt")
    # Only _CID resolves + has history; _CID_B resolves but its CLOB history is empty.
    src = _source({_CID: _YES_TOKEN, _CID_B: _YES_TOKEN_B}, {_YES_TOKEN: _HIST})

    results = {r.condition_id: r for r in ingest_per_market_odds(alt, store, source=src, max_markets=10)}
    assert results[_CID].written == 3
    assert results[_CID_B].written == 0  # dead market → 0 rows, batch continued


def test_ingest_hourly_uses_fidelity_60_and_distinct_metric(tmp_path):
    # The hourly variant ingests at fidelity=60 AND stores under metric="odds_60" — distinct from the daily
    # "odds" series so the two cadences never co-mingle in one (provider, symbol, metric) keyspace.
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 500.0)])
    alt = AltDataStore(root=tmp_path / "alt")
    seen: dict[str, str] = {}

    def clob(url: str):
        seen["url"] = url
        token = url.split("market=", 1)[-1].split("&", 1)[0]
        return {_YES_TOKEN: _HIST}.get(token, {"history": []})

    src = PerMarketOddsSource(_gamma_fetcher=_gamma_for({_CID: _YES_TOKEN}), _clob_fetcher=clob)
    results = ingest_per_market_odds_hourly(alt, store, source=src, max_markets=10)

    assert "fidelity=60" in seen["url"]  # hourly cadence reached the CLOB
    assert results == [PerMarketIngestResult(condition_id=_CID, written=3, total=3)]
    # Stored under "odds_60", NOT "odds" — the per-cell min-trades Gate reads the denser hourly series here.
    assert len(alt.read_all("polymarket", _CID, "odds_60")) == 3
    assert alt.read_all("polymarket", _CID, "odds") == []  # daily series untouched by the hourly run
    # +1-bucket PIT lag carried through the ingest (hourly bucket = one hour).
    assert all(p.available_at == p.ts + timedelta(hours=1) for p in alt.read_all("polymarket", _CID, "odds_60"))


def test_ingest_carries_one_bucket_pit_lag(tmp_path):
    # The daily ingest persists available_at = ts + one DAY (the look-ahead fix), so read_asof at the bucket's own
    # ts sees NOTHING and only sees the point a full day later — the entry bar can't use its own bucket price.
    store = _store(tmp_path)
    _seed_universe(store, [(_CID, 500.0)])
    alt = AltDataStore(root=tmp_path / "alt")
    src = _source({_CID: _YES_TOKEN}, {_YES_TOKEN: _HIST})

    ingest_per_market_odds(alt, store, source=src, max_markets=10)
    first_ts = datetime(2024, 1, 1, tzinfo=UTC)
    # As-of the first bucket's own timestamp: not yet available (lagged one day) → empty.
    assert alt.read_asof("polymarket", _CID, "odds", first_ts) == []
    # As-of one day later: the first bucket is now knowable.
    visible = alt.read_asof("polymarket", _CID, "odds", first_ts + timedelta(days=1))
    assert [round(p.value, 2) for p in visible] == [0.40]
