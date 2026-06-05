# intent: parse phase0 verdict markdown files into typed rows for the /verdicts endpoint.
# No LLM, no DB — pure filesystem + regex on the static docs.

from __future__ import annotations

import re
from pathlib import Path

from cosmu.api.models import VerdictRow

_VERDICTS_DIR = Path(__file__).resolve().parents[4] / "docs" / "reports"


def _clean(s: str) -> str:
    """Strip markdown bold markers (* only) and convert link syntax to plain text.
    Underscore-emphasis is intentionally NOT stripped — column names use underscores."""
    return re.sub(r"\*{1,2}|\[([^\]]*)\]\([^)]*\)", r"\1", s).strip()


def _flt(s: str) -> float | None:
    try:
        s2 = _clean(s).replace("−", "-").replace("–", "-")  # − and –
        s2 = re.sub(r"[^0-9.\-]", "", s2)
        return float(s2) if s2 and s2 not in ("-", ".") else None
    except (ValueError, TypeError):
        return None


def _int(s: str) -> int | None:
    try:
        s2 = re.sub(r"[^0-9]", "", _clean(s))
        return int(s2) if s2 else None
    except (ValueError, TypeError):
        return None


def _parse_verdict(path: Path) -> VerdictRow:
    text = path.read_text(encoding="utf-8")

    # slug from filename: phase0-carry-verdict.md → carry
    slug = path.stem
    if slug.startswith("phase0-"):
        slug = slug[7:]
    if slug.endswith("-verdict"):
        slug = slug[:-8]

    # --- thesis & id from title line ---
    first_line = text.split("\n")[0]
    paren_m = re.search(r"\(([^)]+)\)\s*$", first_line)
    raw_id = paren_m.group(1).strip() if paren_m else ""
    id_m = re.match(r"(P0\.\d+)", raw_id)
    p0_id = id_m.group(1) if id_m else raw_id

    clean_line = re.sub(r"\s*\([^)]+\)\s*$", "", first_line)
    clean_line = re.sub(r"^#+\s*Phase-0\s+", "", clean_line, flags=re.IGNORECASE)
    thesis = re.sub(r"\s+Verdict\s*$", "", clean_line, flags=re.IGNORECASE).strip()
    if not thesis:
        thesis = slug.replace("-", " ").title()

    # --- status: first matching pattern wins ---
    status = "FAIL"
    for pat, fixed in [
        (r"###\s+\*\*(PASS)\*\*", "PASS"),
        (r"###\s+\*\*(FAIL)", "FAIL"),
        (r"###\s+\*\*(INSUFFICIENT-DATA)\*\*", "INSUFFICIENT-DATA"),
        (r"verdict\s*:\s*\*\*(PASS)\*\*", "PASS"),
        (r"verdict\s*:\s*\*\*(FAIL)", "FAIL"),
        (r"\*\*Verdict:\s*FAIL", "FAIL"),
        (r"\*\*Verdict:\s*PASS", "PASS"),
        (r"\*\*(FAIL)", "FAIL"),
        (r"\*\*(PASS)\*\*", "PASS"),
    ]:
        if re.search(pat, text, re.IGNORECASE):
            status = fixed
            break

    # --- date: binding run date ---
    # Prefer an explicit "Re-run — DATE" or "Results — DATE" or "Run date: DATE" over raw last-date.
    date = ""
    for pat in [
        r"(?:Re-run|Results)[^\n]*?[—–]\s*(20\d{2}-\d{2}-\d{2})",
        r"Run date[^\n]*?(20\d{2}-\d{2}-\d{2})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            date = m.group(1)
            break
    if not date:
        # Fall back: last ISO date before the §3+ section
        sec_m = re.search(r"\n##\s+3\.\s+(?:Verdict|Results|The Gate|TL;DR)", text, re.IGNORECASE)
        search_text = text[: sec_m.start()] if sec_m else text
        fallback_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", search_text)
        date = fallback_dates[-1] if fallback_dates else ""

    # --- parse markdown tables; use the LAST table that has a DSR-like column ---
    # Multiple result tables in one file (e.g. §2a superseded + §2b binding) — the last one is the
    # binding verdict, so we prefer it over an earlier table with a higher-but-stale number.
    best_dsr: float | None = None  # best DSR within the latest DSR-bearing table
    best_row: dict[str, str] | None = None

    headers: list[str] | None = None
    cur_rows: list[dict[str, str]] = []
    cur_best_dsr: float | None = None
    cur_best_row: dict[str, str] | None = None

    def _commit_table() -> None:
        nonlocal best_dsr, best_row
        if cur_best_dsr is not None:
            best_dsr = cur_best_dsr
            best_row = cur_best_row

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line.startswith("|"):
            _commit_table()
            headers = None
            cur_rows = []
            cur_best_dsr = None
            cur_best_row = None
            continue
        cells = [_clean(c) for c in line.split("|")[1:-1]]
        if not cells:
            continue
        if all(re.match(r"^[-: ]+$", c) for c in cells if c):
            continue  # separator row
        if headers is None:
            headers = [c.lower() for c in cells]
            continue
        if len(cells) != len(headers):
            headers = None
            continue
        row = dict(zip(headers, cells))
        cur_rows.append(row)
        for key, val in row.items():
            if "deflated" in key or "dsr" in key:
                v = _flt(val)
                if v is not None and (cur_best_dsr is None or v > cur_best_dsr):
                    cur_best_dsr = v
                    cur_best_row = row

    _commit_table()  # flush last table

    # Fallback: use raw Sharpe when no deflated-Sharpe / DSR column was found at all
    if best_dsr is None:
        headers = None
        cur_best_dsr = None
        cur_best_row = None
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line.startswith("|"):
                if cur_best_dsr is not None:
                    best_dsr = cur_best_dsr
                    best_row = cur_best_row
                headers = None
                cur_best_dsr = None
                cur_best_row = None
                continue
            cells = [_clean(c) for c in line.split("|")[1:-1]]
            if not cells:
                continue
            if all(re.match(r"^[-: ]+$", c) for c in cells if c):
                continue
            if headers is None:
                headers = [c.lower() for c in cells]
                continue
            if len(cells) != len(headers):
                headers = None
                continue
            row = dict(zip(headers, cells))
            for key, val in row.items():
                if key in ("sharpe", "val sharpe"):
                    v = _flt(val)
                    if v is not None and (cur_best_dsr is None or v > cur_best_dsr):
                        cur_best_dsr = v
                        cur_best_row = row
        if cur_best_dsr is not None:
            best_dsr = cur_best_dsr
            best_row = cur_best_row

    # pull cost_ratio + trades from the best row
    cost_ratio: float | None = None
    trades: int | None = None

    if best_row:
        if "cost_ratio" in best_row:
            v = _flt(best_row["cost_ratio"])
            if v is not None and 0.0 <= v <= 2.0:
                cost_ratio = v
        if "trades" in best_row:
            v2 = _int(best_row["trades"])
            if v2 and v2 > 0:
                trades = v2

    # --- one-line reason ---
    reason = ""

    # priority 1: **Headline:** paragraph (collapse lines, first 200 chars)
    hl_m = re.search(r"\*\*Headline:\*\*\s*(.+?)(?=\n\n|\n\*\*|\n#|\Z)", text, re.DOTALL)
    if hl_m:
        reason = re.sub(r"\s+", " ", _clean(hl_m.group(1))).strip()[:200]

    # priority 2: "### **VERDICT** — description" inline label
    if not reason:
        hdr_m = re.search(
            r"###\s+\*\*(?:FAIL|PASS|INSUFFICIENT-DATA|DATA-BLOCKED)\*\*\s*[—–-]\s*(.+?)$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
        if hdr_m:
            reason = _clean(hdr_m.group(1))[:200]

    # priority 3: first substantive non-table line from a Verdict/Results/TL;DR section
    if not reason:
        for sec_pat in [
            r"##\s+\d+[a-z]?\.\s+Verdict[^\n]*\n(.*?)(?=\n##\s+\d|\Z)",
            r"##\s+\d+[a-z]?\.\s+(?:Results|TL;DR)[^\n]*\n(.*?)(?=\n##\s+\d|\Z)",
        ]:
            sec_m = re.search(sec_pat, text, re.DOTALL | re.IGNORECASE)
            if sec_m:
                for ln in sec_m.group(1).split("\n"):
                    ln = ln.strip()
                    cleaned = _clean(re.sub(r"\[.*?\]\(.*?\)", "", ln)).strip("- \t")
                    if cleaned and len(cleaned) > 15 and not cleaned.startswith("#") and "|" not in cleaned:
                        reason = cleaned[:200]
                        break
            if reason:
                break

    return VerdictRow(
        slug=slug,
        thesis=thesis,
        id=p0_id,
        date=date,
        status=status,  # type: ignore[arg-type]
        deflated_sharpe=round(best_dsr, 3) if best_dsr is not None else None,
        trades=trades,
        cost_ratio=round(cost_ratio, 3) if cost_ratio is not None else None,
        reason=reason,
    )


def load_verdicts() -> list[VerdictRow]:
    if not _VERDICTS_DIR.is_dir():
        return []
    rows: list[VerdictRow] = []
    for path in sorted(_VERDICTS_DIR.glob("phase0-*-verdict.md")):
        try:
            rows.append(_parse_verdict(path))
        except Exception:
            pass
    return rows
