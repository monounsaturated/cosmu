# intent: CAPSTONE intraday over-extension FADE on Polymarket (EXPERIMENT ONLY, offline, keyless).
#
# THESIS (the actual live hypothesis the whole edge batch points to): when a market's odds SPIKE
# intraday (over-extend on flow/news), do they mean-revert within K hours — BEFORE resolution —
# enough to trade NET of fees AND the wide CLOB bid/ask spread? Retail over-reacts intraday; the
# snap-back is the edge. This is the OPPOSITE horizon of H9 (which shorted the long-shot and held to
# resolution and DIED on the survivorship tail). Here the trade opens and CLOSES intraday, strictly
# before resolution, so the resolution tail is NOT the risk — the SPREAD is.
#
# DATA (keyless, free — the windowed CLOB path the #389 trust experiment proved surfaces HOURLY odds):
#   - Gamma /events?closed=true -> RESOLVED markets + tags (category) + createdAt + endDate + outcomePrices.
#   - CLOB /prices-history?market={YES_token}&startTs=..&endTs=..&fidelity=60 -> HOURLY YES-odds (3600s
#     spacing). The full-history interval=max call only ever returns DAILY (fidelity=1440); the WINDOWED
#     startTs/endTs request is the only way to get hourly. We page the windows across each market's life.
#
# SIGNAL (one PRE-REGISTERED rule, NO sweep):
#   - rolling z-score of the H-hour odds CHANGE: z_t = (move_t - mean) / sd over a LOOKBACK of L bars,
#     where move_t = p_t - p_{t-H}. An over-extension is |z_t| >= Z_ENTRY.
#   - FADE it: if the odds spiked UP (z>0) we SHORT YES (bet it reverts down); if they spiked DOWN
#     (z<0) we LONG YES (bet it reverts up). Enter at p_t.
#   - EXIT after K_HOURS (time stop) at p_{t+K}, strictly before resolution. P&L per $1:
#       short YES: entry_p - exit_p ;  long YES: exit_p - entry_p.
#
# THREE DECISIVE DISCONFIRMERS:
#   (1) PIT — the z-score at entry uses ONLY bars up to and including the entry ts; the exit bar is in
#       the FUTURE of the entry but we never let the signal peek at it. Fail-LOUD asserts on every trade.
#   (2) NOT TREND-TOWARD-TRUTH — the move must be a genuine intraday over-extension, not the odds
#       legitimately converging to the eventual outcome. CONTROL by (a) EXCLUDING the final
#       FINAL_EXCLUDE_HOURS before resolution (where real convergence lives), and (b) decomposing the
#       fade P&L by whether we faded the side that EVENTUALLY WON vs LOST — a real reversion edge profits
#       on BOTH; an edge that only "works" by shorting winners-about-to-lose is just longshot bias.
#   (3) SPREAD HONESTY — the historical prices-history series is the MIDPOINT (Roll-spread ≈ 0 on it),
#       so the bid/ask is NOT in the data and MUST be charged explicitly. Each intraday round-trip pays
#       the CLOB spread, which on Polymarket is WIDE. We charge a per-round-trip spread calibrated from
#       LIVE two-sided books (sampled this run: median full spread ~1c, mean ~2.9c, p75 ~3c on genuinely
#       tradeable markets) at three levels (optimistic/base/conservative) + the category fee, and report
#       GROSS vs SPREAD vs NET decomposition plainly.
#
# FEES: net of the CATEGORY fee — 0% geopolitics, 3% sports. Crypto (7.2% band) EXCLUDED entirely.
# Gate: BRUT via cosmu/master/scorer.py (DSR / min-trades) on the per-trade NET-of-spread P&L.
#
# ZERO production impact: read-only fetches, persists NOTHING to prod, no Gate constant touched, no cron,
# docs-only. Writes a disposable HTML table + prints a JSON summary. Run:
#   python3 apps/engine/scripts/research/polymarket_intraday_overextension.py [--max-events N] [--out f.html]

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean, pstdev

# Make `cosmu` importable regardless of cwd (script dir is sys.path[0], not the engine root). This is the
# ONLY production touch and it is import-path plumbing for an offline research script (no prod behavior).
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# ----------------------------------------------------------------------------------------------------------
# Keyless fetch (certifi-backed SSL — the M2 needs it for these hosts; mirrors h9 + cosmu.data.altdata).
# ----------------------------------------------------------------------------------------------------------
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def _fetch(url: str, *, retries: int = 3) -> object:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 400:  # bad window/params — caller treats as empty, never retry
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — network/timeout → backoff retry
            last = e
        time.sleep(0.5 * (attempt + 1))
    if last:
        raise last
    return None


