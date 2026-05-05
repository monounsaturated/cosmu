import { ShieldCheck, Zap } from "lucide-react";

export default function ProPage() {
  return (
    <main className="page page-wide">
      <section className="command-panel">
        <div>
          <p className="muted">Cosmu Pro</p>
          <h1>Agentic live trading control</h1>
          <p className="field-help">
            Pro will combine Research outputs, multi-agent review, risk gating, deterministic validation, and live approval.
          </p>
        </div>
        <div className="pro-readiness">
          <span><ShieldCheck size={16} /> Live approval required by default</span>
          <span><Zap size={16} /> Capped auto-live planned later</span>
        </div>
      </section>

      <section className="ops-grid">
        <article className="panel">
          <h3>Pro V1 Pipeline</h3>
          <div className="pipeline-strip">
            {["Analysts", "Bear Review", "Trader", "Risk Review", "Validator", "Execution"].map((step) => (
              <span key={step}>{step}</span>
            ))}
          </div>
          <p className="muted" style={{ marginTop: "16px" }}>
            This mode is intentionally gated until Research and observability prove stable.
          </p>
        </article>
        <article className="panel">
          <h3>Live Safety Defaults</h3>
          <ul className="clean-list">
            <li>Human approval before live promotion.</li>
            <li>Existing deterministic validator remains mandatory.</li>
            <li>Global kill switch stays shared with Light.</li>
            <li>Paper evidence required before live eligibility.</li>
          </ul>
        </article>
      </section>
    </main>
  );
}

