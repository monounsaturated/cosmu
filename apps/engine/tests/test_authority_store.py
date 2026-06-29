# PERSISTENCE for the AUTHORITY feature (cosmu/authority/store.py) — the proprietary data store. Pins:
#   * a call corpus round-trips (persist → load) and a re-fed dump is DEDUPED (no double-count);
#   * build_scoreboard scores the corpus against an injected tape (offline, no network);
#   * persist_scoreboard → load_scoreboard round-trips a composite row incl. the top_movers JSON, composite DESC
#     with UNTESTED (NULL composite) last;
#   * DEFENSIVE reads — a fresh DB with no tables returns the honest empty state (these run on a schema'd store,
#     so we assert the empty-corpus and empty-scoreboard shapes rather than dropping the table).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.authority.models import AccountCall, PricePoint
from cosmu.authority.store import (
    build_scoreboard,
    load_calls,
    load_scoreboard,
    persist_calls,
    persist_scoreboard,
)
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store

T0 = datetime(2024, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(days=120)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/authority.sqlite3", openrouter_api_key=None, _env_file=None))


def _call(account: str, asset: str, direction: str, day: int, *, call_id: str = "") -> AccountCall:
    return AccountCall(account=account, platform="x", asset=asset, direction=direction,  # type: ignore[arg-type]
                       ts=T0 + timedelta(days=day), conviction=0.6, call_id=call_id, source="json")


def test_calls_roundtrip_and_dedupe(tmp_path):
    store = _store(tmp_path)
    calls = [_call("@a", "BTC", "up", 10, call_id="1"), _call("@a", "ETH", "down", 12, call_id="2")]

    assert persist_calls(store, calls) == 2
    # Re-feeding the same dump writes nothing new (deduped on the stable key).
    assert persist_calls(store, calls) == 0
    # A genuinely new call is added.
    assert persist_calls(store, [_call("@b", "BTC", "up", 14, call_id="3")]) == 1

    loaded = load_calls(store)
    assert len(loaded) == 3
    assert {c.account for c in loaded} == {"@a", "@b"}
    assert loaded[0].asset == "BTC" and loaded[0].ts == T0 + timedelta(days=10)  # ordered by ts


def test_build_and_persist_scoreboard_roundtrip(tmp_path):
    store = _store(tmp_path)
    # @up calls BTC up; BTC ramps up → a resolved hit. Tape injected (no network).
    persist_calls(store, [_call("@up", "BTC", "up", 10, call_id="u1"), _call("@up", "BTC", "up", 15, call_id="u2")])
    tape = {"BTC": [PricePoint(ts=T0 + timedelta(days=i), price=100.0 + 2.0 * i) for i in range(60)]}

    scores = build_scoreboard(store, tape, now=NOW)
    assert len(scores) == 1 and scores[0].account == "@up"
    assert scores[0].n_resolved == 2 and scores[0].hit_rate == 1.0

    written = persist_scoreboard(store, scores)
    assert written == 1

    rows = load_scoreboard(store)
    assert len(rows) == 1
    row = rows[0]
    assert row["account"] == "@up" and row["platform"] == "x"
    assert row["n_resolved"] == 2 and row["hit_rate"] == 1.0
    assert isinstance(row["top_movers"], list) and len(row["top_movers"]) >= 1
    assert row["composite"] is not None


def test_scoreboard_orders_composite_desc_untested_last(tmp_path):
    store = _store(tmp_path)
    # @sharp resolves (BTC up, ramps up). @pending only has a call too recent to resolve → UNTESTED (NULL composite).
    persist_calls(store, [
        _call("@sharp", "BTC", "up", 10, call_id="s1"),
        _call("@pending", "BTC", "up", 118, call_id="p1"),
    ])
    tape = {"BTC": [PricePoint(ts=T0 + timedelta(days=i), price=100.0 + 2.0 * i) for i in range(121)]}
    scores = build_scoreboard(store, tape, now=T0 + timedelta(days=119))
    persist_scoreboard(store, scores)

    rows = load_scoreboard(store)
    assert [r["account"] for r in rows] == ["@sharp", "@pending"]  # tested first, untested last
    assert rows[0]["composite"] is not None
    assert rows[1]["composite"] is None and rows[1]["n_resolved"] == 0  # honest untested, never 0


def test_scoreboard_persists_relative_ranking(tmp_path):
    """Two tested accounts → the scoreboard persists + serves their RELATIVE standing (rank/percentile/z)."""
    store = _store(tmp_path)
    persist_calls(store, [_call("@a", "BTC", "up", 10, call_id="a1"), _call("@b", "BTC", "down", 10, call_id="b1")])
    tape = {"BTC": [PricePoint(ts=T0 + timedelta(days=i), price=100.0 + 2.0 * i) for i in range(60)]}  # ramps up

    persist_scoreboard(store, build_scoreboard(store, tape, now=NOW))
    rows = {r["account"]: r for r in load_scoreboard(store)}

    assert rows["@a"]["rank"] == 1 and rows["@b"]["rank"] == 2          # @a (up) correct outranks @b (down)
    assert rows["@a"]["percentile"] == 1.0 and rows["@b"]["percentile"] == 0.0
    assert rows["@a"]["composite_z"] is not None and rows["@a"]["composite_z"] > 0


def test_build_scoreboard_drops_sarcasm_and_neutral_before_scoring(tmp_path):
    """The pre-scoring actionable filter: a sarcasm call on the corpus never reaches the scorer, so it does not
    inflate the account's volume. With the filter OFF (diagnostics) the raw corpus is scored."""
    store = _store(tmp_path)
    real = AccountCall(account="@a", platform="x", asset="BTC", direction="up", ts=T0 + timedelta(days=10),
                       conviction=0.6, call_id="r", text="long BTC here, clear breakout", source="json")
    sarc = AccountCall(account="@a", platform="x", asset="BTC", direction="up", ts=T0 + timedelta(days=12),
                       conviction=0.6, call_id="s", text="buy BTC when MSTR goes to zero lol", source="json")
    persist_calls(store, [real, sarc])
    tape = {"BTC": [PricePoint(ts=T0 + timedelta(days=i), price=100.0 + 2.0 * i) for i in range(60)]}

    scores = build_scoreboard(store, tape, now=NOW)
    assert len(scores) == 1 and scores[0].n_calls == 1            # the sarcasm call was dropped before scoring
    raw = build_scoreboard(store, tape, now=NOW, drop_non_actionable=False)
    assert raw[0].n_calls == 2                                    # filter off → both count


def test_empty_store_is_honest_empty(tmp_path):
    store = _store(tmp_path)
    assert load_calls(store) == []
    assert load_scoreboard(store) == []
    assert build_scoreboard(store, {}, now=NOW) == []
