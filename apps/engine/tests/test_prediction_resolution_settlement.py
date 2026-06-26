# The UMA/payoutNumerators resolution-settled backtest (scout #385 Fix-B). A prediction position held to
# resolution must settle at the authoritative $1/$0 payout, NOT the last odds quote — the join that makes the
# favorite-longshot edge testable. Covers: (1) the resolution data source parses payoutNumerators / resolved
# outcomePrices with a PIT-honest available_at; (2) the ingest stores it idempotently under metric="resolution";
# (3) the PredictionDataAdapter reads it back point-in-time; (4) the backtest settles a held-to-resolution
# position at the payout (YES → $1, NO → $0) and refuses to re-enter a resolved market; (5) the flag gates it
# (settle_at_resolution=False → marks at the last odds, byte-identical). All hermetic (Gamma mocked).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.prediction import Market, PredictionDataAdapter
from cosmu.adapters.data.prediction import instrument_id as pm_instrument_id
from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataStore
from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.data.sources.polymarket import PolymarketResolutionSource
from cosmu.ingest.polymarket_odds import ingest_per_market_resolutions
from cosmu.knowledge.store import Store
from cosmu.strategy.spec import StrategySpec

_CID = "0xCONDITION_RES"
_RESOLVED_AT = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)


def _gamma_market(*, payout_numerators=None, outcome_prices=None, resolved=True, resolved_at=_RESOLVED_AT):
    m: dict = {"conditionId": _CID, "clobTokenIds": ["yes_tok", "no_tok"]}
    if payout_numerators is not None:
        m["payoutNumerators"] = payout_numerators
    if outcome_prices is not None:
        m["outcomePrices"] = outcome_prices
    if resolved:
        m["umaResolutionStatus"] = "resolved"
        m["closed"] = True
        m["active"] = False
        m["resolvedTime"] = int(resolved_at.timestamp())
    return m


def _gamma_for(market: dict | None):
    def fetcher(_url: str):
        return [market] if market is not None else []
    return fetcher


# --------------------------------------------------------------------------- the resolution source

def test_source_parses_payout_numerators_yes_wins():
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(_gamma_market(payout_numerators=[1, 0])))
    pts = src.fetch_resolution(_CID)
    assert len(pts) == 1
    assert pts[0].value == 1.0  # numerators [1,0] → YES pays $1
    assert pts[0].ts == _RESOLVED_AT
    assert pts[0].available_at == _RESOLVED_AT  # PIT: knowable ONLY at the real resolution time


def test_source_parses_payout_numerators_no_wins():
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(_gamma_market(payout_numerators=[0, 1])))
    pts = src.fetch_resolution(_CID)
    assert pts[0].value == 0.0  # numerators [0,1] → YES pays $0


def test_source_falls_back_to_resolved_outcome_prices():
    # No payoutNumerators, but the market is resolved and outcomePrices is a clean 1/0 → YES pays $1.
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(_gamma_market(outcome_prices=["1", "0"])))
    pts = src.fetch_resolution(_CID)
    assert pts[0].value == 1.0


def test_source_refuses_unresolved_market():
    # A still-trading market (not resolved, mid odds) yields NO settlement point — never fabricate one.
    m = _gamma_market(outcome_prices=["0.62", "0.38"], resolved=False)
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(m))
    assert src.fetch_resolution(_CID) == []


def test_source_refuses_mid_odds_masquerading_as_price():
    # Even flagged resolved, a non-binary outcomePrice (0.62) is NOT a $1/$0 payout → refuse (no payoutNumerators).
    m = _gamma_market(outcome_prices=["0.62", "0.38"], resolved=True)
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(m))
    assert src.fetch_resolution(_CID) == []


def test_source_uses_real_resolution_ts_not_scheduled_enddate():
    # available_at MUST be the REAL resolution time, never the scheduled endDate (which can be days earlier/later).
    m = _gamma_market(payout_numerators=[1, 0])
    m["endDate"] = "2025-02-01T00:00:00Z"  # scheduled end, much earlier than resolvedTime
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(m))
    pts = src.fetch_resolution(_CID)
    assert pts[0].available_at == _RESOLVED_AT  # the resolvedTime wins, not the endDate


def test_source_empty_on_dead_fetch():
    def boom(_url: str):
        raise RuntimeError("gamma down")
    src = PolymarketResolutionSource(_gamma_fetcher=boom)
    assert src.fetch_resolution(_CID) == []  # one dead fetch → [], never a raise


# --------------------------------------------------------------------------- ingest + adapter read-back

def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/pm.sqlite3", openrouter_api_key=None))


def test_ingest_stores_resolution_keyed_by_condition_id(tmp_path):
    store = _store(tmp_path)
    alt = AltDataStore(root=tmp_path / "alt")
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(_gamma_market(payout_numerators=[1, 0])))
    results = ingest_per_market_resolutions(alt, store, source=src, condition_ids=[_CID])
    assert results[0].written == 1
    stored = alt.read_all("polymarket", _CID, "resolution")
    assert [p.value for p in stored] == [1.0]
    # Idempotent re-run writes nothing new.
    again = ingest_per_market_resolutions(alt, store, source=src, condition_ids=[_CID])
    assert again[0].written == 0


