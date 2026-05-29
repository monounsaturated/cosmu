"use client";

import { useEffect, useState } from "react";
import { RunDetail } from "./run-detail";

type Run = {
  id: string;
  status: string;
  startedAt: string;
  promptSystem: string | null;
  promptUser: string | null;
  researchOutput: string | null;
  traderOutput: string | null;
  traderVersion: number | null;
  validationResult?: { accepted: boolean; issues: string[] } | null;
};

type RunsResponse = {
  total: number;
  limit: number;
  offset: number;
  runs: Run[];
};

const PAGE_SIZE = 20;

export function RecentRuns({
  botId,
  initialData
}: {
  botId: string;
  initialData: RunsResponse | null;
}) {
  const [data, setData] = useState<RunsResponse | null>(initialData);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [includeGuardian, setIncludeGuardian] = useState(false);

  useEffect(() => {
    // Only refetch once the user changes page / filter — initial render comes from server.
    if (offset === 0 && !includeGuardian && initialData) return;

    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
      includeGuardian: String(includeGuardian)
    });
    fetch(`/api/bots/${botId}/runs?${params.toString()}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((json: RunsResponse) => {
        if (!cancelled) setData(json);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [botId, offset, includeGuardian, initialData]);

  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px", flexWrap: "wrap", gap: "8px" }}>
        <p className="muted" style={{ margin: 0 }}>
          {total > 0 ? `${total} ${includeGuardian ? "runs total" : "non-guardian runs"} · page ${page} / ${totalPages}` : "No runs"}
        </p>
        <label style={{ fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" }} className="muted">
          <input
            type="checkbox"
            checked={includeGuardian}
            onChange={(e) => {
              setIncludeGuardian(e.target.checked);
              setOffset(0);
            }}
          />
          Include guardian runs
        </label>
      </div>

      {runs.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {runs.map((run) => (
            <RunDetail key={run.id} run={run} />
          ))}
        </div>
      ) : (
        <p className="muted">{loading ? "Loading..." : "No execution runs yet."}</p>
      )}

      {total > PAGE_SIZE && (
        <div style={{ display: "flex", gap: "8px", marginTop: "16px", justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn"
            disabled={!canPrev || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            ← Prev
          </button>
          <button
            type="button"
            className="btn"
            disabled={!canNext || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}
