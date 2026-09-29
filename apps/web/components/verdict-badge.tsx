// The one verdict badge used across the page: same size, icon + label, colour by verdict.
import { VERDICT_ICON, type Verdict } from "@/lib/showcase";
import { Icon } from "./icon";

export function VerdictBadge({ v, style }: { v: Verdict; style?: React.CSSProperties }) {
  return (
    <span className={`verdict v-${v.cls}`} style={style}>
      <Icon name={VERDICT_ICON[v.cls]} size={14} />
      {v.text}
    </span>
  );
}
