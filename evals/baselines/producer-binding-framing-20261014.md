# Producer citation framing: retained-answer reaudit

Parser v4 checks two fixed representations of each associated fenced snippet
against the same pinned line range: the Markdown-rendered body (up to the
opening fence's indentation removed per line) and the raw body. It removes
exactly one final LF or CRLF from each. A raw-only match is **unverifiable**,
because the displayed snippet does not match the claimed source range. This is
a literal-binding diagnostic, not a new quality assessment.

## Inputs and integrity

| Input | Contract |
|---|---|
| Answers | The same 32 retained answers: 8 development tasks, 2 repetitions, ordinary and quoted arms |
| Sources | The same 8 pinned snapshots; each admitted file checked against its size and SHA-256 |
| Original experiment | All 15 completed-campaign artifact seals and 32 request/result/answer identities verified; no answer or grade rewritten |
| Output | [Public JSON](producer-binding-framing-20261014.json) with per-answer counts, match modes, transitions and digests; full audit stays in the local retained archive |
| Model calls | 0 |

## Literal-binding results

The denominator is a citation occurrence, not a claim or an independent task.

| Arm and parser | Citations | Valid | Invalid | Unverifiable |
|---|---:|---:|---:|---:|
| Ordinary, v3 | 367 | 0 | 6 | 361 |
| Ordinary, v4 | 367 | 0 | 6 | 361 |
| Quoted, v3 | 416 | 227 | 109 | 80 |
| Quoted, v4 | 416 | 227 | 9 | 180 |

| Quoted v4 match mode | Occurrences | Meaning |
|---|---:|---|
| Both | 97 | Raw and rendered snippets match the declared range |
| Rendered only | 130 | The displayed snippet matches |
| Raw only | 100 | The raw body matches; binding remains unverifiable |
| Neither | 9 | Both checked representations fall outside the declared range |
| Unchecked | 80 | No complete two-representation comparison was possible |

The 100 raw-only cases account exactly for the shift from `invalid` to
`unverifiable`; valid bindings and both arm denominators are unchanged. Of the
remaining nine invalid quoted citations, six raw bodies match the pinned file
only when the declared range is extended by one line. The other three have no
exact raw or rendered match anywhere in the pinned file. These observations do
not authorize range repair or semantic acceptance. Original reviewer outcomes
remain ordinary 15/16 and quoted 14/16 satisfied.

## Reproduce

The retained archive and its source snapshots are local inputs. Run from the
repository root with the parser and evidence auditor matching the public JSON's
`provenance.implementation_sha256`. Use new output names: the controller refuses
to replace an existing report.

```sh
python3 -B .mastermind/research/producer-binding-reaudit-20261014/reaudit-v4.py \
  --archive .mastermind/research/source-quotes-ab-20261014 \
  --output /absolute/path/to/new-retained-report.json \
  --public-output /absolute/path/to/new-public-report.json
python3 -m unittest discover -s tests -t .
python3 scripts/validate.py
```

The frozen local parser and controller are
`.mastermind/research/producer-binding-reaudit-20261014/producer_binding-v4.py`
and `reaudit-v4.py`. The controller imports the live repository parser; the
frozen parser is an evidence copy, not an automatic fallback. The public JSON
contains no raw answers or quote bodies;
its `retained_report_sha256` binds the complete local audit. Literal matches do
not prove that the quoted text supports the surrounding assertion, that all
material claims were cited, or that either response arm is acceptable.
