# intent: PHASE 3 of "PageRank for credibility" — PRIMACY + AUTHORITY. Deterministic, NO LLM. Three signals fuse
# into a credibility weight per voice and a per-asset signal:
#   (1) PRIMACY — who said it FIRST. Group claims by (entity, direction); the earliest in a window is primary, the
#       rest are ECHOES (down-weighted). Being first earns credit; being loud later does not.
#   (2) LEAD-LAG vs an EVENT TIMELINE (GDELT/news/on-chain) — a claim that PRECEDES the event is EVIDENCE
#       (foresight); one that FOLLOWS it is an ECHO (reacting to news). This separates a voice that breaks a move
#       from one that parrots it.
#   (3) CITATION-GRAPH PAGERANK anchored to the Phase-2 track record — personalized PageRank whose teleport mass is
#       each voice's deterministic `skill` (Brier-skill vs base, sample-shrunk). Authority flows along who-cites-whom
#       but is ANCHORED to proven skill, so INFLUENCE ≠ AUTHORITY: a loud, well-cited, but WRONG account (skill ~ 0)
#       cited only by other noise accumulates ~no authority; a quiet, calibrated voice does.
# From these we emit two POINT-IN-TIME features WITH HISTORY: author_authority[handle] and
# authority_weighted_claim_signal[entity]. inputs: Phase-1 claims + OHLC bars (for Phase-2 resolution) + the Phase-0
# posts (citation edges) + an event timeline + an injected `as_of`; outputs: an AuthorityState + per-entity signal +
# an AltDataProvider/PIT-history seam. invariants: PURE + offline + deterministic (the clock is injected); every
# read is POINT-IN-TIME — a snapshot as_of t uses ONLY claims/posts/events with ts <= t and outcomes resolved with
# now = t (no look-ahead); availability == observation (a real-time judgement is knowable only when made); honest —
# no claims → empty, never a fabricated authority.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar
from cosmu.mind.claims import Claim, VoicePost
from cosmu.mind.outcomes import AuthorTrackRecord, resolve_claims, score_authors

# Frozen, versioned transform — pinned into the emitted PIT features so a gate-passed survivor stays reproducible.
AUTHORITY_VERSION = "social-authority-v1"

# Defaults (policy constants — NEVER enter a strategy spec). A "primacy window": two same-direction calls on the
# same entity within this span are the same idea, so only the first is primary. A "signal window": only claims
# this recent feed the live per-entity signal. Lead/lag windows: how close to an event a claim must be to count as
# evidence (foresight) or echo (reaction).
PRIMACY_WINDOW_DAYS = 7.0
SIGNAL_WINDOW_DAYS = 30.0
LEAD_WINDOW_DAYS = 7.0
LAG_WINDOW_DAYS = 3.0

# Down-weights. An echo (not first / reacting to news) still counts, but less than original evidence.
ECHO_DISCOUNT = 0.4
NEUTRAL_LEADLAG = 0.75  # a claim with no nearby event is neither evidence nor echo — mild discount

_PR_DAMPING = 0.85
_PR_ITERATIONS = 100
_PR_TOL = 1e-12

_DIR_SIGN = {"up": 1.0, "down": -1.0, "flat": 0.0}


# --------------------------------------------------------------------------- the event timeline (lead-lag input)


@dataclass(frozen=True)
class Event:
    """One dated market event from an EXTERNAL timeline (GDELT headline, on-chain print, news wire). A claim that
    precedes a same-entity event is evidence; one that follows it is an echo. `ts` is the event's availability."""

    ts: datetime
    entity: str
    label: str = ""


# --------------------------------------------------------------------------- per-claim primacy / lead-lag context


@dataclass(frozen=True)
class ClaimContext:
    """A claim annotated with WHO-FIRST + EVIDENCE-vs-ECHO. `is_primary`: first to make this (entity, direction)
    call within the primacy window. `lead_seconds`: how long before the next echo of it (None if none). `lead_lag`:
    'evidence' (claim led an event), 'echo' (claim followed an event), or 'none' (no nearby event)."""

    claim: Claim
    is_primary: bool
    lead_seconds: float | None
    lead_lag: str  # "evidence" | "echo" | "none"


def annotate_primacy(claims: list[Claim], *, window_days: float = PRIMACY_WINDOW_DAYS) -> dict[str, bool]:
    """Mark each claim primary/echo by (entity, direction). The earliest call in a window is primary; a later same
    call within `window_days` is an echo of it; a same call beyond the window opens a fresh primary. Returns a map
    keyed by a stable claim identity → is_primary."""
    window = timedelta(days=window_days)
    by_topic: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        by_topic[(c.entity, c.direction)].append(c)
    is_primary: dict[str, bool] = {}
    for topic_claims in by_topic.values():
        topic_claims = sorted(topic_claims, key=lambda c: (c.ts, c.handle, c.post_id))
        anchor_ts: datetime | None = None
        for c in topic_claims:
            if anchor_ts is None or (c.ts - anchor_ts) > window:
                is_primary[_claim_key(c)] = True
                anchor_ts = c.ts
            else:
                is_primary[_claim_key(c)] = False
    return is_primary


