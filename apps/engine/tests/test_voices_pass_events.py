# Step 3 of the LLM-leap: the voices pass now wires the INDEPENDENT event timeline (market_events, news/on-chain)
# into compute_authority, so each claim's lead-lag (foresight vs echo) goes from latent to live. These tests prove:
# the starter panel loads + is well-formed; _load_event_timeline maps venue symbols → claim entities and EXCLUDES
# voice posts (the circularity guard); and a claim that FOLLOWS a same-entity event is scored as an ECHO end-to-end
# through the pass. Offline + deterministic: fixture providers, an injected chat seam, fake bars, a SQLite store.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.config.voices import ENTITY_BARS_SYMBOL, VOICE_PANEL, Voice
from cosmu.data.events_store import MarketEvent, PgEventsStore
from cosmu.data.market import Bar
from cosmu.data.sources.voices import FixtureVoiceProvider, VoicePost
from cosmu.ingest.voices_pass import _load_event_timeline, run_voices_pass
from cosmu.knowledge.store import Store
from cosmu.mind.claims import HORIZON_DAYS, ClaimExtractor

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=20)
_HORIZON = min(HORIZON_DAYS, key=lambda h: HORIZON_DAYS[h])


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/voices.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- the pre-registered panel


def test_starter_panel_loads_and_is_well_formed():
    assert len(VOICE_PANEL) >= 8  # a real starter panel, not the empty default
    for v in VOICE_PANEL:
        assert v.platform in ("x", "reddit", "rss")
        assert v.handle and len(v.why) > 10  # every voice carries its pre-registered, falsifiable WHY
    # diversity: more than one platform, and a couple of distinct hypotheses (not all the same flavour).
    assert len({v.platform for v in VOICE_PANEL}) >= 2
    # every X handle is @-shaped; reddit is r/ or u/; rss is a URL — matches the provider routing.
    for v in VOICE_PANEL:
        if v.platform == "x":
            assert v.handle.startswith("@")
        elif v.platform == "reddit":
            assert v.handle.startswith(("r/", "u/"))
        elif v.platform == "rss":
            assert v.handle.startswith("http")


def test_real_panel_runs_offline_stubbed_with_honest_zeros(tmp_path):
    # The REAL VOICE_PANEL runs end-to-end through the pass with every platform stubbed empty (no keys, no
    # network) — one honest scoreboard row per voice, no claims, no fabricated skill. Proves panel↔pass wiring.
    store = _store(tmp_path)
    providers = {p: FixtureVoiceProvider({}, platform=p) for p in ("x", "reddit", "rss")}
    report = run_voices_pass(store, providers=providers, extractor=ClaimExtractor(chat=None),
                             now=datetime.now(UTC))
    assert report.voices == len(VOICE_PANEL)
    assert report.scoreboard_rows == len(VOICE_PANEL)
    assert report.claims_new == 0 and report.errors == []  # empty timelines → honest no-op, never an error
    rows = store.rows("SELECT handle, skill FROM voice_scoreboard")
    assert len(rows) == len(VOICE_PANEL)
    assert all(r["skill"] is None for r in rows)  # untested ≠ unskilled: NULL, never a fabricated 0


# --------------------------------------------------------------------------- the event timeline loader


def _news_event(symbol: str, *, days: int) -> MarketEvent:
    ts = _T0 + timedelta(days=days)
    return MarketEvent(provider="cryptopanic", source="wire", symbols=(symbol,), ts=ts,
                       available_at=ts, title=f"news on {symbol}", event_type="headline")


def test_load_event_timeline_maps_symbols_to_entities_and_excludes_voices(tmp_path):
    store = _store(tmp_path)
    events_store = PgEventsStore(store)
    # An external news event on BTCUSDT — must surface as an Event keyed by entity "BTC".
    events_store.append([_news_event("BTCUSDT", days=5)])
    # A voice post (provider='voices') — must be EXCLUDED (using it as its own evidence would be circular).
    events_store.append([MarketEvent(provider="voices", source="@x", symbols=(), ts=_T0 + timedelta(days=6),
                                     available_at=_T0 + timedelta(days=6), title="a tweet", event_type="voice_post")])
    # A market-wide event (no symbols) and an unmapped symbol — both dropped (named no_data, never guessed).
    events_store.append([_news_event("DOGEUSDT", days=7)])  # DOGE is mapped → kept
    events_store.append([MarketEvent(provider="gdelt", source="x", symbols=("UNMAPPEDX",), ts=_T0 + timedelta(days=8),
                                     available_at=_T0 + timedelta(days=8), title="x")])

    events = _load_event_timeline(store, {"BTC", "DOGE"}, now=_NOW)
    by_entity = {e.entity for e in events}
    assert by_entity == {"BTC", "DOGE"}                 # mapped symbols only
    assert all(e.entity in ENTITY_BARS_SYMBOL for e in events)
    assert all(e.ts <= _NOW for e in events)            # PIT: nothing past `now`


def test_load_event_timeline_honest_empty_on_fresh_store(tmp_path):
    store = _store(tmp_path)
    assert _load_event_timeline(store, set(), now=_NOW) == []          # no entities
    assert _load_event_timeline(store, {"BTC"}, now=_NOW) == []        # empty market_events


def test_event_timeline_marks_a_claim_following_an_event_as_an_echo(tmp_path):
    # End-to-end: a news event lands BEFORE the only claim → the claim is an ECHO (it reacted to the news), which
    # without the wired timeline would be 'none'. Proves the lead-lag separation is now LIVE in the pass.
    store = _store(tmp_path)
    PgEventsStore(store).append([_news_event("BTCUSDT", days=0)])  # event at day 0

    panel = (Voice("@reactor", "x", "posts after the news prints — echo candidate"),)
    posts = FixtureVoiceProvider(
        {"@reactor": [VoicePost(platform="x", handle="@reactor", post_id="r1",
                                text="BTC pumping, up we go", ts=_T0 + timedelta(days=1),  # day 1, AFTER the event
                                available_at=_T0 + timedelta(days=1))]},
        platform="x",
    )

    class _Chat:
        def __call__(self, _model: str, prompt: str) -> str:
            return json.dumps([{"entity": "BTC", "direction": "up", "horizon": _HORIZON,
                                "conviction": 0.8, "quote": "BTC up", "rationale": "momentum"}])

    class _RisingBars:
        def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
            bars = []
            for i in range(60):
                p = Decimal(str(round(30000 * (1.03 ** i), 2)))
                bars.append(Bar(ts=_T0 - timedelta(days=10) + timedelta(days=i),
                                open=p, high=p, low=p, close=p, volume=p))
            return bars[-limit:]

    report = run_voices_pass(
        store, panel=panel, providers={"x": posts}, extractor=ClaimExtractor(chat=_Chat()),
        bars_provider=_RisingBars(), now=_NOW,
    )
    assert report.claims_new == 1
    # Recompute the authority state with the same wired timeline and confirm the claim is classified as an echo.
    events = _load_event_timeline(store, {"BTC"}, now=_NOW)
    assert events and events[0].entity == "BTC"
    from cosmu.mind.authority import classify_lead_lag
    from cosmu.mind.claims import Claim, horizon_to_days

    claim = Claim(handle="@reactor", platform="x", post_id="r1", entity="BTC", direction="up",
                  horizon=_HORIZON, horizon_days=horizon_to_days(_HORIZON), conviction=0.8,
                  ts=_T0 + timedelta(days=1))
    assert classify_lead_lag(claim, events) == "echo"  # claim FOLLOWED the event → echo, not foresight
