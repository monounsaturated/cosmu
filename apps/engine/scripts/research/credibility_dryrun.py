# intent: OFFLINE dry-run of the dormant credibility / voices lane (cosmu.mind.{claims,outcomes,authority}) on REAL
# market data, with ZERO production impact — no prod schedule, no toggle, no Gate, no DB write. It constructs a small
# voice panel with KNOWN behaviors (a SNIPER who is early+right, a SPAMMER firing at the base rate, a LATE-FOLLOWER
# who only echoes a move after it has happened) whose claims are generated FROM the real OHLC bars we fetch keyless,
# then runs Phase 2 (deterministic outcome resolution + Brier-skill track record) and Phase 3 (primacy + lead-lag +
# skill-anchored authority) end-to-end and PRINTS: (1) the sample scoreboard, (2) the lead-lag SYMMETRY disconfirmer
# (the astro lesson — if a voice's "skill" is identical at lead h=+1 and lag h=-1 it is non-causal echo), (3) the
# authority-weighted per-entity signal. Run: `python3 -m scripts.research.credibility_dryrun` from apps/engine.
#
# This is a CHARACTERIZATION harness, not production code — it imports the lane unchanged and only reads bars.

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cosmu.data.market import Bar, default_crypto_reference
from cosmu.mind.authority import (
    Event,
    authority_weighted_signal,
    classify_lead_lag,
    compute_authority,
)
from cosmu.mind.claims import Claim, horizon_to_days
from cosmu.mind.outcomes import resolve_claims, score_authors

# The entities (and the venue symbol whose bars resolve their claims) we run the dry-run on.
ENTITY_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "DOGE": "DOGEUSDT"}
HORIZON = "3d"  # short, frequently-resolvable horizon
HORIZON_DAYS = horizon_to_days(HORIZON)


# --------------------------------------------------------------------------- real bars

def fetch_bars() -> dict[str, list[Bar]]:
    """Keyless daily bars for each entity (the REAL outcome timeline). ~400 daily bars (~13 months)."""
    prov = default_crypto_reference()
    out: dict[str, list[Bar]] = {}
    for entity, symbol in ENTITY_SYMBOL.items():
        bars = prov.fetch_bars(symbol, "1d", limit=400)
        if bars:
            out[entity] = sorted(bars, key=lambda b: b.ts)
    return out


def _ret(bars: list[Bar], i: int, horizon_days: int) -> float | None:
    """Realized fractional return from bar i to the first bar at/after i's ts + horizon."""
    target = bars[i].ts + timedelta(days=horizon_days)
    for j in range(i + 1, len(bars)):
        if bars[j].ts >= target:
            entry = float(bars[i].close)
            if entry == 0:
                return None
            return (float(bars[j].close) - entry) / entry
    return None


def _claim(handle: str, entity: str, direction: str, ts: datetime, *, conviction: float, pid: str) -> Claim:
    return Claim(
        handle=handle, platform="x", post_id=pid, entity=entity, direction=direction,
        horizon=HORIZON, horizon_days=HORIZON_DAYS, conviction=conviction, ts=ts,
    )


# --------------------------------------------------------------------------- the three KNOWN-behavior voices

# Each archetype's claims are GENERATED from the real bars, so the behavior is deliberate and verifiable:
#   SNIPER       — calls the direction the market WILL make, but ONLY on the rarest/biggest moves (a true call
#                  that beats the base rate). Early + right.
#   SPAMMER      — fires the SAME direction (the market's dominant drift) on many days. Often "right" in absolute
#                  terms but only at the base rate → no excess skill.
#   LATE-FOLLOWER— only speaks AFTER a move has already happened, claiming the move CONTINUES (momentum echo). Its
#                  call timestamp is placed at the END of a realized move; a 3d-forward call from there is roughly a
#                  coin flip — and, critically, its "skill" is symmetric in lead/lag (it is reacting, not foreseeing).

