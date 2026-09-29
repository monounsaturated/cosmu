# intent: the STANDING leakage tripwire — the #1 blow-up guard. A look-ahead/alignment bug UPSTREAM of the Gate
# is Gate-INVISIBLE (the Gate validates edge-after-costs, NOT pipeline honesty): it produces a survivor that is
# genuinely real on paper and zero/negative live. This module bundles FOUR independent disconfirmers into ONE
# PASS/FAIL report a NEW data source MUST clear before it is trusted as a feature ([[vibe_coding_leakage_risk]]).
# The three the operator named — PIT/available_at audit, shuffle-null, ticker/identity anonymization — plus the
# forward-shift sanity (kept from the merged guard, #387, because it catches the back-dated-alignment leak the
# other three structurally miss):
#
#   (1) AVAILABLE_AT AUDIT  — the align_asof PIT join is strictly BACKWARD-looking: NO feature value is ever
#       joined to a bar whose ts < that value's available_at. Brute-verified against the points themselves, so
#       a join that ever peeked a not-yet-published value is caught directly (not inferred from an IC). This is
#       the point-in-time / available_at honesty check (operator's disconfirmer #1).
#   (2) SHUFFLE-NULL        — permute the feature's VALUES in time (break the real time-alignment, keep the
#       marginal distribution) → its IC vs forward returns must COLLAPSE toward 0. An IC that SURVIVES the
#       shuffle reflects a genuine feature→return alignment; an IC inside the shuffled band is a noise /
#       autocorrelation artefact, never an edge (BlindTrade: IC 0.015 → 0.0004 under shuffle). (Operator's #2.)
#   (3) TICKER / IDENTITY ANONYMIZATION — strip SYMBOL IDENTITY by demeaning each symbol's feature AND forward
#       return WITHIN that symbol, then pool. A cross-sectional IC that comes from a memorized per-symbol PRIOR
#       (a constant level that happens to rank with that symbol's drift — "BTC always goes up") VANISHES; a
#       transferable within-symbol timing signal SURVIVES. The IC analog of the LLM ticker-memorization test
#       (Sarkar & Vafa). (Operator's #3.) Only runs when a MULTI-SYMBOL series map is supplied — identity is a
#       cross-sectional concept; a single series has no ticker to mask. Advisory-but-recorded for one symbol.
#   (4) FORWARD-SHIFT SANITY — shifting the feature +1 bar (using TOMORROW's value TODAY) must IMPROVE in-sample
#       fit (|IC| rises) — that is the honest direction of cheating, and it MUST help. If instead shifting the
#       feature BACKWARD (a MORE honest, more-lagged read) improves the fit, the live wiring is ALREADY peeking
#       at the future: the as-of alignment is too-early by a bar, so de-leaking it (lagging) helps. That is the
#       fingerprint of a baked-in look-ahead the AVAILABLE_AT audit can miss when available_at itself is wrong.
#
# Each check is NECESSARY, never sufficient — surviving the tripwire is the price of admission to the Gate, which
# alone disposes (PROPOSE-ONLY). PURE + OFFLINE: operates on AltDataPoint lists + Bar lists already read
# point-in-time, reuses align_asof (the SAME join the backtest runs) + spearman_ic + the shuffle_null and
# symbol_anonymization_null harnesses (never a second hand-rolled correlation). No I/O, no DB, no settings, no
# LLM, no Gate constant mutation. Changes NO Gate constant; reads none. It INFORMS, it does NOT move money.
#
# HONEST LIMITATIONS (a PASS is necessary, not sufficient — read these before trusting a green report):
#   - The shuffle + anonymization nulls catch the SPURIOUS / MEMORIZED class; the available_at + forward-shift
#     checks catch LOOK-AHEAD. None catches a leak that is BOTH real-in-alignment AND survives a value-shuffle
#     AND is symbol-transferable — e.g. a globally-normalized transform (mean/std over the WHOLE history) whose
#     leak is a slow drift, not a per-bar misalignment. That class needs the available_at audit on the RAW
#     source + the profile-source PIT-lag profiler upstream; the tripwire reduces the surface, it does not close
#     it. (Global-normalization smell is best caught at ingest, not here — documented, not over-claimed.)
#   - Ticker-anonymization (3) uses within-symbol demeaning + a BINARY memorized flag (within|IC| < 50% of
#     pooled|IC|). A MIXED edge (real timing + a partial identity prior) shows a partial identity_share and may
#     pass or fail near the 50% boundary — read identity_share, not just the flag. It needs a MULTI-SYMBOL map;
#     a single series carries no ticker and the check is SKIPPED (reported as such, never silently passed).
#   - The shuffle p-value is empirical (add-one corrected); with few obs the band is wide. The forward-shift
#     margin (15%) is conservative against estimation noise — a sub-margin baked-in peek can slip [4].
#
# Entry points:
#   audit_feature(points, bars, horizon=...) -> TripwireReport   (the programmatic gate the edge lane calls)
#   python -m cosmu.research.leakage_tripwire <feature>          (CLI: runs the checks on offline data)

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.disconfirmers import (
    ShuffleNullResult,
    SymbolAnonymizationResult,
    pit_ic,
    shuffle_null,
    symbol_anonymization_null,
)

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
    """The PASS/FAIL verdict over the independent disconfirmers. `passed` is the AND of every ACTIVE check: a NEW
    source must clear EVERY check before the edge lane trusts it as a feature. A FAIL names the disconfirmer
    that caught it (`failed_checks`) so the operator fixes the right surface (look-ahead vs spurious IC vs ticker
    memorization vs baked-in peek). The ticker-anonymization check is ACTIVE only when a multi-symbol series map
    is supplied (`anonymization is not None`); identity is a cross-sectional concept, so a single series carries
    no ticker to mask and the check is skipped (never silently passed). PROPOSE-ONLY: a PASS is necessary, never
    sufficient — the Gate alone disposes; this report moves no money and reads no Gate constant."""

    feature: str
    n_obs: int
    real_ic: float
    available_at: AvailableAtResult
    shuffle: ShuffleNullResult
    forward_shift: ForwardShiftResult
    passed: bool
    anonymization: SymbolAnonymizationResult | None = None  # active only for a multi-symbol series map
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
        ]
        if self.anonymization is not None:
            a = self.anonymization
            lines.append(
                f"  [3] ticker-anonymization: pooled|IC|={abs(a.pooled_ic):.4f}, "
                f"within|IC|={abs(a.within_ic):.4f}, identity_share={a.identity_share:.2f}"
                f"  -> {'PASS (transferable, identity not the edge)' if a.survives else 'FAIL (edge dies when ticker masked = memorized prior)'}"
            )
        else:
            lines.append("  [3] ticker-anonymization: SKIPPED (single series — no ticker identity to mask)")
        lines.append(
            f"  [4] {self.forward_shift.summary}"
            f"  -> {'PASS' if self.forward_shift.passed else 'FAIL (lagging the feature improves fit = live peek)'}"
        )
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
    series_by_symbol: dict[str, list[AltDataPoint]] | None = None,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    require_anonymization_survival: bool = True,
) -> TripwireReport:
    """Run the leakage tripwire on one feature's PIT-stamped points against `bars`, returning a PASS/FAIL
    TripwireReport. The single front door the edge lane gates a NEW source on.

    Checks (every ACTIVE one must pass for `passed=True`):
      [1] available_at audit   — align_asof is strictly backward-looking (zero look-ahead in the join).
      [2] shuffle-null         — the IC survives a time-shuffle (genuine alignment, not a noise artefact).
      [3] ticker-anonymization — the IC survives masking SYMBOL IDENTITY (a transferable timing edge, not a
          memorized per-symbol prior). ACTIVE only when `series_by_symbol`+`bars_by_symbol` (a multi-symbol map)
          are supplied; identity is cross-sectional, so a single series has no ticker to mask and [3] is SKIPPED
          (reported as such, never silently passed).
      [4] forward-shift sanity — lagging the feature does NOT beat the live read (no baked-in 1-bar look-ahead).

    `require_shuffle_survival` (default True) makes a feature whose IC collapses INTO the shuffled band a FAIL —
    a "signal" indistinguishable from noise is not trustworthy. `require_anonymization_survival` (default True)
    likewise fails an edge that dies when the ticker is masked. Set either False to keep that check advisory (the
    report still records its verdict). The positive-look-ahead checks ([1], [4]) are always hard.

    PURE + deterministic for fixed (points, bars, seed, trials). Reuses align_asof + spearman_ic + the
    shuffle_null and symbol_anonymization_null harnesses — never a second hand-rolled correlation. Changes NO
    Gate constant; reads none. PROPOSE-ONLY — it informs, it does not move money."""
    real_ic, n = pit_ic(points, bars, horizon)
    a1 = available_at_audit(points, bars)
    a2 = shuffle_null(points, bars, horizon, trials=shuffle_trials, seed=seed, alpha=alpha)
    a4 = forward_shift_sanity(points, bars, horizon)

    a3: SymbolAnonymizationResult | None = None
    if series_by_symbol is not None and bars_by_symbol is not None:
        a3 = symbol_anonymization_null(series_by_symbol, bars_by_symbol, horizon)

    failed: list[str] = []
    if not a1.passed:
        failed.append("available_at_audit")
    if require_shuffle_survival and not a2.survives:
        failed.append("shuffle_null")
    if a3 is not None and require_anonymization_survival and not a3.survives:
        failed.append("ticker_anonymization")
    if not a4.passed:
        failed.append("forward_shift_sanity")

    return TripwireReport(
        feature=feature,
        n_obs=n,
        real_ic=real_ic,
        available_at=a1,
        shuffle=a2,
        forward_shift=a4,
        anonymization=a3,
        passed=not failed,
        failed_checks=tuple(failed),
    )


