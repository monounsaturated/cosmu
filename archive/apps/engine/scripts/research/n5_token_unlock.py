# intent: N5 — TOKEN-UNLOCK SUPPLY-SHOCK DRIFT event-study (EXPERIMENT ONLY, offline-ish keyless). Zero prod
# impact. docs-only, persists NOTHING to prod, no Gate constant touched, no cron.
#
# THESIS (slate v2, #2 after N1 killed): large SCHEDULED vesting unlocks are a pre-announced, DATED supply shock.
# The cliff date is fixed at TGE and public months ahead, yet small/mid-cap tokens are claimed to drift DOWN INTO
# a large unlock (sellers front-run the new supply) and RELIEVE after (overhang cleared). Retail holds through the
# cliff; informed flow positions early. Classic forced-flow with a fixed, LEAK-PROOF PIT date.
#
# WHY LEAK-PROOF (the whole moat-fit): the unlock schedule is set at token genesis, so `available_at` of the event
# is YEARS before the event. There is no revising-source risk, no answer-key leakage. The ONLY way to fool
# ourselves is a spurious drift that is just the tokens' own beta/vol — which is EXACTLY what the placebo-date null
# is built to catch.
#
# DATA (keyless, free — confirmed reachable from the M2):
#   - DefiLlama datasets host (NOT api.llama.fi/emissions, which now 402s):
#       https://defillama-datasets.llama.fi/emissionsProtocolsList        -> the list of protocols w/ unlock data
#       https://defillama-datasets.llama.fi/emissions/{slug}              -> per-protocol unlock schedule:
#           .metadata.unlockEvents[]  : grouped-by-date cliff/linear allocations (the discrete cliff EVENTS)
#           .documentedData.data[]    : per-category CUMULATIVE unlocked token series (daily) -> the circulating
#                                       denominator (total tokens unlocked-to-date) for the % -of-float magnitude
#           .gecko_id                 : the CoinGecko id, mapped to a ticker symbol
#   - CoinGecko keyless coins/list   : gecko_id -> SYMBOL (APT, ENA, ARB, ...)
#   - Keyless OHLC (cosmu.data.market): Bybit -> Binance -> Kraken spot daily bars (first that has the pair).
#
# MAGNITUDE (the bucket variable, pre-registered): unlock_pct = cliff_tokens / circulating_just_before, where
# circulating_just_before = total cumulative-unlocked tokens at the day BEFORE the cliff (from documentedData).
# This is "% of the float about to be hit by new supply". Larger shock -> larger expected drift (the thesis).
#
# EVENT-STUDY (ONE pre-registered rule, NO sweep):
#   - LARGE unlock  := unlock_pct >= LARGE_PCT  (pre-registered 5% of circulating float).
#   - Window        := close-to-close trading-day returns at h = -H..+H around the cliff DAY (H = 5).
#   - Drift metrics : pre = ret[-H -> 0], post = ret[0 -> +H], full = ret[-H -> +H]; all log-summed daily returns.
#   - Net of fees   : a conservative round-trip spot cost (taker fee + slippage) on the traded leg.
#   - Thesis sign   : pre-drift < 0 (sellers front-run down) and/or post-drift > 0 (relief). We report the sign,
#                     do NOT assume it.
#
# DECISIVE CONTROL — PLACEBO-DATE NULL: for each real LARGE-unlock token, draw K random PLACEBO dates on the SAME
# token, each at least PLACEBO_GAP_DAYS from ANY real unlock of that token, and run the IDENTICAL window math. If
# the "edge" shows up on placebo dates too, it is just the token's beta/vol -> KILL. The real drift must beat the
# placebo band (bootstrap p-value) to survive.
#
# GATE STATS: per-event net drift stream scored with the REAL cosmu.master.scorer (DSR / min-trades) — the SAME
# production scorer, nothing re-implemented — so the pooled verdict speaks the Gate's language.
#
# Run:
#   python3 apps/engine/scripts/research/n5_token_unlock.py [--max-protocols N] [--out report.html] [--json out.json]
#
# ZERO production impact: read-only keyless fetches; writes a disposable HTML table + a JSON summary under
# scripts/research/. No DB, no prod source, no Gate constant.

from __future__ import annotations

import argparse
import json
import math
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import fmean, pstdev

# Make `cosmu` importable regardless of cwd (same plumbing as the sibling n1/h9 harnesses; the ONLY prod touch is
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

