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

# Gate-rejection reasons that are CRITICAL — a candidate rejected for ANY of these is NOT a near-miss worth
# watching: it failed a risk/economic floor (it lost money vs buy-and-hold, drew down past the cap, or never
# traded enough to mean anything), not the statistical-significance gate. We watch only candidates whose ONLY
# rejection reasons are statistical near-misses (deflated_sharpe / pbo / folds_positive / fdr), because those are
# precisely where a too-strict gate would manufacture a false negative. The risk floors are correctly strict and
# a rejection on them is a TRUE negative, never a Type-II candidate. (Reason strings mirror master/scorer.py.)
CRITICAL_REJECT_REASONS = frozenset({"max_drawdown", "buy_and_hold", "min_trades", "holdout"})


@dataclass(frozen=True)
class RejectsCandidate:
    """One gate-rejected candidate the lane has decided to WATCH. It is NOT promoted and carries ZERO capital —
    it exists only so we can measure, after the fact, how it would have performed vs the survivors. `reasons` is
    the gate's own rejection reasons (guaranteed free of any CRITICAL_REJECT_REASONS), so the report can confirm
    these are genuine statistical near-misses, never risk-floor failures."""

    candidate_id: str
    deflated_sharpe_prob: float
    net_profit: float
    reasons: list[str] = field(default_factory=list)


def identify_rejects(
    promotions: list[Any],
    candidates: list[Any] | None = None,
    *,
    band_min: float = 0.90,
    band_max: float = 0.95,
) -> list[RejectsCandidate]:
    """The watch-list selector. A Promotion is a CLOSE reject (a Type-II candidate) iff ALL hold:
      - it was NOT promoted (the gate rejected it),
      - its deflated-Sharpe probability is in the watch band [band_min, band_max) — it cleared most of the way to
        the 0.95 promotion floor but fell short,
      - it SURVIVED Benjamini-Hochberg FDR (so it is not a multiple-testing artifact — a reject that flunked FDR
        is correctly dead, never a false negative),
      - NONE of its rejection reasons is a CRITICAL filter (max_drawdown / buy_and_hold / min_trades / holdout):
        a risk/economic-floor rejection is a TRUE negative, not something the gate got wrong.

    `promotions`/`candidates` are duck-typed (attribute access) so this module never imports cohort — mirroring
    verdict_log's one-way dependency. `candidates` is OPTIONAL and used only to carry net_profit when a Promotion
    lacks it (it does not, currently; the param keeps the signature symmetric with persist_rejects_watch and lets
    a caller pass richer Candidate metrics later). Pure + side-effect-free: it reads the verdict, never writes it.
    """
    if band_min >= band_max:
        # A degenerate band can never select anything; refuse silently rather than mis-banding the watch-list.
        return []
    profit_by_id: dict[str, float] = {}
    for c in candidates or []:
        cid = getattr(c, "id", None)
        if cid is not None:
            profit_by_id[cid] = float(getattr(c, "net_profit", 0.0) or 0.0)

    out: list[RejectsCandidate] = []
    for p in promotions:
        if getattr(p, "promoted", False):
            continue  # a promoted candidate is a survivor, not a reject — nothing to watch
        if not getattr(p, "survived_fdr", False):
            continue  # flunked FDR → correctly dead (multiple-testing artifact), not a false negative
        dsr = float(getattr(p, "deflated_sharpe_prob", 0.0) or 0.0)
        if not (band_min <= dsr < band_max):
            continue  # outside the CLOSE band → either a survivor's territory or a clear reject, not a near-miss
        reasons = list(getattr(p, "reasons", []) or [])
        if CRITICAL_REJECT_REASONS.intersection(reasons):
            continue  # rejected on a risk/economic floor → a TRUE negative, never a Type-II candidate
        cid = getattr(p, "candidate_id", None)
        if cid is None:
            continue
        net = profit_by_id.get(cid, float(getattr(p, "net_profit", 0.0) or 0.0))
        out.append(
            RejectsCandidate(
                candidate_id=cid,
                deflated_sharpe_prob=dsr,
                net_profit=net,
                reasons=reasons,
            )
        )
    # Rank the watch-list by how CLOSE it came (descending DSR), so the report and any UI surface the nearest
    # misses first — the most informative false-negative candidates.
    out.sort(key=lambda r: r.deflated_sharpe_prob, reverse=True)
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
