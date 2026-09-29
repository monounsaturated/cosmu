// Shared page toolbar (Iris Bento `.toolbar-row`). Every surface leads with one of these: the page
// title on the left, optional left-aligned controls (filter chips, status badges) right after it, and
// a right-aligned action group (page buttons + the always-present theme toggle). Replaces the old
// SectionHeader. Keep it server-safe — the only client bit is <ThemeToggle/>.

import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/theme-toggle";

export function Toolbar({ title, left, right }: { title: string; left?: ReactNode; right?: ReactNode }) {
  return (
    <div className="toolbar-row">
      <span className="page-title">{title}</span>
      {left}
      <div className="toolbar-actions">
        {right}
        <ThemeToggle />
      </div>
    </div>
  );
}

// A bare page wrapper — the bento `.page` block (entrance animation + padding). Use for every route's
// content beneath the Toolbar so page transitions feel consistent.
export function Page({ children }: { children: ReactNode }) {
  return <div className="page active">{children}</div>;
}
