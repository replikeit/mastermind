# Improvement roadmap (2026-10-15)

Use this roadmap to choose the next speed, token, quality and proof experiments.
It combines the [statistical reanalysis](baselines/statistical-reanalysis-20261015.md)
of retained campaigns with a source-checked survey of open techniques. It complements
[OPTIMIZATION.md](OPTIMIZATION.md) and [RESEARCH-CANDIDATES.md](RESEARCH-CANDIDATES.md);
items already covered there are not repeated.

| Input | Content |
|---|---|
| Statistical reanalysis | Retained paired tests and variance estimates; its normal-approximation resource sample-size recipe is superseded by the [exact-rule power calculation](baselines/resource-power-20261015.md) |
| Survey | 111 candidates across 8 axes plus a completeness critic: 14 `keep`, 50 `revise`, 46 `reject`, 1 `unverified` (missing citation verdict). A retained proposal may still require the corrections in its `fit` review |
| Full survey record | Local `.mastermind/research/improvement-survey-20261015/survey.json` (SHA-256 `e2bb23d1…1f415f`): sources, verdicts, corrected effects and suggested fixes |

Effects quoted from papers belong to their own benchmarks and models. Statements
marked as inference are ours. No item below is a measured Mastermind benefit.
The original survey and statistical report remain retained records. Corrections
below qualify their interpretation; they do not rewrite campaign outcomes.

## What the current measurements allow

| Claim type | Status | Consequence |
|---|---|---|
| Resource change (tokens, time, tools) | On these 8 development tasks, low effort has total tokens −34.2%, output −52.8%, producer time −44.5%, each at p=0.0078. These are completed-slot, task-level geometric-mean effects; 35 resource comparisons were uncorrected | Repetitions can resolve resource effects conditional on this corpus; held-out repositories are needed for broader claims |
| Acceptance change | No difference was detected (all resolved-pair exact McNemar p=1.00). This establishes neither equivalence nor non-inferiority. Bounds over missing labels reach −25 pp; they are not sampling confidence intervals | Keep unknowns and planned denominators, improve the outcome measure, and qualify safety separately |
| Judge reliability | Different model judges disagree on 2/14 identical answers; arms differ in 15/92 resolved contrast-pairs, with repeated tasks and a reused factorial baseline | Neither quantity identifies current judge error. Calibrate against human labels and measure same-profile test-retest reliability |
| Campaign spread | χ² p=0.38 fails to detect heterogeneity. The original satisfied-count calculation also treats unresolved reviews as non-success | Do not claim there is no campaign effect or that every outcome flip is judge noise |
| Corpus information | Four tasks carry most observed non-satisfied outcomes; four are near ceiling | Add independently selected harder tasks and negatives. Keep original corpus results; do not select the qualification set using candidate outcomes |

## Decision rules

| Rule | Basis |
|---|---|
| Resource experiments register one primary task-level geometric-mean contrast and use its exact two-sided sign-flip rule | Simulate that rule before selecting repetitions. The old 8 tasks × 8 repeats recipe gives about 69% power under its stated normal assumptions, rather than 80%; see the [recalculation](baselines/resource-power-20261015.md) and its variance sensitivity |
| Acceptance is a separate non-inferiority constraint with the existing material-error veto | The old 101–156 tasks for a 10 pp margin is an approximate planning scenario. Its pooled discordance reuses baselines/tasks; plan with clustering, missing labels and calibrated judge error before claiming a required size |
| Quality claims need a more informative outcome before more samples | Deterministic oracles, criterion-level outcomes, calibrated and length-invariant judging |
| Register qualification decisions and their error budget before testing | Repeated promotions need multiplicity control. e-LOND is deferred until valid e-values and the decision stream are specified |
| Resource savings are reported raw and API-equivalent weighted | 84% of input tokens are cache reads; output tokens cost far more than cached input |

### Resource experiment size

The [recalculation](baselines/resource-power-20261015.md) simulates the actual
two-sided sign-flip rule on 20,000 campaigns per design. These powers detect a
nonzero effect when the true token ratio is 0.90; they do not certify a saving
of at least 10%. Run SD is 0.25 for a paired log ratio. Task-effect SD remains
uncertain, so compare the central 0.05 and sensitivity 0.08 assumptions.

