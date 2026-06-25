# intent: the STANDING leakage tripwire — the #1 blow-up guard. A look-ahead/alignment bug UPSTREAM of the Gate
# is Gate-INVISIBLE (the Gate validates edge-after-costs, NOT pipeline honesty): it produces a survivor that is
# genuinely real on paper and zero/negative live. This module bundles THREE independent disconfirmers into ONE
# PASS/FAIL report a NEW data source MUST clear before it is trusted as a feature ([[vibe_coding_leakage_risk]]):
#
#   (1) AVAILABLE_AT AUDIT  — the align_asof PIT join is strictly BACKWARD-looking: NO feature value is ever
#       joined to a bar whose ts < that value's available_at. Brute-verified against the points themselves, so
#       a join that ever peeked a not-yet-published value is caught directly (not inferred from an IC).
#   (2) SHUFFLE-NULL        — permute the feature's VALUES in time (break the real time-alignment, keep the
#       marginal distribution) → its IC vs forward returns must COLLAPSE toward 0. An IC that SURVIVES the
#       shuffle reflects a genuine feature→return alignment; an IC inside the shuffled band is a noise /
#       autocorrelation artefact, never an edge (BlindTrade: IC 0.015 → 0.0004 under shuffle).
#   (3) FORWARD-SHIFT SANITY — shifting the feature +1 bar (using TOMORROW's value TODAY) must IMPROVE in-sample
#       fit (|IC| rises) — that is the honest direction of cheating, and it MUST help. If instead shifting the
#       feature BACKWARD (a MORE honest, more-lagged read) improves the fit, the live wiring is ALREADY peeking
#       at the future: the as-of alignment is too-early by a bar, so de-leaking it (lagging) helps. That is the
#       fingerprint of a baked-in look-ahead the AVAILABLE_AT audit can miss when available_at itself is wrong.
#
# Each check is NECESSARY, never sufficient — surviving the tripwire is the price of admission to the Gate, which
# alone disposes (PROPOSE-ONLY). PURE + OFFLINE: operates on AltDataPoint lists + Bar lists already read
# point-in-time, reuses align_asof (the SAME join the backtest runs) + spearman_ic + the shuffle_null harness
# (never a second hand-rolled correlation). No I/O, no DB, no settings, no LLM. Changes NO Gate constant.
#
# Entry points:
#   audit_feature(points, bars, horizon=...) -> TripwireReport   (the programmatic gate the edge lane calls)
#   python -m cosmu.research.leakage_tripwire <feature>          (CLI: runs the three checks on offline data)

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.disconfirmers import ShuffleNullResult, pit_ic, shuffle_null

# The forward-shift sanity needs a real margin before it accuses the wiring of peeking: a backward-shifted IC
# must beat the live IC by MORE than this fraction (and the live IC must already be a real signal) before we call
# it look-ahead. Keeps tiny estimation noise on a near-zero IC from tripping the alarm. Tunable, conservative.
_FORWARD_SHIFT_MARGIN: float = 0.15  # backward |IC| must exceed live |IC| by >15% to flag a peek
_FORWARD_SHIFT_MIN_LIVE_IC: float = 0.05  # below this the live IC is too weak to reason about its shift direction


# ---------------------------------------------------------------- (1) AVAILABLE_AT AUDIT (strict backward-look)


@dataclass(frozen=True)
class AvailableAtResult:
    n_joined: int                 # how many bars received a value from align_asof
    n_checked: int                # how many of those we re-derived from the raw points (== n_joined)
    violations: int               # bars that carry a value with NO point available_at <= bar.ts (LOOK-AHEAD)
    mismatches: int               # bars whose joined value != the latest-available point's value (wrong winner)
    passed: bool                  # zero violations AND zero mismatches — the join is strictly as-of

    @property
    def summary(self) -> str:
        return (
            f"available_at audit: {self.n_joined} bars joined, "
            f"{self.violations} look-ahead, {self.mismatches} wrong-winner"
        )


