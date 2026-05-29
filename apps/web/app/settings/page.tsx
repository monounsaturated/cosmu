import { VenueTraderPromptSettings } from "./venue-trader-prompt-settings";
import { SettingsConsole } from "./settings-console";

export default function SettingsPage() {
  return (
    <main className="page page-wide">
      <section className="command-hero">
        <div>
          <p className="eyebrow">System</p>
          <h1>Defaults for a focused agent product.</h1>
          <p className="muted">
            Pick default prompts, providers, models, runtime settings, and future data source toggles from one place.
          </p>
        </div>
      </section>

      <SettingsConsole />

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.15rem" }}>Venue trader prompt</h2>
        <p className="muted" style={{ marginBottom: "16px" }}>
          Converts free-form research into executable TradingDecision JSON per venue.
        </p>
        <VenueTraderPromptSettings />
      </section>
    </main>
  );
}
