# intent: OFFLINE unit test for the astro deep-dive harness scaffolding — proves the CostTracker STOP latch,
# the DeepDiveConfig scope/cost math, and that `--mode prepare` (prepare_only) runs PHASE0 and spends $0 WITHOUT
# importing modal or hitting the network. No DB, no Modal, no network — pure local wiring proof.

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research"))

from astro_deepdive_modal.cost_tracker import CostTracker  # noqa: E402


def test_cost_tracker_stop_latch_fires_once_over_threshold() -> None:
    ct = CostTracker(budget_usd=10.0, container_hr_usd=1.0)
    ct.add_container_hours(5, label="p1").checkpoint("under")  # $5 < 0.8*$10
    assert not ct.should_stop
    ct.add_container_hours(4, label="p3").checkpoint("over")  # $9 > $8 stop line
    assert ct.should_stop
    # latch is idempotent: a second over-threshold checkpoint stays stopped, no exception
    ct.checkpoint("still over")
    assert ct.should_stop
    s = ct.summary()
    assert s["stopped"] is True and s["spent_usd"] == 9.0 and s["budget_usd"] == 10.0


def test_cost_tracker_emit_falls_back_to_print_without_webhook(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    ct = CostTracker(budget_usd=1.0, container_hr_usd=1.0)
    ct.add_container_hours(1, label="p").checkpoint("boom")  # $1 > 0.8 → alert via print
    out = capsys.readouterr().out
    assert "budget STOP" in out and ct.should_stop


def test_deepdive_config_scope_and_cost_in_envelope() -> None:
    m = _entry_module()
    spec = m.DownloadSpec(pairs=[f"P{i}USDT" for i in range(400)], timeframes=["1d", "1h", "1m"])
    cfg = _make_cfg(spec)
    scope = cfg.scope_summary()
    assert scope["r2_prefix"] == "astro_deepdive"
    assert scope["pairs"] == 400
    assert scope["n_download_containers"] == 1200  # 400 pairs × 3 timeframes
    # full-universe estimate sits inside the PLAN's $35–110 envelope and under the 0.8× stop
    assert 20.0 <= scope["est_modal_usd"] <= 110.0
    assert scope["stop_at_usd"] == 88.0


def test_prepare_only_runs_phase0_and_spends_zero(capsys) -> None:
    cfg = _make_cfg()
    out = _run(cfg, prepare_only=True)
    assert out["phase"] == "prepare"
    assert out["spent_usd"] == 0.0
    printed = capsys.readouterr().out
    assert "PHASE0" in printed and "$0 spent" in printed


def test_prepare_only_empty_pairs_aborts() -> None:
    m = _entry_module()
    cfg = _make_cfg(m.DownloadSpec(pairs=[]))
    try:
        _run(cfg, prepare_only=True)
    except SystemExit as e:
        assert "pairs is empty" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit on empty pairs")


# ── helpers: import the entry harness by path (it shares a name with the package, so load it explicitly) ──


def _entry_module():
    import importlib.util

    path = ENGINE_ROOT / "scripts/research/astro_deepdive_modal.py"
    spec = importlib.util.spec_from_file_location("astro_deepdive_modal_entry", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # register so dataclass cls.__module__ resolves
    spec.loader.exec_module(mod)
    return mod


def _make_cfg(spec=None):
    m = _entry_module()
    if spec is None:
        return m.DeepDiveConfig()
    return m.DeepDiveConfig(download_spec=spec)


def _run(cfg, *, prepare_only):
    m = _entry_module()
    return m.run_astro_deepdive_modal(cfg, prepare_only=prepare_only)
