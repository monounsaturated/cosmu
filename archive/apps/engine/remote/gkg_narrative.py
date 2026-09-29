# intent: the Modal HEAVY/PARALLEL lane for the LLM-NARRATIVE axis — get the axis a DEEP raw-text corpus and a
# REAL verdict, off the M2. Three stages, all writing to ONE persistent Modal Volume so each is resumable and the
# (paid-once) LLM cache survives between runs:
#   (1) corpus   — .map() across the GKG 15-min file URLs for a date range; each worker downloads + filters one
#                  file to the liquid universe and returns per-asset PIT headlines. Collected to corpus JSONL.
#   (2) score    — LLM-score each UNIQUE headline content-only/PIT via OpenRouter gpt-4o-mini, content-hash
#                  cached on the Volume (so the bill is paid ONCE; reruns are free), aggregate to a daily PIT
#                  'net narrative pressure' per asset (available_at = day+1). Daily scores written to JSONL.
#   (3) verdict  — load the deep daily scores and run the UNCHANGED merged harness (research.llm_narrative_cohort.
#                  run_cohort): promote_cohort BH-FDR on a REAL purged+embargoed holdout + PIT fees, with the
#                  time-shuffle placebo + momentum-only control disconfirmers. The verdict comes ONLY from that
#                  honest path (never gate.evaluate_cross_asset_ablation).
#
# inputs: the "cosmu-engine" Modal Secret (OPENROUTER_API_KEY for scoring; DATABASE_URL unused by the verdict —
#         it runs against a fresh tempfile store like the local harness). outputs: corpus + daily-score JSONL on
#         the Volume, and a printed honest verdict per asset. invariants: NO order ever fires; the LLM is ONLY at
#         ingest standardizing text (content-only prompt, never the outcome); every item is PIT-stamped at GDELT's
#         index time; available_at = day+1; the time-shuffle disconfirmer is the empirical leak check. COST: each
#         unique headline costs ~$5e-5 once; corpus dedupes hard; stay WELL under the $15 Modal+LLM budget — the
#         actual spend is reported by the score stage (scorer.cost_usd + scorer.calls).

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import modal

ENGINE_DIR = Path(__file__).resolve().parent.parent

app = modal.App("cosmu-gkg-narrative")

# Same build contract as remote/app.py: copy the engine tree, pip install it so `cosmu` is importable.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("certifi>=2024.8")
    .add_local_dir(
        str(ENGINE_DIR),
        remote_path="/root/engine",
        copy=True,
        ignore=["**/__pycache__", "**/*.pyc", "tests/**", "remote/**", ".cosmu/**"],
    )
    .run_commands("pip install /root/engine")
)

engine_secret = modal.Secret.from_name("cosmu-engine")

# ONE persistent volume holds: the deduped corpus JSONL, the content-hash LLM score cache, and the daily-score
# JSONL. Surviving between runs makes every stage resumable and means the LLM bill is paid exactly once.
vol = modal.Volume.from_name("cosmu-gkg-narrative", create_if_missing=True)
VOL_ROOT = "/data"
CORPUS_DIR = f"{VOL_ROOT}/corpus"
CACHE_DIR = f"{VOL_ROOT}/llm_cache"
SCORES_DIR = f"{VOL_ROOT}/daily_scores"


def _ensure_engine_on_path() -> None:
    import sys

    if "/root/engine" not in sys.path:
        sys.path.insert(0, "/root/engine")


# --------------------------------------------------------------------------- stage 1: parallel corpus build


@app.function(image=image, timeout=60 * 10, retries=2, max_containers=40)
def _fetch_and_filter(url: str) -> dict[str, list[dict]]:
    """One worker = one GKG 15-min file: download + filter to the liquid universe. Returns {symbol: [{ts,headline}]}
    (JSON-able). A dead/missing slice returns {} (honest absence — GDELT has gaps)."""
    _ensure_engine_on_path()
    from cosmu.research.gkg_corpus import DEFAULT_UNIVERSE, fetch_gkg_file, parse_gkg_bytes

    raw = fetch_gkg_file(url)
    if raw is None:
        return {}
    parsed = parse_gkg_bytes(raw, DEFAULT_UNIVERSE)
    return {
        sym: [{"ts": it.ts.isoformat(), "headline": it.headline} for it in items]
        for sym, items in parsed.items()
    }


