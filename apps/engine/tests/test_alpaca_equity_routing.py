# The Alpaca equities lane shipped key-gated in #172 but nothing selected it — the paper clock's
# PricingRouter equity leg was hardwired to keyless Yahoo. This wires the lane: the equity leg PREFERS Alpaca
# (IEX, dividend-adjusted) when ALPACA keys are configured and degrades honestly to Yahoo without them, while
# the crypto leg stays on Binance. Widening the /universe "has data" sets to include the equity venue must NOT
# let the crypto-specific Finder/cohort fire on an empty crypto universe — has_live_data() stays crypto-keyed.
# Fully offline + deterministic (no provider is ever called; only the SELECTION is asserted).

from __future__ import annotations

from cosmu.adapters.data.alpaca import AlpacaDailyBarsProvider
from cosmu.config.settings import Settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store
from cosmu.orchestrator.loop import PricingRouter
from cosmu.spine.universe import (
    CLASSES_WITH_DATA,
    VENUES_WITH_DATA,
    enabled_universe,
    has_live_data,
    set_venue_enabled,
)
from cosmu.spine.venue import default_catalog


def _store(tmp_path, **settings_kwargs) -> Store:
    # _env_file=None → hermetic: the no-keys test must not inherit the dev box's real Alpaca keys from .env.local
    # (keyed tests still pass their own keys via **settings_kwargs, which override regardless).
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/alpaca_route.sqlite3", _env_file=None, **settings_kwargs))
    store.migrate()
    return store


def _seed_venues(store: Store) -> None:
    for v in default_catalog().venues:
        store.insert(
            "venues",
            {"id": v.id, "name": v.name, "kind": v.kind, "adapter": v.adapter,
             "fee_schedule": "{}", "constraints": "{}", "enabled": int(v.enabled)},
        )


# --- lane selection -----------------------------------------------------------------------------------------

def test_equity_leg_prefers_alpaca_when_keys_present(tmp_path):
    """A store carrying ALPACA paper keys → the clock's router prices equities via Alpaca; crypto stays Binance."""
    store = _store(tmp_path, alpaca_paper_api_key="k", alpaca_paper_api_secret="x")
    router = PricingRouter(default_catalog(), settings=store.settings)
    assert isinstance(router.provider_for("SPY", "alpaca"), AlpacaDailyBarsProvider)
    assert isinstance(router.provider_for("SPY", "ibkr"), AlpacaDailyBarsProvider)  # any equity instrument
    assert type(router.provider_for("BTCUSDT", "binance")).__name__ == "BinanceSpotOHLCVProvider"


def test_equity_leg_falls_back_to_yahoo_without_keys(tmp_path):
    """No keys → from_settings returns None → honest degradation to the keyless Yahoo total-return path."""
    store = _store(tmp_path)
    router = PricingRouter(default_catalog(), settings=store.settings)
    assert isinstance(router.provider_for("SPY", "alpaca"), YahooDailyBarsProvider)


def test_injected_equity_provider_wins_over_settings(tmp_path):
    """An explicitly injected equity provider (tests / alternate venues) always wins, keys or not."""
    store = _store(tmp_path, alpaca_paper_api_key="k", alpaca_paper_api_secret="x")

    class _Fake:
        def fetch_bars(self, symbol, timeframe, *, limit):  # noqa: ANN001, ANN201
            return []  # selection-only test; never actually called

    injected = _Fake()
    router = PricingRouter(default_catalog(), equity=injected, settings=store.settings)
    assert router.provider_for("SPY", "alpaca") is injected


# --- UI honesty + the crypto-Finder gate must stay crypto-specific ------------------------------------------

def test_equity_data_capability_is_now_honest():
    """Equity marks flow today (keyless Yahoo / Alpaca-when-keyed), so the /universe sets must say so."""
    assert "alpaca" in VENUES_WITH_DATA
    assert "equity" in CLASSES_WITH_DATA
    assert "binance" in VENUES_WITH_DATA and "crypto" in CLASSES_WITH_DATA


def test_has_live_data_stays_crypto_specific_when_only_equities_enabled(tmp_path):
    """REGRESSION (audit 2026-06-13): widening VENUES_WITH_DATA to include the equity venue must NOT make the
    crypto-only Finder/cohort fire on an empty crypto universe. With BOTH crypto data venues (Binance + Kraken)
    disabled but Alpaca (equity) still enabled and in VENUES_WITH_DATA, has_live_data() — the crypto gate —
    must be False (equity venues never satisfy the crypto-specific gate)."""
    store = _store(tmp_path)
    _seed_venues(store)
    set_venue_enabled(store, "binance", False)
    set_venue_enabled(store, "kraken", False)  # Kraken is also a crypto data venue now; isolate the equity case

    venues, classes = enabled_universe(store)
    assert "alpaca" in venues and "alpaca" in VENUES_WITH_DATA  # the equity venue IS enabled + display-data
    assert has_live_data(store) is False  # but the crypto Finder gate is correctly starved


def test_has_live_data_true_when_binance_enabled(tmp_path):
    store = _store(tmp_path)
    _seed_venues(store)
    assert has_live_data(store) is True


def test_has_live_data_true_on_kraken_alone(tmp_path):
    """Kraken is a real always-available crypto data venue (keyless public OHLC), so the crypto Finder gate is
    satisfied by Kraken even with Binance disabled — the converse of the equity-only starvation above."""
    store = _store(tmp_path)
    _seed_venues(store)
    set_venue_enabled(store, "binance", False)
    assert has_live_data(store) is True  # Kraken keeps the crypto gate alive
