# The building-block registry: specs decompose into content-hashed blocks invariant to param NAMES (only
# structure + search ranges + features matter), the combo_hash identifies a whole hypothesis, the registry
# dedups re-tested hypotheses (protecting the multiple-testing budget) WITHOUT ever touching the seed lane,
# block stats stay observational, and everything fails OPEN on a store whose migration hasn't run.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import FarmLoop
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.knowledge.block_registry import (
    block_leaderboard,
    blocks_available,
    find_duplicate,
    partner_rank,
    record_version_blocks,
    versions_sharing_blocks,
)
from cosmu.knowledge.store import Store
from cosmu.strategy.blocks import BLOCK_KINDS, combo_hash, decompose
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


def _spec(
    name: str = "s",
    *,
    thr: str = "thr",
    stop: str = "stop",
    take: str = "take",
    lo: float = 0.3,
    venues: list[str] | None = None,
    bar: str = "4h",
) -> StrategySpec:
    return StrategySpec(
        name=name,
        rationale="r",
        universe=UniverseSelector(
            venues=venues or ["binance"], asset_classes=["crypto"], min_liquidity_usd=2_000_000, min_instruments=5
        ),
        horizon=Horizon(bar_size=bar, min_hold_days=2, max_hold_days=14),
        entry=[Condition(feature=FeatureRef(name="rsi", lookback=14), op="lt", threshold=ParamRef(param=thr))],
        exit=ExitRules(stop_loss=ParamRef(param=stop), take_profit=ParamRef(param=take)),
        risk=RiskRules(),
        param_space={
            thr: ParamSpace(kind="float", lo=lo, hi=0.7),
            stop: ParamSpace(kind="float", lo=0.02, hi=0.12),
            take: ParamSpace(kind="float", lo=0.04, hi=0.24),
        },
    )


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/blocks.sqlite3"))


def _version(store: Store, name: str, status: str) -> str:
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "seed", "created_at": "2026-01-01"})
    return store.insert(
        "strategy_versions",
        {
            "strategy_id": sid, "spec": {}, "generated_code": "", "code_hash": f"h-{name}", "params": {},
            "origin": "seed", "status": status, "created_at": "2026-01-01",
        },
    )


# ── pure decomposition ────────────────────────────────────────────────────────────────────────────


def test_param_names_never_change_hashes():
    # The SAME logic authored with different param names is the SAME hypothesis.
    a = _spec("a", thr="rsi_threshold", stop="sl", take="tp")
    b = _spec("b", thr="t", stop="x", take="y")
    assert {blk.block_hash for blk in decompose(a)} == {blk.block_hash for blk in decompose(b)}
    assert combo_hash(a) == combo_hash(b)


def test_search_range_is_part_of_the_identity():
    # Same structure but a DIFFERENT threshold search range = a different hypothesis.
    a, b = _spec("a", lo=0.3), _spec("b", lo=0.1)
    sig_a = next(blk for blk in decompose(a) if blk.kind == "signal")
    sig_b = next(blk for blk in decompose(b) if blk.kind == "signal")
    assert sig_a.block_hash != sig_b.block_hash
    assert combo_hash(a) != combo_hash(b)


def test_universe_changes_combo_but_not_blocks():
    # A graft (same signal, other market) reuses the same BLOCKS yet is a NEW hypothesis.
    a, b = _spec("a"), _spec("b", bar="1d")
    assert {blk.block_hash for blk in decompose(a)} == {blk.block_hash for blk in decompose(b)}
    assert combo_hash(a) != combo_hash(b)


def test_every_block_kind_is_typed():
    seen = {blk.kind for blk in decompose(seed_momentum_spec())}
    assert seen <= set(BLOCK_KINDS)
    assert "signal" in seen and "exit" in seen and "sizing" in seen


def test_decompose_is_deterministic():
    spec = seed_momentum_spec()
    assert [b.block_hash for b in decompose(spec)] == [b.block_hash for b in decompose(spec)]


