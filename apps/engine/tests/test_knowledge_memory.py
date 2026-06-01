# The self-improvement flywheel's long-term memory (graveyard/research RAG). It must be DETERMINISTIC, KEYLESS
# and OFFLINE (CI has no model key, no network), POINT-IN-TIME (recall never sees a note created at/after as_of),
# and it must surface a planted dead-end and a planted winner for a matching thesis. The scorer/Gate are never
# in this path — memory only informs the proposal.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.evolution.seeder import seed_meanrev_spec, seed_momentum_spec
from cosmu.knowledge.memory import EMBED_DIM, GraveyardMemory, cosine, embed
from cosmu.knowledge.store import Store


class _Ev:
    """A stand-in for evolution.loop.Evaluated (memory only reads these attributes)."""

    def __init__(self, vid, name, origin, passed, reasons, ds=0.5, oos=3.0):  # noqa: ANN001
        self.version_id = vid
        self.name = name
        self.origin = origin
        self.passed = passed
        self.reasons = reasons
        self.deflated_sharpe = ds
        self.oos_return_pct = oos


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/mem.sqlite3", openrouter_api_key=None))


def test_embedding_is_deterministic_keyless_and_unit_norm():
    # No key, no network — same string → same vector, every process.
    a = embed("fade oversold rsi crypto swing")
    b = embed("fade oversold rsi crypto swing")
    assert a == b
    assert len(a) == EMBED_DIM
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9  # L2-normalized
    assert round(cosine(a, b), 6) == 1.0
    # different text → different vector
    assert embed("trend momentum adx") != a


def test_recall_surfaces_planted_dead_end_and_winner(tmp_path):
    store = _store(tmp_path)
    mem = GraveyardMemory(store)

    dead = seed_meanrev_spec()
    dead.name = "Oversold RSI fade"
    win = seed_momentum_spec()
    win.name = "Trend momentum ADX"

    mem.remember(dead, _Ev("v-dead", dead.name, "seed", passed=False, reasons=["deflated_sharpe", "pbo"]))
    mem.remember(win, _Ev("v-win", win.name, "seed", passed=True, reasons=[]))

    # A thesis that matches the DEAD structure surfaces it as the top dead-end, with its kill reasons + structure.
    recall = mem.recall("mean reversion oversold rsi fade on crypto swing", k=5)
    assert recall.dead_ends, "expected a recalled dead end"
    assert recall.dead_ends[0].ref == "v-dead"
    assert recall.dead_ends[0].kind == "dead_end"
    assert "pbo" in recall.dead_ends[0].reasons
    assert "rsi" in recall.dead_ends[0].structure.get("entry_features", [])

    # A thesis that matches the WINNER surfaces it as the top winner pattern.
    recall2 = mem.recall("trend momentum adx confirmation", k=5)
    assert recall2.winners, "expected a recalled winner"
    assert recall2.winners[0].ref == "v-win"
    assert recall2.winners[0].kind == "winner_pattern"


def test_recall_is_point_in_time_no_look_ahead(tmp_path):
    store = _store(tmp_path)
    mem = GraveyardMemory(store)
    spec = seed_meanrev_spec()
    spec.name = "RSI fade"
    stamp = datetime(2024, 6, 1, tzinfo=UTC)
    mem.remember(spec, _Ev("v1", spec.name, "seed", passed=False, reasons=["pbo"]), created_at=stamp.isoformat())

    before = (stamp - timedelta(days=1)).isoformat()
    after = (stamp + timedelta(days=1)).isoformat()
    # as_of strictly BEFORE the note → invisible (no look-ahead). as_of after → visible.
    assert mem.recall("rsi fade", k=5, as_of=before).dead_ends == []
    assert mem.recall("rsi fade", k=5, as_of=after).dead_ends


def test_remember_is_idempotent_per_version_and_kind(tmp_path):
    store = _store(tmp_path)
    mem = GraveyardMemory(store)
    spec = seed_meanrev_spec()
    ev = _Ev("v1", "RSI fade", "seed", passed=False, reasons=["pbo"])
    mem.remember(spec, ev)
    mem.remember(spec, ev)  # same (version_id, kind) → updates in place, no duplicate
    rows = store.rows("SELECT id FROM research_notes WHERE strategy_version_id = 'v1' AND kind = 'dead_end'")
    assert len(rows) == 1


def test_recall_runs_with_no_key_set(tmp_path):
    # The whole path must work with openrouter_api_key=None (CI). Already the case above; assert explicitly.
    store = _store(tmp_path)
    assert store.settings.openrouter_api_key is None
    mem = GraveyardMemory(store)
    mem.remember(seed_momentum_spec(), _Ev("v-w", "Trend", "seed", passed=True, reasons=[]))
    recall = mem.recall(seed_momentum_spec(), k=3)  # recall by SPEC, not just text
    assert recall.winners and recall.winners[0].ref == "v-w"
