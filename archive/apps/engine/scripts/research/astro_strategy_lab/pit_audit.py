#!/usr/bin/env python3
# intent: POINT-IN-TIME honesty audit of the REAL alt-data signals — the question that decides whether ANY edge is
# tradeable LIVE or just a look-ahead mirage off back-filled / revised metrics. For each metric we read the prod
# alt_data (READ-ONLY) and check three tells:
#   (1) availability lag  = available_at − ts. ~0 means "claims known at observation instant"; >0 means honestly
#       lagged. A metric that is actually published late but stamped available_at==ts is LOOK-AHEAD.
#   (2) backfill          = was the row ingested_at AROUND when it became available (live capture over time) or all
#       at once RECENTLY (history scraped after the fact)? Recent-bulk ingest of an old series = we did NOT have those
#       values live; if the source also revises, the stored value ≠ what was tradeable then.
#   (3) revisions         = same (symbol, ts) with >1 distinct available_at and/or >1 distinct value = the source
#       rewrote history. Honest only if each revision carries its own LATER available_at (so read_asof hides the future
#       value); a revision that shares available_at==ts is silent look-ahead.
# Verdict per metric: TRADEABLE-LIVE / LAGGED-OK / SUSPECT(reason). Read-only; writes a report + R2 manifest.

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))

METRICS = ["fear_greed", "funding_rate", "galaxy_score", "social_volume", "social_sentiment",
           "vix_level", "dxy", "fed_funds_rate", "btc_hashrate", "btc_active_addresses", "defi_tvl"]


def dsn() -> str:
    p = urlsplit(os.environ["DATABASE_URL"])
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in ("pgbouncer", "connection_limit")]
    if not any(k == "sslmode" for k, _ in q):
        q.append(("sslmode", "require"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def main() -> None:
    import psycopg2

    conn = psycopg2.connect(dsn(), connect_timeout=25)
    conn.set_session(readonly=True)
    cur = conn.cursor()
    rows = []
    for m in METRICS:
        cur.execute(
            """
            WITH d AS (
              SELECT symbol, ts::timestamptz ts, available_at::timestamptz aa, value,
                     ingested_at::timestamptz ing
              FROM alt_data WHERE metric = %s
            )
            SELECT
              count(*) n,
              min(ts)::date, max(ts)::date,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (aa - ts))/86400.0) lag_med_d,
              max(EXTRACT(EPOCH FROM (aa - ts))/86400.0) lag_max_d,
              min(ing)::date, max(ing)::date,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (ing - aa))/86400.0) ingest_lag_med_d
            FROM d
            """, (m,))
        n, ts0, ts1, lagmed, lagmax, ing0, ing1, inglag = cur.fetchone()
        if not n:
            rows.append(dict(metric=m, n=0, verdict="NO DATA"))
            continue
        # revisions: (symbol, ts) groups with >1 distinct available_at or value
        cur.execute(
            """
            SELECT count(*) FROM (
              SELECT symbol, ts FROM alt_data WHERE metric=%s
              GROUP BY symbol, ts HAVING count(DISTINCT available_at) > 1
            ) t
            """, (m,))
        rev_aa = cur.fetchone()[0]
        cur.execute(
            """
            SELECT count(*) FROM (
              SELECT symbol, ts FROM alt_data WHERE metric=%s
              GROUP BY symbol, ts HAVING count(DISTINCT value) > 1
            ) t
            """, (m,))
        rev_val = cur.fetchone()[0]
        lagmed = float(lagmed or 0); inglag = float(inglag or 0)
        # verdict logic
        backfilled = inglag > 30  # rows written >30d after they were "available" → not captured live
        instant = abs(lagmed) < 0.25  # available_at ≈ ts
        revises = rev_val > 0
        if revises and instant:
            verdict = "SUSPECT — revised AND stamped instant (silent look-ahead)"
        elif backfilled and revises:
            verdict = "SUSPECT — backfilled history + source revises (stored ≠ live value)"
        elif backfilled:
            verdict = "REVIEW — history backfilled (values may differ from what was live; ok if source never revises)"
        elif instant and m not in ("funding_rate",):
            verdict = "REVIEW — stamped available_at≈ts; confirm the source truly publishes with no lag"
        elif lagmed >= 0.5:
            verdict = f"LAGGED-OK — honest ~{lagmed:.1f}d publication lag"
        else:
            verdict = "TRADEABLE-LIVE — settlement value known at ts (funding-type)"
        rows.append(dict(metric=m, n=n, ts=f"{ts0}..{ts1}", lag_med_d=round(lagmed, 2),
                         lag_max_d=round(float(lagmax or 0), 1), ingest_span=f"{ing0}..{ing1}",
                         ingest_lag_med_d=round(inglag, 1), rev_ts_aa=rev_aa, rev_ts_val=rev_val, verdict=verdict))
    cur.close(); conn.close()
    report(rows)


def report(rows) -> None:
    import pandas as pd

    from lab_store import LabStore

    df = pd.DataFrame(rows)
    out = Path(ENGINE_ROOT.parent.parent / "docs/research/alt_data_pit_audit.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    L = ["# Point-in-time honesty audit — are the REAL signals tradeable live?\n",
         "_For each real alt-data metric in prod `alt_data` (READ-ONLY): availability lag (available_at−ts), whether "
         "history was back-filled (ingested long after it was 'available'), and whether the source revised "
         "(same ts → multiple available_at / value). This decides whether a backtest edge could actually be traded "
         "live or is a look-ahead mirage. `pit_audit.py`._\n",
         df.to_markdown(index=False),
         "\n## How to read it\n",
         "- **TRADEABLE-LIVE / LAGGED-OK** — available_at is honest (settlement value, or a real publication lag); a "
         "backtest using read_asof would only ever see values knowable at the bar. Safe to trade.\n"
         "- **REVIEW** — either back-filled history (we didn't capture it live, so trust it only if the source NEVER "
         "revises) or stamped available_at≈ts (confirm the publisher truly has zero lag).\n"
         "- **SUSPECT** — revised history AND/OR instant-stamp = silent look-ahead. An edge built on these is NOT "
         "tradeable live; the backtest saw values that didn't exist yet. Do NOT trade on these without fixing the "
         "available_at stamping (LunarCrush social is the classic offender — vendor backfills/revises).\n",
         "\n_Funding is settlement-stamped (available_at==ts is CORRECT). fear_greed/FRED should carry a +1d/release "
         "lag. LunarCrush social is the one to scrutinize — if it shows instant-stamp + revisions, the social edge in "
         "the composite is partly look-ahead and must be discounted._\n"]
    out.write_text("\n".join(str(x) for x in L) + "\n")
    try:
        LabStore().save_batch(df, "audits/pit_audit")
    except Exception:  # noqa: BLE001
        pass
    print(df.to_string(index=False))
    print(f"\nDONE → {out}")


if __name__ == "__main__":
    main()
