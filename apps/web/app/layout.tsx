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
