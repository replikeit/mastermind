# Source quotes and automatic binding audit

Eight existing development tasks, two repetitions per arm, with fresh GPT-6.1
Sol/high producer sessions and condition-hidden Astra/high review. Adding literal
source snippets did not improve declared acceptance: ordinary answers scored
15/16 satisfied and quoted answers 14/16. Output tokens increased by 56.59%.
This run does not support enabling mandatory snippets for every producer.

The judge instruction now requests structured `source_quotes`. The judge runner
automatically audits imported receipts and records the audit path and digest.
Literal binding remains separate from semantic grades. See the operational
[review instructions](../benchmark/REVIEW.md).

## Fixed conditions

| Contract | Value |
| --- | --- |
| Design | 8 tasks × 2 repetitions × 2 arms = 32 answers; 16 matched pairs |
| A / B | Ordinary answer / same request plus one frozen literal-snippet instruction |
| Requested producer | GPT-6.1 Sol/high |
| Requested judge | Astra/high; original request, criteria, complete answer and pinned source files |
| Judge isolation | Fresh session and opaque source projection per answer; arm, map, producer profile, costs and earlier grades hidden; answer style visible |
| Map | Same lexical `focused_shortlist_v3` payload per task, 1600-byte cap, 171-byte navigation advice |
| B addition | 495 UTF-8 instruction bytes; 497 request bytes including separator |
| Source and tools | Same pinned sources, indexes, native 3.2.4, tool contracts and runtime profiles between A and B |
| Limits | 600 seconds; answer/stderr 262144 bytes; trace 16777216 bytes; no explicit round or output-token cap |
| Ordering | Four tasks start with each arm; second repetition reverses order; late recovery disturbs actual execution order |

The served model and monetary cost are unknown. Producer and judge tools are
fixed within their respective stages. Source bindings and runtime hashes are in
the [compact JSON report](source-quotes-20261014.json).

## Outcomes

S = model-declared satisfied; U = unsatisfied. Repetition 1/2 corresponds to
stored repetition 0/1. All 32 effective assessments passed structural admission;
unknown/unresolved counts are zero. These are model assessments, not human labels.

| Task | A, repeat 1 | B, repeat 1 | A, repeat 2 | B, repeat 2 |
| --- | --- | --- | --- | --- |
| `callees-definition-boundaries-01` | S | S | S | S |
| `concept-match-navigation-01` | S | S | S | S |
| `document-evidence-boundaries-01` | S | S | S | S |
| `documentation-concepts-01` | S | U | U | U |
| `reference-removal-evidence-01` | S | S | S | S |
| `source-receipt-navigation-01` | S | S | S | S |
| `source-root-bindings-01` | S | S | S | S |
| `task-phase-continuity-01` | S | S | S | S |
| Total | 8/8 S | 7/8 S | 7/8 S | 7/8 S |

There is one paired S-to-U loss and no U-to-S gains. All three negatives concern
documentation concepts. For the paired loss, Astra identified missing Rust outer
attributes and Python module-constant signature paths, an overbroad statement
about control-character rejection, and original citation ranges that did not
support the whole claim. The other negatives also missed extraction or
unsupported-source boundaries. Their original material-error declarations and
assessment digests are retained in the JSON; grades were not repaired or resampled.

## Producer resources

Totals below cover 16 completed answers per arm, including successful empty-start
retries. All 16 pairs completed. Deltas compare B with A.

| Metric | A | B | Delta |
| --- | ---: | ---: | ---: |
| Uncached input tokens | 1,104,509 | 1,096,185 | −0.75% |
| Output tokens | 70,514 | 110,418 | +56.59% |
| MCP calls | 578 | 565 | −2.25% |
| Sum of attempt durations, seconds | 2,747.78 | 3,953.74 | +43.89% |

Duration sums are not campaign wall time; they include service and transport
variation. Eleven empty producer failures have unknown usage, so all-attempt
token totals remain unknown. Completed-answer deltas do not establish overall
token or monetary savings. Judge usage is recorded separately in the JSON.

## Literal binding diagnostics

