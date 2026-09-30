# intent: snapshot what the archived engine actually did, from its production database (Supabase Postgres),
#   into apps/web/lib/engine-stats.json — AGGREGATE COUNTS ONLY (no rows, no credentials). The landing page's
#   funnel and the READMEs quote this file, so every "how much was tested" number is reproducible.
# inputs: DATABASE_URL (env var, or the repo-root .env.local which is gitignored). Read-only session.
# usage: python3 scripts/landing/engine_stats.py
import collections
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2

ROOT = Path(__file__).parents[2]
OUT = ROOT / "apps/web/lib/engine-stats.json"

# The "costs ate the edge" example on the landing page, copied from a research report (not from the DB).
COST_EXAMPLE = {
    "label": "Crypto market-neutral momentum, rebalanced ~daily (4h bars)",
    "gross": 0.892,
    "net": -0.604,
    "trades": 6036,
    "source": "archive/docs/reports/edge-hunt-mktneutral-2026-06-25.md",
}
sys.path.insert(0, str(ROOT / "archive/apps/engine"))
from cosmu.strategy.taxonomy import derive_facets  # noqa: E402  (the engine's own classifier)


def database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for line in (ROOT / ".env.local").read_text().splitlines():
        m = re.match(r"^DATABASE_URL=(.*)$", line.strip())
        if m:
            return re.sub(r"\s+#.*$", "", m.group(1)).strip().strip('"').strip("'")
    sys.exit("DATABASE_URL not set")


def connect():
    u = urlsplit(database_url())  # drop Supabase-pooler-only query params libpq rejects
    qs = urlencode([(k, v) for k, v in parse_qsl(u.query) if k.lower() not in ("pgbouncer", "connection_limit")])
    con = psycopg2.connect(urlunsplit((u.scheme, u.netloc, u.path, qs, u.fragment)), connect_timeout=20)
    con.set_session(readonly=True, autocommit=True)
    return con


def main():
    cur = connect().cursor()
    cur.execute("set statement_timeout = '120s'")

    def one(sql):
        cur.execute(sql)
        return cur.fetchone()

    versions, first, last = one("select count(*), min(created_at), max(created_at) from strategy_versions")
    cur.execute("select status, count(*) from strategy_versions group by 1")
    status = dict(cur.fetchall())
    cells, markets, venues = one("select count(*), count(distinct symbol), count(distinct venue_id) from backtest_symbols")
    trades = one("select sum(num_trades) from backtests")[0]
    dead_ends = one("select count(*) from research_notes where kind = 'dead_end'")[0]
    alt_hot, alt_metrics, alt_providers = one("select count(*), count(distinct metric), count(distinct provider) from alt_data")
    lake_rows, lake_files = one("select sum(record_count), count(*) from ducklake_data_file where end_snapshot is null")
    fills = one("select count(*) from executions")[0]

    cur.execute("select id, spec, origin from strategy_versions")
    fam = collections.Counter()
    for _vid, spec, origin in cur.fetchall():
        fam[derive_facets(json.loads(spec) if isinstance(spec, str) else spec, origin).signal_family] += 1

    stats = {
        "as_of": date.today().isoformat(),
        "source": "archived engine production database (Supabase Postgres + DuckLake catalog for the R2 lake)",
        "window": [str(first)[:10], str(last)[:10]],
        "strategies_tested": versions,
        "survived_first_screen": status.get("screened", 0) + status.get("paper", 0),
        "paper_traded": status.get("paper", 0),
        "killed": status.get("killed", 0),
        "backtests": cells,  # one per strategy × market × venue
        "markets": markets,
        "venues": venues,
        "simulated_trades": int(trades or 0),
        "dead_ends_recorded": dead_ends,
        "paper_fills": fills,
        "data_points": int(alt_hot) + int(lake_rows or 0),
        "data_metrics": alt_metrics,
        "data_providers": alt_providers,
        "lake_files": lake_files,
        "strategies_by_signal_family": dict(fam.most_common()),
        "non_price_share": round(1 - fam.get("math_price", 0) / versions, 3),
        "cost_example": COST_EXAMPLE,
    }
    OUT.write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
