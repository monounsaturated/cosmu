# The CREDIBILITY pillar in the Mind panel (analysts.py::authority_analyst) — closes the one real code gap the
# llm-mind-stack assessment flagged: the panel now READS `authority_weighted_claim_signal`. The feature is stored
# in alt_data keyed by ENTITY ("BTC"), but the panel reasons per venue symbol ("BTCUSDT"), so the analyst maps
# symbol→entity to find it. Offline + deterministic: a tiny SQLite store, hand-written alt_data rows, no LLM,
# no network. Observe-only — these analysts never move money (the gate alone funds).

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.knowledge.store import Store
from cosmu.mind.analysts import (
    ALL_ANALYSTS,
    AUTHORITY_SIGNAL_METRIC,
    authority_analyst,
    context_for_symbol,
    gather_context,
    resolve_authority_signal,
)

_NOW = datetime(2026, 6, 26, tzinfo=UTC)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/mind.sqlite3", openrouter_api_key=None))


def _write_authority(store: Store, entity: str, value: float) -> None:
    """Write one authority_weighted_claim_signal row keyed by ENTITY, exactly as voices_pass does."""
    PgAltDataStore(store).append(
        "social_authority", entity, AUTHORITY_SIGNAL_METRIC,
        [AltDataPoint(ts=_NOW, available_at=_NOW, value=value)],
    )


def test_authority_analyst_is_registered_in_the_panel():
    perspectives = {a.__name__ for a in ALL_ANALYSTS}
    assert "authority_analyst" in perspectives


def test_authority_analyst_abstains_without_a_signal(tmp_path):
    store = _store(tmp_path)
    ctx = context_for_symbol(store, gather_context(store), "BTCUSDT")
    stance = authority_analyst(ctx)
    assert stance.lean == "abstain" and stance.conviction == 0.0 and stance.weight == 0.0
    assert stance.source == "abstain"  # honest no-data, never a fabricated read


def test_authority_analyst_reads_bullish_signal_per_symbol(tmp_path):
    store = _store(tmp_path)
    _write_authority(store, "BTC", 0.8)   # credible voices lean strongly bullish on BTC
    ctx = context_for_symbol(store, gather_context(store), "BTCUSDT")
    stance = authority_analyst(ctx)
    assert stance.lean == "bullish" and stance.conviction > 0.5
    assert stance.weight == 0.5 and stance.low_confidence is True  # must earn its place OOS
    assert f"{AUTHORITY_SIGNAL_METRIC}=+0.80" in stance.evidence[0]


def test_authority_analyst_reads_bearish_signal(tmp_path):
    store = _store(tmp_path)
    _write_authority(store, "ETH", -0.7)
    ctx = context_for_symbol(store, gather_context(store), "ETHUSDT")
    assert authority_analyst(ctx).lean == "bearish"


def test_authority_signal_does_not_leak_across_symbols(tmp_path):
    # BTC is bullish; ETH has NO authority row. The per-symbol read must NOT inherit BTC's value onto ETH —
    # the exact cross-asset leak context_for_symbol's strip+entity-keyed resolution defends against.
    store = _store(tmp_path)
    _write_authority(store, "BTC", 0.9)
    base = gather_context(store)
    btc = context_for_symbol(store, base, "BTCUSDT")
    eth = context_for_symbol(store, base, "ETHUSDT")
    assert authority_analyst(btc).lean == "bullish"
    assert authority_analyst(eth).lean == "abstain"  # ETH unseen → honest abstain, never BTC's value


def test_resolve_authority_signal_maps_symbol_to_entity(tmp_path):
    store = _store(tmp_path)
    _write_authority(store, "SOL", 0.5)
    got = resolve_authority_signal(store, "SOLUSDT")
    assert got is not None and abs(got[0] - 0.5) < 1e-9
    assert resolve_authority_signal(store, "SOLUSDT") is not None  # cached path still resolves
    assert resolve_authority_signal(store, "NOTAPAIR") is None     # unmapped symbol → None, never guessed


def test_authority_analyst_neutral_band(tmp_path):
    store = _store(tmp_path)
    _write_authority(store, "BTC", 0.02)  # inside the +/-0.1 dead band
    ctx = context_for_symbol(store, gather_context(store), "BTCUSDT")
    assert authority_analyst(ctx).lean == "neutral"
