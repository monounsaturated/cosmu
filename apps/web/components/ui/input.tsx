"use client";

// module: the shared form-input primitives. Before this, the same Tailwind class strings were
// copy-pasted across the strategies table, the data-table page, the live cap inputs, and the
// launch-live modal — each a vibe-coded one-off. These three primitives capture the EXACT existing
// look (no visual change) so every input in the app shares one focus ring, one border, one rhythm.
//
//   <Input/>        — the base text/number field (border + bg-background/60 + iris focus ring).
//   <SearchInput/>  — a magnifier-prefixed search box with an optional clear button.
//   <MoneyInput/>   — a $-prefixed numeric field on a muted surface, clamped to ≥ 0.

import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

// Base field. The class string is the single source of truth for "what a Cosmu input looks like".
const inputBase =
  "h-8 w-full rounded-md border border-border bg-background/60 px-2.5 text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-quiet hover:border-border-strong focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(inputBase, className)} {...props} />;
}

// Search box: magnifier on the left, optional clear "×" on the right when `onClear` + a value exist.
export function SearchInput({
  className,
  onClear,
  value,
  ...props
}: ComponentProps<"input"> & { onClear?: () => void }) {
  const showClear = onClear && typeof value === "string" && value.length > 0;
  return (
    <div className={cn("relative w-full max-w-xs", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-quiet" />
      <input
        value={value}
        className={cn(inputBase, "pl-8", showClear ? "pr-8" : "pr-2")}
        {...props}
      />
      {showClear ? (
        <button
          type="button"
          onClick={onClear}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-quiet transition-colors hover:text-foreground"
          aria-label="Clear search"
        >
          <X className="size-3.5" />
        </button>
      ) : null}
    </div>
  );
}

// Labelled $-prefixed numeric input on a muted surface. Clamps to ≥ 0 — the shape used by the live
// cap controls and the launch-live amount field.
export function MoneyInput({
  label,
  value,
  onChange,
  min = 0,
  hint
}: {
  label: ReactNode;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  hint?: ReactNode;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="block">
      <span className="text-[11px] uppercase tracking-wide text-quiet">{label}</span>
      <div className="mt-1 flex items-center rounded-md border border-border bg-surface-2/40 px-2.5 transition-colors focus-within:border-iris/60 focus-within:ring-2 focus-within:ring-ring/40">
        <span className="text-[12px] text-quiet">$</span>
        <input
          id={id}
          type="number"
          min={min}
          value={value}
          onChange={(e) => onChange(Math.max(min, Number(e.target.value)))}
          className="w-full bg-transparent py-2 pl-1 text-[13px] tabular text-foreground outline-none"
        />
      </div>
      {hint ? <span className="mt-1 block text-[11px] text-quiet">{hint}</span> : null}
    </label>
  );
}
