"""The PLACEBO COHORT-RIDER — the seam that turns the dormant negative-control empirical-null panel into a STANDING
tripwire that rides EVERY finder cohort (roadmap #1). These tests pin the three load-bearing guarantees:

  (a) OFF BY DEFAULT — with COSMU_PLACEBO_RIDER unset, ride_cohort() is a no-op (returns None, runs NO panel),
      so the finder is byte-identical and the live verdict path is untouched.
  (b) ON + A CAUGHT LEAK — when the flag is ON and the panel reports any_cleared=True (a placebo cleared the
      LOCKED Gate = an upstream leak), the rider logs LOUDLY (WARNING) and writes a best-effort `placebo_leak`
      event row. (We make any_cleared True via a known-leaky synthetic panel, so the test is deterministic and
      cheap — the panel's OWN leak-detection correctness is already pinned by test_placebo_panel.py.)
  (c) LIVE VERDICT UNCHANGED — the rider is OBSERVE-ONLY: the locked Gate constants and promote_brut behaviour are
      identical whether the rider ran or not, the rider never raises into the finder, and a finder run with the
      flag ON produces the SAME survivors as with it OFF.

The instrument LOOSENS NOTHING: it reads the locked gate constants, never writes them.
"""

from __future__ import annotations

import logging

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.lab import placebo_rider
from cosmu.lab.placebo_rider import placebo_rider_enabled, ride_cohort
from cosmu.research.placebo_panel import PlaceboCell, PlaceboPanel

_RIDER_ENV = "COSMU_PLACEBO_RIDER"


def _gates():
    return Settings(openrouter_api_key=None).gates


def _clean_panel() -> PlaceboPanel:
    """A measured null where NO placebo cleared the Gate (the calibrated, leak-free case)."""
    cells = [
        PlaceboCell(spec_name="p1", family="random_entry", symbol="BTCUSDT", dsr=0.5, pbo=0.4, trades=40, cleared=False),
        PlaceboCell(spec_name="p2", family="time_shuffled", symbol="ETHUSDT", dsr=0.6, pbo=0.3, trades=35, cleared=False),
    ]
    return _panel_from(cells, any_cleared=False, cleared=[])


def _leaky_panel() -> PlaceboPanel:
    """A measured null where a placebo CLEARED the locked Gate — the caught-leak case (any_cleared=True)."""
    leaked = PlaceboCell(
        spec_name="Placebo random-entry #3", family="random_entry", symbol="BTCUSDT",
        dsr=0.97, pbo=0.1, trades=60, cleared=True,
    )
    clean = PlaceboCell(spec_name="p2", family="time_shuffled", symbol="ETHUSDT", dsr=0.6, pbo=0.3, trades=35, cleared=False)
    return _panel_from([leaked, clean], any_cleared=True, cleared=[leaked])


def _panel_from(cells, *, any_cleared: bool, cleared) -> PlaceboPanel:
    dsrs = [c.dsr for c in cells]
    return PlaceboPanel(
        cells=cells, gate_dsr_floor=0.95, n_specs=2, n_cells=len(cells),
        dsr_mean=sum(dsrs) / len(dsrs), dsr_p50=dsrs[0], dsr_p95=max(dsrs), dsr_max=max(dsrs),
        pbo_mean=0.3, pbo_p50=0.3, pbo_min=0.1, any_cleared=any_cleared, cleared_cells=list(cleared),
    )