@app.function(image=image, volumes={VOL_ROOT: vol}, timeout=60 * 60 * 2)
def build_corpus(start: str, end: str, per_day: int = 24) -> dict:
    """Map across all GKG file URLs in [start, end] (ISO dates), collect per-asset PIT headlines, write the
    DEDUPED corpus to the Volume as one JSONL per symbol. Returns a depth summary (#items, span, #assets)."""
    _ensure_engine_on_path()
    from cosmu.research.gkg_corpus import DEFAULT_UNIVERSE, gkg_file_urls

    s = _dt.date.fromisoformat(start)
    e = _dt.date.fromisoformat(end)
    urls = gkg_file_urls(s, e, per_day=per_day)
    print(f"[corpus] {start}..{end} per_day={per_day} -> {len(urls)} GKG files to map", flush=True)

    by_symbol: dict[str, dict[tuple[str, str], dict]] = {a.symbol: {} for a in DEFAULT_UNIVERSE}
    done = 0
    # Stream results as workers finish; dedupe globally by (ts, headline) per symbol.
    for partial in _fetch_and_filter.map(urls, order_outputs=False, return_exceptions=True):
        done += 1
        if isinstance(partial, Exception) or not partial:
            continue
        for sym, items in partial.items():
            bucket = by_symbol.setdefault(sym, {})
            for it in items:
                bucket[(it["ts"], it["headline"])] = it
        if done % 200 == 0:
            tot = sum(len(b) for b in by_symbol.values())
            print(f"[corpus] {done}/{len(urls)} files; {tot} unique items so far", flush=True)

    Path(CORPUS_DIR).mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    total_items = 0
    spans: list[str] = []
    for sym, bucket in by_symbol.items():
        items = sorted(bucket.values(), key=lambda d: d["ts"])
        if not items:
            continue
        path = Path(CORPUS_DIR) / f"{sym}.jsonl"
        with path.open("w") as fh:
            for it in items:
                fh.write(json.dumps(it) + "\n")
        total_items += len(items)
        span = f"{items[0]['ts'][:10]}..{items[-1]['ts'][:10]}"
        spans.append(span)
        summary[sym] = {"items": len(items), "span": span}
    vol.commit()

    out = {
        "range": f"{start}..{end}",
        "per_day": per_day,
        "files_mapped": len(urls),
        "assets_with_data": len(summary),
        "total_items": total_items,
        "per_asset": summary,
    }
    print(f"[corpus] DONE: {total_items} items across {len(summary)} assets", flush=True)
    for sym, info in sorted(summary.items(), key=lambda kv: -kv[1]["items"]):
        print(f"  {sym:8} items={info['items']:6} span={info['span']}", flush=True)
    return out


# --------------------------------------------------------------------------- stage 2: LLM score -> daily PIT

# OpenRouter gpt-4o-mini scoring is network-bound (one tiny request per UNIQUE headline). Two layers of
# parallelism keep wall-clock + cost tractable on a deep corpus: (a) ONE container per asset (`.map`), (b)
# inside a container, a thread pool issues many requests concurrently (the scorer is content-hash disk-cached
# on the shared Volume, so the bill is paid once and concurrent dupes collapse to a single write). Determinism
# is preserved: temperature 0 + the cache key is the content hash, so order of completion never changes a score.
_SCORE_THREADS = 16


