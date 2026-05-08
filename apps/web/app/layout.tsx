import "./globals.css";
import type { ReactNode } from "react";
import { ControlHeader } from "./control-header";
import { Sidebar } from "./sidebar";

export const metadata = {
  title: "cosmu",
  description: "AI trading OS"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => { try { const saved = localStorage.getItem("cosmu-theme"); const theme = saved === "light" || saved === "dark" ? saved : (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = theme; document.documentElement.style.colorScheme = theme; } catch { document.documentElement.dataset.theme = "dark"; } try { const sw = localStorage.getItem("cosmu-sidebar-width"); if (sw) document.documentElement.style.setProperty("--sidebar-w", sw + "px"); } catch {} })();`
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
