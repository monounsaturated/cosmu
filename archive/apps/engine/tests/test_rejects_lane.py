# The REJECTS WATCH-LIST lane is OBSERVE-ONLY: it bands gate-rejected-but-CLOSE candidates (a near-miss on the
# statistical gate, never a risk-floor failure) to measure the gate's Type-II rate, and it NEVER changes the
# gate's pass/fail. These tests pin the banding logic (pure, no DB) and the best-effort persist + Type-II report.

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.rejects_lane import (
    CRITICAL_REJECT_REASONS,
    RejectsCandidate,
    identify_rejects,
    persist_rejects_watch,
    rejects_type2_report,
)


@dataclass(frozen=True)
class _Promo:
    """A minimal duck-typed stand-in for cohort.Promotion (the lane reads it by attribute, never imports cohort)."""

    candidate_id: str
    promoted: bool
    deflated_sharpe_prob: float
    survived_fdr: bool
    net_profit: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _store(tmp_path, name="rejects") -> Store:
    s = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))
    s.migrate()
    return s


def test_identify_rejects_bands_a_synthetic_cohort():
    promos = [
        # IN BAND, survived FDR, statistical near-miss only → WATCHED.
        _Promo("close_a", promoted=False, deflated_sharpe_prob=0.93, survived_fdr=True,
               reasons=["deflated_sharpe"], net_profit=0.11),
        _Promo("close_b", promoted=False, deflated_sharpe_prob=0.905, survived_fdr=True,
               reasons=["pbo", "folds_positive"], net_profit=0.07),
        # Promoted survivor → not a reject.
        _Promo("survivor", promoted=True, deflated_sharpe_prob=0.97, survived_fdr=True, reasons=[]),
        # Below the band (clear reject) → not CLOSE.
        _Promo("far", promoted=False, deflated_sharpe_prob=0.80, survived_fdr=True, reasons=["deflated_sharpe"]),
        # At/above the upper edge (band is exclusive on band_max) → not watched.
        _Promo("edge_hi", promoted=False, deflated_sharpe_prob=0.95, survived_fdr=True, reasons=["fdr"]),
        # In band but flunked FDR → correctly dead, never a false negative.
        _Promo("no_fdr", promoted=False, deflated_sharpe_prob=0.92, survived_fdr=False, reasons=["fdr"]),
        # In band + survived FDR but rejected on a RISK floor (max_drawdown) → a TRUE negative, never watched.
        _Promo("risky", promoted=False, deflated_sharpe_prob=0.94, survived_fdr=True,
               reasons=["deflated_sharpe", "max_drawdown"]),
        # In band + survived FDR, failed ONLY buy_and_hold → B&H is DEMOTED, so this IS watched (kept + paper-tested).
        _Promo("loser", promoted=False, deflated_sharpe_prob=0.91, survived_fdr=True,
               reasons=["buy_and_hold"]),
    ]

    watched = identify_rejects(promos, band_min=0.90, band_max=0.95)
    ids = [r.candidate_id for r in watched]

    # The clean statistical near-misses AND the buy_and_hold-only reject (B&H demoted), ranked by descending closeness.
    assert ids == ["close_a", "loser", "close_b"]
    assert all(isinstance(r, RejectsCandidate) for r in watched)
    assert watched[0].deflated_sharpe_prob == 0.93
    assert watched[0].net_profit == 0.11
    assert "risky" not in ids  # a genuine RISK floor (max_drawdown) is never watched
    # No genuine RISK FLOOR reason is ever watched (buy_and_hold is no longer one of them).
    for r in watched:
        assert not CRITICAL_REJECT_REASONS.intersection(r.reasons)


def test_default_band_is_widened_to_080_for_the_type_ii_observe_net():
    """The production caller (verdict_log) uses the DEFAULT band, WIDENED 0.90→0.80 (2026-06-16). The lane is
    zero-capital observation, so we err WIDE to MEASURE Type-II — but only among CLEAN near-misses: the quality
    gates still exclude FDR-failers and economic-floor rejects, so no real negative is ever watched."""
    promos = [
        _Promo("near_082", promoted=False, deflated_sharpe_prob=0.82, survived_fdr=True, reasons=["deflated_sharpe"]),
        _Promo("below_078", promoted=False, deflated_sharpe_prob=0.78, survived_fdr=True, reasons=["deflated_sharpe"]),
        _Promo("near_082_no_fdr", promoted=False, deflated_sharpe_prob=0.82, survived_fdr=False, reasons=["fdr"]),
        _Promo("near_082_risk", promoted=False, deflated_sharpe_prob=0.82, survived_fdr=True, reasons=["max_drawdown"]),
    ]
    # DEFAULT band (no band_min/band_max passed) — the wider net catches 0.82 but never a real RISK-floor negative.
    watched = {r.candidate_id for r in identify_rejects(promos)}
    assert watched == {"near_082"}  # 0.78 below band; FDR-fail (no holdout) excluded; max_drawdown risk-floor excluded