# ----------------------------------------------------------------------------------------------------------
# Keyless hosts.
# ----------------------------------------------------------------------------------------------------------
DATASETS = "https://defillama-datasets.llama.fi"
PROTO_LIST_URL = f"{DATASETS}/emissionsProtocolsList"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"

# ----------------------------------------------------------------------------------------------------------
# PRE-REGISTERED constants (ONE config, declared up front, BEFORE any result is seen — NO sweep).
# ----------------------------------------------------------------------------------------------------------
H = 5                      # event window half-width in TRADING days: h = -5 .. +5 around the cliff day.
LARGE_PCT = 0.05           # "large" unlock := cliff is >= 5% of circulating float (slate pre-registered).
PLACEBO_PER_EVENT = 3      # placebo dates drawn per real large-unlock event (matched, same token).
PLACEBO_GAP_DAYS = 30      # a placebo date must be >= this many days from ANY real unlock of the same token.
ROUNDTRIP_FEE_BPS = 20.0   # conservative spot round-trip taker fee (~2 x 10 bps) on the traded leg.
ROUNDTRIP_SLIP_BPS = 30.0  # conservative round-trip slippage for a small-cap (illiquid) entry+exit.
MIN_HISTORY_BARS = 60      # a token must have >= this many daily bars to be eligible at all.
SEED = 20260627            # deterministic placebo draws + bootstrap.

NET_COST = (ROUNDTRIP_FEE_BPS + ROUNDTRIP_SLIP_BPS) / 1e4  # total round-trip fractional cost on the traded leg.

# Symbols that are NOT spot-tradeable small/mid caps for this study (stablecoins, the majors used as quote, etc.).
_SKIP_SYMBOLS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "BUSD", "USDE", "WBTC", "WETH", "STETH"}


# ----------------------------------------------------------------------------------------------------------
# Keyless fetch (certifi-backed SSL — the M2 needs it for these hosts).
# ----------------------------------------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def _fetch_json(url: str, *, retries: int = 3, timeout: int = 60) -> object:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cosmu-research)"})
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):  # not-found / bad params -> caller treats as empty, never retry
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — network/timeout -> backoff retry
            last = e
        time.sleep(0.6 * (attempt + 1))
    if last:
        raise last
    return None


# ----------------------------------------------------------------------------------------------------------
# Symbol resolution: DefiLlama gecko_id -> CoinGecko symbol -> keyless OHLC.
# ----------------------------------------------------------------------------------------------------------
def load_gecko_symbol_index() -> dict[str, str]:
    """gecko_id -> UPPERCASE ticker symbol, from the keyless CoinGecko coins/list."""
    try:
        rows = _fetch_json(COINGECKO_LIST_URL, timeout=90)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] coingecko coins/list failed ({type(e).__name__}); symbol resolution degraded", file=sys.stderr)
        return {}
    if not isinstance(rows, list):
        return {}
    idx: dict[str, str] = {}
    for c in rows:
        if isinstance(c, dict) and c.get("id") and c.get("symbol"):
            idx[str(c["id"])] = str(c["symbol"]).upper()
    return idx


class _OHLC:
    """Keyless OHLC resolver: try Bybit (deepest alt coverage) -> Binance -> Kraken; the first venue that returns
    >= MIN_HISTORY_BARS daily bars for SYMBOLUSDT wins. Per-symbol memo so each token is fetched once."""

    def __init__(self) -> None:
        import tempfile

        td = tempfile.mkdtemp(prefix="n5_ohlc_")
        self._providers = [
            ("bybit", BybitSpotOHLCVProvider(cache_dir=os.path.join(td, "bybit"))),
            ("binance", BinanceSpotOHLCVProvider(cache_dir=os.path.join(td, "binance"))),
            ("kraken", KrakenSpotOHLCVProvider(cache_dir=os.path.join(td, "kraken"))),
        ]
        self._memo: dict[str, tuple[str, list[Bar]] | None] = {}

    def bars(self, symbol: str) -> tuple[str, list[Bar]] | None:
        if symbol in self._memo:
            return self._memo[symbol]
        pair = f"{symbol}USDT"
        out: tuple[str, list[Bar]] | None = None
        for venue, prov in self._providers:
            try:
                bars = prov.fetch_bars(pair, "1d", limit=4000)
            except Exception:  # noqa: BLE001 — venue offline/refused -> try the next
                bars = []
            if len(bars) >= MIN_HISTORY_BARS:
                out = (venue, bars)
                break
        self._memo[symbol] = out
        return out


