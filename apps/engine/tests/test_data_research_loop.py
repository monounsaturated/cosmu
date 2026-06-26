"""The self-sustained data + auto-research loop: a one-pass free-data ingest CLI fills the append-only
point-in-time store, and a bounded auto-research pass runs the deterministic cross-asset gate against it —
no human in the loop, ZERO LLM in the gate/scoring path (the news LLM is ingest-only, cached)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import cosmu.research.gate as gate_mod
from cosmu.config.settings import Settings
from cosmu.data.altdata import (
    AltDataPoint,
    AltDataStore,
    FixtureAltDataProvider,
    FixtureNewsProvider,
    NewsItem,
)
from cosmu.ingest.run import Providers, run_once
from cosmu.knowledge.store import Store
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.research.gate import CrossAssetVerdict
from cosmu.research.loop import auto_research_pass

_START = datetime(2023, 1, 1, tzinfo=UTC)
_CRYPTO = ("BTCUSDT", "ETHUSDT")


def _store(tmp_path, name="loop") -> Store:
    # no openrouter key → the whole gate runs offline; the LLM (if any) is ingest-only.
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _series(metric: str, n: int = 40, base: float = 1.0) -> list[AltDataPoint]:
    return [AltDataPoint(ts=_START + timedelta(days=i), available_at=_START + timedelta(days=i), value=base + i * 0.01) for i in range(n)]


def _news(n: int = 40) -> list[NewsItem]:
    return [NewsItem(ts=_START + timedelta(days=i), available_at=_START + timedelta(days=i), headline="Bitcoin surges as ETF inflows hit record") for i in range(n)]


def _fixture_providers() -> Providers:
    """Real-provider-shaped FIXTURES so a pass runs fully offline. Each provider keys off (symbol, metric)
    or (MARKET, native-id) exactly like the real free APIs the run CLI defaults to."""
    funding = FixtureAltDataProvider({(s, "funding_rate"): _series("funding_rate", base=0.0001) for s in _CRYPTO})
    feargreed = FixtureAltDataProvider({("MARKET", "fear_greed"): _series("fear_greed", base=50.0)})
    putcall = FixtureAltDataProvider({("MARKET", "putcall_ratio"): _series("putcall_ratio", base=0.9)})
    # The two market-wide cross-asset transfer series, keyed by their NATIVE source ids (mapped to the
    # semantic risk_on / macro_regime names at ingest, as ingest_market_wide_numeric does).
    fred = FixtureAltDataProvider({("MARKET", "T10Y2Y"): _series("macro_regime", base=0.5)})
    polymarket = FixtureAltDataProvider({("MARKET", "risk-on"): _series("risk_on", base=0.6)})
    news = FixtureNewsProvider({s: _news() for s in _CRYPTO})
    # Cross-asset daily levels keyed by their SEMANTIC names under MARKET (StooqDailyProvider maps them).
    multiasset = FixtureAltDataProvider({("MARKET", m): _series(m, base=100.0) for m in ("gold_xau", "spx_index", "eurusd")})
    return Providers(
        funding=funding, feargreed=feargreed, news=news, fred=fred, polymarket=polymarket,
        putcall=putcall, multiasset=multiasset,
        fred_series="T10Y2Y", polymarket_token="risk-on",
    )


def _far_future() -> datetime:
    return datetime(2099, 1, 1, tzinfo=UTC)


# --- (a) run_once with injected FIXTURE providers ---------------------------------------------


def test_run_once_populates_store_with_positive_counts(tmp_path, monkeypatch):
    # poison the LLM seam (instructor/LLM path); news standardization must use the cached offline lexicon.
    import cosmu.ingest.pipeline as pipeline_mod

    real = pipeline_mod.standardize_news
    calls = {"n": 0}

    def _counted(items, **kwargs):  # noqa: ANN001
        calls["n"] += 1
        kwargs.setdefault("llm", None)  # never pass an LLM
        assert kwargs.get("llm") is None, "the gate/ingest must not invoke an LLM beyond cached lexicon"
        return real(items, **kwargs)

    monkeypatch.setattr(pipeline_mod, "standardize_news", _counted)

    astore = AltDataStore(root=tmp_path / "alt")
    counts = run_once(astore, symbols=list(_CRYPTO), providers=_fixture_providers())

    for source in ("funding_rate", "fear_greed", "news_sentiment", "macro_regime", "pm_risk_on", "putcall_ratio"):
        assert counts[source] > 0, f"{source} should ingest > 0 points from fixtures"
    # the cross-asset transfer series landed under their SEMANTIC names at the MARKET key
    assert astore.read_all("polymarket", "MARKET", "pm_risk_on")
    assert astore.read_all("fred", "MARKET", "macro_regime")
    assert calls["n"] >= 1  # news standardization ran (offline, no LLM)


def test_run_once_is_point_in_time_and_idempotent_in_view(tmp_path):
    astore = AltDataStore(root=tmp_path / "alt")
    run_once(astore, symbols=list(_CRYPTO), providers=_fixture_providers())
    before = astore.read_asof("polymarket", "MARKET", "pm_risk_on", _far_future())
    run_once(astore, symbols=list(_CRYPTO), providers=_fixture_providers())  # re-run a scheduled pass
    after = astore.read_asof("polymarket", "MARKET", "pm_risk_on", _far_future())
    # append-only re-run never changes the point-in-time VIEW (latest-revision-per-ts is identical)
    assert [(p.ts, p.value) for p in before] == [(p.ts, p.value) for p in after]


def test_run_once_one_dead_source_does_not_abort_the_pass(tmp_path):
    class _Boom:
        def fetch_series(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            raise RuntimeError("no network")

    providers = _fixture_providers()
    providers.funding = _Boom()  # type: ignore[assignment]
    astore = AltDataStore(root=tmp_path / "alt")
    counts = run_once(astore, symbols=list(_CRYPTO), providers=providers)
    assert counts["funding_rate"] == 0  # dead source → 0 count, logged
    assert counts["pm_risk_on"] > 0  # the rest of the pass still completed


# --- (b) auto_research_pass with fixtures, ZERO LLM in the gate path ---------------------------


def _ingest_live_store(tmp_path) -> AltDataStore:
    """Fill an append-only store from the cross-asset fixtures via run_once, so the loop takes its LIVE
    (StoreBackedAltProvider) branch with the two transfer series present."""
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    crypto = list(market_by_class["crypto"])
    all_symbols = [s for cls in market_by_class.values() for s in cls]
    # Build a Providers set whose native ids map onto the fixture's MARKET series. The polymarket provider's
    # NATIVE token id is "risk_on" (an arbitrary source id); run_once banks it under the canonical stored name
    # pm_risk_on. The synthetic fixture exposes the series under its canonical name pm_risk_on, so the poly
    # fixture is seeded from that and keyed by the native token id.
    fred = FixtureAltDataProvider({("MARKET", "macro_regime"): alt.fetch_series("MARKET", "macro_regime", limit=10**9)})
    poly = FixtureAltDataProvider({("MARKET", "risk_on"): alt.fetch_series("MARKET", "pm_risk_on", limit=10**9)})
    providers = Providers(
        funding=alt, feargreed=alt, news=FixtureNewsProvider({s: news.fetch_news(s, limit=10**9) for s in all_symbols}),
        fred=fred, polymarket=poly, fred_series="macro_regime", polymarket_token="risk_on",
    )
    astore = AltDataStore(root=tmp_path / "alt")
    run_once(astore, symbols=crypto, providers=providers)
    return astore


def test_auto_research_pass_runs_gate_persists_and_emits(tmp_path):
    store = _store(tmp_path, "research")
    astore = _ingest_live_store(tmp_path)
    verdict = auto_research_pass(store, alt_store=astore)

    assert isinstance(verdict, CrossAssetVerdict)
    assert verdict.decision in ("PASS", "STOP-narrow")
    assert verdict.data_source == "live"  # store had risk_on + macro_regime → live branch
    # persisted a gate_verdicts row + a cross_asset_gate_run event
    assert store.rows("SELECT 1 FROM gate_verdicts WHERE data_source = 'live'")
    assert store.rows("SELECT 1 FROM events WHERE kind = 'cross_asset_gate_run'")


def test_auto_research_pass_synthetic_fallback_when_store_empty(tmp_path):
    store = _store(tmp_path, "synthfallback")
    astore = AltDataStore(root=tmp_path / "empty")  # no transfer series ingested
    verdict = auto_research_pass(store, alt_store=astore)
    assert verdict.data_source == "synthetic"
    assert store.rows("SELECT 1 FROM gate_verdicts WHERE data_source = 'synthetic'")


def test_auto_research_pass_calls_no_llm_in_the_gate_path(tmp_path, monkeypatch):
    """Poison the standardize seam like tests/test_cross_asset_gate.py does: if the gate touches news
    standardization, it explodes. The LLM ran only at ingest; the gate reads pre-standardized numerics."""
    store = _store(tmp_path, "noLLM")
    astore = _ingest_live_store(tmp_path)  # news already standardized into the store at ingest

    def _boom(*_a, **_k):
        raise AssertionError("LLM/standardize_news must not run in the gate/scoring path")

    monkeypatch.setattr(gate_mod, "standardize_news", _boom)
    verdict = auto_research_pass(store, alt_store=astore)
    assert verdict.data_source == "live"
    assert isinstance(verdict, CrossAssetVerdict)


# --- (c) ingest is ROBUST + routed OFF the leaky cross-asset gate -------------------------------


def test_ingest_cron_does_not_run_the_leaky_cross_asset_gate(tmp_path, monkeypatch):
    """The ingest cron path (cross_asset_gate=False) must ingest + persist WITHOUT touching the no-FDR/trials=5
    cross-asset ablation the audit flagged as leaky. If the gate ran, this would explode."""
    import cosmu.research.loop as loop_mod

    store = _store(tmp_path, "ingestonly")
    astore = AltDataStore(root=tmp_path / "alt")

    def _boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("the leaky cross-asset gate must NOT run on the ingest cron path")

    monkeypatch.setattr(loop_mod, "evaluate_cross_asset_ablation", _boom)

    verdict = auto_research_pass(store, ingest=True, cross_asset_gate=False, alt_store=astore, providers=_fixture_providers())
    assert verdict is None  # ingest-only → no verdict, and the gate was never reached
    # ingest still completed + persisted the transfer series into the store
    assert astore.read_all("polymarket", "MARKET", "pm_risk_on")
    assert astore.read_all("fred", "MARKET", "macro_regime")
    # no leaky gate_verdicts row was written by this ingest-only pass
    assert not store.rows("SELECT 1 FROM gate_verdicts")


def test_ingest_completes_and_persists_even_if_cross_asset_gate_raises(tmp_path, monkeypatch):
    """The cross-asset gate step is best-effort: a Supabase-hiccup-style failure during the gate must be caught
    + logged and must NEVER abort the ingest step, which has already persisted independently."""
    import cosmu.research.loop as loop_mod

    store = _store(tmp_path, "gateboom")
    astore = AltDataStore(root=tmp_path / "alt")

    def _boom(*_a, **_k):  # noqa: ANN002, ANN003 - mimic a transient connect/fee-read hiccup mid-gate
        raise RuntimeError("supabase connect() hiccup during a fee-read")

    monkeypatch.setattr(loop_mod, "evaluate_cross_asset_ablation", _boom)

    # gate enabled, but it raises → the pass still returns (None) instead of aborting the ingest work
    verdict = auto_research_pass(store, ingest=True, cross_asset_gate=True, alt_store=astore, providers=_fixture_providers())
    assert verdict is None  # the leaky gate failed best-effort; the pass did not crash
    # the ingest step persisted independently of the failing gate step
    assert astore.read_all("polymarket", "MARKET", "pm_risk_on")
    assert astore.read_all("fred", "MARKET", "macro_regime")
    # the failed gate persisted no verdict row
    assert not store.rows("SELECT 1 FROM gate_verdicts")