@app.function(image=image, volumes={VOL_ROOT: vol}, secrets=[engine_secret], timeout=60 * 60 * 4, cpu=2.0)
def _score_one_asset(symbol: str) -> dict:
    """Score ONE asset's corpus content-only/PIT → daily 'net narrative pressure' series. Concurrent scoring
    (thread pool, I/O-bound) over the UNIQUE headlines; the per-day aggregation is recomputed deterministically
    afterwards from the now-warm cache. Writes the daily scores JSONL for `symbol`."""
    _ensure_engine_on_path()
    from concurrent.futures import ThreadPoolExecutor

    from cosmu.data.altdata import NewsItem
    from cosmu.research.llm_narrative_pipeline import (
        CachedNarrativeScorer,
        score_headlines_to_daily,
    )

    src = Path(CORPUS_DIR) / f"{symbol}.jsonl"
    if not src.exists():
        return {"symbol": symbol, "headlines": 0, "daily_points": 0, "live_calls": 0, "cost_usd": 0.0}

    items: list[NewsItem] = []
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        ts = _dt.datetime.fromisoformat(d["ts"])
        items.append(NewsItem(ts=ts, available_at=ts, headline=d["headline"]))

    scorer = CachedNarrativeScorer(cache_dir=CACHE_DIR)
    if not scorer.api_key:
        raise SystemExit("OPENROUTER_API_KEY missing from cosmu-engine secret — cannot score")

    # Warm the cache concurrently over UNIQUE headlines (dedupe so a repeated headline is scored once).
    uniq = list({it.headline for it in items})
    print(f"[score:{symbol}] {len(items)} items, {len(uniq)} unique headlines — warming cache ({_SCORE_THREADS} threads)…", flush=True)
    with ThreadPoolExecutor(max_workers=_SCORE_THREADS) as pool:
        for _ in pool.map(scorer, uniq):
            pass
    vol.commit()  # persist paid scores before aggregation

    # Deterministic per-day aggregation reads straight from the now-warm cache (no new calls).
    points = score_headlines_to_daily(items, scorer)
    out = Path(SCORES_DIR) / f"{symbol}.jsonl"
    Path(SCORES_DIR).mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for p in points:
            fh.write(json.dumps({"ts": p.ts.isoformat(), "available_at": p.available_at.isoformat(), "value": p.value}) + "\n")
    vol.commit()
    print(f"[score:{symbol}] {len(points)} daily points; {scorer.calls} live calls; cost ${scorer.cost_usd:.4f}", flush=True)
    return {"symbol": symbol, "headlines": len(items), "daily_points": len(points),
            "live_calls": scorer.calls, "cost_usd": round(scorer.cost_usd, 6)}


@app.function(image=image, volumes={VOL_ROOT: vol}, secrets=[engine_secret], timeout=60 * 60 * 5)
def score_corpus(symbols: list[str] | None = None) -> dict:
    """Fan out one scoring container per asset (parallel), collect the per-asset summaries, and report the ACTUAL
    LLM spend (the number to report) = sum of live-call cost across assets. Cache on the Volume → reruns are free."""
    corpus = Path(CORPUS_DIR)
    if not corpus.exists():
        raise SystemExit("no corpus on volume — run build_corpus first")
    targets = symbols or [p.stem for p in sorted(corpus.glob("*.jsonl"))]
    print(f"[score] fanning out {len(targets)} assets: {targets}", flush=True)

    per_asset: dict[str, dict] = {}
    total_calls = 0
    total_cost = 0.0
    for r in _score_one_asset.map(targets, order_outputs=False, return_exceptions=True):
        if isinstance(r, Exception):
            print(f"[score] asset failed: {r}", flush=True)
            continue
        per_asset[r["symbol"]] = {"headlines": r["headlines"], "daily_points": r["daily_points"]}
        total_calls += r["live_calls"]
        total_cost += r["cost_usd"]

    summary = {
        "assets_scored": len(per_asset),
        "live_llm_calls": total_calls,
        "llm_cost_usd": round(total_cost, 6),
        "per_asset": per_asset,
    }
    print(f"[score] DONE: {total_calls} live LLM calls, cost ${total_cost:.4f}", flush=True)
    return summary


# --------------------------------------------------------------------------- stage 3: the honest verdict


def _load_daily_points(symbol: str):
    from cosmu.data.altdata import AltDataPoint

    path = Path(SCORES_DIR) / f"{symbol}.jsonl"
    if not path.exists():
        return []
    pts = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        pts.append(
            AltDataPoint(
                ts=_dt.datetime.fromisoformat(d["ts"]),
                available_at=_dt.datetime.fromisoformat(d["available_at"]),
                value=float(d["value"]),
            )
        )
    return sorted(pts, key=lambda p: p.ts)


def _bars_for(symbol: str, kind: str, limit: int = 1400):
    """Daily bars for the verdict: Binance spot for crypto, Stooq (free, keyless) for equities/ETFs."""
    if kind == "crypto":
        from cosmu.data.market import BinanceSpotOHLCVProvider

        return BinanceSpotOHLCVProvider().fetch_bars(symbol, "1d", limit=limit)
    from cosmu.data.market import StooqDailyBarsProvider

    return StooqDailyBarsProvider().fetch_bars(symbol, "1d", limit=limit)


