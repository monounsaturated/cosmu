import "./globals.css";
import type { ReactNode } from "react";
import { Inter, Geist_Mono } from "next/font/google";
import {
  Activity,
  ChartCandlestick,
  Dna,
  LayoutDashboard,
  Lock,
  MessagesSquare,
  Trophy
} from "lucide-react";
import { CosmuWordmark } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

export const metadata = {
  title: "Cosmu v2 — autonomous quant lab",
  description: "Autonomous, self-learning swing-trading money machine. Scorer and money out of the agent's reach."
};

const nav = [
  { href: "/#dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/farm", label: "Farm", icon: Dna },
  { href: "/#leaderboard", label: "Leaderboard", icon: Trophy },
  { href: "/strategy/sv-btc", label: "Strategy", icon: ChartCandlestick },
  { href: "/#console", label: "Console", icon: MessagesSquare }
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="font-sans">
        <div className="mx-auto grid min-h-screen max-w-[1560px] grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)]">
          <aside className="glass sticky top-0 hidden h-screen flex-col border-r border-border/70 p-4 lg:flex">
            <div className="px-1 pb-4">
              <CosmuWordmark />
            </div>
            <nav className="mt-2 flex flex-col gap-1" aria-label="Main navigation">
              {nav.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="group flex items-center gap-3 rounded-md border border-transparent px-3 py-2 text-[13px] text-muted transition-colors hover:border-border hover:bg-surface-2/60 hover:text-foreground"
                >
                  <item.icon className="size-[17px] text-quiet transition-colors group-hover:text-iris-soft" />
                  <span>{item.label}</span>
                </a>
              ))}
            </nav>

            <div className="mt-auto rounded-lg border border-border/70 bg-surface-2/40 p-3">
              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                <Lock className="size-3.5 text-warn" />
                Capital valve
              </div>
              <p className="mt-1.5 text-[11.5px] leading-snug text-quiet">
                LLM proposes, deterministic disposes. Live orders gated behind the toggle.
              </p>
            </div>
          </aside>

          <main className="min-w-0">
            <header className="glass sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border/70 px-5 py-3 lg:px-7">
              <div className="flex items-center gap-2.5 text-[13px] text-muted">
                <span className="relative flex size-2">
                  <span className="animate-pulse-dot absolute inline-flex size-2 rounded-full bg-up/70" />
                  <span className="relative inline-flex size-2 rounded-full bg-up" />
                </span>
                <Activity className="size-4 text-up" />
                <span className="hidden sm:inline">Paper farming on live-shadow data · scorer deterministic</span>
                <span className="sm:hidden">Paper farming</span>
              </div>
              <Badge variant="warn">
                <Lock className="size-3" />
                Live off by default
              </Badge>
            </header>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
