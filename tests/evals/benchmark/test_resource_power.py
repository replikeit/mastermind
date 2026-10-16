"""Resource planning uses the exact task-level test and retains uncertainty."""

from contextlib import redirect_stderr, redirect_stdout
import io
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest

from evals.benchmark import resource_power


class ResourcePowerTests(unittest.TestCase):
    def test_sign_flip_matches_exhaustive_reference_including_ties(self):
        for values in ([1, -2, 3, 4], [1] * 8, [0] * 8, list(range(-6, 7)) + [20, 30, 40]):
            with self.subTest(values=values):
                observed = abs(sum(values))
                signed = [abs(sum(sign * value for sign, value in zip(signs, values)))
                          for signs in itertools.product((-1, 1), repeat=len(values))]
                expected = sum(value >= observed for value in signed) / len(signed)
                self.assertEqual(resource_power.sign_flip_pvalue(values), expected)
        self.assertEqual(resource_power.sign_flip_pvalue([1] * 8), 2 / 256)

    def test_null_rejection_rate_obeys_the_discrete_alpha(self):
        magnitudes = [2 ** index for index in range(8)]
        rejected = sum(resource_power.sign_flip_pvalue([sign * value for sign, value in zip(signs, magnitudes)])
                       <= 0.05 for signs in itertools.product((-1, 1), repeat=8))
        self.assertEqual(rejected, 12)

    def test_simulation_distinguishes_known_effect_from_null_and_retains_mc_interval(self):
        common = dict(tasks=8, repetitions=8, run_sd=0.0, task_sd=0.0,
                      alpha=0.05, simulations=40, seed=17)
        effect = resource_power.simulate_power(token_ratio=0.9, **common)
        null = resource_power.simulate_power(token_ratio=1.0, **common)
        self.assertEqual((effect["rejections"], null["rejections"]), (40, 0))
        self.assertLess(effect["monte_carlo_wilson95"][0], 1.0)
        self.assertGreater(null["monte_carlo_wilson95"][1], 0.0)
        self.assertEqual(effect["producer_attempts_two_arms"], 128)
        self.assertEqual(effect["producer_attempts_four_arms"], 256)
        noisy = dict(common, run_sd=0.25, task_sd=0.05)
        self.assertEqual(resource_power.simulate_power(token_ratio=0.9, **noisy),
                         resource_power.simulate_power(token_ratio=0.9, **noisy))

    def test_invalid_design_is_rejected(self):
        valid = dict(tasks=8, repetitions=8, token_ratio=0.9, run_sd=0.25, task_sd=0.05,
                     alpha=0.05, simulations=1, seed=17)
        for change in ({"tasks": True}, {"tasks": 17}, {"repetitions": 0}, {"simulations": 0},
                       {"token_ratio": math.nan}, {"run_sd": -0.1}, {"task_sd": math.inf},
                       {"alpha": 1.0}, {"seed": False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                resource_power.simulate_power(**dict(valid, **change))

    def test_cli_writes_a_reproducible_new_record_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "power.json"
            arguments = ["--output", str(output), "--simulations", "2", "--seed", "17"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(resource_power.main(arguments), 0)
            before = output.read_bytes()
            report = json.loads(before)
            self.assertFalse(report["qualification_eligible"])
            self.assertEqual(report["simulation"]["seed"], 17)
            self.assertEqual(len(report["power"]), 87)
            self.assertTrue(all(row["simulations"] == 2 for row in report["power"]))
            self.assertEqual(report, resource_power.plan(simulations=2, seed=17))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(resource_power.main(arguments), 2)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
