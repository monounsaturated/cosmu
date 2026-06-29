# intent: an OFFLINE, READ-ONLY reviewer for the strategy-authoring railway — make a directory of N hand/agent-
# authored specs as easy to eyeball as 1, BEFORE they hit a boot-scan or the Gate. For each inbox file it REUSES
# the existing authoring stack — _spec_from_file (load .md/.pine/.json → typed StrategySpec), validate_spec
# (PASS/FAIL + reasons), derive_facets (the facet vocabulary) — and surfaces the key spec facts. Across the set it
# computes pairwise structural_distance (the novelty/dedup primitive) and clusters near-duplicates, so the specs
# that would burn the Gate's BH-FDR budget are visible up front. invariants: NEVER mutates the DB or the inbox
# files (no Store, no writes, no network); robust to a malformed spec (reported FAILED, never crashes the scan);
# fully deterministic. This is a lint/preview, NOT the Gate — it disposes nothing and moves no money.

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cosmu.knowledge.memory import structural_distance
from cosmu.lab.inbox import _INBOX_DIR, _spec_from_file
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec
from cosmu.strategy.taxonomy import derive_facets

# Mirror the scanner's supported suffixes + doc-skip rules so the lint sees EXACTLY the same file set a real
# boot-scan would (no surprises between "lint says clean" and "the scanner imports this").
_SUPPORTED = (".md", ".pine", ".json")
_DOC_STEMS = frozenset({"readme"})

# Near-duplicate threshold on structural_distance (Jaccard over entry-feature sets + bar_size penalty; 0 =
# identical structure, 1 = disjoint). Two specs with distance STRICTLY BELOW this are treated as near-dups and
# unioned into the same cluster. 0.25 matches novelty_gate's min_distance — the same bar the live-population
# monoculture guard uses — so the lint flags exactly what the gate's novelty check would later reject as
# too-similar. Tunable via --dup-threshold for a stricter/looser pre-screen.
_DEFAULT_DUP_THRESHOLD = 0.25


@dataclass
class LintedSpec:
    """One inbox file's lint result. `cluster` is the dup-cluster id (-1 = singleton / no near-dup);
    `nearest_dist`/`nearest` are the closest OTHER spec by structural_distance (None when nothing to compare)."""

    path: str
    filename: str
    name: str
    kind: str                  # pine | json | md-spec | brief | <suffix> (parse failures keep the raw suffix)
    status: str                # "PASS" | "FAIL"
    issues: list[str] = field(default_factory=list)
    # Surfaced spec facts (honest "—" when the spec did not load).
    strategy_kind: str = "—"
    lane: str = "—"
    direction: str = "—"
    entry_mechanism: str = "—"
    exit_mechanism: str = "—"
    features: list[str] = field(default_factory=list)
    universe: str = "—"
    horizon: str = "—"
    signal_family: str = "—"
    edge_type: str = "—"
    # Cross-set dedup facts.
    nearest: str | None = None
    nearest_dist: float | None = None
    cluster: int = -1


@dataclass
class LintReport:
    inbox_dir: str
    scanned: int
    passed: list[LintedSpec] = field(default_factory=list)
    failed: list[LintedSpec] = field(default_factory=list)
    # cluster_id -> the filenames in that near-dup cluster (size >= 2 only).
    dup_clusters: dict[int, list[str]] = field(default_factory=dict)

    def all_rows(self) -> list[LintedSpec]:
        """Every linted row in scan order (passed first, then failed) — the manifest table iterates this."""
        return [*self.passed, *self.failed]


def _is_spec_file(path: Path) -> bool:
    """The scanner's file filter, mirrored: a real spec file (supported suffix, not a README/TEMPLATE doc)."""
    if path.suffix.lower() not in _SUPPORTED or not path.is_file():
        return False
    if path.stem.lower() in _DOC_STEMS or path.stem.upper().endswith("TEMPLATE"):
        return False
    return True


def _entry_mechanism(spec: StrategySpec) -> str:
    """A compact, human read of the entry trigger: 'event' for event/regime specs (their trigger is the payload
    match, not a price condition), else the entry conditions as 'feature op param'. '—' if absent."""
    if getattr(spec, "strategy_kind", "indicator") in ("event", "regime"):
        return "event-payload-match"
    parts = [f"{c.feature.name} {c.op} {c.threshold.param}" for c in spec.entry]
    return " AND ".join(parts) if parts else "—"


def _exit_mechanism(spec: StrategySpec) -> str:
    """A compact read of the exit envelope: the fixed stop/take params + any signal-exits + composable legs."""
    bits: list[str] = [f"stop={spec.exit.stop_loss.param}", f"tp={spec.exit.take_profit.param}"]
    if spec.exit.time_stop_days is not None:
        bits.append(f"time_stop={spec.exit.time_stop_days.param}")
    if spec.exit.signal_exits:
        bits.append(f"signal_exits={len(spec.exit.signal_exits)}")
    if spec.exit.plan is not None and spec.exit.plan.multi_tp:
        bits.append(f"multi_tp={len(spec.exit.plan.multi_tp)}")
    if spec.exit.trailing_stop is not None:
        bits.append("trailing_stop")
    if spec.exit.atr_mult is not None:
        bits.append("atr_stop")
    return ", ".join(bits)


