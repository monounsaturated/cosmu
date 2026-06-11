# intent: the DETERMINISTIC EVENT-STUDY harness (realtime-data-lane epic §4) — measure whether typed
# unstructured events (news / tweets / Polymarket moves) carry ABNORMAL forward returns in EVENT TIME on
# intraday bars, with the statistical hygiene the literature demands: market-model residuals (never raw
# returns), volatility-standardized CARs over pre-registered windows, a PRE-event window that exposes
# leakage/echo (a move that precedes the "news" means the news was late), root-event-only observation sets,
# confounded-event exclusion, market-comove flags, randomization inference against weekday×hour×vol-matched
# placebo times, and BH-FDR across the (cell) grid so window/type/source shopping cannot manufacture a
# discovery. inputs: MarketEvent records + per-symbol Bar lists (one timeframe grid, designed for 1m) + a
# market reference symbol; outputs: a typed EventStudyReport (per-cell SCARs, RI p-values, leakage flags,
# FDR verdicts). invariants: PURE + offline + deterministic (seeded RNG, no network, no LLM); an event the
# data can't power is SKIPPED and counted, never guessed; a cell below min_events is INSUFFICIENT, never a
# verdict; β/σ estimation ends strictly BEFORE the event's containing bar (no contamination); the reaction
# window starts at the first bar OPENING AFTER the event (the tradeable convention — conservatively excludes
# the intra-bar pop you could not have caught).

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.master.fdr import benjamini_hochberg

__all__ = ["EventStudyConfig", "CellResult", "EventStudyReport", "run_event_study"]


@dataclass(frozen=True)
class EventStudyConfig:
    """Pre-registered knobs. `windows` are in BARS of whatever grid the caller supplies (minutes on 1m bars);
    `primary_window` is the ONE window inference runs on — the others are descriptive (no window shopping)."""

    windows: tuple[int, ...] = (5, 30, 60, 1440)
    primary_window: int = 60
    pre_window: int = 30
    beta_window: int = 1440          # β/σ estimation span (1 day of 1m bars), strictly pre-event
    exclusion_bars: int = 120        # two events on one symbol within this distance are both confounded
    market_z: float = 3.0            # |market CAR z| above this during the primary window ⇒ comove flag
    min_events: int = 20             # a cell below this is INSUFFICIENT, not a verdict
    placebo_sets: int = 200          # randomization-inference resamples
    seed: int = 7
    fdr_q: float = 0.10
    market_symbol: str = "BTCUSDT"
    roots_only: bool = True          # study root events only (the breaker per cluster); echoes are a separate study


