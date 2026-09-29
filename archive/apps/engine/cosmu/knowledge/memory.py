# intent: the SELF-IMPROVEMENT FLYWHEEL's long-term memory — a graveyard/research RAG. It persists a research
# note + a point-in-time, DETERMINISTIC, KEYLESS, OFFLINE embedding for every killed Version (with its
# kill_reason) and every survivor (with its winning structure), then recalls the most relevant prior deaths +
# winners for a thesis/spec so the authoring brain stops re-walking dead ends and leans toward what worked.
# inputs: a Store + an Evaluated/spec outcome; outputs: persisted research_notes rows + recall() hits.
# invariants: the embedding is a hashing/TF-IDF vector (no model key, no network) so CI works offline; pgvector
# (cosine over the `vector` column) is used when DATABASE_URL is postgres, else a pure-Python cosine over the
# JSON float array on sqlite; point-in-time — recall(as_of=...) never sees a note created at/after as_of (no
# look-ahead); this memory only INFORMS the LLM-OPTIONAL author — it never gates (the scorer/Gate dispose).

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cosmu.knowledge.store import Store, utcnow

if TYPE_CHECKING:  # avoid importing the heavy spec/loop modules at import time
    from cosmu.evolution.loop import Evaluated
    from cosmu.strategy.spec import StrategySpec

# The embedding dimension. Matches the Postgres `vector(1536)` column so the same deterministic vector lands in
# pgvector unchanged; on sqlite it is stored as a JSON float array. A hashing (feature-hashing) embedding maps
# tokens into this many buckets — fully deterministic and keyless, so CI needs no model key or network.
EMBED_DIM = 1536
_TOKEN = re.compile(r"[a-z0-9_]+")


# --------------------------------------------------------------------------- embedding (deterministic, keyless)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed(text: str) -> list[float]:
    """A DETERMINISTIC, KEYLESS, OFFLINE embedding: TF feature-hashing into EMBED_DIM buckets, L2-normalized.
    No model, no network — the same string always yields the same unit vector, so CI (no key) is reproducible
    and recall ranking is stable. A signed hash trick keeps collisions unbiased."""
    vec = [0.0] * EMBED_DIM
    for tok in _tokens(text):
        h = _stable_hash(tok)
        bucket = h % EMBED_DIM
        sign = 1.0 if (h >> 17) & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _stable_hash(token: str) -> int:
    """A process-independent stable hash (Python's built-in hash is salted per process). FNV-1a, 64-bit."""
    h = 0xCBF29CE484222325
    for ch in token.encode("utf-8"):
        h ^= ch
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity over two equal-length float arrays (vectors are already unit-norm from embed())."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- the structure → text the brain reads


def _spec_text(spec: StrategySpec) -> str:
    """Flatten a spec's STRUCTURE (universe, horizon, named entry/exit features, composable setup modules) into
    the text the embedding indexes. Thresholds (ParamRefs) are deliberately excluded — memory matches on the
    structural fingerprint (which features/modules), not on fitted magic numbers."""
    parts: list[str] = [spec.name, spec.rationale or ""]
    parts += spec.universe.asset_classes
    parts += spec.universe.venues
    parts.append(spec.horizon.bar_size)
    if spec.catalyst:
        parts.append(spec.catalyst)
    for cond in spec.entry:
        parts.append(f"{cond.feature.name} {cond.op}")
    for cond in spec.exit.signal_exits:
        parts.append(f"{cond.feature.name} {cond.op}")
    setup = spec.setup
    if setup is not None:
        if setup.ma_trend_filter is not None:
            parts.append("ma_trend_filter")
        if setup.orb is not None:
            parts.append("orb")
        if setup.fvg is not None:
            parts.append("fvg fvg_retest")
    if spec.exit.plan is not None:
        if spec.exit.plan.multi_tp:
            parts.append("multi_tp")
        if spec.exit.plan.break_even_after_tp1:
            parts.append("break_even runner")
    return " ".join(p for p in parts if p)


