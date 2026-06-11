# GET /mind/credibility — the SOURCE SCOREBOARD (realtime-data-lane epic P2): voice_scoreboard served
# flat and typed, ordered skill DESC with NULLs (untested) LAST, every nullable metric passed through as
# null (untested ≠ unskilled — never coerced to 0), and an honest empty-panel shape (rows=[], as_of=null,
# panel_size=0). AUTH is the app-level shared-secret middleware — no per-route check. Offline +
# deterministic: temp sqlite Store via TestClient, no network, no lifespan (mirrors test_strategy_summary).

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store

_COLUMNS = (
    "handle", "platform", "n_posts", "n_claims", "n_resolved", "hit_rate", "base_hit_rate",
    "excess_hit_rate", "brier_skill_score", "calibration_error", "skill", "authority",
    "primacy_rate", "updated_at",
)


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: ignore a dev box's .env.local (API_SECRET_KEY there would 401 the
    # no-secret tests), exactly as tests/test_strategy_summary.py does.
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/credibility.sqlite3", openrouter_api_key=None, _env_file=None))


def _seed(store: Store, **row) -> None:
    """One voice_scoreboard row. Defaults are the honest UNTESTED state: counts 0, every metric NULL."""
    record = {
        "handle": "@voice", "platform": "x", "n_posts": 0, "n_claims": 0, "n_resolved": 0,
        "hit_rate": None, "base_hit_rate": None, "excess_hit_rate": None, "brier_skill_score": None,
        "calibration_error": None, "skill": None, "authority": None, "primacy_rate": None,
        "updated_at": "2026-06-01T00:00:00+00:00",
    }
    record.update(row)
    with store.batch() as writer:
        writer.execute(
            f"INSERT INTO voice_scoreboard ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
            tuple(record[c] for c in _COLUMNS),
        )


def _client(store: Store, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=store.settings.database_url, openrouter_api_key=None, api_secret_key=secret, _env_file=None)
    # Writes to app_mod.settings/store fan out to _shared + every router (the back-compat seam).
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


def _seed_panel(store: Store) -> None:
    _seed(
        store, handle="@sharp", platform="x", n_posts=40, n_claims=12, n_resolved=8,
        hit_rate=0.62, base_hit_rate=0.51, excess_hit_rate=0.11, brier_skill_score=0.09,
        calibration_error=0.14, skill=0.71, authority=0.42, primacy_rate=0.5,
        updated_at="2026-06-10T12:00:00+00:00",
    )
    _seed(
        store, handle="r/echo", platform="reddit", n_posts=90, n_claims=30, n_resolved=20,
        hit_rate=0.45, base_hit_rate=0.51, excess_hit_rate=-0.06, brier_skill_score=-0.04,
        calibration_error=0.3, skill=0.22, authority=0.18, primacy_rate=0.05,
        updated_at="2026-06-09T12:00:00+00:00",
    )
    # The UNTESTED voice: posts on record but zero resolved claims → every metric NULL, never 0.
    _seed(store, handle="@quiet", platform="x", n_posts=15, n_claims=1, updated_at="2026-06-08T12:00:00+00:00")


def test_credibility_ordering_skill_desc_nulls_last(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_panel(store)
    body = _client(store, monkeypatch).get("/mind/credibility").json()
    assert [r["handle"] for r in body["rows"]] == ["@sharp", "r/echo", "@quiet"]
    assert body["panel_size"] == 3
    assert body["as_of"] == "2026-06-10T12:00:00+00:00"  # max updated_at across the panel


def test_credibility_nullable_metrics_pass_through_as_null(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_panel(store)
    rows = {r["handle"]: r for r in _client(store, monkeypatch).get("/mind/credibility").json()["rows"]}

    # The untested voice: counts are real, every metric is honestly null — NEVER 0.
    quiet = rows["@quiet"]
    assert (quiet["n_posts"], quiet["n_claims"], quiet["n_resolved"]) == (15, 1, 0)
    for metric in ("hit_rate", "base_hit_rate", "excess_hit_rate", "brier_skill_score",
                   "calibration_error", "skill", "authority", "primacy_rate"):
        assert quiet[metric] is None, f"{metric} must stay null for an untested voice"

    # The tested voice: real values round-trip exactly (incl. the negative Brier skill on r/echo).
    sharp = rows["@sharp"]
    assert sharp["platform"] == "x" and sharp["hit_rate"] == 0.62 and sharp["base_hit_rate"] == 0.51
    assert sharp["skill"] == 0.71 and sharp["updated_at"] == "2026-06-10T12:00:00+00:00"
    assert rows["r/echo"]["brier_skill_score"] == -0.04 and rows["r/echo"]["excess_hit_rate"] == -0.06


def test_credibility_empty_panel_honest_shape(tmp_path, monkeypatch):
    body = _client(_store(tmp_path), monkeypatch).get("/mind/credibility").json()
    assert body == {"as_of": None, "panel_size": 0, "rows": []}


def test_credibility_ties_break_on_handle_and_all_null_skill_orders_by_handle(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed(store, handle="@b-untested", updated_at="2026-06-01T00:00:00+00:00")
    _seed(store, handle="@a-untested", updated_at="2026-06-02T00:00:00+00:00")
    body = _client(store, monkeypatch).get("/mind/credibility").json()
    assert [r["handle"] for r in body["rows"]] == ["@a-untested", "@b-untested"]
    assert body["as_of"] == "2026-06-02T00:00:00+00:00"


def test_credibility_behind_shared_secret_when_set(tmp_path, monkeypatch):
    # No per-route auth: the app-level middleware alone gates this GET, same as every /mind route.
    store = _store(tmp_path)
    _seed_panel(store)
    c = _client(store, monkeypatch, secret="s3cret")
    assert c.get("/mind/credibility").status_code == 401
    ok = c.get("/mind/credibility", headers={"x-api-key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["panel_size"] == 3
