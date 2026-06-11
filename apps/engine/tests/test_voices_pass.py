# The credibility pass (ingest/voices_pass.py, realtime-data-lane epic P2): pre-registered panel only, posts
# stored durably + deduped (re-runs never re-spend the extractor), claims persisted once, deterministic
# Phase-2/3 scoring lands in the flat voice_scoreboard + the two registered alt_data features, and keyless
# runs degrade honestly. Offline + deterministic: fixture providers, an injected chat seam, fake bars.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.config.voices import Voice
from cosmu.data.market import Bar
from cosmu.data.sources.voices import FixtureVoiceProvider, VoicePost
from cosmu.ingest.voices_pass import run_voices_pass
from cosmu.knowledge.store import Store
from cosmu.mind.claims import HORIZON_DAYS, ClaimExtractor

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=20)  # claims resolved (past their horizon) AND inside the 30d signal window
_HORIZON = min(HORIZON_DAYS, key=lambda h: HORIZON_DAYS[h])  # the shortest canonical horizon code


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/voices.sqlite3", openrouter_api_key=None))


def _post(handle: str, post_id: str, text: str, *, days: int) -> VoicePost:
    ts = _T0 + timedelta(days=days)
    return VoicePost(platform="x", handle=handle, post_id=post_id, text=text, ts=ts, available_at=ts)


def _panel() -> tuple[Voice, ...]:
    return (
        Voice("@caller", "x", "test voice that makes BTC calls"),
        Voice("@quiet", "x", "test voice that never claims anything"),
    )


def _providers() -> dict[str, FixtureVoiceProvider]:
    return {
        "x": FixtureVoiceProvider({
            "@caller": [
                _post("@caller", "p1", "BTC breaks out here, easy continuation", days=0),
                _post("@caller", "p2", "BTC still looks strong into the weekly close", days=2),
            ],
            "@quiet": [_post("@quiet", "q1", "nice weather today", days=1)],
        }, platform="x"),
    }


class _CountingChat:
    """A chat seam that emits one bullish BTC claim for posts mentioning BTC, [] otherwise — and counts
    calls so re-extraction (re-spend) is detectable."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _model: str, prompt: str) -> str:
        self.calls += 1
        # Key on the POST TEXT, not "BTC" — the prompt template itself mentions BTC in the schema example.
        if "nice weather" in prompt:
            return "[]"
        return json.dumps([{
            "entity": "BTC", "direction": "up", "horizon": _HORIZON,
            "conviction": 0.8, "quote": "BTC breaks out", "rationale": "momentum",
        }])


class _RisingBars:
    """Ascending daily closes so an 'up' claim resolves as a hit."""

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        bars = []
        for i in range(60):
            p = Decimal(str(round(30000 * (1.05 ** i), 2)))  # +5%/day: clears the resolver's flat band
            bars.append(Bar(ts=_T0 - timedelta(days=10) + timedelta(days=i), open=p, high=p, low=p, close=p, volume=p))
        return bars[-limit:]


def _run(store, chat=None, **kw):
    extractor = ClaimExtractor(chat=chat) if chat is not None else ClaimExtractor(chat=None)
    return run_voices_pass(
        store, panel=_panel(), providers=_providers(), extractor=extractor,
        bars_provider=_RisingBars(), now=_NOW, **kw,
    )


def test_full_pass_stores_posts_claims_scoreboard_and_features(tmp_path):
    store = _store(tmp_path)
    chat = _CountingChat()
    report = _run(store, chat)

    assert report.posts_fetched == 3 and report.posts_new == 3
    assert report.claims_new == 2  # both BTC posts carry one claim each
    assert chat.calls == 3         # every NEW post visits the extractor once

    # Durable post records, deduped by (platform, handle, post_id).
    posts = store.rows("SELECT source FROM market_events WHERE provider = 'voices'")
    assert len(posts) == 3

    # The flat scoreboard: one row per PANEL voice, honest states.
    rows = {r["handle"]: r for r in store.rows("SELECT * FROM voice_scoreboard")}
    assert set(rows) == {"@caller", "@quiet"}
    caller, quiet = rows["@caller"], rows["@quiet"]
    assert caller["n_claims"] == 2 and int(caller["n_resolved"]) >= 1
    assert caller["skill"] is not None and float(caller["hit_rate"]) == 1.0  # rising tape: both calls hit
    assert quiet["n_claims"] == 0 and quiet["skill"] is None  # untested ≠ unskilled: NULL, never 0

    # The two registered PIT features accrued under the social_authority provider.
    feats = store.rows("SELECT symbol, metric FROM alt_data WHERE provider = 'social_authority'")
    metrics = {(r["symbol"], r["metric"]) for r in feats}
    assert ("@caller", "author_authority") in metrics
    assert ("BTC", "authority_weighted_claim_signal") in metrics


def test_rerun_is_free_no_new_posts_no_new_llm_calls(tmp_path):
    store = _store(tmp_path)
    chat = _CountingChat()
    _run(store, chat)
    calls_after_first = chat.calls

    second = _run(store, chat)

    assert second.posts_new == 0 and second.claims_new == 0
    assert chat.calls == calls_after_first  # an already-stored post never re-visits the extractor
    assert len(store.rows("SELECT id FROM voice_claims")) == 2  # no duplicate claim rows either


def test_extraction_budget_caps_llm_spend(tmp_path):
    store = _store(tmp_path)
    chat = _CountingChat()
    report = _run(store, chat, max_extractions=1)
    assert report.posts_extracted == 1 and chat.calls == 1  # the cap bounds the bill, not the cron cadence


def test_keyless_run_degrades_honestly(tmp_path):
    store = _store(tmp_path)
    report = _run(store, chat=None)  # no chat seam → extractor yields nothing

    assert report.posts_new == 3 and report.claims_new == 0
    rows = {r["handle"]: r for r in store.rows("SELECT * FROM voice_scoreboard")}
    assert rows["@caller"]["n_claims"] == 0 and rows["@caller"]["skill"] is None
    assert store.rows("SELECT id FROM alt_data WHERE provider = 'social_authority'") == []


def test_unknown_platform_is_an_error_not_a_crash(tmp_path):
    store = _store(tmp_path)
    report = run_voices_pass(
        store, panel=(Voice("feed", "rss", "no provider injected"),), providers={},
        extractor=ClaimExtractor(chat=None), bars_provider=_RisingBars(), now=_NOW,
    )
    assert report.errors and "no provider" in report.errors[0]
    assert report.scoreboard_rows == 1  # the panel row still renders (honest zeros)