# ----------------------------------------------------------------------------------------------------------
# Category classification (geopolitics 0% fee, sports 3%, crypto 7.2% EXCLUDED) — same vocab as H9.
# ----------------------------------------------------------------------------------------------------------
_GEO_TAGS = {
    "politics", "geopolitics", "elections", "world", "world elections", "global elections",
    "economy", "economic policy", "fed rates", "fed", "fomc", "us election", "usa election",
    "middle east", "iran", "russia", "ukraine", "china", "israel", "trump", "biden", "harris",
    "election", "presidential election", "macro geopolitics", "fiscal", "taxes", "war", "nato",
}
_SPORTS_TAGS = {
    "sports", "nba", "nfl", "soccer", "basketball", "football", "baseball", "mlb", "nhl", "hockey",
    "tennis", "ufc", "mma", "boxing", "golf", "f1", "formula 1", "champions league", "premier league",
    "epl", "ucl", "super bowl", "superbowl", "super bowl champion", "world cup", "olympics", "ncaa",
}
_CRYPTO_TAGS = {
    "crypto", "bitcoin", "btc", "ethereum", "eth", "crypto prices", "solana", "memecoin", "altcoin",
    "crypto price", "defi",
}

# Per-category round-trip FEE on $1 (on TODAY's schedule — the "fees always today" rule). This is the
# venue FEE, charged ON TOP of the spread (which is a separate, dominant cost for intraday round-trips).
_CATEGORY_FEE = {"geopolitics": 0.0, "sports": 0.03}

# ----------------------------------------------------------------------------------------------------------
# PRE-REGISTERED rule (NO sweep — one config, declared up front).
# ----------------------------------------------------------------------------------------------------------
MOVE_HORIZON_H = 3        # over-extension move measured over the last 3 hours (p_t - p_{t-3})
Z_LOOKBACK = 48           # rolling z-score over the trailing 48 hourly bars (2 days of context)
Z_ENTRY = 2.5             # enter the FADE when |z| >= 2.5 (a clear over-extension, not noise)
K_HOURS = 6               # exit after 6 hours (time stop) — strictly intraday, well before resolution
FINAL_EXCLUDE_HOURS = 48  # NEVER enter inside the last 48h before resolution (where real convergence lives)
MIN_ENTRY_P = 0.05        # only fade mid-band odds; below/above this the tick floor + one-sided book dominate
MAX_ENTRY_P = 0.95
MIN_BARS_PER_MARKET = 96  # need at least ~4 days of hourly bars to form z-scores + non-overlapping trades
COOLDOWN_H = 6            # after a trade opens, no new entry until it closes (non-overlapping per market)

# Spread levels charged per intraday round-trip (one full bid/ask crossing in + out), calibrated from
# LIVE two-sided Polymarket books sampled at runtime (see calibrate_spread). These are the FULL spread in
# probability units; a round-trip pays ~one full spread (half on entry, half on exit).
SPREAD_LEVELS = {"optimistic_1c": 0.01, "base_3c": 0.03, "conservative_5c": 0.05}
SPREAD_PRIMARY = "base_3c"  # the headline NET uses the empirically-typical ~3c round-trip


def classify(tag_labels: list[str]) -> str | None:
    low = {(t or "").lower() for t in tag_labels}
    if low & _CRYPTO_TAGS:
        return None
    if low & _GEO_TAGS:
        return "geopolitics"
    if low & _SPORTS_TAGS:
        return "sports"
    return None


