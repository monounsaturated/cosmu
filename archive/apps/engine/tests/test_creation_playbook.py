# intent: lock the strategy-CREATION PLAYBOOK (strategy/creation_playbook.py) — the deterministic pre-Gate
# authoring rules that make every authored spec realistic / coherent / live-feasible BEFORE it hits the Gate, plus
# the offline-safe learning-loop scaffold. Covers each rule's pass/warn/fail, the aggregate verdict, and that the
# playbook is PURE (no DB) for the checks while the learning loop reads/writes the event ledger.

from __future__ import annotations

from cosmu.data.backtest import DEFAULT_MAKER_FILL
from cosmu.strategy.creation_playbook import (
    learned_maker_fill,
    record_outcome,
    run_playbook,
)
from cosmu.strategy.spec import (
    Condition,
    EntrySetup,
    ExitRules,
    FairValueGap,
    FeatureRef,
    Horizon,
    OpeningRangeBreakout,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)


def _spec(
    *,
    execution_mode: str = "taker",
    direction: int = 1,
    op: str = "lt",
    venues: list[str] | None = None,
    asset_classes: list[str] | None = None,
    disconfirmer: str | None = "kill if it loses to buy-and-hold net of fees on its own cell",
    rationale: str = "a fade hypothesis",
    setup: EntrySetup | None = None,
    lookback: int | ParamRef = None,  # type: ignore[assignment]
    settle_at_resolution: bool = False,
) -> StrategySpec:
    return StrategySpec(
        name="pb-test",
        rationale=rationale,
        disconfirmer=disconfirmer,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        universe=UniverseSelector(
            venues=venues or ["binance"],
            asset_classes=asset_classes or ["crypto"],
            min_instruments=5,
        ),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=5),
        entry=[Condition(
            feature=FeatureRef(name="rsi", lookback=(lookback if lookback is not None else ParamRef(param="lb"))),
            op=op,  # type: ignore[arg-type]
            threshold=ParamRef(param="thr"),
        )],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            settle_at_resolution=settle_at_resolution,
        ),
        risk=RiskRules(),
        setup=setup,
        param_space={
            "lb": ParamSpace(kind="int", lo=2, hi=30),
            "thr": ParamSpace(kind="float", lo=10.0, hi=90.0),
            "stop": ParamSpace(kind="float", lo=0.01, hi=0.2),
            "take": ParamSpace(kind="float", lo=0.01, hi=0.2),
        },
    )


# --------------------------------------------------------------------------- execution coherence


def test_taker_is_always_coherent():
    rep = run_playbook(_spec(execution_mode="taker"))
    assert rep.verdict == "pass"
    assert next(f for f in rep.findings if f.rule == "execution_coherence").severity == "pass"


def test_maker_reversion_long_is_coherent():
    """A long maker that FADES (buys weakness, op=lt) is coherent — a passive bid is natural for a reversion."""
    rep = run_playbook(_spec(execution_mode="maker", direction=1, op="lt"))
    assert next(f for f in rep.findings if f.rule == "execution_coherence").severity == "pass"


def test_maker_with_breakout_setup_is_a_hard_fail():
    """A breakout (ORB/FVG) must CROSS to chase — declaring it maker is a hard contradiction."""
    setup = EntrySetup(orb=OpeningRangeBreakout(range_bars=ParamRef(param="lb"), buffer=ParamRef(param="thr")))
    rep = run_playbook(_spec(execution_mode="maker", setup=setup))
    coh = next(f for f in rep.findings if f.rule == "execution_coherence")
    assert coh.severity == "fail"
    assert rep.verdict == "fail" and not rep.ok()

    setup_fvg = EntrySetup(fvg=FairValueGap(max_retests=ParamRef(param="lb"), gap_min=ParamRef(param="thr")))
    assert run_playbook(_spec(execution_mode="maker", setup=setup_fvg)).verdict == "fail"


def test_maker_that_chases_strength_warns():
    """A long maker whose only entry CHASES strength (op=gt) is suspicious for a passive order → WARN."""
    rep = run_playbook(_spec(execution_mode="maker", direction=1, op="gt"))
    coh = next(f for f in rep.findings if f.rule == "execution_coherence")
    assert coh.severity == "warn"


def test_short_maker_fading_strength_is_coherent():
    """A short maker fades strength (sells into a rip, op=gt) — coherent for the short side."""
    rep = run_playbook(_spec(execution_mode="maker", direction=-1, op="gt"))
    assert next(f for f in rep.findings if f.rule == "execution_coherence").severity == "pass"


# --------------------------------------------------------------------------- venue feasibility


