# intent: generate docs/AUTHORING.md DIRECTLY FROM THE CODE so the strategy-authoring "fiche" can never drift
# from the real feature registry / spec schema; inputs: cosmu.config.feature_registry + cosmu.strategy.spec;
# outputs: a deterministic Markdown reference written to <repo-root>/docs/AUTHORING.md; invariants: every fact is
# read live from the imported symbols (no hand-maintained copy), so a stale doc is impossible — re-run to refresh.
"""Authoring fiche generator.

Run from `apps/engine`:

    python3 -m cosmu.docs.authoring_fiche

It DUMPS FROM THE CODE — the feature vocabulary, the spec field lists, and the param-space kinds are all read
from the live imported symbols, so the generated `docs/AUTHORING.md` is a never-drifting reference usable by both
a human and Claude Code. Pass `--check` to fail (exit 1) if the on-disk doc is stale instead of rewriting it.
"""

from __future__ import annotations

import argparse
import sys
import types
import typing
from pathlib import Path
from typing import get_args, get_origin

from pydantic import BaseModel

from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names
from cosmu.strategy.spec import (
    EntrySetup,
    ExitPlan,
    ExitRules,
    MetaLabel,
    ParamSpace,
    RiskRules,
)

# The on-bar TA features usable with NO ingest (pure price/registry, parquet_bars source). Kept here as the
# canonical split list the task pins; every name is asserted to exist in feature_names() below so this list can
# never silently drift from the registry either.
ON_BAR_TA_FEATURES: tuple[str, ...] = (
    "ret_Nd",
    "rsi",
    "adx",
    "atr",
    "bb_z",
    "bb_width",
    "range_position",
    "vol_realized",
    "xsec_momentum_rank",
)


def _repo_root() -> Path:
    # this file is <repo>/apps/engine/cosmu/docs/authoring_fiche.py → four parents up is <repo>/apps/engine,
    # the repo root is two more up. Resolve explicitly so the doc lands at <repo-root>/docs/AUTHORING.md.
    return Path(__file__).resolve().parents[4]


def _type_str(annotation: object) -> str:
    """Render a field annotation as a compact, readable type string (Optional[...], list[...], Literal[...])."""
    if annotation is None or annotation is type(None):
        return "None"
    origin = get_origin(annotation)
    if origin is None:
        name = getattr(annotation, "__name__", None)
        return name if name else str(annotation).replace("typing.", "")
    args = get_args(annotation)
    # Optional[X] is Union[X, None] — both the typing.Union and the PEP-604 `X | None` (types.UnionType) forms.
    if origin is typing.Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        rendered = " | ".join(_type_str(a) for a in non_none)
        if len(non_none) != len(args):
            return f"Optional[{rendered}]"
        return rendered
    if origin is typing.Literal:
        inner = ", ".join(repr(a) for a in args)
        return f"Literal[{inner}]"
    origin_name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
    inner = ", ".join(_type_str(a) for a in args)
    return f"{origin_name}[{inner}]"


def _model_fields(model: type[BaseModel]) -> list[tuple[str, str, str]]:
    """Return (name, type, default) rows for a pydantic model, read live from model_fields."""
    rows: list[tuple[str, str, str]] = []
    for name, field in model.model_fields.items():
        type_str = _type_str(field.annotation)
        if field.is_required():
            default = "— (required)"
        else:
            # default_factory (e.g. list) renders as an empty collection note; a plain default renders as repr.
            if field.default_factory is not None:  # type: ignore[truthy-function]
                default = f"{field.default_factory.__name__}()"
            else:
                default = repr(field.default)
        rows.append((name, type_str, default))
    return rows


def _section_features() -> str:
    enabled = feature_names()
    on_bar = [f for f in FEATURE_REGISTRY if f.name in ON_BAR_TA_FEATURES and f.enabled]
    on_bar_names = {f.name for f in on_bar}
    # Sanity: every pinned on-bar name must be a real enabled registry feature, else the split lies.
    missing = [n for n in ON_BAR_TA_FEATURES if n not in enabled]
    if missing:
        raise SystemExit(f"on-bar TA features missing from enabled registry: {missing}")

    alt = [f for f in FEATURE_REGISTRY if f.enabled and f.name not in on_bar_names]

    lines: list[str] = []
    lines.append("## Feature vocabulary")
    lines.append("")
    lines.append(
        f"Every condition/meta-label/funding feature MUST reference one of these **{len(enabled)} enabled** "
        "registry names (an unknown name is rejected by `validate_spec` as `unknown_feature`). "
        "Disabled features (mislabeled / unwired / quarantined) are intentionally absent. "
        "Source of truth: `cosmu/config/feature_registry.py::feature_names()`."
    )
    lines.append("")

    lines.append("### On-bar TA features (no ingest — pure price, `parquet_bars`)")
    lines.append("")
    lines.append("These compute straight off the OHLCV bars — no alt-data join, no key, available everywhere.")
    lines.append("")
    lines.append("| feature | source | tier | as-of |")
    lines.append("|---------|--------|------|-------|")
    for f in sorted(on_bar, key=lambda x: ON_BAR_TA_FEATURES.index(x.name)):
        lines.append(f"| `{f.name}` | {f.source} | {f.tier} | {_short(f.asof_semantics)} |")
    lines.append("")

    lines.append(f"### Alt-data features ({len(alt)} — require an ingest source / key)")
    lines.append("")
    lines.append(
        "Each needs its point-in-time source ingested (some are key-gated; non-causal **controls** are wired "
        "honestly for the Gate to KILL). Vet a new feed with `/profile-source` before authoring on it."
    )
    lines.append("")
    lines.append("| feature | source | tier | as-of |")
    lines.append("|---------|--------|------|-------|")
    for f in sorted(alt, key=lambda x: x.name):
        lines.append(f"| `{f.name}` | {f.source} | {f.tier} | {_short(f.asof_semantics)} |")
    lines.append("")
    return "\n".join(lines)


