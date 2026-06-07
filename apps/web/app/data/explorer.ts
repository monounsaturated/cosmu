// module: Strategy Explorer data adapter. Serves stored backtest snapshots for the
// operator's pick-and-compare UI. Never fabricates curves or numbers.
// Honesty model: same as every other data module — connected:false → honest empty state.

import type {
  ExplorerDetailResponse,
  ExplorerListResponse,
} from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyList: ExplorerListResponse = {
  versions: [],
  venues: [],
  assets: [],
};

const emptyDetail: ExplorerDetailResponse = {
  version_id: "",
  name: "",
  spec: {},
  available: false,
  equity_curve: [],
  trades: [],
  stats: {
    thesis: null,
    asset: null,
    venue: null,
    fee_assumed_bps: null,
    data_span_days: null,
    num_bars: null,
    gross_return_pct: null,
    net_return_pct: null,
    cost_ratio: null,
    num_trades: null,
    deflated_sharpe: null,
    max_dd: null,
    oos_holdout_pct: null,
    gate_decision: null,
    gate_reason: null,
  },
};

export async function getExplorerList(): Promise<{
  list: ExplorerListResponse;
  connected: boolean;
}> {
  const { data, connected } = await getJson<ExplorerListResponse>("/explorer", emptyList);
  return { list: { versions: data.versions ?? [], venues: data.venues ?? [], assets: data.assets ?? [] }, connected };
}

export async function getExplorerDetail(
  versionId: string
): Promise<{ detail: ExplorerDetailResponse; connected: boolean }> {
  const { data, connected } = await getJson<ExplorerDetailResponse>(
    `/explorer/${versionId}`,
    emptyDetail
  );
  return { detail: data, connected };
}