def available_at_audit(points: list[AltDataPoint], bars: list[Bar]) -> AvailableAtResult:
    """Assert the align_asof join is strictly BACKWARD-looking: for every bar that received a value, that value
    must be reproducible from ONLY the points whose available_at <= bar.ts, and it must be the LATEST such point.
    A value present on a bar with no point available by then is a LOOK-AHEAD (a future publish leaked); a value
    that is not the latest-available revision is a wrong-winner (the join picked a stale or future revision).

    This audits the ACTUAL join the backtest runs (align_asof), against the raw points, so it catches a leak in
    the join itself — independent of any IC. Pure + deterministic."""
    joined = align_asof(points, bars)
    violations = 0
    mismatches = 0
    n_checked = 0
    for bar in bars:
        key = bar.ts.isoformat()
        if key not in joined:
            continue
        n_checked += 1
        available = [p for p in points if p.available_at <= bar.ts]
        if not available:
            violations += 1  # a value present with nothing knowable by this bar = look-ahead
            continue
        # The honest winner is the latest-available point; align_asof must agree (value, not identity).
        expected = max(available, key=lambda p: p.available_at).value
        if joined[key] != expected:
            mismatches += 1
    return AvailableAtResult(
        n_joined=len(joined),
        n_checked=n_checked,
        violations=violations,
        mismatches=mismatches,
        passed=(violations == 0 and mismatches == 0),
    )


# ---------------------------------------------------------------- (3) FORWARD-SHIFT SANITY (peek-direction probe)


def _shift_points(points: list[AltDataPoint], bars: list[Bar], k: int) -> list[AltDataPoint]:
    """Re-stamp the PIT-joined feature series shifted by `k` bars, then return it as AltDataPoints whose
    available_at == the new bar.ts (so the same align_asof + pit_ic machinery scores it).

    k = +1 uses bar t's feature value on bar t-1 — i.e. TOMORROW's value TODAY (the honest direction of
    cheating: this should HELP in-sample because it is a 1-bar look-ahead). k = -1 lags the feature one extra
    bar (a MORE honest read). We score on the SAME bar grid, so the comparison isolates the shift's direction.

    Built from the as-of JOIN (not the raw points) so the shift operates on the value each bar actually sees —
    the quantity the live wiring would peek. A bar with no shifted partner is dropped (no fabricated value)."""
    joined = align_asof(points, bars)
    by_ts = [(bar.ts, joined.get(bar.ts.isoformat())) for bar in bars]
    out: list[AltDataPoint] = []
    n = len(by_ts)
    for i in range(n):
        src = i + k  # the bar whose value lands on bar i (k>0 pulls a FUTURE bar's value back onto bar i)
        if 0 <= src < n:
            ts_i, _ = by_ts[i]
            _, v_src = by_ts[src]
            if v_src is not None:
                out.append(AltDataPoint(ts=ts_i, available_at=ts_i, value=v_src))
    return out


@dataclass(frozen=True)
class ForwardShiftResult:
    live_ic: float                # |IC| of the feature as wired (align_asof live)
    forward_ic: float             # |IC| when shifted +1 bar (tomorrow's value today — the honest cheat)
    backward_ic: float            # |IC| when shifted -1 bar (a MORE honest / extra-lagged read)
    n_obs: int
    forward_improves: bool        # +1 shift raised |IC| (the expected, healthy direction)
    backward_improves: bool       # -1 shift raised |IC| materially over live — the look-ahead fingerprint
    passed: bool                  # NOT (backward materially beats live) — live wiring is not peeking

    @property
    def summary(self) -> str:
        return (
            f"forward-shift: live|IC|={self.live_ic:.4f} "
            f"(+1 cheat={self.forward_ic:.4f}, -1 honest={self.backward_ic:.4f})"
        )


