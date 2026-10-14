# Producer citation parser: retained-answer reaudit

This offline analysis applies `mastermind-producer-binding-v2` to the same
32 retained answers from [the source-quotes comparison](source-quotes-20261014.md).
It makes zero model calls and checks literal source bindings. It adds no new
experimental answers, semantic judgments or qualification evidence.

Quoted answers now have **227 valid bindings**, compared with 84 under the
frozen experimental parser. The improved coverage also reveals **109 snippets
outside their declared ranges**. Neither count measures claim correctness.
The retained Astra outcomes remain ordinary 15/16 and quoted 14/16 satisfied.

## Inputs and output

| Contract | Value |
|---|---|
| Retained answers | 8 development tasks, 2 repetitions, ordinary and quoted arms: 32 answers |
| Sources | The same 8 pinned source snapshots; every admitted file checked by size and SHA-256 |
| Answer selection | Effective results, including 11 producer transport retries; original failures remain retained |
| Answer integrity | Every request, result and standalone `answer.md` checked against the original seals/report |
| Markdown framing | Remove up to the opening fence's 0–3 spaces per body line and one final LF/CRLF; no source-dependent repair |
| Filename resolution | Exact path first, then a unique admitted basename; ambiguous candidates remain unverifiable |
| Semantic outcomes | Carried from the original report without regrading |
| Public evidence | [JSON](producer-binding-reaudit-20261014.json): 32 slot records, counts, transitions and input/code digests |
| Full evidence | Local `.mastermind/research/producer-binding-reaudit-20261014/`: complete audit, frozen parser/controller copies and verification logs |

## Coverage

The unit is a citation occurrence, not a claim or an independent task.

| Arm and parser | Citation occurrences | Valid | Invalid | Unverifiable |
|---|---:|---:|---:|---:|
| Ordinary, frozen experimental parser | 367 | 0 | 72 | 295 |
| Ordinary, maintained v2 | 308 | 0 | 0 | 308 |
| Quoted, frozen experimental parser | 416 | 84 | 59 | 273 |
| Quoted, maintained v2 | 403 | 227 | 109 | 67 |

The 59 ordinary and 13 quoted occurrences omitted by v2 are ranges written with
an en dash, `path:first–last`. The old regex partially parsed each as a citation
to its first line; v2 rejects the full unsupported token. V2 currently requires
the ASCII hyphen in `first-last`. Denominators therefore differ, and ratios are
not directly comparable accuracy rates. Individual transitions use the original
character span and literal citation as identity.

V2 also excludes references inside unsupported indented-code lines and avoids
interpreting numeric fields such as `top:1` as source paths. These protections
do not account for the 72 omitted occurrences in this retained corpus.

| Observed transition | Ordinary | Quoted |
|---|---:|---:|
| Unverifiable → valid | 0 | 144 |
| Valid → valid | 0 | 83 |
| Valid → unverifiable, ambiguous association | 0 | 1 |
| Invalid → unverifiable, uniquely resolved but unquoted filename | 53 | 42 |
| Unverifiable → invalid, literal quote outside range | 0 | 105 |
| Old partial parses of unsupported en-dash ranges excluded | 59 | 13 |

The quoted answers contain 346 closed fenced blocks, including the 258
three-space blocks missed by the old parser. V2 associates 336 blocks with
citations. It retains 21 ambiguous citation occurrences and 46 missing-snippet
occurrences as unverifiable. All 109 invalid bindings fail literal range
membership. Recognizing a block does not make its contents valid.

The filename resolver recovers 53 ordinary and 42 quoted references under the
supported grammar. These references have no associated snippets, so resolution
establishes the path but cannot establish a literal binding. The original format
diagnostic's larger counts of 66 and 55 filename references include 13 per arm
with unsupported en-dash ranges.

## Quoted answers by task

Each row combines two retained repetitions; no grades were changed.

| Task | Old valid | V2 valid | V2 invalid | V2 unverifiable |
|---|---:|---:|---:|---:|
| callees-definition-boundaries-01 | 14 | 44 | 2 | 4 |
| concept-match-navigation-01 | 0 | 43 | 0 | 21 |
| document-evidence-boundaries-01 | 14 | 29 | 0 | 2 |
| documentation-concepts-01 | 40 | 50 | 36 | 0 |
| reference-removal-evidence-01 | 0 | 28 | 2 | 22 |
| source-receipt-navigation-01 | 0 | 4 | 41 | 0 |
| source-root-bindings-01 | 16 | 16 | 19 | 0 |
| task-phase-continuity-01 | 0 | 13 | 9 | 18 |

## Reproduce and verify

For an ordinary sealed review export, use the supported offline command:

```sh
python3 -m evals.benchmark.review audit-producer-bindings /absolute/path/to/review-export \
  --output /absolute/path/to/new-producer-binding-audit.json
```

See [the review runbook](../benchmark/REVIEW.md#audit-citations-in-producer-answers)
for supported syntax, bounds, output statuses and recovery. Publication succeeds
even when bindings are invalid or unverifiable; exit 0 is not an acceptance gate.

This custom retained campaign needs its original local archive and source
snapshots. The controller also binds absolute source references to the exact
prefix from each verified request. Give every repeat new output paths outside
the original inputs:

```sh
python3 -B .mastermind/research/producer-binding-reaudit-20261014/reaudit-v2.py \
  --archive .mastermind/research/source-quotes-ab-20261014 \
  --output /absolute/path/to/new-retained-reaudit.json \
  --public-output /absolute/path/to/new-summary.json
python3 -m unittest discover -s tests -t .
python3 scripts/validate.py
```

The public JSON contains no raw answers, quote bodies or host absolute paths.
It binds the original full report, all 15 completed-campaign artifact seals,
32 request/result/answer slots, 8 source snapshots and the new implementation.
Inputs were rechecked before publication. Reproduction requires the retained
archive; the Git summary does not reconstruct it.

For exact reproduction, the repository's parser and evidence-auditor digests
must match `provenance.implementation_sha256` in the JSON. The controller imports
the current repository modules; retained source copies are not selected
automatically. A newer parser requires a new report with its own digests.

## Verification

All 499 deterministic Python tests passed on the final implementation, including
28 parser boundary tests and the real sealed-export CLI integration test. Runtime
and test-file digests remained unchanged throughout the full run. Artifact
validation checked 41 artifacts with zero errors or warnings.

Independent verification reproduced all 32 audits from 92 source-file records
across the eight snapshots and matched every public count, transition and digest.
The original campaign's sealed artifacts and assessments remain unchanged.

## Boundaries

This is post hoc parser analysis on one repository's development answers.
It does not change the original experiment's failure denominators, resource
measurements or model assessments. The improved parser has no measured effect
on producer token use or task acceptance.

Literal source identity does not establish entailment or complete material-claim
coverage. Missing snippets and unsupported syntax remain unknown. Exact-profile
judge calibration and human adjudication are still required before using these
diagnostics to decide which semantic assessments can support an acceptance gate.
