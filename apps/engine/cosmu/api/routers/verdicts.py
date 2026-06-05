# intent: parsed phase0-*-verdict.md research history; inputs: none; outputs: VerdictsResponse; invariants: read-only over docs/reports; honest empty when no reports exist.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api.models import VerdictRow, VerdictsResponse

router = APIRouter()


@router.get("/verdicts", response_model=VerdictsResponse)
def verdicts_list() -> VerdictsResponse:
    """Parse docs/reports/phase0-*-verdict.md and return structured per-thesis verdicts."""
    import re
    from pathlib import Path

    # routers/verdicts.py → parents[5] is the repo root (apps/engine/cosmu/api/routers/verdicts.py).
    reports_dir = Path(__file__).parents[5] / "docs" / "reports"
    items: list[VerdictRow] = []

    try:
        paths = sorted(reports_dir.glob("phase0-*-verdict.md"))
    except Exception:
        return VerdictsResponse(rows=[])

    for path in paths:
        stem = path.stem  # e.g. "phase0-carry-verdict"
        slug = re.sub(r"^phase0-|-verdict$", "", stem)
        name = " ".join(p.capitalize() for p in slug.split("-"))

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        verdict = "FAIL"
        _patterns = [
            r"##\s+3\.[^#\n]+\*\*(PASS|FAIL|INSUFFICIENT-DATA|DATA-BLOCKED)\*\*",
            r"###\s+\*\*(FAIL|PASS|INSUFFICIENT-DATA|DATA-BLOCKED)\*\*",
            r"\*\*Verdict:\s+(FAIL|PASS|INSUFFICIENT-DATA|DATA-BLOCKED)",
            r"Powered\s+(FAIL|PASS)",
        ]
        for pat in _patterns:
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                verdict = m.group(1).upper()
                break
        if verdict.startswith("FAIL"):
            verdict = "FAIL"

        # Extract date from content (e.g. "Run 2026-06-05" or "Pre-registered 2026-06-05")
        date = ""
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", content)
        if dm:
            date = dm.group(1)

        reason = ""
        m = re.search(r"\*\*Headline:\*\*\s+(.+?)(?:\n|$)", content)
        if m:
            reason = re.sub(r"[*`]", "", m.group(1)).strip()
        if not reason:
            m = re.search(r"###\s+\*\*(?:FAIL|PASS)[^*]*\*\*\s*(?:—\s*)?(.+?)(?:\n|$)", content)
            if m:
                reason = re.sub(r"[*`]", "", m.group(1)).strip()
        if not reason:
            m = re.search(r"\*\*Verdict:[^*]+\*\*\s*(.+?)(?:\.|$)", content)
            if m:
                reason = re.sub(r"[*`]", "", m.group(1)).strip()
        if len(reason) > 120:
            reason = reason[:117] + "…"

        items.append(VerdictRow(
            slug=slug, thesis=name, id=slug, date=date,
            status=verdict, reason=reason,
        ))

    return VerdictsResponse(rows=items)
