---
name: pine-from-url
description: Import a TradingView/Pine strategy from a URL — scrape the page (Pine source + described logic), translate to a typed StrategySpec, drop into the inbox, ready for /run-gate. Use when the user pastes a TradingView URL or any URL hosting Pine code and docs.
---

# pine-from-url

Fetch a URL → extract Pine source + description → translate to a typed `StrategySpec` → inbox → Gate.

**Key invariants (same as `/import-pine`):**
- Magic numbers become `param_space` entries, never stay hardcoded.
- Every indicator maps to a named `feature_registry` module — no inline math.
- The Gate (deterministic, no LLM) decides if the spec earns a SIM track.

**ToS / copyright caution:** Public Pine scripts are licensed under the Mozilla Public License 2.0 (MPL-2.0) by default on TradingView. You may read and adapt the *logic* (indicators, thresholds) into a `StrategySpec` for personal research under the adaptation clause. Do NOT store or publish verbatim Pine source. The translated spec is your own original work expressed in Cosmu's typed format.

**Honesty:** Most published community Pine is curve-fit to a visible chart. The Gate (CSCV-PBO + deflated Sharpe + FDR) is your only real protection — not the scraper, not the translator, not the description.

---

## Steps

### 1. Fetch (cheap model — scraping only)

Use `WebFetch` (or `mcp__Claude_in_Chrome__get_page_text`) on the URL. Ask a cheap model (Haiku / Sonnet via OpenRouter `:free`) to:

```
Extract from this page:
1. The complete Pine Script source (everything between //@version=N and the last line of strategy.* calls). Output it verbatim inside <pine>…</pine>.
2. A one-paragraph plain-English description of the strategy logic/thesis (from the author's description or README section). Output inside <desc>…</desc>.
3. The strategy name as the author published it. Output inside <strategy_name>…</strategy_name>.
```

If the page has no Pine source (access-gated, JavaScript-rendered without SSR), report that clearly and stop — do not hallucinate Pine.

**Tiered-agent pattern:** the cheap model does the extraction. The stronger model (Sonnet / Opus) does the translation and QA below. This keeps scraping costs near zero.

### 2. Extract Pine source and description

Parse the `<pine>` block. If it is empty or absent, retry with `mcp__Claude_in_Chrome__get_page_text` (full DOM) and re-run Step 1. If still empty, abort with: "No Pine source found at that URL — paste the source directly and use `/import-pine` instead."

### 3. Translate Pine → StrategySpec (stronger model)

Call `cosmu/strategy/pine.py:translate_pine(source)` via the engine helper `cosmu/strategy/pine_url.py:fetch_and_translate`:

```python
from cosmu.strategy.pine_url import fetch_and_translate
result = fetch_and_translate(pine_source, description=desc_text, strategy_name=strategy_name)
# result: PineUrlResult(translation, description, source_url, strategy_name, notes)
```

`fetch_and_translate` wraps `translate_pine` and:
- Injects the page description into the spec's `rationale` field so the Gate has prose context.
- Prefixes the spec name with the author's published title (not a generic "Imported Pine strategy").
- Appends `(pine-url)` to the name for traceability.
- Surfaces any `notes` from the translator (unsupported indicators, OR flattening, etc.).

### 4. Run static_check + compile_spec

```python
from cosmu.strategy.static_check import validate_spec
from cosmu.strategy.compiler import compile_spec
from cosmu.evolution.loop import fit_params

issues = validate_spec(result.translation.spec)
if issues:
    # report issues; do NOT silently drop them
    raise ValueError(f"spec has issues after translation: {issues}")
compile_spec(result.translation.spec, fit_params(result.translation.spec))  # must not raise
```

If issues remain after the auto-repair inside `translate_pine`, surface them to the user and ask whether to proceed.

### 5. Write to inbox

```python
import json
from pathlib import Path

spec = result.translation.spec
slug = spec.name.lower().replace(" ", "-").replace("/", "-")[:60]
out = Path("apps/engine/strategies/inbox") / f"{slug}.json"
out.write_text(json.dumps(spec.model_dump(mode="json"), indent=2))
print(f"Spec written to {out}")
```

### 6. Hand to /run-gate

Report:
> Spec written to `apps/engine/strategies/inbox/<slug>.json`.
> Name: `<spec.name>`
> Entry conditions: `<n>` — features: `<list>`
> Lifted params: `<lifted_params>`
> Notes: `<notes or "none">`
> Run `/run-gate` to screen it, or push and let the 4h cron pick it up.

---

## Verify

```bash
cd apps/engine && python3 -m pytest tests/test_pine_url.py -q
```

- The spec written to the inbox must pass `validate_spec` (zero issues).
- `compile_spec` must not raise.
- The spec name must contain the original strategy name, not the generic "Imported Pine strategy".
- `lifted_params` must be non-empty (every literal became a `param_space` entry).