# ----------------------------------------------------------------------------------------------------------
# Unlock-event extraction from a DefiLlama emissions payload.
# ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class UnlockEvent:
    protocol: str
    symbol: str
    venue: str
    ts: datetime              # the cliff DAY (UTC midnight)
    cliff_tokens: float       # total cliff tokens unlocked on this date (summed across recipients)
    circulating_before: float # cumulative tokens unlocked up to the day BEFORE the cliff (the denominator)
    unlock_pct: float         # cliff_tokens / circulating_before — the % -of-float magnitude


def _total_unlocked_series(payload: dict) -> list[tuple[int, float]]:
    """Build the daily CUMULATIVE total-unlocked token series (summed across all documentedData categories).
    Returns ascending (unix_ts, total_unlocked). The series is cumulative/monotone by construction."""
    dd = payload.get("documentedData", {})
    cats = dd.get("data", []) if isinstance(dd, dict) else []
    totals: dict[int, float] = {}
    for cat in cats:
        for pt in cat.get("data", []):
            ts = pt.get("timestamp")
            unlocked = pt.get("unlocked")
            if ts is None or unlocked is None:
                continue
            try:
                totals[int(ts)] = totals.get(int(ts), 0.0) + float(unlocked)
            except (ValueError, TypeError):
                continue
    return sorted(totals.items())


def _circulating_before(series: list[tuple[int, float]], event_ts: int) -> float | None:
    """Total cumulative tokens unlocked at the latest documentedData point STRICTLY before `event_ts` — the
    circulating-float denominator just ahead of the cliff. None if no prior point (the genesis event)."""
    prior = [v for (t, v) in series if t < event_ts]
    if not prior:
        return None
    last = prior[-1]
    return last if last > 0 else None


def extract_events(payload: dict, symbol: str, venue: str) -> list[UnlockEvent]:
    """Extract discrete CLIFF unlock events from a DefiLlama emissions payload, each tagged with its % -of-float
    magnitude. Linear-only dates (no cliff allocation) are skipped (a slow drip is not the shock the thesis is
    about). The genesis cliff (no prior circulating) is skipped (no denominator)."""
    md = payload.get("metadata", {})
    unlock_events = md.get("unlockEvents", []) if isinstance(md, dict) else []
    series = _total_unlocked_series(payload)
    name = str(payload.get("name") or "?")
    out: list[UnlockEvent] = []
    for ev in unlock_events:
        ts = ev.get("timestamp")
        if ts is None:
            continue
        cliffs = ev.get("cliffAllocations", []) or []
        cliff_tokens = 0.0
        for a in cliffs:
            if a.get("unlockType") == "cliff":
                try:
                    cliff_tokens += float(a.get("amount", 0) or 0)
                except (ValueError, TypeError):
                    continue
        if cliff_tokens <= 0:
            continue  # linear-only date — not the discrete shock
        circ = _circulating_before(series, int(ts))
        if circ is None:
            continue  # genesis / no prior float -> no honest denominator
        pct = cliff_tokens / circ
        out.append(
            UnlockEvent(
                protocol=name,
                symbol=symbol,
                venue=venue,
                ts=datetime.fromtimestamp(int(ts), tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0),
                cliff_tokens=cliff_tokens,
                circulating_before=circ,
                unlock_pct=pct,
            )
        )
    return out


# ----------------------------------------------------------------------------------------------------------
# Event-study window math on daily bars (close-to-close log returns).
# ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class WindowResult:
    pre: float    # log return from h=-H to h=0 (into the unlock)
    post: float   # log return from h=0 to h=+H (after the unlock)
    full: float   # log return from h=-H to h=+H
    daily: list[float]  # the 2H daily log returns across the window (for the placebo/bootstrap)


