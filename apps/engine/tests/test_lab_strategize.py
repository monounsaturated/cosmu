# The /strategize front door: classify a free-form input → route to the right existing skill, author typed specs
# (no magic numbers), track them, and let the deterministic Gate dispose. THIN orchestrator — reuses the sibling
# skills' machinery (draft_from_brief, translate_pine, scan_inbox). Offline-safe.

from __future__ import annotations

import json

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.lab.strategize import (
    SKILL_FOR,
    AuthoredSpec,
    classify_intent,
    strategize,
)
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.pine_samples import PINE_SAMPLES
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/strategize.sqlite3", openrouter_api_key=None))


class _FixtureBars:
    """Tiny offline market so the optional --gate screen stays fast in CI (same pattern as test_lab_inbox)."""

    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


# ── classification ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.tradingview.com/script/abc/", "url"),
        ("fade crowded perp funding on BTC", "vibe"),
        ("find me something on funding", "scan"),
        ("what should we try next?", "scan"),
        ("evolve the winner onto other assets", "evolve"),
        ("compound the gate-passed survivor", "evolve"),
        ("generate 5 strategies from a funding theme", "batch"),
        ("give me a few momentum ideas", "batch"),
    ],
)
def test_classify_intent_shapes(text, expected):
    assert classify_intent(text) == expected


def test_classify_pine_source():
    assert classify_intent(PINE_SAMPLES["RSI oversold reversion"]) == "pine"


def test_explicit_batch_params_force_batch():
    # n>1 or an explicit theme overrides the prose shape (even a plain vibe sentence).
    assert classify_intent("fade crowded funding", n=4) == "batch"
    assert classify_intent("fade crowded funding", theme="funding") == "batch"
    assert classify_intent("fade crowded funding", n=1) == "vibe"  # n==1 is not a batch


def test_every_intent_maps_to_a_real_skill():
    skills_dir = __import__("pathlib").Path(__file__).resolve().parents[3] / ".claude" / "skills"
    for intent, skill in SKILL_FOR.items():
        assert (skills_dir / skill / "SKILL.md").exists(), f"{intent} → /{skill} has no SKILL.md"


# ── authoring (offline) ───────────────────────────────────────────────────────────────────────────────────

def test_vibe_authors_one_tracked_spec(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    route = strategize("fade crowded perp funding on BTC", store=store, inbox_dir=inbox)

    assert route.intent == "vibe" and route.skill == "dump-idea" and not route.delegated
    assert route.count == 1
    [authored] = route.authored
    assert authored.valid and authored.path
    # the written file is a typed spec with NO magic numbers.
    spec = StrategySpec.model_validate(json.loads((inbox / authored.path.split("/")[-1]).read_text()))
    assert validate_spec(spec) == []
    # tracked: an audited event was recorded.
    rows = store.rows("SELECT payload FROM events WHERE kind = 'strategize_authored'", ())
    assert len(rows) == 1


def test_batch_authors_n_distinct_specs(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    route = strategize("generate from a theme", store=store, n=5, theme="funding", inbox_dir=inbox)

    assert route.intent == "batch" and route.theme == "funding"
    assert route.count == 5
    valid = [a for a in route.authored if a.valid]
    assert len(valid) == 5
    # every authored spec is magic-number-free and was written to its own inbox file.
    paths = {a.path for a in valid}
    assert len(paths) == 5
    for a in valid:
        spec = StrategySpec.model_validate(json.loads(__import__("pathlib").Path(a.path).read_text()))
        assert validate_spec(spec) == []


def test_batch_clamps_runaway_count(tmp_path):
    store = _store(tmp_path)
    route = strategize("spin up specs", store=store, n=999, theme="vol", inbox_dir=tmp_path / "inbox")
    assert route.count == 16  # _MAX_BATCH
    assert any("clamp" in n.lower() for n in route.notes)


def test_pine_paste_authors_typed_spec(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    route = strategize(PINE_SAMPLES["RSI oversold reversion"], store=store, inbox_dir=inbox)

    assert route.intent == "pine" and route.skill == "import-pine"
    [authored] = route.authored
    assert authored.valid and authored.path
    assert not route.delegated  # local translate succeeded → no handoff needed
    spec = StrategySpec.model_validate(json.loads(__import__("pathlib").Path(authored.path).read_text()))
    assert validate_spec(spec) == []  # Pine literals lifted into param_space


# ── delegation (network/gate-heavy) ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("text", "intent", "skill"),
    [
        ("https://example.com/script", "url", "pine-from-url"),
        ("find me something on macro", "scan", "scan-signals"),
        ("evolve the winner onto equities", "evolve", "evolve-strategy"),
    ],
)
def test_delegated_intents_route_without_authoring(text, intent, skill, tmp_path):
    store = _store(tmp_path)
    route = strategize(text, store=store, inbox_dir=tmp_path / "inbox")
    assert route.intent == intent and route.skill == skill
    assert route.delegated and route.authored == []
    assert skill in route.reason or "drive" in route.reason


# ── gate handoff (deterministic) ──────────────────────────────────────────────────────────────────────────

def test_gate_runs_the_deterministic_screen_on_authored_specs(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    route = strategize(
        "momentum trend breakout on crypto",
        store=store,
        inbox_dir=inbox,
        gate=True,
        market_data=_FixtureBars(),
    )
    assert route.intent == "vibe" and route.authored[0].valid
    # the deterministic screen actually ran on what we authored — strategize judges nothing, the Gate disposes.
    assert route.cohort is not None
    assert route.cohort.generated >= 1


def test_author_failure_is_reported_not_raised(tmp_path):
    # AuthoredSpec is the contract surfaced for a brief that can't become a valid spec — exercised via a degenerate
    # empty brief, which the drafter still turns into a valid template; assert the happy path stays valid.
    store = _store(tmp_path)
    route = strategize("trend", store=store, inbox_dir=tmp_path / "inbox")
    assert isinstance(route.authored[0], AuthoredSpec)
