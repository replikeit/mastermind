You review answers to one read-only source research task. Judge each answer
against the original task, its review key and the source in `source/`. Answers
come from different conditions in shuffled order; do not guess which condition
produced an answer, and do not reward length, confidence or style.

For every answer in `assessment-template.json`, fill each field:

| Field | Rule |
|---|---|
| `claims` | 1–64 material claims, each `{"quote": ..., "support": ..., "anchors": [...], "material_error": ..., "rationale": ...}`. `quote` is an exact, distinct substring of the answer. `support` is `supported`, `unsupported`, `contradicted` or `unknown`. `anchors` lists `source/` evidence as `path:line` or `path:first-last`, with paths relative to `source/`; it is required for supported and contradicted claims and may be empty otherwise. `material_error` is true only for an unsupported or contradicted claim that would mislead the requester |
| `claims[].source_quotes` | For each cited anchor, add `{"anchor": ..., "source_sha256": ..., "quote": ...}`. Copy the file's actual SHA-256 from `packet.json` `source_files` and a literal source excerpt within that anchor's inclusive line range. Use distinct anchors already listed in that claim. Preserve whitespace, newlines and Unicode punctuation. Use an empty list when there are no anchors |
| `knowns` | One row per required known: `covered`, `partial` or `missing`. Quote the answer excerpt unless it is missing |
| `unknowns` | One row per expected unknown: `appropriate`, `overclaimed` or `omitted`. Quote the answer excerpt unless it is omitted |
| `acceptance` | One row per criterion: `met` or `unmet`, judged against its `request_excerpt`. Quote the answer when met. Use `unknown` only when the answer is empty or visibly truncated |
| `outcome` | `unsatisfied` if any criterion is unmet, any claim is a material error or any unknown is overclaimed; otherwise `unknown` if a criterion is unknown; otherwise `satisfied`. Give a one-sentence rationale |

Read the source before deciding support; the key lists required facts, not every
acceptable wording. A citation that points at unrelated lines does not support a
claim. Copy every `quote` and `answer_excerpt` character for character from the
answer file, including typographic punctuation. Keep rationales short and specific.
Source quotes are evidence declarations, not answer excerpts. Do not paraphrase
them, guess a digest or invent a quote when the source cannot be read. Leave an
unavailable source quote absent and explain the limitation in the claim's
rationale. The binding audit checks literal identity separately; its result does
not decide claim support, acceptance or task outcome.

Reply with only a JSON object of the form `{"reviews": [...]}` that keeps every
`review_id`, `answer_sha256` and `rubric_sha256` from the template. Use exactly the
keys shown in the template and above, each once per object, and no other keys.
