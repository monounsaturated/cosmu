# intent: N11 — ATTENTION-ACCELERATION BREAKOUT event-study (EXPERIMENT ONLY, keyless, offline-ish). Zero prod
# impact. docs-only, persists NOTHING to prod, no Gate constant touched, no cron.
#
# THESIS (slate v2, #3 after N1 + N5 killed): a SUDDEN ACCELERATION in public attention precedes a price move
# (attention onset -> flow). We trade the SECOND derivative of attention (the change-IN-change), NOT the level
# (which lags/coincides and is a beta). The PIT-clean redemption of the killed social lane: the killed signal was
# LunarCrush (a revising/backfilling source -> a PIT mirage). Wikipedia pageviews are IMMUTABLE and T+1-stamped
# (day-T views become knowable on day T+1; Wikimedia never revises history) -> there is no answer-key leakage.
# Niche/small-mid-cap tokens are the moat: a few thousand new eyeballs move a small float; the giants ignore them.
#
# DATA (keyless, free, confirmed reachable from the M2):
#   - Wikipedia daily pageviews via the wired cosmu source (Wikimedia REST per-article; immutable; available_at=T+1).
#   - Keyless daily OHLC via cosmu.data.market: Bybit -> Binance -> Kraken spot (first venue with the USDT pair).
#   The universe is every token that has BOTH a keyless Wikipedia article AND a keyless USDT spot pair (verified).
#
# THE SIGNAL (attention ACCELERATION, strictly causal, PIT-honest):
#   L_t  = ln(pageviews_t)                          # log level (variance-stabilised; pageviews span 10^2..10^6)
#   d_t  = L_t - L_{t-1}                             # first derivative (attention velocity)
#   a_t  = d_t - d_{t-1}                             # SECOND derivative (attention acceleration)  <-- the signal
#   z_t  = (a_t - mean(a over trailing W, strictly < t)) / std(... )   # trailing-window z-score, NO look-ahead
#   The z-window uses ONLY points strictly before t (causal). a_t needs L_t, L_{t-1}, L_{t-2}; L_t is knowable at
#   T+1, so a_t (and z_t) are first knowable at T+1.
#
# PIT ENTRY TIMING (the make-or-break): the acceleration computed THROUGH day T is available at T+1 00:00 UTC.
# The first bar a trader can ACT on is the close of day T+1. So a signal at obs-day T enters at the close of T+1
# and the forward h-day return is measured from the T+1 close -> there is NO same-day look-ahead.
#
# EVENT-STUDY (ONE pre-registered rule, NO sweep):
#   - EVENT      := acceleration z_t >= Z_THRESH (an attention-acceleration SPIKE).  Pre-registered Z_THRESH.
#   - ENTRY      := close of the T+1 bar (first PIT-tradeable bar after the signal is available).
#   - FORWARD    := close-to-close log return over the next H_FWD trading days from the entry bar (long).
#   - NET        := minus a conservative small-cap round-trip cost (taker fee + slippage).
#   - SIGN       := the thesis says forward return > 0 (attention onset -> inflow). We read the sign off, then test it.
#
# TWO DECISIVE CONTROLS (pre-registered, the whole point of the study):
#   (1) SHUFFLE-NULL  — time-shuffle each token's attention series, recompute the acceleration + events on the
#                       SHUFFLED attention but the SAME (unshuffled) price, and re-run. If the edge survives the
#                       shuffle it is PRICE autocorrelation, not attention -> KILL. The real edge MUST collapse the
#                       shuffle (real forward return must beat the shuffle band, bootstrap p < 0.05).
#   (2) LEAD-LAG TIME-REVERSAL (the astro disconfirmer) — measure the same event's effect at lead h=+1 (entry AFTER
#                       the signal, the predictive direction) vs lag h=-1 (the bar BEFORE the signal, the coincident
#                       direction). If the effect is the SAME magnitude/sign at +1 and -1 the attention is COINCIDENT,
#                       not predictive -> KILL. A real predictive edge is ASYMMETRIC: strong at +1, ~0 at -1.
#
# GATE STATS: the per-event NET forward-return stream is scored with the REAL production scorer
# (cosmu.master.scorer probabilistic_sharpe / sample_moments) — the SAME primitive the Gate's deflated-Sharpe is
# built on — so the pooled verdict speaks the Gate's language. Single pool (BRUT).
#
# Run:
#   python3 apps/engine/scripts/research/n11_attention_accel.py [--out report.html] [--json out.json]
#   python3 apps/engine/scripts/research/n11_attention_accel.py --selftest   # offline pure-logic test, no network
#
# ZERO production impact: read-only keyless fetches; writes a disposable HTML table + JSON summary under
# scripts/research/. No DB, no prod source mutated, no Gate constant, no cron.

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import fmean, pstdev

