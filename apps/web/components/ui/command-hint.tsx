"use client";

// module: CommandHint — the cockpit's "run /command" hover modal. Cosmu's screens SHOW; the doing
// happens in Claude Code. Rather than bury that in prose, any widget can drop a small mono chip that,
// on hover (and click, for touch), reveals a compact card: the slash command, what it does, when to
// reach for it, and a one-tap copy. Logic + a button, not a wall of text. Pure-client, reduced-motion
// aware, closes on outside-click / Escape. It only tells you what to run — it never runs anything.

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Terminal } from "lucide-react";
import { COMMANDS } from "@/lib/commands";
import { cn } from "@/lib/utils";

export function CommandHint({ cmd, className, label }: { cmd: string; className?: string; label?: string }) {
  const entry = COMMANDS[cmd];
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  // Close on outside-click and Escape — standard popover dismissal.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!entry) return null;
  const Icon = entry.icon ?? Terminal;

  async function copy() {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked — the command is still visible to copy by hand */
    }
  }

  return (
    <span
      ref={ref}
      className={cn("group/cmd relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-md border border-border/70 bg-surface-2/40 px-1.5 py-0.5 font-mono text-[11px] text-iris-soft outline-none transition-colors hover:border-iris/50 hover:bg-iris/10 focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <Terminal className="size-3" />
        {label ?? cmd}
      </button>

      <span
        role="tooltip"
        className={cn(
          "absolute right-0 top-full z-40 mt-2 w-[min(82vw,288px)] origin-top-right rounded-lg border border-border bg-surface p-3 text-left shadow-card transition-all duration-150",
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        )}
      >
        <span className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 font-mono text-[12px] font-medium text-foreground">
            <Icon className="size-3.5 text-iris-soft" />
            {cmd}
          </span>
          <button
            type="button"
            onClick={copy}
            aria-label={`Copy ${cmd}`}
            className="inline-flex items-center gap-1 rounded-md border border-border/70 px-1.5 py-0.5 text-[10.5px] text-quiet transition-colors hover:border-border hover:text-foreground"
          >
            {copied ? <Check className="size-3 text-up" /> : <Copy className="size-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </span>
        <span className="mt-2 block text-[11.5px] leading-relaxed text-muted">{entry.what}</span>
        <span className="mt-1.5 block text-[11px] leading-relaxed text-quiet">
          <span className="text-muted">When:</span> {entry.when}
        </span>
        <span className="mt-2 block border-t border-border/50 pt-2 text-[10.5px] leading-relaxed text-quiet">
          Run it in Claude Code — the cockpit shows, Claude Code does. The Gate alone disposes; this only proposes.
        </span>
      </span>
    </span>
  );
}