| Tasks × repetitions per arm | Two-arm attempts | Power at task SD 0.05 | Power at task SD 0.08 | Use |
|---|---:|---:|---:|---|
| 8 × 8 | 128 | 68.6% | 55.1% | Old recipe; insufficient for an 80% target |
| 8 × 14 | 224 | 84.3% | 66.3% | Central-assumption development screen on existing tasks; not robust to the larger task variance |
| 12 × 8 | 192 | 90.3% | 79.4% | Cheaper in producer attempts under central assumptions; needs four new independent tasks |
| 16 × 8 | 256 | 97.1% | 90.9% | Preferred planning target if eight new independent tasks can be authored; requires an explicit execution plan above the 240-attempt campaign cap |

At SD 0.08, keeping only eight tasks needs 50 repetitions per arm (800 two-arm
attempts) for the first tested even count whose marginal Monte Carlo lower bound
exceeds 80%. Broader task coverage is more useful than that repetition count if
independent tasks are available. Monte Carlo intervals exclude uncertainty in
the variance estimates. Authoring cost, judges, retries and failed-attempt usage
are additional. This calculation launches no model campaign.

## Tier 0: no model calls

Do these first. Each is deterministic and has a falsifiable check.

| Item | Change and owner | Evidence and source | Check |
|---|---|---|---|
| Source-review protocol — bounded preparation and validation | `operation-roles-v3` binds a query-only operation/constraint ledger before retrieval and requires typed own-behavior witnesses with source-bound matched constraints. Structural validation invokes no model; semantic qualification uses separate source reviewers. | [Source-witness and actual MCP study](baselines/concept-witness-20261016.md): the two prior false matches are removed and four prior role disagreements are corrected. 574/574 useful identities survive, including 413 with exact roles/order. Four fresh v3 stdio sessions complete 178 retained and 24 new queries. Independent V12 confirms 70/70 emitted rows useful, 16/16 positive queries with semantic results and 8/8 empty negative pages. | Strict V12 qualification **fails**: three semantic/context disagreements remain. Literal exact anchors are 13/16; a separate postflight diagnostic identifies two qualified-name format mismatches and one actual omitted declaration (15/16 source identities). All 24 cases remain coverage-incomplete: 1,529 unknowns and 524 source-omission records. No postflight relabeling. Historical failures remain retained; separate MCP success does not establish Desktop reconnection or general semantic quality. |
| Plain-text source delivery | `mmcg_read` emits one header preserving every Delivery field plus `N<TAB>text` lines; update client-facing parsers and accounting together | The survey's corrected lossless renderer saves 29.0% of read bytes, about 23.1% of tool bytes in this harness. The 34% renderer omitted four fields. The 79.6% read share is imposed by the broker; production share is unmeasured. Codex selects `structuredContent`, so duplicate transport fields do not imply duplicate model tokens. [SWE-agent ACI](https://arxiv.org/abs/2405.15793) | Round-trip through the actual renderer/decoder, then pinned-client visible payload, tokenizer counts and model behavior; no total-token claim from byte deltas alone |
| Hoisted precision classes | One `precision_classes` map per `mmcg_search`/`mmcg_callers` reply, referenced by id per row | Replay: −32.6% and −51.4% for those replies, about 2% of all tool bytes in the retained harness | Same lossless replay; schema version bump |
| Outline as indented text | Lossless tree string for `mmcg_outline`, signatures kept | Outlines are 6.8% of tool bytes. [LocAgent](https://arxiv.org/abs/2503.09089) | Replay byte delta and round-trip test |
| Observation replay module | Re-render retained tool results through a candidate encoder; prove losslessness, report exact byte deltas | Turns codec choices into exact measurements; models then test behavior only | 100% round-trip on retained results |
| Output and cost ledger | Add `output_tokens` and non-reasoning output to [`efficiency.py`](benchmark/efficiency.py) resources; report `api_equivalent_cost` beside raw tokens | Reasoning share varies by runtime and effort; the old 60–67% figure does not describe the current producer runs. Non-reasoning output also includes tool arguments | Recompute each profile's recorded breakdown and published totals; keep missing usage unknown |
| Receipt reuse by instruction | Executor checks `acceptance status` and reruns only checks that are not Current | `inspect_checks` already accepts unchanged passing receipts | Count redundant runs in retained executor logs |
| Mutation test of the completion gate | `cargo-mutants` restricted to gate functions, killed by the conformance selection; [cargo-mutants](https://github.com/sourcefrog/cargo-mutants) | Measures the selected suite's sensitivity to non-equivalent gate mutations; it does not measure the entire Rust refinement gap | Surviving gate mutants, triaged and reported per kill suite |
| Lesson sections | Index each `_lessons.md` lesson as its own history row; exclude `candidate` entries | Verified: the whole file is one FTS row, including unreviewed candidates | Probe set: expected lesson IDs returned |
| Localization screening metric | File and symbol Acc@k of maps, search and actual read sets against key anchors; [LocAgent](https://arxiv.org/abs/2503.09089) | Anchors exist for development and corpus tasks | Use only to reject retrieval variants |
| Tool regression replay | Replay retained MCP calls against a candidate binary and its rebuilt index on the pinned snapshot | Detects changes to recorded replies. The survey reviewer rejected outcome reuse: its singleton diagnostic was 0.578 overall and exceeded the proposal's 0.2 threshold in every family. Matching recorded calls does not qualify unseen trajectories. [Chronicle](https://arxiv.org/abs/2609.20625) | Changed-reply rate per tool under an explicit volatile-field normalization contract; historical changing/unchanged release pairs |
| Persona miner validation | Temporal hold-out and other-author lift modes in [`persona/replay.py`](persona/replay.py); [LaMP](https://arxiv.org/abs/2304.11406) | Production profile holds commit-derived conventions only | Wilson bound on held-out agreement; repository conventions dropped from personal rules |
| Misclassification-aware calibration | Add judge sensitivity, specificity, unknown rate and arm-length bias to [`qualify_calibration.py`](benchmark/qualify_calibration.py); [Lee et al.](https://arxiv.org/abs/2511.21140) | The module states reviewer error is not simulated | Size and power of the registered rule across the judge-error region |
| Probability-sampled human labels | Preregister nonzero inclusion probabilities and weights; disagreement oversampling may be retained with that design. [PPI++](https://arxiv.org/abs/2311.01453), [AutoEval](https://arxiv.org/abs/2403.07008) | Unweighted prevalence or accuracy estimates from disagreement-first labels are biased | Recorded inclusion probabilities and sampling units for every labelled answer |
| Client truncation contract | Per-client visible-reply budget with explicit continuation | Largest retained reply is about 80% of the Codex model budget | Replay plus one large-repository stress run |
| Per-request telemetry | Local OTLP receiver for Codex and Claude CLI telemetry; [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage) | Codex streams report one aggregate usage event per attempt | Model-request count and time close against run time; prompt bytes unchanged |
| Graph edge audit | Precision and recall of tree-sitter edges against SCIP from `rust-analyzer scip` | Edge accuracy has never been measured | Per edge kind and resolution class at a pinned revision |
| Passive diagnostics | Stuck-loop patterns and reply recovery hints (`total_lines` on out-of-range reads) | [OpenHands stuck detector](https://docs.openhands.dev/sdk/guides/agent-stuck-detector) | Pattern rate on the first coding campaign |

## Tier 1: model campaigns on the development tasks

Select repetitions from the [exact-rule power report](baselines/resource-power-20261015.md),
then freeze paired, position-balanced execution. Resources have one registered
primary contrast. Acceptance requires its own powered, calibrated design and
material-error veto; passing the resource experiment does not qualify quality.

| Experiment | Arms | Why now |
|---|---|---|
| Effort × map | Primary contrast: map on/off at low effort. Add high-effort cells only with the same registered repetitions and explicit cost from the power report | Measures the map effect at the shipped low setting. A full factorial can estimate interaction, but interaction power must be planned separately; 128 attempts is not a qualified default |
| Text verbosity | Codex `model_verbosity` {unset, low} crossed with effort; one counted smoke probe first | Measure answer and tool-argument output separately at each effort; run the length-invariance check first |
| Read codec | Tier-0 plain-text delivery vs current JSON | Only after the lossless replay proof |
| Installed context footprint | Phase 0: installed bytes × observed rounds; model arm only if the prediction is ≥20% raw or ≥10% weighted. [AGENTS.md study](https://arxiv.org/abs/2602.11988) | Every benchmark arm strips the context Mastermind installs for users |
| Map delivery parity | Push the measured map through the prompt hook with a source-bound receipt | The measured saving used an appended map; the product uses a pull tool |
| Judge length invariance | At least 29 meaning-preserving expansions and trims of satisfied answers; [length-controlled AlpacaEval](https://arxiv.org/abs/2404.04475) | Every output-axis decision depends on the judge not rewarding length |
| Judge test-retest | Same judge profile three times on identical retained answers | Decides whether selective review is feasible. [Trust or Escalate](https://arxiv.org/abs/2407.18370) |
| Criterion-level reliability | Criterion agreement between reviewers vs task-level agreement; [signal and noise](https://arxiv.org/abs/2508.13144) | Several criteria per answer can carry more information than one bit |

## Tier 2: a coding corpus with deterministic oracles

This tier supplies observable coding outcomes. Hidden tests cover specified
behaviors, not every aspect of correctness; retain regression, scope and material-error
review. Most quality items depend on the corpus and its independent oracles.

| Item | Mechanism | Source |
|---|---|---|
| Historical-fix inversion corpus | Task = parent commit plus redacted request; hidden oracle = the fix's tests failing on the parent and passing on the fix, plus pass-to-pass; three reruns as a flake filter | [SWE-smith](https://arxiv.org/abs/2504.21798) |
| Red-green reproduction receipt | For fix tasks, a test must build, fail by assertion at the baseline and pass on the candidate | [Otter](https://arxiv.org/abs/2502.05368) |
| Discriminating-check receipts | Rerun mapped checks at the baseline with only test files applied; record baseline and head outcome per test | [SWT-Bench](https://arxiv.org/abs/2406.12952) |
| Diff-scoped mutation score | Mutants only on changed lines; triage survivors for equivalent behavior before classifying a test gap; evaluation-side first | [cargo-mutants in-diff](https://mutants.rs/in-diff.html), [Meta ACH](https://arxiv.org/abs/2501.12862) |
| Criterion probe check | A criterion whose checks kill no changed-line mutant is `mapped_but_unprobed` | Original; attribution from the same mutation run |
| Calibrated test impact | Recall of each `mmcg_test_impact` tier against mutation kills | [Predictive test selection](https://arxiv.org/abs/1810.05286) |
| Assured test filters | k-rerun flake filter and changed-line coverage from existing coverage records | [TestGen-LLM](https://arxiv.org/abs/2402.09171) |
| Repair feedback tail | Persist the bounded failure stream; deliver an exact tail slice verifiable by recomputation | [Self-Debugging](https://arxiv.org/abs/2304.05128) |
| Differential patch audit | Compare accepted patches with the reference fix on generated tests (evaluation instrument) | [PatchDiff](https://arxiv.org/abs/2503.15223) |
| Natural negatives | Task variants whose key-fact files come from an older revision; A/A and known-harm control campaigns | [JudgeBench](https://arxiv.org/abs/2410.12784) |
| Cross-family jury | Aggregate retained GLM and Astra verdicts first; unanimity required, disagreement becomes unknown | [PoLL](https://arxiv.org/abs/2404.18796) |
| Post-completion rework | Persist the completed diff; measure later changes to agent lines as the user-correction proxy | [Copilot productivity](https://arxiv.org/abs/2205.06537) |
| Judge-free persona metric | Score agent diffs with the miner's own predicates; add a direction-reversal arm | [PrefEval](https://arxiv.org/abs/2502.09597) |
| Lessons memory | Off vs all active lessons vs token-matched lessons from another project | [VibeMemBench](https://arxiv.org/abs/2609.23570) |

## Tier 3: controller conformance and sequential decisions

Mutation and sampled conformance checks provide bounded test evidence, not a
proof that the complete Rust implementation refines the formal model.

| Item | Mechanism | First step |
|---|---|---|
| Gate mutation (Tier 0) | Surviving non-equivalent mutants locate untested behavior | Triage survivors, then add checks for observable gate requirements |
| State-machine conformance | `proptest-state-machine` sequences against an operation-sequence oracle; [docs](https://proptest-rs.github.io/proptest/proptest/state-machine.html) | Assert that `learned` implies every current obligation |
| Publication compare-and-swap | Publish completion only if the evidence-set digest is unchanged under the verification lock | Reproduce the verification-run window with the existing git-shim test pattern |
| Reachable abstract states | A reviewed abstraction from `state.json` and receipts to the model bits; one refusal scenario per reachable state with a false bit | [Trace validation](https://arxiv.org/abs/2404.16075) |
| Environment-bound receipts | `env_clear` plus a recorded allowlist for checks declared replayable | [Reproducible builds](https://reproducible-builds.org/docs/definition/) |
| Online error control | e-LOND over the qualification stream only; development screening stays non-confirmatory | [e-LOND](https://arxiv.org/abs/2311.06412) |

## Highest-leverage ideas

| Idea | Why it changes the product |
|---|---|
| Tool regression replay | Finds changes to recorded observations cheaply; outcome-reuse certificates remain rejected |
| Deterministic coding oracles | Historical-fix inversion measures independently specified coding behavior without a model judge; coverage limits remain explicit |
| Mutation-probed acceptance | Shows that the mapped checks would fail if the change were wrong, not only that they pass |
| Calibrated statistics stack | Judge-error simulation and probability-sampled human labels can support defensible decisions under checked assumptions; online control needs its own valid inputs |
| Judge-free persona evidence | The miner's own predicates score agent diffs; a reversal arm gives causal evidence of profile use |

## Rejected in this survey

Do not re-propose without new evidence. Reasons are in the local survey record.

| Axis | Rejected candidates |
|---|---|
| Latency | Edit-time check hook (unmediated execution channel), warm executor resume (breaks guard and receipt binding), plan caching (covered by task history), hedged review, sharded per-criterion review, orchestrator fan-out (no subagent tool in adapters) |
| Input tokens | Summarized literal search, multi-phrasing RRF, static embeddings, AST chunk index (edges already stored), observation masking (handoff already isolates context), goal-conditioned extractive read, per-term frequency feedback |
| Output tokens | Chain-of-Draft template (output contracts already bound answers), per-family answer budget, token-complexity frontier (not identifiable), compact review serialization (−8.4% bytes only), patch-only edit discipline, rendered executor report |
| Coding quality | Property oracles filtered against the buggy baseline (logic flaw), multi-candidate patches (cost, single executor), static-analyzer delta (already expressible) |
| Statistics | Betting confidence sequences (single interim look), small-sample Bayesian statistic, pairwise preference endpoint, latency CUPED (already detectable) |
| Formal proof | Concurrent TLA+/Quint spec (lock model wrong), Kani core (targets missing), Stateright model (decisions are I/O-bound), crash enumeration (writes already synced), DSSE signing and transparency log (same-uid key exposure), temporal-logic monitor |
| Memory | Outcome-counted lessons, verified-procedure memory, edit-delta preference induction (no persisted diff), Mem0 conflict triage, rule usefulness ranking and specificity ranking (no habits to rank), graph-scoped push lessons |
| Workflow | Model-equality drift canary, learned mode selection, budget tracker, production holdout receipts, plan-footprint disagreement trigger |

## Measurement template

Use this for every candidate before any model run.

| Field | Required content |
|---|---|
| Hypothesis | One axis, direction and minimum useful effect |
| Phase 0 | Free replay or count that can stop the work |
| Arms | Frozen conditions differing in one factor (or a declared factorial) |
| Unit and sample | Independent tasks, repetitions per task, power calculation from the reanalysis variances |
| Primary metric | Task-level geometric-mean ratio or a deterministic oracle outcome |
| Gate | No paired acceptance loss, material-error veto, all attempts counted |
| Retained record | New baseline path with source, runtime and judge bindings |