def _bar_index_for_day(bars: list[Bar], day: datetime) -> int | None:
    """Index of the bar whose date is the LAST one on-or-before `day` (the close the trader sees at the event
    day). None if the event is before the first bar or after the last + buffer."""
    target = day.date()
    lo, hi, ans = 0, len(bars) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid].ts.date() <= target:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def window_returns(bars: list[Bar], day: datetime, h: int = H) -> WindowResult | None:
    """Close-to-close log returns across [-h, +h] TRADING-bar steps around the bar at `day`. Requires h bars on
    each side to exist (else the event is too close to a data edge -> dropped, never padded)."""
    i0 = _bar_index_for_day(bars, day)
    if i0 is None or i0 - h < 0 or i0 + h >= len(bars):
        return None
    closes = [float(bars[i0 + k].close) for k in range(-h, h + 1)]  # length 2h+1, center is index h
    if any(c <= 0 for c in closes):
        return None
    logs = [math.log(closes[k + 1] / closes[k]) for k in range(len(closes) - 1)]  # 2h daily log returns
    pre = sum(logs[:h])           # -h -> 0
    post = sum(logs[h:])          # 0 -> +h
    full = sum(logs)              # -h -> +h
    return WindowResult(pre=pre, post=post, full=full, daily=logs)


# ----------------------------------------------------------------------------------------------------------
# Placebo-date null: random non-unlock dates on the SAME token, >= PLACEBO_GAP_DAYS from any real unlock.
# ----------------------------------------------------------------------------------------------------------
def placebo_dates(
    bars: list[Bar], real_unlock_days: list[datetime], n: int, rng: random.Random, h: int = H
) -> list[datetime]:
    """Draw up to `n` placebo event-dates from the token's own bar dates, each at least PLACEBO_GAP_DAYS from
    EVERY real unlock of the token AND with a full [-h,+h] window of bars available. Same-token so the placebo
    inherits the token's beta/vol — the whole point: if the drift survives here it is just that beta."""
    if len(bars) < 2 * h + 1:
        return []
    real_dates = {d.date() for d in real_unlock_days}
    candidates: list[datetime] = []
    for i in range(h, len(bars) - h):  # only bars with a full window
        bd = bars[i].ts
        if any(abs((bd - rd).days) < PLACEBO_GAP_DAYS for rd in real_unlock_days):
            continue
        if bd.date() in real_dates:
            continue
        candidates.append(bd)
    if not candidates:
        return []
    rng.shuffle(candidates)
    return candidates[:n]


# ----------------------------------------------------------------------------------------------------------
# Pooling + bootstrap test (real drift vs placebo band).
# ----------------------------------------------------------------------------------------------------------
def _mean(xs: list[float]) -> float:
    return fmean(xs) if xs else float("nan")


def _bootstrap_p_greater_abs(real_mean: float, placebo: list[float], rng: random.Random, iters: int = 5000) -> float:
    """One-sided bootstrap p-value: P(|placebo mean| >= |real mean|) under resampling the placebo pool. Small p
    => the real drift is OUTSIDE the placebo band (the token's own beta/vol cannot explain it). Two-sided on the
    magnitude because the thesis sign is read off, not assumed."""
    if not placebo or math.isnan(real_mean):
        return float("nan")
    n = len(placebo)
    target = abs(real_mean)
    hits = 0
    for _ in range(iters):
        sample = [placebo[rng.randrange(n)] for _ in range(n)]
        if abs(_mean(sample)) >= target:
            hits += 1
    return hits / iters


# ----------------------------------------------------------------------------------------------------------
# Gate scorer hook (the REAL production scorer on the net per-event stream).
# ----------------------------------------------------------------------------------------------------------
def _gate_summary(net_returns: list[float]) -> dict:
    """Score the per-event NET drift stream with the production scorer if importable; degrade to a plain
    t-stat/DSR-ish summary otherwise (the harness must run anywhere, even without the full engine deps). The net
    stream is the post-drift LONG-RELIEF leg net of round-trip cost (the only spot-tradeable leg per slate)."""
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

        # PSR (Bailey & López de Prado) on the per-event NET stream vs a zero benchmark — the SAME production
        # primitive the Gate's deflated-Sharpe is built on. Single pool (BRUT), so PSR here is the honest
        # P(true per-event Sharpe > 0); the full DSR would only DEFLATE this further for trial-count.
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
    events: list[UnlockEvent] = field(default_factory=list)
    large: list[tuple[UnlockEvent, WindowResult]] = field(default_factory=list)
    placebo: list[WindowResult] = field(default_factory=list)
    skipped_no_symbol: int = 0
    skipped_no_bars: int = 0
    protocols_seen: int = 0
    protocols_matched: int = 0