class _RecordingStore:
    """A minimal Store stand-in capturing append_event calls (the events-table audit trail)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def append_event(self, *, actor, kind, ref_type=None, ref_id=None, payload=None) -> None:
        self.events.append({"actor": actor, "kind": kind, "ref_type": ref_type, "ref_id": ref_id, "payload": payload})


def _tiny_market() -> dict[str, list[Bar]]:
    from cosmu.research.fixtures import permutation_null_market

    return permutation_null_market(correlated=False, n=120, seed=11)


# --------------------------------------------------------------------------- (a) OFF BY DEFAULT


def test_rider_off_by_default(monkeypatch):
    """With COSMU_PLACEBO_RIDER unset, the rider is disabled and ride_cohort is a strict no-op (returns None,
    NEVER runs the panel) — the finder cohort path is byte-identical."""
    monkeypatch.delenv(_RIDER_ENV, raising=False)
    assert placebo_rider_enabled() is False

    calls = {"n": 0}

    def _boom(**_kwargs):  # the panel must NOT be invoked when the flag is off
        calls["n"] += 1
        raise AssertionError("run_placebo_panel must not run when the rider flag is OFF")

    monkeypatch.setattr(placebo_rider, "run_placebo_panel", _boom)
    out = ride_cohort(market=_tiny_market(), gates=_gates(), family="seed")
    assert out is None
    assert calls["n"] == 0


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_rider_falsey_values_stay_off(monkeypatch, val):
    monkeypatch.setenv(_RIDER_ENV, val)
    assert placebo_rider_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "On"])
def test_rider_truthy_values_turn_on(monkeypatch, val):
    monkeypatch.setenv(_RIDER_ENV, val)
    assert placebo_rider_enabled() is True


# --------------------------------------------------------------------------- (b) ON + A CAUGHT LEAK FIRES LOUDLY


def test_rider_on_caught_leak_logs_loud_and_writes_event(monkeypatch, caplog):
    """Flag ON + the panel reports any_cleared=True → the rider logs a LOUD WARNING and writes a `placebo_leak`
    event row carrying the cleared cells. This is the caught-upstream-leak alarm."""
    monkeypatch.setenv(_RIDER_ENV, "1")
    monkeypatch.setattr(placebo_rider, "run_placebo_panel", lambda **_k: _leaky_panel())
    store = _RecordingStore()

    with caplog.at_level(logging.WARNING, logger="cosmu.lab.placebo_rider"):
        out = ride_cohort(market=_tiny_market(), gates=_gates(), family="seed-fam", store=store)

    assert out is not None
    assert out.any_cleared is True
    # LOUD WARNING fired with the alarm wording
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("UPSTREAM LEAK CAUGHT" in r.getMessage() for r in warnings)
    # a placebo_leak event row was written with the cleared cell detail
    leaks = [e for e in store.events if e["kind"] == "placebo_leak"]
    assert len(leaks) == 1
    assert leaks[0]["ref_id"] == "seed-fam"
    assert leaks[0]["payload"]["n_cleared"] == 1
    assert leaks[0]["payload"]["cleared"][0]["symbol"] == "BTCUSDT"


def test_rider_on_clean_panel_no_warning_no_event(monkeypatch, caplog):
    """Flag ON + the panel is CLEAN (no placebo cleared) → an INFO breadcrumb only, NO warning, NO leak event."""
    monkeypatch.setenv(_RIDER_ENV, "1")
    monkeypatch.setattr(placebo_rider, "run_placebo_panel", lambda **_k: _clean_panel())
    store = _RecordingStore()

    with caplog.at_level(logging.INFO, logger="cosmu.lab.placebo_rider"):
        out = ride_cohort(market=_tiny_market(), gates=_gates(), family="seed", store=store)

    assert out is not None and out.any_cleared is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [e for e in store.events if e["kind"] == "placebo_leak"] == []


def test_rider_places_survivor_in_null_tail(monkeypatch):
    """Flag ON → each promoted survivor's DSR is placed in the measured null's right tail (the propose-only
    credibility read), returned for the caller without touching any verdict."""
    monkeypatch.setenv(_RIDER_ENV, "1")
    monkeypatch.setattr(placebo_rider, "run_placebo_panel", lambda **_k: _clean_panel())
    out = ride_cohort(
        market=_tiny_market(), gates=_gates(), family="seed",
        survivor_dsrs={"v1:BTCUSDT@binance": 0.99},
    )
    assert out is not None
    cmp = out.survivor_comparisons["v1:BTCUSDT@binance"]
    assert cmp.survivor_dsr == 0.99
    assert cmp.right_tail is True  # 0.99 > null p95 (0.6) AND >= the gate floor (0.95)


# --------------------------------------------------------------------------- (c) OBSERVER NEVER ENDANGERS THE RUN


def test_rider_swallows_panel_error(monkeypatch, caplog):
    """The rider is OBSERVE-ONLY: if the panel run raises, the rider swallows it (returns None) and the finder
    run is unaffected — an observer must NEVER put the live verdict path at risk."""
    monkeypatch.setenv(_RIDER_ENV, "1")

    def _explode(**_k):
        raise RuntimeError("panel blew up")

    monkeypatch.setattr(placebo_rider, "run_placebo_panel", _explode)
    with caplog.at_level(logging.ERROR, logger="cosmu.lab.placebo_rider"):
        out = ride_cohort(market=_tiny_market(), gates=_gates(), family="seed")
    assert out is None  # swallowed; no exception propagates to the finder


def test_rider_empty_market_is_noop(monkeypatch):
    """Flag ON but an empty/bar-less market → no panel, returns None (nothing to measure)."""
    monkeypatch.setenv(_RIDER_ENV, "1")
    called = {"n": 0}
    monkeypatch.setattr(placebo_rider, "run_placebo_panel", lambda **_k: called.__setitem__("n", called["n"] + 1))
    assert ride_cohort(market={}, gates=_gates(), family="seed") is None
    assert ride_cohort(market={"BTCUSDT": []}, gates=_gates(), family="seed") is None
    assert called["n"] == 0


# --------------------------------------------------------------------------- (c) END-TO-END: finder verdict identical


class _FixtureBars:
    """The same small offline market the finder test uses: 2 catalog symbols × edge-bearing bars."""

    def __init__(self) -> None:
        from cosmu.research.fixtures import edge_bearing_screen_market

        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _run_finder(tmp_path, name: str):
    from cosmu.evolution.seeder import seed_orb_fvg_spec
    from cosmu.knowledge.store import Store
    from cosmu.lab.finder import StrategyFinder

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))
    finder = StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())
    return finder.find(seed_orb_fvg_spec(), max_variants=8)


def test_finder_verdict_identical_flag_on_vs_off(tmp_path, monkeypatch):
    """END-TO-END: a finder run with the rider OFF and a run with it ON must produce the IDENTICAL verdict —
    same screened/gate_passed/promoted counts and the same survivor config_tags. The rider is OBSERVE-ONLY: it
    rides the cohort but NEVER changes the brut promote_brut decision or the Gate constants."""
    monkeypatch.delenv(_RIDER_ENV, raising=False)
    off = _run_finder(tmp_path, "off")

    monkeypatch.setenv(_RIDER_ENV, "1")
    on = _run_finder(tmp_path, "on")

    assert (off.screened, off.gate_passed, off.promoted) == (on.screened, on.gate_passed, on.promoted)
    assert sorted(r.config_tag for r in off.survivors) == sorted(r.config_tag for r in on.survivors)
    assert sorted(r.config_tag for r in off.leaderboard) == sorted(r.config_tag for r in on.leaderboard)


def test_finder_run_with_rider_on_does_not_raise(tmp_path, monkeypatch):
    """The rider riding a REAL finder cohort (flag ON, real bounded placebo panel) completes without raising —
    the standing instrument is wired live and bounded."""
    monkeypatch.setenv(_RIDER_ENV, "1")
    report = _run_finder(tmp_path, "live")
    assert report.screened > 0
