"""Phase 1.5: the aggregation-edge ablation gate + the LLM news adapter."""

from datetime import UTC, datetime

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.config.settings import Settings
from cosmu.data.altdata import NewsItem
from cosmu.ingest.standardize import TRANSFORM_VERSION, StandardizedNews, standardize_headline, standardize_news
from cosmu.knowledge.store import Store
from cosmu.research.fixtures import synthetic_ablation_inputs
from cosmu.research.gate import evaluate_ablation


def _store(tmp_path, name="abl") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def test_ablation_passes_when_alt_data_adds_edge(tmp_path):
    store = _store(tmp_path, "pass")
    market, alt, news = synthetic_ablation_inputs(edge=True, seed=7)
    v = evaluate_ablation(market, alt, news, store)
    assert v.decision == "PASS"
    assert v.alt_return > v.price_only_return > v.buy_and_hold_return  # alt beats price-only beats buy&hold
    assert v.alt_dsr >= 0.95
    assert v.cscv_pbo < 0.5
    assert v.regimes_positive >= 2
    # the drop-one report ranks the paying source first (news, by construction)
    assert v.drop_one[0].source == "news"
    assert v.drop_one[0].delta > 0
    # every arm/variant attempt is counted in the global trial ledger
    assert len(store.rows("SELECT 1 FROM trials")) == v.attempts
    assert v.attempts <= v.bar["attempt_budget"]


def test_ablation_stops_without_edge(tmp_path):
    store = _store(tmp_path, "stop")
    market, alt, news = synthetic_ablation_inputs(edge=False, seed=7)
    v = evaluate_ablation(market, alt, news, store)
    assert v.decision == "STOP"
    assert v.reasons


def test_ablation_is_deterministic(tmp_path):
    a_market, a_alt, a_news = synthetic_ablation_inputs(edge=True, seed=7)
    b_market, b_alt, b_news = synthetic_ablation_inputs(edge=True, seed=7)
    a = evaluate_ablation(a_market, a_alt, a_news, _store(tmp_path, "da"))
    b = evaluate_ablation(b_market, b_alt, b_news, _store(tmp_path, "db"))
    assert (a.decision, a.alt_dsr, a.cscv_pbo, a.alt_return) == (b.decision, b.alt_dsr, b.cscv_pbo, b.alt_return)


def test_news_adapter_cache_hit_avoids_second_call():
    ts = datetime(2023, 1, 1, tzinfo=UTC)
    items = [NewsItem(ts=ts, available_at=ts, headline="Bitcoin surges as ETF inflows hit record")] * 3
    counter: dict[str, int] = {}

    def fake_llm(_headline: str) -> StandardizedNews:
        return StandardizedNews(event_type="bullish", sentiment=1.0, confidence=1.0)

    points = standardize_news(items, llm=fake_llm, counter=counter)
    assert len(points) == 3
    assert counter["calls"] == 1  # 3 identical headlines → one compute (content-hash cache)


def test_news_adapter_offline_is_deterministic():
    assert standardize_headline("Bitcoin surges as ETF inflows hit record").sentiment > 0
    assert standardize_headline("Exchange hack triggers a broad selloff").sentiment < 0
    assert standardize_headline("markets quiet today").sentiment == 0.0


def test_news_sentiment_feature_pins_transform_version():
    feature = next(f for f in FEATURE_REGISTRY if f.name == "news_sentiment")
    assert feature.transform_version == TRANSFORM_VERSION
