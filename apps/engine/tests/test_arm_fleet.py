# Smoke tests for cosmu.research.arm_fleet — the fleet arming entrypoint.
#
# These tests NEVER touch the real store or Yahoo (offline-safe) and NEVER call the
# real arm() implementations (which require market data and a live DB).  The goal is:
#
#   1. All 10 fleet modules import cleanly and expose arm(store=None) -> dict.
#   2. --dry-run path works end-to-end without any DB writes.
#   3. arm_all() correctly tallies armed / skipped / failed from mocked arm() results.
#   4. --only filtering and the CLI main() exit codes are correct.
#
# Run with:  PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests/test_arm_fleet.py -q

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from cosmu.research.arm_fleet import (
    _FLEET,
    _ARMED,
    _FAILED,
    _SKIPPED,
    arm_all,
    main,
)


# ---------------------------------------------------------------------------
# 1. All fleet modules are importable and expose arm()
# ---------------------------------------------------------------------------

def test_all_fleet_modules_importable():
    """Every entry in _FLEET resolves to a module with an arm() callable."""
    import importlib
    for entry in _FLEET:
        mod = importlib.import_module(entry.module)
        assert callable(getattr(mod, "arm", None)), (
            f"{entry.module} does not expose arm()"
        )


# ---------------------------------------------------------------------------
# 2. --dry-run: no DB writes, correct return shape
# ---------------------------------------------------------------------------

def test_dry_run_returns_would_arm_list():
    result = arm_all(dry_run=True)
    assert result["dry_run"] is True
    assert set(result["would_arm"]) == {e.alias for e in _FLEET}


def test_dry_run_subset_via_only():
    subset = ["faber_gtaa", "vaa"]
    result = arm_all(dry_run=True, only=subset)
    assert result["dry_run"] is True
    assert result["would_arm"] == subset


# ---------------------------------------------------------------------------
# 3. arm_all() tallies correctly from mocked arm() outcomes
# ---------------------------------------------------------------------------

def _mock_arm(outcome: dict):
    """Return a callable that ignores `store` and returns `outcome`."""
    def _arm(store=None):
        return outcome
    return _arm


def _patch_fleet_arm_fns(entries, outcomes: list[dict]):
    """Temporarily replace each entry's arm_fn with a mock returning outcomes[i]."""
    originals = [e.arm_fn for e in entries]
    for entry, outcome in zip(entries, outcomes):
        entry.arm_fn = _mock_arm(outcome)
    yield
    for entry, orig in zip(entries, originals):
        entry.arm_fn = orig


@pytest.fixture()
def mocked_fleet():
    """Inject mock arm_fn on every fleet entry before arm_all() loads them, and
    restore the originals (or None) after the test.  Because _load_fleet skips
    entries whose arm_fn is already set, the mocks survive the import step."""
    originals = {e.alias: e.arm_fn for e in _FLEET}
    # Pre-populate with a default "armed" mock so tests only need to override specifics
    for entry in _FLEET:
        entry.arm_fn = _mock_arm({"armed": True, "version_id": f"v-{entry.alias}"})
    yield _FLEET
    for entry in _FLEET:
        entry.arm_fn = originals[entry.alias]


def test_all_armed(mocked_fleet):
    result = arm_all(only=[e.alias for e in mocked_fleet])
    assert result["armed"] == len(mocked_fleet)
    assert result["skipped"] == 0
    assert result["failed"] == 0


def test_all_skipped(mocked_fleet):
    # armed=True + reused=True  ->  SKIPPED
    for entry in mocked_fleet:
        entry.arm_fn = _mock_arm({"armed": True, "reused": True, "version_id": f"v-{entry.alias}"})

    result = arm_all(only=[e.alias for e in mocked_fleet])
    assert result["skipped"] == len(mocked_fleet)
    assert result["armed"] == 0
    assert result["failed"] == 0


def test_one_failed_rest_armed(mocked_fleet):
    mocked_fleet[0].arm_fn = _mock_arm({"armed": False, "reason": "not deployable"})

    result = arm_all(only=[e.alias for e in mocked_fleet])
    assert result["failed"] == 1
    assert result["armed"] == len(mocked_fleet) - 1


def test_exception_in_arm_counts_as_failed(mocked_fleet):
    # If arm() raises, arm_all should catch it and count it as FAILED, not crash.
    def _raises(store=None):
        raise RuntimeError("simulated DB error")

    mocked_fleet[0].arm_fn = _raises
    result = arm_all(only=[mocked_fleet[0].alias])
    assert result["failed"] == 1
    assert result["strategies"][mocked_fleet[0].alias]["status"] == _FAILED


def test_strategies_dict_has_all_aliases(mocked_fleet):
    result = arm_all(only=[e.alias for e in mocked_fleet])
    assert set(result["strategies"].keys()) == {e.alias for e in mocked_fleet}


# ---------------------------------------------------------------------------
# 4. CLI: main() exit codes + --only validation
# ---------------------------------------------------------------------------

def test_main_dry_run_exits_zero():
    rc = main(["--dry-run"])
    assert rc == 0


def test_main_unknown_alias_exits_2(capsys):
    rc = main(["--only", "no_such_strategy"])
    assert rc == 2


def test_main_dry_run_with_only_exits_zero():
    rc = main(["--dry-run", "--only", "faber_gtaa,vaa"])
    assert rc == 0
