import "./globals.css";
import type { ReactNode } from "react";
import { ControlHeader } from "./control-header";
import { Sidebar } from "./sidebar";

export const metadata = {
  title: "cosmu",
  description: "Lean AI trading cockpit and signal sentinel"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => { try { const saved = localStorage.getItem("cosmu-theme"); const theme = saved === "light" || saved === "dark" ? saved : (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = theme; document.documentElement.style.colorScheme = theme; } catch { document.documentElement.dataset.theme = "dark"; } })();`
          }}
        />
      </head>
      <body>
        <div className="app-shell">
          <Sidebar />
          <div className="app-main">
            <ControlHeader />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
