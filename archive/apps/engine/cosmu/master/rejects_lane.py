# intent: the REJECTS WATCH-LIST lane — OBSERVE-ONLY. The Gate is correctly strict (0 survivors = the machine
# working) and we NEVER loosen it; but a strict gate has a Type-II / false-negative rate we never measured. This
# lane identifies gate-REJECTED-but-CLOSE candidates (a near-miss on the statistical gate, NOT a risk/economic
# floor failure), zero-capital paper-tracks them on the SAME SIM path survivors use, and reports an EMPIRICAL
# Type-II estimate by comparing the rejects' realized paper performance against the survivors'. inputs: the
# cohort's Promotions + Candidates (duck-typed, read-only) + the store; outputs: rejects_watch rows + an optional
# zero-capital track + a Type-II report. invariants: this lane NEVER changes the gate's pass/fail (it reads the
# verdict, never writes it), a rejects track funds at ZERO capital (it cannot move money and is excluded from
# every money/leaderboard population), persistence is BEST-EFFORT (a failure never breaks the gate run), and the
# math here is purely observational — no LLM, no gate threshold, no scorer/cohort logic is touched.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from cosmu.knowledge.store import Store, utcnow

log = logging.getLogger(__name__)

# The genuine risk/economic FLOORS — a rejection on ANY of these is a TRUE negative, never a Type-II candidate:
# the book drew down past the cap, never traded enough to mean anything, or its purged OOS holdout was sign-
# negative. A reject FREE of these is a statistical/benchmark near-miss — precisely where a too-strict gate
# manufactures a false negative — so the lane watches it (zero capital). (Reason strings mirror master/scorer.py.)
#
# NOTE (2026-06-16): 'buy_and_hold' was DEMOTED out of this set. Failing to OUT-RETURN an explosive asset in a
# bull sample is a BENCHMARK choice, not a risk failure: a positive, individually-clean book that merely didn't
# beat HODL is exactly what we want to KEEP + paper-test (B&H is a reference, not a north star). buy_and_hold is
# now a displayed reason on the watch row, never a watch-DISQUALIFIER.
RISK_FLOOR_REASONS = frozenset({"max_drawdown", "min_trades", "holdout"})
CRITICAL_REJECT_REASONS = RISK_FLOOR_REASONS  # back-compat alias (same meaning now that B&H is demoted)

# OOS-holdout admission floor (PATH 2). A candidate the IN-SAMPLE multiple-testing penalty (deflated_sharpe / fdr)
# killed, but whose REAL purged+embargoed OOS holdout Sharpe is significantly positive (P(SR>0) >= 0.70, i.e.
# holdout_dsr >= 0.20 on the PSR-0.5 scale) AND that is individually clean (PBO + folds passed) AND made money, is
# the textbook over-rejection to MEASURE forward. Mirrors the equity deploy holdout floor (DEPLOY_MIN_HOLDOUT_DSR).
OOS_HOLDOUT_WATCH_FLOOR = 0.20


@dataclass(frozen=True)
class RejectsCandidate:
    """One gate-rejected candidate the lane has decided to WATCH. It is NOT promoted and carries ZERO capital —
    it exists only so we can measure, after the fact, how it would have performed vs the survivors. `reasons` is
    the gate's own rejection reasons (guaranteed free of any RISK_FLOOR_REASONS), so the report can confirm these
    are genuine statistical/benchmark near-misses, never risk-floor failures. `admission` records WHICH path let
    it in (a DSR near-miss vs a strong out-of-sample holdout the in-sample penalty killed); `holdout_dsr` is the
    REAL purged+embargoed OOS holdout Sharpe (PSR-0.5), the evidence behind the 'oos_strong' path."""

    candidate_id: str
    deflated_sharpe_prob: float
    net_profit: float
    reasons: list[str] = field(default_factory=list)
    holdout_dsr: float | None = None
    admission: str = "dsr_near_miss"  # 'dsr_near_miss' (in-band + survived FDR) | 'oos_strong' (strong OOS holdout)


