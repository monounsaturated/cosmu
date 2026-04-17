import type { DashboardPayload } from "@cosmu/shared";

type VenueEntry = { accountBalance: number; allocatedAmount: number; spareAmount: number };

function VenueCard({ label, data, dotClass, labelColor }: {
  label: string;
  data: VenueEntry;
  dotClass: string;
  labelColor: string;
}) {
  return (
    <div className="panel venue-group" style={{ flex: "1 1 340px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
        <span className={`status-dot ${dotClass}`} style={{ width: "8px", height: "8px" }} />
        <span className="label" style={{ fontSize: "13px", color: labelColor }}>{label}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
        <div>
          <p className="label">Account Balance</p>
          <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${data.accountBalance.toFixed(2)}</h2>
        </div>
        <div>
          <p className="label">Allocated to Bots</p>
          <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${data.allocatedAmount.toFixed(2)}</h2>
        </div>
        <div>
          <p className="label">Spare</p>
          <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${data.spareAmount.toFixed(2)}</h2>
        </div>
      </div>
    </div>
  );
}

export function VenueOverview({ venueOverview }: { venueOverview: DashboardPayload["venueOverview"] }) {
  const hasAny = venueOverview.live || venueOverview.testnet;

  return (
    <section style={{ marginBottom: "32px", display: "flex", gap: "16px", flexWrap: "wrap" }}>
      {venueOverview.live && (
        <VenueCard label="Live" data={venueOverview.live} dotClass="status-active" labelColor="#34d399" />
      )}
      {venueOverview.testnet && (
        <VenueCard label="Testnet" data={venueOverview.testnet} dotClass="status-inactive" labelColor="#a1a1aa" />
      )}
      {!hasAny && (
        <div className="panel" style={{ flex: 1 }}>
          <p className="muted">No venue data available.</p>
        </div>
      )}
    </section>
  );
}
