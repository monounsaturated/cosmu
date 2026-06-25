# intent: generate the module-tree section of docs/ARCHITECTURE.md DIRECTLY FROM THE CODE so the codebase map
# can never silently drift from the real package layout; inputs: a live walk of the cosmu/ package tree reading
# each module's first docstring / `# intent:` header line; outputs: a deterministic Markdown block written
# BETWEEN the BEGIN/END GENERATED markers already present in <repo-root>/docs/ARCHITECTURE.md (the hand-written
# prose around the block is left untouched); invariants: every line is read live from the on-disk modules
# (no hand-maintained copy), so a stale block is impossible — re-run to refresh, or `--check` to fail CI.
"""Codebase-map generator.

Run from `apps/engine`:

    python3 -m cosmu.docs.codebase_map            # rewrite the generated block in docs/ARCHITECTURE.md
    python3 -m cosmu.docs.codebase_map --check     # exit 1 if the on-disk block is stale (CI / drift guard)

It walks the `cosmu/` package tree and, for each top-level package and each module, reads a one-line summary
(the module docstring's first line, or the `# intent:` header's first line). The result replaces ONLY the text
between the `<!-- BEGIN GENERATED: module-tree -->` and `<!-- END GENERATED: module-tree -->` markers in
`docs/ARCHITECTURE.md`, so the surrounding hand-written architecture prose is preserved. This mirrors the
authoring-fiche generator (`cosmu/docs/authoring_fiche.py`) and gives a future CI a drift guard.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN GENERATED: module-tree -->"
END_MARKER = "<!-- END GENERATED: module-tree -->"

# Directories under cosmu/ that are not part of the documented application surface.
_SKIP_DIRS = {"__pycache__", "tests", "test"}


def _repo_root() -> Path:
    # this file is <repo>/apps/engine/cosmu/docs/codebase_map.py → parents[4] is <repo>/apps/engine,
    # the repo root is two more up. Resolve explicitly so we read/write <repo-root>/docs/ARCHITECTURE.md.
    return Path(__file__).resolve().parents[4]


def _cosmu_root() -> Path:
    # parents[1] of this file is <repo>/apps/engine/cosmu.
    return Path(__file__).resolve().parents[1]


def _summary_for(path: Path) -> str:
    """One-line summary of a module: its docstring's first line, else its `# intent:` header, else "".

    Read without importing (pure text/AST parse) so the generator never executes package code and stays fast
    and side-effect-free.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

    # 1) a real module docstring.
    try:
        tree = ast.parse(text)
        doc = ast.get_docstring(tree)
        if doc:
            first = doc.strip().splitlines()[0].strip()
            if first:
                return _clip(first)
    except SyntaxError:
        pass

    # 2) the `# intent:` convention used across the engine — collect the contiguous comment header.
    intent_lines: list[str] = []
    started = False
    for raw in text.splitlines():
        line = raw.strip()
        if not started:
            if line.lower().startswith("# intent:"):
                started = True
                intent_lines.append(line[len("# intent:"):].strip())
            elif line and not line.startswith("#"):
                break  # hit real code before any intent header
            continue
        # continuation of the comment header
        if line.startswith("#"):
            intent_lines.append(line.lstrip("#").strip())
        else:
            break
    if intent_lines:
        joined = " ".join(p for p in intent_lines if p)
        # the intent header is multi-clause; keep only the first clause (up to the first ';') for the table.
        first_clause = joined.split(";")[0].strip()
        return _clip(first_clause or joined)

    return ""


def _clip(text: str, limit: int = 130) -> str:
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[: limit - 1].rstrip() + "…"
    return flat


def _iter_packages() -> list[Path]:
    """Top-level packages directly under cosmu/ (a dir with an __init__.py), sorted by name."""
    root = _cosmu_root()
    pkgs: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in _SKIP_DIRS:
            continue
        if (child / "__init__.py").exists():
            pkgs.append(child)
    return pkgs


def _iter_modules(pkg: Path) -> list[Path]:
    """Direct *.py modules in a package (one level deep), excluding __init__, sorted by name."""
    mods: list[Path] = []
    for child in sorted(pkg.iterdir()):
        if child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
            mods.append(child)
    return mods


def _count_tree(pkg: Path) -> int:
    """Total *.py modules anywhere under a package (for the per-package size hint)."""
    return sum(1 for p in pkg.rglob("*.py") if p.name != "__init__.py" and "__pycache__" not in p.parts)


def render_block() -> str:
    """Render the generated module-tree Markdown block (between the markers, markers excluded)."""
    cosmu = _cosmu_root()
    lines: list[str] = []
    lines.append("")
    lines.append(
        "_Walked live from `apps/engine/cosmu/` by `python3 -m cosmu.docs.codebase_map`. Each package's "
        "one-liner is its `__init__.py` summary; each module's is its docstring or `# intent:` header. "
        "Re-run after adding/removing a module — `--check` fails CI on drift._"
    )
    lines.append("")

    pkgs = _iter_packages()
    lines.append(f"**{len(pkgs)} top-level packages** under `cosmu/`:")
    lines.append("")

    for pkg in pkgs:
        pkg_summary = _summary_for(pkg / "__init__.py") or "_(no package summary)_"
        n = _count_tree(pkg)
        rel = pkg.relative_to(cosmu.parent)  # e.g. cosmu/data
        lines.append(f"### `{rel}/` — {pkg_summary}")
        lines.append("")
        mods = _iter_modules(pkg)
        if not mods:
            lines.append(f"_{n} module(s); no top-level modules (see sub-packages)._")
            lines.append("")
            continue
        lines.append(f"_{n} module(s) total. Top-level modules:_")
        lines.append("")
        lines.append("| module | summary |")
        lines.append("|--------|---------|")
        for mod in mods:
            summary = _summary_for(mod) or ""
            lines.append(f"| `{mod.name}` | {summary} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _splice(existing: str, block: str) -> str:
    """Replace the text between the BEGIN/END markers in `existing` with `block`. Markers must exist."""
    if BEGIN_MARKER not in existing or END_MARKER not in existing:
        raise SystemExit(
            f"markers not found in ARCHITECTURE.md — expected '{BEGIN_MARKER}' and '{END_MARKER}'. "
            "Add them (with the surrounding prose) before generating."
        )
    pre, rest = existing.split(BEGIN_MARKER, 1)
    _, post = rest.split(END_MARKER, 1)
    return f"{pre}{BEGIN_MARKER}\n{block}{END_MARKER}{post}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the module-tree block of docs/ARCHITECTURE.md from code.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the generated block in docs/ARCHITECTURE.md is missing or stale.",
    )
    args = parser.parse_args(argv)

    out_path = _repo_root() / "docs" / "ARCHITECTURE.md"
    if not out_path.exists():
        print(f"MISSING: {out_path} does not exist — create it (with the BEGIN/END markers) first.")
        return 1

    existing = out_path.read_text(encoding="utf-8")
    block = render_block()
    spliced = _splice(existing, block)

    if args.check:
        if existing != spliced:
            print(
                f"STALE: the generated module-tree block in {out_path} is out of date — "
                "run `cd apps/engine && python3 -m cosmu.docs.codebase_map`"
            )
            return 1
        print(f"OK: {out_path} module-tree block is up to date")
        return 0

    out_path.write_text(spliced, encoding="utf-8")
    print(f"wrote module-tree block into {out_path} ({len(block)} bytes generated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
