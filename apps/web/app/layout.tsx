import "./globals.css";
import type { ReactNode } from "react";
import { Activity, Bot, ChartNoAxesCombined, LayoutDashboard, MessageSquareText, Trophy } from "lucide-react";

export const metadata = {
  title: "Cosmu v2",
  description: "Autonomous quant money machine"
};

const nav = [
  { href: "/#dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/#leaderboard", label: "Leaderboard", icon: Trophy },
  { href: "/strategy/sv-btc", label: "Strategy", icon: ChartNoAxesCombined },
  { href: "/#console", label: "Console", icon: MessageSquareText }
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">
              <div className="mark">C</div>
              <div>
                <strong>Cosmu</strong>
                <div className="subtle">v2 autonomous lab</div>
              </div>
            </div>
            <nav className="nav" aria-label="Main navigation">
              {nav.map((item) => (
                <a key={item.href} href={item.href}>
                  <item.icon size={17} />
                  <span>{item.label}</span>
                </a>
              ))}
            </nav>
          </aside>
          <main className="main">
            <div className="topbar">
              <div className="row">
                <Activity size={18} color="var(--green)" />
                <span className="subtle">Paper farming live-shadow data. Live capital gated.</span>
              </div>
              <div className="pill warn">
                <Bot size={14} />
                live off by default
              </div>
            </div>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

