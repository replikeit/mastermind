# Resource screening power: exact-rule planning

Eight independent tasks with eight repetitions per arm have **68.6% simulated
power**, not 80%, to detect a nonzero resource change when the true token ratio
is 0.90 under the central Normal assumptions. This calculation adds no model
results and establishes neither acceptance non-inferiority nor product benefit.

## Inputs and method

| Input | Binding |
|---|---|
| Original planning assumptions | [Statistical reanalysis](statistical-reanalysis-20261015.md), SHA-256 `8f46bbfd…5d20888`; original report unchanged |
| Simulator | [`resource_power.py`](../benchmark/resource_power.py), SHA-256 `0df02ff5…a39ee0e` |
| Current full result | [resource-power-20261015-v2.json](resource-power-20261015-v2.json), SHA-256 `4ad501d7…cd9d15c` |
| Initial eight-task grid | [resource-power-20261015.json](resource-power-20261015.json), SHA-256 `180fb82a…616a7bd`; preserved before adding larger-task alternatives |

V2 replaces full sign enumeration with exact counting of the sums of two task
halves. Its eight-task rejection counts equal the initial grid in every row;
it also evaluates 12 and 16 tasks. Exhaustive tests compare its counts with
direct enumeration, including ties and a 16-task case.

Each row contains 20,000 simulated campaigns, seed `20261015`, Python 3.13.16.
The unit is an independent task. Its mean paired log ratio is sampled directly
from a Normal distribution with mean `log(0.90)` and variance
`task_sd² + 0.25² / repetitions`. The 0.25 is the SD of the paired per-run log
ratio, rather than either arm's tokens in isolation. This is equivalent to
averaging independent Normal run errors with a Normal task effect. Task SDs
0.03, 0.05 and 0.08 are sensitivity assumptions from a small development sample.

The implemented rule is the exact two-sided task sign-flip test of a zero mean
log ratio, rejecting at `p <= 0.05`, including ties with tolerance `1e-12`.
The eight-task test has 256 assignments; the alternatives have 4,096 and 65,536.
The seed restarts for each row so the eight-task sensitivity grid shares Normal
draws. A simulated zero-effect check rejects 926/20,000 campaigns: **4.63%**
(95% Monte Carlo Wilson interval 4.35–4.93%). This agrees with the eight-task
test's attainable null rate of 12/256 = 4.6875% under continuous symmetric errors.

## Eight-task repetition sensitivity

Power below means rejection of zero at an assumed true reduction of 10%.
It does not mean proving a reduction of at least 10%.

| Task SD | Repetitions per arm | Simulated power [95% Monte Carlo interval] | Two-arm producer attempts | Four-arm producer attempts |
|---|---:|---|---:|---:|
| 0.03 | 8 | 75.44% [74.84, 76.03] | 128 | 256 |
| 0.03 | 10 | 83.36% [82.84, 83.87] | 160 | 320 |
| 0.05 | 8 | **68.60% [67.95, 69.23]** | 128 | 256 |
| 0.05 | 12 | 80.38% [79.82, 80.92] | 192 | 384 |
| 0.05 | 14 | 84.35% [83.83, 84.84] | 224 | 448 |
| 0.08 | 8 | 55.12% [54.42, 55.80] | 128 | 256 |
| 0.08 | 48 | 80.42% [79.86, 80.96] | 768 | 1,536 |
| 0.08 | 50 | 80.77% [80.21, 81.31] | 800 | 1,600 |

The full result covers every even repetition count from 8 through 64. Selecting
the first tested count whose marginal Monte Carlo lower bound reaches 80% gives
**10, 14 and 50 repetitions** for task SDs 0.03, 0.05 and 0.08 respectively.
These are planning choices on this grid. Their intervals exclude nuisance
uncertainty and do not provide simultaneous coverage after selecting a design.

## Alternatives with more independent tasks

| Tasks | Repetitions per arm | Task SD | Simulated power [95% Monte Carlo interval] | Two-arm producer attempts | Four-arm producer attempts |
|---:|---:|---|---|---:|---:|
| 12 | 8 | 0.05 | 90.30% [89.88, 90.70] | 192 | 384 |
| 12 | 8 | 0.08 | 79.42% [78.86, 79.98] | 192 | 384 |
| 16 | 8 | 0.05 | 97.15% [96.90, 97.37] | 256 | 512 |
| 16 | 8 | 0.08 | 90.85% [90.44, 91.24] | 256 | 512 |

Additional independent tasks can be more useful than dozens of repetitions,
especially when the task effect SD is nearer 0.08. Task authoring costs and
availability are not measured here. The existing eight development questions
cannot become independent new tasks by renaming or repeating them.

## Plan the contrast before spending model calls

The primary resource contrast is **lexical map on versus map off at low effort**.
At the central assumptions, eight tasks × 14 repetitions requires 224 planned
producer attempts. It is a development screen; the effect variance for this
specific low-effort contrast has not yet been measured.

Keeping 14 repetitions in all four effort × map cells costs **448 producer
attempts**. Four repetitions in each cell cost 128, but this calculation does
not establish that design's power. Interaction power remains unknown until its
target effect and variance are planned. Neither pooling the main effect across
effort levels nor the interaction can inherit the primary contrast's power.

The current campaign runner caps a campaign at 240 attempts. Designs above that
limit need an explicit execution plan before preparation. Costs in the tables
exclude reviewers, retries, failed-attempt usage and task authoring. Position
balance must be fixed in the campaign plan; order effects are not simulated.

Acceptance, material errors, incomplete reviews, transport failures and missing
usage are outside this simulator. Keep those denominators and gates in the
campaign record. Eight tasks from one repository remain development data, and
Normal sampling assumptions need pilot checks before any registered qualification.

## Reproduce

Prerequisite: Python standard library, run from the repository root. The command
makes no model calls and writes a new record; choose a new output path to rerun.

```sh
python3 -m evals.benchmark.resource_power \
  --output /private/tmp/resource-power-reproduction.json \
  --simulations 20000 --seed 20261015
python3 -m unittest tests.evals.benchmark.test_resource_power
```

Existing outputs are never overwritten. On an output-path error, preserve the
existing file and choose a fresh canonical directory and filename. Full hashes,
per-row rejection counts, standard errors and marginal Wilson intervals are
retained in the JSON. The original statistical reanalysis and its local script
and output remain unchanged.
