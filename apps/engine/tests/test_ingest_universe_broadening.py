# intent: verify that run_once / the scheduler sweep the FULL perp_universe() when no symbols are given,
# not just the old DEFAULT_SYMBOLS ("BTCUSDT", "ETHUSDT"). Offline — fixture providers only.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider
from cosmu.data.universe import PERP_UNIVERSE, perp_universe
from cosmu.ingest.run import DEFAULT_SYMBOLS, Providers, run_once
from cosmu.knowledge.store import Store

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _fixture_funding(symbols) -> FixtureAltDataProvider:
    """Return one AltDataPoint per symbol so the assertion can count them."""
    data = {(sym, "funding_rate"): [AltDataPoint(ts=_T0, available_at=_T0, value=0.0001)] for sym in symbols}
    return FixtureAltDataProvider(data)


def test_run_once_default_symbols_is_full_universe(tmp_path):
    """When no symbols arg is given run_once must use the full perp_universe(), NOT the legacy 2-symbol constant."""
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/k.sqlite3", openrouter_api_key=None))
    full = perp_universe()

    # Sanity: the old DEFAULT_SYMBOLS ("BTCUSDT", "ETHUSDT") is a strict subset of the full universe.
    assert set(DEFAULT_SYMBOLS).issubset(set(full)), "DEFAULT_SYMBOLS must still be part of PERP_UNIVERSE"
    # The full universe must be strictly wider than the legacy 2-symbol constant.
    assert len(full) > len(DEFAULT_SYMBOLS), "perp_universe() must be wider than the legacy DEFAULT_SYMBOLS pair"

    # Build a fixture funding provider that has data for every symbol in the full universe.
    funding_fixture = _fixture_funding(full)
    null_provider = FixtureAltDataProvider({})  # all other sources return empty (zero counts; safe)

    providers = Providers(
        funding=funding_fixture,
        feargreed=null_provider,
        news=null_provider,
        fred=null_provider,
        polymarket=null_provider,
        liquidations=null_provider,
        putcall=null_provider,
        defillama=null_provider,
        open_interest=null_provider,
        basis=null_provider,
        netflow=null_provider,
        osint=null_provider,
        polymarket_clob=null_provider,
        reddit=null_provider,
        lunarcrush=null_provider,
        okx_funding=null_provider,
        kraken_futures_funding=null_provider,
        gdelt_tone=null_provider,
        dvol=null_provider,
        xai_twitter=null_provider,
        llm_index=null_provider,
        venue_fees=null_provider,
        multiasset=null_provider,
    )

    # Call run_once WITHOUT passing symbols → must default to perp_universe().
    counts = run_once(store, providers=providers)

    # The funding_rate count must equal the full universe size (one point per symbol), NOT just 2.
    assert counts["funding_rate"] == len(full), (
        f"run_once without explicit symbols should cover all {len(full)} perp universe symbols, "
        f"got {counts['funding_rate']} (old DEFAULT_SYMBOLS only covers {len(DEFAULT_SYMBOLS)})"
    )


def test_run_once_explicit_symbols_not_overridden(tmp_path):
    """An explicit symbols list must still be honoured — the universe broadening must not ignore caller overrides."""
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/k2.sqlite3", openrouter_api_key=None))
    explicit = ["BTCUSDT", "SOLUSDT"]
    funding_fixture = _fixture_funding(explicit)
    null_provider = FixtureAltDataProvider({})

    providers = Providers(
        funding=funding_fixture,
        feargreed=null_provider,
        news=null_provider,
        fred=null_provider,
        polymarket=null_provider,
        liquidations=null_provider,
        putcall=null_provider,
        defillama=null_provider,
        open_interest=null_provider,
        basis=null_provider,
        netflow=null_provider,
        osint=null_provider,
        polymarket_clob=null_provider,
        reddit=null_provider,
        lunarcrush=null_provider,
        okx_funding=null_provider,
        kraken_futures_funding=null_provider,
        gdelt_tone=null_provider,
        dvol=null_provider,
        xai_twitter=null_provider,
        llm_index=null_provider,
        venue_fees=null_provider,
        multiasset=null_provider,
    )

    counts = run_once(store, symbols=explicit, providers=providers)
    assert counts["funding_rate"] == len(explicit), (
        "explicit symbols kwarg must be respected (caller should still be able to narrow the universe)"
    )