def forward_shift_sanity(
    points: list[AltDataPoint],
    bars: list[Bar],
    horizon: int,
    *,
    margin: float = _FORWARD_SHIFT_MARGIN,
    min_live_ic: float = _FORWARD_SHIFT_MIN_LIVE_IC,
) -> ForwardShiftResult:
    """Forward-shift sanity (tripwire item 3). Score |IC| three ways on the same bar grid: as-wired (live),
    shifted +1 bar (tomorrow's value today — a deliberate 1-bar look-ahead), and shifted -1 bar (an extra-lagged,
    MORE honest read).

    Healthy wiring: the +1 CHEAT improves the fit (look-ahead always helps), and lagging it -1 does NOT improve
    over the live alignment. The leak fingerprint this catches: when the live alignment is ALREADY a bar too
    early (a baked-in look-ahead available_at itself didn't reveal), de-leaking it by lagging -1 bar IMPROVES the
    fit — because the live read was peeking. We flag `passed=False` only when the backward (more-honest) read
    materially beats the live read (by > `margin`) AND the live IC is strong enough (`min_live_ic`) to reason
    about its shift direction — so estimation noise on a dead feature never trips the alarm."""
    live_ic, n = pit_ic(points, bars, horizon)
    fwd_pts = _shift_points(points, bars, +1)
    bwd_pts = _shift_points(points, bars, -1)
    fwd_ic, _fn = pit_ic(fwd_pts, bars, horizon)
    bwd_ic, _bn = pit_ic(bwd_pts, bars, horizon)
    a_live, a_fwd, a_bwd = abs(live_ic), abs(fwd_ic), abs(bwd_ic)
    forward_improves = a_fwd > a_live
    # Backward "improves" = the more-honest lag materially beats the live read → the live read was peeking.
    backward_improves = a_live >= min_live_ic and a_bwd > a_live * (1.0 + margin)
    return ForwardShiftResult(
        live_ic=round(a_live, 6),
        forward_ic=round(a_fwd, 6),
        backward_ic=round(a_bwd, 6),
        n_obs=n,
        forward_improves=forward_improves,
        backward_improves=backward_improves,
        passed=not backward_improves,
    )


# ---------------------------------------------------------------- the bundled report


@dataclass(frozen=True)
class TripwireReport:
    """The PASS/FAIL verdict over the three independent disconfirmers. `passed` is the AND of all three: a NEW
    source must clear EVERY check before the edge lane trusts it as a feature. A FAIL names the disconfirmer
    that caught it (`failed_checks`) so the operator fixes the right surface (look-ahead vs spurious IC vs
    baked-in peek). PROPOSE-ONLY: a PASS is necessary, never sufficient — the Gate alone disposes."""

    feature: str
    n_obs: int
    real_ic: float
    available_at: AvailableAtResult
    shuffle: ShuffleNullResult
    forward_shift: ForwardShiftResult
    passed: bool
    failed_checks: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """A human-readable multi-line report (the CLI body)."""
        verdict = "PASS" if self.passed else "FAIL"
        lines = [
            f"LEAKAGE TRIPWIRE — {self.feature}: {verdict}  (n_obs={self.n_obs}, real_ic={self.real_ic:+.4f})",
            f"  [1] {self.available_at.summary}"
            f"  -> {'PASS' if self.available_at.passed else 'FAIL'}",
            f"  [2] shuffle-null: real|IC|={abs(self.real_ic):.4f}, "
            f"null_mean|IC|={self.shuffle.null_mean_abs:.4f}, p={self.shuffle.p_value:.4f}"
            f"  -> {'PASS (survives, collapsed)' if self.shuffle.survives else 'FAIL (IC inside shuffled band)'}",
            f"  [3] {self.forward_shift.summary}"
            f"  -> {'PASS' if self.forward_shift.passed else 'FAIL (lagging the feature improves fit = live peek)'}",
        ]
        if self.failed_checks:
            lines.append(f"  FAILED: {', '.join(self.failed_checks)}")
        return "\n".join(lines)


