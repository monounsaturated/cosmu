from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import FarmLoop, fit_params
from cosmu.knowledge.store import Store
from cosmu.lab.author import draft_from_brief
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.pine_samples import PINE_SAMPLES
from cosmu.strategy.static_check import validate_spec


class FixtureProvider:
    def __init__(self) -> None:
        self.bars = _fixture_bars()

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def _fixture_bars(count: int = 360) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for idx in range(count):
        move = Decimal("0.01") if idx % 16 < 8 else Decimal("-0.008")
        open_ = price
        close = (price * (Decimal("1") + move)).quantize(Decimal("0.0001"))
        bars.append(
            Bar(
                ts=ts + timedelta(days=idx),
                open=open_,
                high=(max(open_, close) * Decimal("1.005")).quantize(Decimal("0.0001")),
                low=(min(open_, close) * Decimal("0.995")).quantize(Decimal("0.0001")),
                close=close,
                volume=Decimal("1000"),
            )
        )
        price = close
    return bars


@pytest.mark.parametrize("name", list(PINE_SAMPLES))
def test_every_community_pine_sample_translates_and_compiles(name):
    tr = translate_pine(PINE_SAMPLES[name])
    assert validate_spec(tr.spec) == [], f"{name} invalid: {validate_spec(tr.spec)}"
    compile_spec(tr.spec, fit_params(tr.spec))  # must not raise
    assert tr.spec.entry, f"{name} has no entry conditions"


def test_pine_lifts_input_var_threshold():
    # oversold = input.int(30); ta.crossover(rsiVal, oversold) → threshold 30 lifted, not 0
    tr = translate_pine(PINE_SAMPLES["RSI oversold reversion"])
    assert any(round(v) == 30 for v in tr.lifted_params.values())
    assert tr.spec.entry[0].feature.name == "rsi"


def test_pine_band_breakout_maps_to_bb_z():
    tr = translate_pine(PINE_SAMPLES["Bollinger breakout"])
    assert any(c.feature.name == "bb_z" for c in tr.spec.entry)


def test_author_drafts_valid_spec_from_brief():
    draft = draft_from_brief("Fade oversold RSI on crypto with a tight stop, swing horizon")
    assert draft.valid
    assert draft.base_template == "mean_reversion"
    assert "binance" in draft.venues
    assert draft.data_sources  # derived from feature registry
    assert draft.requires_approval is False  # research-only draft


def test_author_flags_money_adjacent_intent():
    draft = draft_from_brief("go live with real capital on a momentum breakout")
    assert draft.requires_approval is True


def test_author_detects_osint_air_activity_from_plane_brief():
    # a free-text brief about watching planes / flight activity auto-detects the OSINT air-activity feature
    draft = draft_from_brief("watching planes and flight activity as a crypto risk-appetite proxy")
    assert "osint_air_activity" in draft.features
    assert "opensky" in draft.data_sources


def test_author_run_seeds_cohort(tmp_path):
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/author.sqlite3"))
    loop = FarmLoop(settings=store.settings, store=store, market_data=FixtureProvider())
    draft = draft_from_brief("momentum trend on equities")
    summary = loop.run_cohort(seed=5, cohort_size=40, extra_seeds=[draft.spec])
    assert summary.lanes["chat"] == 1
    assert summary.generated > 0