@app.function(image=image, volumes={VOL_ROOT: vol}, secrets=[engine_secret], timeout=60 * 60)
def verdict(symbols: list[str] | None = None) -> dict:
    """Run the UNCHANGED merged harness (run_cohort) per asset on the DEEP daily scores. Real purged+embargoed
    holdout, promote_cohort BH-FDR, time-shuffle placebo + momentum control. Returns the honest verdict per asset."""
    _ensure_engine_on_path()
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.research.gkg_corpus import DEFAULT_UNIVERSE
    from cosmu.research.llm_narrative_cohort import run_cohort

    kind_of = {a.symbol: a.kind for a in DEFAULT_UNIVERSE}
    targets = symbols or [a.symbol for a in DEFAULT_UNIVERSE]

    verdicts: dict[str, dict] = {}
    for sym in targets:
        points = _load_daily_points(sym)
        if not points:
            verdicts[sym] = {"verdict": "NO-SCORES", "note": "no daily scores on volume for this symbol"}
            continue
        bars = _bars_for(sym, kind_of.get(sym, "equity"))
        if len(bars) < 80:
            verdicts[sym] = {"verdict": "NO-BARS", "note": f"only {len(bars)} bars from provider"}
            continue
        market = {sym: bars}
        tmp = tempfile.mkdtemp(prefix="cosmu-gkg-")
        store = Store(Settings(database_url=f"sqlite:///{tmp}/v.sqlite3", openrouter_api_key=None))
        rep = run_cohort(market, points, store, symbol=sym, data_source="gdelt-gkg+openrouter")
        verdicts[sym] = {
            "verdict": rep.verdict,
            "headline": rep.headline,
            "window": rep.window,
            "narrative_days": rep.narrative_points,
            "disconfirmers": rep.disconfirmers,
            "members": [
                {
                    "name": m.name, "net": m.net_return, "dsr": m.deflated_sharpe_prob,
                    "holdout_dsr": m.holdout_deflated_sharpe, "trades": m.num_trades,
                    "promoted": m.promoted, "survived_fdr": m.survived_fdr,
                }
                for m in rep.members
            ],
            "notes": rep.notes,
        }
        print(f"[verdict] {sym}: {rep.verdict} — {rep.headline}", flush=True)
        for m in rep.members:
            flag = "PROMOTED" if m.promoted else ("fdr" if m.survived_fdr else "stop")
            print(f"    [{flag:>8}] {m.name:<30} net={m.net_return:+.4f} dsr={m.deflated_sharpe_prob:.3f} "
                  f"holdoutDSR={m.holdout_deflated_sharpe:+.3f} trades={m.num_trades}", flush=True)
        for k, v in rep.disconfirmers.items():
            print(f"      {k}: {v}", flush=True)
    return verdicts


# --------------------------------------------------------------------------- driver


@app.local_entrypoint()
def main(
    stage: str = "all",
    start: str = "2023-01-01",
    end: str = "",
    per_day: int = 24,
    symbols: str = "",
) -> None:
    """`modal run apps/engine/remote/gkg_narrative.py --stage [corpus|score|verdict|all] --start 2023-01-01 [--end ...] [--per-day 24] [--symbols BTCUSDT,ETHUSDT]`.

    all = corpus → score → verdict end-to-end. Defaults: 2023-01-01..today, hourly (24/day) subsample, full
    universe. The corpus + LLM cache persist on the cosmu-gkg-narrative volume, so re-running `score`/`verdict`
    is free (no re-download, no re-billing)."""
    end = end or _dt.date.today().isoformat()
    syms = [s.strip() for s in symbols.split(",") if s.strip()] or None

    if stage in ("corpus", "all"):
        print(f"=== STAGE 1: corpus {start}..{end} (per_day={per_day}) ===")
        cs = build_corpus.remote(start, end, per_day)
        print(json.dumps(cs, indent=2))
    if stage in ("score", "all"):
        print("=== STAGE 2: LLM score -> daily PIT ===")
        ss = score_corpus.remote(syms)
        print(json.dumps(ss, indent=2))
    if stage in ("verdict", "all"):
        print("=== STAGE 3: honest verdict ===")
        vs = verdict.remote(syms)
        print(json.dumps(vs, indent=2))
