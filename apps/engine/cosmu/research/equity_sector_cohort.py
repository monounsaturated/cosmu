# intent: test whether a SECTOR overlay carries an exploitable edge after REALISTIC equity costs — removing the
# market-beta + single-name survivorship that killed the raw long-only books. TWO constructions are gated together
# as ONE cohort, routed through the EXISTING deterministic scorer + cohort.promote_cohort BH-FDR (q=0.10):
#   (a) SECTOR ROTATION on the 9 sector ETFs (XLK/XLF/XLE/XLV/XLY/XLP/XLI/XLU/XLB): rank by trailing 12-1 month
#       momentum, hold the top-k sectors equal-weight, rebalanced MONTHLY. Disconfirmers: random-rank placebo,
#       and an equal-weight-all-9-sectors benchmark (rotation must beat just owning every sector).
#   (b) SECTOR-NEUTRAL single-name book: classify the 58 single names into the 9 GICS sectors, rank names WITHIN
#       each sector by momentum (or reversal), go LONG top / SHORT bottom inside each sector, dollar-neutral
#       across sectors. This is market-neutral AND sector-neutral, so the surviving-universe long bias is
#       differenced out. Disconfirmers: random-within-sector placebo, and the opposite-sign sibling.
#
# DOCTRINE: ZERO LLM calls. The scorer thresholds + promote_cohort q=0.10 are NOT changed (only routed). Every grid/
# param variant (each k, each lookback, each sign, each placebo seed) is registered as a trial so deflation/FDR see
# the true count. Fresh tempfile cohort store. Split-adjusted close-to-close (Yahoo v8 adjusts close for splits).
# NO synthetic / zero fill — a month missing a bar for a name simply drops that name that month. NO look-ahead — the
# ranking signal at month m uses only returns realized through m's close; the book earns month m+1's return.
#
# EQUITY FEE MODEL (commission-free retail, NOT crypto): ETFs ~6 bps/side; single names ~13 bps/side; ~0 commission.
# Cost is applied to the realized MONTHLY two-sided turnover of each book (Σ|w_t - w_{t-1}| * per-side cost), so a
# low-turnover monthly rotation is charged honestly little and a churny dollar-neutral book is charged honestly more.
#
# SURVIVORSHIP: the single-name universe is TODAY's survivors, so any LONG-ONLY single-name return is inflated and
# uninvestable. The single-name construction here is dollar-neutral AND sector-neutral precisely to difference that
# bias out; we still flag it. The sector-ETF rotation is survivorship-clean (the 9 SPDRs are not selected on outcome).

from __future__ import annotations

import hashlib
import json
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics, cscv_pbo, score
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")