def _claim_key(c: Claim) -> str:
    return f"{c.handle}|{c.platform}|{c.post_id}|{c.entity}|{c.direction}|{c.ts.isoformat()}"


def _lead_seconds(claims: list[Claim], claim: Claim, *, window_days: float) -> float | None:
    """Seconds from `claim` to the NEXT same-(entity,direction) call within the window (None if no echo)."""
    window = timedelta(days=window_days)
    nxt: datetime | None = None
    for c in claims:
        if c.entity == claim.entity and c.direction == claim.direction and c.ts > claim.ts and (c.ts - claim.ts) <= window:
            if nxt is None or c.ts < nxt:
                nxt = c.ts
    return (nxt - claim.ts).total_seconds() if nxt is not None else None


def classify_lead_lag(
    claim: Claim,
    events: list[Event],
    *,
    lead_window_days: float = LEAD_WINDOW_DAYS,
    lag_window_days: float = LAG_WINDOW_DAYS,
) -> str:
    """'evidence' if a same-entity event falls just AFTER the claim (the voice called it first), 'echo' if one
    falls just BEFORE (the voice reacted to it), else 'none'. Forward (foresight) takes priority over backward."""
    lead = timedelta(days=lead_window_days)
    lag = timedelta(days=lag_window_days)
    led = False
    echoed = False
    for e in events:
        if e.entity != claim.entity:
            continue
        if claim.ts < e.ts <= claim.ts + lead:
            led = True
        elif claim.ts - lag <= e.ts < claim.ts:
            echoed = True
    if led:
        return "evidence"
    if echoed:
        return "echo"
    return "none"


def build_contexts(
    claims: list[Claim],
    events: list[Event],
    *,
    primacy_window_days: float = PRIMACY_WINDOW_DAYS,
    lead_window_days: float = LEAD_WINDOW_DAYS,
    lag_window_days: float = LAG_WINDOW_DAYS,
) -> list[ClaimContext]:
    """Annotate every claim with primacy + lead-lag. Deterministic order by (ts, handle, post_id)."""
    primary = annotate_primacy(claims, window_days=primacy_window_days)
    out: list[ClaimContext] = []
    for c in sorted(claims, key=lambda c: (c.ts, c.handle, c.post_id, c.entity, c.direction)):
        out.append(ClaimContext(
            claim=c,
            is_primary=primary.get(_claim_key(c), True),
            lead_seconds=_lead_seconds(claims, c, window_days=primacy_window_days),
            lead_lag=classify_lead_lag(c, events, lead_window_days=lead_window_days, lag_window_days=lag_window_days),
        ))
    return out


# --------------------------------------------------------------------------- citation graph + personalized PageRank


def build_citation_edges(posts: list[VoicePost]) -> list[tuple[str, str]]:
    """Directed (citing_handle → cited_handle) edges from each post's `refs` (post_ids / urls it cites or quotes).
    A ref is resolved to its author via the post_id / url maps built from all posts; self-citations are dropped."""
    by_id: dict[str, str] = {}
    for p in posts:
        by_id[p.post_id] = p.handle
        if p.url:
            by_id[p.url] = p.handle
    edges: list[tuple[str, str]] = []
    for p in posts:
        for ref in p.refs:
            cited = by_id.get(ref)
            if cited and cited != p.handle:
                edges.append((p.handle, cited))
    return edges


