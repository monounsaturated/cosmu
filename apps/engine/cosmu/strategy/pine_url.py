# intent: wrap translate_pine for the pine-from-url skill — accepts a pre-fetched Pine source + page metadata
# (description, strategy name, source URL) and returns a PineUrlResult that enriches the spec's rationale and
# name from the page context; inputs: pine_source (str), optional description/strategy_name/source_url; outputs:
# PineUrlResult(translation, description, source_url, strategy_name, notes); invariants: offline-safe (no live
# network — the caller fetches the page; this module only wraps the existing translator), no magic numbers
# (translate_pine enforces this), fully testable with fixture Pine snippets.

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cosmu.strategy.pine import PineTranslation, translate_pine


@dataclass
class PineUrlResult:
    """The output of fetch_and_translate: the typed spec (via PineTranslation) enriched with page context."""

    translation: PineTranslation
    description: str          # author's prose description from the page (empty string if not available)
    source_url: str           # the URL the Pine was scraped from (empty string if not from a URL)
    strategy_name: str        # the author's published name (used to override the generic translated name)
    notes: list[str] = field(default_factory=list)


def fetch_and_translate(
    pine_source: str,
    *,
    description: str = "",
    strategy_name: str = "",
    source_url: str = "",
) -> PineUrlResult:
    """Translate Pine source that was scraped from a URL into a typed StrategySpec.

    Builds on `translate_pine` and applies three enrichments from the page context:
    1. Spec name — overrides the generic "Imported Pine strategy" with the author's published title.
    2. Rationale — prepends the page description (thesis) so the Gate has prose context about the edge.
    3. Traceability — appends "(pine-url)" to the name so operators can tell URL-imported specs from
       paste-imported ones; source_url is surfaced in the notes.

    This function is **offline-safe**: it performs no network I/O. The caller (the skill's Step 1) is
    responsible for fetching the page and extracting the Pine source and metadata.
    """
    translation = translate_pine(pine_source)
    notes: list[str] = list(translation.notes)

    spec = translation.spec

    # --- 1. Override the spec name with the author's title if provided ---
    effective_name = _effective_name(spec.name, strategy_name)
    if effective_name != spec.name:
        spec = spec.model_copy(update={"name": effective_name})
        notes.append(f"name overridden from page: {effective_name!r}")

    # --- 2. Enrich rationale with the author's prose description ---
    if description.strip():
        enriched_rationale = _enrich_rationale(spec.rationale, description.strip(), source_url)
        spec = spec.model_copy(update={"rationale": enriched_rationale})

    # --- 3. Rebuild translation with the enriched spec ---
    enriched_translation = PineTranslation(
        spec=spec,
        source_hash=translation.source_hash,
        indicators=translation.indicators,
        conditions=translation.conditions,
        notes=notes,
        lifted_params=translation.lifted_params,
    )

    if source_url:
        notes.append(f"scraped from: {source_url}")

    return PineUrlResult(
        translation=enriched_translation,
        description=description,
        source_url=source_url,
        strategy_name=effective_name,
        notes=notes,
    )


# ---------------------------------------------------------------- name / rationale helpers


def _effective_name(translated_name: str, page_name: str) -> str:
    """Derive the final spec name: prefer the page title, fall back to what the translator inferred.

    Rules:
    - If `page_name` is non-empty and not the same as the translator's result, use `page_name (pine-url)`.
    - If the translated name already ends with '(pine)', replace the suffix with '(pine-url)' so the
      provenance tag is consistent regardless of path.
    - Otherwise append '(pine-url)' to mark URL-imported origin.
    """
    base = page_name.strip() if page_name.strip() else translated_name

    # Remove any existing provenance tag to avoid "(pine)(pine-url)" etc.
    base = re.sub(r"\s*\(pine(?:-url)?\)\s*$", "", base, flags=re.IGNORECASE).strip()

    # TradingView titles can be long; cap to keep slugs sane.
    tag = " (pine-url)"
    max_base = 80 - len(tag)
    if len(base) > max_base:
        base = base[:max_base].rstrip()

    return f"{base}{tag}"


def _enrich_rationale(original: str, description: str, source_url: str) -> str:
    """Prepend the page description to the spec rationale so downstream reviewers see the edge thesis.

    Format:
        Author's description: <description>
        [Source: <url>]

        <original rationale>
    """
    lines = [f"Author's description: {description}"]
    if source_url:
        lines.append(f"Source: {source_url}")
    lines.append("")
    lines.append(original)
    return "\n".join(lines)