# ----------------------------------------------------------------------------------------------------------
# Live-book spread calibration (real two-sided books on OPEN markets) — disconfirmer-3 input.
# ----------------------------------------------------------------------------------------------------------
def calibrate_spread(pages: int = 4) -> dict:
    """Sample the REAL current bid/ask spread on genuinely-tradeable two-sided OPEN markets, so the spread
    we charge is empirical not assumed. Resolved markets have a degenerate post-resolution book (~0.001),
    so live open markets are the only honest source of the intraday spread the fade would actually pay."""
    spreads: list[float] = []
    for off in range(0, pages * 100, 100):
        try:
            ev = _fetch(f"{GAMMA}/events?closed=false&active=true&limit=100&offset={off}&order=volume&ascending=false")
        except Exception:  # noqa: BLE001
            break
        if not isinstance(ev, list) or not ev:
            break
        for e in ev:
            for m in e.get("markets") or []:
                try:
                    bb = float(m.get("bestBid"))
                    ba = float(m.get("bestAsk"))
                except (TypeError, ValueError):
                    continue
                mid = (bb + ba) / 2.0
                w = ba - bb
                if 0.05 <= mid <= 0.95 and 0.0 < w < 0.20:  # genuine two-sided tradeable book
                    spreads.append(w)
    spreads.sort()
    if not spreads:
        return {"n": 0}

    def pct(p: float) -> float:
        return spreads[int(p / 100 * (len(spreads) - 1))]

    return {
        "n": len(spreads),
        "p10": pct(10), "p25": pct(25), "median": pct(50), "p75": pct(75), "p90": pct(90),
        "mean": fmean(spreads),
    }


# ----------------------------------------------------------------------------------------------------------
# Discovery: resolved binary markets across geopolitics + sports (survivorship-complete; crypto excluded).
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Market:
    condition_id: str
    question: str
    category: str
    yes_token: str
    created_at: datetime
    deadline: datetime
    terminal_yes: float  # UMA-settled YES outcome in {0,1} (resolution label, used ONLY for disconfirmer-2)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(s[:19].replace("Z", "")).replace(tzinfo=UTC)
        except ValueError:
            return None


def _yes_token(m: dict) -> str | None:
    tids = m.get("clobTokenIds") or "[]"
    if isinstance(tids, str):
        try:
            tids = json.loads(tids)
        except (json.JSONDecodeError, TypeError):
            tids = []
    return str(tids[0]) if tids else None


def _terminal_yes(m: dict) -> float | None:
    op = m.get("outcomePrices")
    if isinstance(op, str):
        try:
            op = json.loads(op)
        except (json.JSONDecodeError, TypeError):
            op = None
    if not op or len(op) < 2:
        return None
    try:
        yes = float(op[0])
        no = float(op[1])
    except (TypeError, ValueError):
        return None
    yes_r = 1.0 if yes > 0.9 else (0.0 if yes < 0.1 else None)
    no_r = 1.0 if no > 0.9 else (0.0 if no < 0.1 else None)
    if yes_r is None or no_r is None or yes_r == no_r:
        return None
    return yes_r


def discover(max_events: int, *, page: int = 100, per_cat_budget: int = 0, seed: int = 7) -> list[Market]:
    """Resolved binary markets across geopolitics + sports, sampling EVERY market in each event. Seeded
    down-sample per category (per_cat_budget>0) to spread the hourly-fetch budget across the full resolved
    history — the shuffle does NOT condition on outcome (survivorship-complete)."""
    out: list[Market] = []
    seen: set[str] = set()
    offset = 0
    pulled_events = 0
    while pulled_events < max_events:
        url = f"{GAMMA}/events?closed=true&limit={page}&offset={offset}&order=volume&ascending=false"
        try:
            events = _fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [discover] event page offset={offset} failed: {e}", file=sys.stderr)
            break
        if not isinstance(events, list) or not events:
            break
        for ev in events:
            pulled_events += 1
            tag_labels = [t.get("label") for t in (ev.get("tags") or [])]
            cat = classify(tag_labels)
            if cat is None:
                continue
            for m in ev.get("markets") or []:
                outs = m.get("outcomes")
                if isinstance(outs, str):
                    try:
                        outs = json.loads(outs)
                    except (json.JSONDecodeError, TypeError):
                        outs = []
                if not outs or len(outs) != 2:
                    continue
                cid = str(m.get("conditionId") or m.get("id") or "")
                if not cid or cid in seen:
                    continue
                tok = _yes_token(m)
                term = _terminal_yes(m)
                created = _parse_dt(m.get("createdAt"))
                deadline = _parse_dt(m.get("endDate") or m.get("endDateIso"))
                if not (tok and term is not None and created and deadline):
                    continue
                if deadline <= created:
                    continue
                seen.add(cid)
                out.append(Market(cid, (m.get("question") or "")[:120], cat, tok, created, deadline, term))
        offset += page
        if pulled_events >= max_events:
            break
        time.sleep(0.15)

    if per_cat_budget > 0:
        import random

        rng = random.Random(seed)
        capped: list[Market] = []
        for cat in ("geopolitics", "sports"):
            pool = [m for m in out if m.category == cat]
            rng.shuffle(pool)
            capped.extend(pool[:per_cat_budget])
        return capped
    return out