def structure_fingerprint(spec: StrategySpec) -> dict[str, Any]:
    """A small machine-readable structural fingerprint stored alongside the note: the asset classes + the named
    entry/exit features + the composable setup modules. The brain reads this to AVOID dead structures and LEAN
    toward winning ones — never thresholds (no magic numbers leak through memory)."""
    setup_modules: list[str] = []
    if spec.setup is not None:
        if spec.setup.ma_trend_filter is not None:
            setup_modules.append("ma_trend_filter")
        if spec.setup.orb is not None:
            setup_modules.append("orb")
        if spec.setup.fvg is not None:
            setup_modules.append("fvg")
    if spec.exit.plan is not None and spec.exit.plan.multi_tp:
        setup_modules.append("multi_tp")
    return {
        "asset_classes": sorted(set(spec.universe.asset_classes)),
        "bar_size": spec.horizon.bar_size,
        "entry_features": sorted({c.feature.name for c in spec.entry}),
        "exit_features": sorted({c.feature.name for c in spec.exit.signal_exits}),
        "setup_modules": sorted(set(setup_modules)),
    }


# --------------------------------------------------------------------------- recall hits


@dataclass(frozen=True)
class RecallHit:
    kind: str  # "dead_end" | "winner_pattern"
    score: float  # cosine similarity in [-1, 1]
    text: str  # the human-readable note body
    ref: str  # the strategy_version_id (or note id) it came from
    structure: dict[str, Any]  # the structural fingerprint
    reasons: list[str]  # kill reasons (deaths) or empty (winners)


@dataclass(frozen=True)
class Recall:
    """The brain's read of long-term memory for one thesis/spec: relevant prior DEATHS (to avoid) + WINNERS
    (to lean toward). The author conditions on these; the deterministic scorer/Gate still dispose."""

    dead_ends: list[RecallHit]
    winners: list[RecallHit]

    @property
    def all_hits(self) -> list[RecallHit]:
        return [*self.dead_ends, *self.winners]


# --------------------------------------------------------------------------- the public API


