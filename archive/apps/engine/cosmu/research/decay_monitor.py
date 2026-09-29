# intent: the TIME-AXIS DECAY MONITOR — a backtest-only study of post-discovery alpha decay borrowed from
# swarm/ACO PHEROMONE EVAPORATION (cross-disciplinary playbook bridge #8 + red-team "post-discovery alpha decay").
# THESIS: an edge decays after discovery; a track's SIZE should evaporate on a half-life unless it is RE-CONFIRMED
# forward. So instead of holding a funded track at full size until it hard-fails (HOLD-UNTIL-FAIL, the current
# baseline: full size until the wallet kill, master/risk.py), we multiply its size by `exp(-Δt/τ)` where Δt =
# periods since the track's last SIGNIFICANT forward confirmation
# and τ = the combo's own backtest edge half-life (master/drift.fit_edge_decay). A forward confirmation = a trailing
# window whose Probabilistic-Sharpe clears the SAME live-readiness floor the arming gate uses (PAPER_MIN_FORWARD_DSR
# over PAPER_MIN_FORWARD_OBS obs, master/live_eligibility.forward_significance) — re-proof on data the discovery
# never saw, which resets the evaporation clock. inputs: per-track realized net-return series (+ timestamps) read
# from portfolio_snapshots OR replayed from a spec over real bars; τ from each track's own edge-decay fit. outputs:
# a deterministic DecayStudyReport comparing the risk-adjusted return of the DECAYED book vs the HOLD-UNTIL-FAIL
# book (the current policy), + a designed-but-NOT-wired live multiplier. invariants: fully deterministic, seed-free
# in the analytics, OFFLINE-capable, point-in-time / causal (a period's size is decided only from STRICTLY PRIOR
# returns — no look-ahead), GATE CONSTANTS UNTOUCHED (this study only READS the forward-significance floor; it adds
# no scorer/FDR knob and moves no money), and the live rule is DESIGN-ONLY here — nothing is wired into the order
# path in this module. Thresholds are POLICY constants (like drift.py's), not strategy params, so the "no magic
# numbers in a spec" rule is untouched.

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass, field

from cosmu.config.settings import PAPER_MIN_FORWARD_DSR, PAPER_MIN_FORWARD_OBS
from cosmu.master.drift import fit_edge_decay, rolling_edge
from cosmu.master.risk_metrics import annualized_return, calmar_ratio, max_drawdown
from cosmu.master.scorer import probabilistic_sharpe, sample_moments
from cosmu.master.track_equity import real_track_rows, track_starting_capital

# --- policy constants (named, never inline magic; the forward floor is the SAME one the live arming gate uses) ---

# Trailing window (periods) over which a forward re-confirmation is tested. ~21 ≈ a month of daily marks; wide
# enough that the PSR estimate is meaningful, short enough that a re-confirmation is a recent forward event.
CONFIRM_WINDOW: int = 21
# Minimum observations before a forward-confirmation test is trusted (reuses the live arming gate's obs floor).
CONFIRM_MIN_OBS: int = PAPER_MIN_FORWARD_OBS
# Significance floor a trailing window must clear to count as a forward confirmation: PSR(window Sharpe vs 0) − 0.5
# must exceed this. Reuses PAPER_MIN_FORWARD_DSR so "significant forward confirmation" speaks the gate's language.
CONFIRM_MIN_FORWARD_DSR: float = PAPER_MIN_FORWARD_DSR
# τ floor (periods) so a near-zero fitted half-life can't blow up exp(-Δt/τ); below this, decay is effectively a step.
TAU_MIN_PERIODS: float = 1.0
# Crypto daily annualization calendar (24/7 tape) — matches the repo's ANN = sqrt(365) convention.
PERIODS_PER_YEAR: int = 365


# --- the evaporation kernel + forward-confirmation clock (pure, causal, deterministic) -------------------------