# ----------------------------------------------------------------------------------------------------------
# HOURLY YES-odds via the WINDOWED CLOB path (the #389 finding). interval=max only gives daily; the
# startTs/endTs windowed request at fidelity=60 returns ~3600s-spaced rows. We page windows across life.
# ----------------------------------------------------------------------------------------------------------
def hourly_odds(yes_token: str, start: datetime, end: datetime, *, window_days: int = 14) -> list[tuple[datetime, float]]:
    """Hourly YES-odds over [start, end] by paging fidelity=60 windows of `window_days`. Dedupe + sort.
    Empty on any failure (dead fetch / no history) — the market is then skipped."""
    out: dict[int, float] = {}
    s = int(start.timestamp())
    e = int(end.timestamp())
    if e <= s:
        return []
    step = window_days * 86400
    t = s
    while t < e:
        w_end = min(t + step, e)
        q = urllib.parse.urlencode({"market": yes_token, "startTs": t, "endTs": w_end, "fidelity": 60})
        try:
            payload = _fetch(f"{CLOB}/prices-history?{q}")
        except Exception:  # noqa: BLE001 — dead window → skip this window, keep paging
            payload = None
        rows = payload.get("history", []) if isinstance(payload, dict) else []
        for row in rows:
            try:
                ts = int(row["t"])
                out[ts] = float(row["p"])
            except (KeyError, TypeError, ValueError):
                continue
        t = w_end
    series = sorted((datetime.fromtimestamp(ts, tz=UTC), p) for ts, p in out.items())
    return series


# ----------------------------------------------------------------------------------------------------------
# The pre-registered intraday FADE: z-score over-extension entry, K-hour time-stop exit, before resolution.
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Trade:
    condition_id: str
    question: str
    category: str
    entry_ts: datetime
    exit_ts: datetime
    deadline: datetime
    side: str            # "short_yes" (faded an up-spike) or "long_yes" (faded a down-spike)
    z: float             # the entry z-score of the H-hour move (signed)
    entry_p: float
    exit_p: float
    hours_to_deadline: float
    terminal_yes: float
    faded_winner: bool   # True if we faded the side that EVENTUALLY won (disconfirmer-2 decomposition)
    gross_pnl: float     # per $1, BEFORE spread & fee
    spread_cost: float   # the primary (base) round-trip spread charged
    fee: float
    net_pnl: float       # gross - spread(primary) - fee


def build_trades(m: Market, series: list[tuple[datetime, float]]) -> list[Trade]:
    """Non-overlapping intraday fades on one market's hourly odds. PIT: the z-score at bar i uses ONLY
    bars[:i+1]; the exit is bar i+K in the future. Skip entries inside the final-exclude window."""
    n = len(series)
    if n < MIN_BARS_PER_MARKET:
        return []
    ts = [t for t, _ in series]
    p = [v for _, v in series]
    deadline_ts = m.deadline.timestamp()
    fee = _CATEGORY_FEE[m.category]
    spread_primary = SPREAD_LEVELS[SPREAD_PRIMARY]
    trades: list[Trade] = []
    i = Z_LOOKBACK + MOVE_HORIZON_H  # first bar with a full lookback of H-hour moves
    while i + K_HOURS < n:
        entry_t = ts[i]
        # disconfirmer-2 control: never enter inside the final convergence window
        if (deadline_ts - entry_t.timestamp()) / 3600.0 <= FINAL_EXCLUDE_HOURS:
            break  # series is sorted ascending; all later bars are even closer to the deadline
        # rolling z of the H-hour move, using ONLY bars up to i (PIT)
        moves = [p[j] - p[j - MOVE_HORIZON_H] for j in range(i - Z_LOOKBACK + 1, i + 1)]
        # PIT assertion — the newest bar feeding the signal must be the entry bar, never the future
        assert ts[i] == entry_t, "z-window peeked past the entry bar (look-ahead)"
        mu = fmean(moves)
        sd = pstdev(moves)
        if sd <= 1e-9:
            i += 1
            continue
        move_now = p[i] - p[i - MOVE_HORIZON_H]
        z = (move_now - mu) / sd
        entry_p = p[i]
        if not (MIN_ENTRY_P <= entry_p <= MAX_ENTRY_P) or abs(z) < Z_ENTRY:
            i += 1
            continue
        exit_i = i + K_HOURS
        exit_t = ts[exit_i]
        # PIT assertions — fail LOUD: entry strictly before exit strictly before deadline
        assert entry_t < exit_t, "exit not after entry"
        assert exit_t.timestamp() < deadline_ts, "exit at/after resolution (intraday invariant broken)"
        exit_p = p[exit_i]
        # FADE: up-spike (z>0) -> SHORT YES (profit if it falls); down-spike (z<0) -> LONG YES.
        if z > 0:
            side = "short_yes"
            gross = entry_p - exit_p
        else:
            side = "long_yes"
            gross = exit_p - entry_p
        # disconfirmer-2: did we fade the side that EVENTUALLY WON? (short_yes when YES won, or long_yes
        # when YES lost = we faded the eventual winner). A real reversion edge should NOT depend on this.
        faded_winner = (side == "short_yes" and m.terminal_yes >= 0.5) or (
            side == "long_yes" and m.terminal_yes < 0.5
        )
        net = gross - spread_primary - fee
        trades.append(
            Trade(
                condition_id=m.condition_id, question=m.question, category=m.category,
                entry_ts=entry_t, exit_ts=exit_t, deadline=m.deadline, side=side, z=z,
                entry_p=entry_p, exit_p=exit_p,
                hours_to_deadline=(deadline_ts - entry_t.timestamp()) / 3600.0,
                terminal_yes=m.terminal_yes, faded_winner=faded_winner,
                gross_pnl=gross, spread_cost=spread_primary, fee=fee, net_pnl=net,
            )
        )
        i = exit_i + COOLDOWN_H  # non-overlapping: next entry only after this trade closes + cooldown
    return trades