def personalized_pagerank(
    nodes: list[str],
    edges: list[tuple[str, str]],
    personalization: dict[str, float],
    *,
    damping: float = _PR_DAMPING,
    iterations: int = _PR_ITERATIONS,
    tol: float = _PR_TOL,
) -> dict[str, float]:
    """Deterministic personalized PageRank (power iteration, stdlib). The teleport vector is `personalization`
    (here: each voice's deterministic skill), so rank is ANCHORED to proven track record, not raw citation volume.
    A node with zero personalization gains rank ONLY through incoming citations from nodes that themselves have
    rank — so a loud account cited only by zero-skill noise stays near zero (influence ≠ authority)."""
    nodes = sorted(set(nodes) | {n for e in edges for n in e})
    if not nodes:
        return {}
    n = len(nodes)
    # Teleport distribution p: ∝ personalization, uniform if it is all-zero (no proven skill anywhere yet).
    raw = {node: max(0.0, float(personalization.get(node, 0.0))) for node in nodes}
    s = sum(raw.values())
    p = {node: (raw[node] / s) if s > 0 else (1.0 / n) for node in nodes}
    out_links: dict[str, list[str]] = defaultdict(list)
    for u, v in edges:
        out_links[u].append(v)
    rank = {node: 1.0 / n for node in nodes}
    for _ in range(iterations):
        nxt = {node: (1.0 - damping) * p[node] for node in nodes}
        dangling = 0.0
        for node in nodes:
            outs = out_links.get(node)
            if not outs:
                dangling += rank[node]
                continue
            share = damping * rank[node] / len(outs)
            for v in outs:
                nxt[v] += share
        # Dangling mass is redistributed by the teleport vector (standard handling).
        for node in nodes:
            nxt[node] += damping * dangling * p[node]
        delta = sum(abs(nxt[node] - rank[node]) for node in nodes)
        rank = nxt
        if delta < tol:
            break
    total = sum(rank.values()) or 1.0
    return {node: rank[node] / total for node in nodes}


# --------------------------------------------------------------------------- the fused authority state (PIT snapshot)


@dataclass(frozen=True)
class AuthorityState:
    """A point-in-time credibility snapshot as_of a time. `author_authority` is the personalized-PageRank weight
    per handle (anchored to the deterministic track record); `track_records` is the Phase-2 record per handle;
    `contexts` is every known claim annotated with primacy + lead-lag; `primacy_rate` / `evidence_rate` are the
    per-handle summaries. Built ONLY from information knowable at `as_of` — no look-ahead."""

    as_of: datetime
    author_authority: dict[str, float]
    track_records: dict[str, AuthorTrackRecord]
    contexts: list[ClaimContext]
    primacy_rate: dict[str, float]
    evidence_rate: dict[str, float]


def _rates(contexts: list[ClaimContext]) -> tuple[dict[str, float], dict[str, float]]:
    """Per-handle primacy rate (primary / total) and evidence rate (evidence / (evidence + echo))."""
    prim_n: dict[str, int] = defaultdict(int)
    prim_d: dict[str, int] = defaultdict(int)
    ev_n: dict[str, int] = defaultdict(int)
    ev_d: dict[str, int] = defaultdict(int)
    for ctx in contexts:
        h = ctx.claim.handle
        prim_d[h] += 1
        if ctx.is_primary:
            prim_n[h] += 1
        if ctx.lead_lag in ("evidence", "echo"):
            ev_d[h] += 1
            if ctx.lead_lag == "evidence":
                ev_n[h] += 1
    primacy_rate = {h: prim_n[h] / prim_d[h] for h in prim_d}
    evidence_rate = {h: (ev_n[h] / ev_d[h]) if ev_d[h] else 0.5 for h in prim_d}
    return primacy_rate, evidence_rate


def compute_authority(
    claims: list[Claim],
    *,
    bars_by_entity: dict[str, list[Bar]],
    posts: list[VoicePost] | None = None,
    events: list[Event] | None = None,
    as_of: datetime,
    primacy_window_days: float = PRIMACY_WINDOW_DAYS,
    lead_window_days: float = LEAD_WINDOW_DAYS,
    lag_window_days: float = LAG_WINDOW_DAYS,
) -> AuthorityState:
    """Fuse track record + primacy + lead-lag + citation graph into a POINT-IN-TIME authority snapshot. Only
    claims/posts/events knowable at `as_of` are used, and outcomes are resolved with now = as_of (no look-ahead).
    author_authority = personalized PageRank over the citation graph with teleport ∝ the deterministic skill."""
    posts = posts or []
    events = events or []
    known_claims = [c for c in claims if c.ts <= as_of]
    known_posts = [p for p in posts if p.ts <= as_of]
    known_events = [e for e in events if e.ts <= as_of]

    # Phase-2 track record, resolved strictly as-of now (only outcomes observed by `as_of` count).
    resolved = resolve_claims(known_claims, bars_by_entity, now=as_of)
    track_records = score_authors(resolved)
    skill = {h: rec.skill for h, rec in track_records.items()}

    # Citation graph anchored to skill. Nodes include every voice that has spoken or posted by now.
    nodes = sorted({c.handle for c in known_claims} | {p.handle for p in known_posts})
    edges = build_citation_edges(known_posts)
    authority = personalized_pagerank(nodes, edges, skill)

    contexts = build_contexts(
        known_claims, known_events,
        primacy_window_days=primacy_window_days, lead_window_days=lead_window_days, lag_window_days=lag_window_days,
    )
    primacy_rate, evidence_rate = _rates(contexts)
    return AuthorityState(
        as_of=as_of, author_authority=authority, track_records=track_records,
        contexts=contexts, primacy_rate=primacy_rate, evidence_rate=evidence_rate,
    )


