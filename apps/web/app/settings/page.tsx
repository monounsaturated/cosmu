import Link from "next/link";
import { FormatterPromptSettings } from "./formatter-prompt-settings";

export default function SettingsPage() {
  return (
    <main className="page page-wide">
      <section className="hero">
        <div>
          <p className="eyebrow">Control room</p>
          <h1>Settings without the noise.</h1>
          <p className="muted">
            Keep defaults simple. Advanced prompt and execution behavior stays here, versioned and inspectable.
          </p>
        </div>
        <Link href="/" className="btn btn-secondary">Back to Trader</Link>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>Formatter / execution prompt</h2>
        <p className="muted" style={{ marginBottom: "16px" }}>
          Converts free-form research into executable TradingDecision JSON per venue.
        </p>
        <FormatterPromptSettings />
      </section>
    </main>
  );
}
