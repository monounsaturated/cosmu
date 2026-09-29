# The ML-through-natural-language seam: plain-language request → deterministic intent classification → survival
# ranking / feature-importance over REAL persisted outcomes → result JUDGED by the scorer (gate verdict per item)
# but NEVER altering it. No LLM in the scorer/gate path; offline + reproducible.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.lab.ml import classify_intent, run_ml_request
from cosmu.research.fixtures import edge_bearing_screen_market


class _FixtureBars:
    # Small, fast offline market: 2 catalog symbols x ~280 edge-bearing bars (enough for the screen's 80-bar
    # floor + holdout split) so finder grids stay quick in CI.
    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _store_with_outcomes(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/ml.sqlite3", openrouter_api_key=None))
    StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars()).find(seed_orb_fvg_spec(), max_variants=8)
    return store


def test_intent_classification_is_deterministic():
    assert classify_intent("rank survivors by edge-persistence") == "survival_ranking"
    assert classify_intent("which features matter most") == "feature_importance"
    assert classify_intent("anything else entirely") == "survival_ranking"  # safe default


def test_survival_ranking_is_a_permutation_judged_by_the_gate(tmp_path):
    store = _store_with_outcomes(tmp_path)
    res = run_ml_request(store, "rank the survivors by edge persistence")
    assert res.task == "survival_ranking"
    # ranking is ordered by score descending (the ML orders; it never vetoes)
    scores = [i.score for i in res.ranking]
    assert scores == sorted(scores, reverse=True)
    # each item carries the DETERMINISTIC gate verdict (judged) — the ML reports it, never sets it
    assert all(isinstance(i.gate_passed, bool) for i in res.ranking)


def test_feature_importance_returns_weights(tmp_path):
    store = _store_with_outcomes(tmp_path)
    res = run_ml_request(store, "which features matter for survival?")
    assert res.task == "feature_importance"
    assert res.feature_importance
    # weights sorted by absolute magnitude (importance ordering)
    mags = [abs(w.weight) for w in res.feature_importance]
    assert mags == sorted(mags, reverse=True)


def test_no_llm_no_network_required(tmp_path):
    # With no key the seam still runs fully (deterministic intent + cold-start/trained heuristic). The note makes
    # the no-LLM path explicit, and nothing here touches the scorer/gate internals.
    store = _store_with_outcomes(tmp_path)
    res = run_ml_request(store, "rank survivors", llm_enabled=False)
    assert res.llm.startswith("off")
    assert any("deterministic" in n for n in res.notes)