def identify_rejects(
    promotions: list[Any],
    candidates: list[Any] | None = None,
    *,
    band_min: float = 0.80,   # WIDENED from 0.90 (2026-06-16): this is a ZERO-CAPITAL observe net whose only job is
    band_max: float = 0.95,   # to MEASURE the gate's Type-II rate. The quality gates below (survived-FDR + no
    #                           economic-floor fail) already guarantee every watched row is a CLEAN statistical
    #                           near-miss, never a real negative — so band_min only sets how far down the DSR ladder
    #                           we look. Observation is free and the directive is "don't over-discard," so err WIDE.
) -> list[RejectsCandidate]:
    """The watch-list selector. A non-promoted Promotion enters the zero-capital watch-list via EITHER path, and
    NEVER if it failed a genuine risk floor (RISK_FLOOR_REASONS = max_drawdown / min_trades / holdout):

      PATH 1 — DSR NEAR-MISS: it SURVIVED BH-FDR and its deflated-Sharpe probability is in the band
        [band_min, band_max) — it cleared a SOLID majority of the way to the 0.95 floor (default ≥0.80) but fell
        short. The "is the deflated-Sharpe bar too strict?" candidate.

      PATH 2 — OOS-STRONG: the IN-SAMPLE multiple-testing penalty (deflated_sharpe / fdr) killed it, but it is
        individually CLEAN (PBO + folds passed), made money (net > 0), and its REAL purged+embargoed OOS holdout
        Sharpe is significantly positive (holdout_dsr ≥ OOS_HOLDOUT_WATCH_FLOOR). This captures the over-rejection
        the deflation manufactures on a correlated/crowded cohort — observed forward, NEVER re-promoted. Requires
        the candidate's metrics (via `candidates`) to carry `holdout_deflated_sharpe`.

    buy_and_hold is NOT disqualifying for either path (DEMOTED — see RISK_FLOOR_REASONS): a positive book that
    merely didn't out-return a bull asset is precisely what we keep + paper-test.

    `promotions`/`candidates` are duck-typed (attribute access) so this module never imports cohort — mirroring
    verdict_log's one-way dependency. `candidates` carries net_profit and (on `.metrics.holdout_deflated_sharpe`)
    the OOS holdout PATH 2 reads. Pure + side-effect-free: it reads the verdict, never writes it.
    """
    if band_min >= band_max:
        # A degenerate band can never select anything; refuse silently rather than mis-banding the watch-list.
        return []
    profit_by_id: dict[str, float] = {}
    holdout_by_id: dict[str, float] = {}
    for c in candidates or []:
        cid = getattr(c, "id", None)
        if cid is None:
            continue
        profit_by_id[cid] = float(getattr(c, "net_profit", 0.0) or 0.0)
        metrics = getattr(c, "metrics", None)
        h = getattr(metrics, "holdout_deflated_sharpe", None) if metrics is not None else None
        if h is not None:
            holdout_by_id[cid] = float(h)

    out: list[RejectsCandidate] = []
    for p in promotions:
        if getattr(p, "promoted", False):
            continue  # a promoted candidate is a survivor, not a reject — nothing to watch
        cid = getattr(p, "candidate_id", None)
        if cid is None:
            continue
        reasons = list(getattr(p, "reasons", []) or [])
        if RISK_FLOOR_REASONS.intersection(reasons):
            continue  # rejected on a risk/economic floor → a TRUE negative, never a Type-II candidate
        dsr = float(getattr(p, "deflated_sharpe_prob", 0.0) or 0.0)
        net = profit_by_id.get(cid, float(getattr(p, "net_profit", 0.0) or 0.0))
        holdout = holdout_by_id.get(cid)

        # PATH 1 — DSR near-miss: survived FDR AND in the close band (not a multiple-testing artifact).
        near_miss = bool(getattr(p, "survived_fdr", False)) and (band_min <= dsr < band_max)
        # PATH 2 — OOS-strong: in-sample penalty killed it, but it is individually clean (PBO + folds passed),
        # profitable, and its REAL purged OOS holdout is significantly positive. Observe forward regardless of FDR.
        oos_strong = (
            net > 0.0
            and holdout is not None
            and holdout >= OOS_HOLDOUT_WATCH_FLOOR
            and "pbo" not in reasons
            and "folds_positive" not in reasons
        )
        if not (near_miss or oos_strong):
            continue
        out.append(
            RejectsCandidate(
                candidate_id=cid,
                deflated_sharpe_prob=dsr,
                net_profit=net,
                reasons=reasons,
                holdout_dsr=holdout,
                admission="dsr_near_miss" if near_miss else "oos_strong",
            )
        )

    # Rank by unified CLOSENESS = max(in-sample DSR, holdout PSR=holdout_dsr+0.5) descending, so the nearest misses
    # surface first — and an OOS-strong reject (in-sample DSR ~0 but a high holdout PSR) is not buried beneath
    # weaker DSR near-misses.
    def _closeness(r: RejectsCandidate) -> float:
        hold_psr = (r.holdout_dsr + 0.5) if r.holdout_dsr is not None else 0.0
        return max(r.deflated_sharpe_prob, hold_psr)

    out.sort(key=_closeness, reverse=True)
    return out


