# intent: verify the AUTONOMY_CRON_ENABLED guard in scheduler._main():
#   - absent / "0" → exits 0 without calling run_tick (the Railway cron fires but does nothing)
#   - "1"          → calls run_tick (offline mode so no network/DB needed)
# These tests touch NO money path and keep live OFF — they exercise the guard only.

import importlib
import os

import pytest


def _main_with_env(monkeypatch, value, extra_argv=None):
    """Run scheduler._main() with AUTONOMY_CRON_ENABLED set to `value` (or absent if None)."""
    from cosmu.master import scheduler

    importlib.reload(scheduler)  # fresh module state
    if value is None:
        monkeypatch.delenv("AUTONOMY_CRON_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AUTONOMY_CRON_ENABLED", value)
    return scheduler._main(extra_argv or [])


def test_cron_guard_absent_exits_zero(monkeypatch):
    """AUTONOMY_CRON_ENABLED absent → exits 0 immediately (no tick runs)."""
    code = _main_with_env(monkeypatch, None)
    assert code == 0


def test_cron_guard_zero_exits_zero(monkeypatch):
    """AUTONOMY_CRON_ENABLED=0 → exits 0 immediately (no tick runs)."""
    code = _main_with_env(monkeypatch, "0")
    assert code == 0


def test_cron_guard_false_exits_zero(monkeypatch):
    """AUTONOMY_CRON_ENABLED=false → exits 0 immediately (no tick runs)."""
    code = _main_with_env(monkeypatch, "false")
    assert code == 0


def test_cron_guard_enabled_runs_offline(monkeypatch):
    """AUTONOMY_CRON_ENABLED=1 --offline → tick runs on a temp sqlite (no network/keys) and exits 0."""
    code = _main_with_env(monkeypatch, "1", extra_argv=["--offline", "--n", "1"])
    assert code == 0
