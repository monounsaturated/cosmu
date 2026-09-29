"use client";

// Viewport-clamped hover tooltip — ported from the reference mockup's global `#tipbox` handler so any
// element anywhere in the app can show a tooltip just by carrying a `data-tip="…"` attribute (gate-chip
// (?) marks, key status dots, editable caps, the engine dot, …). Mounted once in the app shell. Styling
// lives in globals.css (`#tipbox`). No portal needed — it appends a single fixed node to <body>.

import { useEffect } from "react";

// Deliberate hover delay (ms): you must rest on an element for ~2/3 s before its tip appears. This is what
// keeps tooltips from flickering as the cursor merely PASSES over a row of cropped names — they only show
// when you actually pause to read one.
const TIP_DELAY = 650;

export function TipLayer() {
  useEffect(() => {
    const tip = document.createElement("div");
    tip.id = "tipbox";
    document.body.appendChild(tip);

    let timer: ReturnType<typeof setTimeout> | undefined;
    let current: HTMLElement | null = null;

    function hide() {
      tip.classList.remove("on");
    }

    function show(target: HTMLElement) {
      const text = target.getAttribute("data-tip") ?? "";
      if (!text) return;
      tip.textContent = text;
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

    function onOver(e: MouseEvent) {
      const target = (e.target as HTMLElement | null)?.closest<HTMLElement>("[data-tip]") ?? null;
      if (target === current) return; // same element (or still none) — let any pending timer ride
      current = target;
      clearTimeout(timer);
      hide();
      if (target) timer = setTimeout(() => show(target), TIP_DELAY);
    }

    document.addEventListener("mouseover", onOver);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mouseover", onOver);
      tip.remove();
    };
  }, []);

  return null;
}
