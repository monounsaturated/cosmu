# intent: DURABLE, labeled, ISOLATED trial store for the astro-strategy lab. Every backtested config is written
# BOTH to a local Parquet mirror (never lost even if R2 hiccups) AND to Cloudflare R2 (r2://<bucket>/astro_lab/...,
# the project cold lake) via a DuckDB-native R2 secret (no boto3 creds on disk — same pattern as
# cosmu/data/providers/parquet_store.py). This is a SEPARATE namespace ('astro_lab/') — it never touches the real
# alt_data table or the Gate ledger, so the deep astro search cannot contaminate the money path. Append-only:
# each batch is one immutable Parquet file; read_all() globs them back for aggregation + deflation.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd


class LabStore:
    """Append-only Parquet trial store (local mirror + R2 durable copy). Labeled 'astro_lab', isolated from prod."""

    def __init__(self, prefix: str = "astro_lab", local_dir: str | Path = ".cosmu/astro_lab") -> None:
        self.bucket = os.environ.get("R2_BUCKET")
        self.acct = os.environ.get("R2_ACCOUNT_ID")
        self.key = os.environ.get("R2_ACCESS_KEY_ID")
        self.secret = os.environ.get("R2_SECRET_ACCESS_KEY")
        self.prefix = prefix.strip("/")
        self.local = Path(local_dir)
        self.local.mkdir(parents=True, exist_ok=True)

    @property
    def r2_ready(self) -> bool:
        return bool(self.bucket and self.acct and self.key and self.secret)

    def _conn(self) -> Any:
        import duckdb

        con = duckdb.connect(database=":memory:")
        if self.r2_ready:
            con.execute("INSTALL httpfs; LOAD httpfs;")
            # credentials live ONLY in this in-memory secret, never written to disk
            con.execute(
                "CREATE OR REPLACE SECRET cosmu_r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
                [self.key, self.secret, self.acct],
            )
        return con

    def r2_uri(self, batch_id: str) -> str:
        return f"r2://{self.bucket}/{self.prefix}/{batch_id}.parquet"

    def save_batch(self, df: pd.DataFrame, batch_id: str) -> dict[str, str]:
        """Persist one trial-results batch. LOCAL mirror first (always succeeds), then R2 (best-effort durable).
        Returns the paths actually written so a caller can verify nothing was lost."""
        out: dict[str, str] = {}
        local_path = self.local / f"{batch_id}.parquet"
        local_path.parent.mkdir(parents=True, exist_ok=True)  # batch_id may carry a run-id subdir
        df.to_parquet(local_path, index=False)
        out["local"] = str(local_path)
        if self.r2_ready:
            con = self._conn()
            con.register("_batch", df)
            con.execute(f"COPY _batch TO '{self.r2_uri(batch_id)}' (FORMAT parquet)")
            con.close()
            out["r2"] = self.r2_uri(batch_id)
        return out

    def read_all(self, *, source: str = "auto") -> pd.DataFrame:
        """Glob every saved batch back into one DataFrame (for aggregation + deflation). `source`: 'r2' | 'local'
        | 'auto' (R2 when ready, else local)."""
        use_r2 = (source == "r2") or (source == "auto" and self.r2_ready)
        con = self._conn()
        try:
            if use_r2:
                glob = f"r2://{self.bucket}/{self.prefix}/*.parquet"
            else:
                glob = str(self.local / "*.parquet")
            return con.execute(f"SELECT * FROM read_parquet('{glob}')").df()
        except Exception:  # noqa: BLE001 — empty store / no files yet
            return pd.DataFrame()
        finally:
            con.close()

    def read_run(self, run_id: str, *, source: str = "auto") -> pd.DataFrame:
        """Read back just ONE run's batches (the run-id subfolder) — RAM-bounded aggregation from the durable
        store instead of holding every trial in memory."""
        use_r2 = (source == "r2") or (source == "auto" and self.r2_ready)
        con = self._conn()
        try:
            glob = (f"r2://{self.bucket}/{self.prefix}/{run_id}/*.parquet" if use_r2
                    else str(self.local / run_id / "*.parquet"))
            return con.execute(f"SELECT * FROM read_parquet('{glob}')").df()
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
        finally:
            con.close()

    def count(self) -> int:
        df = self.read_all()
        return 0 if df is None or df.empty else len(df)


if __name__ == "__main__":
    # ROUND-TRIP PROOF: write a tiny batch to local + R2, read it back, confirm durable persistence works
    import sys

    store = LabStore()
    print(f"R2 ready: {store.r2_ready}  bucket={store.bucket}  prefix={store.prefix}")
    demo = pd.DataFrame(
        {"config_id": ["demo_a", "demo_b"], "school": ["western", "vedic"], "asset": ["BTCUSDT", "SPY"],
         "sharpe": [0.42, -0.13], "dsr": [0.01, 0.0], "n_trades": [120, 88]}
    )
    paths = store.save_batch(demo, "_roundtrip_test")
    print("wrote:", paths)
    back = store.read_all(source="r2" if store.r2_ready else "local")
    print(f"read back {len(back)} rows from {'R2' if store.r2_ready else 'local'}:")
    print(back.to_string(index=False))
    ok = len(back) >= 2 and set(demo["config_id"]) <= set(back["config_id"])
    print("ROUND-TRIP", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
