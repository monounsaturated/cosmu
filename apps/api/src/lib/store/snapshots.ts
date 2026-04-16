import { portfolioSnapshotSchema, type PortfolioSnapshot } from "@cosmu/shared";
import { sql } from "../../db.js";

export const storePortfolioSnapshot = async (runId: string, stage: "before" | "after", snapshot: PortfolioSnapshot) => {
  const parsed = portfolioSnapshotSchema.parse(snapshot);
  await sql`
    insert into portfolio_snapshots (
      run_id, asset_class, stage, total_usd_value,
      gross_pnl_usd, net_pnl_usd, fee_usd,
      balances, prices, raw_snapshot
    ) values (
      ${runId}, ${parsed.assetClass}, ${stage}, ${parsed.totalUsdValue},
      ${parsed.grossPnlUsd}, ${parsed.netPnlUsd}, ${parsed.feeUsd},
      ${sql.json(parsed.balances)}, ${sql.json(parsed.prices)},
      ${sql.json(parsed)}
    )
  `;
};