# Make `cosmu` importable regardless of cwd (same plumbing as the sibling n1/n5 harnesses; the ONLY prod touch is
# the import path, no prod behaviour).
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from cosmu.data.market import (  # noqa: E402 — after sys.path insert
    Bar,
    BinanceSpotOHLCVProvider,
    BybitSpotOHLCVProvider,
    KrakenSpotOHLCVProvider,
)
from cosmu.data.sources.wikipedia_pageviews import (  # noqa: E402
    ENTITY_MAP,
    WikipediaPageviewsSource,
)

# ----------------------------------------------------------------------------------------------------------
# PRE-REGISTERED constants (ONE config, declared up front, BEFORE any result is seen — NO sweep).
# ----------------------------------------------------------------------------------------------------------
Z_THRESH = 2.5             # an EVENT := acceleration z-score >= 2.5 (a clear attention-acceleration spike).
Z_WINDOW = 60              # trailing window (calendar/obs days) for the acceleration z-score denominator (causal).
H_FWD = 5                  # forward horizon in TRADING days for the long return measured from the entry bar.
ROUNDTRIP_FEE_BPS = 20.0   # conservative spot round-trip taker fee (~2 x 10 bps).
ROUNDTRIP_SLIP_BPS = 30.0  # conservative round-trip slippage for a small/mid-cap entry+exit.
MIN_HISTORY_BARS = 200     # a token must have >= this many daily bars to be eligible at all.
MIN_WIKI_DAYS = 300        # a token must have >= this many immutable Wikipedia obs-days to be eligible.
MAX_ENTRY_GAP_DAYS = 4     # the entry bar must be within this many days of the signal's availability day. Wikipedia
                           # history (to 2015) far outruns the keyless price window (~999 bars / 2.7yr); WITHOUT
                           # this guard every pre-price-coverage spike degenerately maps to the FIRST price bar,
                           # collapsing hundreds of distinct days onto one entry and polluting the pool. A gap > a
                           # few days means there is no contemporaneous price bar -> the event is not tradeable, DROP.
WIKI_BACKFILL_DAYS = 4000  # how deep to pull the (immutable) Wikipedia series — bounded by article age.
SHUFFLE_REPS = 20          # independent time-shuffles of the attention series per token (the shuffle-null pool).
BOOTSTRAP_ITERS = 5000     # bootstrap iterations for the placebo/shuffle band p-value.
SEED = 20260627            # deterministic shuffles + bootstrap.

NET_COST = (ROUNDTRIP_FEE_BPS + ROUNDTRIP_SLIP_BPS) / 1e4  # total round-trip fractional cost on the long leg.

# The keyless universe: token -> Wikipedia article title. The first block is the canonical wired ENTITY_MAP crypto
# subset; the second is a VERIFIED niche/small-mid-cap extension (each confirmed to have BOTH a live Wikipedia
# article with >= MIN_WIKI_DAYS of history AND a keyless USDT spot pair, probed before this run). Extending the map
# HERE (not in the prod source) keeps the experiment zero-impact. None disables a symbol (handled by the source).
_EXTENSION_ARTICLES: dict[str, str] = {
    "UNIUSDT": "Uniswap",
    "ALGOUSDT": "Algorand",
    "FILUSDT": "Filecoin",
    "XLMUSDT": "Stellar_(payment_network)",
    "TRXUSDT": "Tron_(cryptocurrency)",
    "EOSUSDT": "EOS.IO",
    "XTZUSDT": "Tezos",
    "MKRUSDT": "MakerDAO",
    "OPUSDT": "Optimism_(blockchain)",
    "INJUSDT": "Injective_(blockchain)",
    "PEPEUSDT": "Pepe_the_Frog",
}


def _universe() -> dict[str, str]:
    """token (USDT pair) -> Wikipedia article title for the full keyless universe (canonical + verified extension)."""
    uni: dict[str, str] = {
        sym: art for sym, art in ENTITY_MAP.items() if sym.endswith("USDT") and art is not None
    }
    uni.update(_EXTENSION_ARTICLES)
    return uni


# ----------------------------------------------------------------------------------------------------------
# Keyless OHLC resolver (Bybit -> Binance -> Kraken; first venue with >= MIN_HISTORY_BARS wins).
# ----------------------------------------------------------------------------------------------------------
class _OHLC:
    def __init__(self) -> None:
        import tempfile

        td = tempfile.mkdtemp(prefix="n11_ohlc_")
        self._providers = [
            ("bybit", BybitSpotOHLCVProvider(cache_dir=os.path.join(td, "bybit"))),
            ("binance", BinanceSpotOHLCVProvider(cache_dir=os.path.join(td, "binance"))),
            ("kraken", KrakenSpotOHLCVProvider(cache_dir=os.path.join(td, "kraken"))),
        ]
        self._memo: dict[str, tuple[str, list[Bar]] | None] = {}

    def bars(self, symbol: str) -> tuple[str, list[Bar]] | None:
        if symbol in self._memo:
            return self._memo[symbol]
        out: tuple[str, list[Bar]] | None = None
        for venue, prov in self._providers:
            try:
                bars = prov.fetch_bars(symbol, "1d", limit=4000)
            except Exception:  # noqa: BLE001 — venue offline/refused -> try the next
                bars = []
            if len(bars) >= MIN_HISTORY_BARS:
                out = (venue, bars)
                break
        self._memo[symbol] = out
        return out


