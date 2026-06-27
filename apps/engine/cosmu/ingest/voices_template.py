# intent: the LLM-VOICES/AUTHORITY LANE TEMPLATE runner — a clean, minimal, MOCKABLE scaffold the operator EXTENDS
# in a future chat (see docs/epics/llm-lane-template.md). It wraps the real `run_voices_pass` (ingest/voices_pass.py)
# with TWO modes and the RATCHET defaults:
#   * MOCK / offline mode (the DEFAULT — what CI and the cron run): canned posts → a deterministic in-process claim
#     extractor → fake bars. NO network, NO LLM, $0. The whole Phase-0..3 pipeline runs and is fully testable.
#   * LIVE-cheap mode (opt-in behind VOICES_LIVE_ENABLED=1): keyless Reddit/RSS retrieval + the OpenRouter `:free`
#     claim extractor (OPENROUTER_FREE_MODEL). Still ~$0 (`:free` does not draw the OpenRouter credit) and still
#     observe-only — it PROPOSES + SCORES; the Gate alone funds (no track/position/order anywhere on this path).
# inputs: an injectable Store + the env flag; outputs: a VoicesPassReport + the durable scoreboard/PIT features.
# invariants: OBSERVE-ONLY / zero-capital; mock is the safe default so a cron tick can never spend or block; the
# model id is the single swappable RATCHET constant; everything is deterministic + offline-testable.
# `python3 -m cosmu.ingest.voices_template` (mock) · `VOICES_LIVE_ENABLED=1 python3 -m cosmu.ingest.voices_template`.

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings, get_settings
from cosmu.config.voices import (
    VOICE_PANEL,
    VOICES_LIVE_ENABLED_ENV,
    Voice,
)
from cosmu.data.market import Bar, MarketDataProvider
from cosmu.data.sources.voices import FixtureVoiceProvider, VoicePost
from cosmu.ingest.voices_pass import VoicesPassReport, run_voices_pass
from cosmu.knowledge.store import Store
from cosmu.mind.claims import ClaimExtractor

# --------------------------------------------------------------------------------------------------------------
# The MOCK fixtures — a tiny, self-contained, deterministic world so the whole lane runs with no network/LLM.
# Designed so the scoreboard SEPARATES a known SNIPER (early + correct) from a SPAMMER (loud + base-rate): the
# canned chat seam below turns each post into a typed claim, and the rising mock bars make the sniper's calls hit.
# --------------------------------------------------------------------------------------------------------------

# A fixed clock so the mock pass is reproducible. NOW sits past the claims' horizon AND inside the signal window.
MOCK_T0 = datetime(2024, 1, 1, tzinfo=UTC)
MOCK_NOW = MOCK_T0 + timedelta(days=20)

# Two canned voices mirroring the two ARCHETYPES the scoreboard must tell apart (NOT the production panel — this is
# the offline test world). @mock_sniper makes a small number of EARLY, correct BTC calls; @mock_spammer fires the
# same direction constantly (loud, reproduces the drift, beats no base rate).
MOCK_SNIPER = Voice("@mock_sniper", "x", "MOCK: an early, correct caller — the skill archetype")
MOCK_SPAMMER = Voice("@mock_spammer", "x", "MOCK: a loud constant caller — the base-rate/volume archetype")
MOCK_PANEL: tuple[Voice, ...] = (MOCK_SNIPER, MOCK_SPAMMER)


def _mock_post(handle: str, post_id: str, text: str, *, days: int) -> VoicePost:
    ts = MOCK_T0 + timedelta(days=days)
    return VoicePost(platform="x", handle=handle, post_id=post_id, text=text, ts=ts, available_at=ts)


def mock_providers() -> dict[str, FixtureVoiceProvider]:
    """Canned timelines (no network). The sniper posts a couple of dated BTC calls; the spammer posts many."""
    return {
        "x": FixtureVoiceProvider(
            {
                MOCK_SNIPER.handle: [
                    _mock_post(MOCK_SNIPER.handle, "snipe1", "BTC breaks out here — continuation higher", days=0),
                    _mock_post(MOCK_SNIPER.handle, "snipe2", "BTC still strong into the weekly close", days=2),
                ],
                MOCK_SPAMMER.handle: [
                    _mock_post(MOCK_SPAMMER.handle, f"spam{d}", "BTC up only, more upside ahead", days=d)
                    for d in range(0, 10, 2)
                ],
            },
            platform="x",
        ),
    }