def persist_rejects_watch(
    store: Store,
    rejects: list[RejectsCandidate],
    cohort_run_id: str,
    *,
    band_min: float = 0.90,
    band_max: float = 0.95,
) -> int:
    """Write one `rejects_watch` row per watched candidate (idempotent on (cohort_run_id, candidate_id)) + emit a
    single `rejects_watched` event. Returns the number of rows written. BEST-EFFORT: any failure is swallowed +
    logged (the gate verdict is already durably in gate_verdicts — a watch-list write must NEVER break a run).
    Zero capital is implied (no track is funded here; the watch-list only records WHICH candidates to observe)."""
    if not rejects:
        return 0
    written = 0
    try:
        for r in rejects:
            existing = store.row(
                "SELECT id FROM rejects_watch WHERE cohort_run_id = ? AND candidate_id = ?",
                (cohort_run_id, r.candidate_id),
            )
            if existing is not None:
                continue  # idempotent: re-running a cohort never double-watches a candidate
            store.rows(
                "INSERT INTO rejects_watch(id, cohort_run_id, candidate_id, strategy_version_id, "
                "deflated_sharpe_prob, band_min, band_max, net_profit, reasons, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex,
                    cohort_run_id,
                    r.candidate_id,
                    None,  # a zero-capital paper track may be opened later; null until then
                    float(r.deflated_sharpe_prob),
                    float(band_min),
                    float(band_max),
                    float(r.net_profit),
                    json.dumps(list(r.reasons), sort_keys=True),
                    utcnow(),
                ),
            )
            written += 1
        store.append_event(
            actor="master",
            kind="rejects_watched",
            ref_type="gate",
            ref_id=cohort_run_id,
            payload={"n_watched": written, "band_min": band_min, "band_max": band_max,
                     "candidate_ids": [r.candidate_id for r in rejects]},
        )
    except Exception:  # noqa: BLE001 — an observe-only watch-list write must never break the gate path.
        log.warning("persist_rejects_watch failed for cohort_run_id=%s", cohort_run_id, exc_info=True)
    return written


def link_and_open_rejects_tracks(
    store: Store,
    run_id: str,
    version_by_candidate: dict[str, str],
    *,
    catalog=None,  # noqa: ANN001 — spine.venue.VenueCatalog; None → default_catalog (resolved lazily)
) -> int:
    """ACTIVATE the watch-list: for each rejects_watch row of `run_id` that has no track yet, open a ZERO-CAPITAL
    paper track (reusing the SAME SIM fund/step machinery survivors use) and STAMP its strategy_version_id back on
    the row — so the Type-II report can join the reject's realized paper P&L to the gate verdict that rejected it.
    `version_by_candidate` maps a watched candidate_id (the finder's config_tag) to the persisted strategy_version
    that already carries the reject's exact spec + fitted params. Returns the number of tracks opened.

    Idempotent + best-effort: a row already carrying a strategy_version_id is skipped (no double-open), and any
    failure is swallowed + logged — the rejects lane is OBSERVE-ONLY and must never break the gate/research path.
    Zero capital means the opened track contributes 0 to every money/leaderboard sum; it exists only to MEASURE
    the gate's Type-II rate, never to move money. The gate's pass/fail is untouched (this runs strictly after it)."""
    if not version_by_candidate:
        return 0
    opened = 0
    try:
        from cosmu.master.zero_capital import open_zero_capital_track

        rows = store.rows(
            "SELECT id, candidate_id, strategy_version_id FROM rejects_watch WHERE cohort_run_id = ?",
            (run_id,),
        )
        for r in rows:
            if r.get("strategy_version_id"):
                continue  # already linked → idempotent (never double-open a watched reject's track)
            vid = version_by_candidate.get(r.get("candidate_id"))
            if not vid:
                continue  # no persisted version for this candidate → nothing to observe yet
            result = open_zero_capital_track(store, vid, catalog=catalog, origin="rejects")
            # Stamp the version onto the row regardless of whether THIS call opened the track (a pre-existing
            # track for the version is still the link the report needs) — so the join always resolves.
            store.rows(
                "UPDATE rejects_watch SET strategy_version_id = ? WHERE id = ?",
                (vid, r.get("id")),
            )
            if result.opened:
                opened += 1
        if opened:
            store.append_event(
                actor="master",
                kind="rejects_tracks_opened",
                ref_type="gate",
                ref_id=run_id,
                payload={"n_opened": opened},
            )
    except Exception:  # noqa: BLE001 — an observe-only watch-list open must never break the gate path.
        log.warning("link_and_open_rejects_tracks failed for run_id=%s", run_id, exc_info=True)
    return opened