def _universe_str(spec: StrategySpec) -> str:
    u = spec.universe
    venues = "/".join(u.venues) if u.venues else "—"
    classes = "/".join(u.asset_classes) if u.asset_classes else "—"
    return f"{classes}@{venues} (min={u.min_instruments})"


def _horizon_str(spec: StrategySpec) -> str:
    h = spec.horizon
    tfs = "+".join(h.timeframes()) if hasattr(h, "timeframes") else h.bar_size
    return f"{tfs} hold {h.min_hold_days}-{h.max_hold_days}d"


def _lint_one(path: Path) -> tuple[LintedSpec, StrategySpec | None]:
    """Load + validate one file, surface its facts. Returns the row AND the parsed spec (None on failure) so the
    caller can run cross-set structural_distance only over the specs that actually parsed."""
    text = path.read_text(encoding="utf-8", errors="replace")
    spec, kind, issues = _spec_from_file(path, text)
    row = LintedSpec(
        path=str(path),
        filename=path.name,
        name=(spec.name if spec else path.stem),
        kind=kind,
        status="PASS" if (spec is not None and not issues) else "FAIL",
        issues=list(issues),
    )
    if spec is None:
        # Parse failure already captured in `issues` by _spec_from_file (e.g. "parse_error:..."); nothing more
        # to surface — the malformed file is reported FAILED, not crashed.
        return row, None

    # validate_spec is also run inside _spec_from_file for most kinds, but call it directly so the contract is
    # explicit here and the lint never depends on that internal detail. Merge + dedup (order-stable): validate_spec
    # can emit the same issue twice (e.g. an unknown feature referenced by BOTH an entry condition and the funding
    # leg), so collapse repeats while preserving first-seen order.
    merged: list[str] = []
    for issue in [*row.issues, *validate_spec(spec)]:
        if issue not in merged:
            merged.append(issue)
    row.issues = merged
    if row.issues:
        row.status = "FAIL"

    facets = derive_facets(spec.model_dump(mode="json"), origin="inbox")
    row.strategy_kind = getattr(spec, "strategy_kind", "indicator")
    row.lane = getattr(spec, "lane", "gate")
    row.direction = {1: "long", -1: "short", 0: "signal"}.get(getattr(spec, "direction", 1), "—")
    row.entry_mechanism = _entry_mechanism(spec)
    row.exit_mechanism = _exit_mechanism(spec)
    row.features = list(facets.features)
    row.universe = _universe_str(spec)
    row.horizon = _horizon_str(spec)
    row.signal_family = facets.signal_family_label
    row.edge_type = facets.edge_type
    return row, spec


