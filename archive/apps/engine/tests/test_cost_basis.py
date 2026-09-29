# Cost-basis recompute — offline, deterministic (no network, no keys, no LLM). Proves the fee-basis selector's
# data source: a stored crypto/binance version is re-screened under No-fee + each venue's REAL fee+depth, the
# no-fee baseline is the gross ceiling, cheaper venues keep more edge, per-venue depth is carried through, and
# an unknown version / non-crypto spec returns an HONEST available=False (never a fabricated number).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow
from cosmu.research.cost_basis import compute_version_cost_basis
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)


class _Bars:
    """Fake market provider: every requested symbol resolves to the one canned series (so the core-slice loop
    fills) — same injection seam StrategyFinder uses in tests."""

    def __init__(self, market: dict[str, list[Bar]]) -> None:
        self._m = market

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._m.get(symbol, next(iter(self._m.values())))[-limit:]


def _trending_market(n: int = 320) -> dict[str, list[Bar]]:
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 100.0
    for i in range(n):
        step = -0.02 if i % 7 == 0 else 0.015
        open_ = price
        price = price * (1 + step)
        d = lambda x: Decimal(str(round(x, 6)))  # noqa: E731
        bars.append(
            Bar(ts=t0 + timedelta(days=i), open=d(open_), high=d(max(open_, price) * 1.004),
                low=d(min(open_, price) * 0.996), close=d(price), volume=d(5_000_000.0))
        )
    return {"BTCUSDT": bars}


def _momentum_spec(venues: list[str], asset: str = "crypto") -> tuple[StrategySpec, dict[str, float]]:
    spec = StrategySpec(
        name=f"cost-basis test {asset}",
        rationale="Long when short-window return is positive; small take so it round-trips often and cost bites.",
        universe=UniverseSelector(venues=venues, asset_classes=[asset], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=8),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=5, max_position_pct=0.2, conviction=0.9),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=2, hi=20, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.05),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.02, hi=0.2),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
        },
    )
    params = {"mom_lookback": 2.0, "mom_floor": 0.0, "stop": 0.05, "take": 0.04, "time_stop": 4.0, "config_tag": "v1"}
    return spec, params


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_version(store: Store, spec: StrategySpec, params: dict) -> str:
    sid = store.insert("strategies", {"name": spec.name, "thesis": spec.rationale, "origin": "finder", "created_at": utcnow()})
    return store.insert(
        "strategy_versions",
        {
            "strategy_id": sid, "parent_id": None, "spec": spec.model_dump(mode="json"),
            "generated_code": "compiled", "code_hash": "hash-" + spec.name, "params": params,
            "mutation_operator": None, "mutation_rationale": None, "origin": "finder",
            "status": "screened", "created_at": utcnow(),
        },
    )


def test_cost_basis_recomputes_per_venue(tmp_path) -> None:
    store = _store(tmp_path, "cb")
    spec, params = _momentum_spec(["binance"])
    vid = _seed_version(store, spec, params)
    report = compute_version_cost_basis(
        store, vid, settings=store.settings, venues=["binance", "kraken", "coinbase"], market_data=_Bars(_trending_market())
    )
    assert report.available is True, report.reason
    by = {i.basis: i for i in report.items}
    # The no-fee baseline is present, zero-cost, and equals the gross ceiling.
    assert "none" in by and by["none"].venue_id is None and by["none"].fee_bps == 0.0
    assert report.gross_return_pct == by["none"].net_return_pct
    assert all(by["none"].net_return_pct >= it.net_return_pct for it in report.items)
    # Every requested venue is priced; the cheaper venue keeps strictly more (or equal) edge.
    assert {"binance", "kraken", "coinbase"} <= set(by)
    assert by["binance"].net_return_pct >= by["kraken"].net_return_pct >= by["coinbase"].net_return_pct
    # Per-venue DEPTH (not just fee) is carried through: Coinbase's wider book shows a larger half-spread.
    assert by["coinbase"].slippage_bps > by["binance"].slippage_bps
    assert by["binance"].num_trades > 0


def test_cost_basis_defaults_to_the_spec_venue(tmp_path) -> None:
    store = _store(tmp_path, "cbdef")
    spec, params = _momentum_spec(["binance"])
    vid = _seed_version(store, spec, params)
    report = compute_version_cost_basis(store, vid, settings=store.settings, market_data=_Bars(_trending_market()))
    assert report.available is True
    bases = {i.basis for i in report.items}
    assert bases == {"none", "binance"}  # no venues arg → the spec's own venue + the no-fee baseline


def test_cost_basis_unknown_version_is_honest(tmp_path) -> None:
    store = _store(tmp_path, "cbunknown")
    report = compute_version_cost_basis(store, "nope", settings=store.settings)
    assert report.available is False and report.reason and not report.items


def test_cost_basis_non_crypto_spec_is_honest(tmp_path) -> None:
    store = _store(tmp_path, "cbeq")
    spec, params = _momentum_spec(["ibkr"], asset="equity")
    vid = _seed_version(store, spec, params)
    report = compute_version_cost_basis(store, vid, settings=store.settings, market_data=_Bars(_trending_market()))
    assert report.available is False and "crypto/binance" in (report.reason or "")