def test_oos_strong_path_admits_deflation_killed_books_with_strong_holdout():
    """PATH 2: a candidate the IN-SAMPLE multiple-testing penalty killed (DSR~0, flunked FDR) but that is
    individually CLEAN (PBO + folds passed), profitable, and has a STRONG purged OOS holdout is admitted to the
    zero-capital watch lane — the textbook over-rejection to measure forward. Mirrors the 6 real prod books
    (e.g. triple-barrier meta-labeled momentum: net +0.285, OOS holdout +0.449, killed by deflated_sharpe+fdr+B&H)."""

    @dataclass(frozen=True)
    class _Metrics:
        holdout_deflated_sharpe: float | None

    @dataclass(frozen=True)
    class _Cand2:
        id: str
        net_profit: float
        metrics: _Metrics

    promos = [
        # killed by in-sample deflation/FDR + B&H, but PBO+folds CLEAN and strong holdout → admitted (oos_strong)
        _Promo("oos_win", promoted=False, deflated_sharpe_prob=0.0, survived_fdr=False,
               reasons=["buy_and_hold", "deflated_sharpe", "fdr"]),
        # same shape but WEAK holdout (< floor) → no genuine OOS evidence → NOT admitted
        _Promo("oos_weak", promoted=False, deflated_sharpe_prob=0.0, survived_fdr=False,
               reasons=["buy_and_hold", "deflated_sharpe", "fdr"]),
        # strong holdout but FAILED PBO → individually overfit → NOT admitted
        _Promo("pbo_fail", promoted=False, deflated_sharpe_prob=0.0, survived_fdr=False,
               reasons=["deflated_sharpe", "fdr", "pbo"]),
        # strong holdout but a real RISK floor (max_drawdown) → TRUE negative → NOT admitted
        _Promo("dd_fail", promoted=False, deflated_sharpe_prob=0.0, survived_fdr=False,
               reasons=["deflated_sharpe", "fdr", "max_drawdown"]),
        # strong holdout but NEGATIVE net → not a kept book → NOT admitted
        _Promo("loss", promoted=False, deflated_sharpe_prob=0.0, survived_fdr=False,
               reasons=["deflated_sharpe", "fdr"]),
    ]
    cands = [
        _Cand2("oos_win", 0.285, _Metrics(0.449)),
        _Cand2("oos_weak", 0.10, _Metrics(0.05)),
        _Cand2("pbo_fail", 0.20, _Metrics(0.40)),
        _Cand2("dd_fail", 0.20, _Metrics(0.40)),
        _Cand2("loss", -0.05, _Metrics(0.40)),
    ]
    watched = identify_rejects(promos, cands)
    assert {r.candidate_id for r in watched} == {"oos_win"}
    win = watched[0]
    assert win.admission == "oos_strong"
    assert win.holdout_dsr == 0.449
    assert win.net_profit == 0.285  # net read from the candidate metrics, not the (zero) promotion default


def test_identify_rejects_respects_custom_band_and_degenerate_band():
    promos = [
        _Promo("a", promoted=False, deflated_sharpe_prob=0.85, survived_fdr=True, reasons=["pbo"]),
        _Promo("b", promoted=False, deflated_sharpe_prob=0.93, survived_fdr=True, reasons=["pbo"]),
    ]
    # A wider band catches the lower near-miss too.
    wide = identify_rejects(promos, band_min=0.80, band_max=0.95)
    assert {r.candidate_id for r in wide} == {"a", "b"}
    # A degenerate (empty/inverted) band selects nothing rather than mis-banding.
    assert identify_rejects(promos, band_min=0.95, band_max=0.90) == []
    assert identify_rejects(promos, band_min=0.90, band_max=0.90) == []


def test_identify_rejects_uses_candidate_net_profit_when_present():
    @dataclass(frozen=True)
    class _Cand:
        id: str
        net_profit: float

    promos = [_Promo("x", promoted=False, deflated_sharpe_prob=0.92, survived_fdr=True, reasons=["pbo"])]
    cands = [_Cand("x", net_profit=0.42)]
    watched = identify_rejects(promos, cands, band_min=0.90, band_max=0.95)
    assert watched[0].net_profit == 0.42


