# intent: the NL→strategy pipeline's FRONT DOOR — turn an unstructured document (a vibe note, an abstract, a
# page from an old trading book, a research PDF) into ordered, hashed DocumentChunk(s) that the downstream
# Thinker can reason over. inputs: a file path (.txt/.md → section split; .pdf → pdfplumber/PyPDF2/pypdf when a
# parser is importable, else an HONEST "pdf parsing unavailable" chunk); outputs: list[DocumentChunk] with a
# stable per-chunk id derived from the file bytes (idempotent — same bytes → same chunk ids). invariants:
# NO LLM, NO network here (pure parsing); offline-safe; a missing/unreadable file degrades to a single honest
# chunk rather than raising into the pipeline. The chunk's content_hash lets the orchestrator skip re-thinking
# an unchanged document (same idempotency contract the inbox scanner uses).

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# Section-split markers for prose documents: a markdown/setext heading, a numbered/roman section header, or a
# blank-line paragraph break. Kept deliberately simple — the Thinker, not the splitter, does the reasoning.
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6}\s+\S|[A-Z][A-Za-z0-9 ].{0,60}\n[=-]{3,}\s*$)", re.MULTILINE)
_MAX_CHUNK_CHARS = 6000  # a hard ceiling so one giant section is still split into bounded pieces


@dataclass
class DocumentChunk:
    """One ordered, hashed slice of a source document.

    `path` is the source file. `chunk_id` is stable for the same file bytes + position (idempotent). `text` is the
    raw slice. `metadata` carries the parser/source kind + section title for the Thinker's audit trail.
    """

    path: str
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def _bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_id(file_hash: str, index: int) -> str:
    # File-bytes hash + ordinal → a chunk id that is identical on re-parse of the SAME bytes (idempotent) and
    # changes the instant the file changes.
    return f"{file_hash[:16]}-{index:03d}"


def _split_prose(text: str) -> list[tuple[str, str]]:
    """Split prose into (section_title, body) pairs at headings, then bound each by _MAX_CHUNK_CHARS. A document
    with no headings collapses to paragraph-bounded chunks so very long flat text still chunks sensibly."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    # Find heading offsets; sections run from one heading to the next.
    starts = [m.start() for m in _HEADING_RE.finditer(text)]
    sections: list[tuple[str, str]] = []
    if starts:
        bounds = starts + [len(text)]
        # Leading text before the first heading is its own (untitled) section.
        if starts[0] > 0:
            sections.append(("", text[: starts[0]].strip()))
        for i in range(len(starts)):
            block = text[bounds[i] : bounds[i + 1]].strip()
            title = block.splitlines()[0].lstrip("# ").strip() if block else ""
            sections.append((title, block))
    else:
        # No headings: split on blank-line paragraph breaks, grouping greedily up to the ceiling.
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) + 2 > _MAX_CHUNK_CHARS:
                sections.append(("", buf.strip()))
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf.strip():
            sections.append(("", buf.strip()))

    # Hard-bound any oversize section.
    bounded: list[tuple[str, str]] = []
    for title, body in sections:
        if not body:
            continue
        if len(body) <= _MAX_CHUNK_CHARS:
            bounded.append((title, body))
            continue
        for off in range(0, len(body), _MAX_CHUNK_CHARS):
            bounded.append((title, body[off : off + _MAX_CHUNK_CHARS]))
    return bounded


def _pdf_text(data: bytes) -> tuple[str | None, str]:
    """Extract text from PDF bytes using whichever parser is importable (pdfplumber → pypdf → PyPDF2). Returns
    (text | None, parser_name). text is None when NO parser is available — the caller emits an HONEST
    'pdf parsing unavailable' chunk rather than fabricating content. Pure-local; no network."""
    import io

    # pdfplumber: best layout fidelity when present.
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
        return "\n\n".join(pages).strip(), "pdfplumber"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — a corrupt PDF is reported, never crashes the pipeline
        return f"pdf parsing error ({type(exc).__name__})", "pdfplumber-error"

    # pypdf / PyPDF2: the lighter fallbacks (same API surface).
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        try:
            reader = mod.PdfReader(io.BytesIO(data))
            pages = [(pg.extract_text() or "") for pg in reader.pages]
            return "\n\n".join(pages).strip(), mod_name
        except Exception as exc:  # noqa: BLE001
            return f"pdf parsing error ({type(exc).__name__})", f"{mod_name}-error"

    return None, "none"


class DocumentHandler:
    """Parse a source file into ordered, hashed DocumentChunk(s). Pure, offline, idempotent (same bytes → same
    chunk ids). The ONLY stateful thing it touches is the filesystem (read-only)."""

    SUPPORTED = (".txt", ".md", ".markdown", ".text", ".pdf")

    def parse_file(self, path: str | Path) -> list[DocumentChunk]:
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as exc:
            # Missing/unreadable file → one honest chunk; the pipeline degrades, never raises here.
            return [
                DocumentChunk(
                    path=str(p),
                    chunk_id="unreadable-000",
                    text=f"could not read file: {type(exc).__name__}",
                    metadata={"kind": "error", "parser": "none"},
                )
            ]

        file_hash = _bytes_hash(data)
        suffix = p.suffix.lower()

        if suffix == ".pdf":
            text, parser = _pdf_text(data)
            if text is None:
                return [
                    DocumentChunk(
                        path=str(p),
                        chunk_id=_chunk_id(file_hash, 0),
                        text="pdf parsing unavailable (install pdfplumber, pypdf, or PyPDF2 to extract text)",
                        metadata={"kind": "pdf", "parser": "none", "content_hash": file_hash},
                    )
                ]
            sections = _split_prose(text)
            kind = "pdf"
        elif suffix in (".txt", ".md", ".markdown", ".text"):
            text = data.decode("utf-8", errors="replace")
            sections = _split_prose(text)
            kind = "markdown" if suffix in (".md", ".markdown") else "text"
            parser = "section-split"
        else:
            # Unknown suffix: treat as plain text rather than refusing (best-effort).
            text = data.decode("utf-8", errors="replace")
            sections = _split_prose(text)
            kind = "text"
            parser = "section-split"

        if not sections:
            return [
                DocumentChunk(
                    path=str(p),
                    chunk_id=_chunk_id(file_hash, 0),
                    text="",
                    metadata={"kind": kind, "parser": parser, "content_hash": file_hash, "empty": True},
                )
            ]

        chunks: list[DocumentChunk] = []
        for i, (title, body) in enumerate(sections):
            chunks.append(
                DocumentChunk(
                    path=str(p),
                    chunk_id=_chunk_id(file_hash, i),
                    text=body,
                    metadata={
                        "kind": kind,
                        "parser": parser,
                        "section": title,
                        "index": i,
                        "content_hash": file_hash,
                    },
                )
            )
        return chunks
