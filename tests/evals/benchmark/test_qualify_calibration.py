"""Calibration controls the implemented rule's false-pass rate and reports its power."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import math
from pathlib import Path
import random
import shutil
import tempfile
import unittest

from evals.benchmark import artifacts, qualify, qualify_calibration as calibration


def settings(**change):
    value = {"kind": "mastermind-qualification-calibration-input", "schema_version": 1, "claim": "R",
             "repositories": 6, "tasks_per_repository": 2, "repetitions": 4, "baseline_acceptance": 0.85,
             "difficulty_sd": 1.0, "repository_interaction_sd": 0.3, "task_interaction_sd": 0.5,
             "token_task_sd": 0.2, "token_attempt_sd": 0.2, "margin": 0.10, "alpha": 0.05,
             "concentrated_fraction": 0.125, "material_error_rate": 0.02, "veto_false_rate": 0.05,
             "interim_repositories": None,
             "scenarios": [{"name": "null", "acceptance_delta": -0.10, "token_ratio": 0.7},
                           {"name": "strong", "acceptance_delta": 0.0, "token_ratio": 0.7}],
             "simulations": 400, "seed": 7}
    value.update(change)
    return value


def rule_size(value, t_star, seed, count=600, **options):
    """False-pass rate of qualify's step 1 on independent campaigns at the given critical value."""
    population = calibration.Population(value)
    rng = random.Random(seed)
    passed = 0
    for _ in range(count):
        cases, clusters = calibration.simulate(value, population, rng, **options)
        prereg = calibration.registration(value, clusters, t_star, 1.0, 10 ** 6)
        passed += qualify.scenario(cases, prereg, "worst", {"status": "unknown"}, None)["steps"][0]
    return passed / count, math.sqrt(0.05 * 0.95 / count)


