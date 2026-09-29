#!/usr/bin/env python3
# intent: organize the astro_lab R2 lake (db best practices) — write a MANIFEST describing every experiment prefix
# (what it is, schema, row count, the one-line finding) and a curated FINDINGS table of the best/interesting results,
# all as Parquet under r2://<bucket>/astro_lab/ so it is DuckDB-queryable, easy to learn from, and trivially
# droppable (one prefix per experiment). Prints the exact DuckDB dump/query one-liners. Idempotent.

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from lab_store import LabStore  # noqa: E402

# curated findings — the distilled "best/interesting stuff" worth learning from (not raw trials)
FINDINGS = [
    dict(experiment="strategy_lab", prefix="astro_lab/run_*/", finding="152,166 astro strategy trials (5 schools × 35 assets × 6 segments)",
         headline="raw best Sharpe 1.85 → 0 survive Deflated-Sharpe at the true trial count", verdict="NO EDGE", tradeable=False),
    dict(experiment="deep_study", prefix="(docs) astro_vs_markets_deep", finding="126 astro features vs 13.6M-row real alt panel; incremental test",
         headline="astro DEGRADES OOS AUC on top of real signals (-0.015/-0.042, p=1.0)", verdict="NO EDGE (negative)", tradeable=False),
    dict(experiment="composite", prefix="astro_lab/composite/", finding="multi-signal composite (astro+events+real+spaceweather+natal), train/test",
         headline="train→OOS ranking INVERTS (best-train=worst-OOS); astro dilutes the faint real edge", verdict="NO EDGE", tradeable=False),
    dict(experiment="event_study", prefix="astro_lab/event_study/", finding="vol/turnover in ±3d windows around named astro events vs fake-date null",
         headline="apparent full-moon/eclipse realized-VOL effect (3/76 survive BH-FDR) — CANDIDATE", verdict="CANDIDATE→KILLED", tradeable=False),
    dict(experiment="lunar_vol", prefix="astro_lab/lunar_vol/", finding="decisive phase-shuffle null on the lunar-vol candidate",
         headline="phase-shuffle p=0.33, flat profile, outlier-driven → the candidate is an artifact", verdict="ARTIFACT (no edge)", tradeable=False),
    dict(experiment="pit_audit", prefix="astro_lab/audits/", finding="point-in-time honesty of the REAL signals (available_at / backfill / revisions)",
         headline="which real signals are tradeable-live vs look-ahead (see alt_data_pit_audit.md)", verdict="SEE AUDIT", tradeable=None),
]

LESSONS = [
    "Expected best raw Sharpe under noise ≈ sqrt(2·ln N)/sqrt(T); Deflated Sharpe charges exactly that — more configs deflate HARDER, never 'find' an edge.",
    "Train-IC ranking that does NOT predict OOS-Sharpe ranking is the fingerprint of noise/decay, not structure.",
    "A fake-RANDOM-date placebo is too weak for autocorrelated metrics (vol); the proper null is a LABEL/PHASE-SHUFFLE that preserves the series.",
    "Astro is broadcast-identically across assets → cross-sectional needs a per-asset construction (natal); even that carried nothing.",
    "Pure astro (planets/aspects/lunar/eclipse/natal) is dead; the only faint signal is wider NON-astro (calendar turn-of-month, real macro/sentiment) and it decays OOS.",
]


def main() -> None:
    store = LabStore()
    if not store.r2_ready:
        print("R2 not configured — nothing to organize"); return
    con = store._conn()

    # inventory every parquet under astro_lab/ → prefix, files, rows, columns
    inv = []
    try:
        files = con.execute(
            f"SELECT file FROM glob('r2://{store.bucket}/{store.prefix}/**/*.parquet')"
        ).df()["file"].tolist()
    except Exception:
        files = []
    by_prefix: dict[str, list[str]] = {}
    for f in files:
        rel = f.split(f"{store.prefix}/", 1)[-1]
        pref = rel.split("/")[0] if "/" in rel else rel
        by_prefix.setdefault(pref, []).append(f)
    for pref, fs in sorted(by_prefix.items()):
        try:
            n = con.execute(f"SELECT count(*) FROM read_parquet({fs!r})").fetchone()[0]
            cols = con.execute(f"SELECT * FROM read_parquet({fs[0]!r}) LIMIT 0").df().columns.tolist()
        except Exception:
            n, cols = -1, []
        inv.append(dict(prefix=f"{store.prefix}/{pref}/", n_files=len(fs), n_rows=int(n), columns=", ".join(cols)))
    inv_df = pd.DataFrame(inv)
    find_df = pd.DataFrame(FINDINGS)

    # write the manifest + findings as Parquet (queryable) — top-level, never inside a run subdir
    store.save_batch(inv_df, "_manifest")
    store.save_batch(find_df, "_findings")
    store.save_batch(pd.DataFrame({"lesson": LESSONS}), "_lessons")
    con.close()

    # human-readable manifest doc
    out = Path(__file__).resolve().parents[3].parent.parent / "docs/research/astro_lab_R2_manifest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    L = ["# astro_lab R2 lake — manifest & how to use it\n",
         f"_All experiments persisted under **`r2://{store.bucket}/{store.prefix}/`** as Parquet — one prefix per "
         "experiment, DuckDB-queryable, trivially droppable. The raw trials are kept for learning; the distilled "
         "findings + lessons are the top-level tables. `r2_manifest.py` (idempotent)._\n",
         "## Inventory\n", inv_df.to_markdown(index=False) if len(inv_df) else "(empty)",
         "\n## Curated findings (the interesting stuff)\n", find_df.to_markdown(index=False),
         "\n## Lessons (reusable for the next signal)\n", "\n".join(f"- {x}" for x in LESSONS),
         "\n## Query / dump (DuckDB — no boto3, R2 secret in-memory)\n",
         "```sql\n"
         "INSTALL httpfs; LOAD httpfs;\n"
         "CREATE SECRET r2 (TYPE r2, KEY_ID '…', SECRET '…', ACCOUNT_ID '…');\n"
         f"-- curated findings:\nSELECT * FROM read_parquet('r2://{store.bucket}/{store.prefix}/_findings.parquet');\n"
         f"-- inventory:\nSELECT * FROM read_parquet('r2://{store.bucket}/{store.prefix}/_manifest.parquet');\n"
         f"-- all 152k strategy trials, ranked:\nSELECT * FROM read_parquet('r2://{store.bucket}/{store.prefix}/run_*/*.parquet') "
         "ORDER BY sharpe DESC LIMIT 50;\n"
         "```\n",
         "## Drop a single experiment (clean teardown)\n",
         f"Each experiment is one prefix under `{store.prefix}/` — delete that prefix in R2 to drop it; nothing else "
         "references it (isolated namespace, never touches prod `alt_data` or the Gate).\n"]
    out.write_text("\n".join(str(x) for x in L) + "\n")
    print(inv_df.to_string(index=False))
    print(f"\nmanifest + findings + lessons → r2://{store.bucket}/{store.prefix}/  ·  doc → {out}")


if __name__ == "__main__":
    main()