@dataclass
class _SymbolPanel:
    """One symbol's aligned return panel vs the market, with prefix sums for O(1) window statistics."""

    ts: list[datetime]              # bar OPEN times, ascending, intersection grid with the market
    r_a: list[float]                # asset log returns (r[0] = 0.0 placeholder)
    r_m: list[float]                # market log returns on the same grid
    p_a: list[float] = field(default_factory=list)    # prefix sums of r_a
    p_aa: list[float] = field(default_factory=list)
    p_m: list[float] = field(default_factory=list)
    p_mm: list[float] = field(default_factory=list)
    p_am: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.r_a)
        self.p_a, self.p_aa, self.p_m, self.p_mm, self.p_am = ([0.0] * (n + 1) for _ in range(5))
        for i in range(n):
            self.p_a[i + 1] = self.p_a[i] + self.r_a[i]
            self.p_aa[i + 1] = self.p_aa[i] + self.r_a[i] * self.r_a[i]
            self.p_m[i + 1] = self.p_m[i] + self.r_m[i]
            self.p_mm[i + 1] = self.p_mm[i] + self.r_m[i] * self.r_m[i]
            self.p_am[i + 1] = self.p_am[i] + self.r_a[i] * self.r_m[i]

    def _sums(self, lo: int, hi: int) -> tuple[float, float, float, float, float, int]:
        """Window sums over return indices [lo, hi] inclusive."""
        k = hi - lo + 1
        return (
            self.p_a[hi + 1] - self.p_a[lo], self.p_aa[hi + 1] - self.p_aa[lo],
            self.p_m[hi + 1] - self.p_m[lo], self.p_mm[hi + 1] - self.p_mm[lo],
            self.p_am[hi + 1] - self.p_am[lo], k,
        )

    def beta_sigma(self, lo: int, hi: int, *, use_market: bool) -> tuple[float, float, float] | None:
        """(β, σ_abnormal_per_bar, σ_market_per_bar) estimated on [lo, hi]. None when degenerate."""
        if lo < 1 or hi <= lo:
            return None
        s_a, s_aa, s_m, s_mm, s_am, k = self._sums(lo, hi)
        var_m = s_mm / k - (s_m / k) ** 2
        beta = (s_am / k - (s_a / k) * (s_m / k)) / var_m if (use_market and var_m > 0) else 0.0
        # Var(r_a - β r_m) = Var(a) - 2β Cov + β² Var(m), all from the same sums.
        var_a = s_aa / k - (s_a / k) ** 2
        cov = s_am / k - (s_a / k) * (s_m / k)
        var_ar = max(var_a - 2 * beta * cov + beta * beta * var_m, 0.0)
        if var_ar <= 0:
            return None
        return beta, math.sqrt(var_ar), math.sqrt(var_m) if var_m > 0 else 0.0

    def scar(self, anchor: int, k: int, beta: float, sigma: float) -> float | None:
        """Standardized cumulative abnormal return over [anchor, anchor+k-1]."""
        hi = anchor + k - 1
        if anchor < 1 or hi >= len(self.r_a) or sigma <= 0:
            return None
        s_a, _, s_m, _, _, _ = self._sums(anchor, hi)
        return (s_a - beta * s_m) / (sigma * math.sqrt(k))

    def market_z(self, anchor: int, k: int, sigma_m: float) -> float | None:
        hi = anchor + k - 1
        if anchor < 1 or hi >= len(self.r_a) or sigma_m <= 0:
            return None
        _, _, s_m, _, _, _ = self._sums(anchor, hi)
        return s_m / (sigma_m * math.sqrt(k))


def _build_panel(bars: list[Bar], market: list[Bar]) -> _SymbolPanel | None:
    """Align asset and market bars on their ts intersection (gap bars on either side are skipped, never
    zero-filled) and precompute log returns. None when the overlap is too thin to study."""
    m_close = {b.ts: float(b.close) for b in market if float(b.close) > 0}
    ts, a_closes, m_closes = [], [], []
    for b in bars:
        c = float(b.close)
        if c > 0 and b.ts in m_close:
            ts.append(b.ts)
            a_closes.append(c)
            m_closes.append(m_close[b.ts])
    if len(ts) < 3:
        return None
    r_a = [0.0] + [math.log(a_closes[i] / a_closes[i - 1]) for i in range(1, len(ts))]
    r_m = [0.0] + [math.log(m_closes[i] / m_closes[i - 1]) for i in range(1, len(ts))]
    return _SymbolPanel(ts=ts, r_a=r_a, r_m=r_m)


@dataclass
class _Obs:
    """One powered (event, symbol) observation."""

    symbol: str
    anchor: int
    content_hash: str
    scars: dict[int, float]
    pre_scar: float
    confounded: bool = False
    market_comove: bool = False


@dataclass
class CellResult:
    key: tuple[str, ...]
    n_total: int = 0          # observations routed to this cell (incl. skipped)
    n_skipped: int = 0        # unpowered (no bars / insufficient history or future)
    n_confounded: int = 0     # excluded: another root event too close on the same symbol
    n_comove: int = 0         # excluded: the whole market moved (beta, not the event)
    n_clean: int = 0
    mean_scar: dict[int, float] = field(default_factory=dict)
    mean_pre_scar: float = 0.0
    ri_pvalue: float | None = None      # randomization-inference p (primary window, two-sided), clean set
    pre_pvalue: float | None = None     # same machinery on the PRE-window
    leakage_flag: bool = False          # pre-window significant ⇒ "news" follows the move (echo/leak)
    fdr_pass: bool = False
    verdict: str = "insufficient"       # insufficient | fail | pass