def pheromone_weight(dt: float, tau: float | None) -> float:
    """The ACO evaporation kernel: `exp(-Δt/τ)` ∈ (0, 1]. Δt = periods since the last forward confirmation, τ =
    the combo's backtest edge half-life. τ is None / non-finite / ≤ 0 ⇒ the trail does NOT evaporate (return 1.0) —
    a non-decaying edge has no half-life, so its size is never pulled by this overlay. With this convention the
    size reaches e⁻¹ ≈ 0.37 at Δt = τ and ≈ 0.50 at Δt = τ·ln2."""
    if tau is None or not math.isfinite(tau) or tau <= 0.0:
        return 1.0
    return math.exp(-max(0.0, float(dt)) / max(tau, TAU_MIN_PERIODS))


def edge_half_life(returns: list[float], *, rolling_window: int = 5) -> float | None:
    """τ for a track = the half-life implied by its OWN realized edge-decay trajectory (master/drift.fit_edge_decay
    on the rolling-mean edge). None when the edge is flat/rising/already non-positive — i.e. there is no finite
    decay to evaporate against, so the track keeps full size."""
    return fit_edge_decay(rolling_edge(returns, window=rolling_window)).half_life


def _forward_dsr(window: list[float]) -> float:
    """PSR(window per-obs Sharpe vs 0) − 0.5 ∈ [−0.5, +0.5] — the recentred forward-significance statistic the live
    arming gate uses (master/live_eligibility.forward_significance). Reuses the scorer's PSR machinery verbatim."""
    sr, skew, kurt, n = sample_moments(window)
    return probabilistic_sharpe(sr, n, skew, kurt, 0.0) - 0.5


def is_forward_confirmation(window: list[float]) -> bool:
    """Does a trailing window count as a SIGNIFICANT forward confirmation? It must have enough obs AND clear the
    same Probabilistic-Sharpe floor the live arming gate applies (CONFIRM_MIN_FORWARD_DSR)."""
    return len(window) >= CONFIRM_MIN_OBS and _forward_dsr(window) > CONFIRM_MIN_FORWARD_DSR


def decay_weights(
    returns: list[float],
    tau: float | None,
    *,
    confirm_window: int = CONFIRM_WINDOW,
    min_obs: int = CONFIRM_MIN_OBS,
    min_forward_dsr: float = CONFIRM_MIN_FORWARD_DSR,
) -> list[float]:
    """The pheromone-evaporation weight applied to EACH period's return, decided STRICTLY CAUSALLY. The weight for
    period t is `min(1, exp(-clock/τ))` where `clock` = periods since the last forward confirmation, measured from
    information available at the START of period t (i.e. from returns[:t] only — the period's own return r_t is used
    ONLY to update the clock for t+1, never to size t). Funding counts as a confirmation, so clock starts at 0 and
    the first period is full size; the clock resets to 0 whenever a trailing window becomes a forward confirmation."""
    n = len(returns)
    weights: list[float] = []
    clock = 0  # periods since the last confirmation, known at the start of the current period (funding ⇒ 0)
    for t in range(n):
        weights.append(min(1.0, pheromone_weight(clock, tau)))
        # r_t is now observable: test whether a re-confirmation fires as of the CLOSE of period t (affects t+1).
        window = returns[max(0, t + 1 - confirm_window) : t + 1]
        if len(window) >= min_obs and _forward_dsr(window) > min_forward_dsr:
            clock = 0
        else:
            clock += 1
    return weights


def hold_until_fail_weights(returns: list[float], *, kill_floor: float = 0.0) -> list[float]:
    """The literal HOLD-UNTIL-FAIL baseline (master/risk.py kill-combo): full size (1.0) the whole way, cut to 0
    ONLY once the track's compounded equity falls to `kill_floor`× its starting capital — i.e. it rides the
    position to the bitter end and is pulled only by the hard wallet kill, never anticipatorily. The prod default
    `kill_floor=0.0` means "held until total ruin", so in a bounded replay the track is effectively held at full
    size throughout — exactly the passive baseline the evaporation overlay must beat. Causal: the kill at the close
    of period t pulls size only from t+1 onward."""
    n = len(returns)
    weights = [1.0] * n
    equity = 1.0
    killed_at: int | None = None
    for t in range(n):
        if killed_at is not None and t >= killed_at:
            weights[t] = 0.0
            continue
        equity *= 1.0 + returns[t]
        if killed_at is None and equity <= kill_floor:
            killed_at = t + 1
    return weights


