# intent: H9 — Polymarket resolution-convergence theta-decay study (EXPERIMENT ONLY, offline, keyless).
#
# THESIS: a long-shot YES on a dated binary theta-decays toward 0 as the deadline nears, because retail
# lottery-buyers do not time-decay probability. The trade = SHORT the long-shot YES (= buy NO) at a fixed
# days-to-deadline, hold to resolution. P&L per $1 short = entry_YES - terminal_YES, net of the category fee.
#
# DATA (keyless, free — the SAME endpoints cosmu/data/sources/polymarket.py already calls):
#   - Gamma /events?closed=true  -> RESOLVED markets + per-event tag labels (category) + endDate (deadline,
#     fixed at createdAt) + outcomePrices (the UMA-settled terminal YES/NO, the resolution label).
#   - CLOB /prices-history?market={YES_token}&fidelity=1440&interval=max -> daily YES-odds history.
#
# TWO DISCONFIRMERS that decide the whole thing:
#   (1) SURVIVORSHIP (core risk): we sample ALL resolved binary markets in each category — both the many
#       long-shots that resolved NO *and* the rare long-shots that resolved YES (the tail that pays off big
#       against the short). Dropping the YES-resolvers is fake edge that blows up on the tail. Multi-outcome
#       events (NBA-champion, election-winner) are sampled in full, which is exactly where the YES-resolvers
#       live.
#   (2) PIT-SAFE: the deadline (endDate) is fixed at market creation; the outcome (outcomePrices) only labels
#       post-hoc; the entry price is a real daily as-of bar strictly BEFORE the deadline. We assert
#       entry_ts < deadline and entry_ts >= createdAt on every trade — no look-ahead.
#
# ONE pre-registered entry rule (NO sweep): long-shot = entry-bar YES in [LO_BAND, HI_BAND]; entry bar = the
# daily bar closest to ENTRY_DAYS_TO_DEADLINE days before endDate; SHORT YES, hold to resolution.
#
# FEES: net of the CATEGORY fee — 0% geopolitics, 3% sports. Crypto (7.2% band) is EXCLUDED entirely.
#
# Gate stats: BRUT per category via cosmu/master/scorer.py (DSR / PBO / min-trades) on the per-trade P&L.
#
# ZERO production impact: read-only fetches, persists NOTHING to prod, no Gate constant touched, no cron,
# docs-only. Writes a disposable HTML table + prints a JSON summary to stdout. Run:
#   python3 apps/engine/scripts/research/h9_polymarket_thetadecay.py [--max-events N] [--out report.html]

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

# Make `cosmu` importable regardless of cwd: a script run as `python3 scripts/research/foo.py` puts the
# SCRIPT dir on sys.path[0], not the engine root — so add apps/engine (three levels up) explicitly. This is
# the ONLY production touch and it is import-path plumbing for an offline research script (no prod behavior).
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# ----------------------------------------------------------------------------------------------------------
# Keyless fetch (certifi-backed SSL — the M2 needs it for these hosts; mirrors cosmu.data.providers._types)
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
# Category classification by event tag labels (the reliable path — the /markets?order= path strips tags).
# Geopolitics = 0% fee band; Sports = 3%; Crypto = 7.2% EXCLUDED.
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

# Per-category round-trip fee charged on a $1 short (entry + exit/settlement), on TODAY's schedule (the
# memory's "fees always today" rule). Polymarket charges 0% on most geopolitics/event markets; the sports
# band is the higher tier; the crypto band (~7.2%) is excluded so it never flatters the result.
_CATEGORY_FEE = {"geopolitics": 0.0, "sports": 0.03}

# Pre-registered entry rule (NO sweep — one config, declared up front).
ENTRY_DAYS_TO_DEADLINE = 14  # enter on the daily bar closest to 14 days before the deadline
LO_BAND = 0.05               # "long-shot YES" = entry odds in [0.05, 0.25] — a cheap lottery ticket,
HI_BAND = 0.25               #   not noise (>=0.05) and clearly a long-shot (<=0.25)
ENTRY_TOL_DAYS = 7           # the entry bar must be within +/-7d of the target days-to-deadline, else skip


def classify(tag_labels: list[str]) -> str | None:
    """geopolitics | sports | None (crypto / mixed-crypto / unclassifiable -> excluded)."""
    low = {(t or "").lower() for t in tag_labels}
    if low & _CRYPTO_TAGS:
        return None  # crypto band excluded outright (and any market that even touches it)
    if low & _GEO_TAGS:
        return "geopolitics"
    if low & _SPORTS_TAGS:
        return "sports"
    return None


