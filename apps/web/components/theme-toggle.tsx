"use client";

// Light/dark toggle. Flips `.light` on <html> and persists the choice; layout.tsx applies it before paint.
export function ThemeToggle() {
  function toggle() {
    const isLight = document.documentElement.classList.toggle("light");
    try {
      localStorage.setItem("cosmu.theme", isLight ? "light" : "dark");
    } catch {
      /* storage blocked — the toggle still works for this visit */
    }
  }

  return (
    <button className="icon-btn" onClick={toggle} title="Light / dark" aria-label="Toggle theme" type="button">
      <svg className="ic-moon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
      <svg className="ic-sun" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    </button>
  );
}
