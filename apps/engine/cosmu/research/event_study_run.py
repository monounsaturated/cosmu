# intent: the RUNNABLE pre-registered EVENT-STUDY experiment (realtime-data-lane epic §4.3) — one CLI that
# loads a raw text corpus (JSONL), clusters it into root events, enriches typed fields (LLM if keyed, lexicon
# otherwise), joins cached intraday bars, runs the deterministic event-study harness, and prints + persists an
# honest machine-readable report. inputs: --corpus JSONL + a bar-cache dir (the `<symbol>_<tf>.json` layout
# every provider writes; Binance Vision 1m backfills land there) + the symbol universe; outputs: a per-cell
# verdict table on stdout, a JSON report file, and an `event_study_completed` audit event when a DB is
# reachable. invariants: OFFLINE-capable (cached bars + lexicon enrichment need no key and no network);
# deterministic for a fixed corpus+cache+seed; availability semantics are EXPLICIT (--availability
# publish-time | <ISO scrape time>) so a scraped archive can never silently backdate; an unpowered run prints
# INSUFFICIENT — it never manufactures a verdict. Heavy runs belong on Modal/local, never a Railway cron.
#
# Pre-registered experiment 1 (epic §4.3.1):
#   python3 -m cosmu.research.event_study_run --corpus gkg_majors.jsonl --availability publish-time \
#       --bars-dir .cosmu/market_data/binancevision --timeframe 1m --symbols BTCUSDT,ETHUSDT,SOLUSDT \
#       --out event_study_report.json

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from cosmu.ingest.bars import bar_cache_path, read_cached_bars
from cosmu.ingest.llm_formatter import enrich_market_events
from cosmu.research.event_corpus import cluster_root_events, events_from_jsonl
from cosmu.research.event_study import EventStudyConfig, run_event_study


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic event-study harness on a text corpus + cached intraday bars.")
    parser.add_argument("--corpus", required=True, help="JSONL corpus: one {ts, title, symbol|symbols, source?} per line")
    parser.add_argument("--provider", default="gdelt")
    parser.add_argument("--availability", required=True,
                        help='"publish-time" ONLY for true point-in-time feeds; an ISO datetime (the scrape time) for any archive')
    parser.add_argument("--bars-dir", required=True, help="bar-cache dir with <SYMBOL>_<tf>.json files")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--symbols", required=True, help="comma-separated universe incl. the market symbol")
    parser.add_argument("--market-symbol", default="BTCUSDT")
    parser.add_argument("--by-source", action="store_true", help="cells = (event_type, source) instead of event_type")
    parser.add_argument("--out", default=None, help="write the full JSON report here")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    availability = "publish-time" if args.availability == "publish-time" else datetime.fromisoformat(args.availability)
    events = events_from_jsonl(args.corpus, provider=args.provider, availability=availability)
    events = cluster_root_events(events)
    events = enrich_market_events(events)  # lexicon by default; pass a keyed formatter via code for LLM typing
    print(f"corpus: {len(events)} events loaded + clustered + enriched")

    bars_by_symbol = {}
    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        bars = read_cached_bars(bar_cache_path(args.bars_dir, symbol, args.timeframe))
        if bars:
            bars_by_symbol[symbol] = bars
        print(f"bars: {symbol} {args.timeframe} -> {len(bars)} cached")
    if args.market_symbol not in bars_by_symbol:
        print(f"FATAL: no cached bars for the market symbol {args.market_symbol} — backfill first "
              f"(python3 -m cosmu.data.binance_vision_backfill … --timeframes {args.timeframe})")
        return 2

    cfg = EventStudyConfig(market_symbol=args.market_symbol, seed=args.seed)
    cell_of = (lambda e: (e.event_type or "all", e.source or "unknown")) if args.by_source else None
    report = run_event_study(events, bars_by_symbol, cfg, **({"cell_of": cell_of} if cell_of else {}))

    print(f"\nEVENT STUDY — {report.n_roots_studied} root events studied (of {report.n_events_in} in)")
    print(f"{'cell':40} {'n_clean':>7} {'mean SCAR@' + str(cfg.primary_window):>14} {'RI p':>8} {'pre p':>8} {'leak':>5} verdict")
    for c in report.cells:
        scar = c.mean_scar.get(cfg.primary_window)
        print(f"{'/'.join(c.key):40} {c.n_clean:>7} {(f'{scar:+.3f}' if scar is not None else '—'):>14} "
              f"{(f'{c.ri_pvalue:.3f}' if c.ri_pvalue is not None else '—'):>8} "
              f"{(f'{c.pre_pvalue:.3f}' if c.pre_pvalue is not None else '—'):>8} "
              f"{('YES' if c.leakage_flag else 'no'):>5} {c.verdict.upper()}")

    if args.out:
        payload = {
            "config": asdict(report.config), "n_events_in": report.n_events_in,
            "n_roots_studied": report.n_roots_studied,
            "cells": [
                {"key": list(c.key), "n_total": c.n_total, "n_skipped": c.n_skipped,
                 "n_confounded": c.n_confounded, "n_comove": c.n_comove, "n_clean": c.n_clean,
                 "mean_scar": {str(k): v for k, v in c.mean_scar.items()}, "mean_pre_scar": c.mean_pre_scar,
                 "ri_pvalue": c.ri_pvalue, "pre_pvalue": c.pre_pvalue, "leakage_flag": c.leakage_flag,
                 "fdr_pass": c.fdr_pass, "verdict": c.verdict}
                for c in report.cells
            ],
        }
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"\nreport written: {args.out}")

    # Best-effort audit trail — a DB-less offline run still completes (the printed report is the output).
    try:
        from cosmu.config.settings import Settings
        from cosmu.knowledge.store import Store

        Store(Settings()).append_event(
            actor="research", kind="event_study_completed", ref_type="event_study", ref_id=args.provider,
            payload={"roots": report.n_roots_studied,
                     "cells": {"pass": sum(1 for c in report.cells if c.verdict == "pass"),
                               "fail": sum(1 for c in report.cells if c.verdict == "fail"),
                               "insufficient": sum(1 for c in report.cells if c.verdict == "insufficient")}},
        )
    except Exception:  # noqa: BLE001 — offline run: stdout/JSON report is the deliverable
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