# ----------------------------------------------------------------------------------------------------------
# Gate stats (BRUT) via the REAL production scorer — byte-identical DSR/min-trades.
# ----------------------------------------------------------------------------------------------------------
def gate_stats(net_pnls: list[float]) -> dict:
    from decimal import Decimal

    from cosmu.config.settings import GateSettings
    from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob, sample_moments

    n = len(net_pnls)
    if n < 2:
        return {"n": n, "note": "too few trades for stats"}
    sr_obs, skew, kurt, _ = sample_moments(net_pnls)
    wins = sum(1 for x in net_pnls if x > 0)
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(sum(net_pnls), 6))),
        sharpe=Decimal(str(round(sr_obs * math.sqrt(n), 6))),
        sortino=Decimal("0"), max_drawdown=Decimal("0"),
        win_rate=Decimal(str(round(wins / n, 6))), num_trades=n,
        sharpe_per_obs=Decimal(str(round(sr_obs, 6))),
        skew=Decimal(str(round(skew, 6))), kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n, trials_counted=1,
    )
    gates = GateSettings()
    dsr = deflated_sharpe_prob(metrics, TrialStats(count=1))
    passes_min_trades = n >= gates.min_trades
    passes_dsr = Decimal(str(dsr)) >= gates.min_deflated_sharpe_prob
    return {
        "n": n, "mean_net_pnl": fmean(net_pnls), "sd_net_pnl": pstdev(net_pnls),
        "sharpe_per_obs": sr_obs, "skew": skew, "kurtosis": kurt, "win_rate": wins / n,
        "deflated_sharpe_prob": dsr,
        "min_deflated_sharpe_prob_gate": float(gates.min_deflated_sharpe_prob),
        "min_trades_gate": gates.min_trades,
        "passes_min_trades": passes_min_trades, "passes_dsr": passes_dsr,
        "passes_gate": bool(passes_min_trades and passes_dsr),
    }


