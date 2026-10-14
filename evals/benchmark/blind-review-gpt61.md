# Blind review instructions for GPT 6.1 Sol

Use a fresh GPT 6.1 Sol session with requested model `gpt-6.1-sol`. Retain this
instruction's hash and the runtime identity with the review. Reviewer label:
`gpt-6-1-sol-blind`. This is a model assessment; the reference reviewer is a real
person using label `human`.

Your inputs are only the sealed reviewer's `packet.json`,
`assessment-template.json`, `answers/` and `source/`. Read the task, original
request, rubric, each answer and the relevant frozen source. Do not inspect the
coordinator, original trial directories, condition mappings, seed key, human or
other model assessments, previous chat, summary scores or external sources. If
you have already seen those inputs, record that exposure and do not declare the
review blind. A fresh session does not establish independent human review.

Fill the supplied template for every retained answer. Preserve `export_id`,
`packet_sha256`, answer and rubric hashes, and review IDs. Set only `reviewer` to
`gpt-6-1-sol-blind`. Return a complete assessment JSON with claim support, known
coverage, unknown handling, acceptance criteria and outcome, using the supplied
schema. Quote exact answer substrings and anchor evidence to the supplied source.
For every cited anchor, include `claims[].source_quotes` entries with `anchor`,
the file's actual `source_sha256` from `packet.json` `source_files`, and a literal
source `quote` within the cited line range. Preserve whitespace and punctuation;
do not reconstruct excerpts or digests. If a source quote is unavailable, leave
it absent and explain the limitation. The separate literal binding audit does
not decide support, acceptance or outcome.

Judge whether the original request was fulfilled. For each central factual
claim, open its cited source location and check that those lines support that
claim. Finding correct code elsewhere does not repair the answer's citation. If
a required evidence binding points to unrelated lines, mark the affected
criterion unmet and explain the mismatch with a correct source anchor. Distinguish
this from a minor citation omission on a claim that does not affect the request.

Preserve runtime and external-consumer unknowns. Do not assert an absence of
downstream uses, test coverage or release history from a source allowlist that
excludes them. Required omissions and material false conclusions make the answer
unsatisfied. An inability to resolve a criterion remains unknown; keep the
failure denominator and do not infer success from schema validity.

Retain the first complete assessment before seeing reference labels or aggregate
results. Do not revisit a valid judgment merely to improve agreement. Subsequent
adjudication is a separate, exposed review with a new label and retained reasons.
