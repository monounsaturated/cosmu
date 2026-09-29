# inbox-lint — offline validate + dedup manifest for the strategy-authoring railway

2026-06-28 · autonomous-run POC · **DO NOT MERGE yet**

## Why

Roadmap #2 is the strategy-creation **railway**: making it cheap to author and review many specs.
When a human or an agent drops 50 hand-written strategy specs into `strategies/inbox/`, today the
only way to see if they're sound is to let the boot-scan import them and the Gate dispose them — by
which point a typo'd feature name, a too-small universe, or a clutch of near-identical specs has
already burned compute and, worse, **FDR budget** (the BH-FDR cohort gate treats near-duplicates as
independent tests, so 6 copies of one momentum idea inflate the multiple-comparison correction and
make a real edge harder to clear).

`inbox-lint` makes a directory of 50 specs as reviewable as 1, **before** any scan or Gate, with a
single offline, read-only command.

## What it is

`apps/engine/cosmu/lab/inbox_lint.py` — an offline CLI + importable `lint_inbox()`.

It **reuses the existing authoring stack** rather than reinventing anything:

| Concern | Reused primitive | Source |
| --- | --- | --- |
| Load `.md`/`.pine`/`.json` → typed `StrategySpec` | `_spec_from_file` | `cosmu/lab/inbox.py` |
| Inbox directory + supported suffixes + README/TEMPLATE skip | `_INBOX_DIR`, mirrored filters | `cosmu/lab/inbox.py` |
| PASS/FAIL validation + reasons | `validate_spec` | `cosmu/strategy/static_check.py` |
| Facet vocabulary (signal-family, edge-type, features) | `derive_facets` | `cosmu/strategy/taxonomy.py` |
| Near-duplicate distance | `structural_distance` | `cosmu/knowledge/memory.py` |

Per spec it surfaces: status (PASS/FAIL + reasons), kind (`json`/`pine`/`md-spec`/`brief`),
`strategy_kind`, `lane`, `direction`, entry mechanism (`feature op param …`), exit envelope
(stop/take/time-stop/signal-exits/plan/trailing/atr), features, universe, horizon, signal-family,
and edge-type.

Across the set it computes pairwise `structural_distance` (Jaccard over entry-feature sets +
bar-size penalty; the **same** primitive the novelty gate uses), records each spec's nearest
neighbour, and unions near-dups (distance `< --dup-threshold`, default `0.25` = `novelty_gate`'s
`min_distance`) into clusters via union-find (transitive: A~B, B~C ⇒ one cluster).

### Invariants

- **Read-only**: no `Store`, no DB, no network, no inbox-file mutation. It imports zero money-path code.
- **Robust**: a malformed file (bad JSON, broken front-matter) is reported `FAIL` with a
  `parse_error:` reason — it never crashes the lint. A belt-and-braces `try/except` around each file
  guards even unexpected loader failures.
- **Deterministic**: cluster ids are the smallest member row-index; ordering is stable.
- It is a **lint/preview, NOT the Gate** — it disposes nothing and funds nothing.

## Usage

```bash
# default: the canonical strategies/inbox; prints the table then the JSON manifest
python3 -m cosmu.lab.inbox_lint

# point at any dir, write the machine-readable manifest, stricter dedup
python3 -m cosmu.lab.inbox_lint --inbox path/to/inbox --json out.json --dup-threshold 0.15

# JSON only (for piping into other tooling)
python3 -m cosmu.lab.inbox_lint --json-only
```

Exit code is `1` when **any** spec FAILs (so a pre-author CI hook can gate on a clean inbox), `0`
when all clear.

## Output shape

**Human table** (one row per spec) + a near-dup cluster list + fail reasons:

