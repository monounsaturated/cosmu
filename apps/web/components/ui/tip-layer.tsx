"use client";

// Viewport-clamped hover tooltip — ported from the reference mockup's global `#tipbox` handler so any
// element anywhere in the app can show a tooltip just by carrying a `data-tip="…"` attribute (gate-chip
// (?) marks, key status dots, editable caps, the engine dot, …). Mounted once in the app shell. Styling
// lives in globals.css (`#tipbox`). No portal needed — it appends a single fixed node to <body>.

import { useEffect } from "react";

export function TipLayer() {
  useEffect(() => {
    const tip = document.createElement("div");
    tip.id = "tipbox";
    document.body.appendChild(tip);

    function onOver(e: MouseEvent) {
      const target = (e.target as HTMLElement | null)?.closest<HTMLElement>("[data-tip]");
      if (!target) {
        tip.classList.remove("on");
        return;
      }
      tip.textContent = target.getAttribute("data-tip") ?? "";
      tip.classList.add("on");
      const r = target.getBoundingClientRect();
      tip.style.left = "0px";
      tip.style.top = "0px"; // reset to measure
      const tw = tip.offsetWidth;
      const th = tip.offsetHeight;
      let x = r.left + r.width / 2 - tw / 2;
      x = Math.max(8, Math.min(x, window.innerWidth - tw - 8));
      let y = r.top - th - 8;
      if (y < 8) y = r.bottom + 8;
      y = Math.min(y, window.innerHeight - th - 8);
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    }

    document.addEventListener("mouseover", onOver);
    return () => {
      document.removeEventListener("mouseover", onOver);
      tip.remove();
    };
  }, []);

  return null;
}
