// Adversarial verification of the deep astro study. Independent skeptics each try to BREAK the
// "astrology adds no edge" conclusion from a distinct failure-mode lens, reading the real report +
// module sources. Then a synthesis judges overall confidence + the must-fix list.
// Launch: Workflow({scriptPath: ".../_adversarial_audit.wf.js", args: {report, deepDir, round1Report}})

export const meta = {
  name: 'astro-adversarial-audit',
  description: 'Adversarially verify the deep astrology-vs-markets study: skeptics hunt leakage, selection bias, incremental-test validity, survivorship, backtest realism, and overreach; synthesize a confidence verdict.',
  phases: [{ title: 'Audit' }, { title: 'Synthesize' }],
}

const A = args || {}
const DEEP = A.deepDir || 'apps/engine/scripts/research/astro_deep'
const REPORT = A.report || 'docs/research/astro_vs_markets_deep.md'
const R1 = A.round1Report || 'docs/research/astro_vs_markets.md'

const CTX = `
You are an adversarial quant auditor on the COSMU trading project, whose ENTIRE value is an honest, no-look-ahead
research process. A research study concludes: "pure broad astrology carries NO exploitable predictive edge on top
of real signals, after costs + multiple-testing." Your job is to TRY TO BREAK that conclusion — find any flaw that
would either (a) hide a real edge that exists, or (b) be manufacturing/own-goal a false negative or false positive.
Read the ACTUAL files; quote line numbers as evidence. Be specific and skeptical; vague doubts are useless.

Files (cwd = repo root <repo>/.claude/worktrees/tender-turing-19c2dd):
- Report (round 2): ${REPORT}
- Round-1 report: ${R1}
- Modules: ${DEEP}/astro_features_deep.py, real_panel.py, ml_harness.py, astro_deep_study.py, extra_signals.py, modal_sweep.py
To run code, cd apps/engine and (if DB/Modal needed) set -a; . <repo>/.env.local; set +a.
`;

const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['lens', 'verdict', 'issues', 'strongest_counterpoint'],
  properties: {
    lens: { type: 'string' },
    verdict: { type: 'string', enum: ['SOUND', 'FLAWED', 'INCONCLUSIVE'], description: 'is the study sound on THIS lens?' },
    issues: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['severity', 'claim', 'evidence', 'fix'],
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          claim: { type: 'string', description: 'the specific flaw' },
          evidence: { type: 'string', description: 'file:line + what you saw/ran proving it' },
          fix: { type: 'string', description: 'concrete remedy' },
        },
      },
    },
    strongest_counterpoint: { type: 'string', description: 'the single best argument the conclusion is wrong or unsafe' },
  },
};

phase('Audit')

const LENSES = [
  ['leakage', `LENS: LOOK-AHEAD / POINT-IN-TIME LEAKAGE. Audit every place future info could reach a past bar:
    real_panel.py _asof_join + the SQL (available_at<=ts? ts column is TEXT — does the >= bound and ordering hold?),
    space-weather shift(1) in astro_deep_study.load_spaceweather, the bull/bear regime (SMA200 trailing only?),
    forward-return alignment in assemble(), the backtest signal centering (expanding median — verify it is past-only),
    and the deterministic astro (is anything computed from a FUTURE syzygy/eclipse used to label a past day?).
    Actually run a spot check if useful. A leak that flatters the result is as serious as one that hides an edge.`],
  ['multiple_testing', `LENS: MULTIPLE-TESTING / SELECTION. Verify BH-FDR is applied over the WHOLE IC grid (ml_harness.ic_panel);
    that the Deflated Sharpe (deflated_sharpe) charges the REAL number of trials (how is n_trials set in astro_deep_study?);
    that the ML "group×horizon beats null at p<0.05" claims are not a selection artifact across the ~12 configs (is there any
    correction across configs, or should the report stop calling marginal p-values 'beats'?); and that the "strongest signals"
    table is honestly framed as pre-correction. Is the headline conclusion robust to the trial count?`],
  ['incremental', `LENS: INCREMENTAL-TEST VALIDITY (the headline). In ml_harness.incremental_test: does the null shuffle ONLY the
    astro block (preserving the real baseline) and truly destroy astro info? Is the REAL baseline strong enough that "astro adds
    no lift" is informative rather than "both are noise" (check auc_base — if it's ~0.50 the test is weak)? Could astro↔real
    collinearity or HGB regularization mask a genuine astro contribution? Would a different model (linear, deeper) change it?
    Is pooled walk-forward leaking across assets at a shared date boundary?`],
  ['data_quality', `LENS: DATA QUALITY / SURVIVORSHIP. Crypto universe = today's listed Binance pairs → delisted-coin survivorship
    (does it matter for this question?). Equity via Yahoo: adjusted vs raw close, split look-ahead. Alt-data coverage/NaN handling
    (HGB native-NaN — any column all-NaN or near-constant feeding a fold?). Label balance (fwd>0 base rate per asset). LunarCrush
    base-asset key resolution correctness. Anything that biases the AUCs up or down.`],
  ['backtest', `LENS: BACKTEST / COST / DSR REALISM. In ml_harness.backtest_long_short + deflated_sharpe: fee model and turnover
    accounting correct? Annualization √365 (crypto) applied to equity assets too (mixed calendars)? Is the DSR formula faithful to
    Bailey-López de Prado (sr0 expected-max, skew/kurt adjustment)? Does the per-asset "best feature" selection inflate DSR despite
    the n_trials charge? Re-derive one number by hand if you can.`],
  ['overreach', `LENS: OVERREACH / COMPLETENESS. Does the report's conclusion over- or under-claim relative to what was tested?
    What is NOT tested that a serious skeptic (or a financial-astrologer) would demand: intraday/hourly astro, cross-sectional
    astro ranking, specific named hypotheses tested individually (Bradley turn dates, Gann, ingress, eclipse windows — are these
    in the IC grid by name?), non-linear interactions, regime-conditional astro. Is "no edge" the honest summary, or should it be
    narrower? What single additional test would most strengthen or threaten the conclusion?`],
];

const audits = await parallel(LENSES.map(([key, prompt]) =>
  () => agent(`${CTX}\n\n${prompt}\n\nReturn the structured verdict for lens "${key}".`,
    { label: `audit:${key}`, phase: 'Audit', schema: VERDICT })
));

phase('Synthesize')

const valid = audits.filter(Boolean);
const synthesis = await agent(
  `${CTX}\n\nSix adversarial auditors returned these verdicts (JSON):\n${JSON.stringify(valid, null, 2)}\n\n` +
  `Synthesize a final judgement:\n` +
  `1. Overall confidence the study's "astrology adds no exploitable edge" conclusion is SOUND (high/medium/low) and why.\n` +
  `2. The deduplicated MUST-FIX list (blockers + majors only), each with file:line and the fix, ordered by severity.\n` +
  `3. Whether any finding could flip the conclusion (hidden real edge) vs merely tighten rigor.\n` +
  `4. The honest one-paragraph verdict to append to the report.\n` +
  `Be decisive. Distinguish real defects from nitpicks.`,
  { label: 'synthesis', phase: 'Synthesize' });

return { audits: valid, synthesis };