def run_study(max_protocols: int | None) -> Study:
    rng = random.Random(SEED)
    gecko_idx = load_gecko_symbol_index()
    ohlc = _OHLC()
    study = Study()

    try:
        protocols = _fetch_json(PROTO_LIST_URL)
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: emissionsProtocolsList fetch failed: {type(e).__name__} {e}", file=sys.stderr)
        return study
    if not isinstance(protocols, list):
        print("FATAL: emissionsProtocolsList shape unexpected", file=sys.stderr)
        return study
    if max_protocols:
        protocols = protocols[:max_protocols]

    # First pass: resolve every protocol -> events, keeping only those with a tradeable keyless symbol.
    per_token_events: dict[str, list[UnlockEvent]] = {}
    per_token_bars: dict[str, list[Bar]] = {}
    for slug in protocols:
        study.protocols_seen += 1
        try:
            payload = _fetch_json(f"{DATASETS}/emissions/{urllib.parse.quote(slug)}")
        except Exception:  # noqa: BLE001 — a single protocol 404/timeout -> skip, never abort the pass
            continue
        if not isinstance(payload, dict):
            continue
        gecko_id = payload.get("gecko_id")
        symbol = gecko_idx.get(str(gecko_id)) if gecko_id else None
        if not symbol or symbol in _SKIP_SYMBOLS:
            study.skipped_no_symbol += 1
            continue
        resolved = ohlc.bars(symbol)
        if resolved is None:
            study.skipped_no_bars += 1
            continue
        venue, bars = resolved
        evs = extract_events(payload, symbol, venue)
        if not evs:
            continue
        study.protocols_matched += 1
        per_token_events.setdefault(symbol, []).extend(evs)
        per_token_bars[symbol] = bars
        study.events.extend(evs)
        time.sleep(0.05)  # be gentle on the keyless host

    # Second pass: event-study the LARGE unlocks + matched placebo dates, per token.
    for symbol, evs in per_token_events.items():
        bars = per_token_bars[symbol]
        large_evs = [e for e in evs if e.unlock_pct >= LARGE_PCT]
        windows: list[tuple[UnlockEvent, WindowResult]] = []
        for e in large_evs:
            w = window_returns(bars, e.ts)
            if w is not None:
                windows.append((e, w))
        if not windows:
            continue
        study.large.extend(windows)
        # placebo: K per LARGE event that produced a usable window, on the same token, away from ANY real unlock.
        real_days = [e.ts for e in evs]
        n_placebo = PLACEBO_PER_EVENT * len(windows)
        for pd in placebo_dates(bars, real_days, n_placebo, rng):
            pw = window_returns(bars, pd)
            if pw is not None:
                study.placebo.append(pw)

    return study


# ----------------------------------------------------------------------------------------------------------
# Reporting.
# ----------------------------------------------------------------------------------------------------------
def summarize(study: Study) -> dict:
    rng = random.Random(SEED + 1)
    real_pre = [w.pre for (_e, w) in study.large]
    real_post = [w.post for (_e, w) in study.large]
    real_full = [w.full for (_e, w) in study.large]
    plac_pre = [w.pre for w in study.placebo]
    plac_post = [w.post for w in study.placebo]
    plac_full = [w.full for w in study.placebo]

    # NET tradeable leg: the slate says spot can only trade the post-cliff LONG RELIEF leg; net of round-trip cost.
    net_post = [w.post - NET_COST for (_e, w) in study.large]
    # The short-into leg (would need a perp venue) — reported gross only, for sign, never as the spot edge.
    short_into_gross = [-w.pre for (_e, w) in study.large]  # profit of shorting into the unlock = -(pre drift)

    summary: dict = {
        "N_total_events": len(study.events),
        "N_large_events": len(study.large),
        "N_placebo": len(study.placebo),
        "protocols_seen": study.protocols_seen,
        "protocols_matched": study.protocols_matched,
        "skipped_no_symbol": study.skipped_no_symbol,
        "skipped_no_bars": study.skipped_no_bars,
        "large_pct_threshold": LARGE_PCT,
        "window_half_width_days": H,
        "net_cost_roundtrip": NET_COST,
        "drift": {
            "pre_mean": _mean(real_pre),
            "post_mean": _mean(real_post),
            "full_mean": _mean(real_full),
            "pre_mean_placebo": _mean(plac_pre),
            "post_mean_placebo": _mean(plac_post),
            "full_mean_placebo": _mean(plac_full),
        },
        "placebo_p": {
            "pre": _bootstrap_p_greater_abs(_mean(real_pre), plac_pre, rng),
            "post": _bootstrap_p_greater_abs(_mean(real_post), plac_post, rng),
            "full": _bootstrap_p_greater_abs(_mean(real_full), plac_full, rng),
        },
        "net_post_relief_leg": _gate_summary(net_post),
        "short_into_gross_leg": {
            "mean": _mean(short_into_gross),
            "n": len(short_into_gross),
        },
    }
    # Magnitude monotonicity: split large events into the lower/upper half by unlock_pct and compare drift.
    if study.large:
        ranked = sorted(study.large, key=lambda ew: ew[0].unlock_pct)
        mid = len(ranked) // 2
        lo, hi = ranked[:mid], ranked[mid:]
        summary["magnitude_split"] = {
            "lower_half_pct_range": [ranked[0][0].unlock_pct, ranked[max(mid - 1, 0)][0].unlock_pct],
            "upper_half_pct_range": [ranked[mid][0].unlock_pct if mid < len(ranked) else None, ranked[-1][0].unlock_pct],
            "lower_pre_mean": _mean([w.pre for (_e, w) in lo]),
            "upper_pre_mean": _mean([w.pre for (_e, w) in hi]),
            "lower_post_mean": _mean([w.post for (_e, w) in lo]),
            "upper_post_mean": _mean([w.post for (_e, w) in hi]),
        }
    return summary


