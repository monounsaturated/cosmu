"use client";

// Light/dark toggle (Iris Bento `.theme-btn`). Flips the `.light` class on <html> and persists to
// localStorage. A tiny inline script in the root layout applies the stored choice before paint, so
// there is no flash. The moon/sun glyphs swap purely via CSS (`html.light .ic-moon{display:none}` …),
// so this button is theme-agnostic — it just toggles the class.

export function ThemeToggle() {
  function toggle() {
    const isLight = document.documentElement.classList.toggle("light");
    try {
      localStorage.setItem("cosmu.theme", isLight ? "light" : "dark");
    } catch {
      /* ignore */
    }
  }

  return (
    <button className="theme-btn" onClick={toggle} title="Light / dark mode" aria-label="Toggle theme" type="button">
      <svg className="ic-moon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
      <svg className="ic-sun" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    </button>
  );
}
