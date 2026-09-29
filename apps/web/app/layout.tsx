import "./globals.css";
import type { ReactNode } from "react";
import type { Metadata } from "next";
import Script from "next/script";
import { Inter, JetBrains_Mono } from "next/font/google";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

const DESC = "Ask in plain English. Cosmu finds the news, tests it on real prices with your broker's fees, and tells you if it would have made money.";

export const metadata: Metadata = {
  openGraph: { title: "Cosmu: turn any headline into a backtest", description: DESC, type: "website" },
  twitter: { card: "summary", title: "Cosmu: turn any headline into a backtest", description: DESC },
  title: "Cosmu: turn any headline into a backtest",
  description:
    "Ask in plain English. Cosmu finds the news, tests it on real prices with your broker's fees, and tells you if it would have made money.",
};

// Theme before paint: stored choice wins, else follow the OS. Dark is the default.
const themeScript = `try{var t=localStorage.getItem('cosmu.theme');if(!t&&window.matchMedia)t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';if(t==='light')document.documentElement.classList.add('light')}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Script id="theme-init" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
      </body>
    </html>
  );
}
