# intent: the ML-through-natural-language seam — turn a plain-language ML request ("rank survivors by
# edge-persistence", "which features matter") into a DETERMINISTIC ML pass (survival ranking or feature
# importance) over the store's REAL persisted screen outcomes. LLM-OPTIONAL: with a key the model only PARSES
# intent (proposes which task to run); offline a deterministic keyword classifier does the same. The result is
# JUDGED by the deterministic scorer (it reports each ranked item's gate verdict) but the ML NEVER alters the
# scorer/gate — ranking is a permutation, the gate alone decides survival. invariants: scorer/gate out of every
# LLM path, offline + reproducible, point-in-time (reads only already-labeled past outcomes).

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.knowledge.store import Store
from cosmu.ml.survival import FEATURE_NAMES, SurvivalFeatures, load_survival_model

# Plain-language intent → ML task. The deterministic classifier; an LLM slots in here when a key is set, but it
# only chooses the task — it never runs the ranking or touches the gate.
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("feature_importance", ("feature", "matter", "important", "driver", "which signal", "attribut")),
    ("survival_ranking", ("rank", "persist", "edge", "survive", "order", "queue", "priorit")),
)


@dataclass
class RankedItem:
    version_id: str
    name: str
    score: float            # the survival model's edge-persistence score in [0,1] (ordering only)
    gate_passed: bool       # the DETERMINISTIC gate's verdict for this version — judged, never altered here
    deflated_sharpe: float


@dataclass
class FeatureWeight:
    feature: str
    weight: float           # standardized contribution magnitude (sign = direction); ordering only


@dataclass
class MlResult:
    task: str               # "survival_ranking" | "feature_importance"
    request: str
    llm: str                # "on" | "off (deterministic)"
    trained: bool
    backend: str
    n_labels: int
    ranking: list[RankedItem] = field(default_factory=list)
    feature_importance: list[FeatureWeight] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def classify_intent(request: str, *, llm_enabled: bool = False) -> str:
    """Pick the ML task from the request. Deterministic keyword match (the LLM, when enabled, only proposes the
    same choice — it cannot run the task or reach the gate). Defaults to survival_ranking."""
    text = request.lower()
    for task, keys in _INTENT_KEYWORDS:
        if any(k in text for k in keys):
            return task
    return "survival_ranking"


def run_ml_request(store: Store, request: str, *, llm_enabled: bool = False, limit: int = 24) -> MlResult:
    """Run the ML pass the request asks for, over the store's REAL persisted screen outcomes. The survival model
    (load_survival_model) trains on LABELED past outcomes (gate pass/kill) and ORDERS survivors; the gate verdict
    on each item is REPORTED (the scorer judges) but never changed by this path."""
    task = classify_intent(request, llm_enabled=llm_enabled)
    model = load_survival_model(store)
    notes: list[str] = []
    if not llm_enabled:
        notes.append("model router disabled (no key) — deterministic intent classification used")
    if not model.trained:
        notes.append(f"survival model cold-start (< train threshold, {model.n_labels} labels) — heuristic ordering")

    result = MlResult(
        task=task,
        request=request,
        llm="on" if llm_enabled else "off (deterministic)",
        trained=model.trained,
        backend=model.backend,
        n_labels=model.n_labels,
        notes=notes,
    )

    rows = _gate_passers_with_features(store, limit=limit)
    if task == "feature_importance":
        result.feature_importance = _feature_importance(model, rows)
        # Even feature-importance still surfaces the ranking so the answer is JUDGED (gate verdict per item).
        result.ranking = _rank(model, rows)
    else:
        result.ranking = _rank(model, rows)
    return result


def _rank(model, rows: list[dict]) -> list[RankedItem]:  # noqa: ANN001
    items = [(r["version_id"], r["features"]) for r in rows]
    ranked = {rk.key: rk for rk in model.rank(items)}  # permutation only — count-in == count-out
    out = [
        RankedItem(
            version_id=r["version_id"],
            name=r["name"],
            score=ranked[r["version_id"]].score,
            gate_passed=bool(r["passed_gates"]),
            deflated_sharpe=float(r["deflated_sharpe"]),
        )
        for r in rows
    ]
    out.sort(key=lambda i: (i.score, i.deflated_sharpe), reverse=True)
    return out


def _feature_importance(model, rows: list[dict]) -> list[FeatureWeight]:  # noqa: ANN001
    """Feature importance. A trained logistic model exposes its standardized weights directly; otherwise we
    report a deterministic permutation-importance proxy: how much each feature moves the heuristic score when
    zeroed, across the real screen-survivor feature rows. Ordering only — never a gate input."""
    weights = getattr(model, "_weights", None)
    if model.trained and weights is not None and len(weights) == len(FEATURE_NAMES):
        out = [FeatureWeight(feature=name, weight=round(weights[i], 6)) for i, name in enumerate(FEATURE_NAMES)]
    else:
        out = _permutation_importance(model, rows)
    out.sort(key=lambda w: abs(w.weight), reverse=True)
    return out


def _permutation_importance(model, rows: list[dict]) -> list[FeatureWeight]:  # noqa: ANN001
    if not rows:
        return [FeatureWeight(feature=name, weight=0.0) for name in FEATURE_NAMES]
    base = [model.score_features(r["features"]) for r in rows]
    out: list[FeatureWeight] = []
    for i, name in enumerate(FEATURE_NAMES):
        delta = 0.0
        for r, b in zip(rows, base, strict=True):
            vec = list(r["features"].vector())
            vec[i] = 0.0
            zeroed = SurvivalFeatures(*vec)
            delta += abs(model.score_features(zeroed) - b)
        out.append(FeatureWeight(feature=name, weight=round(delta / len(rows), 6)))
    return out


def _gate_passers_with_features(store: Store, *, limit: int) -> list[dict]:
    """Read recent persisted screen outcomes (gate-passers first), reconstructing each version's survival feature
    row from its stored screen backtest columns — exactly the columns the survival model trains on. Point-in-time:
    only already-persisted past outcomes are read."""
    rows = store.rows(
        """
        SELECT sv.id AS version_id, s.name AS name, b.passed_gates AS passed_gates,
               b.deflated_sharpe AS deflated_sharpe, b.sharpe AS sharpe, b.num_trades AS num_trades,
               b.max_dd AS max_dd, b.folds_positive AS folds_positive, b.pbo AS pbo
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        JOIN backtests b ON b.strategy_version_id = sv.id AND b.kind = 'screen'
        ORDER BY CAST(b.passed_gates AS INTEGER) DESC, CAST(b.deflated_sharpe AS REAL) DESC, sv.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    out: list[dict] = []
    for r in rows:
        features = SurvivalFeatures(
            sharpe_per_obs=float(r["sharpe"] or 0) / 16.0,  # de-annualization proxy (monotone in SR)
            num_trades=float(r["num_trades"] or 0),
            max_dd=float(r["max_dd"] or 0),
            folds_positive_pct=float(r["folds_positive"] or 0) / 6.0,
            pbo=float(r["pbo"] or 0),
            skew=0.0,
            kurt_excess=0.0,
            n_obs=0.0,
            regime_spread=0.0,
        )
        out.append({**dict(r), "features": features})
    return out