def decayed_weights(returns: list[float], tau: float | None, *, kill_floor: float = 0.0) -> list[float]:
    """The DECAYED policy = the hold-until-fail baseline with the pheromone-evaporation overlay multiplied on top,
    so the study isolates the MARGINAL value of evaporating size between forward confirmations (the hard wallet kill
    still applies underneath)."""
    huf = hold_until_fail_weights(returns, kill_floor=kill_floor)
    dec = decay_weights(returns, tau)
    return [h * d for h, d in zip(huf, dec, strict=True)]


# --- track + book model ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackSeries:
    """One track's FORWARD (post-funding) per-period realized net-of-fee return series with parallel ISO timestamps,
    plus the combo's BACKTEST edge half-life τ (fit on the DISCOVERY window, BEFORE the forward replay; None ⇒ no
    finite decay ⇒ full size). The split matters: τ has to be measured where the edge is still positive and merely
    DECAYING — once an edge has decayed PAST zero, master/drift.fit_edge_decay reports None ('already non-positive'),
    so fitting τ on the full series would silently disable the very evaporation the dead tail needs."""

    track_id: str
    returns: list[float]    # the FORWARD window only — what the books are evaluated over
    ts: list[str]
    tau: float | None       # the combo's backtest edge half-life (periods), fit on the discovery window

    @staticmethod
    def from_returns(track_id: str, returns: list[float], ts: list[str] | None = None, *, tau: float | None = None) -> TrackSeries:
        """Build a track whose supplied series is ALREADY the forward window (τ fit on it if not given). Used by
        the pure-core tests; real loaders use `from_full_series` to honour the discovery/forward split."""
        rs = [float(x) for x in returns]
        stamps = list(ts) if ts is not None else [str(i) for i in range(len(rs))]
        return TrackSeries(track_id, rs, stamps, tau if tau is not None else edge_half_life(rs))

    @staticmethod
    def from_full_series(track_id: str, returns: list[float], ts: list[str] | None = None, *, funded_at: int) -> TrackSeries:
        """Split a full realized series at `funded_at`: returns[:funded_at] is the DISCOVERY/backtest window (τ is
        fit here — the combo's backtest edge half-life) and returns[funded_at:] is the FORWARD window the books
        replay over. The evaporation clock starts at the funding point (just confirmed by the backtest)."""
        rs = [float(x) for x in returns]
        stamps = list(ts) if ts is not None else [str(i) for i in range(len(rs))]
        cut = max(0, min(funded_at, len(rs)))
        return TrackSeries(track_id, rs[cut:], stamps[cut:], edge_half_life(rs[:cut]))


@dataclass(frozen=True)
class BookMetrics:
    n: int
    total_return: float
    annualized_return: float
    sharpe: float            # annualized; the headline risk-adjusted metric
    max_drawdown: float
    calmar: float
    forward_dsr: float       # PSR(book Sharpe vs 0) − 0.5; is the book's edge significant, not luck?


@dataclass
class DecayStudyReport:
    verdict: str             # "DECAYED-WINS" | "HOLD-WINS" | "TIE"
    data_source: str         # "synthetic-fixture" | "portfolio_snapshots" | "spec-replay"
    decayed_wins: bool
    n_tracks: int
    periods: int
    sharpe_margin: float     # decayed.sharpe − hold.sharpe (the primary risk-adjusted delta)
    decayed: BookMetrics
    hold_until_fail: BookMetrics
    median_tau: float | None
    headline: str
    notes: list[str] = field(default_factory=list)


