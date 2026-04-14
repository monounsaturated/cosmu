import "./globals.css";
import type { ReactNode } from "react";
import { Sidebar } from "./sidebar";

export const metadata = {
  title: "cosmu",
  description: "Internal V1 trading dashboard"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Sidebar />
          <div className="app-content">{children}</div>
        </div>
      </body>
    </html>
  );
}