def _placebo_key(seed: int, month: tuple[int, int], sym: str) -> float:
    """Deterministic pseudo-random rank key in [0,1) for the placebo arms. Uses blake2b (NOT Python's salted
    builtin hash) so the random-rank disconfirmer is byte-reproducible across processes — a placebo that wanders
    run-to-run is a weak disconfirmer."""
    h = hashlib.blake2b(f"{seed}|{month[0]}-{month[1]}|{sym}".encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") % 1_000_003) / 1_000_003.0

# Per-SIDE cost (fraction). 1 bp = 0.0001.
COST_ETF_PER_SIDE = 0.0006      # ~6 bps/side liquid sector/broad ETFs
COST_STOCK_PER_SIDE = 0.0013    # ~13 bps/side single large-caps

# The 9 GICS sector SPDRs that define the rotation universe AND the sector buckets for the neutral book.
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
# Broad-market / non-sector ETFs — excluded from everything (not a tradable sector leg, not a single name).
BROAD_ETFS = {"SPY", "QQQ", "DIA", "IWM", "GLD", "TLT"}

# GICS sector classification of each single name -> its SPDR bucket. Hand-mapped from each issuer's GICS sector.
# (Communication Services has no dedicated SPDR among the 9 here; GOOGL/META/NFLX/DIS/T/VZ map to their pre-2018
#  GICS homes: internet/media names sit with Consumer Discretionary tech-adjacent (XLY) for GOOGL/META/NFLX/DIS,
#  telecoms T/VZ with Utilities-like defensives is wrong — they are their own group; to avoid a 1-2 name bucket we
#  fold T/VZ into XLK-adjacent? No. We instead drop names with no clean 9-bucket home rather than mis-bucket.)
SECTOR_OF: dict[str, str] = {
    # Information Technology -> XLK
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "ADBE": "XLK", "CRM": "XLK",
    "CSCO": "XLK", "ORCL": "XLK", "AMD": "XLK", "INTC": "XLK", "IBM": "XLK", "TXN": "XLK",
    "QCOM": "XLK", "V": "XLK", "MA": "XLK",  # V/MA are GICS Financials post-2016 -> see below; tentatively XLK
    # Financials -> XLF
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "C": "XLF", "GS": "XLF", "AXP": "XLF",
    "SCHW": "XLF", "SPGI": "XLF",
    # Energy -> XLE
    "XOM": "XLE", "CVX": "XLE",
    # Health Care -> XLV
    "JNJ": "XLV", "UNH": "XLV", "LLY": "XLV", "ABBV": "XLV", "MRK": "XLV", "PFE": "XLV",
    # Consumer Discretionary -> XLY
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "LOW": "XLY", "MCD": "XLY", "NKE": "XLY",
    "SBUX": "XLY",
    # Consumer Staples -> XLP
    "PG": "XLP", "KO": "XLP", "PEP": "XLP", "WMT": "XLP", "COST": "XLP",
    # Industrials -> XLI
    "BA": "XLI", "CAT": "XLI", "HON": "XLI", "GE": "XLI", "MMM": "XLI", "RTX": "XLI",
    "UNP": "XLI", "UPS": "XLI",
    # Materials -> XLB
    "LIN": "XLB",
    # Communication Services (no 9-bucket SPDR among the chosen set; placed by primary listing sector affinity):
    # GOOGL/META/NFLX historically Tech-adjacent -> XLK; DIS Consumer-Disc -> XLY; T/VZ telecom -> own group, no
    # clean bucket -> DROPPED from the neutral book to avoid mis-classification noise (NO synthetic bucket).
    "GOOGL": "XLK", "META": "XLK", "NFLX": "XLK", "DIS": "XLY",
}
# V/MA: GICS reclassified card networks to "Financials" in 2016 industry shuffles but they trade as payment-tech;
# keep them in XLK (their behavioural sector) — the within-sector rank only needs a coherent comovement bucket.
# T, VZ deliberately absent (no clean 9-bucket home).

# ---- SURVIVORSHIP FIX: fold in the FADED / declined large-caps backfilled by equity_faded_backfill, each already
# classified to its GICS-SPDR bucket. This puts genuine LOSERS into every sector bucket, so the WITHIN-sector
# short leg shorts real laggards (not just ex-winners) and the long leg is no longer drawn from survivors alone.
# Names not present in the cache are simply never seen by build_panel (NO synthetic fill).
try:
    from cosmu.research.equity_faded_backfill import FADED as _FADED
    for _sym, _sec in _FADED.items():
        SECTOR_OF.setdefault(_sym, _sec)
except Exception:  # noqa: BLE001 — backfill module optional; cohort still runs on the base mapping
    pass


@dataclass
class Series:
    symbol: str
    ts: list[int]
    close: list[float]


def load_universe() -> dict[str, Series]:
    out: dict[str, Series] = {}
    for f in sorted(CACHE.glob("*_1d.json")):
        sym = f.name.replace("_1d.json", "")
        rows = json.loads(f.read_text())
        out[sym] = Series(sym, [int(r["ts"]) for r in rows], [float(r["close"]) for r in rows])
    return out


def _month_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, UTC).date()
    return (d.year, d.month)