@dataclass(frozen=True)
class GraveyardMemory:
    """Long-term memory bound to a Store. `remember(version, outcome)` persists a research note + embedding for a
    killed or surviving Version; `recall(thesis|spec)` returns the most relevant prior deaths + winners."""

    store: Store

    # -- write ---------------------------------------------------------------

    def remember(self, spec: StrategySpec, evaluated: Evaluated, *, created_at: str | None = None) -> str:
        """Persist ONE memory: a research note (winner structure or kill_reason) + a deterministic point-in-time
        embedding for the Version. `created_at` pins the as-of stamp (point-in-time; defaults to now). Idempotent
        per (version_id, kind) — re-remembering the same outcome updates in place rather than duplicating."""
        won = bool(evaluated.passed)
        kind = "winner" if won else "dead_end"
        fingerprint = structure_fingerprint(spec)
        text = _note_text(spec, evaluated, fingerprint)
        embedding = embed(_spec_text(spec) + " " + " ".join(evaluated.reasons))
        ts = created_at or utcnow()
        structured = {
            "outcome": kind,
            "version_id": evaluated.version_id,
            "name": evaluated.name,
            "origin": evaluated.origin,
            "deflated_sharpe": round(evaluated.deflated_sharpe, 6),
            "oos_return_pct": round(evaluated.oos_return_pct, 4),
            "reasons": list(evaluated.reasons),
            "structure": fingerprint,
        }
        existing = self.store.row(
            "SELECT id FROM research_notes WHERE strategy_version_id = ? AND kind = ?",
            (evaluated.version_id, kind),
        )
        emb = _encode_embedding(embedding, self.store)
        if existing:
            self.store.rows(
                "UPDATE research_notes SET body_md = ?, structured = ?, created_at = ?, embedding = ? WHERE id = ?",
                (text, json.dumps(structured, sort_keys=True), ts, emb, existing["id"]),
            )
            return str(existing["id"])
        return self.store.insert(
            "research_notes",
            {
                "strategy_version_id": evaluated.version_id,
                "kind": kind,
                "body_md": text,
                "structured": structured,
                "created_at": ts,
                "embedding": emb,
            },
        )

    # -- read ----------------------------------------------------------------

    def recall(self, query: str | StrategySpec, *, k: int = 5, as_of: str | None = None) -> Recall:
        """Return the k most relevant prior DEAD ENDS + WINNERS for a plain-text thesis or a StrategySpec.
        POINT-IN-TIME: with `as_of` set, only notes created strictly BEFORE it are visible (no look-ahead).
        Uses pgvector cosine on Postgres; pure-Python cosine over the stored JSON array on sqlite. Deterministic
        for a fixed memory + query."""
        from cosmu.strategy.spec import StrategySpec as _Spec  # local import to avoid a cycle

        text = _spec_text(query) if isinstance(query, _Spec) else str(query)
        qvec = embed(text)
        dead = self._search(qvec, kind="dead_end", k=k, as_of=as_of)
        winners = self._search(qvec, kind="winner", k=k, as_of=as_of)
        return Recall(dead_ends=dead, winners=winners)

    def _search(self, qvec: list[float], *, kind: str, k: int, as_of: str | None) -> list[RecallHit]:
        if self.store._is_pg:  # noqa: SLF001 — same package; backend selection mirrors store.connect()
            return self._search_pg(qvec, kind=kind, k=k, as_of=as_of)
        return self._search_sqlite(qvec, kind=kind, k=k, as_of=as_of)

    def _search_sqlite(self, qvec: list[float], *, kind: str, k: int, as_of: str | None) -> list[RecallHit]:
        clause = "kind = ?"
        params: list[Any] = [kind]
        if as_of is not None:
            clause += " AND created_at < ?"
            params.append(as_of)
        rows = self.store.rows(
            f"SELECT strategy_version_id, body_md, structured, embedding FROM research_notes WHERE {clause} AND embedding IS NOT NULL",
            tuple(params),
        )
        scored: list[RecallHit] = []
        for r in rows:
            try:
                vec = json.loads(r["embedding"])
            except (TypeError, json.JSONDecodeError):
                continue
            scored.append(_hit(kind, cosine(qvec, vec), r))
        scored.sort(key=lambda h: (h.score, h.ref), reverse=True)
        return scored[:k]

    def _search_pg(self, qvec: list[float], *, kind: str, k: int, as_of: str | None) -> list[RecallHit]:
        clause = "kind = %s"
        params: list[Any] = [kind]
        if as_of is not None:
            clause += " AND created_at < %s"
            params.append(as_of)
        literal = "[" + ",".join(repr(round(x, 8)) for x in qvec) + "]"
        # pgvector cosine distance (<=>) ascending → most-similar first. 1 - distance is the cosine similarity.
        rows = self.store.rows(
            f"""
            SELECT strategy_version_id, body_md, structured,
                   1 - (embedding <=> '{literal}') AS sim
            FROM research_notes
            WHERE {clause} AND embedding IS NOT NULL
            ORDER BY embedding <=> '{literal}' ASC
            LIMIT {int(k)}
            """,
            tuple(params),
        )
        return [_hit(kind, float(r.get("sim") or 0.0), r) for r in rows]


# --------------------------------------------------------------------------- helpers


def _encode_embedding(vec: list[float], store: Store) -> str:
    """pgvector accepts a '[..]' text literal on INSERT; sqlite stores the JSON array. Both round-trip."""
    if store._is_pg:  # noqa: SLF001
        return "[" + ",".join(repr(round(x, 8)) for x in vec) + "]"
    return json.dumps([round(x, 8) for x in vec])


def _note_text(spec: StrategySpec, evaluated: Evaluated, fingerprint: dict[str, Any]) -> str:
    feats = ", ".join(fingerprint["entry_features"]) or "-"
    mods = ", ".join(fingerprint["setup_modules"]) or "-"
    classes = "/".join(fingerprint["asset_classes"])
    if evaluated.passed:
        return (
            f"WINNER {evaluated.name}: {classes} {fingerprint['bar_size']} on features [{feats}], modules [{mods}] "
            f"cleared the gate (deflated_sharpe={evaluated.deflated_sharpe:.4f}, oos={evaluated.oos_return_pct:+.2f}%). "
            f"Lean toward this structure."
        )
    reasons = ", ".join(evaluated.reasons) or "screened_out"
    return (
        f"DEAD END {evaluated.name}: {classes} {fingerprint['bar_size']} on features [{feats}], modules [{mods}] "
        f"was killed by the gate ({reasons}). Avoid re-walking this structure."
    )


