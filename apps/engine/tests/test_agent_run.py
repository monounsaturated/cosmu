# Guard test for the LLM observe-run tick entry point (P0.4f). Proves the AUTONOMY_CRON_ENABLED gate: when off,
# main() returns 0 WITHOUT touching the DB or the network. The reasoning path itself is covered by
# test_agent_executor.py (run_agent_strategies). See docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.strategy import agent_run


def test_disabled_autonomy_skips_cleanly(monkeypatch):
    monkeypatch.setenv("AUTONOMY_CRON_ENABLED", "0")
    # If this tried to build Store(Settings()) it could hit prod; the gate must short-circuit BEFORE that.
    assert agent_run.main([]) == 0


def test_false_value_also_skips(monkeypatch):
    monkeypatch.setenv("AUTONOMY_CRON_ENABLED", "false")
    assert agent_run.main([]) == 0
