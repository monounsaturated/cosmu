# REGRESSION (locks commit d3e898b): Hyperliquid is DELIBERATELY excluded from the spine "has data" sets.
# Its provider (HyperliquidOHLCVProvider) is CACHE-ONLY — bars exist only after scripts/ingest_hyperliquid_bars.py
# runs, and that cache is gitignored, so a fresh checkout / CI / prod boot has none. Claiming "has data" for HL
# would be exactly the lie these sets forbid. The finder still backtests HL for any spec that explicitly declares
# it (lab/finder reads spec.universe.venues + the cache directly), so cross-asset HL works WITHOUT an
# always-available claim here. This test prevents a future edit from silently re-adding HL as if it had ingested
# data. Pure constants — no network, no store.

from __future__ import annotations

from cosmu.spine.universe import (
    _CRYPTO_VENUES_WITH_DATA,
    VENUES_WITH_DATA,
)


def test_hyperliquid_excluded_from_venues_with_data():
    """The /universe display "has data" set must NOT advertise Hyperliquid — its data path is cache-only."""
    assert "hyperliquid" not in VENUES_WITH_DATA


def test_hyperliquid_excluded_from_crypto_venues_with_data():
    """The crypto Finder/cohort gate set (has_live_data) must NOT include Hyperliquid for the same cache-only reason."""
    assert "hyperliquid" not in _CRYPTO_VENUES_WITH_DATA


def test_no_hyperliquid_aliases_leak_into_has_data_sets():
    """Belt-and-braces: no common HL spelling sneaks into either set under a different name."""
    aliases = {"hyperliquid", "hl", "hyperliquid_perp", "hyper_liquid"}
    assert not (aliases & VENUES_WITH_DATA)
    assert not (aliases & _CRYPTO_VENUES_WITH_DATA)


def test_kraken_included_in_has_data_sets():
    """The CONVERSE of the HL exclusion: Kraken HAS a keyless, always-available data path (KrakenSpotOHLCVProvider
    free public OHLC + managed-bar ccxt history in DEFAULT_BAR_VENUES), so it belongs in BOTH the display set and
    the crypto Finder/cohort gate — the /universe badge must stop saying 'no data' for Kraken."""
    assert "kraken" in VENUES_WITH_DATA
    assert "kraken" in _CRYPTO_VENUES_WITH_DATA
