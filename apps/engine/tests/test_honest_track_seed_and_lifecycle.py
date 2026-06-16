# Regression locks for the 2026-06-15 lifecycle/track-seed fix:
#   1. open_paper_track (master/tracks.py) is the ONE create path and seeds a track HONESTLY — equity =
#      starting_capital, return_pct = 0. The backtest OOS must NEVER be copied into the FORWARD columns (that
#      leak let an unmarked survivor display its OOS as forward P&L and read live_ready off a backtest number).
#   2. The status vocabulary (knowledge/lifecycle_status.py) is the single source of truth; the phantom 'forward'
#      is gone and the canonical write-set is exactly {screened, paper, live, killed}.
#   3. The spine demo lane KILLS a gate-failed version (terminal) instead of stranding it at the old non-canonical
#      'validating' — the orphan that sat 13 days. No code path ever writes 'validating'.
#
# Offline-safe: in-memory SQLite Store; the conftest network guard fails any accidental socket.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge import lifecycle_status as ls
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.scorer import ScoreVerdict
from cosmu.master.tracks import open_paper_track
from cosmu.spine.engine import EngineFacade


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/honest_seed.sqlite3", openrouter_api_key=None))


def test_open_paper_track_seeds_zero_forward_pnl(tmp_path):
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "t", "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sid, "spec": {}, "generated_code": "{}", "code_hash": "h", "params": {},
         "origin": "test", "status": ls.SCREENED, "created_at": utcnow()},
    )
    open_paper_track(store, version_id=vid, starting_capital=Decimal("4242"))
    row = store.row("SELECT starting_capital, equity, return_pct FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert row is not None
    # Born honest: equity == starting_capital, return_pct == 0 — never a backtest/OOS number.
    assert Decimal(str(row["starting_capital"])) == Decimal("4242")
    assert Decimal(str(row["equity"])) == Decimal("4242.00")
    assert Decimal(str(row["return_pct"])) == Decimal("0.00")


def test_no_seed_path_writes_a_positive_return_pct_at_birth(tmp_path):
    # The whole engine (every create lane now routes through open_paper_track) must never INSERT a non-zero
    # return_pct at birth. We scan the package for a literal positive seed of the exact leaked shape.
    import pathlib
    import re

    pkg = pathlib.Path(__file__).resolve().parents[1] / "cosmu"
    # `equity = <cap> * (Decimal("1") + <oos/holdout>...)` — the leak's signature.
    leak = re.compile(r"""\*\s*\(\s*Decimal\(["']1["']\)\s*\+\s*Decimal\(str\(round\(v\[""")
    offenders = [
        f"{p.relative_to(pkg)}:{i}"
        for p in pkg.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if leak.search(line)
    ]
    assert not offenders, "a create lane still seeds tracks.equity from the backtest OOS:\n" + "\n".join(offenders)


def test_lifecycle_vocabulary_is_canonical_and_phantom_free():
    assert ls.CANONICAL == frozenset({"screened", "paper", "live", "killed"})
    # 'forward' was a phantom (never written) — it must not appear in ANY derived set.
    for s in (ls.PAPER_ALIASES, ls.FORWARD_STATUSES, ls.FUNDED_STATUSES, ls.ALIVE_STATUSES):
        assert "forward" not in s
    # legacy 'forward_test' is reader-tolerated only
    assert ls.is_paper("paper") and ls.is_paper("forward_test")
    assert not ls.is_paper("screened") and not ls.is_paper(None)
    # FUNDED = paper(+alias) + live; ALIVE adds screened; neither includes killed
    assert "live" in ls.FUNDED_STATUSES and "killed" not in ls.FUNDED_STATUSES
    assert "screened" in ls.ALIVE_STATUSES and "killed" not in ls.ALIVE_STATUSES
    # sql_in_list renders a deterministic, sorted, quoted IN list
    assert ls.sql_in_list(ls.PAPER_ALIASES) == "('forward_test', 'paper')"


def test_spine_kills_gate_failed_version_instead_of_validating(tmp_path, monkeypatch):
    # A gate-FAILED spine demo run must leave its version TERMINAL ('killed' with a reason), never stranded at the
    # old non-canonical 'validating' (the orphan that sat 13 days). Force a FAIL verdict deterministically.
    settings = Settings(database_url=f"sqlite:///{tmp_path}/spine_fail.sqlite3", environment="test")
    settings.live.enabled = True

    def _fail(metrics, gates, *args, **kwargs):  # noqa: ANN001, ANN202 — matches score()'s shape
        return ScoreVerdict(
            ranking_scalar=Decimal("0.10"), deflated_sharpe_prob=Decimal("0.10"), passed=False,
            reasons=["deflated_sharpe"],
        )

    monkeypatch.setattr("cosmu.spine.engine.score", _fail)
    facade = EngineFacade.create(settings)
    result = facade.run_backtest(seed=7)
    assert result["passed"] is False

    rows = facade.store.rows("SELECT status, kill_reason FROM strategy_versions")
    assert rows, "spine run must create the sample version"
    assert all(r["status"] == "killed" for r in rows), [r["status"] for r in rows]
    assert all(r["kill_reason"] for r in rows)
    # The orphan value is gone entirely.
    assert facade.store.row("SELECT 1 FROM strategy_versions WHERE status = 'validating'") is None
