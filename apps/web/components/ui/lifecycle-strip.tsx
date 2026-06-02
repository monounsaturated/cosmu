// module: the one-glance mental model. Cosmu has exactly four stages and money only moves at the last
// one. This strip is the canonical answer to "what's the difference between Lab / Research / Paper / Live?"
// Each stage is a real link to its route, so the strip doubles as primary navigation + a how-it-works legend.

import Link from "next/link";
import { Microscope, Filter, Wallet, Radio, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

type Stage = {
  href: string;
  label: string;
  tag: string;
  blurb: string;
  icon: typeof Microscope;
};

// Research == Lab (the discovery stage) — called out explicitly because the owner found the overlap unclear.
const STAGES: Stage[] = [
  { href: "/lab", label: "Lab", tag: "Discover", blurb: "Research & author candidates. (Lab = Research.)", icon: Microscope },
  { href: "/strategies", label: "Strategies", tag: "Screen", blurb: "The Gate scores them. Only edge that beats fees survives.", icon: Filter },
  { href: "/paper", label: "Paper", tag: "Forward-test", blurb: "Survivors trade a paper wallet on real prices.", icon: Wallet },
  { href: "/live", label: "Live", tag: "Real money", blurb: "You promote a proven sleeve. 5 interlocks, off by default.", icon: Radio }
];

export function LifecycleStrip() {
  return (
    <section aria-label="How Cosmu works">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-quiet">how it works</span>
        <span className="text-[11px] text-quiet">— discover → screen → forward-test → live. Money only moves at the last step.</span>
      </div>
      <ol className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {STAGES.map((s, i) => {
          const Icon = s.icon;
          const isLive = s.href === "/live";
          return (
            <li key={s.href} className="relative">
              <Link
                href={s.href}
                className={cn(
                  "group flex h-full flex-col gap-1.5 rounded-lg border bg-surface-2/30 p-3 transition-colors",
                  "border-border/60 hover:border-border hover:bg-surface-2/60",
                  isLive && "opacity-90 hover:opacity-100"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <span className={cn("flex size-7 items-center justify-center rounded-md", isLive ? "bg-info/15" : "bg-iris/12")}>
                      <Icon className={cn("size-4", isLive ? "text-info" : "text-iris-soft")} />
                    </span>
                    <span className="text-[13px] font-semibold text-foreground">{s.label}</span>
                  </span>
                  <span className="text-[10px] font-medium uppercase tracking-wide text-quiet">
                    {i + 1}. {s.tag}
                  </span>
                </div>
                <p className="text-[11.5px] leading-snug text-muted">{s.blurb}</p>
              </Link>
              {i < STAGES.length - 1 && (
                <ArrowRight className="absolute -right-[11px] top-1/2 z-10 hidden size-4 -translate-y-1/2 text-quiet lg:block" aria-hidden />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