def build_panel_claims(bars_by_entity: dict[str, list[Bar]]) -> list[Claim]:
    claims: list[Claim] = []
    for entity, bars in bars_by_entity.items():
        n = len(bars)
        # Pre-compute forward returns and the dominant drift direction over the window.
        fwd = [(i, _ret(bars, i, HORIZON_DAYS)) for i in range(n)]
        fwd = [(i, r) for i, r in fwd if r is not None]
        if len(fwd) < 30:
            continue
        rets = [r for _, r in fwd]
        # Dominant drift: the most common realized 3d direction (the spammer parrots this).
        ups = sum(1 for r in rets if r > 0.01)
        downs = sum(1 for r in rets if r < -0.01)
        drift = "up" if ups >= downs else "down"

        # SNIPER: the biggest correct moves — call the direction of the largest-magnitude 3d windows. These are the
        # rare, hard, base-rate-beating calls. Take the top ~12 by |return|, claim their realized direction early.
        ranked = sorted(fwd, key=lambda t: abs(t[1]), reverse=True)[:12]
        for k, (i, r) in enumerate(ranked):
            d = "up" if r > 0 else "down"
            claims.append(_claim("@sniper", entity, d, bars[i].ts, conviction=0.9, pid=f"snipe-{entity}-{k}"))

        # SPAMMER: fire the dominant drift direction on ~50 distinct days. Loud, often right in a trending tape, but
        # only at the base rate.
        step = max(1, len(fwd) // 50)
        for k, (i, _r) in enumerate(fwd[::step]):
            claims.append(_claim("@spammer", entity, drift, bars[i].ts, conviction=0.85, pid=f"spam-{entity}-{k}"))

        # LATE-FOLLOWER: after each big realized move, post that the move CONTINUES (same direction). The claim ts is
        # placed at the END of the move (i + horizon), so it is reacting to news already on the tape — a momentum
        # echo, not foresight. Its forward 3d outcome from there is near a coin flip.
        for k, (i, r) in enumerate(ranked):
            end_i = min(n - 1, i + HORIZON_DAYS)
            d = "up" if r > 0 else "down"  # "the rally/dump keeps going"
            claims.append(_claim("@follower", entity, d, bars[end_i].ts, conviction=0.85, pid=f"foll-{entity}-{k}"))
    return claims


# --------------------------------------------------------------------------- a REAL event timeline (lead-lag input)

def build_events(bars_by_entity: dict[str, list[Bar]]) -> list[Event]:
    """A market-event timeline derived from the real bars: a dated Event at the END of each large realized 3d move
    (|return| over the top decile). A claim that PRECEDES a same-entity event led it (evidence/foresight); one that
    FOLLOWS it echoed it (reaction). The late-follower's calls are placed AFTER these events → they should classify
    as echoes; the sniper's calls precede them → evidence."""
    events: list[Event] = []
    for entity, bars in bars_by_entity.items():
        n = len(bars)
        moves = []
        for i in range(n):
            r = _ret(bars, i, HORIZON_DAYS)
            if r is not None:
                moves.append((i, abs(r)))
        if not moves:
            continue
        thresh = statistics.quantiles([m for _, m in moves], n=10)[-1]  # top decile magnitude
        for i, mag in moves:
            if mag >= thresh:
                end_i = min(n - 1, i + HORIZON_DAYS)
                events.append(Event(ts=bars[end_i].ts, entity=entity, label="big_move"))
    return events


# --------------------------------------------------------------------------- the lead-lag SYMMETRY disconfirmer

@dataclass
class SymmetryResult:
    handle: str
    skill_fwd: float        # Brier-skill resolving the claim FORWARD (real: entry now, exit at +horizon)
    skill_bwd: float        # Brier-skill resolving the SAME claim BACKWARD (entry at -horizon, exit now)
    asymmetry: float        # skill_fwd - skill_bwd. >0 = foresight (predicts the future). ~0 = non-causal echo.
    causal: bool            # asymmetry materially positive → a real forward forecaster, not a backward echo


def _backward_skill(claims: list[Claim], bars_by_entity: dict[str, list[Bar]], *, now: datetime) -> dict[str, float]:
    """Resolve each claim AGAINST THE PAST: does the claimed direction match the move that ALREADY happened over the
    horizon BEFORE the claim (exit = the claim's bar, entry = the bar one horizon earlier)? We build a mirror claim
    stamped one horizon earlier and resolve it forward to the original time — so 'backward skill' is just forward
    resolution on the time-reversed claim. A genuine forecaster has LOW backward skill (the past is not what it
    predicted); a late-follower that parrots a move already on the tape has HIGH backward skill."""
    mirror: list[Claim] = []
    for c in claims:
        mirror.append(Claim(
            handle=c.handle, platform=c.platform, post_id=c.post_id + "-bwd", entity=c.entity,
            direction=c.direction, horizon=c.horizon, horizon_days=c.horizon_days,
            conviction=c.conviction, ts=c.ts - timedelta(days=c.horizon_days),
        ))
    recs = score_authors(resolve_claims(mirror, bars_by_entity, now=now))
    return {h: r.skill for h, r in recs.items()}


def leadlag_symmetry(
    claims: list[Claim],
    bars_by_entity: dict[str, list[Bar]],
    *,
    as_of: datetime,
) -> dict[str, SymmetryResult]:
    """The astro lead-lag SYMMETRY test applied to voices. The astro lesson: if an apparent 'skill' is identical at
    lead h=+1 and lag h=-1, the relationship is non-causal (the signal is correlated with, not predictive of, the
    outcome). Here: resolve each voice's calls FORWARD (the real test — did the +horizon move match?) and BACKWARD
    (did the -horizon move that already happened match?). A genuine forecaster is ASYMMETRIC: high forward skill,
    chance-level backward skill. A late-follower that only echoes a move already on the tape is SYMMETRIC — its
    backward skill is as high or higher than its forward skill, because it is describing the past, not foreseeing
    the future. asymmetry = skill_fwd - skill_bwd; ~0 (or negative) is the non-causal echo tell."""
    fwd = {h: r.skill for h, r in score_authors(resolve_claims(claims, bars_by_entity, now=as_of)).items()}
    bwd = _backward_skill(claims, bars_by_entity, now=as_of)
    out: dict[str, SymmetryResult] = {}
    for handle in sorted(set(fwd) | set(bwd)):
        sf = fwd.get(handle, 0.0)
        sb = bwd.get(handle, 0.0)
        asym = sf - sb
        out[handle] = SymmetryResult(handle=handle, skill_fwd=sf, skill_bwd=sb, asymmetry=asym, causal=asym > 0.10)
    return out


# --------------------------------------------------------------------------- run

def main() -> int:
    bars = fetch_bars()
    if not bars:
        print("NO BARS — cannot run dry-run (need keyless market data).")
        return 1
    cover = ", ".join(f"{e}:{len(b)}b {b[0].ts.date()}->{b[-1].ts.date()}" for e, b in bars.items())
    print("=== REAL BARS (outcome timeline) ===")
    print(cover)

    claims = build_panel_claims(bars)
    events = build_events(bars)
    as_of = max(b[-1].ts for b in bars.values()) + timedelta(days=1)

    print(f"\n=== PANEL CLAIMS: {len(claims)} | EVENTS: {len(events)} | as_of {as_of.date()} ===")
    by_handle: dict[str, int] = {}
    for c in claims:
        by_handle[c.handle] = by_handle.get(c.handle, 0) + 1
    for h, n in sorted(by_handle.items()):
        print(f"  {h}: {n} claims")

    # --- Phase 2 + 3: deterministic scoring ---
    resolved = resolve_claims(claims, bars, now=as_of)
    records = score_authors(resolved)
    state = compute_authority(claims, bars_by_entity=bars, events=events, as_of=as_of)

    print("\n=== SAMPLE SCOREBOARD (Phase 2/3) ===")
    hdr = f"{'handle':<12}{'n_res':>6}{'hit':>7}{'base':>7}{'excess':>8}{'BSS':>8}{'skill':>8}{'authority':>11}{'primacy':>9}"
    print(hdr)
    for h in ("@sniper", "@spammer", "@follower"):
        r = records.get(h)
        auth = state.author_authority.get(h, 0.0)
        prim = state.primacy_rate.get(h, 0.0)
        if r is None:
            print(f"{h:<12}{'--':>6}")
            continue
        print(f"{h:<12}{r.n_resolved:>6}{r.hit_rate:>7.3f}{r.base_hit_rate:>7.3f}"
              f"{r.excess_hit_rate:>8.3f}{r.brier_skill_score:>8.3f}{r.skill:>8.3f}{auth:>11.4f}{prim:>9.3f}")

    # --- lead-lag symmetry disconfirmer ---
    print("\n=== LEAD-LAG SYMMETRY DISCONFIRMER (the astro test) ===")
    print("forward skill (predicts +horizon) vs backward skill (matches -horizon past). asymmetry≈0 = non-causal echo.")
    sym = leadlag_symmetry(claims, bars, as_of=as_of)
    print(f"{'handle':<12}{'skill_fwd':>11}{'skill_bwd':>11}{'asymmetry':>11}{'verdict':>16}")
    for h in ("@sniper", "@spammer", "@follower"):
        s = sym.get(h)
        if s is None:
            continue
        verdict = "CAUSAL(foresight)" if s.causal else "NON-CAUSAL echo"
        print(f"{h:<12}{s.skill_fwd:>11.3f}{s.skill_bwd:>11.3f}{s.asymmetry:>11.3f}{verdict:>16}")

    # --- shuffle null: a sniper with SHUFFLED directions must collapse to ~0 skill (the edge is in WHICH way,
    #     not in the timestamps). This is the third astro disconfirmer — destroy the claim→outcome link, keep the
    #     timing, and confirm the skill vanishes (so the 0.701 is the call, not the calendar). ---
    print("\n=== SHUFFLE NULL (sniper directions randomized; skill must collapse) ===")
    rng = random.Random(7)
    sniper_claims = [c for c in claims if c.handle == "@sniper"]
    dirs = [c.direction for c in sniper_claims]
    null_skills = []
    for _ in range(50):
        rng.shuffle(dirs)
        shuffled = [
            Claim(handle="@sniper_null", platform=c.platform, post_id=c.post_id + "-n", entity=c.entity,
                  direction=d, horizon=c.horizon, horizon_days=c.horizon_days, conviction=c.conviction, ts=c.ts)
            for c, d in zip(sniper_claims, dirs, strict=True)
        ]
        rec = score_authors(resolve_claims(shuffled, bars, now=as_of)).get("@sniper_null")
        null_skills.append(rec.skill if rec else 0.0)
    real_skill = records["@sniper"].skill
    null_mean = sum(null_skills) / len(null_skills)
    null_max = max(null_skills)
    p = (sum(1 for s in null_skills if s >= real_skill) + 1) / (len(null_skills) + 1)
    print(f"  real sniper skill = {real_skill:.3f} | shuffled-direction null: mean {null_mean:.3f}, "
          f"max {null_max:.3f} (n=50) | permutation p = {p:.3f}")
    print(f"  → {'PASS — skill is in the CALL, not the timing' if real_skill > null_max else 'FAIL — timing artifact'}")

    # --- point-in-time check: a snapshot mid-history must NOT see the future. Recompute the sniper's skill as_of a
    #     date BEFORE its later calls resolve and confirm only past-resolved claims count (no look-ahead). ---
    print("\n=== POINT-IN-TIME CHECK (mid-history snapshot ignores the future) ===")
    mid = bars["BTC"][len(bars["BTC"]) // 2].ts
    mid_state = compute_authority(claims, bars_by_entity=bars, events=events, as_of=mid)
    mid_rec = mid_state.track_records.get("@sniper")
    full_rec = records["@sniper"]
    mid_n = mid_rec.n_resolved if mid_rec else 0
    print(f"  as_of {mid.date()}: sniper has {mid_n} resolved claims; "
          f"as_of {as_of.date()}: {full_rec.n_resolved} resolved.")
    print(f"  → {'PASS — fewer claims resolved earlier (no look-ahead)' if mid_n < full_rec.n_resolved else 'CHECK'}")

    # --- the authority-weighted per-entity signal ---
    print("\n=== AUTHORITY-WEIGHTED SIGNAL per entity (credibility-weighted consensus) ===")
    for entity in sorted(bars):
        sig = authority_weighted_signal(state, entity, as_of=as_of)
        print(f"  {entity}: {sig if sig is None else round(sig, 4)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