# --------------------------------------------------------------------------- the per-entity authority-weighted signal


def _leadlag_weight(lead_lag: str) -> float:
    if lead_lag == "evidence":
        return 1.0
    if lead_lag == "echo":
        return ECHO_DISCOUNT
    return NEUTRAL_LEADLAG


def authority_weighted_signal(
    state: AuthorityState,
    entity: str,
    *,
    as_of: datetime,
    window_days: float = SIGNAL_WINDOW_DAYS,
) -> float | None:
    """The authority-weighted directional signal for one entity in [-1, +1] — a credibility-weighted consensus of
    the recent claims on it. Each claim's vote (+1 up / -1 down / 0 flat) is weighted by its author's authority ×
    conviction × primacy × evidence-vs-echo. A primary, foresightful call by a high-authority voice dominates;
    an echo by a loud-but-low-authority account barely registers. None when no claim is active (honest abstain)."""
    window = timedelta(days=window_days)
    num = 0.0
    den = 0.0
    for ctx in state.contexts:
        c = ctx.claim
        if c.entity != entity or c.ts > as_of or (as_of - c.ts) > window:
            continue
        w = (
            state.author_authority.get(c.handle, 0.0)
            * float(c.conviction)
            * (1.0 if ctx.is_primary else ECHO_DISCOUNT)
            * _leadlag_weight(ctx.lead_lag)
        )
        if w <= 0.0:
            continue
        num += w * _DIR_SIGN[c.direction]
        den += w
    if den <= 0.0:
        return None
    return num / den


# --------------------------------------------------------------------------- POINT-IN-TIME history + provider seam


def signal_history(
    claims: list[Claim],
    *,
    bars_by_entity: dict[str, list[Bar]],
    entity: str,
    start: datetime,
    end: datetime,
    posts: list[VoicePost] | None = None,
    events: list[Event] | None = None,
    step: timedelta = timedelta(days=1),
    window_days: float = SIGNAL_WINDOW_DAYS,
) -> list[AltDataPoint]:
    """Build the POINT-IN-TIME history of authority_weighted_claim_signal[entity] by recomputing the snapshot at
    each step t and emitting one AltDataPoint stamped (ts == available_at == t) — a real-time judgement is knowable
    only when made, so there is NO look-ahead. This is the series the gate trains on and `profile-source` audits.
    Days with no active claim are skipped (honest — we emit nothing rather than a fabricated zero)."""
    out: list[AltDataPoint] = []
    t = start
    while t <= end:
        state = compute_authority(claims, bars_by_entity=bars_by_entity, posts=posts, events=events, as_of=t)
        v = authority_weighted_signal(state, entity, as_of=t, window_days=window_days)
        if v is not None:
            out.append(AltDataPoint(ts=t, available_at=t, value=float(v)))
        t += step
    return out


@dataclass
class AuthorityProvider:
    """The AltDataProvider that emits the social-authority PIT features. `fetch_series(symbol, metric)`:
      - metric == 'authority_weighted_claim_signal' → symbol is the ENTITY; emits one point (signal as_of now).
      - metric == 'author_authority'                → symbol is the HANDLE; emits one point (that voice's authority).
    Availability == observation (now): a real-time credibility judgement is knowable only when made (no look-ahead).
    Over many cron passes the append-only store accumulates a real series WITH HISTORY for the gate to train on.
    HONEST DEGRADATION: with no claims (Phase 0 ingested nothing) `fetch_series` returns [] — never a fabricated
    authority. Offline-testable: inject claims/bars/posts/events + a fixed `now`."""

    claims: list[Claim]
    bars_by_entity: dict[str, list[Bar]]
    posts: list[VoicePost] | None = None
    events: list[Event] | None = None
    window_days: float = SIGNAL_WINDOW_DAYS
    now: datetime | None = None

    def _now(self) -> datetime:
        return self.now or datetime.now(tz=UTC)

    def fetch_series(self, symbol: str, metric: str, *, limit: int, since: "datetime | None" = None) -> list[AltDataPoint]:
        if metric not in ("authority_weighted_claim_signal", "author_authority"):
            return []
        if not self.claims:  # no Phase-0 timeline → honest degradation (never a fabricated authority)
            return []
        now = self._now()
        state = compute_authority(self.claims, bars_by_entity=self.bars_by_entity, posts=self.posts, events=self.events, as_of=now)
        if metric == "author_authority":
            value = state.author_authority.get(symbol)
        else:
            value = authority_weighted_signal(state, symbol, as_of=now, window_days=self.window_days)
        if value is None:
            return []
        pts = [AltDataPoint(ts=now, available_at=now, value=float(value))]
        return pts[-limit:] if limit > 0 else []