@dataclass(frozen=True)
class Type2Report:
    """The empirical Type-II readout. `n_rejects` watched candidates were zero-capital paper-tracked; `n_with_paper`
    of them accrued a realized paper return (a track that has actually traded). `false_negative_rate` is the
    fraction of WATCHED rejects whose realized paper return cleared the survivors' median — i.e. the gate rejected
    something that, on forward paper evidence, performed like a survivor. It is an ESTIMATE of the gate's Type-II
    rate on the near-miss band, never a verdict that re-promotes anything. `survivor_median_return` is the bar the
    rejects are measured against (None when there are no marked survivors to compare to → the rate is None)."""

    n_rejects: int
    n_with_paper: int
    n_survivors_marked: int
    survivor_median_return: float | None
    n_false_negatives: int
    false_negative_rate: float | None
    detail: list[dict[str, Any]] = field(default_factory=list)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def rejects_type2_report(store: Store) -> Type2Report:
    """Compare the watched rejects' realized paper performance against the survivors' → an EMPIRICAL Type-II
    estimate. Reads only (observe-only): joins each rejects_watch row to its zero-capital paper track's realized
    `tracks.return_pct`, and compares against the median realized return of the genuine (gate-passed) survivors'
    tracks. A reject that cleared the survivor median is a candidate FALSE NEGATIVE (the gate rejected something
    that performed like a survivor); their fraction is the Type-II rate. Offline + DB-light + NEVER moves money —
    it informs the two-lane-routing question (is the gate too strict?), it does not answer it by loosening anything.

    Survivors here = strategy_versions that PASSED the gate (a screen backtest with passed_gates=1) and have a
    track. The rejects' tracks are linked via rejects_watch.strategy_version_id (the zero-capital paper track), so a
    reject with no funded track simply has no realized return yet and does not count toward the rate."""
    rejects = store.rows(
        "SELECT candidate_id, strategy_version_id, deflated_sharpe_prob, net_profit "
        "FROM rejects_watch"
    )
    # The survivor benchmark: realized paper return of genuine gate-passed survivors. A survivor with no marked
    # track is excluded (no realized evidence to benchmark against), matching the rejects' has-a-track requirement.
    survivor_rows = store.rows(
        "SELECT tr.return_pct AS return_pct "
        "FROM tracks tr "
        "JOIN backtests b ON b.strategy_version_id = tr.strategy_version_id AND b.kind = 'screen' "
        "WHERE b.passed_gates = 1"
    )
    survivor_returns = [float(r["return_pct"]) for r in survivor_rows if r.get("return_pct") is not None]
    survivor_median = _median(survivor_returns)

    detail: list[dict[str, Any]] = []
    n_with_paper = 0
    n_false_neg = 0
    for r in rejects:
        vid = r.get("strategy_version_id")
        realized: float | None = None
        if vid is not None:
            track = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (vid,))
            if track is not None and track.get("return_pct") is not None:
                realized = float(track["return_pct"])
        cleared = False
        if realized is not None:
            n_with_paper += 1
            if survivor_median is not None and realized >= survivor_median:
                cleared = True
                n_false_neg += 1
        detail.append(
            {
                "candidate_id": r.get("candidate_id"),
                "strategy_version_id": vid,
                "deflated_sharpe_prob": float(r.get("deflated_sharpe_prob") or 0.0),
                "net_profit": float(r.get("net_profit") or 0.0),
                "realized_return_pct": realized,
                "cleared_survivor_median": cleared,
            }
        )

    # Rate is over the rejects that ACTUALLY accrued paper evidence (and only when there is a survivor bar to
    # compare to) — never over the whole watch-list, which would understate it with not-yet-traded rejects.
    rate: float | None = None
    if survivor_median is not None and n_with_paper > 0:
        rate = n_false_neg / n_with_paper

    return Type2Report(
        n_rejects=len(rejects),
        n_with_paper=n_with_paper,
        n_survivors_marked=len(survivor_returns),
        survivor_median_return=survivor_median,
        n_false_negatives=n_false_neg,
        false_negative_rate=rate,
        detail=detail,
    )
