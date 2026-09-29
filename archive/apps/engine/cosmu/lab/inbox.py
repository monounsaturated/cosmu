# intent: the strategies/inbox scanner — on engine startup AND via `python3 -m cosmu.lab.inbox`, scan
# strategies/inbox/*.{md,pine,json}, translate each to a typed StrategySpec (REUSE strategy/pine for .pine and
# lab/author for .md briefs; .json is a serialized StrategySpec), and feed survivors into the Lab by running them
# through the DETERMINISTIC FarmLoop screen/gate as extra seeds. Idempotent: each file's content-hash is recorded
# as an event so an unchanged file is never re-imported. invariants: LLM-OPTIONAL (offline pine/author path),
# the deterministic scorer/gate decide survival, fully offline-safe (no keys/network), reproducible.

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.market import MarketDataProvider
from cosmu.evolution.loop import CohortSummary, FarmLoop
from cosmu.knowledge.store import Store
from cosmu.lab.author import draft_from_brief
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

# The canonical inbox: apps/engine/strategies/inbox (parents[2] == apps/engine). It lives UNDER apps/engine so
# the Railway image — built from apps/engine — actually ships it and this scanner reads the same files authors
# write (scripts/seed_inbox_strategies.py targets the same path). Resolved relative to this file (CWD-agnostic).
_INBOX_DIR = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
_SUPPORTED = (".md", ".pine", ".json")
# Filenames that are documentation, never strategy specs — skipped by the scanner even though a .md README
# parses into a draft spec.
_DOC_STEMS = frozenset({"readme"})


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


# Operator-dropped "vibe" ideas land as brief files prefixed so they're easy to spot among authored specs.
_QUEUE_PREFIX = "idea-"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "idea"


@dataclass
class QueuedIdea:
    filename: str
    name: str
    path: str
    content_hash: str


@dataclass
class QueuedIdeaRow:
    filename: str
    name: str
    ts: str
    status: str  # "queued" (awaiting the next scan) | "imported" (scanned into the Lab)


def queue_idea(store: Store, text: str, *, name: str | None = None, inbox_dir: Path | None = None) -> QueuedIdea:
    """Persist an operator's natural-language strategy 'vibe' as a `.md` brief in strategies/inbox/ so the next
    boot scan / autonomy tick translates it into a typed StrategySpec and routes it through the DETERMINISTIC Gate.
    Writes the file AND records an audited `inbox_queued` event (with the content-hash the scanner later matches on).
    This never authors a spec or moves money — it only queues prose; the Gate alone disposes."""
    body = (text or "").strip()
    if not body:
        raise ValueError("idea text is empty")
    directory = inbox_dir or _INBOX_DIR
    directory.mkdir(parents=True, exist_ok=True)
    title = (name or body.splitlines()[0]).strip()[:80] or "Untitled idea"
    # Hash the EXACT bytes we write to disk so the recorded content_hash equals the hash the scanner computes when
    # it reads the file back — that equality is how list_queued knows a queued idea has since been imported.
    contents = body + "\n"
    chash = _content_hash(contents)
    # Content-addressed filename: the same vibe re-dropped overwrites its own file (idempotent), and the scanner's
    # content-hash idempotency means it is imported exactly once.
    filename = f"{_QUEUE_PREFIX}{_slugify(title)}-{chash[:8]}.md"
    path = directory / filename
    path.write_text(contents, encoding="utf-8")
    store.append_event(
        actor="human",
        kind="inbox_queued",
        ref_type="strategy_spec",
        payload={"path": str(path), "filename": filename, "name": title, "content_hash": chash, "chars": len(body)},
    )
    return QueuedIdea(filename=filename, name=title, path=str(path), content_hash=chash)


# Fanned exit-envelope variants land as content-addressed .json specs prefixed so they're easy to spot among
# operator vibes and authored specs.
_FAN_PREFIX = "exitfan-"