def monthly_closes(s: Series) -> dict[tuple[int, int], float]:
    """Last close in each calendar month (the month-end close). PIT: only realized bars used."""
    by_month: dict[tuple[int, int], tuple[int, float]] = {}
    for t, c in zip(s.ts, s.close, strict=True):
        mk = _month_key(t)
        if mk not in by_month or t >= by_month[mk][0]:
            by_month[mk] = (t, c)
    return {mk: v[1] for mk, v in by_month.items()}


@dataclass
class Panel:
    """Month-grid panel. `level[m][sym]` = month-end close; `ret[m][sym]` = that-month total return (vs prev month).
    Months are the union across symbols; a symbol simply absent in a month is not fillable (NO synthetic)."""

    months: list[tuple[int, int]]
    level: dict[tuple[int, int], dict[str, float]]
    ret: dict[tuple[int, int], dict[str, float]]
    symbols: list[str]


def build_panel(universe: dict[str, Series], symbols: list[str]) -> Panel:
    mclose = {sym: monthly_closes(universe[sym]) for sym in symbols if sym in universe}
    all_months = sorted({mk for sym in mclose for mk in mclose[sym]})
    idx = {mk: i for i, mk in enumerate(all_months)}
    level: dict[tuple[int, int], dict[str, float]] = {m: {} for m in all_months}
    ret: dict[tuple[int, int], dict[str, float]] = {m: {} for m in all_months}
    for sym, wc in mclose.items():
        for mk, c in wc.items():
            level[mk][sym] = c
            i = idx[mk]
            if i == 0:
                continue
            prev = all_months[i - 1]
            if prev in wc and wc[prev] > 0:
                ret[mk][sym] = c / wc[prev] - 1.0
    return Panel(all_months, level, ret, list(mclose.keys()))


def momentum_signal(panel: Panel, m_idx: int, sym: str, lookback: int, skip: int) -> float | None:
    """Trailing (lookback - skip) month return: level[m-skip]/level[m-lookback] - 1, the classic 12-1 momentum
    (skip the most recent month to avoid 1-month reversal contamination). Needs both month-end levels present.
    NO look-ahead: both endpoints are <= month m's close, and the harvested return is month m+1."""
    months = panel.months
    if m_idx - lookback < 0 or m_idx - skip < 0:
        return None
    m_recent = months[m_idx - skip]
    m_old = months[m_idx - lookback]
    lr = panel.level[m_recent].get(sym)
    lo = panel.level[m_old].get(sym)
    if lr is None or lo is None or lo <= 0:
        return None
    return lr / lo - 1.0


@dataclass
class StratResult:
    net: list[float]
    gross: list[float]
    turnover: list[float]
    months: list[tuple[int, int]]


def _apply_turnover_cost(weights: dict[str, float], prev: dict[str, float],
                         cost_of: dict[str, float], default_cost: float) -> tuple[float, float]:
    """Return (two-sided turnover, cost) for moving from `prev` to `weights`."""
    names = set(weights) | set(prev)
    turnover = sum(abs(weights.get(s, 0.0) - prev.get(s, 0.0)) for s in names)
    cost = sum(abs(weights.get(s, 0.0) - prev.get(s, 0.0)) * cost_of.get(s, default_cost) for s in names)
    return turnover, cost