def _annualized_sharpe(returns: list[float], periods_per_year: int) -> float:
    """Annualized Sharpe of a per-period net-return stream (mean/std × √ppy) — matches data/backtest._sharpe.
    0.0 when there are < 2 returns or zero dispersion."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((x - mean) ** 2 for x in returns) / (n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return 0.0
    return (mean / sd) * math.sqrt(periods_per_year)


def evaluate_book(returns: list[float], *, periods_per_year: int = PERIODS_PER_YEAR) -> BookMetrics:
    """Risk-adjusted summary of a book's per-period net-return stream. forward_dsr reuses the scorer PSR so the
    book's significance is measured in the gate's own language."""
    n = len(returns)
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    total = growth - 1.0
    return BookMetrics(
        n=n,
        total_return=total,
        annualized_return=annualized_return(returns, periods_per_year),
        sharpe=_annualized_sharpe(returns, periods_per_year),
        max_drawdown=max_drawdown(returns),
        calmar=calmar_ratio(returns, periods_per_year),
        forward_dsr=(_forward_dsr(returns) if n >= 2 else 0.0),
    )


def book_returns(tracks: list[TrackSeries], weight_of: dict[str, list[float]]) -> list[float]:
    """Aggregate a set of tracks into ONE book's per-period net-return stream on the UNION timeline. Each track
    holds a fixed base slice 1/N of the book and contributes `(1/N) · w_{i,t} · r_{i,t}` on the periods (keyed by
    timestamp) where it has data; evaporated size sits in CASH (un-renormalized) so the study measures the honest
    cost/benefit of PULLING capital as a trail goes stale — not a reshuffle that is always fully invested."""
    if not tracks:
        return []
    base = 1.0 / len(tracks)
    contrib: dict[str, float] = {}
    for tr in tracks:
        w = weight_of[tr.track_id]
        for t, stamp in enumerate(tr.ts):
            contrib[stamp] = contrib.get(stamp, 0.0) + base * w[t] * tr.returns[t]
    return [contrib[s] for s in sorted(contrib)]


def run_study(
    tracks: list[TrackSeries],
    *,
    data_source: str,
    periods_per_year: int = PERIODS_PER_YEAR,
    sharpe_tie_margin: float = 0.10,
    kill_floor: float = 0.0,
) -> DecayStudyReport:
    """Replay the supplied tracks under both policies and compare risk-adjusted return. DECAYED wins only if its
    annualized Sharpe beats hold-until-fail by more than `sharpe_tie_margin` (a small dead-band so noise ≠ a win)."""
    tracks = [t for t in tracks if len(t.returns) >= 2]
    hold_w = {t.track_id: hold_until_fail_weights(t.returns, kill_floor=kill_floor) for t in tracks}
    dec_w = {t.track_id: decayed_weights(t.returns, t.tau, kill_floor=kill_floor) for t in tracks}
    hold_book = evaluate_book(book_returns(tracks, hold_w), periods_per_year=periods_per_year)
    dec_book = evaluate_book(book_returns(tracks, dec_w), periods_per_year=periods_per_year)

    margin = dec_book.sharpe - hold_book.sharpe
    if margin > sharpe_tie_margin:
        verdict, wins = "DECAYED-WINS", True
    elif margin < -sharpe_tie_margin:
        verdict, wins = "HOLD-WINS", False
    else:
        verdict, wins = "TIE", False

    taus = sorted(t.tau for t in tracks if t.tau is not None and math.isfinite(t.tau))
    median_tau = taus[len(taus) // 2] if taus else None
    periods = max((len(t.returns) for t in tracks), default=0)
    headline = (
        f"{verdict}: decayed Sharpe {dec_book.sharpe:.2f} vs hold {hold_book.sharpe:.2f} "
        f"(Δ {margin:+.2f}), maxDD {dec_book.max_drawdown:.1%} vs {hold_book.max_drawdown:.1%} "
        f"over {len(tracks)} tracks × {periods} periods [{data_source}]"
    )
    notes = [
        "τ = each combo's own backtest edge half-life (master/drift.fit_edge_decay); None ⇒ no decay (full size).",
        f"forward confirmation = trailing {CONFIRM_WINDOW}-period PSR−0.5 > {CONFIRM_MIN_FORWARD_DSR} "
        f"(>= {CONFIRM_MIN_OBS} obs) — the live arming gate's floor.",
        "evaporated size sits in CASH (un-renormalized); hold-until-fail is the current drift-defund policy.",
        "DESIGN-ONLY: no live order-path wiring in this PR; gate/scorer constants untouched.",
    ]
    return DecayStudyReport(
        verdict=verdict,
        data_source=data_source,
        decayed_wins=wins,
        n_tracks=len(tracks),
        periods=periods,
        sharpe_margin=margin,
        decayed=dec_book,
        hold_until_fail=hold_book,
        median_tau=median_tau,
        headline=headline,
        notes=notes,
    )


# --- DESIGN ONLY: the proposed live decay multiplier (NOT wired into the order path in this PR) ----------------


def live_decay_multiplier(
    realized_returns: list[float],
    tau: float | None,
    *,
    confirm_window: int = CONFIRM_WINDOW,
) -> float:
    """DESIGN-ONLY proposal for the live rule (see docs/reports/decay-monitor-*.md). Given a funded cell's realized
    net-return series so far and its backtest edge half-life τ, return the size multiplier the live sizer WOULD
    apply: `min(1, exp(-Δt/τ))` for Δt = periods since the cell's last forward confirmation. This is the LAST weight
    `decay_weights` would assign — exposed as a single scalar a future `master/sizing.py` overlay could multiply
    into `size_fraction`. It is NOT called by any live path in this PR (the order path is unchanged); it is wired
    only AFTER the backtest evidence shows the decayed book wins on risk-adjusted return, behind its own gate."""
    if not realized_returns:
        return 1.0
    return decay_weights(realized_returns, tau, confirm_window=confirm_window)[-1]


# --- synthetic panel: deterministic METHOD-VALIDATION fixture (CI/tests only — never displayed, never live) ----


def synthetic_panel(
    *,
    n_tracks: int,
    periods: int,
    seed: int,
    mode: str,
    funded_at: int | None = None,
    base_edge: float = 0.016,
    idio_noise: float = 0.008,
    common_noise: float = 0.005,
    zero_at: int | None = None,
    reconfirm_every: int | None = None,
) -> list[TrackSeries]:
    """A DETERMINISTIC synthetic panel for METHOD VALIDATION ONLY (quarantined to CI/tests — AGENTS.md: never
    display synthetic, never run in prod). Each track is a FULL series split at `funded_at` (default periods/3) into
    a discovery window (where τ is fit — the edge is positive and decaying there) and the forward window the books
    replay over. The true per-period edge follows one of three post-discovery shapes, matching how master/drift
    models decay (a linear slope toward — and past — zero):
      · "persistent"  — a constant positive edge (no decay): τ is None, so the overlay must NOT pull size (control).
      · "decaying"    — a LINEAR edge `base_edge·(1 − t/zero_at)` that crosses zero at `zero_at` and goes NEGATIVE
                        in the forward window (the real crowded-out / arbed-away alpha decay the red-team fears):
                        holding full size rides the losing tail, evaporation should trim it before the wallet kill.
      · "reconfirmed" — the same decay but RE-DISCOVERED every `reconfirm_every` periods (the edge re-boosts to
                        fresh), so the forward-confirmation detector should KEEP size up on a genuinely live edge.
    Noise has a SHARED market component (`common_noise`, common to all tracks at each period) plus a per-track
    idiosyncratic part (`idio_noise`) — so the book is realistically CORRELATED (diversification does not collapse
    its volatility to zero) and the book Sharpe stays plausible rather than astronomically high."""
    common_rng = random.Random(seed * 1000003)
    cut = funded_at if funded_at is not None else max(2, periods // 3)
    z = zero_at if zero_at is not None else max(2, cut + (periods - cut) // 2)  # zero crossing inside the forward window
    common = [common_rng.gauss(0.0, common_noise) for _ in range(periods)]
    out: list[TrackSeries] = []
    for k in range(n_tracks):
        rng = random.Random(seed + k)
        mu0 = base_edge * (1.0 + 0.25 * (k - (n_tracks - 1) / 2) / max(1, n_tracks))  # mild cross-track spread
        rets: list[float] = []
        since = 0
        for t in range(periods):
            if mode == "persistent":
                edge = mu0
            else:
                edge = mu0 * (1.0 - since / z)  # linear decay; negative once `since` passes `zero_at`
            rets.append(edge + common[t] + rng.gauss(0.0, idio_noise))
            since += 1
            if mode == "reconfirmed" and reconfirm_every and since >= reconfirm_every:
                since = 0  # a genuine forward re-discovery re-boosts the edge to fresh
        out.append(TrackSeries.from_full_series(f"synthetic-{k}", rets, funded_at=cut))
    return out


# --- drivers: load REAL track series (run on Modal / locally where data is available) --------------------------


def load_tracks_from_store(store, *, limit: int = 500, discovery_frac: float = 0.25) -> list[TrackSeries]:
    """Read the realized forward record of every funded track from portfolio_snapshots (scope='track'). The
    snapshots are all post-funding, so there is no separate backtest slice to fit τ on; the honest fallback fits τ
    on the EARLIEST `discovery_frac` of each track's marks (the freshly-confirmed edge right after funding) and
    replays decay over the rest. A live wiring would instead read the combo's stored backtest edge half-life.
    Returns honest-empty when no tracks have snapshots (e.g. a fresh DB)."""
    rows = store.rows(
        "SELECT ref_id, ts, equity FROM portfolio_snapshots WHERE scope = 'track' ORDER BY ref_id, ts ASC"
    )
    from collections import defaultdict

    # Group the raw snapshot rows per ref, THEN drop the funder's seed-collapse rows before deriving returns: an
    # interleaved re-mark to the seed would inject a phantom down/up round-trip that corrupts the fitted edge
    # half-life τ this study estimates (see master/track_equity).
    raw_by_ref: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        raw_by_ref[r["ref_id"]].append(r)
    by_ref: dict[str, list[tuple[str, float]]] = {}
    for ref, raw in raw_by_ref.items():
        kept = real_track_rows(raw, track_starting_capital(store, ref))
        by_ref[ref] = [(str(r["ts"]), float(r["equity"])) for r in kept]
    out: list[TrackSeries] = []
    for ref, series in by_ref.items():
        series = series[-(limit + 1) :]
        rets: list[float] = []
        stamps: list[str] = []
        for (_, prev), (ts, cur) in zip(series, series[1:], strict=False):
            if prev > 0 and math.isfinite(prev) and math.isfinite(cur):
                rets.append((cur - prev) / prev)
                stamps.append(ts)
        if len(rets) >= 2:
            cut = max(CONFIRM_MIN_OBS, int(len(rets) * discovery_frac))
            cut = min(cut, len(rets) - 2)  # always leave a forward window of >= 2
            out.append(TrackSeries.from_full_series(ref, rets, stamps, funded_at=max(0, cut)))
    return out


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Time-axis decay monitor — backtest-only study (pheromone evaporation).")
    p.add_argument("--source", choices=["synthetic", "store"], default="synthetic",
                   help="synthetic = deterministic method-validation fixture; store = portfolio_snapshots (real).")
    p.add_argument("--scenario", choices=["decaying", "persistent", "reconfirmed"], default="decaying",
                   help="synthetic scenario (ignored for --source store).")
    p.add_argument("--tracks", type=int, default=12)
    p.add_argument("--periods", type=int, default=180)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--zero-at", type=int, default=None, help="period the synthetic edge crosses zero (decaying).")
    p.add_argument("--ppy", type=int, default=PERIODS_PER_YEAR, help="periods per year for annualization.")
    p.add_argument("--out", type=str, default=None, help="optional path to write the JSON report.")
    args = p.parse_args(argv)

    if args.source == "store":
        from cosmu.config.settings import Settings
        from cosmu.knowledge.store import Store

        store = Store(Settings())
        tracks = load_tracks_from_store(store)
        source = "portfolio_snapshots"
        if not tracks:
            print("no funded tracks with portfolio_snapshots — run on Modal/prod where forward data exists.")
            return 0
    else:
        recon = max(CONFIRM_WINDOW, args.periods // 4) if args.scenario == "reconfirmed" else None
        tracks = synthetic_panel(n_tracks=args.tracks, periods=args.periods, seed=args.seed,
                                 mode=args.scenario, zero_at=args.zero_at, reconfirm_every=recon)
        source = "synthetic-fixture"

    report = run_study(tracks, data_source=source, periods_per_year=args.ppy)
    print(report.headline)
    for note in report.notes:
        print(f"  · {note}")
    payload = json.dumps(asdict(report), indent=2, default=float)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(payload)
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
