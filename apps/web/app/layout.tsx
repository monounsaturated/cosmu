import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "cosmu",
  description: "Internal V1 trading dashboard"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
