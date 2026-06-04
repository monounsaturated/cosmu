# Offline tests for the canonical perp universe + the dedupe normalizer. Pure constants/helpers — no network.

from __future__ import annotations

from cosmu.data.universe import (
    CORE_PERP_UNIVERSE,
    PERP_UNIVERSE,
    dedupe_symbols,
    perp_universe,
)


def test_universe_is_widened_and_deduped():
    # The carry-verdict next action: widen 5 → 20–50 liquid perps.
    assert 20 <= len(PERP_UNIVERSE) <= 50
    # No symbol appears twice (deduped at definition time).
    assert len(set(PERP_UNIVERSE)) == len(PERP_UNIVERSE)
    # All upper-cased, all USDT perps (the venue spelling).
    assert all(s == s.upper() and s.endswith("USDT") for s in PERP_UNIVERSE)
    # The core slice is the first 5 and a strict prefix of the wide universe.
    assert CORE_PERP_UNIVERSE == PERP_UNIVERSE[:5]
    assert len(CORE_PERP_UNIVERSE) == 5


def test_dedupe_symbols_is_order_preserving_and_normalizing():
    out = dedupe_symbols([" btcusdt ", "ETHUSDT", "btcusdt", "", "  ", "ethusdt"])
    assert out == ("BTCUSDT", "ETHUSDT")  # first occurrence kept, upper-cased, blanks dropped
    # upper=False leaves case intact but still dedupes exact spellings
    assert dedupe_symbols(["a", "A", "a"], upper=False) == ("a", "A")


def test_perp_universe_truncation_is_deterministic():
    assert perp_universe(10) == list(PERP_UNIVERSE[:10])
    assert perp_universe() == list(PERP_UNIVERSE)
    assert perp_universe(0) == []
    # The deepest-N slice is a prefix (volume-ordered) — stable across calls.
    assert perp_universe(3) == perp_universe(3)