class _UnionFind:
    """Tiny union-find for clustering near-dup specs by transitive structural similarity (A~B, B~C => one cluster)."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, i: int) -> int:
        while self._parent[i] != i:
            self._parent[i] = self._parent[self._parent[i]]
            i = self._parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self._parent[max(ri, rj)] = min(ri, rj)


def _cluster_near_dups(
    rows: list[LintedSpec],
    specs: list[StrategySpec],
    threshold: float,
) -> dict[int, list[str]]:
    """Compute pairwise structural_distance over the parsed specs, record each row's nearest neighbour, and
    union near-dups (distance < threshold) into clusters. Mutates `rows` (nearest/nearest_dist/cluster) and
    returns {cluster_id: [filenames]} for clusters of size >= 2. cluster_id is the smallest row index in the
    cluster (stable, deterministic)."""
    n = len(specs)
    if n < 2:
        return {}
    uf = _UnionFind(n)
    best: list[tuple[float, int] | None] = [None] * n  # (dist, j) nearest OTHER spec for row i
    for i in range(n):
        for j in range(i + 1, n):
            dist = structural_distance(specs[i], specs[j])
            for a, b in ((i, j), (j, i)):
                if best[a] is None or dist < best[a][0]:
                    best[a] = (dist, b)
            if dist < threshold:
                uf.union(i, j)

    for i in range(n):
        if best[i] is not None:
            d, j = best[i]
            rows[i].nearest = rows[j].filename
            rows[i].nearest_dist = d

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    clusters: dict[int, list[str]] = {}
    for root, members in groups.items():
        if len(members) < 2:
            continue
        for i in members:
            rows[i].cluster = root
        clusters[root] = [rows[i].filename for i in members]
    return clusters


def lint_inbox(inbox_dir: Path | None = None, *, dup_threshold: float = _DEFAULT_DUP_THRESHOLD) -> LintReport:
    """Walk the inbox, load + validate + facet each spec, and cluster near-duplicates. READ-ONLY: no DB, no
    writes, no network. Robust to a malformed file (reported FAILED). Deterministic."""
    directory = inbox_dir or _INBOX_DIR
    report = LintReport(inbox_dir=str(directory), scanned=0)
    if not directory.exists():
        return report

    rows: list[LintedSpec] = []
    parsed_rows: list[LintedSpec] = []
    parsed_specs: list[StrategySpec] = []
    for path in sorted(directory.iterdir()):
        if not _is_spec_file(path):
            continue
        report.scanned += 1
        try:
            row, spec = _lint_one(path)
        except Exception as exc:  # noqa: BLE001 — belt-and-braces: never let one bad file crash the whole lint
            row = LintedSpec(
                path=str(path), filename=path.name, name=path.stem, kind=path.suffix.lstrip("."),
                status="FAIL", issues=[f"lint_error:{exc}"],
            )
            spec = None
        rows.append(row)
        if spec is not None:
            parsed_rows.append(row)
            parsed_specs.append(spec)

    report.dup_clusters = _cluster_near_dups(parsed_rows, parsed_specs, dup_threshold)
    report.passed = [r for r in rows if r.status == "PASS"]
    report.failed = [r for r in rows if r.status == "FAIL"]
    return report


# --------------------------------------------------------------------------- rendering


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def render_table(report: LintReport) -> str:
    """The human-readable manifest: one row per spec — status · kind · features · facets · nearest-neighbour
    distance · dup-cluster id. Dup clusters are listed below the table so near-dups are visible up front."""
    lines: list[str] = []
    lines.append(f"INBOX LINT — {report.inbox_dir}")
    lines.append(
        f"  scanned={report.scanned}  PASS={len(report.passed)}  FAIL={len(report.failed)}  "
        f"dup_clusters={len(report.dup_clusters)}"
    )
    lines.append("")
    header = ["STATUS", "NAME", "KIND", "EDGE", "FAMILY", "FEATURES", "NEAREST", "CLUSTER"]
    widths = [6, 30, 8, 13, 17, 26, 14, 7]
    lines.append("  " + "  ".join(h.ljust(w) for h, w in zip(header, widths)))
    lines.append("  " + "  ".join("-" * w for w in widths))
    for r in report.all_rows():
        nearest = "—" if r.nearest_dist is None else f"{r.nearest_dist:.2f}"
        cluster = "—" if r.cluster < 0 else f"#{r.cluster}"
        feats = ",".join(r.features) if r.features else "—"
        cells = [
            r.status,
            _truncate(r.name, widths[1]),
            _truncate(r.kind, widths[2]),
            _truncate(r.edge_type, widths[3]),
            _truncate(r.signal_family, widths[4]),
            _truncate(feats, widths[5]),
            nearest,
            cluster,
        ]
        lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(cells, widths)))

    if report.dup_clusters:
        lines.append("")
        lines.append("  NEAR-DUPLICATE CLUSTERS (would compete for the same Gate FDR budget):")
        for cid, members in sorted(report.dup_clusters.items()):
            lines.append(f"    #{cid}: {', '.join(members)}")

    failed_with_issues = [r for r in report.failed if r.issues]
    if failed_with_issues:
        lines.append("")
        lines.append("  FAIL REASONS:")
        for r in failed_with_issues:
            lines.append(f"    {r.filename}: {', '.join(r.issues)}")
    return "\n".join(lines)


def to_json(report: LintReport) -> dict:
    """Machine-readable manifest: passed / failed / dup-clusters, each row fully serialized."""
    return {
        "inbox_dir": report.inbox_dir,
        "scanned": report.scanned,
        "passed": [asdict(r) for r in report.passed],
        "failed": [asdict(r) for r in report.failed],
        "dup_clusters": {str(cid): members for cid, members in sorted(report.dup_clusters.items())},
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline, read-only lint of strategies/inbox/*.{md,pine,json}: validate + facet each spec and "
            "cluster near-duplicates BEFORE they hit a boot-scan or the Gate. Mutates nothing."
        ),
    )
    parser.add_argument("--inbox", type=Path, default=None, help="inbox directory (default: the canonical strategies/inbox)")
    parser.add_argument("--json", type=Path, default=None, help="also write the machine-readable manifest to this file")
    parser.add_argument(
        "--dup-threshold", type=float, default=_DEFAULT_DUP_THRESHOLD,
        help=f"structural_distance below which two specs are near-dups (default {_DEFAULT_DUP_THRESHOLD})",
    )
    parser.add_argument("--json-only", action="store_true", help="print ONLY the JSON manifest to stdout (no table)")
    args = parser.parse_args(argv)

    report = lint_inbox(args.inbox, dup_threshold=args.dup_threshold)
    payload = to_json(report)

    if args.json_only:
        print(json.dumps(payload, indent=2))
    else:
        print(render_table(report))
        print()
        print(json.dumps(payload, indent=2))

    if args.json is not None:
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if not args.json_only:
            print(f"\n[json written] {args.json}")

    # Exit non-zero when any spec FAILs so a CI/pre-author hook can gate on a clean inbox; 0 = all clear.
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(_main())