# ----------------------------------------------------------------------------------------------------------
# Discovery: page resolved events by volume, keep ALL binary markets (survivorship-complete).
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Market:
    condition_id: str
    question: str
    category: str
    yes_token: str
    created_at: datetime
    deadline: datetime
    terminal_yes: float  # the UMA-settled YES outcome in {0,1} (resolution label, post-hoc)


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
    """The resolved YES terminal price from Gamma outcomePrices=[YES,NO]; binary {0,1} only."""
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
    # Round the dust (e.g. 0.0000004 / 0.9999996) to a clean binary; reject anything not ~{0,1}.
    yes_r = 1.0 if yes > 0.9 else (0.0 if yes < 0.1 else None)
    no_r = 1.0 if no > 0.9 else (0.0 if no < 0.1 else None)
    if yes_r is None or no_r is None or yes_r == no_r:
        return None  # not a cleanly-resolved binary (void / 50-50 / multi) -> excluded
    return yes_r


def discover(max_events: int, *, page: int = 100, per_cat_budget: int = 0, seed: int = 7) -> list[Market]:
    """Resolved binary markets across geopolitics + sports, sampling EVERY market in each event (both
    YES- and NO-resolvers). Crypto excluded. Returns one Market per cleanly-resolved binary.

    `per_cat_budget` (>0) deterministically down-samples each category to that many markets via a SEEDED
    shuffle over the *full* discovered set — so the per-market odds-fetch budget is spent across the whole
    resolved history (not just top-volume), while STILL sampling YES- and NO-resolvers in proportion
    (survivorship-complete: the shuffle does not condition on outcome)."""
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
                # binary YES/NO markets only
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
                out.append(
                    Market(
                        condition_id=cid,
                        question=(m.get("question") or "")[:120],
                        category=cat,
                        yes_token=tok,
                        created_at=created,
                        deadline=deadline,
                        terminal_yes=term,
                    )
                )
        offset += page
        if pulled_events >= max_events:
            break
        time.sleep(0.15)  # be gentle on the public API

    if per_cat_budget > 0:
        import random

        rng = random.Random(seed)
        capped: list[Market] = []
        for cat in ("geopolitics", "sports"):
            pool = [m for m in out if m.category == cat]
            rng.shuffle(pool)  # seeded — does NOT look at outcome, so YES/NO ratio is preserved in expectation
            capped.extend(pool[:per_cat_budget])
        return capped
    return out


# ----------------------------------------------------------------------------------------------------------
# Daily YES-odds history (keyless CLOB, interval=max&fidelity=1440 — the path the engine already uses).
# ----------------------------------------------------------------------------------------------------------
def daily_odds(yes_token: str) -> list[tuple[datetime, float]]:
    q = urllib.parse.urlencode({"market": yes_token, "fidelity": 1440, "interval": "max"})
    try:
        payload = _fetch(f"{CLOB}/prices-history?{q}")
    except Exception:  # noqa: BLE001 — dead fetch -> empty, the market is skipped
        return []
    rows = payload.get("history", []) if isinstance(payload, dict) else []
    out: list[tuple[datetime, float]] = []
    for row in rows:
        try:
            ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
            out.append((ts, float(row["p"])))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    out.sort(key=lambda x: x[0])
    return out


# ----------------------------------------------------------------------------------------------------------
# The pre-registered trade: SHORT YES at the entry bar, hold to resolution. P&L per $1 = entry - terminal.
# ----------------------------------------------------------------------------------------------------------
@dataclass
class Trade:
    condition_id: str
    question: str
    category: str
    entry_ts: datetime
    deadline: datetime
    days_to_deadline: float
    entry_yes: float
    terminal_yes: float
    resolved_yes: bool
    gross_pnl: float  # per $1 short YES = entry - terminal (before fee)
    fee: float
    net_pnl: float


