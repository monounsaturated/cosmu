# Test: cosmu.lab.batch — one-command generate→backtest→gate pipeline.
#
# Acceptance criteria (per TASK C):
#   1. run_batch authors N distinct valid specs (>~40 of 50 clear novelty gate / are structurally distinct).
#   2. Specs are written to a tmp inbox dir.
#   3. --gate routes through scan_inbox(run_cohort=True), NOT a custom scorer.
#   4. No spec bypasses the FDR trial ledger.
#   5. CLI entrypoint: `python3 -m cosmu.lab.batch --n 50 --theme "funding dispersion" --gate` wires up.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.lab.batch import BatchResult, run_batch
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec


def _store(tmp_path: Path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/batch.sqlite3", openrouter_api_key=None))


class _FixtureBars:
    """Minimal offline market provider for the --gate path (same pattern as test_lab_strategize)."""

    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


# ── core: author N distinct valid specs ───────────────────────────────────────────────────────────────────

def test_batch_authors_valid_specs(tmp_path):
    """run_batch with n=50 must author >~40 compiler-clean specs and write them to the inbox."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("funding dispersion", 50, inbox_dir=inbox, store=store)

    assert isinstance(result, BatchResult)
    assert result.theme == "funding dispersion"
    assert result.requested == 50
    # At least 40 of 50 should clear novelty gate and produce valid, compiler-clean specs.
    assert result.authored >= 40, (
        f"Expected >=40 valid specs, got {result.authored} "
        f"(invalid={result.invalid}, compiler_fail={result.compiler_fail}; "
        f"issues={result.issues[:5]})"
    )


def test_batch_writes_to_inbox(tmp_path):
    """Every authored spec must be a file in the inbox dir."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("momentum", 10, inbox_dir=inbox, store=store)

    # All reported paths must actually exist.
    assert len(result.paths) == result.authored
    for p in result.paths:
        assert Path(p).exists(), f"authored path missing: {p}"
        assert Path(p).parent == inbox


def test_batch_specs_are_valid_and_magic_number_free(tmp_path):
    """Every spec written to the inbox must pass validate_spec (no magic numbers, no unknown features)."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("volatility regime", 12, inbox_dir=inbox, store=store)

    assert result.authored >= 1, f"expected >=1 valid specs, got 0; issues={result.issues}"
    for p in result.paths:
        raw = Path(p).read_text()
        spec = StrategySpec.model_validate(json.loads(raw))
        issues = validate_spec(spec)
        assert issues == [], f"spec at {p} has issues: {issues}"


def test_batch_structural_diversity(tmp_path):
    """50 specs on a theme must produce at least 5 distinct feature-set fingerprints (Jaccard divergence)
    so they don't collapse to near-duplicates that the novelty gate would reject en-masse."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("funding dispersion", 50, inbox_dir=inbox, store=store)

    # Collect entry-feature frozensets for authored specs.
    feature_sets: list[frozenset[str]] = []
    for p in result.paths:
        raw = Path(p).read_text()
        spec = StrategySpec.model_validate(json.loads(raw))
        fs = frozenset(c.feature.name for c in spec.entry)
        feature_sets.append(fs)

    unique_sets = {frozenset(fs) for fs in feature_sets}
    assert len(unique_sets) >= 5, (
        f"Expected >=5 distinct feature-set fingerprints across {len(feature_sets)} authored specs, "
        f"got {len(unique_sets)}: {[sorted(s) for s in unique_sets]}"
    )


def test_batch_clamps_to_max(tmp_path):
    """Requesting more than _MAX_BATCH (64) is silently clamped."""
    from cosmu.lab.strategize import _MAX_BATCH

    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("vol", 999, inbox_dir=inbox, store=store)
    assert result.requested == _MAX_BATCH


def test_batch_no_gate_by_default(tmp_path):
    """Without --gate the cohort fields stay None (no auto-scoring outside the FDR ledger)."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"

    result = run_batch("funding", 5, inbox_dir=inbox, store=store)

    assert result.cohort_generated is None
    assert result.cohort_passed is None
    assert result.cohort_killed is None


def test_batch_gate_routes_through_scan_inbox(tmp_path):
    """--gate must call scan_inbox(run_cohort=True), returning a cohort summary from the deterministic gate.
    We don't assert pass/fail (the strict Gate kills most things) — only that the ledger ran."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    market = _FixtureBars()

    # Patch scan_inbox to intercept the call and verify run_cohort=True is passed.
    import cosmu.lab.batch as batch_mod
    import cosmu.lab.inbox as inbox_mod
    from cosmu.lab.inbox import InboxReport, scan_inbox

    calls: list[dict] = []
    original_scan = scan_inbox

    def _spy_scan(store_arg, *, inbox_dir=None, run_cohort=False, market_data=None):
        calls.append({"inbox_dir": str(inbox_dir), "run_cohort": run_cohort})
        # Delegate to the real scan_inbox with the fixture market so FarmLoop can run.
        return original_scan(store_arg, inbox_dir=inbox_dir, run_cohort=run_cohort, market_data=market)

    import unittest.mock as mock

    with mock.patch.object(inbox_mod, "scan_inbox", side_effect=_spy_scan):
        # Re-import so batch.py picks up the patched version from the module.
        import importlib
        import cosmu.lab.batch as _batch
        importlib.reload(_batch)
        result = _batch.run_batch("funding", 5, inbox_dir=inbox, store=store, gate=True)

    # scan_inbox must have been called with run_cohort=True.
    assert any(c["run_cohort"] for c in calls), f"scan_inbox was not called with run_cohort=True; calls={calls}"
    # Cohort summary must be populated.
    assert result.cohort_generated is not None


def test_batch_gate_populates_cohort_summary(tmp_path):
    """--gate populates cohort_generated/passed/killed/kill_rate from the deterministic screen."""
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    market = _FixtureBars()

    # Author a batch first, then gate with the fixture market data.
    import cosmu.lab.batch as batch_mod

    # We need to inject market_data into scan_inbox — run_batch accepts no market_data arg by design
    # (the gate path calls scan_inbox which uses cached bars in the real system).
    # For this test, patch scan_inbox to forward the fixture market.
    import cosmu.lab.inbox as inbox_mod
    original_scan = inbox_mod.scan_inbox

    def _with_fixture(store_arg, *, inbox_dir=None, run_cohort=False, market_data=None):
        return original_scan(store_arg, inbox_dir=inbox_dir, run_cohort=run_cohort, market_data=market)

    import unittest.mock as mock
    import importlib

    with mock.patch.object(inbox_mod, "scan_inbox", side_effect=_with_fixture):
        importlib.reload(batch_mod)
        result = batch_mod.run_batch("volatility", 6, inbox_dir=inbox, store=store, gate=True)

    # The gate ran — cohort fields are ints, not None.
    assert isinstance(result.cohort_generated, int)
    assert isinstance(result.cohort_passed, int)
    assert isinstance(result.cohort_killed, int)
    assert isinstance(result.cohort_kill_rate, float)


# ── CLI entrypoint smoke test ──────────────────────────────────────────────────────────────────────────────

def test_batch_cli_entrypoint_runs(tmp_path):
    """The __main__ entrypoint must parse args and exit 0 when at least one spec is authored."""
    import subprocess
    import os

    # PYTHONPATH must point at apps/engine (the package root containing cosmu/).
    engine_root = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    # Prepend apps/engine to any existing PYTHONPATH so cosmu is importable.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{engine_root}:{existing}" if existing else engine_root

    proc = subprocess.run(
        [
            "python3", "-m", "cosmu.lab.batch",
            "--n", "8",
            "--theme", "funding dispersion",
            "--inbox", str(tmp_path / "inbox"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"CLI exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "authored" in proc.stdout.lower() or "BATCH" in proc.stdout