# ----------------------------------------------------------------------------------------------------------------
# (a) SECTOR ROTATION on the 9 sector ETFs
# ----------------------------------------------------------------------------------------------------------------
def run_rotation(panel: Panel, *, top_k: int, lookback: int, skip: int,
                 mode: str = "momentum", rng_seed: int | None = None) -> StratResult:
    """LONG-ONLY equal-weight top-k of the 9 sector ETFs each month.
    mode='momentum' -> rank by 12-1 momentum, hold the strongest k (rotation).
    mode='equalweight' -> the benchmark: hold ALL present sectors equal-weight every month (no selection).
    rng_seed set -> random-rank placebo: pick k sectors by a deterministic pseudo-random key."""
    months = panel.months
    prev: dict[str, float] = {}
    net: list[float] = []
    gross: list[float] = []
    turn: list[float] = []
    used: list[tuple[int, int]] = []
    cost_of = {s: COST_ETF_PER_SIDE for s in SECTOR_ETFS}

    for i in range(len(months) - 1):
        m = months[i]
        m_next = months[i + 1]
        fwd = panel.ret[m_next]
        present = [s for s in SECTOR_ETFS if s in panel.level[m] and s in fwd]
        if len(present) < 5:
            prev = {}
            continue

        if mode == "equalweight":
            chosen = present
        elif rng_seed is not None:
            chosen = sorted(present, key=lambda sym: _placebo_key(rng_seed, m, sym))[:top_k]
        else:
            scored = [(s, momentum_signal(panel, i, s, lookback, skip)) for s in present]
            scored = [(s, v) for s, v in scored if v is not None]
            if len(scored) < top_k:
                prev = {}
                continue
            scored.sort(key=lambda x: x[1], reverse=True)  # strongest momentum first
            chosen = [s for s, _ in scored[:top_k]]

        if not chosen:
            prev = {}
            continue
        w = {s: 1.0 / len(chosen) for s in chosen}
        gross_ret = sum(w[s] * fwd[s] for s in w)
        tov, cost = _apply_turnover_cost(w, prev, cost_of, COST_ETF_PER_SIDE)
        net.append(gross_ret - cost)
        gross.append(gross_ret)
        turn.append(tov)
        used.append(m_next)
        prev = w

    return StratResult(net, gross, turn, used)


# ----------------------------------------------------------------------------------------------------------------
# (b) SECTOR-NEUTRAL single-name book (dollar-neutral within each sector, summed across sectors)
# ----------------------------------------------------------------------------------------------------------------
def run_sector_neutral(panel: Panel, *, sign: int, lookback: int, skip: int,
                       frac: float = 1 / 3, rng_seed: int | None = None) -> StratResult:
    """Within each GICS sector bucket, rank that sector's present names by 12-1 momentum, then:
        sign=+1 -> MOMENTUM: long top-frac winners, short bottom-frac losers WITHIN the sector.
        sign=-1 -> REVERSAL sibling (disconfirmer): the opposite.
    Each sector contributes a self-financing (dollar-neutral) sub-book; sub-books are equal-weighted across the
    sectors that have >= 2*ceil(frac*n) tradable names, so the whole book is dollar-neutral AND sector-neutral.
    rng_seed set -> random-WITHIN-sector placebo. NO look-ahead, NO synthetic fill."""
    months = panel.months
    prev: dict[str, float] = {}
    net: list[float] = []
    gross: list[float] = []
    turn: list[float] = []
    used: list[tuple[int, int]] = []
    cost_of = {s: COST_STOCK_PER_SIDE for s in panel.symbols}

    # group the universe's single names by sector bucket
    buckets: dict[str, list[str]] = {}
    for sym in panel.symbols:
        sec = SECTOR_OF.get(sym)
        if sec is not None:
            buckets.setdefault(sec, []).append(sym)

    for i in range(len(months) - 1):
        m = months[i]
        m_next = months[i + 1]
        fwd = panel.ret[m_next]

        # build per-sector long/short legs
        active_sectors: list[dict[str, float]] = []  # each: per-name weight dict, self-financing (sum 0)
        for syms in buckets.values():
            names = []
            for s in syms:
                if s not in fwd or s not in panel.level[m]:
                    continue
                if rng_seed is not None:
                    sigv = _placebo_key(rng_seed, m, s)
                else:
                    sigv = momentum_signal(panel, i, s, lookback, skip)
                if sigv is not None:
                    names.append((s, sigv))
            n = len(names)
            k = int(round(n * frac))
            if n < 4 or k < 1:
                continue
            names.sort(key=lambda x: x[1])  # ascending: losers .. winners
            losers = [s for s, _ in names[:k]]
            winners = [s for s, _ in names[-k:]]
            long_names = winners if sign == +1 else losers   # momentum longs winners
            short_names = losers if sign == +1 else winners
            sub: dict[str, float] = {}
            for s in long_names:
                sub[s] = sub.get(s, 0.0) + 1.0 / len(long_names)
            for s in short_names:
                sub[s] = sub.get(s, 0.0) - 1.0 / len(short_names)
            active_sectors.append(sub)

        if not active_sectors:
            prev = {}
            continue

        # equal-weight the sector sub-books, then scale gross exposure to 1.0 (0.5 long + 0.5 short)
        w: dict[str, float] = {}
        per = 1.0 / len(active_sectors)
        for sub in active_sectors:
            for s, wt in sub.items():
                w[s] = w.get(s, 0.0) + wt * per
        gross_exposure = sum(abs(v) for v in w.values())
        if gross_exposure > 0:
            scale = 1.0 / gross_exposure
            w = {s: v * scale for s, v in w.items()}

        gross_ret = sum(w[s] * fwd[s] for s in w)
        tov, cost = _apply_turnover_cost(w, prev, cost_of, COST_STOCK_PER_SIDE)
        net.append(gross_ret - cost)
        gross.append(gross_ret)
        turn.append(tov)
        used.append(m_next)
        prev = w

    return StratResult(net, gross, turn, used)