class CalibrationTests(unittest.TestCase):
    def test_student_t_quantiles_match_reference_tables(self):
        for probability, freedom, expected in ((0.95, 19, 1.729), (0.95, 3, 2.353), (0.975, 10, 2.228),
                                               (0.975, 1, 12.706)):
            with self.subTest(freedom=freedom):
                self.assertAlmostEqual(calibration.student_t_quantile(probability, freedom), expected, places=3)

    def test_population_reproduces_the_requested_acceptance_changes(self):
        value = settings()
        population = calibration.Population(value)
        rng = random.Random(123)
        draws = [(rng.gauss(0, 1.0), rng.gauss(0, 0.3) + rng.gauss(0, 0.5)) for _ in range(200000)]
        base = sum(calibration.sigmoid(population.intercept + difficulty) for difficulty, _ in draws) / len(draws)
        self.assertAlmostEqual(base, 0.85, delta=0.003)
        for delta in (-0.10, 0.0, 0.05):
            with self.subTest(delta=delta):
                shift = population.shift_for(delta)
                moved = sum(calibration.sigmoid(population.intercept + difficulty + shift + noise)
                            for difficulty, noise in draws) / len(draws)
                self.assertAlmostEqual(moved - base, delta, delta=0.003)
        loss = population.concentrated_loss(0.125, 0.10)
        average = 0.125 * sum(min(calibration.sigmoid(population.intercept + difficulty), loss)
                              for difficulty, _ in draws) / len(draws)
        self.assertAlmostEqual(average, 0.10, delta=0.003)
        with self.assertRaises(artifacts.BenchmarkError) as raised:
            population.concentrated_loss(0.05, 0.10)
        self.assertEqual(raised.exception.code, "calibration_input")

    def test_critical_value_uses_the_rules_arithmetic_and_breaks_ties_upwards(self):
        tie = (0.15, 0.13017082793177756)
        statistics = [tie] * 20 + [(-0.2, 0.1)] * 380
        critical = calibration.critical_value(statistics, -0.10, 0.05)
        allowed = 400 - math.ceil(0.95 * 401)
        self.assertLessEqual(sum(calibration.passes(item, critical, -0.10) for item in statistics), allowed)
        lower = math.nextafter(critical, -math.inf)
        self.assertGreater(sum(calibration.passes(item, lower, -0.10) for item in statistics), allowed)
        with self.assertRaises(artifacts.BenchmarkError) as raised:
            calibration.critical_value([(0.0, 0.0)] * 30 + [(-0.2, 0.1)] * 370, -0.10, 0.05)
        self.assertEqual(raised.exception.code, "calibration_design")

    def test_calibrated_value_holds_size_on_fresh_campaigns_for_each_null(self):
        value = settings()
        result = calibration.calibrate(value)
        self.assertEqual(result, calibration.calibrate(settings()))
        self.assertEqual(set(result["nulls"]), {"logit", "concentrated"})
        self.assertEqual(result["t_star"], max(row["critical"] for row in result["nulls"].values()))
        self.assertAlmostEqual(result["t_upper"], calibration.student_t_quantile(0.95, 5))
        for name, row in result["nulls"].items():
            with self.subTest(null=name):
                self.assertEqual(row["fresh_size"]["check"], "consistent")
        population = calibration.Population(value)
        self.assertEqual(result["nulls"]["concentrated"]["loss"], population.concentrated_loss(0.125, 0.10))
        self.assertEqual(result["nulls"]["logit"]["shift"], population.shift_for(-0.10))
        for options in ({"shift": population.shift_for(-0.10)}, {"loss": population.concentrated_loss(0.125, 0.10)}):
            with self.subTest(options=options):
                fraction, error = rule_size(value, result["t_star"], 99, **options)
                self.assertLessEqual(fraction, 0.05 + 3 * error)

    def test_logit_null_binds_when_repository_interactions_dominate(self):
        value = settings(repositories=8, repository_interaction_sd=1.0, concentrated_fraction=0.4)
        result = calibration.calibrate(value)
        self.assertGreater(result["nulls"]["logit"]["critical"], result["nulls"]["concentrated"]["critical"])
        population = calibration.Population(value)
        fraction, error = rule_size(value, result["t_star"], 101, shift=population.shift_for(-0.10))
        self.assertLessEqual(fraction, 0.05 + 3 * error)

    def test_quality_claim_calibrates_against_its_own_step_one_bound(self):
        value = settings(claim="Q")
        result = calibration.calibrate(value)
        self.assertEqual((result["step1_bound"], set(result["nulls"])), (0.0, {"logit"}))
        population = calibration.Population(value)
        rng = random.Random(5)
        for claim, bound in (("R", -0.10), ("Q", 0.0)):
            for _ in range(60):
                cases, clusters = calibration.simulate(value, population, rng)
                for critical in (0.5, 1.0, 2.0):
                    prereg = calibration.registration(dict(value, claim=claim), clusters, critical, 1.0, 10 ** 6)
                    statistic = calibration.acceptance_statistics(cases, prereg)
                    rule = qualify.scenario(cases, prereg, "worst", {"status": "unknown"}, None)["steps"][0]
                    self.assertEqual(calibration.passes(statistic, critical, bound), rule)
        fraction, error = rule_size(value, result["t_star"], 77, shift=0.0)
        self.assertLessEqual(fraction, 0.05 + 3 * error)

    def test_power_separates_a_null_candidate_from_a_strong_one(self):
        quiet = settings(repositories=10, repetitions=6, baseline_acceptance=0.95, difficulty_sd=0.5,
                         repository_interaction_sd=0.1, task_interaction_sd=0.1)
        power = {row["name"]: row["decisions"] for row in calibration.calibrate(quiet)["power"]}
        self.assertLessEqual(power["null"].get("promote", {"fraction": 0})["fraction"], 0.08)
        self.assertGreater(power["strong"]["promote"]["fraction"], 0.6)

    def test_interim_futility_uses_the_first_repositories_and_changes_decisions(self):
        scenario = [{"name": "small loss", "acceptance_delta": -0.05, "token_ratio": 0.9}]
        final = calibration.calibrate(settings(scenarios=scenario))["power"][0]
        staged = calibration.calibrate(settings(scenarios=scenario, interim_repositories=3))["power"][0]
        later = calibration.calibrate(settings(scenarios=scenario, interim_repositories=5))["power"][0]
        self.assertEqual(final["interim_stops"], 0)
        self.assertGreater(staged["interim_stops"], 0.2)
        self.assertNotEqual(staged["interim_stops"], later["interim_stops"])
        self.assertNotEqual(final["decisions"], staged["decisions"])

    def test_veto_limit_is_exact(self):
        limit, tail = calibration.veto_limit(settings())
        self.assertEqual(limit, 2)
        self.assertAlmostEqual(tail, 0.0333, places=3)

    def test_cli_refuses_existing_output_and_unregistrable_designs_before_writing(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory)
        source, output = directory / "input.json", directory / "output.json"
        artifacts.write_new(source, settings())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(calibration.main(["--input", str(source), "--output", str(output)]), 0)
        self.assertEqual(json.loads(out.getvalue())["t_star"], artifacts.load_json(output)["t_star"])
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(calibration.main(["--input", str(source), "--output", str(output)]), 2)
        self.assertTrue(err.getvalue().startswith("calibration_output:"), err.getvalue())
        extreme = directory / "extreme.json"
        artifacts.write_new(extreme, settings(baseline_acceptance=0.99, margin=0.10))
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(calibration.main(["--input", str(extreme), "--output", str(directory / "never.json")]), 2)
        self.assertTrue(err.getvalue().startswith("calibration_design:"), err.getvalue())
        self.assertIn("zero between-repository error", err.getvalue())
        self.assertFalse((directory / "never.json").exists())

    def test_invalid_inputs_are_refused(self):
        directory = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, directory)
        for index, change in enumerate(({"repetitions": 3}, {"interim_repositories": 6}, {"alpha": 0.6},
                                        {"extra": 1}, {"simulations": 399}, {"margin": 0.9},
                                        {"scenarios": [{"name": "x", "acceptance_delta": 0.2, "token_ratio": 1}]},
                                        {"scenarios": [{"name": "x", "acceptance_delta": 0.0, "token_ratio": 1000}]})):
            with self.subTest(change=change):
                path = directory / f"bad-{index}.json"
                artifacts.write_new(path, settings(**change))
                with self.assertRaises(artifacts.BenchmarkError) as raised:
                    calibration.load_input(path)
                self.assertEqual(raised.exception.code, "calibration_input")


if __name__ == "__main__":
    unittest.main()
