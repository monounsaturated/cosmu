# The operator-facing INDEX subsystem (cosmu.indexes) layered ON the canonical scorers — NOT a second scoring
# path: specs validate per kind, the registry round-trips + upserts, text indexes DELEGATE to the cosmu.lab.indexes
# rubric scorer (reused, deterministic), social indexes DELEGATE to cosmu.mind.authority (deterministic,
# honest-empty), the monitor reports freshness + stability, index metrics route as strategy features, and the
# /indexes API serves real cards + an honest "not active" state. Offline, no keys, no network.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, PgAltDataStore
from cosmu.indexes.compute import (
    compute_social_point,
    compute_text_point,
    read_index_series,
    rubric_from_spec,
    store_index_points,
)
from cosmu.indexes.monitor import index_health
from cosmu.indexes.registry import active_indexes, get_index, indexes_available, list_indexes, register_index
from cosmu.indexes.routing import index_routes
from cosmu.indexes.spec import INDEX_PROVIDER, IndexSpec
from cosmu.knowledge.store import Store
from cosmu.lab.indexes import EvidenceSnippet, FixtureEvidenceProvider, _evidence_id
from cosmu.mind.claims import Claim


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/idxreg.sqlite3"))


def _chat(reply: str):
    def chat(model_id: str, prompt: str) -> str:
        return reply
    return chat


def _evidence_for(spec: IndexSpec, *texts: str) -> FixtureEvidenceProvider:
    snips = [EvidenceSnippet(id=_evidence_id(t), text=t, available_at=datetime(2026, 6, 1, tzinfo=UTC)) for t in texts]
    return FixtureEvidenceProvider({spec.metric: snips})


def _claim(handle: str, entity: str, direction: str, day: int) -> Claim:
    ts = datetime(2026, 6, day, tzinfo=UTC)
    return Claim(handle=handle, platform="x", post_id=f"{handle}-{day}", entity=entity,
                 direction=direction, horizon="1w", horizon_days=7, conviction=0.8, ts=ts)


# --------------------------------------------------------------------------- spec validation


def test_spec_metric_symbols_kindflags():
    s = IndexSpec(id="mideast-news", name="Middle East news", rationale="geopolitical risk proxy",
                  kind="event_topic", definition={"topic": "middle east conflict"})
    assert s.metric == "idx_mideast-news" and s.market_wide and s.symbols() == ["MARKET"] and s.is_text

    b = IndexSpec(id="btc-infl", name="BTC influencers", rationale="bucket", kind="social_bucket",
                  definition={"handles": ["@a", "@b"]}, entities=["BTC", "ETH"])
    assert not b.market_wide and b.symbols() == ["BTC", "ETH"] and b.is_social


@pytest.mark.parametrize("kind,definition", [
    ("single_account", {"handles": ["@a", "@b"]}),
    ("social_bucket", {"handles": []}),
    ("event_topic", {"topic": "  "}),
    ("prompt_rubric", {}),
])
def test_spec_rejects_bad_definition(kind, definition):
    with pytest.raises(ValueError):
        IndexSpec(id="idx1", name="n", rationale="r", kind=kind, definition=definition)


@pytest.mark.parametrize("bad_id", ["A", "x", "-bad", "bad-", "x" * 60])
def test_spec_rejects_bad_slug(bad_id):
    with pytest.raises(ValueError):
        IndexSpec(id=bad_id, name="n", rationale="r", kind="event_topic", definition={"topic": "t"})


def test_spec_forbids_extra_fields():
    with pytest.raises(ValueError):
        IndexSpec(id="ok", name="n", rationale="r", kind="event_topic", definition={"topic": "t"}, surprise="x")  # type: ignore[call-arg]


# --------------------------------------------------------------------------- registry round-trip


def test_registry_available_and_roundtrip(tmp_path):
    store = _store(tmp_path)
    assert indexes_available(store) is True and list_indexes(store) == []
    register_index(store, IndexSpec(id="risk-on", name="Risk on", rationale="macro appetite",
                                    kind="prompt_rubric", definition={"prompt": "score risk appetite"}, status="active"))
    got = get_index(store, "risk-on")
    assert got is not None and got.kind == "prompt_rubric" and got.created_at is not None
    assert [s.id for s in list_indexes(store)] == ["risk-on"]
    assert [s.id for s in active_indexes(store)] == ["risk-on"]


def test_registry_upsert_keeps_created_at(tmp_path):
    store = _store(tmp_path)
    s1 = register_index(store, IndexSpec(id="dup", name="V1", rationale="r", kind="event_topic", definition={"topic": "t"}))
    s2 = register_index(store, IndexSpec(id="dup", name="V2", rationale="r2", kind="event_topic", definition={"topic": "t2"}))
    assert len(list_indexes(store)) == 1 and get_index(store, "dup").name == "V2" and s2.created_at == s1.created_at


# --------------------------------------------------------------------------- text compute (delegates to lab.indexes)


def test_rubric_from_spec_shapes():
    topic = rubric_from_spec(IndexSpec(id="tt", name="t", rationale="r", kind="event_topic", definition={"topic": "oil"}))
    assert topic.lo == -1.0 and topic.hi == 1.0 and "oil" in topic.question
    rub = rubric_from_spec(IndexSpec(id="pp", name="p", rationale="r", kind="prompt_rubric",
                                     definition={"prompt": "Q?", "lo": 0.0, "hi": 1.0}))
    assert rub.lo == 0.0 and rub.hi == 1.0 and rub.question == "Q?"