# ----------------------------------------------------------------------------------------------------------------
# metrics + gate plumbing (mirrors equity_reversal_cohort exactly)
# ----------------------------------------------------------------------------------------------------------------
def _max_drawdown(returns: list[float]) -> float:
    peak = equity = 1.0
    mdd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def _folds_positive_pct(returns: list[float], k: int = 5) -> float:
    if len(returns) < k:
        return 0.0
    size = len(returns) // k
    pos = 0
    for f in range(k):
        seg = returns[f * size:(f + 1) * size] if f < k - 1 else returns[f * size:]
        if seg and statistics.fmean(seg) > 0:
            pos += 1
    return pos / k


def metrics_from_returns(returns: list[float], *, trials_counted: int, long_only: bool,
                         bench_return: float = 0.0) -> BacktestMetrics:
    """Monthly NET return stream -> BacktestMetrics with a REAL purged+embargoed out-of-sample holdout.

    All gate-facing stats (Sharpe, skew, oos_return, n_obs, drawdown, folds) are computed on the IN-SAMPLE slice;
    `holdout_deflated_sharpe` is the genuine DSR of the held-out tail (last ~20%, with an embargo). This replaces
    the prior stub that pinned the holdout to 0.0001 and computed every stat on the full sample. embargo=12 covers
    the 12-month formation window of the 12-1 momentum book so no formation period straddles the split boundary."""
    metrics, _split = metrics_with_holdout(
        returns, trials_counted=trials_counted, periods_per_year=12,
        holdout_frac=0.2, embargo=12, long_only=long_only, bench_return=bench_return)
    return metrics


@dataclass
class Verdict:
    n_months: int
    window: str
    candidates: list[dict] = field(default_factory=list)
    verdict: str = ""
    headline: str = ""
    notes: list[str] = field(default_factory=list)