def _verdict(summary: dict) -> tuple[str, list[str]]:
    """Pre-registered GO/KILL: GO needs (i) N_large >= 30, (ii) a drift whose sign matches the thesis AND beats
    the placebo band (p < 0.05) on at least the spot-tradeable post-relief leg, (iii) net of fees still > 0."""
    reasons: list[str] = []
    n_large = summary["N_large_events"]
    drift = summary["drift"]
    pp = summary["placebo_p"]
    net = summary["net_post_relief_leg"]

    if n_large < 30:
        reasons.append(f"N_large={n_large} < 30 (event count too thin to pool honestly)")
    # Does the spot-tradeable post-relief leg beat placebo?
    post_beats = (not math.isnan(pp.get("post", float("nan")))) and pp["post"] < 0.05
    if not post_beats:
        reasons.append(
            f"post-drift placebo p={pp.get('post')!r} not < 0.05 "
            f"(real post {drift['post_mean']:+.4f} vs placebo {drift['post_mean_placebo']:+.4f} — inside the beta/vol band)"
        )
    net_pos = isinstance(net.get("mean_net"), float) and net["mean_net"] > 0
    if not net_pos:
        reasons.append(f"net post-relief leg mean {net.get('mean_net')!r} <= 0 after {NET_COST*1e4:.0f}bps round-trip cost")

    if n_large >= 30 and post_beats and net_pos:
        return "GO-to-Gate", reasons
    return "KILL", reasons


