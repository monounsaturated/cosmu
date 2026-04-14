import Link from "next/link";
import { FormatterPromptSettings } from "./formatter-prompt-settings";
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
          <p className="muted">
            App-wide defaults per venue. Phase 1 uses the preprompt + each bot&apos;s strategy prompt for
            research; phase 2 uses the formatter prompt to turn research + live prices into order JSON.
          </p>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>Phase 1 — system preprompt (per venue)</h2>
        <PrepromptSettings />
      </section>

      <section className="panel" style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>Phase 2 — formatter / execution prompt (per venue)</h2>
        <FormatterPromptSettings />
      </section>
    </main>
  );
}
