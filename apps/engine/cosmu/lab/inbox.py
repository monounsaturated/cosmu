# intent: the strategies/inbox scanner — on engine startup AND via `python3 -m cosmu.lab.inbox`, scan
# strategies/inbox/*.{md,pine,json}, translate each to a typed StrategySpec (REUSE strategy/pine for .pine and
# lab/author for .md briefs; .json is a serialized StrategySpec), and feed survivors into the Lab by running them
# through the DETERMINISTIC FarmLoop screen/gate as extra seeds. Idempotent: each file's content-hash is recorded
# as an event so an unchanged file is never re-imported. invariants: LLM-OPTIONAL (offline pine/author path),
# the deterministic scorer/gate decide survival, fully offline-safe (no keys/network), reproducible.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.market import Bar, MarketDataProvider
from cosmu.evolution.loop import CohortSummary, FarmLoop
from cosmu.knowledge.store import Store
from cosmu.lab.author import draft_from_brief
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

# The repo-root strategies/inbox directory. Resolved relative to this file so it works from any CWD.
_INBOX_DIR = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
_SUPPORTED = (".md", ".pine", ".json")


@dataclass
class ImportedFile:
    path: str
    kind: str               # "pine" | "brief" | "json"
    content_hash: str
    name: str
    valid: bool
    imported: bool = False  # False => skipped (unchanged) or invalid
    issues: list[str] = field(default_factory=list)


@dataclass
class InboxReport:
    inbox_dir: str
    scanned: int
    imported: list[ImportedFile] = field(default_factory=list)
    skipped: list[ImportedFile] = field(default_factory=list)
    cohort: CohortSummary | None = None


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _already_imported(store: Store, content_hash: str) -> bool:
    row = store.row(
        "SELECT id FROM events WHERE kind = 'inbox_imported' AND payload LIKE ? LIMIT 1",
        (f'%"content_hash": "{content_hash}"%',),
    )
    return row is not None


def _spec_from_file(path: Path, text: str) -> tuple[StrategySpec | None, str, list[str]]:
    """Translate one inbox file to a typed StrategySpec. Reuses translate_pine (.pine), draft_from_brief (.md),
    and StrategySpec parsing (.json). Returns (spec | None, kind, issues)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pine":
            tr = translate_pine(text)
            return tr.spec, "pine", validate_spec(tr.spec)
        if suffix == ".json":
            spec = StrategySpec.model_validate(json.loads(text))
            return spec, "json", validate_spec(spec)
        if suffix == ".md":
            draft = draft_from_brief(text, llm_enabled=False)
            return draft.spec, "brief", draft.issues or validate_spec(draft.spec)
    except Exception as exc:  # noqa: BLE001 — a malformed file is reported, never crashes the scan
        return None, suffix.lstrip("."), [f"parse_error:{exc}"]
    return None, suffix.lstrip("."), ["unsupported"]


def scan_inbox(
    store: Store,
    *,
    inbox_dir: Path | None = None,
    market_data: MarketDataProvider | None = None,
    run_cohort: bool = True,
) -> InboxReport:
    """Scan the inbox, translate new/changed files to specs, and (idempotently) feed valid ones into the Lab via
    one deterministic FarmLoop cohort (extra_seeds). Unchanged files (same content-hash) are skipped. Offline-safe."""
    directory = inbox_dir or _INBOX_DIR
    report = InboxReport(inbox_dir=str(directory), scanned=0)
    if not directory.exists():
        return report

    new_specs: list[StrategySpec] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in _SUPPORTED or not path.is_file():
            continue
        report.scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        chash = _content_hash(text)
        spec, kind, issues = _spec_from_file(path, text)
        name = spec.name if spec else path.stem
        record = ImportedFile(path=str(path), kind=kind, content_hash=chash, name=name, valid=bool(spec and not issues), issues=issues)

        if _already_imported(store, chash):
            record.imported = False
            report.skipped.append(record)
            continue
        if spec is None or issues:
            record.imported = False
            report.skipped.append(record)
            store.append_event(
                actor="human",
                kind="inbox_rejected",
                ref_type="strategy_spec",
                payload={"path": str(path), "kind": kind, "content_hash": chash, "issues": issues},
            )
            continue

        record.imported = True
        new_specs.append(spec)
        report.imported.append(record)
        store.append_event(
            actor="human",
            kind="inbox_imported",
            ref_type="strategy_spec",
            payload={"path": str(path), "kind": kind, "content_hash": chash, "name": spec.name},
        )

    if run_cohort and new_specs:
        loop = FarmLoop(settings=store.settings, store=store, market_data=market_data)
        report.cohort = loop.run_cohort(cohort_size=len(new_specs), explore_pct=0.0, extra_seeds=new_specs)
    return report


def _print(report: InboxReport) -> None:
    print(f"INBOX SCAN — {report.inbox_dir}")
    print(f"  scanned={report.scanned} imported={len(report.imported)} skipped={len(report.skipped)}")
    for f in report.imported:
        print(f"    [import:{f.kind}] {f.name}  ({f.path})")
    for f in report.skipped:
        why = "unchanged" if f.valid else f"invalid: {f.issues}"
        print(f"    [skip] {f.name}  · {why}")
    if report.cohort is not None:
        c = report.cohort
        print(f"  GATED (deterministic): generated={c.generated} passed={c.passed} killed={c.killed} kill_rate={c.kill_rate}")


def _offline_store() -> Store:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="cosmu-inbox-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/inbox.sqlite3", openrouter_api_key=None))


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Scan strategies/inbox/*.{md,pine,json} → typed specs → Lab (idempotent, offline).")
    parser.add_argument("--no-cohort", action="store_true", help="translate + record only; do not run the screen cohort")
    args = parser.parse_args(argv)

    # CLI runs against the configured store so a real scheduler imports into the live Lab; offline-safe (cached bars).
    store = Store(Settings())
    report = scan_inbox(store, run_cohort=not args.no_cohort)
    _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