@dataclass
class QueuedExitFan:
    """Result of fanning one validated entry spec into the inbox: the base spec name, how many exit variants were
    written, and their paths. PROPOSE-ONLY — the variants sit in the inbox until the next deterministic scan routes
    them through the Gate (scan_inbox → FarmLoop → BH-FDR). This call NEVER scores or funds anything."""

    base_name: str
    variants: int
    paths: list[str] = field(default_factory=list)


def queue_exit_fan(
    base_spec: StrategySpec,
    store: Store,
    *,
    n: int | None = None,
    inbox_dir: Path | None = None,
) -> QueuedExitFan:
    """Fan ONE validated entry spec over the EXIT envelope (fan_exit_envelope) and drop each variant as a typed
    `.json` StrategySpec into strategies/inbox/, so the existing deterministic scan (scan_inbox → FarmLoop →
    BH-FDR) disposes the whole cohort. Each variant is a serialized StrategySpec — the scanner parses .json directly
    and validates it — and is written content-addressed so a re-fan of the same base is imported exactly once
    (the scanner's content-hash idempotency). An audited `inbox_queued` event is recorded per variant.

    PROPOSE-ONLY: this is the research-to-cohort hook for 'fix one edge, fan the exit envelope'. It NEVER scores,
    promotes, or moves money — the Gate alone funds. Raises ValueError (via fan_exit_envelope) if `base_spec` is
    not itself validate_spec-clean."""
    from cosmu.lab.exit_sweep import fan_exit_envelope

    variants = fan_exit_envelope(base_spec, n=n)
    directory = inbox_dir or _INBOX_DIR
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for variant in variants:
        contents = json.dumps(variant.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        chash = _content_hash(contents)
        filename = f"{_FAN_PREFIX}{_slugify(variant.name)}-{chash[:8]}.json"
        path = directory / filename
        path.write_text(contents, encoding="utf-8")
        paths.append(str(path))
        store.append_event(
            actor="master",
            kind="inbox_queued",
            ref_type="strategy_spec",
            payload={
                "path": str(path),
                "filename": filename,
                "name": variant.name,
                "content_hash": chash,
                "origin": "exit_fan",
                "base_name": base_spec.name,
            },
        )
    return QueuedExitFan(base_name=base_spec.name, variants=len(variants), paths=paths)


def list_queued(store: Store, *, limit: int = 20) -> list[QueuedIdeaRow]:
    """The operator-queued ideas, newest first. Each stays `queued` until a scan imports its content-hash, then
    flips to `imported`. Read straight off the audited event ledger — honest, never fabricated."""
    rows = store.rows(
        "SELECT ts, payload FROM events WHERE kind = 'inbox_queued' ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    out: list[QueuedIdeaRow] = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {}
        payload = payload or {}
        chash = payload.get("content_hash", "")
        status = "imported" if chash and _already_imported(store, chash) else "queued"
        out.append(QueuedIdeaRow(filename=payload.get("filename", ""), name=payload.get("name", ""), ts=r["ts"], status=status))
    return out


def _already_imported(store: Store, content_hash: str) -> bool:
    row = store.row(
        "SELECT id FROM events WHERE kind = 'inbox_imported' AND payload LIKE ? LIMIT 1",
        (f'%"content_hash": "{content_hash}"%',),
    )
    return row is not None


def _authored_by(store: Store, content_hash: str) -> str:
    """Provenance of an inbox spec for the wave-0 novelty policy: was this file written by the AGENT batch master
    (strategize/batch author with authored_by='agent') or by a HUMAN? Read off the audited authoring events
    (strategize_authored / inbox_queued), matched on the file's content_hash. Defaults to 'human' — we only
    HARD-SKIP a near-dup on POSITIVE evidence it was machine-authored, so an operator's intentional inbox spec is
    never silently dropped. Best-effort: any read hiccup degrades to 'human' (the conservative, never-drop side)."""
    try:
        # Only the AUTHORING events carry real provenance — inbox_imported is always recorded actor='human' by the
        # scanner, so it would mask an agent file's true origin. Match on the authoring events alone.
        row = store.row(
            "SELECT actor FROM events WHERE kind IN ('strategize_authored', 'inbox_queued') "
            "AND payload LIKE ? ORDER BY id ASC LIMIT 1",
            (f'%"content_hash": "{content_hash}"%',),
        )
    except Exception:  # noqa: BLE001 — provenance is advisory; a read hiccup must never break the scan
        return "human"
    actor = (row or {}).get("actor") if row else None
    return "agent" if actor == "agent" else "human"


def _spec_from_frontmatter(text: str) -> StrategySpec | None:
    """A `.md` file may lead with a YAML front-matter block (`---` … `---`) that IS a typed StrategySpec — the
    authored format the inbox README documents. Parse it directly so the authored edge (named features, modules,
    fitted param_space) is preserved verbatim, instead of being thrown away by the prose-heuristic drafter.
    `risk` is optional here (RiskRules is fully defaultable) and any extra prose keys (e.g. `strategy:`, `modules:`)
    are ignored by the model. Returns None when there is no front-matter or it isn't a spec — caller falls back
    to draft_from_brief for genuine prose briefs."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None
    block, sep, _body = stripped[3:].partition("\n---")
    if not sep:
        return None
    try:
        import yaml

        data = yaml.safe_load(block)
    except Exception:  # noqa: BLE001 — malformed YAML → not a spec; degrade to the prose-brief path
        return None
    # Only treat it as a typed spec when it carries the structural fields; otherwise it's prose-with-metadata.
    if not isinstance(data, dict) or not ("entry" in data and "param_space" in data):
        return None
    data.setdefault("risk", {})  # authored briefs omit risk to use RiskRules defaults
    try:
        return StrategySpec.model_validate(data)
    except Exception:  # noqa: BLE001 — incomplete/invalid front-matter → fall back to the brief drafter
        return None


def _spec_from_file(path: Path, text: str) -> tuple[StrategySpec | None, str, list[str]]:
    """Translate one inbox file to a typed StrategySpec. Reuses translate_pine (.pine), StrategySpec parsing
    (.json), front-matter parsing (.md with a typed `---` block), and draft_from_brief (.md prose). Returns
    (spec | None, kind, issues)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pine":
            tr = translate_pine(text)
            return tr.spec, "pine", validate_spec(tr.spec)
        if suffix == ".json":
            spec = StrategySpec.model_validate(json.loads(text))
            return spec, "json", validate_spec(spec)
        if suffix == ".md":
            fm_spec = _spec_from_frontmatter(text)
            if fm_spec is not None:
                return fm_spec, "md-spec", validate_spec(fm_spec)
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
    new_specs_authored_by: list[str] = []  # parallel provenance for the wave-0 novelty policy (human vs agent)
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in _SUPPORTED or not path.is_file():
            continue
        # Docs that live alongside specs (README, *TEMPLATE) are not strategies — a .md README happily parses
        # into a draft spec, so without this guard it would be imported as a bogus Version. Skip them quietly.
        if path.stem.lower() in _DOC_STEMS or path.stem.upper().endswith("TEMPLATE"):
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
        # Provenance for the wave-0 novelty policy: resolved from the authoring events BEFORE we record the
        # inbox_imported event below (so this file's own import never masks its true origin). Human by default.
        new_specs_authored_by.append(_authored_by(store, chash))
        report.imported.append(record)
        store.append_event(
            actor="human",
            kind="inbox_imported",
            ref_type="strategy_spec",
            payload={"path": str(path), "kind": kind, "content_hash": chash, "name": spec.name},
        )

    if run_cohort and new_specs:
        loop = FarmLoop(settings=store.settings, store=store, market_data=market_data)
        report.cohort = loop.run_cohort(
            cohort_size=len(new_specs), explore_pct=0.0,
            extra_seeds=new_specs, extra_seeds_authored_by=new_specs_authored_by,
        )
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
