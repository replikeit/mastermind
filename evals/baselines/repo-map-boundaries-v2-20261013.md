# Bundle boundary checks: development repeat

Purpose: test a general navigation instruction against the two observed bundle defects while preserving measured savings. Eight existing development tasks, two fresh repetitions, matched baseline and candidate. The second order reverses the first; each arm has mean position 0.5 per task and 8 slots at each position across the campaign.

The 1600-byte shortlist is unchanged on all 8 tasks. Advice changes 171→236 UTF-8 bytes. Producer GPT-6.1 Sol/high; randomized condition-hidden fresh Astra/high reviews. Sources, indexes, native tools and limits remain matched.

| Variant | Astra satisfied | Unsatisfied | Unknown/unresolved | Uncached input vs baseline | Total tokens vs baseline | Tools vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 14/16 | 2 | 0 | reference | reference | reference |
| bundle v2 | 10/16 | 2 | 4 | -7.1% | +7.4% | +1.3% |

| Targeted source check | Repetition 0 | Repetition 1 |
| --- | --- | --- |
| Correct fixture boundary | passed | passed |
| Missing definition vs empty field | failed | failed |

These source checks inspect only the original defects and are separate from full-answer Astra assessments. The old documentation baseline omitted the same numeric-variable definition distinction but its assessor accepted it; that old paired grade therefore does not establish clean causal superiority.

Fresh producer attempts: 32; blind review attempts: 32; unique fresh sessions: 64. Paired satisfied→unsatisfied losses: 2. All failed/unknown attempts remain in denominators.

| Registered descriptive gate | Result |
| --- | --- |
| all candidate reviews resolved | not passed |
| model acceptance not lower | not passed |
| no paired unsatisfied loss | not passed |
| targeted source checks passed | not passed |
| tools not increased | not passed |
| total savings preserved | not passed |
| uncached savings preserved | not passed |

The first 243-byte instruction retained a targeted documentation omission and was rejected before optional blind grading. Its 32 producer attempts are retained separately: 14,802,157 reported tokens and 1192 tool calls. Those answers have no whole-answer acceptance labels and are not pooled with this comparison. Judge spend is separate in JSON.

This is development evidence on one repository. Repeats remain 8 independent tasks. Human reference and exact-profile Astra seeded calibration are incomplete. Historical savings are descriptive targets only; there is no fresh old-bundle arm to isolate instruction efficacy from model variability. Actual served model, billing and model rounds remain unknown. No production benefit is qualified.

The candidate was not promoted: the original 171-byte instruction was restored and checked byte-for-byte on all eight tasks. The evaluated 236-byte candidate remains sealed separately.

[JSON report](repo-map-boundaries-v2-20261013.json) binds all slots, the detailed immutable report, targeted source quotes, and rejected tuning spend.

## Reproduce and recover

Requires the retained campaign, frozen CLI/native generators, source projections/indexes and Codex subscription. Inspect input-seal.json, analysis-plan.json, payloads.json and readiness-seal.json first. Finished attempts are immutable; commands resume only untouched slots. Never erase a partial trace or rerun an unfavorable/invalid assessment.

```sh
python3 -B .mastermind/research/repo-map-boundaries-v2-20261013/verify_inputs.py
python3 -B .mastermind/research/repo-map-boundaries-v2-20261013/run.py --run
python3 -B .mastermind/research/repo-map-boundaries-v2-20261013/review.py --run
```

Retained inputs/results: `.mastermind/research/repo-map-boundaries-v2-20261013/`. Rejected first iteration: `.mastermind/research/repo-map-boundaries-20261013/`. For interrupted partial attempts, preserve files and prepare an audited recovery revision; never overwrite seals or raw outputs.