def run(*, persist: bool = False) -> Verdict:
    """`persist=True` records the cohort verdict to durable experiment-memory (gate_verdicts) via the REAL
    configured store (separate from the tempfile trial-ledger below) — main() sets it on real runs; tests leave
    it False so they never touch the durable store."""
    universe = load_universe()
    all_syms = sorted(universe)
    single_names = [s for s in all_syms if s not in SECTOR_ETFS and s not in BROAD_ETFS]

    # Two panels share a tempfile store + one trial ledger so FDR spans the whole family.
    etf_panel = build_panel(universe, SECTOR_ETFS)
    name_panel = build_panel(universe, single_names)
    if len(etf_panel.months) < 60:
        return Verdict(len(etf_panel.months), "n/a", verdict="INSUFFICIENT-DATA", headline="too few months")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-eqsec-')}/g.sqlite3",
                           openrouter_api_key=None))
    base_gates = store.settings.gates

    # --------------------------------------------------------------------------------------------------------
    # GRID. Every variant below is registered as a trial (true multiple-testing count).
    #   rotation: top_k in {2,3,4} x lookback/skip in {(12,1),(6,1)}  + equalweight benchmark + placebos
    #   sector-neutral: sign in {+1,-1} x frac in {0.25, 1/3} x lookback/skip {(12,1),(6,1)} + placebos
    # --------------------------------------------------------------------------------------------------------
    rotation_variants: list[tuple[str, StratResult, BacktestMetrics]] = []
    neutral_variants: list[tuple[str, StratResult, BacktestMetrics]] = []
    eqw_variants: list[tuple[str, StratResult, BacktestMetrics]] = []
    rot_placebo: list[tuple[str, StratResult, BacktestMetrics]] = []
    neu_placebo: list[tuple[str, StratResult, BacktestMetrics]] = []

    # equal-weight-all-sectors benchmark (the rotation disconfirmer + the long-only hurdle source)
    eqw_res = run_rotation(etf_panel, top_k=9, lookback=12, skip=1, mode="equalweight")
    eqw_total = 1.0
    for r in eqw_res.net:
        eqw_total *= (1.0 + r)
    eqw_total -= 1.0
    eqw_m = metrics_from_returns(eqw_res.net, trials_counted=1, long_only=True, bench_return=eqw_total)
    register_trial(store, float(eqw_m.sharpe_per_obs), source="equity_sector", label="eqw_benchmark")
    eqw_variants.append(("eqw_benchmark", eqw_res, eqw_m))

    for top_k in (2, 3, 4):
        for lookback, skip in ((12, 1), (6, 1)):
            res = run_rotation(etf_panel, top_k=top_k, lookback=lookback, skip=skip, mode="momentum")
            # rotation must beat just owning all 9 sectors -> long-only hurdle = eqw benchmark net total
            m = metrics_from_returns(res.net, trials_counted=1, long_only=True, bench_return=eqw_total)
            register_trial(store, float(m.sharpe_per_obs), source="equity_sector",
                           label=f"rotation:k={top_k},lb={lookback}")
            rotation_variants.append((f"k={top_k},lb={lookback}", res, m))

    for seed in range(1, 6):
        res = run_rotation(etf_panel, top_k=3, lookback=12, skip=1, mode="momentum", rng_seed=seed)
        m = metrics_from_returns(res.net, trials_counted=1, long_only=True, bench_return=eqw_total)
        register_trial(store, float(m.sharpe_per_obs), source="equity_sector", label=f"rot_placebo:seed={seed}")
        rot_placebo.append((f"seed={seed}", res, m))

    for sign in (+1, -1):
        for frac in (0.25, 1 / 3):
            for lookback, skip in ((12, 1), (6, 1)):
                res = run_sector_neutral(name_panel, sign=sign, lookback=lookback, skip=skip, frac=frac)
                m = metrics_from_returns(res.net, trials_counted=1, long_only=False)
                tag = "mom" if sign == +1 else "rev"
                register_trial(store, float(m.sharpe_per_obs), source="equity_sector",
                               label=f"neutral_{tag}:frac={frac:.2f},lb={lookback}")
                neutral_variants.append((f"{tag}:frac={frac:.2f},lb={lookback},sign={sign}", res, m))

    for seed in range(1, 6):
        res = run_sector_neutral(name_panel, sign=+1, lookback=12, skip=1, frac=1 / 3, rng_seed=seed)
        m = metrics_from_returns(res.net, trials_counted=1, long_only=False)
        register_trial(store, float(m.sharpe_per_obs), source="equity_sector", label=f"neu_placebo:seed={seed}")
        neu_placebo.append((f"seed={seed}", res, m))

    trials = trial_stats(store)

    # gate-best selector (passed first, then higher DSR) over a list of (tag,res,m)
    def gate_best(variants, gates):
        best = None
        best_key = (-1, -1.0)
        for tag, res, m in variants:
            v = score(m, gates, trials=trials)
            key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
            if best is None or key > best_key:
                best_key = key
                best = (tag, res, m)
        return best

    gates_longonly = base_gates  # require_beat_buy_and_hold ON (default True) -> rotation must beat eqw
    gates_neutral = base_gates.model_copy(update={"require_beat_buy_and_hold": False})

    rot_best = gate_best(rotation_variants, gates_longonly)
    neu_best = gate_best(neutral_variants, gates_neutral)
    rot_plc_best = gate_best(rot_placebo, gates_longonly)
    neu_plc_best = gate_best(neu_placebo, gates_neutral)
    eqw_best = eqw_variants[0]

    # Real CSCV-PBO within each arm's own config population (legitimate — same construction, varied params).
    # Computed on the IN-SAMPLE slice ONLY (exclude the held-out tail) so the holdout stays untouched.
    rot_streams = [purged_embargoed_split(res.net, embargo=12).in_sample
                   for _, res, _ in rotation_variants if len(res.net) >= 20]
    neu_streams = [purged_embargoed_split(res.net, embargo=12).in_sample
                   for _, res, _ in neutral_variants if len(res.net) >= 20]
    rot_pbo = cscv_pbo(rot_streams) if len(rot_streams) >= 2 else 1.0
    neu_pbo = cscv_pbo(neu_streams) if len(neu_streams) >= 2 else 1.0

    # ---- DISTINCT candidates -> promote_cohort (BH-FDR q=0.10). The cohort spans BOTH constructions + the
    #      disconfirmers, so the family-wise correction is honest across the whole round. ----
    candidates: list[Candidate] = []
    meta: dict[str, tuple[StratResult, BacktestMetrics, bool]] = {}

    def add(name: str, best, pbo: float | None, long_only: bool):
        tag, res, m = best
        # m already carries the in-sample folds_positive_pct AND the REAL purged+embargoed holdout DSR (from
        # metrics_from_returns -> metrics_with_holdout). The ONLY metric we attach here is the real CSCV-PBO.
        upd: dict = {}
        if pbo is not None:
            upd["pbo"] = Decimal(str(round(pbo, 6)))
        m = m.model_copy(update=upd) if upd else m
        var = statistics.pvariance(res.net) if len(res.net) > 1 else 1.0
        candidates.append(Candidate(id=name, metrics=m, net_profit=float(m.oos_return),
                                    source="equity_sector", label=f"{name}:{tag}", return_variance=var or 1.0))
        meta[name] = (res, m, long_only)

    add("sector_rotation", rot_best, rot_pbo, long_only=True)
    add("eqw_benchmark", eqw_best, None, long_only=True)
    add("rotation_placebo", rot_plc_best, None, long_only=True)
    add("sector_neutral", neu_best, neu_pbo, long_only=False)
    add("neutral_placebo", neu_plc_best, None, long_only=False)

    # promote_cohort scores each candidate with ONE gates object; the long-only beat-bh hurdle is enforced via the
    # candidate's buy_and_hold_return (set only on long-only metrics; 0 elsewhere) under require_beat_buy_and_hold.
    # We route with the hurdle ON; neutral candidates carry bh=0 so oos<=0 is the only way they trip it.
    persist_spec = durable_persist(
        run_id="equity-sector-overlay",
        hypothesis="an equity sector-rotation / sector-neutral overlay carries a gate-clearing edge after realistic fees",
        source="research/equity_sector", data_source="equities-offline",
    ) if persist else None
    promotions = promote_cohort(store, candidates, gates_longonly, fdr_q=0.10, register=False, trials=trials, persist=persist_spec)
    by_id = {p.candidate_id: p for p in promotions}

    rows: list[dict] = []
    for c in candidates:
        res, m, long_only = meta[c.id]
        p = by_id[c.id]
        gross_total = 1.0
        for g in res.gross:
            gross_total *= (1.0 + g)
        gross_total -= 1.0
        cost_ratio = (float(m.oos_return) / gross_total) if gross_total else float("nan")
        rows.append({
            "name": c.id,
            "net_total_return": round(float(m.oos_return), 5),
            "gross_total_return": round(gross_total, 5),
            "cost_ratio": round(cost_ratio, 3) if gross_total else None,
            "ann_sharpe": float(m.sharpe), "sharpe_per_obs": float(m.sharpe_per_obs),
            "deflated_sharpe_prob": round(float(p.deflated_sharpe_prob), 6),
            "pbo": float(m.pbo), "folds_positive": float(m.folds_positive_pct),
            "holdout_dsr": round(float(m.holdout_deflated_sharpe), 6),
            "n_months": m.num_trades, "max_dd": float(m.max_drawdown),
            "mean_monthly_turnover": round(statistics.fmean(res.turnover), 3) if res.turnover else 0.0,
            "win_rate": float(m.win_rate),
            "promoted": p.promoted, "survived_fdr": p.survived_fdr, "reasons": p.reasons,
        })

    m0 = etf_panel.months[0]
    m1 = etf_panel.months[-1]
    window = f"{m0[0]}-{m0[1]:02d} .. {m1[0]}-{m1[1]:02d}"
    rot_p = by_id["sector_rotation"]
    neu_p = by_id["sector_neutral"]
    any_real = rot_p.promoted or neu_p.promoted
    placebo_promoted = by_id["rotation_placebo"].promoted or by_id["neutral_placebo"].promoted
    if any_real and not placebo_promoted:
        verdict = "PASS"
        which = []
        if rot_p.promoted:
            which.append("sector-rotation")
        if neu_p.promoted:
            which.append("sector-neutral single-name")
        headline = f"{' + '.join(which)} SURVIVED the cohort gate + BH-FDR (q=0.10) with placebos rejected"
    else:
        verdict = "FAIL"
        headline = (f"NO sector construction survived: rotation promoted={rot_p.promoted} "
                    f"(DSR={rot_p.deflated_sharpe_prob:.3f}, {rot_p.reasons}); "
                    f"neutral promoted={neu_p.promoted} (DSR={neu_p.deflated_sharpe_prob:.3f}, {neu_p.reasons})")
        if placebo_promoted:
            headline += " | WARNING: a PLACEBO promoted -> machinery suspect"
    return Verdict(len(etf_panel.months), window, candidates=rows, verdict=verdict, headline=headline)