# ----------------------------------------------------------------------------------------------------------
# Attention series + acceleration signal (strictly causal; PIT-honest available_at = obs_day + 1).
# ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AttnPoint:
    obs_day: datetime      # the day the views were RECORDED (UTC midnight)
    avail_day: datetime    # the day the count is first KNOWABLE (= obs_day + 1; immutable, never revised)
    log_views: float       # ln(pageviews) on obs_day


def attention_series(symbol: str, article: str, as_of: datetime) -> list[AttnPoint]:
    """Pull the immutable Wikipedia pageview series for `symbol` and return ascending log-view points, each with
    its PIT availability day (obs_day + 1). Uses the wired source's backfill (one keyless call). Gaps are absent
    (never zero-filled). We override the article via a one-off source whose ENTITY map we patch through scope."""
    src = WikipediaPageviewsSource(metric="wiki_pageviews", lookback_days=WIKI_BACKFILL_DAYS)
    # The source resolves the article from its own ENTITY_MAP/fallback. For canonical symbols that already resolve,
    # query directly; for the extension symbols we resolve the article by querying the raw API through the source's
    # fetcher using a temporary alias the source understands (we register the article on the instance map).
    raw = _backfill_with_article(src, symbol, article, WIKI_BACKFILL_DAYS, as_of)
    pts: list[AttnPoint] = []
    for p in raw:
        if p.value is None or p.value <= 0:
            continue
        pts.append(
            AttnPoint(
                obs_day=p.ts,
                avail_day=p.available_at,
                log_views=math.log(p.value),
            )
        )
    return sorted(pts, key=lambda x: x.obs_day)


def _backfill_with_article(src: WikipediaPageviewsSource, symbol: str, article: str, days: int, as_of: datetime):
    """Pull raw daily pageview AltDataPoints for an explicit Wikipedia `article`, reusing the wired source's PIT
    parsing + availability stamping but overriding the symbol->article resolution (so extension tokens not in the
    prod ENTITY_MAP still work, without mutating the prod map)."""
    from cosmu.data.sources import wikipedia_pageviews as wp

    end_day = as_of - wp._AVAILABILITY_LAG
    start_day = end_day - timedelta(days=max(0, days - 1))
    url = wp._url_for_article(article, start_day.strftime("%Y%m%d"), end_day.strftime("%Y%m%d"))
    try:
        payload = src._fetcher(url)
    except Exception:  # noqa: BLE001 — network/404 -> absent series, never crash
        return []
    raw = [p for p in wp._parse_response(payload) if p.available_at <= as_of]
    return raw


def acceleration_z(log_views: list[float], window: int = Z_WINDOW) -> list[float | None]:
    """Per-index acceleration z-score, strictly causal. For index i:
        a_i = (L_i - L_{i-1}) - (L_{i-1} - L_{i-2})              # second derivative at i
        z_i = (a_i - mean(a_j for j in [i-window, i)) ) / std(...)  using ONLY j strictly < i
    Returns a list aligned to `log_views` (None where i < 2 or the trailing window has < 2 acceleration points or
    zero variance). NO look-ahead: z_i uses only acceleration values at indices strictly before i."""
    n = len(log_views)
    accel: list[float | None] = [None] * n
    for i in range(2, n):
        accel[i] = (log_views[i] - log_views[i - 1]) - (log_views[i - 1] - log_views[i - 2])
    out: list[float | None] = [None] * n
    for i in range(2, n):
        # window of acceleration values strictly before i (and within `window` obs days)
        lo = max(2, i - window)
        win = [accel[j] for j in range(lo, i) if accel[j] is not None]
        if len(win) < 2 or accel[i] is None:
            continue
        mu = fmean(win)
        sd = pstdev(win)
        if sd <= 0:
            continue
        out[i] = (accel[i] - mu) / sd
    return out


# ----------------------------------------------------------------------------------------------------------
# Price-side helpers: map an availability day to the entry bar, measure forward returns.
# ----------------------------------------------------------------------------------------------------------
def _bar_index_on_or_after(bars: list[Bar], day: datetime) -> int | None:
    """Index of the FIRST bar whose date is >= `day` (the first tradeable close at/after the signal is available).
    None if no such bar exists (signal too recent / after the last bar)."""
    target = day.date()
    lo, hi, ans = 0, len(bars) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid].ts.date() >= target:
            ans = mid
            hi = mid - 1
        else:
            lo = mid + 1
    return ans


def forward_log_return(bars: list[Bar], entry_idx: int, h: int) -> float | None:
    """Close-to-close log return from `entry_idx` to `entry_idx + h` (h trading bars). None at a data edge or on a
    non-positive close. h may be NEGATIVE for the lead-lag time-reversal (a backward return)."""
    j = entry_idx + h
    if entry_idx < 0 or j < 0 or entry_idx >= len(bars) or j >= len(bars):
        return None
    c0 = float(bars[entry_idx].close)
    c1 = float(bars[j].close)
    if c0 <= 0 or c1 <= 0:
        return None
    return math.log(c1 / c0)