def _hit(kind: str, score: float, row: dict[str, Any]) -> RecallHit:
    structured = row.get("structured")
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except json.JSONDecodeError:
            structured = {}
    structured = structured or {}
    return RecallHit(
        kind="winner_pattern" if kind == "winner" else "dead_end",
        score=round(float(score), 6),
        text=row.get("body_md") or "",
        ref=str(row.get("strategy_version_id") or ""),
        structure=structured.get("structure", {}) if isinstance(structured, dict) else {},
        reasons=structured.get("reasons", []) if isinstance(structured, dict) else [],
    )


# --------------------------------------------------------------------------- novelty gate


def _feature_set(spec: StrategySpec) -> frozenset[str]:
    return frozenset(c.feature.name for c in spec.entry)


def structural_distance(a: StrategySpec, b: StrategySpec) -> float:
    """Jaccard distance over the entry-feature sets + bar_size penalty. 0 = identical structure, 1 = disjoint."""
    fa, fb = _feature_set(a), _feature_set(b)
    if not fa and not fb:
        return 0.0
    jaccard = len(fa & fb) / len(fa | fb) if (fa | fb) else 1.0
    bar_penalty = 0.0 if a.horizon.bar_size == b.horizon.bar_size else 0.15
    return round(1.0 - jaccard + bar_penalty, 6)


def complexity_score(spec: StrategySpec) -> int:
    """The number of entry conditions + signal exit conditions. More conditions = more overfitting surface."""
    return len(spec.entry) + len(spec.exit.signal_exits)


def novelty_gate(
    spec: StrategySpec,
    store: Store,
    *,
    live_specs: list[StrategySpec] | None = None,
    min_distance: float = 0.25,
    max_complexity: int = 6,
) -> tuple[bool, str]:
    """Check whether a candidate spec is sufficiently novel vs. (1) recent dead-ends in memory and
    (2) the live population. Returns (pass, reason). Deterministic, offline, no LLM."""
    cx = complexity_score(spec)
    if cx > max_complexity:
        return False, f"too_complex ({cx} conditions, max {max_complexity})"

    memory = GraveyardMemory(store)
    recall = memory.recall(spec, k=8)

    for hit in recall.dead_ends:
        feats = hit.structure.get("entry_features", [])
        if not feats:
            continue
        dead_features = frozenset(feats)
        spec_features = _feature_set(spec)
        if not spec_features:
            continue
        overlap = len(spec_features & dead_features) / len(spec_features | dead_features) if (spec_features | dead_features) else 0
        bar_match = hit.structure.get("bar_size") == spec.horizon.bar_size
        dist = 1.0 - overlap + (0.0 if bar_match else 0.15)
        if dist < min_distance:
            return False, f"too_similar_to_dead_end (dist={dist:.3f}, features={sorted(dead_features)})"

    if live_specs:
        # Reject if the candidate is too SIMILAR to ANY live spec — that is what actually prevents a
        # monoculture (admitting a near-duplicate of something already running). The prior logic was inverted:
        # it accepted as soon as the candidate was far from *some one* live spec, so in a diverse population
        # near-duplicates of an existing strategy sailed through (every candidate differs from at least one
        # member). Novel = distinct from EVERY live spec.
        for live in live_specs:
            dist = structural_distance(spec, live)
            if dist < min_distance:
                return False, f"monoculture (within dist {min_distance:.2f} of a live spec)"
        return True, "novel"

    return True, "novel"


def memory_insights(store: Store, *, limit: int = 12) -> list[dict[str, Any]]:
    """The GET /memory/insights feed: the most recent things the brain has LEARNED — dead-end structures to
    avoid and winning patterns to reuse. Read straight off the persisted notes (no recompute, no LLM)."""
    rows = store.rows(
        "SELECT strategy_version_id, kind, body_md FROM research_notes WHERE kind IN ('dead_end', 'winner') ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "kind": "winner_pattern" if r["kind"] == "winner" else "dead_end",
                "text": r["body_md"] or "",
                "ref": str(r["strategy_version_id"] or ""),
            }
        )
    return out
