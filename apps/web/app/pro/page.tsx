import { ShieldCheck, Zap } from "lucide-react";
import { approvalRequestSchema } from "@cosmu/shared";
import { BotTable } from "../bot-table";
import { getDashboard } from "../dashboard-data";
import { ProApprovals } from "./pro-approvals";

export const dynamic = "force-dynamic";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

async function fetchApi(path: string) {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) return null;
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey },
      signal: AbortSignal.timeout(6000)
    });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export default async function ProPage() {
  const [dashboard, approvalsRaw] = await Promise.all([
    getDashboard(),
    fetchApi("/agent-control/approvals?status=pending")
  ]);

  const approvals = approvalRequestSchema.array().catch([]).parse(approvalsRaw?.approvals ?? []);

  return (
    <main className="page page-wide">
      <section className="command-panel">
        <div>
          <p className="eyebrow">Cosmu Pro</p>
          <h1>Live control, approval first.</h1>
          <p className="field-help">
            Pro is the live-eligible workspace. Approved Research candidates land here as Pro bots, gated by the
            shared deterministic validator and the global kill switch. Light bots and unpromoted research bots are
            never visible here.
          </p>
        </div>
        <div className="pro-readiness">
          <span><ShieldCheck size={16} /> Live approval required by default</span>
          <span><Zap size={16} /> Capped auto-live planned later</span>
        </div>
      </section>

      <section className="ops-grid">
        <article className="panel">
          <h3>Pro V1 pipeline</h3>
          <div className="pipeline-strip">
            {["Analysts", "Bear Review", "Trader", "Risk Review", "Validator", "Execution"].map((step) => (
              <span key={step}>{step}</span>
            ))}
          </div>
          <p className="muted" style={{ marginTop: "12px", fontSize: "12px" }}>
            The validator and execution stages are shared with Light. Pro bots inherit the same deterministic
            checks and global kill switch the rest of the platform uses.
          </p>
        </article>
        <article className="panel">
          <h3>Execution safety defaults</h3>
          <ul className="clean-list">
            <li>Human approval before promotion to a real-funds venue.</li>
            <li>Promoted bots start with execution disabled — a human enables order placement.</li>
            <li>Validator and global kill switch are mandatory and shared with Light.</li>
            <li>Research evidence and skeptic pass are required before real-funds eligibility.</li>
          </ul>
        </article>
      </section>

      <ProApprovals initialApprovals={approvals} />

      <div style={{ marginTop: "20px" }}>
        <BotTable
          dashboard={dashboard}
          workspaceMode="pro"
          title="Promoted agents"
          description="Venue-scoped agents promoted from Research. Each row is a strategy that cleared review and explicit human approval."
          emptyMessage="No promoted agents yet. Approve a Research promotion request above to spawn one."
        />
      </div>
    </main>
  );
}
