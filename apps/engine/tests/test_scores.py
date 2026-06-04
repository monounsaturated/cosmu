# The scores cockpit (cosmu/mind/scores.build_scores + GET /scores). It must be DETERMINISTIC and OFFLINE
# (CI has no key, no network), HONEST (a category/source with no ingested data is connected=False with a
# null index — never a fabricated score), and KEY-GATED (a source whose key is absent shows disabled=True so
# the UI greys it out). Reviews are plain-language strings; this path never touches a money table.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind.scores import CATEGORY_ORDER, build_scores


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/scores.sqlite3", openrouter_api_key=None))


def _seed(store: Store, metric: str, value: float, *, provider: str = "test", hours_ago: float = 1.0) -> None:
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    store.rows(
        "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider, "BTCUSDT", metric, ts.isoformat(), ts.isoformat(), value, utcnow()),
    )


def test_empty_store_is_honest_offline(tmp_path):
    snap = build_scores(_store(tmp_path), present_keys=set())
    # Every requested category is present, in canonical order.
    assert [c.key for c in snap.categories] == list(CATEGORY_ORDER)
    # Nothing ingested → no fabricated numbers anywhere.
    assert snap.composite_index is None
    assert snap.composite_status == "offline"
    for c in snap.categories:
        assert c.index_score is None
        assert c.connected is False
        assert c.live_sources == 0


def test_ingested_source_lifts_its_category_index(tmp_path):
    store = _store(tmp_path)
    _seed(store, "fear_greed", 20.0)  # alternative.me → crypto category, fresh
    snap = build_scores(store, present_keys=set())
    crypto = next(c for c in snap.categories if c.key == "crypto")
    assert crypto.connected is True
    assert crypto.index_score is not None and crypto.index_score > 0.0
    assert crypto.live_sources >= 1
    assert snap.composite_index is not None and snap.composite_index > 0.0
    assert "composite" in snap.composite_review.lower()


def test_key_gated_source_is_disabled_without_key(tmp_path):
    store = _store(tmp_path)
    snap = build_scores(store, present_keys=set())
    social = next(c for c in snap.categories if c.key == "social")
    xai = next(s for s in social.sources if s.source == "xai")
    assert xai.key_required is True
    assert xai.key_name == "XAI_API_KEY"
    assert xai.key_present is False
    assert xai.disabled is True
    assert "XAI_API_KEY" in xai.review


def test_key_present_clears_the_gate(tmp_path):
    store = _store(tmp_path)
    snap = build_scores(store, present_keys={"XAI_API_KEY"})
    social = next(c for c in snap.categories if c.key == "social")
    xai = next(s for s in social.sources if s.source == "xai")
    assert xai.key_present is True
    assert xai.disabled is False


def test_metals_forex_is_declared_but_offline(tmp_path):
    # No metals/forex feed is wired yet — the category renders honestly offline, never faked.
    snap = build_scores(_store(tmp_path), present_keys=set())
    mf = next(c for c in snap.categories if c.key == "metals_forex")
    assert mf.total_sources == 0
    assert mf.index_score is None
    assert mf.connected is False


def test_deterministic(tmp_path):
    # Same store → same scores. (as_of is a wall-clock stamp, so compare the scored structure, not it.)
    store = _store(tmp_path)
    _seed(store, "fear_greed", 55.0)
    a = build_scores(store, present_keys=set())
    b = build_scores(store, present_keys=set())

    def shape(snap):
        return (snap.composite_index, [(c.key, c.index_score, c.connected, c.live_sources) for c in snap.categories])

    assert shape(a) == shape(b)


def test_scores_endpoint_contract(tmp_path, monkeypatch):
    # The deployed endpoint returns the snake_case contract shape and stays honest on an empty store.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.sqlite3")
    from cosmu.api import app as app_module

    client = TestClient(app_module.app)
    res = client.get("/scores")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"as_of", "composite_index", "composite_status", "composite_review", "categories"}
    keys = [c["key"] for c in body["categories"]]
    assert keys == list(CATEGORY_ORDER)
    for c in body["categories"]:
        for s in c["sources"]:
            assert {"connected", "key_required", "key_present", "disabled", "review"} <= set(s)