# ── registry persistence + queries ───────────────────────────────────────────────────────────────


def test_record_dedup_leaderboard_and_similars(tmp_path):
    store = _store(tmp_path)
    assert blocks_available(store)
    spec1, spec2 = _spec("alpha"), _spec("beta", lo=0.1)  # share exit+sizing blocks, differ on signal
    v1, v2 = _version(store, "alpha", "paper"), _version(store, "beta", "killed")
    with store.batch() as b:
        record_version_blocks(b, v1, spec1)
        record_version_blocks(b, v2, spec2)

    dup = find_duplicate(store, combo_hash(spec1))
    assert dup is not None and dup["version_id"] == v1
    assert find_duplicate(store, combo_hash(_spec("новый", bar="1d"))) is None

    rows = {r["block_hash"]: r for r in block_leaderboard(store, min_n=2)}
    shared_exit = next(blk for blk in decompose(spec1) if blk.kind == "exit")
    stat = rows[shared_exit.block_hash]
    # 2 versions carry the exit block; only the paper one was funded → observational rate 0.5.
    assert stat["n_versions"] == 2 and stat["n_funded"] == 1 and stat["funded_rate"] == 0.5

    similar = versions_sharing_blocks(store, v1)
    assert similar and similar[0]["version_id"] == v2 and int(similar[0]["shared_blocks"]) >= 2

    rank = partner_rank(store, [spec1, spec2])
    assert rank["alpha"] == rank["beta"] == 0.5  # both carry the same (half-funded) exit/sizing blocks


def test_recording_is_idempotent(tmp_path):
    store = _store(tmp_path)
    spec = _spec("alpha")
    v1 = _version(store, "alpha", "paper")
    with store.batch() as b:
        record_version_blocks(b, v1, spec)
        record_version_blocks(b, v1, spec)  # ON CONFLICT DO NOTHING — no duplicate-key explosion
    assert len(store.rows("SELECT 1 FROM version_blocks WHERE strategy_version_id = ?", (v1,))) == len(decompose(spec))


def test_fail_open_when_tables_absent(tmp_path):
    store = _store(tmp_path)
    with store.batch() as b:
        b.execute("DROP TABLE version_combos")
    assert blocks_available(store) is False
    assert partner_rank(store, [_spec("a")]) == {}


# ── FarmLoop integration: dedup protects the budget, seeds are exempt ────────────────────────────


def _fixture_bars(count: int = 420) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for idx in range(count):
        move = Decimal("0.012") if (idx % 18) < 9 else Decimal("-0.009")
        open_ = price
        close = (price * (1 + move)).quantize(Decimal("0.01"))
        hi, lo_ = max(open_, close) * Decimal("1.004"), min(open_, close) * Decimal("0.996")
        bars.append(Bar(ts=ts.replace(day=1) if False else ts, open=open_, high=hi, low=lo_, close=close, volume=Decimal("1000")))
        from datetime import timedelta

        ts = ts + timedelta(hours=4)
        price = close
    return bars


class FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def test_cohort_dedups_rescreened_chat_spec_but_never_seeds(tmp_path):
    store = _store(tmp_path)
    loop = FarmLoop(settings=Settings(database_url=f"sqlite:///{tmp_path}/blocks.sqlite3"), store=store, market_data=FixtureProvider(_fixture_bars()))
    chat = _spec("operator idea")

    first = loop.run_cohort(seed=7, cohort_size=4, explore_pct=0.0, extra_seeds=[chat])
    assert first.duplicates == 0
    assert first.generated > 0

    # Same chat hypothesis again: recognized as already tested → skipped, NOT re-screened. The seed
    # population is exempt by design (it is the baseline parent pool, re-run every cohort).
    second = loop.run_cohort(seed=7, cohort_size=4, explore_pct=0.0, extra_seeds=[chat])
    assert second.duplicates >= 1
    assert second.generated > 0  # seeds still screened — dedup never starves the cohort