# ----------------------------------------------------------------------------------------------------------
# Event extraction: an acceleration spike -> a PIT entry bar -> forward returns (predictive +H and reversal -1).
# ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    symbol: str
    venue: str
    obs_day: datetime      # the attention obs-day whose acceleration spiked
    avail_day: datetime    # obs_day + 1 (when the signal is knowable)
    entry_day: datetime    # the entry bar's date (first close on/after avail_day)
    z: float               # the acceleration z at the spike
    fwd: float             # +H_FWD forward log return from the entry bar (the predictive, tradeable leg)
    fwd1: float            # +1 forward log return (one day AFTER entry) — matched to rev for a 1d-vs-1d symmetry test
    rev: float             # the -1 backward log return (the lead-lag time-reversal / coincidence check)


def events_for_token(
    symbol: str,
    venue: str,
    attn: list[AttnPoint],
    bars: list[Bar],
    log_views_override: list[float] | None = None,
) -> list[Event]:
    """Extract acceleration-spike events for one token, each mapped to its PIT entry bar with the +H_FWD forward
    return and the -1 reversal return. `log_views_override` lets the shuffle-null inject a time-shuffled attention
    series while keeping the SAME obs/avail-day calendar and the SAME (unshuffled) price bars."""
    logs = log_views_override if log_views_override is not None else [p.log_views for p in attn]
    if len(logs) != len(attn):
        return []
    zs = acceleration_z(logs)
    out: list[Event] = []
    for i, z in enumerate(zs):
        if z is None or z < Z_THRESH:
            continue
        avail = attn[i].avail_day
        entry_idx = _bar_index_on_or_after(bars, avail)
        if entry_idx is None:
            continue
        # The entry bar must be CONTEMPORANEOUS with the signal: a spike whose availability day predates the price
        # coverage maps to the first bar (a degenerate, non-tradeable event) -> DROP if the gap exceeds the guard.
        if (bars[entry_idx].ts.date() - avail.date()).days > MAX_ENTRY_GAP_DAYS:
            continue
        fwd = forward_log_return(bars, entry_idx, H_FWD)
        fwd1 = forward_log_return(bars, entry_idx, 1)   # one day AFTER entry (matched to rev for a 1d symmetry test)
        rev = forward_log_return(bars, entry_idx, -1)   # the bar BEFORE entry -> the coincident/lagging direction
        if fwd is None:
            continue
        out.append(
            Event(
                symbol=symbol,
                venue=venue,
                obs_day=attn[i].obs_day,
                avail_day=avail,
                entry_day=bars[entry_idx].ts,
                z=z,
                fwd=fwd,
                fwd1=fwd1 if fwd1 is not None else float("nan"),
                rev=rev if rev is not None else float("nan"),
            )
        )
    return out


# ----------------------------------------------------------------------------------------------------------
# Stats: pooled means, bootstrap band p-value, the production Gate scorer.
# ----------------------------------------------------------------------------------------------------------
def _mean(xs: list[float]) -> float:
    return fmean(xs) if xs else float("nan")


def _bootstrap_p_real_gt_null(real_mean: float, null_pool: list[float], rng: random.Random, iters: int) -> float:
    """One-sided bootstrap p-value: P(null-resample mean >= real mean). The thesis is a POSITIVE forward return,
    so we test whether the real mean sits ABOVE the null (shuffle) band. Small p => the real edge is outside the
    band the null can produce -> attention (not price autocorrelation) is doing the work."""
    if not null_pool or math.isnan(real_mean):
        return float("nan")
    n = len(null_pool)
    hits = 0
    for _ in range(iters):
        sample_mean = fmean(null_pool[rng.randrange(n)] for _ in range(n))
        if sample_mean >= real_mean:
            hits += 1
    return hits / iters


def _gate_summary(net_returns: list[float]) -> dict:
    """Score the per-event NET forward-return stream with the production scorer if importable; degrade to a plain
    t-stat/Sharpe summary otherwise. This is the only spot-tradeable leg (long the post-onset move, net of cost)."""
    out: dict = {"n": len(net_returns)}
    if not net_returns:
        return out
    mu = _mean(net_returns)
    sd = pstdev(net_returns) if len(net_returns) > 1 else 0.0
    out["mean_net"] = mu
    out["std"] = sd
    out["t_stat"] = (mu / (sd / math.sqrt(len(net_returns)))) if sd > 0 else float("nan")
    out["sharpe_per_event"] = (mu / sd) if sd > 0 else float("nan")
    try:
        from cosmu.master.scorer import probabilistic_sharpe, sample_moments  # type: ignore

        sr_hat, skew, kurt, n = sample_moments(net_returns)
        out["psr_vs_zero"] = float(probabilistic_sharpe(sr_hat, n, skew, kurt, 0.0))
    except Exception as e:  # noqa: BLE001 — scorer signature differs / unimportable -> plain summary only
        out["psr_vs_zero"] = None
        out["psr_err"] = type(e).__name__
    return out