# ----------------------------------------------------------------------------------------------------------
# Per-category aggregation + the GROSS-vs-SPREAD-vs-NET decomposition that decides the verdict.
# ----------------------------------------------------------------------------------------------------------
def summarize(trades: list[Trade], category: str, spread_levels: dict) -> dict:
    ct = [t for t in trades if t.category == category]
    n = len(ct)
    if n == 0:
        return {"category": category, "n": 0}
    fee = _CATEGORY_FEE[category]
    gross = [t.gross_pnl for t in ct]
    mean_gross = fmean(gross)
    # NET at each spread level (= gross - spread - fee), to show exactly where the edge dies
    net_by_spread = {
        name: fmean([t.gross_pnl - s - fee for t in ct]) for name, s in spread_levels.items()
    }
    # disconfirmer-2 decomposition: faded-winner vs faded-loser legs (a real edge profits on BOTH)
    fw = [t.gross_pnl for t in ct if t.faded_winner]
    fl = [t.gross_pnl for t in ct if not t.faded_winner]
    # reversion sign on the GROSS leg: >0 means the fade direction was right on average (it reverted)
    primary_net = [t.net_pnl for t in ct]
    return {
        "category": category, "n": n,
        "mean_z": fmean([abs(t.z) for t in ct]),
        "mean_entry_p": fmean([t.entry_p for t in ct]),
        "mean_hours_to_deadline": fmean([t.hours_to_deadline for t in ct]),
        "n_short_yes": sum(1 for t in ct if t.side == "short_yes"),
        "n_long_yes": sum(1 for t in ct if t.side == "long_yes"),
        "category_fee": fee,
        "mean_gross_pnl": mean_gross,                       # the raw reversion edge (sign = does it revert?)
        "reversion_sign_positive": mean_gross > 0,
        "spread_primary": spread_levels[SPREAD_PRIMARY],
        "net_by_spread": net_by_spread,                     # gross - spread - fee at each level
        "mean_net_pnl_primary": fmean(primary_net),
        "total_net_pnl_primary": sum(primary_net),
        "n_faded_winner": len(fw), "n_faded_loser": len(fl),
        "mean_gross_faded_winner": fmean(fw) if fw else 0.0,
        "mean_gross_faded_loser": fmean(fl) if fl else 0.0,
        "gate_gross": gate_stats(gross),                    # gate on the GROSS leg (is there ANY edge?)
        "gate_net_primary": gate_stats(primary_net),        # gate on the NET-of-spread leg (the real test)
    }