@dataclass
class EventStudyReport:
    config: EventStudyConfig
    cells: list[CellResult]
    n_events_in: int = 0
    n_roots_studied: int = 0

    def cell(self, *key: str) -> CellResult | None:
        for c in self.cells:
            if c.key == tuple(key):
                return c
        return None


def _default_cell(e: MarketEvent) -> tuple[str, ...]:
    return (e.event_type or "all",)


def run_event_study(
    events: list[MarketEvent],
    bars_by_symbol: dict[str, list[Bar]],
    config: EventStudyConfig | None = None,
    *,
    cell_of: Callable[[MarketEvent], tuple[str, ...]] = _default_cell,
) -> EventStudyReport:
    """The full pipeline: roots-only dedup → anchor each (event, symbol) on its grid → SCARs + pre-window →
    confounder/comove exclusion → per-cell randomization inference → BH-FDR across cells. Deterministic for
    a fixed (events, bars, config)."""
    cfg = config or EventStudyConfig()
    rng = random.Random(cfg.seed)
    market_bars = bars_by_symbol.get(cfg.market_symbol, [])
    report = EventStudyReport(config=cfg, cells=[], n_events_in=len(events))

    # Roots only: the earliest member of each cluster is the event; echoes are a different hypothesis.
    studied = sorted((e.hydrated() for e in events), key=lambda e: (e.ts, e.content_hash))
    if cfg.roots_only:
        seen_roots: set[str] = set()
        kept: list[MarketEvent] = []
        for e in studied:
            root = e.root_event_id or e.content_hash
            if root in seen_roots:
                continue
            seen_roots.add(root)
            kept.append(e)
        studied = kept
    report.n_roots_studied = len(studied)

    panels: dict[str, _SymbolPanel | None] = {}

    def panel(symbol: str) -> _SymbolPanel | None:
        if symbol not in panels:
            bars = bars_by_symbol.get(symbol, [])
            panels[symbol] = _build_panel(bars, market_bars if symbol != cfg.market_symbol else bars)
        return panels[symbol]

    max_w = max((*cfg.windows, cfg.primary_window))
    cells: dict[tuple[str, ...], CellResult] = {}
    obs_by_cell: dict[tuple[str, ...], list[_Obs]] = {}
    anchors_by_symbol: dict[str, list[int]] = {}
    raw_obs: list[tuple[tuple[str, ...], _Obs]] = []

    for e in studied:
        symbols = e.symbols or (cfg.market_symbol,)
        key = cell_of(e)
        cell = cells.setdefault(key, CellResult(key=key))
        for symbol in symbols:
            cell.n_total += 1
            pnl = panel(symbol)
            if pnl is None:
                cell.n_skipped += 1
                continue
            # The first bar OPENING after the event is the first you could trade into (conservative).
            anchor = bisect_right(pnl.ts, e.ts)
            containing = anchor - 1
            # β/σ estimation ends BEFORE the pre-window starts, so pre-event leakage can't inflate the very
            # σ that standardizes it (the canon's estimation-window/event-window separation).
            est_lo, est_hi = containing - cfg.pre_window - cfg.beta_window, containing - cfg.pre_window - 1
            if est_lo < 1 or anchor + max_w - 1 >= len(pnl.r_a):
                cell.n_skipped += 1
                continue
            est = pnl.beta_sigma(est_lo, est_hi, use_market=symbol != cfg.market_symbol)
            if est is None:
                cell.n_skipped += 1
                continue
            beta, sigma, sigma_m = est
            scars: dict[int, float] = {}
            ok = True
            for w in sorted({*cfg.windows, cfg.primary_window}):
                s = pnl.scar(anchor, w, beta, sigma)
                if s is None:
                    ok = False
                    break
                scars[w] = s
            pre = pnl.scar(containing - cfg.pre_window, cfg.pre_window, beta, sigma)
            if not ok or pre is None:
                cell.n_skipped += 1
                continue
            o = _Obs(symbol=symbol, anchor=anchor, content_hash=e.content_hash, scars=scars, pre_scar=pre)
            mz = pnl.market_z(anchor, cfg.primary_window, sigma_m) if symbol != cfg.market_symbol else None
            if mz is not None and abs(mz) > cfg.market_z:
                o.market_comove = True
            raw_obs.append((key, o))
            anchors_by_symbol.setdefault(symbol, []).append(anchor)

    # Confounder pass: two ROOT events on one symbol with anchors within exclusion_bars contaminate each
    # other's windows — both are excluded from the clean set (conservative, per the event-study canon).
    for symbol, anchors in anchors_by_symbol.items():
        anchors.sort()
    for key, o in raw_obs:
        anchors = anchors_by_symbol[o.symbol]
        i = bisect_left(anchors, o.anchor)
        near_prev = i > 0 and o.anchor - anchors[i - 1] <= cfg.exclusion_bars
        near_next = i + 1 < len(anchors) and anchors[i + 1] - o.anchor <= cfg.exclusion_bars
        o.confounded = near_prev or near_next
        cell = cells[key]
        if o.confounded:
            cell.n_confounded += 1
        elif o.market_comove:
            cell.n_comove += 1
        else:
            cell.n_clean += 1
            obs_by_cell.setdefault(key, []).append(o)

    # Placebo machinery: per symbol, candidate anchors bucketed by (weekday, hour, trailing-vol tercile),
    # excluding the neighbourhood of every real anchor — the identical pipeline then runs on matched
    # pseudo-events, and the p-value is the fraction of placebo set-means at least as extreme as the real one.
    candidate_buckets: dict[str, dict[tuple[int, int, int], list[int]]] = {}
    candidate_meta: dict[str, dict[int, tuple[float, float, float]]] = {}  # anchor → (β, σ, σ_m)
    candidate_cutoffs: dict[str, tuple[float, float]] = {}                 # symbol → vol tercile cutoffs
    candidate_pool: dict[str, list[int]] = {}                              # symbol → every candidate anchor

    def build_candidates(symbol: str) -> None:
        if symbol in candidate_buckets:
            return
        pnl = panel(symbol)
        buckets: dict[tuple[int, int, int], list[int]] = {}
        meta: dict[int, tuple[float, float, float]] = {}
        candidate_buckets[symbol], candidate_meta[symbol] = buckets, meta
        candidate_cutoffs[symbol], candidate_pool[symbol] = (0.0, 0.0), []
        if pnl is None:
            return
        real = anchors_by_symbol.get(symbol, [])
        n = len(pnl.r_a)
        lo_idx = cfg.beta_window + cfg.pre_window + 2
        hi_idx = n - max_w
        # Stride keeps the pool computation O(n/stride) and the candidates non-overlapping-ish; the pool
        # stays thousands-deep on a year of minute bars.
        stride = max(1, (hi_idx - lo_idx) // 5000)
        pre_pass: list[tuple[int, float, float, float]] = []
        for a in range(lo_idx, hi_idx, stride):
            i = bisect_left(real, a)
            if (i > 0 and a - real[i - 1] <= cfg.exclusion_bars) or (i < len(real) and real[i] - a <= cfg.exclusion_bars):
                continue
            est = pnl.beta_sigma(
                a - 1 - cfg.pre_window - cfg.beta_window, a - 2 - cfg.pre_window,
                use_market=symbol != cfg.market_symbol,
            )
            if est is None:
                continue
            pre_pass.append((a, *est))
        if not pre_pass:
            return
        vols = sorted(row[2] for row in pre_pass)  # σ_abnormal is the matching vol measure
        t1, t2 = vols[len(vols) // 3], vols[(2 * len(vols)) // 3]
        candidate_cutoffs[symbol] = (t1, t2)
        for a, beta, sigma, sigma_m in pre_pass:
            tercile = 0 if sigma <= t1 else (1 if sigma <= t2 else 2)
            ts = pnl.ts[a]
            buckets.setdefault((ts.weekday(), ts.hour, tercile), []).append(a)
            meta[a] = (beta, sigma, sigma_m)
            candidate_pool[symbol].append(a)

    def matched_candidate(symbol: str, anchor: int) -> int | None:
        """A placebo anchor matched on (weekday, hour, vol tercile); relaxes to (weekday, hour) → hour-of-day
        → any candidate when a bucket is empty, so thin histories degrade gracefully rather than abstain."""
        build_candidates(symbol)
        pnl = panel(symbol)
        buckets = candidate_buckets[symbol]
        if pnl is None or not buckets:
            return None
        ts = pnl.ts[anchor]
        est = pnl.beta_sigma(
            anchor - 1 - cfg.pre_window - cfg.beta_window, anchor - 2 - cfg.pre_window,
            use_market=symbol != cfg.market_symbol,
        )
        vol = est[1] if est else 0.0
        t1, t2 = candidate_cutoffs[symbol]
        tercile = 0 if vol <= t1 else (1 if vol <= t2 else 2)
        exact = buckets.get((ts.weekday(), ts.hour, tercile))
        if exact:
            return rng.choice(exact)
        same_wd_hr = [a for bk, lst in buckets.items() if bk[0] == ts.weekday() and bk[1] == ts.hour for a in lst]
        if same_wd_hr:
            return rng.choice(same_wd_hr)
        same_hr = [a for bk, lst in buckets.items() if bk[1] == ts.hour for a in lst]
        if same_hr:
            return rng.choice(same_hr)
        pool = candidate_pool[symbol]
        return rng.choice(pool) if pool else None

    def placebo_pvalues(observations: list[_Obs]) -> tuple[float, float] | None:
        """(primary-window p, pre-window p): two-sided RI against placebo_sets matched pseudo-event sets."""
        real_mean = sum(o.scars[cfg.primary_window] for o in observations) / len(observations)
        real_pre = sum(o.pre_scar for o in observations) / len(observations)
        ge_main = ge_pre = 0
        sets_done = 0
        for _ in range(cfg.placebo_sets):
            mains: list[float] = []
            pres: list[float] = []
            for o in observations:
                a = matched_candidate(o.symbol, o.anchor)
                if a is None:
                    continue
                pnl = panel(o.symbol)
                beta, sigma, _sm = candidate_meta[o.symbol][a]
                s = pnl.scar(a, cfg.primary_window, beta, sigma)
                p = pnl.scar(a - 1 - cfg.pre_window, cfg.pre_window, beta, sigma)
                if s is not None and p is not None:
                    mains.append(s)
                    pres.append(p)
            if not mains:
                continue
            sets_done += 1
            if abs(sum(mains) / len(mains)) >= abs(real_mean):
                ge_main += 1
            if abs(sum(pres) / len(pres)) >= abs(real_pre):
                ge_pre += 1
        if sets_done == 0:
            return None
        return (1 + ge_main) / (1 + sets_done), (1 + ge_pre) / (1 + sets_done)

    # Per-cell statistics + inference, in deterministic key order.
    ordered = sorted(cells.keys())
    for key in ordered:
        cell = cells[key]
        observations = obs_by_cell.get(key, [])
        if observations:
            for w in sorted({*cfg.windows, cfg.primary_window}):
                cell.mean_scar[w] = sum(o.scars[w] for o in observations) / len(observations)
            cell.mean_pre_scar = sum(o.pre_scar for o in observations) / len(observations)
        if len(observations) < cfg.min_events:
            cell.verdict = "insufficient"
            continue
        pvals = placebo_pvalues(observations)
        if pvals is None:
            cell.verdict = "insufficient"
            continue
        cell.ri_pvalue, cell.pre_pvalue = pvals
        cell.leakage_flag = cell.pre_pvalue < 0.10
        cell.verdict = "fail"  # provisional; FDR decides pass below

    # BH-FDR across every cell that earned a p-value (window/type/source shopping is corrected here).
    tested = [cells[k] for k in ordered if cells[k].ri_pvalue is not None]
    if tested:
        mask = benjamini_hochberg([c.ri_pvalue for c in tested], q=cfg.fdr_q)
        for c, ok in zip(tested, mask, strict=True):
            # A leaky cell never passes: a significant PRE-window means the tape moved before the "event"
            # — the event is an echo of the move, not its cause.
            c.fdr_pass = bool(ok) and not c.leakage_flag
            c.verdict = "pass" if c.fdr_pass else "fail"

    report.cells = [cells[k] for k in ordered]
    return report
