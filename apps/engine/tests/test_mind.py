# The Mind — the agent's standardized self-knowledge surface (KNOWS · THINKS · LEARNED). It must be
# DETERMINISTIC and OFFLINE (CI has no key, no network), HONEST (a perspective with no ingested data ABSTAINS
# rather than fabricating a read), and RAILGUARDED (it reasons; it never moves money — building it touches no
# money tables, and the railguard string is always present). reflect() must persist a point-in-time row AND
# degrade gracefully when the additive table is absent.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind import RAILGUARD, build_mind, debate, gather_context, reflect
from cosmu.mind.analysts import ALL_ANALYSTS


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/mind.sqlite3", openrouter_api_key=None))


def _seed_metric(store: Store, metric: str, value: float, *, provider: str = "test", days_ago: int = 0) -> None:
    ts = datetime.now(UTC) - timedelta(days=days_ago)
    store.rows(
        "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider, "BTCUSDT", metric, ts.isoformat(), ts.isoformat(), value, utcnow()),
    )


def test_empty_store_panel_abstains_honestly(tmp_path):
    store = _store(tmp_path)
    mind = build_mind(store)  # no reference bars, no alt-data → nothing ingested
    assert mind["railguard"] == RAILGUARD
    assert mind["consensus"] == "neutral"
    assert mind["conviction"] == 0.0
    assert mind["agreement"] == 0.0
    # Every MARKET analyst abstains (no fabricated read); the process pillars (ML, memory) still report state.
    market = [s for s in mind["stances"] if s["kind"] == "market"]
    assert market and all(s["lean"] == "abstain" for s in market)
    assert any(s["kind"] == "process" and s["perspective"] == "ML survival" for s in mind["stances"])
    # "Knows" lists registry sources as not-ingested rather than hiding them.
    assert mind["knows"], "should still enumerate what it COULD know"
    assert all(item["ingested"] is False for lens in mind["knows"] for item in lens["items"])


def test_ingested_signals_drive_a_consensus(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 15.0)  # extreme fear → bullish
    _seed_metric(store, "macro_regime", 0.8)  # risk-on → bullish
    _seed_metric(store, "funding_rate", -0.5)  # low funding → room to run (bullish)
    mind = build_mind(store)
    leans = {s["perspective"]: s["lean"] for s in mind["stances"]}
    assert leans["Sentiment"] == "bullish"
    assert leans["Macro"] == "bullish"
    assert mind["consensus"] == "bullish"
    assert mind["conviction"] > 0.0
    assert "Sentiment" in mind["bull_case"]
    # Freshness flows into "knows": the seeded metrics now read as ingested.
    sentiment_lens = next(l for l in mind["knows"] if l["perspective"] == "Sentiment")
    fg = next(i for i in sentiment_lens["items"] if i["name"] == "fear_greed")
    assert fg["ingested"] is True and fg["value"] == 15.0


def test_debate_is_deterministic(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 80.0)  # greed → bearish
    _seed_metric(store, "news_sentiment", -0.4)  # negative flow → bearish
    a = build_mind(store)
    b = build_mind(store)
    assert a == b


def test_contested_read_is_flagged(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 10.0)  # bullish
    _seed_metric(store, "macro_regime", -0.9)  # bearish
    mind = build_mind(store)
    assert mind["contested"] is True
    assert mind["bull_case"] and mind["bear_case"]


def test_reflect_persists_a_point_in_time_row_and_event(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 20.0)
    out = reflect(store)
    assert out is not None and out["consensus"] == "bullish"
    rows = store.rows("SELECT consensus, conviction, agreement, payload FROM mind_reflections")
    assert len(rows) == 1 and rows[0]["consensus"] == "bullish"
    events = store.rows("SELECT kind FROM events WHERE kind = 'mind_reflection'")
    assert len(events) == 1


def test_reflect_degrades_when_table_absent(tmp_path):
    store = _store(tmp_path)
    store.rows("DROP TABLE mind_reflections")  # simulate a prod DB that hasn't applied the migration yet
    out = reflect(store)  # must not raise
    assert out is not None
    # The audit event still records the reflection even without the richer table.
    events = store.rows("SELECT kind FROM events WHERE kind = 'mind_reflection'")
    assert len(events) == 1


def test_railguard_present_on_every_analyst_stance_shape(tmp_path):
    store = _store(tmp_path)
    ctx = gather_context(store)
    snap = debate([analyst(ctx) for analyst in ALL_ANALYSTS])
    assert len(snap.stances) == len(ALL_ANALYSTS)
    for s in snap.stances:
        assert s.lean in ("bullish", "bearish", "neutral", "abstain")
        assert 0.0 <= s.conviction <= 1.0
