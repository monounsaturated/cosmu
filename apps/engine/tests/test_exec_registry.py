# The exec adapter registry (cosmu/adapters/exec/registry.py): the single venue -> ExecutionAdapter
# composition point used by the live ignition + the /live "configured" gate. A resolved adapter is safe
# (disabled without keys); key-presence is presence-only, never "armed".

from __future__ import annotations

from cosmu.adapters.exec.alpaca import AlpacaExecutionAdapter
from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
from cosmu.adapters.exec.polymarket import PolymarketExecutionAdapter
from cosmu.adapters.exec.registry import EXEC_ADAPTER_VENUES, adapter_for, keys_present, live_mode
from cosmu.config.settings import LiveSettings, Settings


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_adapter_for_resolves_each_wired_venue():
    s = _s()
    assert isinstance(adapter_for("binance", s), BinanceSpotExecutionAdapter)
    assert isinstance(adapter_for("alpaca", s), AlpacaExecutionAdapter)
    assert isinstance(adapter_for("polymarket", s), PolymarketExecutionAdapter)


def test_adapter_for_unknown_venue_is_none():
    assert adapter_for("ibkr", _s()) is None  # data/legal venue, no exec adapter wired
    assert adapter_for("nope", _s()) is None


def test_resolved_adapters_are_disabled_without_keys():
    s = _s()
    for venue in EXEC_ADAPTER_VENUES:
        adapter = adapter_for(venue, s)
        assert adapter is not None and adapter.active is False  # safe by construction


def test_keys_present_is_presence_only():
    assert keys_present("polymarket", _s()) is False
    assert keys_present("polymarket", _s(polymarket_testnet_private_key="0xt")) is True
    assert keys_present("polymarket", _s(polymarket_private_key="0xr")) is True  # presence != armed (mode still testnet)
    assert keys_present("binance", _s(binance_testnet_api_key="k", binance_testnet_api_secret="s")) is True
    assert keys_present("alpaca", _s(alpaca_paper_api_key="k", alpaca_paper_api_secret="s")) is True
    assert keys_present("ibkr", _s()) is False  # no adapter → never "connected"


def test_live_mode_aggregates_across_all_venues():
    """The /live API mode must reflect ANY wired venue, not just Binance — a Polymarket-only (or Alpaca-only)
    armed state used to falsely read 'disabled'/'sim'. live>testnet>disabled; alpaca 'paper' normalizes to
    testnet."""
    assert live_mode(_s()) == "disabled"
    assert live_mode(_s(polymarket_testnet_private_key="0xt")) == "testnet"  # polymarket-only sandbox
    assert live_mode(_s(binance_testnet_api_key="k", binance_testnet_api_secret="s")) == "testnet"
    assert live_mode(_s(alpaca_paper_api_key="k", alpaca_paper_api_secret="s")) == "testnet"  # paper→testnet
    # real money on ANY venue → 'live'
    live = _s(binance_api_key="k", binance_api_secret="s", live=LiveSettings(mode="real"))
    assert live_mode(live) == "live"


def test_polymarket_keys_present_does_not_imply_armed():
    # The configured gate is True (keys exist) but the adapter stays disabled until live.mode=='real'.
    s = _s(polymarket_private_key="0xreal")
    assert keys_present("polymarket", s) is True
    assert adapter_for("polymarket", s).active is False
    armed = _s(polymarket_private_key="0xreal", live=LiveSettings(mode="real"))
    # Even with mode=real the adapter degrades to disabled here: the dummy key fails to construct a signer, so
    # _build_clob_client returns None (honest degradation, never a half-live adapter that raises mid-tick).
    assert adapter_for("polymarket", armed).active is False
