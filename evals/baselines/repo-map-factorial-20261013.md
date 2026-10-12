# Repo-map factorial development run

Eight tasks, four arms, two fresh repetitions. Per-case second order reverses the first; each arm has meanposition1.5 per case and equal campaign-wide position counts. Header cap1600bytes. Same frozen sources, native tools, GPT-6.1 Sol/high and limits across arms.

| Arm | Satisfied | Unsatisfied | Unknown/unresolved | Uncached input vs baseline | Total tokens vs baseline | Tools vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 14/16 | 1 | 1 | reference | reference | reference |
| map-only | 12/16 | 1 | 3 | -5.1% | -9.4% | +1.2% |
| instructions-only | 13/16 | 2 | 1 | +1.2% | -2.0% | +4.1% |
| bundle | 14/16 | 2 | 0 | -10.1% | -8.5% | -2.1% |

Producer attempts: 64; failed attempts: 0. Astra review attempts: 64; source-anchor-valid assessments: 59. Unique model sessions: 128. All attempts and pending tool calls remain in the retained report.

Astra judgments are model proxy assessments. Real human reference is incomplete and exact-profile seeded calibration is unmeasured. This development study does not qualify a production improvement; repeats preserve8 independent tasks, not16.

Producer spend includes failures/retries and is separated from judge spend. Missing usage remains unknown. Per-case/repetition contrasts and resource interaction are in the JSON report. No historical study is pooled as extra independent evidence.

[JSON report](repo-map-factorial-20261013.json) binds the detailed immutable records retained under `.mastermind/research/repo-map-factorial-20261013/`.

## Reproduce and recover

Requires the sealed CLI/native/source/index bindings and Codex subscription. Inspect input-seal.json and readiness-seal.json before execution. Preserve every partial trace and result; a completed result is never resampled.

```sh
python3 -B .mastermind/research/repo-map-factorial-20261013/verify_inputs.py
python3 -B .mastermind/research/repo-map-factorial-20261013/run.py --run
python3 -B .mastermind/research/repo-map-factorial-20261013/review.py --run
```

Publication is immutable. Do not overwrite effective-results, review-results or final reports. For an interrupted partial attempt, retain it and prepare an audited recovery revision; do not erase it and rerun invisibly.
