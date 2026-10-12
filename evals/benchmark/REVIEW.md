# Offline answer review

The review CLI freezes a planned benchmark batch, imports structured assessments
and accounts for every attempt. It makes no model calls and does not execute
Git, an indexer or the researched application. Python 3.10+ and POSIX are required.

Keys with `acceptance_criteria` export schema 3 assessments. Judge every criterion
against its original request excerpt and quote the retained answer when it is met.
Any unmet criterion, material error or overclaimed unknown makes the task
unsatisfied; otherwise unresolved criteria keep it unknown. Source coverage
remains separately visible. Legacy schema 1/2 assessments retain their original
full-key semantics and cannot be pooled with user-acceptance outcomes.

See [product objectives](../PRODUCT.md) for the acceptance and resource gates.

Review supports the structured research keys in the
[calibration](README.md#calibration-corpus) and [qualification](README.md#qualification-corpus)
corpora. Qualification keys always carry acceptance criteria. Custom keys with only
task/revision fields and decision-task grading are outside this path.

## Export

```sh
python3 -m evals.benchmark.review export /absolute/path/to/batch-id \
  --output /absolute/path/to/new-review-export
```

The output parent must exist. Use a new directory outside the batch. Inputs must
be canonical and contain no symlinks. Relocated archives are supported without
requiring their original runtime executables.

| Output | Purpose |
|---|---|
| `reviewer/packet.json` | Public task, rubric, source descriptions and shuffled opaque attempt IDs |
| `reviewer/source/` | Verified common source snapshot |
| `reviewer/answers/` | Exact retained answers |
| `reviewer/assessment-template.json` | Original blank form |
| `coordinator.json` | Private mapping to conditions, repetitions and execution records |
| `seal.json` | Bound packet, form and coordinator hashes |
| `reviews/` | Immutable imported assessments |

Give the reviewer only `reviewer/` and an editable copy of the form. Keep the
coordinator and raw run artifacts separate. Conditions, model names and timings
are omitted from reviewer metadata, but answer text can still reveal them.
The tool does not contact or send data to a reviewer.

The original reviewer folder has a checked inventory. Extra or missing files,
changed originals or symlinks invalidate the packet. Keep completed forms
outside it. If a batch changes during export, let it stabilize and export again
to a new directory.

## Account for all attempts

| Attempt state | Accounting |
|---|---|
| Completed with an intact declared answer | Completed and reviewable |
| Failed with an intact declared answer | Failed and reviewable |
| Setup failure | Failed |
| Prepared with no result or lock | Not run |
| Lock present without result | Unfinished. Activity versus crash is unknown |
| Missing trial or manifest | Missing artifacts |

Only the answer declared in `result.json` is admitted. Orphan answers or trace
fragments are not recovered as completed outputs. Retained results require their
intact empty `run.lock`. Bound batches also require `execution.lock`, the plan
binding and predecessor chain. Complete chains are `verified`, intact incomplete
prefixes `partial`, and unestablished chains `not_established`. Older unbound
batches remain `unverified_legacy`.

An intact source snapshot from another trial with the same common identity can
supply review evidence for a failed trial. The failed trial remains marked as
such. Retained answers without any intact common source cannot be exported.

## Assess and import

```sh
cp /absolute/path/to/review-export/reviewer/assessment-template.json /absolute/path/to/assessment.json
chmod u+w /absolute/path/to/assessment.json
```

Set a stable lowercase `reviewer` label and complete every retained answer.
Keep generated packet, answer, rubric and export hashes unchanged.

| Field | Required assessment |
|---|---|
| `claims` | Exact excerpts, supported/unsupported/contradicted/unknown status, source anchors, material-error flag and rationale |
| `knowns` | Every required fact, with an answer excerpt or a missing value |
| `unknowns` | Every expected unknown, with appropriate/overclaimed/omitted status and an excerpt or a missing value |
| `outcome` | Whether the answer satisfies the original task: `satisfied`, `unsatisfied` or `unknown`, with a rationale |

Supported and contradicted claims require source anchors. A material error must
be unsupported or contradicted. The importer checks excerpt membership and
anchor ranges. The reviewer is responsible for semantic judgment and complete
material-claim selection.

The version 2 form requires an explicit task outcome. `satisfied` must agree
with covered required facts, appropriate unknown handling and supported selected
claims without material errors. This consistency check does not verify the
reviewer's judgment. Version 1 submissions remain readable; their task outcomes
stay unknown rather than being inferred from selected claims.

```sh
python3 -m evals.benchmark.review import /absolute/path/to/review-export \
  --assessment /absolute/path/to/assessment.json
python3 -m evals.benchmark.review status /absolute/path/to/review-export
```

Each reviewer gets one immutable receipt. Partial, duplicate, stale or invented
assessments are rejected. Concurrent import returns `review_busy`. Retry after
the other import finishes. Additional reviewers are retained separately, up to
64, without averaging away disagreement. Labels do not verify reviewer identity.

`status` verifies artifacts and reports attempts, execution-order integrity,
reviewers, reviewed answers and descriptive assessments overall/by condition.
It preserves task outcomes, material-error flags, required-known coverage, unknown handling
and disagreement. Reviewer-selected claim rows are not aligned votes.
Multiple reviewers do not increase the number of experiments.

For a corpus-wide campaign, repeat import in every case directory under the
review set. Use the same reviewer label only for the same reviewer. The campaign
comparison checks each export against its original batch, task and key.

## Assign reference and blind reviewers

Purpose: keep the human reference separate from model assessments. For new
calibration reviews, use these roles:

| Role | Reviewer label | Responsibility |
|---|---|---|
| Reference | `human` | A real person reviews the frozen sources and answers without seeing condition mappings or model verdicts. These are the reference labels for judge calibration |
| Blind model reviewer | `gpt-6-1-sol-blind` | GPT 6.1 Sol, requested model `gpt-6.1-sol`, reviews the same inputs in a fresh session without the reference labels or prior judge outputs |
| Historical model reference | Existing label, such as `claude-reference` | Retained model evidence; never relabel it as human evidence |

Prerequisite: an intact sealed export. Human-based calibration additionally needs
an actual human reference assessment; the two reviewers can work independently.
The previous chat's source review had seen aggregate results and is not the new
blind GPT review. Until a person submits the reference assessment, human
calibration remains pending; seeded-defect agreement may still be reported with
its original reference identity.

Give each reviewer only the export's `reviewer/` directory and the instructions
for their role. Keep `coordinator.json`, raw trials, condition mappings, imported
receipts, seed `key.json`, prior results and this chat outside the review session.
Use [blind-review-gpt61.md](blind-review-gpt61.md) for the GPT reviewer. Record the
requested model, runtime, instruction hash, visible packet hash and any prior
exposure with its retained assessment; a label alone does not attest the model or
prove blindness. Answer wording can still reveal a condition.

Each reviewer fills every answer in `assessment-template.json`, using their own
reviewer label. Import the two assessments separately, after both initial
assessments have been retained, without rewriting the original export:

```sh
python3 -m evals.benchmark.review import /absolute/path/to/review-export \
  --assessment /absolute/path/to/human-assessment.json
python3 -m evals.benchmark.review import /absolute/path/to/review-export \
  --assessment /absolute/path/to/gpt-assessment.json
```

The existing automated `judge` command below runs a Claude Code transport with an
Anthropic-compatible endpoint. It does not run Codex: do not pass a Codex CLI as
its `cli`. For GPT, retain the fresh session's assessment and import it through
the same reviewer contract. An invalid import can be corrected under that
reviewer's label before admission. A changed admitted assessment needs a new
reviewer label and a retained explanation; never overwrite the first verdict.

## Assess with a model judge

A model judge fills the same assessment form and is admitted through the same
import checks. Its labels are model declarations: calibrate it against blind human
review before using it as a primary reviewer.

Prerequisites: a review export whose key has acceptance criteria, a pinned Claude
Code CLI, `ANTHROPIC_API_KEY` (the CLI runs in `--bare` mode and never reads OAuth
or the keychain) and a frozen instruction. [judge-instruction.md](judge-instruction.md)
is a starting instruction, not a calibrated one.

```json
{"cli": {"path": "/absolute/path/to/claude", "sha256": "<sha256>", "version": "<version>", "origin": "npm"},
 "model": "<exact model ID>", "instruction": "/absolute/path/to/judge-instruction.md",
 "reviewer": "judge", "attempts": 3, "timeout_seconds": 1800}
```

```sh
python3 -m evals.benchmark.judge /absolute/path/to/review-export \
  --config /absolute/path/to/judge.json --output /absolute/path/to/new-judge-run
```

Optional `"base_url"` sends the CLI's requests and `ANTHROPIC_API_KEY` to another
Anthropic-compatible https endpoint, for example GLM through
`https://api.z.ai/api/anthropic` with `"model": "glm-5.3"`. That provider then
receives the task, key, sources and answers. Such endpoints can echo the requested
model name, so the served model remains unverified.

| Contract | Behavior |
|---|---|
| Visible inputs | One answer per call: the verified packet and sources, that answer and a one-review template, in a fresh temporary directory. No other answers, coordinator, raw trials or earlier attempts |
| Runtime | `--bare`, only the `Read` tool and no allow rule, so `dontAsk` denies reads outside the copy. No MCP servers or user, project and local settings; private `HOME` |
| Observed runtime | The stream's init event must report `Read` only, no MCP servers, the copy as cwd, `dontAsk`, the pinned CLI version and the requested model. Plugins and permission denials are recorded |
| Attempts | Same prompt each time, at most 3 per answer; an answer stops at its first review that passes the import checks for that answer |
| Quote repair | A quote or excerpt that matches the answer only after mapping curly quotes, dashes and non-breaking spaces to ASCII is replaced by the unique exact answer span before validation; `quotes_repaired` records the count. Ambiguous or paraphrased passages stay rejected |
| Rejected attempt | Unclean exit, timeout, output cap, runtime mismatch, error result, another model, no JSON, not exactly one review or a rejected review; retained with its error code |
| Output | `judge.json`, `answer-K-attempt-N.{stdout,stderr,json}`, `assessment.json` when every answer is reviewed, and `judge-run.json` on every path, with `error` when the run stopped early. Exit 0 only after import |
| Answer without a valid review | The run stops, no receipt is written and the export's outcomes stay unresolved |

Another reviewer may import during a judge run; the importer rechecks the export
under its lock. The CLI's permission layer is not an OS sandbox, and built-in
plugins still load under `--bare`. Judge output quotes answers and keys, so keep
it with the review export. If the import fails after a valid attempt, import the
retained `assessment.json` with `review import`. The importer checks quotes,
anchors and outcome consistency, not semantic truth.

## Calibrate the judge with seeded defects

Purpose: measure whether a judge rejects answers with a known defect and accepts
answers a reference reviewer judged satisfied. Seeded defects give ground truth by
construction; they do not replace calibration against blind human review, and a
judge may catch artificial edits more easily than natural errors.

Prerequisites: a review export whose key has acceptance criteria, a reference
reviewer's receipt in that export, and mutant answers written from originals that
reference labelled satisfied. Each mutant carries exactly one defect:

| Defect | Target | `passage` | Anchors | Ground truth |
|---|---|---|---|---|
| `criterion_removed` | `criterion_id` | Removed text: in the original, absent from the mutant | none | criterion unmet |
| `fabricated_citation` | `criterion_id` | Text with wrong citations: in the mutant, not the original | correct locations | criterion unmet |
| `listed_false_claim` | `false_claim_index` | The false sentence: in the mutant, not the original | contradicting source | material error |
| `novel_false_claim` | none (`{}`) | The false sentence, not equivalent to a listed false claim | contradicting source | material error |
| `overclaimed_unknown` | `unknown_index` | The unverifiable assertion | none | unknown overclaimed |

```json
{"kind": "mastermind-judge-calibration-mutations", "schema_version": 1, "reference": "reference",
 "controls": ["review-<original id>"],
 "mutants": [{"source_review_id": "review-<original id>", "defect": "listed_false_claim",
              "target": {"false_claim_index": 0}, "answer": "mutants/m01.md",
              "passage": "<exact sentence>", "anchors": ["src/file.py:12"], "rationale": "<why it is unsatisfied>"}]}
```

```sh
python3 -m evals.benchmark.judge_calibration build /absolute/path/to/review-export \
  --mutations /absolute/path/to/mutations.json --output /absolute/path/to/new-set
python3 -m evals.benchmark.judge_calibration run /absolute/path/to/new-set \
  --config /absolute/path/to/judge.json --output /absolute/path/to/new-run
python3 -m evals.benchmark.judge_calibration score /absolute/path/to/new-run [...] \
  --output /absolute/path/to/new-report.json
```

`answer` paths are relative to the mutations file. `build` refuses a mutant equal
to its original, a passage that breaks its rule, a target outside the key, missing
or out-of-range anchors, a control or original that the reference did not label
satisfied, and duplicate answers.

| Contract | Behavior |
|---|---|
| Set | `reviewer/` holds the source export's task, key and sources with new answer IDs in shuffled order, in the export packet format. `key.json` maps answers to defects and `seal.json` binds packet, template and key; neither is copied to the judge |
| Run | The judge contract above, one answer per call. Every answer is attempted; an unresolved answer does not stop the rest. Output: `judge.json`, attempt files and `calibration-run.json`; no receipt is imported. The judge's reviewer label must differ from the reference's |
| Score | Re-verifies each set and every accepted review. Refuses a changed set, an interrupted run (`error` set or answers not all attempted), runs with different judge configurations (CLI, model, endpoint, instruction, prompt, tools, attempts, timeout), the judge scored against its own reference, and any answer text scored twice, including a rebuilt set |
| `sensitivity` | Controls judged `satisfied`: over resolved answers and worst case (unresolved counted as errors), with one-sided 95% Clopper–Pearson lower bounds that treat answers as independent |
| `specificity` | Mutants judged `unsatisfied`, same forms; an `unknown` verdict is a miss. `by_defect` splits it by defect |
| `located` | Mutants where the judge flagged the broken element: the target criterion unmet, the target unknown overclaimed, or a material error on a claim whose every occurrence overlaps the passage. Same forms as `specificity` |
| `youden_j` | `sensitivity + specificity − 1`, in resolved and worst-case forms |
| `gwet_ac1` | Three-category agreement over resolved answers, so `unknown` agrees with neither ground truth. `case_bootstrap_lower_95` is the 5% quantile of a case-level bootstrap and is `null` below `minimum_cases_for_bound` (5) cases; sets from one export are one case |

A judge that rejects a mutant for an unrelated reason counts in `specificity` but
not in `located`. Keep sets with their export: answers quote the key and sources.

## Compare paired outcomes

```sh
python3 -m evals.benchmark.review compare /absolute/path/to/review-export \
  --baseline raw --candidate refined
```

Use IDs from the planned matrix. For default batches, for example, compare
`source` with `portable`. Every repetition contributes a pair under the same
original task and key. Each reviewer gets a separate result.

| Evidence | Task-success value |
|---|---|
| Completed, verified runtime/source and declared `satisfied` | 1 |
| Declared `unsatisfied`, failed attempt or recorded runtime-contract violation | 0 |
| Unreviewed, unknown, not run, unfinished, missing evidence or unverified runtime | [0, 1] |

`success_delta` is candidate minus baseline across **all planned pairs**. Its
lower/upper values include unresolved outcomes; they are uncertainty bounds,
not confidence intervals. `point` exists only when the bounds coincide. Wins,
ties and losses describe resolved pairs. Repetitions of one task do not establish
performance on unseen tasks or a causal product-quality change.

The coordinator also retains setup/run time, four token counters, turns and cost
per attempt. `resources` reports observed totals and measured/unknown trial counts
per condition, including failures. Missing measurements remain null; a partial
total is not a complete cost estimate. This scope covers trial preparation and
adapter attempts, excluding external instruction generation and native client
delivery. Reviewer files contain no resource metadata.

`efficiency` counts successful outcomes and resources across every planned
attempt, including failures. Each reviewer gets a separate estimate. Campaign
totals combine that reviewer's cases; missing reviews preserve unknown outcome
bounds.

| Metric | Definition and boundary |
|---|---|
| Context tokens | Uncached input + cache read + cache write |
| Total tokens | Context + output |
| `run_seconds` | Adapter invocation time |
| `trial_total_seconds` | Trial setup + invocation; excludes campaign coordination, refinement generation and profile mining |
| Resource per successful outcome | Complete resource total / known successful outcomes; undefined with zero successes |
| Useful outcomes per resource | Known successes / complete positive resource total; zero when known successes are zero |
| Resource savings | `1 - candidate_resource / baseline_resource` |
| Resource per success savings | `1 - candidate_per_success / baseline_per_success` |
| Useful outcome yield gain | `candidate_yield / baseline_yield - 1`; undefined when baseline yield is zero |

Point estimates require resolved outcomes and complete measurements. A partial
token total does not become a complete total. `quality_preserved_on_resolved_pairs`
requires all pairs resolved and no previously successful baseline losing its
success. Zero successes in both arms can meet that flag while providing no
useful-work benefit. These are descriptive results on the declared corpus, not
population confidence intervals or independently established causal uplift.

When resource totals are complete, unresolved outcomes still give deterministic
yield bounds: `S_lower / C` through `S_upper / C`. For a guaranteed positive
baseline yield, relative gain ranges from
`candidate_lower / baseline_upper - 1` through
`candidate_upper / baseline_lower - 1`. A potentially zero baseline, zero
resource total or missing resource measurements leaves the relative range
unknown. These ranges describe possible review outcomes; they are not confidence
intervals and do not establish reviewer independence.

New exports use coordinator version 3. Versions 1 and 2 remain readable with
unknown resource measurements and runtime checks. Old records are not upgraded
to stronger evidence merely by importing them.

## Evidence boundary

Hashes bind local artifacts. They are not signatures or protection against an
owner rewriting the entire archive. Semantic assessments remain declarations.
Original `result.json` files retain their transport and quality status.
Retained answers stay `review_pending` in those original records. Results keep
`comparison_accepted: false` and `quality_uplift: null`. A published calibration
corpus and manual review alone do not establish held-out quality.

Reads/writes reject symlinks. Publication checks final file identity and bytes.
Interrupted unsealed exports are invalid.

| Resource | Limit |
|---|---:|
| Planned attempts | 60 |
| Source files | 128 |
| Common source | 8 MiB |
| Control or assessment JSON | 1 MiB each |
| Exported payload | 64 MiB |
| Input reads including rechecks | 1 GiB |
| Answer | Producer cap, at most 16 MiB |

```sh
python3 -m unittest tests.evals.benchmark.test_review tests.evals.benchmark.test_corpus
```

These tests exercise accounting, relocation, source recovery, stale evidence,
review admission and publication using disposable fixtures without model calls.
