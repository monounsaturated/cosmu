import Link from "next/link";
import { FormatterPromptSettings } from "./formatter-prompt-settings";

export default function SettingsPage() {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <Link href="/" className="muted" style={{ display: "inline-block", marginBottom: "16px", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
          <h1>Settings</h1>
          <p className="muted">
            The formatter prompt converts free-form research from phase 1 into executable
            TradingDecision JSON. Each edit is versioned so you can study what worked.
          </p>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>Formatter / execution prompt (per venue)</h2>
        <FormatterPromptSettings />
      </section>
    </main>
  );
}