```
INBOX LINT — /…/strategies/inbox
  scanned=6  PASS=4  FAIL=2  dup_clusters=1

  STATUS  NAME                       KIND     EDGE          FAMILY         FEATURES               NEAREST  CLUSTER
  ------  -------------------------  -------  ------------  -------------  ---------------------  -------  -------
  PASS    Funding-pressure carry     json     carry         On-chain/Flow  funding_rate,perp_sp…  1.15     —
  PASS    Oversold mean reversion    json     mean-reversi…  Math/Price     rsi,bb_z               1.00     —
  PASS    Momentum A                 json     momentum      Math/Price     ret_Nd,adx             0.00     #3
  PASS    Momentum B (param tweak)   json     momentum      Math/Price     ret_Nd,adx             0.00     #3
  FAIL    Unknown-feature spec       json     momentum      Math/Price     not_a_feature,adx      0.67     —
  FAIL    garbage                    json     —             —              —                      —        —

  NEAR-DUPLICATE CLUSTERS (would compete for the same Gate FDR budget):
    #3: mom-a.json, mom-b.json

  FAIL REASONS:
    bad-feature.json: unknown_feature:not_a_feature
    garbage.json: parse_error:Expecting property name enclosed in double quotes: line 1 column 3 (char 2)
```

**JSON manifest** (`--json` / stdout): `{ inbox_dir, scanned, passed[], failed[], dup_clusters{} }`
where each row is the full `LintedSpec` (path, filename, name, kind, status, issues, all surfaced
facts, nearest/nearest_dist, cluster). `dup_clusters` keys are stringified cluster ids → member
filenames. The payload round-trips through `json.dumps`/`json.loads`.

## Run against the real inbox (2026-06-28)

```
scanned=125  PASS=119  FAIL=6  dup_clusters=26
```

The 6 FAILs it caught up front (exactly what the scanner would later reject):
- `liquidation-cascade-reversal.json` — `unknown_feature:liquidation_cascade`
- `llm-narrative-pressure-long.json` — `universe_too_small`
- `social-authority-influencer-surge.json` — `unknown_feature:twitter_influencer_sentiment`
- `social-dominance-share-leadership-long.json` — `unknown_feature:social_dom_z`
- `xsec-funding-dispersion-long-leg.json` / `…-short-leg.json` — `unknown_feature:xsec_funding_rank`

…and 26 near-dup clusters (e.g. 6 funding-carry-shaped specs in one cluster) that would otherwise
each consume an independent slot in the BH-FDR correction.

## Tests

`apps/engine/tests/test_lab_inbox_lint.py` — **6 passed in 0.27s** (ran the single file only, per
M2 discipline; never the full suite).

Covers exactly the required cases:
- (a) valid spec → PASS, facts surfaced (`test_valid_spec_passes`)
- (b) invalid spec caught, not crashed — both an unknown-feature spec AND a non-JSON file
  (`test_invalid_spec_is_caught_not_crashed`)
- (c) two near-duplicate specs → one dup-cluster holding both, distance ~0
  (`test_near_duplicates_cluster_together`)
- (d) two distinct specs (momentum vs mean-reversion) → not clustered, distance ≥ 0.25
  (`test_distinct_specs_not_clustered`)
- plus render/JSON shape + missing-dir safety

## Honest limitations

- `structural_distance` keys on **entry-feature sets + bar_size** only. Two specs with identical
  entry features but very different exit envelopes / thresholds / direction read as distance 0 —
  the lint over-clusters on entry structure. That's faithful to how the live novelty gate measures
  similarity, but it is **not** a full overfit/edge-correlation check (the Gate's PBO/DSR does that).
- It validates structure, **not** edge: a PASS means "well-formed and feature names resolve," never
  "this has alpha." The Gate alone disposes.
- For `.md` prose briefs the loader uses the offline heuristic drafter (`draft_from_brief`,
  `llm_enabled=False`), so a prose brief's facets reflect the heuristic draft, not an LLM authoring.
- Dedup is O(n²) pairwise — fine for inbox-scale (hundreds), not for tens of thousands.
- It mirrors the scanner's file filters by hand (suffixes, README/TEMPLATE skip); if the scanner's
  filter logic changes, this must follow.

## Files

- `apps/engine/cosmu/lab/inbox_lint.py` (new)
- `apps/engine/tests/test_lab_inbox_lint.py` (new)
- `docs/reports/inbox-lint-2026-06-28.md` (this report)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
