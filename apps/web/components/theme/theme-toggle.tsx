"use client";

// Light/dark toggle. Flips the `.light` class on <html> and persists to localStorage. A tiny inline
// script in the root layout applies the stored choice before paint, so there is no flash.

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  const [light, setLight] = useState(false);

  useEffect(() => {
    setLight(document.documentElement.classList.contains("light"));
  }, []);

  function toggle() {
    const isLight = document.documentElement.classList.toggle("light");
    try {
      localStorage.setItem("cosmu.theme", isLight ? "light" : "dark");
    } catch {
      /* ignore */
    }
    setLight(isLight);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
      title={light ? "Switch to dark theme" : "Switch to light theme"}
      className="inline-flex size-9 items-center justify-center rounded-md border border-border/70 text-muted transition-colors hover:bg-surface-2/60 hover:text-foreground"
    >
      {light ? <Moon className="size-[18px]" /> : <Sun className="size-[18px]" />}
    </button>
  );
}