def render_html(study: Study, summary: dict, verdict: str, reasons: list[str]) -> str:
    d = summary["drift"]
    pp = summary["placebo_p"]
    rows = []
    for (e, w) in sorted(study.large, key=lambda ew: ew[0].unlock_pct, reverse=True)[:120]:
        rows.append(
            f"<tr><td>{e.symbol}</td><td>{e.venue}</td><td>{e.ts.date()}</td>"
            f"<td>{e.unlock_pct*100:.1f}%</td><td>{w.pre:+.3f}</td><td>{w.post:+.3f}</td><td>{w.full:+.3f}</td></tr>"
        )
    body = "\n".join(rows)
    return f"""<!doctype html><meta charset="utf-8"><title>N5 token-unlock event-study</title>
<style>body{{font:13px/1.5 system-ui,sans-serif;margin:24px;color:#111}}h1{{font-size:18px}}
table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}.kv{{margin:2px 0}}.verdict{{font-weight:700;font-size:15px}}
.kill{{color:#b00}}.go{{color:#070}}</style>
<h1>N5 — Token-unlock supply-shock drift (event-study, keyless, experiment-only)</h1>
<p class="verdict {'kill' if verdict=='KILL' else 'go'}">VERDICT: {verdict}</p>
<ul>{''.join(f'<li>{r}</li>' for r in reasons) or '<li>all pre-registered GO conditions met</li>'}</ul>
<div class="kv">N total cliff events (tradeable tokens): <b>{summary['N_total_events']}</b></div>
<div class="kv">N LARGE events (&ge;{LARGE_PCT*100:.0f}% of float, full window): <b>{summary['N_large_events']}</b></div>
<div class="kv">N placebo windows: <b>{summary['N_placebo']}</b></div>
<div class="kv">protocols seen / matched-to-OHLC: {summary['protocols_seen']} / {summary['protocols_matched']}</div>
<h2>Drift (mean log return) — real vs placebo</h2>
<table>
<tr><th>leg</th><th>real</th><th>placebo</th><th>placebo-p</th></tr>
<tr><td>pre (-{H}d&rarr;0, into unlock)</td><td>{d['pre_mean']:+.4f}</td><td>{d['pre_mean_placebo']:+.4f}</td><td>{pp['pre']:.3f}</td></tr>
<tr><td>post (0&rarr;+{H}d, relief)</td><td>{d['post_mean']:+.4f}</td><td>{d['post_mean_placebo']:+.4f}</td><td>{pp['post']:.3f}</td></tr>
<tr><td>full (-{H}d&rarr;+{H}d)</td><td>{d['full_mean']:+.4f}</td><td>{d['full_mean_placebo']:+.4f}</td><td>{pp['full']:.3f}</td></tr>
</table>
<div class="kv">net post-relief leg after {NET_COST*1e4:.0f}bps round-trip: mean
 <b>{summary['net_post_relief_leg'].get('mean_net')}</b>, sharpe/event
 {summary['net_post_relief_leg'].get('sharpe_per_event')}, DSR {summary['net_post_relief_leg'].get('dsr')}</div>
<h2>Top large unlocks by magnitude</h2>
<table>
<tr><th>sym</th><th>venue</th><th>cliff date</th><th>%float</th><th>pre</th><th>post</th><th>full</th></tr>
{body}
</table>
<p style="color:#888">Experiment only. Zero production impact. DefiLlama emissions + CoinGecko + keyless OHLC
(Bybit/Binance/Kraken). One pre-registered rule, no sweep. Placebo = random non-unlock dates on the same tokens.</p>
"""


