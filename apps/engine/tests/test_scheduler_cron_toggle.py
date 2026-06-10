# intent: verify the AUTONOMY_CRON_ENABLED guard in scheduler._main():
#   - "0" / "false" / "no" → exits 0 without calling run_tick (the Railway cron fires but does nothing)
#   - absent / "1"         → the tick RUNS (default ON — the autonomous loop is the product; the tick is
#                            sim-only by invariant and the ledger pause flag still stops it)
# These tests touch NO money path and keep live OFF — they exercise the guard only.

import importlib


def _main_with_env(monkeypatch, value, extra_argv=None):
    """Run scheduler._main() with AUTONOMY_CRON_ENABLED set to `value` (or absent if None)."""
    from cosmu.master import scheduler

    importlib.reload(scheduler)  # fresh module state
    if value is None:
        monkeypatch.delenv("AUTONOMY_CRON_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AUTONOMY_CRON_ENABLED", value)
    return scheduler._main(extra_argv or [])


def test_cron_guard_absent_runs_offline(monkeypatch):
    """AUTONOMY_CRON_ENABLED absent → DEFAULT ON: the tick runs (offline mode here, so temp sqlite, no
    network/keys). Flipped 2026-06 (audit): default-OFF meant nothing ran unattended except ingest+marking."""
    code = _main_with_env(monkeypatch, None, extra_argv=["--offline", "--n", "1"])
    assert code == 0


def test_cron_guard_zero_exits_zero(monkeypatch, capsys):
    """AUTONOMY_CRON_ENABLED=0 → exits 0 immediately (no tick runs)."""
    code = _main_with_env(monkeypatch, "0")
    assert code == 0
    assert "skipped" in capsys.readouterr().out


def test_cron_guard_false_exits_zero(monkeypatch, capsys):
    """AUTONOMY_CRON_ENABLED=false → exits 0 immediately (no tick runs)."""
    code = _main_with_env(monkeypatch, "false")
    assert code == 0
    assert "skipped" in capsys.readouterr().out


def test_cron_guard_enabled_runs_offline(monkeypatch):
    """AUTONOMY_CRON_ENABLED=1 --offline → tick runs on a temp sqlite (no network/keys) and exits 0."""
    code = _main_with_env(monkeypatch, "1", extra_argv=["--offline", "--n", "1"])
    assert code == 0