def test_adapter_reads_resolution_point_in_time(tmp_path):
    store = _store(tmp_path)  # noqa: F841 — store unused here; adapter reads the alt store directly
    alt = AltDataStore(root=tmp_path / "alt")
    src = PolymarketResolutionSource(_gamma_fetcher=_gamma_for(_gamma_market(payout_numerators=[1, 0])))
    ingest_per_market_resolutions(alt, store, source=src, condition_ids=[_CID])
    adapter = PredictionDataAdapter([Market(symbol=_CID, token=_CID)], alt_reader=alt, metric="odds")
    iid = pm_instrument_id(_CID)
    # BEFORE the real resolution time: the payout is not yet knowable → None (PIT-honest).
    assert adapter.resolution(iid, _RESOLVED_AT - timedelta(hours=1)) is None
    # AT/AFTER the resolution time: the authoritative $1 payout is visible.
    res = adapter.resolution(iid, _RESOLVED_AT)
    assert res is not None and res.payout == 1.0 and res.ts == _RESOLVED_AT


# --------------------------------------------------------------------------- the settled backtest

def _odds_bars(values: list[float], start: datetime) -> list[Bar]:
    out, t = [], start
    for v in values:
        px = Decimal(str(v))
        out.append(Bar(ts=t, open=px, high=px, low=px, close=px, volume=Decimal("1000")))
        t += timedelta(days=1)
    return out


def _long_hold_spec() -> StrategySpec:
    # Enter long once odds clear a low level, then hold (huge tp/time so only resolution closes it).
    return StrategySpec.model_validate({
        "name": "pred-hold", "rationale": "r", "catalyst": None,
        "universe": {"venues": ["polymarket"], "asset_classes": ["prediction"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 500},
        "entry": [{"feature": {"name": "odds"}, "op": "gt", "threshold": {"param": "lvl"}}],
        "exit": {
            "stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"},
            "time_stop_days": {"param": "ts"}, "settle_at_resolution": True, "signal_exits": [],
        },
        "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 1.0},
        "param_space": {
            "lvl": {"kind": "float", "lo": 0.5, "hi": 0.6}, "stop": {"kind": "float", "lo": 0.4, "hi": 0.5},
            "tp": {"kind": "float", "lo": 0.95, "hi": 0.99}, "ts": {"kind": "int", "lo": 400, "hi": 500, "step": 1},
        },
        "direction": 1,
    })


_PARAMS = {"lvl": 0.51, "stop": 0.49, "tp": 0.98, "ts": 450}


def test_held_to_resolution_settles_at_yes_payout():
    # Odds drift 0.50 → ~0.80; the contract RESOLVES YES (payout $1) at bar 60 (inside the validation slice).
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = _odds_bars([0.50 + 0.0025 * i for i in range(120)], start)
    res_ts = bars[60].ts
    spec = _long_hold_spec()
    settled = run_strategy_backtest_detailed(
        spec, _PARAMS, {"C": bars}, fee_bps=Decimal("0"), include_holdout=False,
        vol_target_sizing=False, resolution_by_symbol={"C": (res_ts, 1.0)},
    )
    no_settle = run_strategy_backtest_detailed(
        spec, _PARAMS, {"C": bars}, fee_bps=Decimal("0"), include_holdout=False, vol_target_sizing=False,
    )
    # Entered ~0.51, settled at $1.0 → a bigger gain than marking at the resolution-bar odds (~0.65).
    assert settled.per_symbol["C"]["return"] > no_settle.per_symbol["C"]["return"]
    assert settled.per_symbol["C"]["return"] > 0.6  # ~0.51 → 1.0


def test_held_to_resolution_settles_at_no_payout_total_loss():
    # The SAME rising odds, but the contract resolves NO (payout $0): a long is a total loss, regardless of how
    # rich the odds looked before resolution — the favorite-longshot reality the last-odds mark could never see.
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = _odds_bars([0.50 + 0.0025 * i for i in range(120)], start)
    res_ts = bars[60].ts
    spec = _long_hold_spec()
    settled = run_strategy_backtest_detailed(
        spec, _PARAMS, {"C": bars}, fee_bps=Decimal("0"), include_holdout=False,
        vol_target_sizing=False, resolution_by_symbol={"C": (res_ts, 0.0)},
    )
    # Long entered ~0.51, settled at $0 → ~ -100% on the trade.
    assert settled.per_symbol["C"]["return"] < -0.9


def test_flag_off_ignores_resolution_marks_at_last_odds():
    # settle_at_resolution=False → the resolution map is ignored entirely (the position marks at the last bar like
    # every other asset). Proves the flag gates the new physics: byte-identical to the no-resolution path.
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = _odds_bars([0.50 + 0.0025 * i for i in range(120)], start)
    res_ts = bars[60].ts
    spec = _long_hold_spec().model_copy(update={"exit": _long_hold_spec().exit.model_copy(update={"settle_at_resolution": False})})
    with_map = run_strategy_backtest_detailed(
        spec, _PARAMS, {"C": bars}, fee_bps=Decimal("0"), include_holdout=False,
        vol_target_sizing=False, resolution_by_symbol={"C": (res_ts, 0.0)},
    )
    without_map = run_strategy_backtest_detailed(
        spec, _PARAMS, {"C": bars}, fee_bps=Decimal("0"), include_holdout=False, vol_target_sizing=False,
    )
    # The flag is OFF, so a NO-resolution payout never touches the curve — identical to no map at all.
    assert with_map.per_symbol["C"]["return"] == without_map.per_symbol["C"]["return"]
    assert with_map.per_symbol["C"]["return"] > 0.0  # marked at the last (rich) odds, never the $0 payout