def audit_feature(
    points: list[AltDataPoint],
    bars: list[Bar],
    *,
    horizon: int = 1,
    feature: str = "feature",
    shuffle_trials: int = 200,
    seed: int = 0,
    alpha: float = 0.05,
    require_shuffle_survival: bool = True,
) -> TripwireReport:
    """Run the three-disconfirmer leakage tripwire on one feature's PIT-stamped points against `bars`, returning
    a PASS/FAIL TripwireReport. The single front door the edge lane gates a NEW source on.

    Checks (all must pass for `passed=True`):
      [1] available_at audit  — align_asof is strictly backward-looking (zero look-ahead in the join).
      [2] shuffle-null        — the IC survives a time-shuffle (genuine alignment, not a noise artefact).
      [3] forward-shift sanity — lagging the feature does NOT beat the live read (no baked-in look-ahead).

    `require_shuffle_survival` (default True) makes a feature whose IC collapses INTO the shuffled band a FAIL —
    a "signal" indistinguishable from noise is not trustworthy. Set False to treat the shuffle as advisory (the
    audit then only fails on a positive look-ahead, [1] or [3]); the report still records the shuffle verdict.

    PURE + deterministic for fixed (points, bars, seed, trials). Reuses align_asof + spearman_ic + the
    shuffle_null harness — never a second hand-rolled correlation. Changes NO Gate constant."""
    real_ic, n = pit_ic(points, bars, horizon)
    a1 = available_at_audit(points, bars)
    a2 = shuffle_null(points, bars, horizon, trials=shuffle_trials, seed=seed, alpha=alpha)
    a3 = forward_shift_sanity(points, bars, horizon)

    failed: list[str] = []
    if not a1.passed:
        failed.append("available_at_audit")
    if require_shuffle_survival and not a2.survives:
        failed.append("shuffle_null")
    if not a3.passed:
        failed.append("forward_shift_sanity")

    return TripwireReport(
        feature=feature,
        n_obs=n,
        real_ic=real_ic,
        available_at=a1,
        shuffle=a2,
        forward_shift=a3,
        passed=not failed,
        failed_checks=tuple(failed),
    )


__all__ = [
    "AvailableAtResult",
    "ForwardShiftResult",
    "TripwireReport",
    "audit_feature",
    "available_at_audit",
    "forward_shift_sanity",
]


# ---------------------------------------------------------------- CLI (offline; no network, no DB, no Binance)