def test_maker_on_paper_only_alpaca_is_infeasible():
    rep = run_playbook(_spec(execution_mode="maker", venues=["alpaca"], asset_classes=["equity"], op="lt"))
    feas = next(f for f in rep.findings if f.rule == "venue_feasibility")
    assert feas.severity == "fail" and "paper-only" in feas.reason


def test_maker_on_ibkr_is_feasible():
    rep = run_playbook(_spec(execution_mode="maker", venues=["ibkr"], asset_classes=["equity"], op="lt"))
    assert next(f for f in rep.findings if f.rule == "venue_feasibility").severity == "pass"


def test_unknown_venue_fails_feasibility():
    rep = run_playbook(_spec(venues=["definitely-not-a-venue"]))
    feas = next(f for f in rep.findings if f.rule == "venue_feasibility")
    assert feas.severity == "fail" and "unknown venue" in feas.reason


# --------------------------------------------------------------------------- fee realism


def test_maker_rebate_claim_warns():
    """An edge whose rationale leans on EARNING/capturing the spread cannot survive the no-spread-credit floor."""
    rep = run_playbook(_spec(
        execution_mode="maker", op="lt",
        rationale="capture the spread by posting passively and collect the maker rebate",
    ))
    fee = next(f for f in rep.findings if f.rule == "fee_realism")
    assert fee.severity == "warn"


def test_taker_fee_realism_is_pass():
    rep = run_playbook(_spec(execution_mode="taker", rationale="capture the spread"))
    # The rebate cue only matters for maker/both; a taker edge does not assume a rebate.
    assert next(f for f in rep.findings if f.rule == "fee_realism").severity == "pass"


# --------------------------------------------------------------------------- disconfirmer


def test_disconfirmer_field_passes():
    assert next(f for f in run_playbook(_spec(disconfirmer="no edge if X")).findings if f.rule == "disconfirmer").severity == "pass"


def test_disconfirmer_in_rationale_passes():
    rep = run_playbook(_spec(disconfirmer=None, rationale="momentum edge; kill if it loses to buy-and-hold"))
    assert next(f for f in rep.findings if f.rule == "disconfirmer").severity == "pass"


def test_missing_disconfirmer_fails():
    rep = run_playbook(_spec(disconfirmer=None, rationale="a vague momentum idea that should just work"))
    disc = next(f for f in rep.findings if f.rule == "disconfirmer")
    assert disc.severity == "fail" and not rep.ok()


# --------------------------------------------------------------------------- look-ahead


def test_nonpositive_lookback_fails():
    rep = run_playbook(_spec(lookback=0))
    la = next(f for f in rep.findings if f.rule == "no_lookahead")
    assert la.severity == "fail"


def test_settle_at_resolution_on_non_prediction_warns():
    rep = run_playbook(_spec(asset_classes=["crypto"], settle_at_resolution=True))
    assert next(f for f in rep.findings if f.rule == "no_lookahead").severity == "warn"


def test_clean_spec_passes_everything():
    rep = run_playbook(_spec(execution_mode="taker"))
    assert rep.verdict == "pass" and rep.summary() == "PASS"
    assert all(f.severity == "pass" for f in rep.findings)


# --------------------------------------------------------------------------- learning-loop scaffold


def test_learned_maker_fill_defaults_without_store():
    """No store → the conservative default (the loop tightens from evidence, never loosens by default)."""
    assert learned_maker_fill(None) == DEFAULT_MAKER_FILL


def test_learning_loop_records_and_reads_back(tmp_path):
    """record_outcome writes audited events; learned_maker_fill reads enough samples back and moves the assumed
    fill_rate toward the observed mean. Offline-safe end-to-end on a throwaway sqlite store."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/pb.sqlite3", openrouter_api_key=None))

    # Too few samples → still the conservative default.
    record_outcome(store, kind="maker_fill_observed", payload={"fill_rate": 0.2})
    assert learned_maker_fill(store) == DEFAULT_MAKER_FILL

    # Enough observed samples (all 0.2) → the learned model adopts the observed mean fill_rate.
    for _ in range(25):
        record_outcome(store, kind="maker_fill_observed", payload={"fill_rate": 0.2})
    learned = learned_maker_fill(store)
    assert abs(learned.fill_rate - 0.2) < 1e-6
    # adverse-selection + queue stay at the conservative defaults until there is a reason to move them.
    assert learned.adverse_selection_frac == DEFAULT_MAKER_FILL.adverse_selection_frac
    assert learned.queue_position_frac == DEFAULT_MAKER_FILL.queue_position_frac


def test_run_playbook_is_pure_no_store_needed():
    """The rule checks never need a DB — run_playbook works with only a spec + the default catalog."""
    rep = run_playbook(_spec())
    assert isinstance(rep.findings, list) and len(rep.findings) == 5