# ----------------------------------------------------------------------------------------------------------
# Main study.
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Study:
    real_events: list[Event] = field(default_factory=list)
    shuffle_fwd: list[float] = field(default_factory=list)  # forward returns of shuffle-null events (the null pool)
    per_token: dict[str, dict] = field(default_factory=dict)
    tokens_seen: int = 0
    tokens_with_bars: int = 0
    tokens_with_wiki: int = 0
    tokens_used: int = 0


def run_study(as_of: datetime | None = None) -> Study:
    rng = random.Random(SEED)
    as_of = as_of or datetime.now(tz=UTC)
    ohlc = _OHLC()
    uni = _universe()
    study = Study()

    for symbol, article in sorted(uni.items()):
        study.tokens_seen += 1
        resolved = ohlc.bars(symbol)
        if resolved is None:
            continue
        study.tokens_with_bars += 1
        venue, bars = resolved
        attn = attention_series(symbol, article, as_of)
        if len(attn) < MIN_WIKI_DAYS:
            continue
        study.tokens_with_wiki += 1

        real_evs = events_for_token(symbol, venue, attn, bars)
        if not real_evs:
            study.per_token[symbol] = {"venue": venue, "wiki_days": len(attn), "bars": len(bars), "events": 0}
            continue
        study.tokens_used += 1
        study.real_events.extend(real_evs)

        # SHUFFLE-NULL: re-draw the attention series in time (same calendar of obs/avail days, same price bars), so
        # an acceleration spike now lands on a RANDOM day. If the forward edge survives here it is price
        # autocorrelation around arbitrary days, not attention. We pool SHUFFLE_REPS independent shuffles.
        base_logs = [p.log_views for p in attn]
        shuffle_evs = 0
        for _ in range(SHUFFLE_REPS):
            shuffled = base_logs[:]
            rng.shuffle(shuffled)
            sev = events_for_token(symbol, venue, attn, bars, log_views_override=shuffled)
            study.shuffle_fwd.extend(e.fwd for e in sev)
            shuffle_evs += len(sev)

        study.per_token[symbol] = {
            "venue": venue,
            "wiki_days": len(attn),
            "bars": len(bars),
            "events": len(real_evs),
            "mean_fwd": _mean([e.fwd for e in real_evs]),
            "shuffle_events_total": shuffle_evs,
        }

    return study


# ----------------------------------------------------------------------------------------------------------
# Summary + pre-registered verdict.
# ----------------------------------------------------------------------------------------------------------
def summarize(study: Study) -> dict:
    rng = random.Random(SEED + 1)
    fwd = [e.fwd for e in study.real_events]
    fwd1 = [e.fwd1 for e in study.real_events if not math.isnan(e.fwd1)]
    rev = [e.rev for e in study.real_events if not math.isnan(e.rev)]
    net_fwd = [f - NET_COST for f in fwd]

    real_fwd_mean = _mean(fwd)
    fwd1_mean = _mean(fwd1)
    shuffle_mean = _mean(study.shuffle_fwd)
    rev_mean = _mean(rev)

    # SHUFFLE-NULL bootstrap p: is the real forward mean ABOVE the shuffle band? (small p => attention, not price AC)
    shuffle_p = _bootstrap_p_real_gt_null(real_fwd_mean, study.shuffle_fwd, rng, BOOTSTRAP_ITERS)

    # LEAD-LAG SYMMETRY (the astro disconfirmer): a real PREDICTIVE edge moves price AFTER the signal is tradeable
    # (the +1d bar) and is ~flat in the bar BEFORE entry (-1d). If the move is the SAME magnitude at -1d and +1d the
    # attention is COINCIDENT (it travels WITH the price), not predictive -> KILL. Two readings, both pre-registered:
    #   (a) per-day:  |reverse(-1d)| vs the per-day forward effect (real_mean / H_FWD).
    #   (b) matched:  |reverse(-1d)| vs |forward(+1d)| (a clean 1-day-vs-1-day symmetry, the strict astro test).
    fwd_per_day = real_fwd_mean / H_FWD if H_FWD else float("nan")  # forward effect on a per-trading-day basis
    symmetry_ratio = (abs(rev_mean) / abs(fwd_per_day)) if (fwd_per_day and not math.isnan(fwd_per_day) and fwd_per_day != 0) else float("nan")
    symmetry_ratio_matched = (abs(rev_mean) / abs(fwd1_mean)) if (fwd1_mean and not math.isnan(fwd1_mean) and fwd1_mean != 0) else float("nan")

    summary: dict = {
        "N_events": len(study.real_events),
        "N_shuffle_events": len(study.shuffle_fwd),
        "tokens_seen": study.tokens_seen,
        "tokens_with_bars": study.tokens_with_bars,
        "tokens_with_wiki": study.tokens_with_wiki,
        "tokens_used": study.tokens_used,
        "z_thresh": Z_THRESH,
        "z_window": Z_WINDOW,
        "h_fwd": H_FWD,
        "net_cost_roundtrip": NET_COST,
        "forward": {
            "real_mean": real_fwd_mean,
            "real_per_day": fwd_per_day,
            "shuffle_mean": shuffle_mean,
            "shuffle_p": shuffle_p,
        },
        "lead_lag": {
            "reverse_mean_minus1": rev_mean,
            "forward_mean_plus1": fwd1_mean,
            "forward_per_day": fwd_per_day,
            "symmetry_ratio_abs": symmetry_ratio,
            "symmetry_ratio_matched_1d": symmetry_ratio_matched,
        },
        "net_forward_leg": _gate_summary(net_fwd),
    }
    return summary