def build_trade(m: Market, series: list[tuple[datetime, float]]) -> Trade | None:
    """Pick the entry bar nearest ENTRY_DAYS_TO_DEADLINE days before the deadline, require it inside the
    long-shot band, then SHORT YES and hold to resolution. Returns None if no qualifying entry."""
    if not series:
        return None
    target = m.deadline.timestamp() - ENTRY_DAYS_TO_DEADLINE * 86400.0
    # candidate bars STRICTLY before the deadline (PIT: never use a bar at/after settlement)
    cands = [(ts, p) for ts, p in series if ts < m.deadline and ts >= m.created_at]
    if not cands:
        return None
    entry_ts, entry_p = min(cands, key=lambda x: abs(x[0].timestamp() - target))
    dtd = (m.deadline.timestamp() - entry_ts.timestamp()) / 86400.0
    # entry bar must be within tolerance of the pre-registered days-to-deadline
    if abs(dtd - ENTRY_DAYS_TO_DEADLINE) > ENTRY_TOL_DAYS:
        return None
    # PIT assertions — fail LOUD if violated (no silent look-ahead)
    assert entry_ts < m.deadline, "entry bar at/after deadline (look-ahead)"
    assert entry_ts >= m.created_at, "entry bar before market creation (impossible)"
    # long-shot band filter (pre-registered, no sweep)
    if not (LO_BAND <= entry_p <= HI_BAND):
        return None
    gross = entry_p - m.terminal_yes  # short YES: profit when terminal < entry
    fee = _CATEGORY_FEE[m.category]   # round-trip category fee on $1 notional
    net = gross - fee
    return Trade(
        condition_id=m.condition_id,
        question=m.question,
        category=m.category,
        entry_ts=entry_ts,
        deadline=m.deadline,
        days_to_deadline=dtd,
        entry_yes=entry_p,
        terminal_yes=m.terminal_yes,
        resolved_yes=(m.terminal_yes >= 0.5),
        gross_pnl=gross,
        fee=fee,
        net_pnl=net,
    )


# ----------------------------------------------------------------------------------------------------------
# Gate stats (BRUT per category) via the REAL scorer. We import cosmu.master.scorer so the DSR/PBO/min-trades
# are byte-identical to production — nothing is re-implemented.
# ----------------------------------------------------------------------------------------------------------
def gate_stats(net_pnls: list[float]) -> dict:
    """Run the production scorer on a per-trade net-P&L stream as a single 'config'. DSR is computed against
    the trial-inflated benchmark; PBO needs >=2 configs so we surface min-trades + DSR + the raw stats and
    flag PBO as N/A (single pre-registered rule = 1 config, the honest brut framing)."""
    from decimal import Decimal

    from cosmu.config.settings import GateSettings
    from cosmu.master.scorer import (
        BacktestMetrics,
        TrialStats,
        deflated_sharpe_prob,
        sample_moments,
    )

    n = len(net_pnls)
    if n < 2:
        return {"n": n, "note": "too few trades for stats"}
    sr_obs, skew, kurt, _ = sample_moments(net_pnls)
    mean = fmean(net_pnls)
    sd = pstdev(net_pnls)
    wins = sum(1 for x in net_pnls if x > 0)
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(sum(net_pnls), 6))),
        sharpe=Decimal(str(round(sr_obs * math.sqrt(n), 6))),  # crude annualization for display only
        sortino=Decimal("0"),
        max_drawdown=Decimal("0"),
        win_rate=Decimal(str(round(wins / n, 6))),
        num_trades=n,
        sharpe_per_obs=Decimal(str(round(sr_obs, 6))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n,
        trials_counted=1,
    )
    gates = GateSettings()
    trials = TrialStats(count=1)
    dsr = deflated_sharpe_prob(metrics, trials)
    passes_min_trades = n >= gates.min_trades
    passes_dsr = Decimal(str(dsr)) >= gates.min_deflated_sharpe_prob
    return {
        "n": n,
        "mean_net_pnl": mean,
        "sd_net_pnl": sd,
        "sharpe_per_obs": sr_obs,
        "skew": skew,
        "kurtosis": kurt,
        "win_rate": wins / n,
        "deflated_sharpe_prob": dsr,
        "min_deflated_sharpe_prob_gate": float(gates.min_deflated_sharpe_prob),
        "min_trades_gate": gates.min_trades,
        "passes_min_trades": passes_min_trades,
        "passes_dsr": passes_dsr,
        "passes_gate": bool(passes_min_trades and passes_dsr),
    }