def test_compute_text_point_deterministic_in_range():
    spec = IndexSpec(id="mideast", name="ME", rationale="r", kind="event_topic", definition={"topic": "middle east"})
    raw = '{"score": -0.6, "confidence": 0.7, "rationale": "war", "evidence_ids": []}'
    ev = _evidence_for(spec, "war escalates", "ceasefire collapses")
    out = compute_text_point(spec, chat=_chat(raw), evidence=ev, model_id="test")
    assert set(out) == {"MARKET"} and out["MARKET"].value == -0.6
    # The SCORE is deterministic (same headlines + rubric → same number = stable ranking); only the wall-clock
    # stamp moves between passes, so compare the value, not the whole point.
    assert compute_text_point(spec, chat=_chat(raw), evidence=ev, model_id="test")["MARKET"].value == -0.6


def test_compute_text_point_no_key_empty():
    spec = IndexSpec(id="tt", name="t", rationale="r", kind="event_topic", definition={"topic": "x"})
    assert compute_text_point(spec, chat=None) == {}


def test_compute_text_point_out_of_range_rejected_to_empty():
    spec = IndexSpec(id="rr", name="r", rationale="r", kind="prompt_rubric",
                     definition={"prompt": "0..1 score", "lo": 0.0, "hi": 1.0})
    raw = '{"score": 5.0, "confidence": 0.9, "rationale": "x", "evidence_ids": []}'  # out of [0,1]
    ev = _evidence_for(spec, "headline")
    assert compute_text_point(spec, chat=_chat(raw), evidence=ev, model_id="test") == {}


# --------------------------------------------------------------------------- social compute (delegates to authority)


def test_compute_social_point_per_entity_and_empty():
    spec = IndexSpec(id="ss", name="s", rationale="r", kind="social_bucket",
                     definition={"handles": ["@a"]}, entities=["BTC"])
    out = compute_social_point(spec, claims=[_claim("@a", "BTC", "up", 1)], bars_by_entity={},
                               now=datetime(2026, 6, 5, tzinfo=UTC))
    assert set(out) <= {"BTC"}
    for p in out.values():
        assert -1.0 <= p.value <= 1.0
    assert compute_social_point(spec, claims=[], bars_by_entity={}, now=datetime(2026, 6, 5, tzinfo=UTC)) == {}


def test_compute_social_point_market_wide_one_series():
    spec = IndexSpec(id="mm", name="m", rationale="r", kind="single_account", definition={"handles": ["@a"]})
    out = compute_social_point(spec, claims=[_claim("@a", "BTC", "up", 1), _claim("@a", "ETH", "down", 1)],
                               bars_by_entity={}, now=datetime(2026, 6, 2, tzinfo=UTC))
    assert set(out) <= {"MARKET"}


# --------------------------------------------------------------------------- storage + monitor


def test_store_and_health(tmp_path):
    store = _store(tmp_path)
    spec = register_index(store, IndexSpec(id="hh", name="h", rationale="r", kind="event_topic", definition={"topic": "t"}))
    now = datetime(2026, 6, 15, tzinfo=UTC)
    PgAltDataStore(store).append(INDEX_PROVIDER, "MARKET", spec.metric, [
        AltDataPoint(ts=now - timedelta(days=i), available_at=now - timedelta(days=i), value=0.5 + 0.01 * i)
        for i in range(5)
    ])
    h = index_health(store, spec, now=now)
    assert h.n_points == 5 and h.freshness == "fresh" and h.latest_value is not None
    assert h.reliability in ("stable", "moderate", "volatile") and h.transform_version == spec.transform_version
    # the per-pass dict storage API writes one point per symbol (a fresh PIT key, not a duplicate)
    later = now + timedelta(days=1)
    assert store_index_points(store, spec, {"MARKET": AltDataPoint(ts=later, available_at=later, value=0.9)}) == 1
    assert len(read_index_series(store, spec, "MARKET")) == 6


def test_health_honest_when_never_computed(tmp_path):
    store = _store(tmp_path)
    spec = register_index(store, IndexSpec(id="ee", name="e", rationale="r", kind="event_topic", definition={"topic": "t"}))
    h = index_health(store, spec)
    assert h.n_points == 0 and h.freshness == "never" and h.reliability == "untested" and h.latest_value is None


def test_index_routes_exposes_metric(tmp_path):
    store = _store(tmp_path)
    register_index(store, IndexSpec(id="feat", name="f", rationale="r", kind="event_topic", definition={"topic": "t"}))
    assert index_routes(store).get("idx_feat") == "index"


# --------------------------------------------------------------------------- API


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import cosmu.api.app as app_mod
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/idxapi.sqlite3", _env_file=None)  # hermetic: no .env.local → x-api-key gate stays off in tests
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", Store(settings))
    return TestClient(app_mod.app)


def test_api_define_list_get(client):
    body = {"id": "mideast", "name": "Middle East news", "rationale": "geopolitical risk",
            "kind": "event_topic", "definition": {"topic": "middle east conflict"}, "status": "active"}
    r = client.post("/indexes", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["index"]["metric"] == "idx_mideast"

    lst = client.get("/indexes").json()
    assert lst["available"] is True and [c["id"] for c in lst["indexes"]] == ["mideast"]
    assert lst["indexes"][0]["health"]["freshness"] == "never" and lst["indexes"][0]["n_strategies_using"] == 0

    detail = client.get("/indexes/mideast").json()
    assert detail["available"] is True and detail["index"]["name"] == "Middle East news"
    assert detail["series"] == [] and detail["strategies_using"] == []


def test_api_bad_definition_rejected(client):
    r = client.post("/indexes", json={"id": "bad", "name": "n", "rationale": "r",
                                       "kind": "single_account", "definition": {"handles": ["@a", "@b"]}})
    assert r.status_code == 422
