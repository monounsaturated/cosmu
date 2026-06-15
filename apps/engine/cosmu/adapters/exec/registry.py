# intent: the SINGLE venue -> ExecutionAdapter composition point, so the order path / live ignition never
# hardcodes a per-venue adapter; inputs: a venue id + Settings; outputs: a resolved core.ExecutionAdapter (or
# None for an unwired venue) and a key-presence boolean for the "configured" UI gate; invariants: a resolved
# adapter is SAFE by construction (its own from_settings returns a disabled adapter when keys/mode are absent,
# so submit raises and nothing routes), key-presence asks ONLY whether creds exist (never whether live.mode is
# real), and this module imports the concrete adapters lazily so it adds no import cycle.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.core.interfaces import ExecutionAdapter

# Venues that have a real ExecutionAdapter implementation today. A venue NOT here can still be a data/research
# venue — it just has no live-money leg, so adapter_for() returns None and the live lane sim-fills it.
EXEC_ADAPTER_VENUES: frozenset[str] = frozenset({"binance", "alpaca", "polymarket"})


def adapter_for(venue_id: str, settings: Settings) -> ExecutionAdapter | None:
    """Resolve the ExecutionAdapter for a venue from settings, or None when no adapter is wired for it. The
    returned adapter is already safe: with no keys / live.mode != 'real' it is `disabled` (submit raises,
    positions/fills return []), so calling this never arms anything on its own."""
    if venue_id == "binance":
        from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter

        return BinanceSpotExecutionAdapter.from_settings(settings)
    if venue_id == "alpaca":
        from cosmu.adapters.exec.alpaca import AlpacaExecutionAdapter

        return AlpacaExecutionAdapter.from_settings(settings)
    if venue_id == "polymarket":
        from cosmu.adapters.exec.polymarket import PolymarketExecutionAdapter

        return PolymarketExecutionAdapter.from_settings(settings)
    return None


def live_mode(settings: Settings) -> str:
    """The aggregate resolved execution mode across ALL wired venues — 'live' if ANY venue resolves to real
    money, else 'testnet' if any resolves to a sandbox (testnet/paper), else 'disabled'. The /live API reports
    THIS instead of one venue's mode, so a Polymarket-only or Alpaca-only armed state is shown honestly (the
    old single-Binance check reported 'sim'/'not armed' while Polymarket was actually routing live). Uses each
    adapter's PURE resolve_mode (keys + live.mode interlock) — no network, safe in the API read path."""
    from cosmu.adapters.exec.alpaca import resolve_mode as _alpaca_mode
    from cosmu.adapters.exec.binance import resolve_mode as _binance_mode
    from cosmu.adapters.exec.polymarket import resolve_mode as _polymarket_mode

    modes = {_binance_mode(settings), _alpaca_mode(settings), _polymarket_mode(settings)}
    if "live" in modes:
        return "live"
    if "testnet" in modes or "paper" in modes:  # alpaca calls its sandbox 'paper'; normalize to testnet
        return "testnet"
    return "disabled"


def keys_present(venue_id: str, settings: Settings) -> bool:
    """True when execution credentials EXIST for a venue (the UI 'configured' gate). This is presence-only —
    it does NOT mean live is armed (that still needs live.mode=='real' + the toggle + a gate-passed survivor).
    Paper/testnet keys count as configured (they connect to the venue, just not with real funds)."""
    if venue_id == "binance":
        return bool(
            (settings.binance_api_key and settings.binance_api_secret)
            or (settings.binance_testnet_api_key and settings.binance_testnet_api_secret)
        )
    if venue_id == "alpaca":
        return bool(
            (settings.alpaca_api_key and settings.alpaca_api_secret)
            or (settings.alpaca_paper_api_key and settings.alpaca_paper_api_secret)
        )
    if venue_id == "polymarket":
        return bool(settings.polymarket_private_key or settings.polymarket_testnet_private_key)
    return False