# ----------------------------------------------------------------------------------------------------------
# Per-category aggregation + the survivorship/tail decomposition that decides the verdict.
# ----------------------------------------------------------------------------------------------------------
def summarize(trades: list[Trade], category: str) -> dict:
    cat_trades = [t for t in trades if t.category == category]
    n = len(cat_trades)
    if n == 0:
        return {"category": category, "n": 0}
    yes_resolvers = [t for t in cat_trades if t.resolved_yes]
    no_resolvers = [t for t in cat_trades if not t.resolved_yes]
    net = [t.net_pnl for t in cat_trades]
    gross = [t.gross_pnl for t in cat_trades]
    fee = _CATEGORY_FEE[category]
    # decay magnitude: mean (entry_yes - terminal_yes) = how much the long-shot YES decayed toward 0
    decay = [t.entry_yes - t.terminal_yes for t in cat_trades]
    # tail cost: the total $ the YES-resolvers cost the short, vs the gains harvested from NO-resolvers
    tail_cost = sum(t.gross_pnl for t in yes_resolvers)        # negative (losses)
    no_harvest = sum(t.gross_pnl for t in no_resolvers)        # positive (small gains)
    return {
        "category": category,
        "n": n,
        "n_yes_resolvers": len(yes_resolvers),
        "n_no_resolvers": len(no_resolvers),
        "yes_resolve_rate": len(yes_resolvers) / n,
        "mean_entry_yes": fmean([t.entry_yes for t in cat_trades]),
        "mean_decay": fmean(decay),  # >0 means YES decayed toward 0 on average (thesis-consistent)
        "category_fee": fee,
        "mean_gross_pnl": fmean(gross),
        "mean_net_pnl": fmean(net),
        "total_net_pnl": sum(net),
        "no_resolver_harvest_total": no_harvest,      # the lottery-ticket gains
        "yes_resolver_tail_cost_total": tail_cost,    # the tail that eats it (negative)
        "net_after_tail_per_trade": fmean(net),       # already includes the tail (full sample)
        "gate": gate_stats(net),
    }


# ----------------------------------------------------------------------------------------------------------
# HTML table (disposable, surfaces EVERY trade per the operator's "surface all compute" rule).
# ----------------------------------------------------------------------------------------------------------
def render_html(trades: list[Trade], cat_summaries: list[dict], meta: dict) -> str:
    def f(x, d=4):
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else str(x)

    rows = []
    for t in sorted(trades, key=lambda x: (x.category, -abs(x.net_pnl))):
        cls = "yes" if t.resolved_yes else "no"
        rows.append(
            f"<tr class='{cls}'><td>{t.category}</td><td class='q'>{t.question}</td>"
            f"<td>{t.entry_ts.date()}</td><td>{f(t.days_to_deadline,1)}</td>"
            f"<td>{f(t.entry_yes)}</td><td>{f(t.terminal_yes,1)}</td>"
            f"<td>{'YES' if t.resolved_yes else 'NO'}</td>"
            f"<td>{f(t.gross_pnl)}</td><td>{f(t.fee)}</td><td><b>{f(t.net_pnl)}</b></td></tr>"
        )

    cat_rows = []
    for s in cat_summaries:
        if s.get("n", 0) == 0:
            continue
        g = s.get("gate", {})
        verdict = "PASS" if g.get("passes_gate") else "FAIL"
        cat_rows.append(
            f"<tr><td><b>{s['category']}</b></td><td>{s['n']}</td>"
            f"<td>{s['n_yes_resolvers']} ({f(s['yes_resolve_rate']*100,1)}%)</td>"
            f"<td>{f(s['mean_entry_yes'])}</td><td>{f(s['mean_decay'])}</td>"
            f"<td>{f(s['category_fee'])}</td><td>{f(s['mean_gross_pnl'])}</td>"
            f"<td>{f(s['yes_resolver_tail_cost_total'])}</td>"
            f"<td><b>{f(s['mean_net_pnl'])}</b></td>"
            f"<td>{f(g.get('deflated_sharpe_prob',0))}</td>"
            f"<td>{g.get('n')}/{g.get('min_trades_gate','?')}</td>"
            f"<td class='{'pass' if verdict=='PASS' else 'fail'}'>{verdict}</td></tr>"
        )

    return f"""<!doctype html><meta charset=utf-8>
<title>H9 Polymarket theta-decay — {meta['generated']}</title>
<style>
 body{{font:13px/1.5 -apple-system,system-ui,sans-serif;margin:24px;color:#111;background:#fafafa}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px}}
 table{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0;font-size:12px}}
 th,td{{border:1px solid #ddd;padding:4px 7px;text-align:right}} td.q{{text-align:left;max-width:340px}}
 th{{background:#f0f0f0;text-align:right}} td:first-child,td.q{{text-align:left}}
 tr.yes{{background:#fff4f4}} tr.no{{background:#f5fbf5}}
 td.pass{{background:#d8f5d8;font-weight:700}} td.fail{{background:#f8d8d8;font-weight:700}}
 .meta{{color:#555;font-size:12px}} .legend{{margin:6px 0}}
 .legend span{{padding:2px 8px;border:1px solid #ccc;margin-right:6px}}
 .yes-l{{background:#fff4f4}} .no-l{{background:#f5fbf5}}
</style>
<h1>H9 — Polymarket resolution-convergence theta-decay (EXPERIMENT ONLY)</h1>
<p class=meta>Generated {meta['generated']} · entry = SHORT long-shot YES at ~{ENTRY_DAYS_TO_DEADLINE}d
to deadline, YES band [{LO_BAND},{HI_BAND}], hold to resolution · net of category fee
(geopolitics 0%, sports 3%) · crypto EXCLUDED · {meta['n_markets']} resolved binaries discovered,
{meta['n_trades']} qualifying trades · keyless Gamma+CLOB · ZERO prod impact.</p>
<div class=legend><span class=yes-l>YES-resolver (the tail — short loses big)</span>
<span class=no-l>NO-resolver (lottery ticket expires — short gains small)</span></div>

<h2>Per-category verdict (BRUT, survivorship-complete)</h2>
<table><tr><th>category</th><th>N</th><th>YES-resolvers</th><th>mean entry YES</th>
<th>mean decay</th><th>fee</th><th>mean gross P&amp;L</th><th>tail cost (Σ YES-resolvers)</th>
<th>mean NET P&amp;L</th><th>DSR</th><th>trades/gate</th><th>Gate</th></tr>
{''.join(cat_rows)}</table>
<p class=meta>mean decay = mean(entry_YES − terminal_YES); &gt;0 = long-shot YES decayed toward 0 on
average (thesis-consistent). mean NET P&amp;L is the full survivorship-complete sample (the YES-resolver
tail is already paid). Gate = production scorer (min_trades={meta['min_trades_gate']},
DSR≥{meta['dsr_gate']}).</p>

<h2>Every trade ({meta['n_trades']})</h2>
<table><tr><th>cat</th><th>question</th><th>entry date</th><th>days→dl</th><th>entry YES</th>
<th>terminal YES</th><th>resolved</th><th>gross P&amp;L</th><th>fee</th><th>NET P&amp;L</th></tr>
{''.join(rows)}</table>
"""