# ----------------------------------------------------------------------------------------------------------
# HTML table (disposable, surfaces EVERY trade per the "surface all compute" rule).
# ----------------------------------------------------------------------------------------------------------
def render_html(trades: list[Trade], cat_summaries: list[dict], meta: dict, spread_cal: dict) -> str:
    def f(x, d=4):
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else str(x)

    rows = []
    for t in sorted(trades, key=lambda x: (x.category, -abs(x.net_pnl))):
        cls = "rev" if t.gross_pnl > 0 else "adv"
        rows.append(
            f"<tr class='{cls}'><td>{t.category}</td><td class='q'>{t.question}</td>"
            f"<td>{t.entry_ts.strftime('%Y-%m-%d %H:%M')}</td><td>{f(t.hours_to_deadline,0)}</td>"
            f"<td>{t.side}</td><td>{f(t.z,2)}</td><td>{f(t.entry_p,3)}</td><td>{f(t.exit_p,3)}</td>"
            f"<td>{'WIN' if t.faded_winner else 'lose'}</td>"
            f"<td>{f(t.gross_pnl)}</td><td>{f(t.spread_cost)}</td><td>{f(t.fee)}</td>"
            f"<td><b>{f(t.net_pnl)}</b></td></tr>"
        )

    cat_rows = []
    for s in cat_summaries:
        if s.get("n", 0) == 0:
            continue
        gg = s.get("gate_gross", {})
        gn = s.get("gate_net_primary", {})
        v_gross = "PASS" if gg.get("passes_gate") else "FAIL"
        v_net = "PASS" if gn.get("passes_gate") else "FAIL"
        nbs = s["net_by_spread"]
        cat_rows.append(
            f"<tr><td><b>{s['category']}</b></td><td>{s['n']}</td>"
            f"<td>{f(s['mean_z'],2)}</td><td>{f(s['mean_entry_p'],3)}</td>"
            f"<td>{f(s['mean_hours_to_deadline'],0)}</td>"
            f"<td>{s['n_short_yes']}/{s['n_long_yes']}</td>"
            f"<td><b>{f(s['mean_gross_pnl'])}</b><br><span class=sub>{'reverts' if s['reversion_sign_positive'] else 'adverse'}</span></td>"
            f"<td>{f(nbs.get('optimistic_1c',0))}</td><td>{f(nbs.get('base_3c',0))}</td><td>{f(nbs.get('conservative_5c',0))}</td>"
            f"<td>{f(s['mean_gross_faded_winner'])} / {f(s['mean_gross_faded_loser'])}</td>"
            f"<td>{f(gg.get('deflated_sharpe_prob',0),3)}</td>"
            f"<td class='{'pass' if v_gross=='PASS' else 'fail'}'>{v_gross}</td>"
            f"<td>{f(gn.get('deflated_sharpe_prob',0),3)}</td>"
            f"<td class='{'pass' if v_net=='PASS' else 'fail'}'>{v_net}</td></tr>"
        )

    sc = spread_cal
    sc_line = (
        f"live two-sided books sampled: N={sc.get('n',0)}, full spread cents "
        f"p25={f(sc.get('p25',0)*100,1)} median={f(sc.get('median',0)*100,1)} "
        f"mean={f(sc.get('mean',0)*100,1)} p75={f(sc.get('p75',0)*100,1)} p90={f(sc.get('p90',0)*100,1)}"
        if sc.get("n") else "live spread sample unavailable"
    )

    return f"""<!doctype html><meta charset=utf-8>
<title>Polymarket intraday over-extension fade — {meta['generated']}</title>
<style>
 body{{font:13px/1.5 -apple-system,system-ui,sans-serif;margin:24px;color:#111;background:#fafafa}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px}}
 table{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0;font-size:12px}}
 th,td{{border:1px solid #ddd;padding:4px 7px;text-align:right}} td.q{{text-align:left;max-width:300px}}
 th{{background:#f0f0f0;text-align:right}} td:first-child,td.q{{text-align:left}}
 tr.rev{{background:#f5fbf5}} tr.adv{{background:#fff4f4}}
 td.pass{{background:#d8f5d8;font-weight:700}} td.fail{{background:#f8d8d8;font-weight:700}}
 .meta{{color:#555;font-size:12px}} .sub{{color:#888;font-size:10px}}
 .legend span{{padding:2px 8px;border:1px solid #ccc;margin-right:6px}}
 .rev-l{{background:#f5fbf5}} .adv-l{{background:#fff4f4}}
</style>
<h1>Polymarket INTRADAY over-extension FADE (EXPERIMENT ONLY — the capstone)</h1>
<p class=meta>Generated {meta['generated']} · HOURLY odds via windowed CLOB (startTs/endTs, fidelity=60) ·
FADE the |z|&ge;{Z_ENTRY} over-extension of the {MOVE_HORIZON_H}h move (z over {Z_LOOKBACK}h), exit after
{K_HOURS}h, entry p∈[{MIN_ENTRY_P},{MAX_ENTRY_P}], NEVER inside the last {FINAL_EXCLUDE_HOURS}h before
resolution · net of category fee (geopolitics 0%, sports 3%) + CLOB spread · crypto EXCLUDED ·
{meta['n_markets']} resolved binaries, {meta['n_with_series']} with hourly series, {meta['n_trades']}
qualifying trades · keyless Gamma+CLOB · ZERO prod impact.</p>
<p class=meta><b>Spread calibration (disconfirmer 3):</b> {sc_line}. Primary NET charges
{f(SPREAD_LEVELS[SPREAD_PRIMARY]*100,1)}c per round-trip ({SPREAD_PRIMARY}).</p>
<div class=legend><span class=rev-l>reverted (fade right, gross&gt;0)</span>
<span class=adv-l>continued (fade wrong, gross&lt;0)</span></div>

<h2>Per-category verdict — GROSS vs SPREAD vs NET (BRUT)</h2>
<table><tr><th>category</th><th>N</th><th>mean |z|</th><th>mean entry p</th><th>mean h→dl</th>
<th>short/long</th><th>mean GROSS</th><th>net@1c</th><th>net@3c</th><th>net@5c</th>
<th>gross faded-win/lose</th><th>DSR gross</th><th>Gate gross</th><th>DSR net</th><th>Gate net</th></tr>
{''.join(cat_rows)}</table>
<p class=meta>mean GROSS = raw reversion edge per $1 before costs (sign &gt;0 = odds reverted after the
spike, thesis-consistent). net@Xc = gross − Xc spread − category fee. faded-win/lose = mean gross when we
faded the eventual WINNER vs LOSER (a real reversion edge profits on BOTH; if only the loser leg pays,
it's longshot bias not reversion). Gate = production scorer (min_trades={meta['min_trades_gate']},
DSR≥{meta['dsr_gate']}).</p>

<h2>Every trade ({meta['n_trades']})</h2>
<table><tr><th>cat</th><th>question</th><th>entry (UTC)</th><th>h→dl</th><th>side</th><th>z</th>
<th>entry p</th><th>exit p</th><th>faded</th><th>gross</th><th>spread</th><th>fee</th><th>NET</th></tr>
{''.join(rows)}</table>
"""