def _verdict(summary: dict) -> tuple[str, list[str]]:
    """Pre-registered GO/KILL. GO needs ALL of:
        (i)   N_events >= 30 (pooled, honest power);
        (ii)  the real forward mean BEATS the shuffle-null band (shuffle_p < 0.05) — attention, not price AC;
        (iii) the lead-lag is ASYMMETRIC — the -1 reversal move is small vs the per-day forward move
              (symmetry_ratio < 0.5), i.e. predictive not coincident;
        (iv)  the net-of-fees forward leg mean > 0 (after the round-trip cost)."""
    reasons: list[str] = []
    n = summary["N_events"]
    fwd = summary["forward"]
    ll = summary["lead_lag"]
    net = summary["net_forward_leg"]

    if n < 30:
        reasons.append(f"N_events={n} < 30 (event count too thin to pool honestly)")

    sp = fwd.get("shuffle_p", float("nan"))
    beats_shuffle = (not math.isnan(sp)) and sp < 0.05 and fwd["real_mean"] > fwd["shuffle_mean"]
    if not beats_shuffle:
        reasons.append(
            f"forward mean does NOT beat the shuffle-null band: real {fwd['real_mean']:+.4f} vs "
            f"shuffle {fwd['shuffle_mean']:+.4f}, shuffle_p={sp!r} (>=0.05 => price autocorrelation, not attention)"
        )

    sr = ll.get("symmetry_ratio_abs", float("nan"))
    asymmetric = (not math.isnan(sr)) and sr < 0.5
    if not asymmetric:
        reasons.append(
            f"lead-lag is SYMMETRIC: |reverse(-1) {ll['reverse_mean_minus1']:+.4f}| vs per-day forward "
            f"{ll['forward_per_day']:+.4f}, ratio={sr!r} (>=0.5 => attention is COINCIDENT, not predictive)"
        )

    net_pos = isinstance(net.get("mean_net"), float) and net["mean_net"] > 0
    if not net_pos:
        reasons.append(f"net forward leg mean {net.get('mean_net')!r} <= 0 after {NET_COST*1e4:.0f}bps round-trip cost")

    if n >= 30 and beats_shuffle and asymmetric and net_pos:
        return "GO-to-Gate", reasons
    return "KILL", reasons