def _synthetic_market(
    n: int = 600, *, seed: int = 7, phi: float = 0.85, beta: float = 0.02
) -> tuple[list[float], list[Bar]]:
    """Deterministic offline market: a SMOOTH (AR(1)) latent feature series + a price path whose return from bar
    t to t+1 is driven by the feature value AT bar t. AR(1) makes neighbouring feature values correlated, so a
    1-bar misalignment DEGRADES the IC instead of destroying it — exactly what lets the forward-shift sanity see
    a peek (a leaked too-early read stays strong, and lagging it back recovers the true peak). Returns the raw
    feature_vals + the bars. Offline + pure (keyless; no Binance — the M2 is geo-blocked)."""
    import random
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    rng = random.Random(f"tripwire-market-{seed}")
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    feature_vals: list[float] = []
    x = 0.0
    for _ in range(n):
        x = phi * x + rng.gauss(0, 1)  # AR(1): persistent, so adjacent bars' feature values correlate
        feature_vals.append(x)
    closes = [100.0]
    # honest relationship: return t -> t+1 is driven by feature[t] (known AT bar t) → a real leading signal.
    for t in range(n - 1):
        ret = beta * feature_vals[t] + 0.004 * rng.gauss(0, 1)
        closes.append(max(0.01, closes[-1] * (1.0 + ret)))
    bars: list[Bar] = []
    for t in range(n):
        ts = t0 + timedelta(days=t)
        px = Decimal(str(round(closes[t], 6)))
        bars.append(Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
    return feature_vals, bars


def _synthetic_clean_feature(
    n: int = 600, *, seed: int = 7, horizon: int = 1  # noqa: ARG001 (horizon kept for CLI symmetry)
) -> tuple[list[AltDataPoint], list[Bar]]:
    """A deterministic on-bar-honest feature with a REAL forward-predictive edge, stamped strictly PIT
    (available_at == the bar it is known at): feature[t] genuinely leads the return t->t+1. It PASSES all three
    checks. Offline + pure (keyless; no Binance/Kraken fetch)."""
    feature_vals, bars = _synthetic_market(n, seed=seed)
    points = [
        AltDataPoint(ts=bar.ts, available_at=bar.ts, value=feature_vals[t]) for t, bar in enumerate(bars)
    ]
    return points, bars


def _synthetic_leaked_feature(
    n: int = 600, *, seed: int = 7, horizon: int = 1  # noqa: ARG001 (horizon kept for CLI symmetry)
) -> tuple[list[AltDataPoint], list[Bar]]:
    """A deliberately LEAKED feature: the SAME honest signal, but the wiring stamps each value ONE BAR EARLY —
    bar t carries feature[t+1], with available_at back-dated to bar t (so the join looks clean). Because the
    feature is AR(1)-smooth, reading it a bar early stays predictive (a strong but DEGRADED live IC), and lagging
    it back -1 recovers the true, STRONGER alignment — the look-ahead fingerprint. It FAILS the forward-shift
    sanity (and the shuffle still flags the IC as real, which it is — the leak is the ALIGNMENT, not the data).
    Offline + pure. Proves the tripwire catches a real baked-in peek, not just blesses clean data."""
    feature_vals, bars = _synthetic_market(n, seed=seed)
    leaked: list[AltDataPoint] = []
    for t in range(len(bars) - 1):
        # bar t carries bar t+1's value, back-dated to bar t's availability → a hidden 1-bar look-ahead.
        leaked.append(AltDataPoint(ts=bars[t].ts, available_at=bars[t].ts, value=feature_vals[t + 1]))
    return leaked, bars[: len(leaked)]


def _main() -> int:
    """`python -m cosmu.research.leakage_tripwire <feature>` — run the three-check tripwire OFFLINE on a
    synthetic feature and print the PASS/FAIL report. Pass `--leaked` to score the deliberately future-peeking
    control (it must FAIL the forward-shift sanity), `--horizon N`, `--trials N`, `--seed N`. No network, no DB,
    no Binance (the M2 is geo-blocked) — the harness is pure so the CLI demonstrates the guard anywhere.

    A real edge-lane caller does NOT use these synthetic builders: it passes the NEW source's actual PIT points +
    the real bars to `audit_feature(...)`. The CLI is the offline demonstrator + the manual spot-check."""
    import sys

    argv = sys.argv[1:]
    feature = next((a for a in argv if not a.startswith("--")), "synthetic")
    leaked = "--leaked" in argv

    def _opt(flag: str, default: int) -> int:
        for i, a in enumerate(argv):
            if a == flag and i + 1 < len(argv):
                try:
                    return int(argv[i + 1])
                except ValueError:
                    return default
        return default

    horizon = _opt("--horizon", 1)
    trials = _opt("--trials", 200)
    seed = _opt("--seed", 7)

    if leaked:
        points, bars = _synthetic_leaked_feature(seed=seed, horizon=horizon)
        label = f"{feature} (LEAKED control)"
    else:
        points, bars = _synthetic_clean_feature(seed=seed, horizon=horizon)
        label = f"{feature} (clean control)"

    report = audit_feature(
        points, bars, horizon=horizon, feature=label, shuffle_trials=trials, seed=seed
    )
    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
