"""Plan resource detection on eight development tasks using the exact sign-flip test.

This is a Normal-model sensitivity calculation, not a qualification decision.
The run standard deviation is for a paired log ratio, so averaging repetitions
gives variance task_sd**2 + run_sd**2 / repetitions without another factor of two.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import hashlib
import math
from pathlib import Path
import platform
import random
import sys

from . import artifacts as artifact_io


REPETITIONS = tuple(range(8, 65, 2))
TASK_SDS = (0.03, 0.05, 0.08)
SOURCE = Path(__file__).resolve().parents[1] / "baselines/statistical-reanalysis-20261015.md"


def _signed_sums(values: list[float]) -> list[float]:
    sums = [0.0]
    for value in values:
        sums = [total + value for total in sums] + [total - value for total in sums]
    return sums


def sign_flip_pvalue(values: list[float]) -> float:
    """Count every task sign assignment exactly, including ties, with two half enumerations."""
    if not 2 <= len(values) <= 16 or not all(math.isfinite(value) for value in values):
        raise ValueError("the exact test requires 2–16 finite task log ratios")
    threshold = abs(sum(values)) - 1e-12
    if threshold <= 0:
        return 1.0
    split = len(values) // 2
    left = _signed_sums(values[:split])
    right = sorted(_signed_sums(values[split:]))
    extreme = sum(bisect_right(right, -threshold - total)
                  + len(right) - bisect_left(right, threshold - total) for total in left)
    return extreme / (len(left) * len(right))


def _fraction(rejections: int, simulations: int) -> dict:
    fraction = rejections / simulations
    z = 1.959963984540054
    denominator = 1 + z * z / simulations
    center = (fraction + z * z / (2 * simulations)) / denominator
    half = z * math.sqrt(fraction * (1 - fraction) / simulations
                         + z * z / (4 * simulations * simulations)) / denominator
    return {"rejections": rejections, "simulations": simulations, "fraction": fraction,
            "monte_carlo_standard_error": math.sqrt(fraction * (1 - fraction) / simulations),
            "monte_carlo_wilson95": [max(0.0, center - half), min(1.0, center + half)]}


def simulate_power(*, tasks: int, repetitions: int, token_ratio: float, run_sd: float,
                   task_sd: float, alpha: float, simulations: int, seed: int) -> dict:
    """Simulate independent Normal task means and apply the exact test to each campaign."""
    integer = lambda value, low, high: type(value) is int and low <= value <= high
    finite = lambda value: type(value) in (int, float) and math.isfinite(value)
    if (not integer(tasks, 2, 16) or not integer(repetitions, 1, 10000)
            or not integer(simulations, 1, 100000) or type(seed) is not int
            or not finite(token_ratio) or not 0.01 <= token_ratio <= 100
            or not finite(alpha) or not 0 < alpha < 0.5
            or not all(finite(sd) and 0 <= sd <= 5 for sd in (run_sd, task_sd))):
        raise ValueError("invalid resource-power design")
    rng = random.Random(seed)
    mean = math.log(token_ratio)
    sd = math.sqrt(task_sd * task_sd + run_sd * run_sd / repetitions)
    rejections = 0
    for _ in range(simulations):
        task_means = [rng.gauss(mean, sd) for _ in range(tasks)]
        rejections += sign_flip_pvalue(task_means) <= alpha
    return {"tasks": tasks, "task_sd": task_sd, "repetitions_per_arm": repetitions, "task_mean_sd": sd,
            "sign_assignments": 2 ** tasks,
            **_fraction(rejections, simulations),
            "producer_attempts_two_arms": 2 * tasks * repetitions,
            "producer_attempts_four_arms": 4 * tasks * repetitions}


def plan(*, simulations: int = 20000, seed: int = 20261015) -> dict:
    """Retain the fixed eight-task development design and its nuisance sensitivity."""
    settings = dict(tasks=8, token_ratio=0.9, run_sd=0.25, alpha=0.05,
                    simulations=simulations, seed=seed)
    rows = [simulate_power(repetitions=repetitions, task_sd=task_sd, **settings)
            for task_sd in TASK_SDS for repetitions in REPETITIONS]
    alternatives = [simulate_power(**dict(settings, tasks=tasks), repetitions=8, task_sd=task_sd)
                    for tasks in (12, 16) for task_sd in (0.05, 0.08)]
    selected = []
    for task_sd in TASK_SDS:
        eligible = [row for row in rows if row["task_sd"] == task_sd
                    and row["monte_carlo_wilson95"][0] >= 0.8]
        selected.append({"task_sd": task_sd, "selection": "first tested even repetition count with lower Wilson95 >= 0.80",
                         "repetitions_per_arm": eligible[0]["repetitions_per_arm"] if eligible else None})
    null = simulate_power(**dict(settings, token_ratio=1.0), repetitions=8, task_sd=0.05)
    inputs = []
    for path in (Path(__file__).resolve(), SOURCE):
        inputs.append({"path": str(path.relative_to(SOURCE.parents[2])),
                       "sha256": hashlib.sha256(artifact_io.read_file(path)).hexdigest()})
    return {"kind": "mastermind-resource-power-planning", "schema_version": 1,
            "qualification_eligible": False, "product_benefit_qualified": False,
            "inputs": inputs, "python": platform.python_version(),
            "design": {"tasks": 8, "independent_unit": "task", "token_ratio": 0.9,
                       "mean_log_ratio": math.log(0.9), "run_log_ratio_sd": 0.25,
                       "task_log_ratio_sds": list(TASK_SDS), "repetitions_per_arm": list(REPETITIONS),
                       "task_mean_distribution": "Normal(log(token_ratio), task_sd**2 + run_sd**2 / repetitions)",
                       "primary_contrast": "low effort: lexical map on versus map off",
                       "four_arm_matrix": "{low, high} effort x {lexical map on, map off}",
                       "interaction_power": None},
            "test": {"method": "exact two-sided task sign-flip of the mean log ratio", "alpha": 0.05,
                     "sign_assignments": 256, "tie_tolerance": 1e-12,
                     "rejection_rule": "p <= alpha", "target_power": 0.8},
            "simulation": {"campaigns_per_row": simulations, "seed": seed,
                           "random_generator": "random.Random.gauss",
                           "streams": "restart the same seed for every row; common Normal draws couple scenarios",
                           "interval": "marginal Wilson 95% Monte Carlo interval; excludes nuisance uncertainty"},
            "null_size": null, "power": rows, "larger_task_alternatives": alternatives,
            "selected_repetitions": selected,
            "limitations": [
                "No model was invoked and no retained outcome was changed; this adds planning calculations only.",
                "Normal independent task effects and independent run errors are assumptions, not verified population measurements.",
                "Eight tasks on one repository remain development data; repetitions do not establish generalization.",
                "Run SD is the SD of the paired log ratio, not the SD of each arm separately.",
                "The rule detects a difference from zero; 80% power at a true 10% reduction does not prove a reduction of at least 10%.",
                "Monte Carlo intervals are marginal per row, not simultaneous guarantees for a grid-selected design.",
                "The four-arm costs assume the same repetitions in all cells; only the low-effort map contrast is planned.",
                "Interaction power is unknown until its within-task contrast variance and target effect are specified.",
                "Acceptance, material errors, transport failures, missing usage, position effects and qualification gates are not simulated."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new immutable planning record")
    parser.add_argument("--simulations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args(argv)
    try:
        output = args.output.absolute()
        if output.exists() or output.parent.resolve(strict=True) != output.parent:
            raise artifact_io.BenchmarkError("resource_power_output", "output must be new in a canonical directory")
        result = plan(simulations=args.simulations, seed=args.seed)
        artifact_io.write_new(output, result)
        print(artifact_io.canonical({"output": str(output), "selected_repetitions": result["selected_repetitions"]}).decode())
        return 0
    except (artifact_io.BenchmarkError, OSError, ValueError) as error:
        print(f"{getattr(error, 'code', 'resource_power_input')}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
