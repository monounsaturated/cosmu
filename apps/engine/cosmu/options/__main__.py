# intent: the CLI seam for the Deribit options substrate — invoked by the (not-yet-deployed) Modal cron as
# `python -m cosmu.options poll` and by a human for an ad-hoc `scan`. Three subcommands:
#   poll  — one FORWARD poll across the configured currencies → append to the local JSONL sink (the hoard).
#   smoke — a parse-only DRY poll (no sink write): confirm the keyless API + parser are healthy. Used by the
#           one-shot verification in this PR; the prompt asks only for a short smoke, never a long hoard.
#   scan  — one forward poll (no write) then run the camper scanner + fillability and print the CONFIRMED
#           opportunities (and a count of the mirages filtered out). Propose-only — prints, never trades.
# Keyless and side-effect-free except for `poll` (which appends to disk). Safe to run anywhere with outbound HTTPS.

from __future__ import annotations

import argparse
import sys

from cosmu.options.campers import default_campers
from cosmu.options.deribit_client import DeribitClient
from cosmu.options.fillability import FillabilityModel
from cosmu.options.logger import DEFAULT_CURRENCIES, DeribitOptionsLogger
from cosmu.options.scanner import run_scan
from cosmu.options.sink import LocalJsonlSink


def _currencies(arg: str | None) -> tuple[str, ...]:
    if not arg:
        return DEFAULT_CURRENCIES
    return tuple(c.strip().upper() for c in arg.split(",") if c.strip())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cosmu.options", description="Deribit options substrate CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("poll", "smoke", "scan"):
        sp = sub.add_parser(name)
        sp.add_argument("--currencies", default=None, help="comma list, e.g. BTC,ETH (default BTC,ETH)")
        sp.add_argument("--max-books", type=int, default=25, help="per-currency order-book enrichments")
        if name == "poll":
            sp.add_argument("--root", default=".cosmu/deribit_options", help="local JSONL sink root")
        if name == "scan":
            sp.add_argument("--realized-vol", type=float, default=None, help="annualized RV %% for the VRP camper")
    args = p.parse_args(argv)
    currencies = _currencies(args.currencies)
    client = DeribitClient()

    if args.cmd == "poll":
        logger = DeribitOptionsLogger(client, LocalJsonlSink(args.root),
                                      currencies=currencies, max_books_per_currency=args.max_books)
        total = 0
        for r in logger.poll_once():
            total += r.n_written
            print(f"[poll] {r.currency}: {r.n_quotes} quotes, {r.n_enriched} enriched, {r.n_written} rows -> {args.root}")
        print(f"[poll] wrote {total} rows")
        return 0

    if args.cmd == "smoke":
        logger = DeribitOptionsLogger(client, None, currencies=currencies, max_books_per_currency=args.max_books)
        ok = True
        for r in logger.poll_once():
            two = len(r.snapshot.two_sided())
            print(f"[smoke] {r.currency}: index={r.snapshot.index_price} dvol={r.snapshot.dvol} "
                  f"quotes={r.n_quotes} two_sided={two} enriched={r.n_enriched}")
            ok = ok and r.n_quotes > 0
        return 0 if ok else 1

    # scan
    logger = DeribitOptionsLogger(client, None, currencies=currencies, max_books_per_currency=args.max_books)
    fill = FillabilityModel()
    ctx = {"realized_vol": args.realized_vol} if args.realized_vol is not None else None
    for r in logger.poll_once():
        opps = run_scan(r.snapshot, default_campers(), fill, context=ctx)
        confirmed = [o for o in opps if o.is_real]
        print(f"[scan] {r.currency}: {len(opps)} candidates, {len(confirmed)} CONFIRMED, "
              f"{len(opps) - len(confirmed)} mirages")
        for o in confirmed:
            v = o.verdict
            print(f"   ✅ {v.classification} {o.candidate.description} | maker ${v.maker_edge_usd:.2f}/u "
                  f"x{v.max_units:.2f} = ${v.capacity_usd:.2f} | {v.note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