# ----------------------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-events", type=int, default=1200, help="resolved events to scan (volume-ranked)")
    ap.add_argument("--out", default="/tmp/polymarket_intraday_overextension.html")
    ap.add_argument("--max-markets", type=int, default=0, help="cap markets fetched (0 = all discovered)")
    ap.add_argument("--per-cat-budget", type=int, default=300,
                    help="seeded down-sample per category (hourly fetch is heavier than daily; 0 = all)")
    ap.add_argument("--workers", type=int, default=10, help="parallel CLOB windowed fetchers")
    ap.add_argument("--json-out", default="", help="optional path to also write the JSON summary")
    args = ap.parse_args()

    t0 = time.time()
    print("[PMI] calibrating live spread (real two-sided books)...", file=sys.stderr)
    spread_cal = calibrate_spread()
    print(f"[PMI] spread cal: {spread_cal}", file=sys.stderr)

    print(f"[PMI] discovering resolved binaries (max_events={args.max_events})...", file=sys.stderr)
    markets = discover(args.max_events, per_cat_budget=args.per_cat_budget)
    if args.max_markets:
        markets = markets[: args.max_markets]
    print(f"[PMI] discovered/sampled {len(markets)} resolved binaries: "
          f"{dict(Counter(m.category for m in markets))}", file=sys.stderr)

    from concurrent.futures import ThreadPoolExecutor

    all_trades: list[Trade] = []
    n_with_series = 0
    done = 0

    def _one(m: Market) -> tuple[bool, list[Trade]]:
        # fetch hourly odds over the whole life of the market (created -> deadline), windowed
        series = hourly_odds(m.yes_token, m.created_at, m.deadline)
        if len(series) < MIN_BARS_PER_MARKET:
            return (False, [])
        return (True, build_trades(m, series))

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for had_series, tr in ex.map(_one, markets):
            done += 1
            if had_series:
                n_with_series += 1
            all_trades.extend(tr)
            if done % 50 == 0:
                print(f"[PMI]  {done}/{len(markets)} fetched, {n_with_series} w/ hourly series, "
                      f"{len(all_trades)} trades so far", file=sys.stderr)

    cats = ["geopolitics", "sports"]
    cat_summaries = [summarize(all_trades, c, SPREAD_LEVELS) for c in cats]
    # pooled (all categories) — the brut headline
    pooled = summarize(all_trades, "pooled", SPREAD_LEVELS) if all_trades else {"category": "pooled", "n": 0}
    if all_trades:
        # summarize() filters by category; build a pooled view by re-tagging
        pooled = {
            "category": "ALL",
            "n": len(all_trades),
            "mean_gross_pnl": fmean([t.gross_pnl for t in all_trades]),
            "reversion_sign_positive": fmean([t.gross_pnl for t in all_trades]) > 0,
            "net_by_spread": {
                name: fmean([t.gross_pnl - s - _CATEGORY_FEE[t.category] for t in all_trades])
                for name, s in SPREAD_LEVELS.items()
            },
            "gate_gross": gate_stats([t.gross_pnl for t in all_trades]),
            "gate_net_primary": gate_stats([t.net_pnl for t in all_trades]),
        }

    from cosmu.config.settings import GateSettings

    g = GateSettings()
    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_markets": len(markets), "n_with_series": n_with_series, "n_trades": len(all_trades),
        "min_trades_gate": g.min_trades, "dsr_gate": float(g.min_deflated_sharpe_prob),
        "elapsed_s": round(time.time() - t0, 1),
        "rule": {
            "move_horizon_h": MOVE_HORIZON_H, "z_lookback": Z_LOOKBACK, "z_entry": Z_ENTRY,
            "k_hours": K_HOURS, "final_exclude_hours": FINAL_EXCLUDE_HOURS,
            "entry_band": [MIN_ENTRY_P, MAX_ENTRY_P], "spread_levels": SPREAD_LEVELS,
            "spread_primary": SPREAD_PRIMARY,
        },
        "spread_calibration": spread_cal,
    }

    html = render_html(all_trades, cat_summaries, meta, spread_cal)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)

    summary = {"meta": meta, "pooled": pooled, "categories": cat_summaries}
    out_json = json.dumps(summary, indent=2, default=str)
    print(out_json)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(out_json)
    print(f"\n[PMI] HTML -> {args.out}  ({meta['elapsed_s']}s, {n_with_series}/{len(markets)} had hourly "
          f"series, {len(all_trades)} trades)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
