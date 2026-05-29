import { Activity, AlertTriangle, CheckCircle2, CircleDollarSign, PlugZap, WalletCards } from "lucide-react";
import type { DashboardPayload } from "@cosmu/shared";

type AccountEntry = DashboardPayload["accounts"][number];
type VenueOverview = DashboardPayload["venueOverview"];
type MarketDataStatus = DashboardPayload["marketDataStatus"];

const formatUsd = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 0 : 2
  }).format(value);

const fallbackAccounts = (venueOverview: VenueOverview): AccountEntry[] => {
  const rows: AccountEntry[] = [];
  if (venueOverview.live) {
    rows.push({
      id: "binance-live",
      label: "Binance Live",
      venue: "binance",
      mode: "live",
      configured: true,
      connected: true,
      configuredAgents: 0,
      activeAgents: 0,
      status: "connected",
      ...venueOverview.live
    });
  }
  if (venueOverview.testnet) {
    rows.push({
      id: "binance-testnet",
      label: "Binance Testnet",
      venue: "binance-testnet",
      mode: "testnet",
      configured: true,
      connected: true,
      configuredAgents: 0,
      activeAgents: 0,
      status: "connected",
      ...venueOverview.testnet
    });
  }
  return rows;
};

const formatFreshness = (value: string | null | undefined) => {
  if (!value) return "warming up";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
};

export function VenueOverview({
  accounts,
  venueOverview,
  marketDataStatus
}: {
  accounts: DashboardPayload["accounts"];
  venueOverview: VenueOverview;
  marketDataStatus?: MarketDataStatus;
}) {
  const rows = accounts.length > 0 ? accounts : fallbackAccounts(venueOverview);

  return (
    <section className="panel account-overview-panel">
      <div className="section-header account-overview-header">
        <div>
          <span className="label">Accounts</span>
          <h3>Cash, allocation, and free capacity</h3>
        </div>
        <span className="badge badge-neutral">{rows.length} tracked</span>
      </div>

      {rows.length === 0 ? (
        <p className="muted">No account data available.</p>
      ) : (
        <div className="account-card-grid">
          {rows.map((account) => {
            const utilization = account.accountBalance > 0
              ? Math.min(100, Math.max(0, (account.allocatedAmount / account.accountBalance) * 100))
              : 0;
            const spareTone = account.spareAmount < 0 ? "value-red" : account.spareAmount > 0 ? "value-green" : "";
            const dataStatus = account.mode === "live" ? marketDataStatus?.live : marketDataStatus?.testnet;
            const dataLabel = account.error
              ? account.error
              : dataStatus?.balanceError
              ? dataStatus.balanceError
              : `checked ${formatFreshness(account.checkedAt ?? dataStatus?.balanceUpdatedAt)}`;
            const badgeClass = account.connected ? "badge-success" : account.status === "error" ? "badge-warn" : "badge-inactive";
            return (
              <article className={`account-card account-card-${account.status}`} key={account.id}>
                <div className="account-card-top">
                  <span>
                    <strong>{account.label}</strong>
                    <small>{account.venue} / {account.mode} · {dataLabel}</small>
                  </span>
                  <span className={`badge ${badgeClass}`}>
                    {account.connected ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
                    {account.connected ? "connected" : account.status}
                  </span>
                </div>

                <div className="account-balance-row">
                  <WalletCards size={18} />
                  <strong className="finance-number">{formatUsd(account.accountBalance)}</strong>
                </div>

                <div className="account-usage" aria-label={`${account.label} allocation`}>
                  <span style={{ width: `${utilization}%` }} />
                </div>

                <div className="account-metrics">
                  <span>
                    <CircleDollarSign size={14} />
                    <small>Allocated</small>
                    <strong>{formatUsd(account.allocatedAmount)}</strong>
                  </span>
                  <span>
                    <PlugZap size={14} />
                    <small>Free</small>
                    <strong className={spareTone}>{formatUsd(account.spareAmount)}</strong>
                  </span>
                  <span>
                    <Activity size={14} />
                    <small>Agents</small>
                    <strong>{account.activeAgents}/{account.configuredAgents}</strong>
                  </span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