__all__ = [
    "AvailableAtResult",
    "ForwardShiftResult",
    "SymbolAnonymizationResult",
    "TripwireReport",
    "audit_feature",
    "available_at_audit",
    "forward_shift_sanity",
    "symbol_anonymization_null",
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


# ---------------------------------------------------------------- multi-symbol fixtures (ticker anonymization, [3])


def _synthetic_clean_panel(
    *, n_symbols: int = 6, n: int = 400, seed: int = 7
) -> tuple[dict[str, list[AltDataPoint]], dict[str, list[Bar]]]:
    """A multi-symbol panel where the feature carries a TRANSFERABLE within-symbol timing edge (feature[t] leads
    that symbol's own return t->t+1, same mechanism every symbol) and NO per-symbol level prior. Demeaning each
    symbol removes nothing real, so the within-symbol IC ~ the pooled IC → it PASSES the ticker-anonymization
    check (the edge is the timing, not the identity). Offline + pure (keyless; per-symbol string-seeded RNG)."""
    series: dict[str, list[AltDataPoint]] = {}
    bars_by: dict[str, list[Bar]] = {}
    for s in range(n_symbols):
        sym = f"SYNTH{s}"
        feature_vals, bars = _synthetic_market(n, seed=seed * 1000 + s)
        # zero-centre the feature per symbol so it carries NO constant level (no identity prior to memorize).
        mu = sum(feature_vals) / len(feature_vals)
        centred = [v - mu for v in feature_vals]
        series[sym] = [AltDataPoint(ts=b.ts, available_at=b.ts, value=centred[t]) for t, b in enumerate(bars)]
        bars_by[sym] = bars
    return series, bars_by


def _synthetic_identity_memorized_panel(
    *, n_symbols: int = 6, n: int = 400, seed: int = 7
) -> tuple[dict[str, list[AltDataPoint]], dict[str, list[Bar]]]:
    """A multi-symbol panel whose pooled cross-sectional IC is a MEMORIZED PER-SYMBOL PRIOR, not a timing edge:
    each symbol gets a CONSTANT feature level (its "identity") that rank-correlates with that symbol's CONSTANT
    drift — "this ticker always goes up, and its feature is always high". Pooled, the level ranks beautifully with
    forward returns (a big spurious IC); but it is pure identity memorization. Demeaning each symbol collapses the
    feature to ~0 (a constant minus its own mean), so the within-symbol IC vanishes → it FAILS the ticker-
    anonymization check. The within-symbol noise carries NO real timing signal. Offline + pure + deterministic.
    Proves the disconfirmer catches a 'BTC always goes up' memorization, not just blesses transferable signals."""
    import random
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    series: dict[str, list[AltDataPoint]] = {}
    bars_by: dict[str, list[Bar]] = {}
    for s in range(n_symbols):
        sym = f"MEMO{s}"
        rng = random.Random(f"tripwire-memo-{seed}-{s}")
        # the symbol's IDENTITY: a constant feature level and a matching constant per-bar drift. Higher level ->
        # higher drift, monotonically, so the pooled (level vs forward-return) IC is large and spurious.
        level = float(s)
        drift = 0.0008 * s  # the ticker-specific drift the constant level "predicts" by memorization
        closes = [100.0]
        for _ in range(n - 1):
            ret = drift + 0.004 * rng.gauss(0, 1)  # drift is per-symbol constant; noise is within-symbol
            closes.append(max(0.01, closes[-1] * (1.0 + ret)))
        bars: list[Bar] = []
        pts: list[AltDataPoint] = []
        for t in range(n):
            ts = t0 + timedelta(days=t)
            px = Decimal(str(round(closes[t], 6)))
            bars.append(Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
            pts.append(AltDataPoint(ts=ts, available_at=ts, value=level))  # CONSTANT feature = identity only
        series[sym] = pts
        bars_by[sym] = bars
    return series, bars_by


def _main() -> int:
    """`python -m cosmu.research.leakage_tripwire <feature>` — run the leakage tripwire OFFLINE on a synthetic
    feature and print the PASS/FAIL report. Flags:
      --leaked   score the deliberately future-peeking single-series control (must FAIL forward-shift, [4]).
      --anon     score a multi-symbol panel + run the ticker-anonymization check ([3]); add --leaked to score
                 the identity-MEMORIZED panel ('BTC always goes up'), which must FAIL anonymization.
      --horizon N / --trials N / --seed N  knobs.
    No network, no DB, no Binance (the M2 is geo-blocked) — the harness is pure so the CLI demonstrates the guard
    anywhere.

    A real edge-lane caller does NOT use these synthetic builders: it passes the NEW source's actual PIT points +
    the real bars to `audit_feature(...)` (and a `series_by_symbol`/`bars_by_symbol` map to activate [3]). The CLI
    is the offline demonstrator + the manual spot-check."""
    import sys

    argv = sys.argv[1:]
    feature = next((a for a in argv if not a.startswith("--")), "synthetic")
    leaked = "--leaked" in argv
    anon = "--anon" in argv

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

    if anon:
        # Activate the ticker-anonymization check ([3]) by passing a multi-symbol map. --leaked picks the
        # identity-memorized panel (must FAIL [3]); otherwise the transferable clean panel (must PASS).
        if leaked:
            series, bars_by = _synthetic_identity_memorized_panel(seed=seed)
            label = f"{feature} (IDENTITY-MEMORIZED panel)"
        else:
            series, bars_by = _synthetic_clean_panel(seed=seed)
            label = f"{feature} (clean transferable panel)"
        # score the FIRST symbol's series for the single-series checks ([1],[2],[4]); the panel drives [3].
        first_sym = next(iter(series))
        report = audit_feature(
            series[first_sym], bars_by[first_sym], horizon=horizon, feature=label,
            shuffle_trials=trials, seed=seed, series_by_symbol=series, bars_by_symbol=bars_by,
        )
        print(report.render())
        return 0 if report.passed else 1

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