def test_persist_rejects_watch_is_idempotent(tmp_path):
    store = _store(tmp_path)
    rejects = [
        RejectsCandidate("c1", deflated_sharpe_prob=0.93, net_profit=0.1, reasons=["pbo"]),
        RejectsCandidate("c2", deflated_sharpe_prob=0.91, net_profit=0.0, reasons=["deflated_sharpe"]),
    ]
    assert persist_rejects_watch(store, rejects, "run-1") == 2
    # Re-running the same cohort never double-watches a candidate.
    assert persist_rejects_watch(store, rejects, "run-1") == 0
    rows = store.rows("SELECT candidate_id, reasons FROM rejects_watch ORDER BY candidate_id")
    assert [r["candidate_id"] for r in rows] == ["c1", "c2"]
    # An event was emitted for the watch.
    evt = store.row("SELECT kind FROM events WHERE kind = 'rejects_watched' LIMIT 1")
    assert evt is not None


def test_persist_rejects_watch_empty_is_noop(tmp_path):
    store = _store(tmp_path)
    assert persist_rejects_watch(store, [], "run-empty") == 0
    assert store.rows("SELECT 1 FROM rejects_watch") == []


def test_type2_report_empty_is_honest(tmp_path):
    store = _store(tmp_path)
    report = rejects_type2_report(store)
    assert report.n_rejects == 0
    assert report.false_negative_rate is None
    assert report.survivor_median_return is None


def _seed_version(store: Store, vid: str, status: str, now: str) -> None:
    store.rows(
        "INSERT INTO strategies(id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
        (vid, vid, "t", "test", now),
    )
    store.rows(
        "INSERT INTO strategy_versions"
        "(id, strategy_id, spec, generated_code, code_hash, params, origin, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, vid, "{}", "", "h", "{}", "test", status, now),
    )


def _seed_track(store: Store, vid: str, capital: str, ret: str, now: str) -> None:
    store.rows(
        "INSERT INTO tracks(id, strategy_version_id, starting_capital, equity, return_pct, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (f"t-{vid}", vid, capital, capital, ret, now),
    )


def _seed_passed_screen(store: Store, vid: str, now: str) -> None:
    store.rows(
        "INSERT INTO backtests"
        "(id, strategy_version_id, kind, oos_return, sharpe, sortino, deflated_sharpe, max_dd, win_rate, "
        "num_trades, pbo, trials_counted, folds_positive, passed_gates, holdout_passed, created_at) "
        "VALUES (?, ?, 'screen', 0, 0, 0, 0.96, 0, 0.5, 30, 0, 1, 1, 1, 1, ?)",
        (f"b-{vid}", vid, now),
    )


def test_type2_report_estimates_false_negative_rate(tmp_path):
    store = _store(tmp_path)
    now = "2026-06-15T00:00:00+00:00"

    # Two genuine gate-passed survivors with realized paper returns → median benchmark = 5.0%.
    for vid, ret in [("sv1", "4.0"), ("sv2", "6.0")]:
        _seed_version(store, vid, "paper", now)
        _seed_track(store, vid, "100000", ret, now)
        _seed_passed_screen(store, vid, now)

    # Two watched rejects, each with a zero-capital paper track: one cleared the survivor median (false negative),
    # one did not. A third reject has no funded track → no realized evidence yet (excluded from the rate).
    persist_rejects_watch(
        store,
        [
            RejectsCandidate("rj_hi", deflated_sharpe_prob=0.94, net_profit=0.1, reasons=["deflated_sharpe"]),
            RejectsCandidate("rj_lo", deflated_sharpe_prob=0.91, net_profit=0.0, reasons=["pbo"]),
            RejectsCandidate("rj_none", deflated_sharpe_prob=0.92, net_profit=0.0, reasons=["pbo"]),
        ],
        "run-1",
    )
    # Link the two paper-tracked rejects to zero-capital tracks (the lane records the link on its row).
    for cid, vid, ret in [("rj_hi", "rv1", "7.0"), ("rj_lo", "rv2", "1.0")]:
        _seed_version(store, vid, "screened", now)
        _seed_track(store, vid, "0", ret, now)  # ZERO capital — a rejects track never moves money
        store.rows("UPDATE rejects_watch SET strategy_version_id = ? WHERE candidate_id = ?", (vid, cid))

    report = rejects_type2_report(store)
    assert report.n_rejects == 3
    assert report.n_survivors_marked == 2
    assert report.survivor_median_return == 5.0
    assert report.n_with_paper == 2  # rj_none has no track → no realized evidence
    assert report.n_false_negatives == 1  # only rj_hi (7.0% >= 5.0% median)
    assert report.false_negative_rate == 0.5