def _print(v: Verdict) -> None:
    print(f"\n=== EQUITY SECTOR OVERLAY COHORT — {v.verdict} ===")
    print(f"  months={v.n_months}  window={v.window}")
    print(f"  fees: ETFs {COST_ETF_PER_SIDE*1e4:.0f} bps/side, single names {COST_STOCK_PER_SIDE*1e4:.0f} bps/side, "
          f"on realized monthly turnover")
    print("  benchmark: rotation hurdle = beat equal-weight-all-9-sectors (net); neutral hurdle = beat cash (0)")
    for r in v.candidates:
        flag = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
        cr = r["cost_ratio"]
        print(f"  [{flag:>9}] {r['name']:<17} net={r['net_total_return']:+.4f} "
              f"gross={r['gross_total_return']:+.4f} cost_ratio={cr} "
              f"annSR={r['ann_sharpe']:+.2f} SRobs={r['sharpe_per_obs']:+.4f} DSR={r['deflated_sharpe_prob']:.3f} "
              f"holdoutDSR={r['holdout_dsr']:+.4f} "
              f"pbo={r['pbo']:.2f} folds+={r['folds_positive']:.2f} maxDD={r['max_dd']:.3f} "
              f"turn={r['mean_monthly_turnover']:.2f} win={r['win_rate']:.2f} fdr={'Y' if r['survived_fdr'] else 'N'} "
              f"n={r['n_months']}")
        if r["reasons"]:
            print(f"               reasons: {', '.join(r['reasons'])}")
    print(f"  HEADLINE: {v.headline}")


def main() -> int:
    _print(run(persist=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
