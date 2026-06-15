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


# ── PHASE1 resilience helpers (resume-from-mirror + bounded retry) — offline, no network/Modal ──────


def test_slab_resume_guard_skips_existing_local_parquet(tmp_path) -> None:
    """_slab_done returns True once a slab's local-mirror Parquet exists (so a re-run SKIPS that pair),
    and False before it is written — proving resume-from-store without touching R2 or the network."""
    import pandas as pd

    m = _entry_module()

    class _Store:  # minimal stand-in for LabStore's resume-relevant surface (local mirror only)
        local = tmp_path
        r2_ready = False

        def r2_uri(self, batch_id):
            return f"r2://x/{batch_id}.parquet"

    store = _Store()
    assert m._slab_done(store, "BTCUSDT", "1d") is False  # nothing written yet
    p = tmp_path / (m._slab_batch_id("BTCUSDT", "1d") + ".parquet")
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts": [1, 2], "close": [10.0, 11.0]}).to_parquet(p)
    assert m._slab_done(store, "BTCUSDT", "1d") is True  # now present → skip on re-run


def test_fetch_month_zip_404_returns_none_without_retry_loop(monkeypatch) -> None:
    """A genuine 404 (month not published / pair not live) returns None immediately — honest absence, never
    fabricated bars, and never burns the full retry budget on a permanent miss."""
    import urllib.error
    import urllib.request

    m = _entry_module()
    calls = {"n": 0}

    def _raise_404(*a, **k):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 404, "nope", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", _raise_404)
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbav", "tbqv", "ignore"]
    out = m._fetch_month_zip("http://x/none.zip", cols, attempts=4, timeout=1)
    assert out is None and calls["n"] == 1  # stopped on the 404, did not retry


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