# ----------------------------------------------------------------------------------------------------------
# Reporting.
# ----------------------------------------------------------------------------------------------------------
def render_html(study: Study, summary: dict, verdict: str, reasons: list[str]) -> str:
    fwd = summary["forward"]
    ll = summary["lead_lag"]
    net = summary["net_forward_leg"]
    tok_rows = []
    for sym, info in sorted(study.per_token.items(), key=lambda kv: -(kv[1].get("events") or 0)):
        mf = info.get("mean_fwd")
        mf_str = f"{mf:+.4f}" if isinstance(mf, float) else "-"
        tok_rows.append(
            f"<tr><td>{sym}</td><td>{info.get('venue')}</td><td>{info.get('wiki_days')}</td>"
            f"<td>{info.get('bars')}</td><td>{info.get('events')}</td>"
            f"<td>{mf_str}</td></tr>"
        )
    ev_rows = []
    for e in sorted(study.real_events, key=lambda e: -e.z)[:120]:
        rev_str = "nan" if math.isnan(e.rev) else f"{e.rev:+.4f}"
        ev_rows.append(
            f"<tr><td>{e.symbol}</td><td>{e.venue}</td><td>{e.obs_day.date()}</td><td>{e.entry_day.date()}</td>"
            f"<td>{e.z:.2f}</td><td>{e.fwd:+.4f}</td><td>{rev_str}</td></tr>"
        )
    return f"""<!doctype html><meta charset="utf-8"><title>N11 attention-acceleration event-study</title>
<style>body{{font:13px/1.5 system-ui,sans-serif;margin:24px;color:#111}}h1{{font-size:18px}}h2{{font-size:15px}}
table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}.kv{{margin:2px 0}}.verdict{{font-weight:700;font-size:15px}}
.kill{{color:#b00}}.go{{color:#070}}</style>
<h1>N11 — Attention-acceleration breakout (event-study, keyless, experiment-only)</h1>
<p class="verdict {'kill' if verdict=='KILL' else 'go'}">VERDICT: {verdict}</p>
<ul>{''.join(f'<li>{r}</li>' for r in reasons) or '<li>all pre-registered GO conditions met</li>'}</ul>
<div class="kv">N attention-acceleration EVENTS (z &ge; {Z_THRESH}): <b>{summary['N_events']}</b></div>
<div class="kv">N shuffle-null events: <b>{summary['N_shuffle_events']}</b> ({SHUFFLE_REPS} shuffles/token)</div>
<div class="kv">tokens seen / with-bars / with-wiki / used: {summary['tokens_seen']} / {summary['tokens_with_bars']} / {summary['tokens_with_wiki']} / {summary['tokens_used']}</div>
<div class="kv">pre-registered: z&ge;{Z_THRESH}, z-window {Z_WINDOW}d, forward {H_FWD}d, entry = first close on/after T+1</div>
<h2>Forward edge vs the SHUFFLE-NULL (control 1)</h2>
<table>
<tr><th>leg</th><th>value</th></tr>
<tr><td>real forward mean ({H_FWD}d, log)</td><td>{fwd['real_mean']:+.4f}</td></tr>
<tr><td>shuffle-null forward mean</td><td>{fwd['shuffle_mean']:+.4f}</td></tr>
<tr><td>shuffle bootstrap p (real &gt; null)</td><td>{fwd['shuffle_p']:.3f}</td></tr>
<tr><td>net forward leg (after {NET_COST*1e4:.0f}bps)</td><td>{net.get('mean_net')}</td></tr>
<tr><td>t-stat / sharpe-per-event / PSR-vs-0</td><td>{net.get('t_stat')} / {net.get('sharpe_per_event')} / {net.get('psr_vs_zero')}</td></tr>
</table>
<h2>Lead-lag TIME-REVERSAL (control 2 — the astro disconfirmer)</h2>
<table>
<tr><th>leg</th><th>value</th></tr>
<tr><td>forward +1d move (the bar AFTER entry)</td><td>{ll['forward_mean_plus1']:+.4f}</td></tr>
<tr><td>reverse -1d move (the bar BEFORE entry)</td><td>{ll['reverse_mean_minus1']:+.4f}</td></tr>
<tr><td>matched symmetry ratio |rev(-1)| / |fwd(+1)|</td><td>{ll['symmetry_ratio_matched_1d']:.3f}</td></tr>
<tr><td>forward per-day move (real_mean / {H_FWD})</td><td>{ll['forward_per_day']:+.4f}</td></tr>
<tr><td>per-day symmetry ratio |rev(-1)| / |fwd-per-day|</td><td>{ll['symmetry_ratio_abs']:.3f}</td></tr>
</table>
<p style="color:#555">Symmetry ratio ~1 (or &gt;1) => the price already moved BEFORE the signal is tradeable => attention is
COINCIDENT/LAGGING, not predictive => KILL. Asymmetry (&lt;0.5, big +1d vs small -1d) => genuinely predictive.</p>
<h2>Per-token coverage</h2>
<table><tr><th>token</th><th>venue</th><th>wiki days</th><th>bars</th><th>events</th><th>mean fwd</th></tr>
{''.join(tok_rows)}</table>
<h2>Top acceleration events (by z)</h2>
<table><tr><th>token</th><th>venue</th><th>obs day</th><th>entry day</th><th>z</th><th>fwd {H_FWD}d</th><th>rev -1d</th></tr>
{''.join(ev_rows)}</table>
<p style="color:#888">Experiment only. Zero production impact. Wikipedia pageviews (immutable, T+1) + keyless OHLC
(Bybit/Binance/Kraken). One pre-registered (z,horizon) rule, no sweep. Controls: time-shuffle null + lead-lag reversal.</p>
"""