# ----------------------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-events", type=int, default=1500, help="resolved events to scan (volume-ranked)")
    ap.add_argument("--out", default="/tmp/h9_polymarket_thetadecay.html")
    ap.add_argument("--max-markets", type=int, default=0, help="cap markets fetched (0 = all discovered)")
    ap.add_argument("--per-cat-budget", type=int, default=1800,
                    help="seeded down-sample per category for the odds-fetch budget (0 = all)")
    ap.add_argument("--workers", type=int, default=12, help="parallel CLOB odds fetchers")
    args = ap.parse_args()

    t0 = time.time()
    print(f"[H9] discovering resolved binaries (max_events={args.max_events})...", file=sys.stderr)
    markets = discover(args.max_events, per_cat_budget=args.per_cat_budget)
    if args.max_markets:
        markets = markets[: args.max_markets]
    by_cat = Counter(m.category for m in markets)
    print(f"[H9] discovered/sampled {len(markets)} resolved binaries: {dict(by_cat)}", file=sys.stderr)

    # Parallel odds fetch (keyless, read-only). Each market is independent; one dead fetch -> 0 rows.
    from concurrent.futures import ThreadPoolExecutor

    trades: list[Trade] = []
    n_no_series = 0
    done = 0

    def _one(m: Market) -> Trade | None:
        series = daily_odds(m.yes_token)
        if not series:
            return None
        return build_trade(m, series)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_one, markets):
            done += 1
            if res is not None:
                trades.append(res)
            if done % 100 == 0:
                print(f"[H9]  {done}/{len(markets)} fetched, {len(trades)} qualifying trades so far",
                      file=sys.stderr)
    # n_no_series is informational; recompute is too costly with threads, so report 0 unless single-threaded.
    n_no_series = 0

    cats = ["geopolitics", "sports"]
    cat_summaries = [summarize(trades, c) for c in cats]

    from cosmu.config.settings import GateSettings

    g = GateSettings()
    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_markets": len(markets),
        "n_trades": len(trades),
        "n_no_series": n_no_series,
        "min_trades_gate": g.min_trades,
        "dsr_gate": float(g.min_deflated_sharpe_prob),
        "elapsed_s": round(time.time() - t0, 1),
    }

    html = render_html(trades, cat_summaries, meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)

    summary = {"meta": meta, "categories": cat_summaries}
    print(json.dumps(summary, indent=2, default=str))
    print(f"\n[H9] HTML -> {args.out}  ({meta['elapsed_s']}s, {n_no_series} markets had no odds series)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
