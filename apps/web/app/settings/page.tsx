import Link from "next/link";
import { PrepromptSettings } from "./preprompt-settings";

export default function SettingsPage() {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <Link href="/" className="muted" style={{ display: "inline-block", marginBottom: "16px", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
          <h1>Settings</h1>
          <p className="muted">App-wide defaults. Per-venue system preprompt applies to all bots on that venue.</p>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>System preprompt (per venue)</h2>
        <PrepromptSettings />
      </section>
    </main>
  );
}