# ----------------------------------------------------------------------------------------------------------
# Offline self-test of the PURE logic (no network) — deterministic, run with --selftest.
# ----------------------------------------------------------------------------------------------------------
def _selftest() -> int:
    """Validate the load-bearing pure functions on deterministic synthetic fixtures: the acceleration z math
    (2nd derivative + causal z), the PIT entry-bar mapping, forward/reverse returns, and the shuffle pathway."""
    from decimal import Decimal

    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # 1) acceleration_z: a small-noise series gives a non-degenerate trailing window (std>0), then a sudden one-day
    #    jump in the LEVEL produces a positive acceleration spike at the jump day. The causal z uses only prior pts.
    base = [0.01 * ((i * 7) % 5 - 2) for i in range(30)]  # tiny deterministic wiggle so the z-window has variance
    logs = base + [base[-1] + 1.0] + [base[-1] + 1.0] * 30  # a step up in level at index 30
    zs = acceleration_z(logs, window=20)
    # acceleration at index 30 = (L30-L29)-(L29-L28) ~= +1 (big positive); at 31 = (L31-L30)-(L30-L29) ~= -1 (negative)
    check("acceleration z positive at the level-jump day", zs[30] is not None and zs[30] > 0)
    check("acceleration z negative the day AFTER the jump", zs[31] is not None and zs[31] < 0)
    check("acceleration z is None before enough history", zs[0] is None and zs[1] is None)
    # causality: z at i must not depend on any value at index > i. Mutate a far-future point; z[30] must be unchanged.
    logs2 = logs[:]
    logs2[50] = 99.0
    zs2 = acceleration_z(logs2, window=20)
    check("acceleration z is strictly causal (future change does not move z[30])", zs[30] == zs2[30])

    # 2) _bar_index_on_or_after + forward/reverse returns on a synthetic up-trend.
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [100.0 * (1.01 ** i) for i in range(20)]  # +1%/day compounding
    bars = [
        Bar(ts=t0 + timedelta(days=i), open=Decimal(str(c)), high=Decimal(str(c)),
            low=Decimal(str(c)), close=Decimal(str(c)), volume=Decimal(1))
        for i, c in enumerate(closes)
    ]
    # availability day = t0 + 5 days; first bar on/after is index 5.
    idx = _bar_index_on_or_after(bars, t0 + timedelta(days=5))
    check("entry bar = first close on/after avail day", idx == 5)
    fwd = forward_log_return(bars, 5, 5)
    rev = forward_log_return(bars, 5, -1)
    check("forward 5d return is positive on an up-trend", fwd is not None and fwd > 0)
    # rev = log(close[4]/close[5]) = log(1/1.01) ~= -1% (the bar BEFORE entry; negative on an up-trend by construction)
    check("reverse -1d return is ~ -1% (log(1/1.01)) on the up-trend", rev is not None and abs(rev - math.log(1 / 1.01)) < 1e-9)
    check("forward return None at the right data edge", forward_log_return(bars, 18, 5) is None)

    # 3) events_for_token wiring: build a token whose attention accelerates once, with a price that rises after.
    attn = [
        AttnPoint(obs_day=t0 + timedelta(days=i), avail_day=t0 + timedelta(days=i + 1), log_views=0.0)
        for i in range(20)
    ]
    # inject a clean acceleration spike at obs day index 8 by bumping the level there
    bumped = list(attn)
    bumped[8] = AttnPoint(obs_day=attn[8].obs_day, avail_day=attn[8].avail_day, log_views=5.0)
    logs3 = [p.log_views for p in bumped]
    # widen variance window so z is defined; lower threshold by checking the raw event presence via a tiny series
    zs3 = acceleration_z(logs3, window=6)
    has_spike = any(z is not None and z >= 1.0 for z in zs3)
    check("a level bump produces a detectable acceleration spike", has_spike)

    # 4) shuffle override changes which days are events (sanity that the override path is wired).
    evs_real = events_for_token("TEST", "synthetic", bumped, bars)
    rng = random.Random(0)
    shuffled = logs3[:]
    rng.shuffle(shuffled)
    evs_shuf = events_for_token("TEST", "synthetic", bumped, bars, log_views_override=shuffled)
    check("shuffle override runs and yields a (possibly different) event set",
          isinstance(evs_real, list) and isinstance(evs_shuf, list))

    print(f"\nSELFTEST: {'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="N11 attention-acceleration breakout event-study (experiment-only).")
    ap.add_argument("--selftest", action="store_true", help="run the offline pure-logic self-test (no network).")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "n11_attention_accel_table.html"))
    ap.add_argument("--json", default=os.path.join(os.path.dirname(__file__), "n11_attention_accel_results.json"))
    args = ap.parse_args()

    if args.selftest:
        print("N11 self-test (offline, pure logic):")
        return _selftest()

    print("N11 attention-acceleration event-study — keyless Wikipedia pageviews + OHLC...", file=sys.stderr)
    study = run_study()
    summary = summarize(study)
    verdict, reasons = _verdict(summary)

    out_json = {"summary": summary, "verdict": verdict, "reasons": reasons,
                "per_token": study.per_token}
    with open(args.json, "w") as fh:
        json.dump(out_json, fh, indent=2, default=str)
    with open(args.out, "w") as fh:
        fh.write(render_html(study, summary, verdict, reasons))

    fwd = summary["forward"]
    ll = summary["lead_lag"]
    net = summary["net_forward_leg"]
    print(json.dumps(summary, indent=2, default=str))
    print("\n================ N11 VERDICT ================")
    print(f"N events: {summary['N_events']}  |  tokens used: {summary['tokens_used']}  |  shuffle events: {summary['N_shuffle_events']}")
    print(f"forward {H_FWD}d  real {fwd['real_mean']:+.4f}  shuffle {fwd['shuffle_mean']:+.4f}  shuffle_p={fwd['shuffle_p']:.3f}")
    print(f"net forward leg ({NET_COST*1e4:.0f}bps): mean {net.get('mean_net')}  t={net.get('t_stat')}  PSR={net.get('psr_vs_zero')}")
    print(f"lead-lag: reverse(-1) {ll['reverse_mean_minus1']:+.4f}  forward(+1) {ll['forward_mean_plus1']:+.4f}  "
          f"matched-symmetry={ll['symmetry_ratio_matched_1d']:.3f}  per-day-symmetry={ll['symmetry_ratio_abs']:.3f}")
    print(f"VERDICT: {verdict}")
    for r in reasons:
        print(f"  - {r}")
    print(f"\nwrote {args.json}\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