A correct literal quote does not establish that its source entails the claim.
Auditing does not rewrite support, acceptance or outcome.

| Judge `source_quotes` | Valid anchors | Invalid anchors | Anchorless criterion placeholders |
| --- | ---: | ---: | ---: |
| Reviews of A | 211 | 3 outside the declared span | 2 unverifiable |
| Reviews of B | 206 | 0 | 2 unverifiable |

The three invalid judge quotes occur in ordinary-arm reviews of concept matching
(repeat 2) and task-phase continuity (both repeats). Their satisfied declarations
remain unchanged; this limits confidence in the model-only evidence.

The frozen producer Markdown parser reported A: 0 valid, 72 invalid, 295
unverifiable citation occurrences; B: 84 valid, 59 invalid, 273 unverifiable.
These counts are conservative diagnostics, not producer accuracy rates. B's
invalid counts comprise four literal snippets outside the declared range and
55 paths absent from the exact admitted-path inventory.

A separately bound post hoc format diagnostic found 258 indented fenced blocks
across 12/16 B answers that the column-zero parser does not recognize, and 55
filename-only references across 7/16 B answers whose basenames occur in the
source inventory. Missing association does not prove a snippet is absent;
noncanonical paths do not prove fabricated sources. Neither paths nor quotes
were normalized, resolved or repaired, and primary counts remain unchanged.

## Failures and sensitivity

| Stage | Original attempts | Empty HTTP 429 | Retries | All attempts | Effective results |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sol | 32 | 11: A 5, B 6 | 11 | 43 | 32 |
| Astra | 32 | 2 | 2 | 34 | 32 |

All 77 attempts have distinct native session identifiers. Original errors,
unknown telemetry and immutable results are retained. The append-only recovery
policy allowed one retry only for verified empty transport failures, with no
answer, productive item or MCP invocation. HTTP 429's cause is unproved.

Reviewer-recovery preparation initially expected native `segments` instead of
the source-only broker's `lines`. A bound preparation repair preserved the
unlaunched allocation and original controller, verified two actual broker replies
against pinned bytes, then used the unchanged executor. It did not call a model.

The preregistered sensitivity subset selects only pairs whose original producers
and first reviewers completed without transport recovery, never by grades.
It contains six pairs from four tasks: both arms score 6/6 satisfied. B has
uncached input +5.23%, output +39.51%, calls +3.91% and duration sum +33.62%.
This smaller subset is separate from the full result.

Eight tuned tasks from one repository are not sixteen independent tasks or a
held-out qualification. Human reference and exact-profile seeded calibration
are missing; general product benefit and statistical qualification remain false.

## Verification and retained evidence

The unchanged implementation bytes passed 470 deterministic Python tests and
artifact validation (41 artifacts, zero errors or warnings). Report validation
included 18 deterministic checks; readiness repair included 14 checks and two
real broker probes. Model-backed measurements are separate from these tests.

The committed JSON contains per-slot outcomes and digests, all 77 attempt
identities and normalized resource observations, original failure denominators,
source/index/map bindings, sensitivity counts and audit summaries. Raw answers,
traces, source projections, indexes and executable copies are in the retained
local archive `.mastermind/research/source-quotes-ab-20261014/`; they are not in
this Git report. Rechecking raw evidence requires that archive and matching
runtime/source bytes. No local archive is reconstructed by these commands.

```sh
python3 -m unittest discover -s tests -t .
python3 scripts/validate.py
# With the retained archive present; these commands do not invoke models.
python3 -B .mastermind/research/source-quotes-ab-20261014/verify_inputs.py
python3 -B .mastermind/research/source-quotes-ab-20261014/verify_reporting-v3.py
```

Keep immutable outputs and every partial attempt. Restore a failed binding-audit
publication by following [review recovery](../benchmark/REVIEW.md); do not rerun
models or replace admitted receipts. Git/subprocess verification needs an
environment that permits process-group cleanup.

Full retained report SHA-256:
`e002400d478e88e758d4e5e993ef076ffd770c11dc1f9ea89f97daa111971e2c`.