# ----------------------------------------------------------------------------------------------------------
# Offline self-test of the PURE logic (no network) — deterministic, run with --selftest.
# ----------------------------------------------------------------------------------------------------------
def _selftest() -> int:
    """Validate the load-bearing pure functions on a deterministic synthetic fixture: window math,
    magnitude denominator, cliff extraction, and the placebo gap rule. No network, no Gate constant."""
    from decimal import Decimal

    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # 1) window_returns: a price that drops 1% per day for 5 days then rises 1% per day for 5 days, event at
    #    the trough -> pre < 0, post > 0, full ~ 0 (symmetric); verify the close-to-close math + centering.
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [100.0]
    for _ in range(5):
        closes.append(closes[-1] * 0.99)   # down into the event
    for _ in range(5):
        closes.append(closes[-1] * 1.01)   # relief after
    bars = [
        Bar(ts=t0 + timedelta(days=i), open=Decimal(str(c)), high=Decimal(str(c)),
            low=Decimal(str(c)), close=Decimal(str(c)), volume=Decimal(1))
        for i, c in enumerate(closes)
    ]
    w = window_returns(bars, t0 + timedelta(days=5), h=5)  # event at the trough (index 5)
    check("window pre-drift < 0 (down into event)", w is not None and w.pre < 0)
    check("window post-drift > 0 (relief)", w is not None and w.post > 0)
    check("window full ~= pre+post", w is not None and abs(w.full - (w.pre + w.post)) < 1e-9)
    check("window has 2H daily returns", w is not None and len(w.daily) == 10)
    check("window dropped when too close to edge", window_returns(bars, t0, h=5) is None)

    # 2) cliff extraction + % -of-float denominator from a tiny synthetic emissions payload.
    ts_a = int(datetime(2024, 3, 1, tzinfo=UTC).timestamp())
    ts_b = int(datetime(2024, 4, 1, tzinfo=UTC).timestamp())
    payload = {
        "name": "TestCoin",
        "metadata": {
            "unlockEvents": [
                {"timestamp": ts_a, "cliffAllocations": [
                    {"unlockType": "cliff", "amount": 10.0}]},
                {"timestamp": ts_b, "cliffAllocations": [
                    {"unlockType": "cliff", "amount": 30.0},
                    {"unlockType": "linear_start", "amount": 5.0}]},  # linear part must be ignored
            ]
        },
        "documentedData": {"data": [
            {"label": "X", "data": [
                {"timestamp": int(datetime(2024, 2, 1, tzinfo=UTC).timestamp()), "unlocked": 100.0},
                {"timestamp": int(datetime(2024, 3, 15, tzinfo=UTC).timestamp()), "unlocked": 110.0},
            ]},
        ]},
    }
    evs = extract_events(payload, "TEST", "synthetic")
    by_ts = {e.ts.date(): e for e in evs}
    a = by_ts.get(datetime.fromtimestamp(ts_a, tz=UTC).date())
    b = by_ts.get(datetime.fromtimestamp(ts_b, tz=UTC).date())
    check("event A extracted", a is not None)
    # circulating before A = latest doc point strictly < ts_a = the 2024-02-01 point (100); pct = 10/100 = 0.10
    check("event A magnitude = cliff/circulating_before (10/100)", a is not None and abs(a.unlock_pct - 0.10) < 1e-9)
    # event B: circulating before = 2024-03-15 point (110); cliff = 30 (linear ignored); pct = 30/110
    check("event B ignores linear, denom = prior doc point (30/110)",
          b is not None and abs(b.unlock_pct - (30.0 / 110.0)) < 1e-9)

    # 3) placebo gap rule: a placebo date must be >= PLACEBO_GAP_DAYS from a real unlock.
    real = [t0 + timedelta(days=20)]
    pbars = [Bar(ts=t0 + timedelta(days=i), open=Decimal(1), high=Decimal(1), low=Decimal(1),
                 close=Decimal(1), volume=Decimal(1)) for i in range(120)]
    pds = placebo_dates(pbars, real, 50, random.Random(1), h=5)
    near = [d for d in pds if any(abs((d - r).days) < PLACEBO_GAP_DAYS for r in real)]
    check("no placebo date within PLACEBO_GAP_DAYS of a real unlock", len(near) == 0)
    check("placebo dates drawn", len(pds) > 0)

    print(f"\nSELFTEST: {'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="N5 token-unlock supply-shock drift event-study (experiment-only).")
    ap.add_argument("--max-protocols", type=int, default=None, help="cap protocols scanned (default: all).")
    ap.add_argument("--selftest", action="store_true", help="run the offline pure-logic self-test (no network).")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "n5_token_unlock_table.html"))
    ap.add_argument("--json", default=os.path.join(os.path.dirname(__file__), "n5_token_unlock_results.json"))
    args = ap.parse_args()

    if args.selftest:
        print("N5 self-test (offline, pure logic):")
        return _selftest()

    print("N5 token-unlock event-study — fetching keyless DefiLlama emissions + matching OHLC...", file=sys.stderr)
    study = run_study(args.max_protocols)
    summary = summarize(study)
    verdict, reasons = _verdict(summary)

    out_json = {"summary": summary, "verdict": verdict, "reasons": reasons}
    with open(args.json, "w") as fh:
        json.dump(out_json, fh, indent=2, default=str)
    with open(args.out, "w") as fh:
        fh.write(render_html(study, summary, verdict, reasons))

    # Console digest (show every number).
    d = summary["drift"]
    pp = summary["placebo_p"]
    print(json.dumps(summary, indent=2, default=str))
    print("\n================ N5 VERDICT ================")
    print(f"N total cliff events: {summary['N_total_events']}  |  N LARGE (>= {LARGE_PCT*100:.0f}% float): {summary['N_large_events']}")
    print(f"pre-drift   real {d['pre_mean']:+.4f}  placebo {d['pre_mean_placebo']:+.4f}  p={pp['pre']:.3f}")
    print(f"post-drift  real {d['post_mean']:+.4f}  placebo {d['post_mean_placebo']:+.4f}  p={pp['post']:.3f}")
    print(f"full-window real {d['full_mean']:+.4f}  placebo {d['full_mean_placebo']:+.4f}  p={pp['full']:.3f}")
    print(f"net post-relief leg ({NET_COST*1e4:.0f}bps round-trip): mean {summary['net_post_relief_leg'].get('mean_net')}")
    print(f"VERDICT: {verdict}")
    for r in reasons:
        print(f"  - {r}")
    print(f"\nwrote {args.json}\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
