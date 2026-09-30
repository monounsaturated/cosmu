import "./globals.css";
import type { ReactNode } from "react";
import type { Metadata } from "next";
import Script from "next/script";
import { Inter, JetBrains_Mono } from "next/font/google";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

const DESC = "Most trading ideas lose money. Describe yours in plain English: Cosmu tests it on real prices, with your fees, against pure luck.";

export const metadata: Metadata = {
  openGraph: { title: "Cosmu: your AI trading analyst", description: DESC, type: "website" },
  twitter: { card: "summary", title: "Cosmu: your AI trading analyst", description: DESC },
  title: "Cosmu: your AI trading analyst",
  description: DESC,
};

// Theme before paint: light by default; a visitor's saved choice (the toggle) wins.
const themeScript = `try{if(localStorage.getItem('cosmu.theme')!=='dark')document.documentElement.classList.add('light')}catch(e){document.documentElement.classList.add('light')}`;

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
