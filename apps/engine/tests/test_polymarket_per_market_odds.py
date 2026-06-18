# Per-market Polymarket odds ingest: the PerMarketOddsSource resolves a conditionId to its YES clobTokenId via
# Gamma, fetches the CLOB /prices-history, and the ingest stores the series keyed by conditionId under
# (provider="polymarket", metric="odds") — the exact shape PredictionDataAdapter reads back. Idempotent
# (append-only, no dup). All hermetic: the CLOB + Gamma are mocked.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataStore
from cosmu.data.sources.polymarket import PerMarketOddsSource
from cosmu.ingest.polymarket_odds import (
    PerMarketIngestResult,
    ingest_per_market_odds,
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
    # PIT: a CLOB midpoint is known at its own bucket time (no declared release lag).
    assert all(p.available_at == p.ts for p in points)
    assert points[0].ts == datetime(2024, 1, 1, tzinfo=UTC)


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