class MockChat:
    """A deterministic, in-process claim 'LLM' — NO network, NO spend. Emits one bullish BTC claim for any post
    that mentions BTC, [] otherwise. Counts calls so a test can prove re-runs do not re-extract (dedup → $0)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _model_id: str, prompt: str) -> str:
        self.calls += 1
        if "BTC" not in prompt.upper() or "nice weather" in prompt.lower():
            return "[]"
        return json.dumps(
            [{"entity": "BTC", "direction": "up", "horizon": "1d", "conviction": 0.8,
              "quote": "BTC up", "rationale": "momentum"}]
        )


class MockRisingBars(MarketDataProvider):
    """Ascending daily closes so the canned 'up' claims RESOLVE as hits — the mock world where skill is earned.
    Offline, deterministic, no network. (A real pass uses default_crypto_reference instead.)"""

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        bars: list[Bar] = []
        start = MOCK_T0 - timedelta(days=10)
        for i in range(60):
            price = Decimal(str(round(30000 * (1.03 ** i), 2)))  # +3%/day clears the resolver's flat band
            bars.append(Bar(ts=start + timedelta(days=i), open=price, high=price, low=price,
                            close=price, volume=price))
        return bars[-limit:] if limit and len(bars) > limit else bars


# --------------------------------------------------------------------------------------------------------------
# The runner — mode selection + the two assembled passes.
# --------------------------------------------------------------------------------------------------------------


def live_enabled(env: dict[str, str] | None = None) -> bool:
    """LOCKED default: mock unless VOICES_LIVE_ENABLED is explicitly truthy. So a cron tick / CI run is $0 and
    never blocks, and live-cheap retrieval is a deliberate opt-in."""
    env = env if env is not None else dict(os.environ)
    return (env.get(VOICES_LIVE_ENABLED_ENV, "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def run_mock_pass(
    store: Store,
    *,
    panel: tuple[Voice, ...] = MOCK_PANEL,
    chat: MockChat | None = None,
    now: datetime = MOCK_NOW,
    **kwargs,
) -> VoicesPassReport:
    """Run the FULL Phase-0..3 pipeline on the canned mock world — NO network, NO LLM, $0. This is the CI/test
    default and the safe cron path. Returns the real VoicesPassReport; the durable scoreboard + PIT features land
    exactly as in a live pass, so the mock is a faithful end-to-end exercise of the lane."""
    chat = chat if chat is not None else MockChat()
    return run_voices_pass(
        store,
        panel=panel,
        providers=mock_providers(),
        extractor=ClaimExtractor(chat=chat),
        bars_provider=MockRisingBars(),
        now=now,
        **kwargs,
    )


def run_live_pass(store: Store, *, settings: Settings | None = None, **kwargs) -> VoicesPassReport:
    """Run the lane LIVE-cheap on the pre-registered KEYLESS panel (VOICE_PANEL): keyless Reddit/RSS retrieval +
    the OpenRouter `:free` claim extractor (~$0). Still observe-only. Uses the real providers/extractor/bars built
    from settings inside run_voices_pass — we just pass the registered panel and let the defaults resolve."""
    _ = settings  # reserved for future explicit overrides; run_voices_pass resolves settings itself
    return run_voices_pass(store, panel=VOICE_PANEL, **kwargs)


def run_template(store: Store | None = None, *, env: dict[str, str] | None = None) -> VoicesPassReport:
    """The single entry the cron calls. Picks MOCK (default, $0, no network) or LIVE-cheap (opt-in via the env
    flag). Observe-only either way — the Gate alone funds."""
    store = store or Store(get_settings())
    if live_enabled(env):
        return run_live_pass(store)
    return run_mock_pass(store)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(
        description="Run the LLM-voices/authority lane TEMPLATE (mock by default; VOICES_LIVE_ENABLED=1 for live-cheap)."
    ).parse_args(argv)
    mode = "LIVE-cheap (keyless retrieval + OpenRouter :free)" if live_enabled() else "MOCK ($0, no network/LLM)"
    report = run_template()
    print(
        f"VOICES TEMPLATE [{mode}] — voices={report.voices} posts={report.posts_fetched} "
        f"(new={report.posts_new}, extracted={report.posts_extracted}) "
        f"claims new={report.claims_new}/total={report.claims_total} "
        f"scoreboard={report.scoreboard_rows} features={report.features_written} errors={len(report.errors)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
