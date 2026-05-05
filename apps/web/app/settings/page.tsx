import { FormatterPromptSettings } from "./formatter-prompt-settings";
import { SettingsConsole } from "./settings-console";

export default function SettingsPage() {
  return (
    <main className="page page-wide">
      <section className="command-hero">
        <div>
          <p className="eyebrow">System</p>
          <h1>Models, data sources, and execution defaults.</h1>
          <p className="muted">
            Configure the pieces every agent depends on before you let it research, trade, or ask for live approval.
          </p>
        </div>
      </section>

      <SettingsConsole />

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
