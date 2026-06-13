import "./globals.css";
import type { ReactNode } from "react";
import Script from "next/script";
import { AppShell } from "@/components/nav/app-shell";

export const metadata = {
  title: "Cosmu — autonomous quant lab",
  description: "Autonomous, self-learning swing-trading money machine. Scorer and money out of the agent's reach."
};

// Cosmu is a LIVE operator dashboard — every route renders on-demand with fresh engine data; nothing is
// statically pre-rendered (static export hangs fetching the engine at build time). The bento shell is a
// client component so it paints instantly; pages stream their data region behind a <Suspense> skeleton.
export const dynamic = "force-dynamic";

// Apply the saved theme before paint to avoid a flash of the wrong palette. The Iris Bento system is
// dark by default; `.light` on <html> flips the palette (globals.css `html.light`).
const themeScript = `try{if(localStorage.getItem('cosmu.theme')==='light')document.documentElement.classList.add('light')}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Script id="cosmu-theme-init" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: themeScript }} />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
