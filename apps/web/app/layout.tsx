import "./globals.css";
import type { ReactNode } from "react";
import { Inter, Geist_Mono } from "next/font/google";
import Script from "next/script";
import { AppShell } from "@/components/nav/app-shell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

export const metadata = {
  title: "Cosmu — autonomous quant lab",
  description: "Autonomous, self-learning swing-trading money machine. Scorer and money out of the agent's reach."
};

// Apply the saved theme before paint to avoid a flash of the wrong palette.
const themeScript = `try{if(localStorage.getItem('cosmu.theme')==='light')document.documentElement.classList.add('light')}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="font-sans">
        <Script id="cosmu-theme-init" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: themeScript }} />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
