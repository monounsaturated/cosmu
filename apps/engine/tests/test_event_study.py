# The deterministic event-study harness (research/event_study.py): an injected genuine reaction must PASS
# (low randomization-inference p, survives BH-FDR), a no-effect cell must FAIL, a cell whose move PRECEDES the
# "events" must be leakage-flagged and blocked from passing, confounded events are excluded, thin cells abstain
# (INSUFFICIENT, never a verdict), and the whole report is deterministic for a fixed seed. Synthetic series are
# CI-ONLY fixtures (never displayed in the app / run in prod) — the harness itself runs on real bars.

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.research.event_study import EventStudyConfig, run_event_study

_T0 = datetime(2026, 4, 1, tzinfo=UTC)
_N = 8640  # six days of 1m bars
_CFG = EventStudyConfig(
    windows=(5, 30), primary_window=30, pre_window=30, beta_window=240,
    exclusion_bars=60, market_z=4.0, min_events=10, placebo_sets=99, seed=7,
    market_symbol="BTCUSDT", fdr_q=0.10,
)
_JUMP = 0.0006  # per-bar injected drift (≈ 4σ over the 30-bar primary window)


def _bars_from_returns(returns: list[float]) -> list[Bar]:
    bars, price = [], 100.0
    for i, r in enumerate(returns):
        price *= math.exp(r)
        p = Decimal(str(round(price, 8)))
        bars.append(Bar(ts=_T0 + timedelta(minutes=i), open=p, high=p, low=p, close=p, volume=Decimal("1000")))
    return bars


def _event(kind: str, anchor: int, i: int) -> MarketEvent:
    # Event ts 30s before its anchor bar opens → bisect lands the anchor exactly on `anchor`.
    ts = _T0 + timedelta(minutes=anchor) - timedelta(seconds=30)
    return MarketEvent(provider="test", source=f"src{i}", symbols=("ALTUSDT",), ts=ts, available_at=ts,
                       title=f"{kind} event {i}", event_type=kind)


def _fixture() -> tuple[list[MarketEvent], dict[str, list[Bar]]]:
    rng = random.Random(42)
    r_m = [rng.gauss(0.0, 0.0008) for _ in range(_N)]
    r_a = [0.6 * m + rng.gauss(0.0, 0.0008) for m in r_m]

    events: list[MarketEvent] = []
    anchors = iter(range(300, 4000, 70))  # singles spaced > exclusion_bars apart

    for i in range(15):  # SIGNAL: genuine post-event drift over the primary window
        a = next(anchors)
        for j in range(a, a + 30):
            r_a[j] += _JUMP
        events.append(_event("signal", a, i))
    for i in range(15):  # NOISE: events with no injected effect
        events.append(_event("noise", next(anchors), i))
    for i in range(12):  # LEAKY: the move happens BEFORE and after the "event" (echo of the move)
        a = next(anchors)
        for j in range(a - 31, a - 1):   # pre-window drift (the tape moved first)
            r_a[j] += _JUMP
        for j in range(a, a + 30):       # and a post drift that would otherwise look like a pass
            r_a[j] += _JUMP
        events.append(_event("leaky", a, i))
    for i in range(3):   # THIN: below min_events → INSUFFICIENT
        events.append(_event("thin", next(anchors), i))
    base = next(anchors)  # CONF: two events 10 bars apart contaminate each other
    events.append(_event("conf", base, 0))
    events.append(_event("conf", base + 10, 1))

    bars = {"ALTUSDT": _bars_from_returns(r_a), "BTCUSDT": _bars_from_returns(r_m)}
    return events, bars


def test_injected_reaction_passes_noise_fails_leak_blocked():
    events, bars = _fixture()
    report = run_event_study(events, bars, _CFG)

    signal = report.cell("signal")
    assert signal is not None and signal.n_clean >= 10
    assert signal.mean_scar[30] > 2.0                       # the injected ≈4σ reaction is visible
    assert signal.ri_pvalue is not None and signal.ri_pvalue <= 0.02
    assert signal.verdict == "pass" and signal.fdr_pass
    assert not signal.leakage_flag

    noise = report.cell("noise")
    assert noise is not None and noise.verdict == "fail" and not noise.fdr_pass
    assert noise.ri_pvalue is not None and noise.ri_pvalue > 0.05
    assert abs(noise.mean_scar[30]) < 1.0

    leaky = report.cell("leaky")
    assert leaky is not None
    assert leaky.leakage_flag                               # the pre-window move is exposed…
    assert leaky.verdict == "fail" and not leaky.fdr_pass   # …and blocks the pass outright