def _short(text: str, limit: int = 120) -> str:
    """Collapse whitespace and truncate a long as-of clause so the table stays readable (full text is in code)."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[: limit - 1].rstrip() + "…"
    return flat


def _section_spec_models() -> str:
    models: list[tuple[str, type[BaseModel], str]] = [
        ("ExitRules", ExitRules, "The exit contract: single stop/take (required) + optional signal exits, time-stop, and a composable `plan`."),
        ("ExitPlan", ExitPlan, "Composable exit structure layered on the single stop/take — multi-TP scale-out, break-even, runner trail."),
        ("EntrySetup", EntrySetup, "Composable entry structure alongside `entry` conditions — MA-trend filter, ORB, FVG retest (long/upside-only)."),
        ("RiskRules", RiskRules, "Position-risk knobs read by the deterministic sizer (`master/sizing.py`)."),
        ("MetaLabel", MetaLabel, "Triple-barrier meta-labeling — a secondary logistic that SIZES/SKIPS the primary trade (never flips side)."),
    ]
    lines: list[str] = []
    lines.append("## Spec field lists (`cosmu/strategy/spec.py`)")
    lines.append("")
    lines.append(
        "Field names + types, dumped live from each pydantic model's `model_fields`. Thresholds are `ParamRef` "
        "(a `{\"param\": ...}` pointer into `param_space`) — never a literal number."
    )
    lines.append("")
    for title, model, blurb in models:
        lines.append(f"### {title}")
        lines.append("")
        lines.append(blurb)
        lines.append("")
        lines.append("| field | type | default |")
        lines.append("|-------|------|---------|")
        for name, type_str, default in _model_fields(model):
            lines.append(f"| `{name}` | `{type_str}` | `{default}` |")
        lines.append("")
    return "\n".join(lines)


def _section_param_space() -> str:
    kinds = get_args(ParamSpace.model_fields["kind"].annotation)
    lines: list[str] = []
    lines.append("## `param_space` kinds (`ParamSpace`)")
    lines.append("")
    lines.append(
        "Every threshold/lookback is a named entry in `param_space`. The Finder grid fits the value — the spec "
        "carries the SEARCH SPACE, never a magic number."
    )
    lines.append("")
    lines.append("| kind | fields | meaning |")
    lines.append("|------|--------|---------|")
    descriptions = {
        "int": ("`lo`, `hi`, `step`", "integer grid from `lo` to `hi` in `step` increments (e.g. a lookback window)"),
        "float": ("`lo`, `hi`", "continuous range from `lo` to `hi` (e.g. a stop %, a funding floor)"),
        "choice": ("`choices`", "an explicit list of candidate values"),
    }
    for kind in kinds:
        fields, meaning = descriptions.get(kind, ("?", "?"))
        lines.append(f"| `{kind}` | {fields} | {meaning} |")
    lines.append("")
    return "\n".join(lines)


def _section_header() -> str:
    return (
        "# Strategy-authoring fiche (AUTHORING.md)\n"
        "\n"
        "> **GENERATED — do not edit by hand.** Regenerate from the code with "
        "`cd apps/engine && python3 -m cosmu.docs.authoring_fiche`.\n"
        "> Every table below is dumped live from `cosmu.config.feature_registry` and `cosmu.strategy.spec`, so this "
        "reference can never drift from the real vocabulary/schema. It is the standardized, never-drifting reference "
        "for authoring a `StrategySpec` — usable by both a human and Claude Code.\n"
        "\n"
        "A spec must clear `validate_spec` (`cosmu/strategy/static_check.py`): **every threshold a `ParamRef` in "
        "`param_space`** · **≥1 entry `Condition`** (indicator specs) · **non-empty `rationale`** · feature names "
        "from the registry only. See `.claude/skills/create-strategy/SKILL.md` for the authoring workflow and the "
        "**Exit & Entry toolbox** wiring matrix (which exits actually run in paper/live today).\n"
    )


def render() -> str:
    parts = [
        _section_header(),
        _section_features(),
        _section_spec_models(),
        _section_param_space(),
    ]
    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate docs/AUTHORING.md from the live code.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if docs/AUTHORING.md is missing or stale.",
    )
    args = parser.parse_args(argv)

    content = render()
    out_path = _repo_root() / "docs" / "AUTHORING.md"

    if args.check:
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != content:
            print(f"STALE: {out_path} differs from generated content — run `python3 -m cosmu.docs.authoring_fiche`")
            return 1
        print(f"OK: {out_path} is up to date")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"wrote {out_path} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