def test_confounded_events_excluded_and_thin_cells_abstain():
    events, bars = _fixture()
    report = run_event_study(events, bars, _CFG)

    conf = report.cell("conf")
    assert conf is not None and conf.n_confounded == 2 and conf.n_clean == 0
    assert conf.verdict == "insufficient" and conf.ri_pvalue is None

    thin = report.cell("thin")
    assert thin is not None and thin.verdict == "insufficient"
    assert thin.ri_pvalue is None  # no p-value is ever fabricated below min_events


def test_report_is_deterministic():
    events, bars = _fixture()
    a = run_event_study(events, bars, _CFG)
    b = run_event_study(events, bars, _CFG)
    assert [(c.key, c.ri_pvalue, c.pre_pvalue, c.verdict, c.mean_scar) for c in a.cells] == [
        (c.key, c.ri_pvalue, c.pre_pvalue, c.verdict, c.mean_scar) for c in b.cells
    ]


def test_unpowered_events_are_skipped_not_guessed():
    events, bars = _fixture()
    # An event before the estimation window can begin, and one for a symbol with no bars at all.
    early = MarketEvent(provider="test", source="", symbols=("ALTUSDT",), ts=_T0 + timedelta(minutes=5),
                        available_at=_T0 + timedelta(minutes=5), title="too early", event_type="signal")
    nodata = MarketEvent(provider="test", source="", symbols=("GHOSTUSDT",), ts=_T0 + timedelta(minutes=500),
                         available_at=_T0 + timedelta(minutes=500), title="no bars", event_type="signal")
    report = run_event_study([*events, early, nodata], bars, _CFG)
    signal = report.cell("signal")
    assert signal.n_skipped == 2
    assert signal.verdict == "pass"  # the powered observations still carry the cell


def test_echoes_are_deduped_to_the_root():
    events, bars = _fixture()
    signal_events = [e for e in events if e.event_type == "signal"]
    # Mark five extra copies as echoes of the first signal event's cluster (hydrate for the real hash).
    root = signal_events[0].hydrated().content_hash
    echoes = [
        MarketEvent(provider="test", source="copycat", symbols=("ALTUSDT",),
                    ts=signal_events[0].ts + timedelta(minutes=i + 1),
                    available_at=signal_events[0].ts + timedelta(minutes=i + 1),
                    title=f"echo copy {i}", event_type="signal", root_event_id=root)
        for i in range(5)
    ]
    report = run_event_study([*events, *echoes], bars, _CFG)
    # roots_only: the echoes collapse into the breaker — the signal cell sees the same 15 observations.
    assert report.cell("signal").n_total == 15


def test_multi_symbol_event_is_one_inference_draw():
    """A story hitting two symbols is ONE event draw, not two observations of sample size — the
    cross-sectional-correlation guard (Kothari–Warner clustering critique)."""
    events, bars = _fixture()
    # Give the market panel a second alt so a multi-symbol event has two real legs.
    rng = random.Random(9)
    r_m = [rng.gauss(0.0, 0.0008) for _ in range(_N)]
    bars = dict(bars)
    bars["ALT2USDT"] = _bars_from_returns([0.5 * m + rng.gauss(0.0, 0.0008) for m in r_m])

    wide = MarketEvent(provider="test", source="", symbols=("ALTUSDT", "ALT2USDT"),
                       ts=_T0 + timedelta(minutes=5000) - timedelta(seconds=30),
                       available_at=_T0 + timedelta(minutes=5000), title="cross-asset story",
                       event_type="wide")
    report = run_event_study([*events, wide], bars, _CFG)
    cell = report.cell("wide")
    assert cell.n_total == 2 and cell.n_clean == 2   # two (event, symbol) observations…
    assert cell.n_clean_events == 1                  # …but ONE inference unit
    assert cell.verdict == "insufficient"            # 1 event << min_events — never a verdict from one story
