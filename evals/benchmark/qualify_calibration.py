"""Calibrate the registered qualification rule by simulation before a campaign.

Synthetic campaigns go through qualify's own arithmetic and decision function,
so the reported size and power belong to the implemented rule. Outcomes are
resolved; reviewer error, unknown usage, latency and the audit detector are not
modelled. The margin on the true scale is margin/J for a judge with Youden J.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import math
import random
import sys

from . import artifacts as artifact_io
from . import qualify


FIELDS = {"kind", "schema_version", "claim", "repositories", "tasks_per_repository", "repetitions",
          "baseline_acceptance", "difficulty_sd", "repository_interaction_sd", "task_interaction_sd",
          "token_task_sd", "token_attempt_sd", "margin", "alpha", "concentrated_fraction", "material_error_rate",
          "veto_false_rate", "interim_repositories", "scenarios", "simulations", "seed"}
SCENARIO_FIELDS = {"name", "acceptance_delta", "token_ratio"}
DRAWS = 20000


def input_error(message):
    return artifact_io.BenchmarkError("calibration_input", message)


def sigmoid(value):
    return 1 / (1 + math.exp(-value))


def student_t_cdf(value: float, freedom: int) -> float:
    """Simpson integration of the Student t density from zero."""
    if value < 0:
        return 1 - student_t_cdf(-value, freedom)
    scale = math.exp(math.lgamma((freedom + 1) / 2) - math.lgamma(freedom / 2)) / math.sqrt(freedom * math.pi)
    density = lambda x: scale * (1 + x * x / freedom) ** (-(freedom + 1) / 2)
    steps = 4000
    width = value / steps
    total = density(0) + density(value) + sum((4 if index % 2 else 2) * density(index * width)
                                              for index in range(1, steps))
    return 0.5 + total * width / 3


def student_t_quantile(probability: float, freedom: int) -> float:
    low, high = 0.0, 1000.0
    for _ in range(100):
        middle = (low + high) / 2
        low, high = (middle, high) if student_t_cdf(middle, freedom) < probability else (low, middle)
    return high


def load_input(path: Path) -> dict:
    value = artifact_io.load_json(path)
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise input_error("unexpected calibration fields")
    number = lambda name, low, high: type(value[name]) in (int, float) and low < value[name] < high
    sd = lambda name: type(value[name]) in (int, float) and 0 <= value[name] <= 5
    integer = lambda name, low, high: type(value[name]) is int and low <= value[name] <= high
    if (value["kind"] != "mastermind-qualification-calibration-input" or value["schema_version"] != 1
            or value["claim"] not in qualify.CLAIMS
            or not integer("repositories", 2, 200) or not integer("tasks_per_repository", 1, 20)
            or not integer("repetitions", 2, 20) or value["repetitions"] % 2
            or not number("baseline_acceptance", 0, 1)
            or not number("alpha", 0, 0.5) or not number("veto_false_rate", 0, 0.5)
            or not number("material_error_rate", 0, 1) or not number("concentrated_fraction", 0, 1)
            or not all(sd(name) for name in ("difficulty_sd", "repository_interaction_sd", "task_interaction_sd",
                                             "token_task_sd", "token_attempt_sd"))
            or value["interim_repositories"] is not None
            and not integer("interim_repositories", 2, value["repositories"] - 1)
            or type(value["seed"]) is not int):
        raise input_error("invalid calibration values")
    if not number("margin", 0, value["baseline_acceptance"]):
        raise input_error("margin must be below baseline acceptance")
    if not integer("simulations", math.ceil(20 / value["alpha"]), 100000):
        raise input_error("simulations must be at least 20/alpha")
    scenarios = value["scenarios"]
    if (not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 32
            or not all(isinstance(row, dict) and set(row) == SCENARIO_FIELDS and isinstance(row["name"], str)
                       and type(row["acceptance_delta"]) in (int, float)
                       and -value["baseline_acceptance"] < row["acceptance_delta"] < 1 - value["baseline_acceptance"]
                       and type(row["token_ratio"]) in (int, float) and 0.01 <= row["token_ratio"] <= 100
                       for row in scenarios)):
        raise input_error("invalid scenarios")
    return value


class Population:
    """Fixed draws that translate acceptance targets into simulation parameters."""

    def __init__(self, settings: dict):
        self.settings = settings
        rng = random.Random(settings["seed"] ^ 0x5EED)
        self.difficulty = [rng.gauss(0, settings["difficulty_sd"]) for _ in range(DRAWS)]
        self.noise = [rng.gauss(0, settings["repository_interaction_sd"]) + rng.gauss(0, settings["task_interaction_sd"])
                      for _ in range(DRAWS)]
        self.intercept = self.bisect(lambda value: self.mean(value) - settings["baseline_acceptance"], -12, 12)
        self.base = self.mean(self.intercept)

    def mean(self, intercept, shift=None):
        if shift is None:
            return sum(sigmoid(intercept + draw) for draw in self.difficulty) / DRAWS
        return sum(sigmoid(intercept + draw + shift + noise) for draw, noise in zip(self.difficulty, self.noise)) / DRAWS

    @staticmethod
    def bisect(function, low, high):
        if function(low) > 0 or function(high) < 0:
            raise input_error("an acceptance target is not reachable for this population")
        for _ in range(60):
            middle = (low + high) / 2
            low, high = (middle, high) if function(middle) < 0 else (low, middle)
        return (low + high) / 2

    def shift_for(self, delta: float) -> float:
        """Logit shift whose population-average acceptance change equals delta."""
        return self.bisect(lambda shift: self.mean(self.intercept, shift) - self.base - delta, -12, 12)

    def concentrated_loss(self, fraction: float, margin: float) -> float:
        """Loss per affected task such that the population-average change is exactly -margin."""
        rates = [sigmoid(self.intercept + draw) for draw in self.difficulty]
        average = lambda loss: fraction * sum(min(rate, loss) for rate in rates) / DRAWS
        return self.bisect(lambda loss: average(loss) - margin, 0.0, 1.0)


def simulate(settings: dict, population: Population, rng: random.Random, *, shift: float = 0.0,
             token_ratio: float = 1.0, loss: float | None = None) -> tuple[list[dict], dict]:
    cases, clusters = [], {}
    repetitions = settings["repetitions"]
    for repository in range(settings["repositories"]):
        repository_effect = rng.gauss(0, settings["repository_interaction_sd"])
        for task in range(settings["tasks_per_repository"]):
            name = f"r{repository}-t{task}"
            clusters[name] = f"r{repository}"
            logit = population.intercept + rng.gauss(0, settings["difficulty_sd"])
            baseline = sigmoid(logit)
            if loss is not None:
                affected = rng.random() < settings["concentrated_fraction"]
                candidate = max(0.0, baseline - loss) if affected else baseline
            else:
                candidate = sigmoid(logit + shift + repository_effect + rng.gauss(0, settings["task_interaction_sd"]))
            ratio = math.log(token_ratio) + rng.gauss(0, settings["token_task_sd"])
            pairs, tokens = [], {"baseline": [], "candidate": []}
            for index in range(repetitions):
                row = {}
                for arm, rate, offset in (("baseline", baseline, 0.0), ("candidate", candidate, ratio)):
                    success = int(rng.random() < rate)
                    row[arm] = {"success": {"lower": success, "upper": success}, "review_id": f"{name}-{arm}-{index}",
                                "material_error": rng.random() < settings["material_error_rate"]}
                    tokens[arm].append(math.exp(math.log(1000) + offset + rng.gauss(0, settings["token_attempt_sd"])))
                pairs.append(row)
            resources = {arm: {"total_tokens": {"observed_values": tokens[arm], "unknown_attempts": 0},
                               "trial_total_seconds": {"observed_values": [1.0] * repetitions, "unknown_attempts": 0}}
                         for arm in tokens}
            cases.append({"case": name, "pairs": pairs, "labels": {}, "judged": True, "tool_revision": "simulated",
                          "resources": resources})
    return cases, clusters


def registration(settings: dict, clusters: dict, t_star: float, t_upper: float, veto: int) -> dict:
    return {"kind": "mastermind-qualification-prereg", "schema_version": 1, "claim": settings["claim"],
            "baseline": "baseline", "candidate": "candidate", "reviewer": "judge",
            "repetitions": settings["repetitions"], "clusters": clusters, "margin": settings["margin"],
            "t_star": t_star, "t_upper": t_upper, "veto_material_errors": veto, "max_unknown_usage": 0,
            "max_infrastructure_failures": 0, "latency": False, "audit": None}


def step1_bound(settings: dict) -> float:
    bound = qualify.CLAIMS[settings["claim"]]["step1_bound"]
    return -settings["margin"] if bound is None else bound


def acceptance_statistics(cases: list[dict], prereg: dict) -> tuple[float, float]:
    estimate = qualify.scenario(cases, prereg, "worst", {"status": "unknown"}, None)["acceptance"]
    return estimate["point"], estimate["standard_error"]


def passes(statistic: tuple[float, float], critical: float, bound: float) -> bool:
    """The rule's own comparison, in qualify.cluster_estimate's operation order."""
    point, error = statistic
    return point - critical * error > bound


def critical_value(statistics: list[tuple[float, float]], bound: float, alpha: float) -> float:
    """Conformal critical value: a fresh null campaign passes with probability at most alpha."""
    count = len(statistics)
    rank = math.ceil((1 - alpha) * (count + 1))
    allowed = count - rank
    required = sorted((point - bound) / error if error > 0 else (math.inf if point > bound else -math.inf)
                      for point, error in statistics)
    critical = max(required[rank - 1], 1e-6)
    if not math.isfinite(critical):
        zero = sum(error == 0 for _, error in statistics) / count
        raise artifact_io.BenchmarkError("calibration_design", f"no finite critical value controls size; {zero:.1%} "
                                         "of null campaigns have zero between-repository error")
    while sum(passes(statistic, critical, bound) for statistic in statistics) > allowed:
        critical = math.nextafter(critical, math.inf)
    if critical > 100:
        raise artifact_io.BenchmarkError("calibration_design", "the critical value exceeds the registrable limit of 100")
    return critical


def binomial_pmf(trials: int, rate: float) -> dict[int, float]:
    spread = 12 * math.sqrt(trials * rate * (1 - rate)) + 12
    low, high = max(0, int(trials * rate - spread)), min(trials, int(trials * rate + spread) + 1)
    return {k: math.exp(math.lgamma(trials + 1) - math.lgamma(k + 1) - math.lgamma(trials - k + 1)
                        + k * math.log(rate) + (trials - k) * math.log1p(-rate)) for k in range(low, high + 1)}


def veto_limit(settings: dict) -> tuple[int, float]:
    """Smallest limit whose exact false-veto probability under equal material-error rates is within bound."""
    answers = settings["repositories"] * settings["tasks_per_repository"] * settings["repetitions"]
    pmf = binomial_pmf(answers, settings["material_error_rate"])
    difference = {}
    for candidate, left in pmf.items():
        for baseline, right in pmf.items():
            difference[candidate - baseline] = difference.get(candidate - baseline, 0.0) + left * right
    for limit in range(answers + 1):
        tail = sum(probability for value, probability in difference.items() if value > limit)
        if tail <= settings["veto_false_rate"]:
            return limit, tail
    return answers, 0.0


def calibrate(settings: dict) -> dict:
    population = Population(settings)
    bound = step1_bound(settings)
    t_upper = student_t_quantile(0.95, settings["repositories"] - 1)
    nulls = {"logit": {"shift": population.shift_for(bound)}}
    if settings["claim"] == "R":
        nulls["concentrated"] = {"loss": population.concentrated_loss(settings["concentrated_fraction"],
                                                                      settings["margin"])}
    report = {}
    for offset, (name, options) in enumerate(nulls.items()):
        batches = []
        for stream in (2 * offset + 1, 2 * offset + 2):
            rng = random.Random(settings["seed"] * 1000 + stream)
            batch = []
            for _ in range(settings["simulations"]):
                cases, clusters = simulate(settings, population, rng, **options)
                batch.append(acceptance_statistics(cases, registration(settings, clusters, 1.0, 1.0, 0)))
            batches.append(batch)
        report[name] = {**options, "critical": critical_value(batches[0], bound, settings["alpha"]),
                        "fresh": batches[1]}
    t_star = max(row["critical"] for row in report.values())
    nulls_out = {}
    for name, row in report.items():
        fraction = sum(passes(statistic, t_star, bound) for statistic in row.pop("fresh")) / settings["simulations"]
        error = math.sqrt(fraction * (1 - fraction) / settings["simulations"])
        check = "exceeds_alpha" if fraction - 2 * error > settings["alpha"] else "consistent"
        nulls_out[name] = {**row, "fresh_size": {"fraction": fraction, "standard_error": error, "check": check}}
    veto, false_veto = veto_limit(settings)
    rng = random.Random(settings["seed"] * 1000 + 99)
    power = []
    for scenario in settings["scenarios"]:
        shift = population.shift_for(scenario["acceptance_delta"])
        counts, stops = {}, 0
        for _ in range(settings["simulations"]):
            cases, clusters = simulate(settings, population, rng, shift=shift, token_ratio=scenario["token_ratio"])
            prereg = registration(settings, clusters, t_star, t_upper, veto)
            decision = None
            if settings["interim_repositories"] is not None:
                early = {f"r{index}" for index in range(settings["interim_repositories"])}
                interim = qualify.decide([case for case in cases if clusters[case["case"]] in early], prereg,
                                         interim=True)["decision"]
                decision = None if interim == "continue" else interim
                stops += decision is not None
            decision = decision or qualify.decide(cases, prereg)["decision"]
            counts[decision] = counts.get(decision, 0) + 1
        total = settings["simulations"]
        power.append({"name": scenario["name"], "acceptance_delta": scenario["acceptance_delta"],
                      "token_ratio": scenario["token_ratio"], "interim_stops": stops / total,
                      "decisions": {name: {"fraction": count / total,
                                           "standard_error": math.sqrt(count / total * (1 - count / total) / total)}
                                    for name, count in sorted(counts.items())}})
    return {"kind": "mastermind-qualification-calibration", "schema_version": 1, "input": settings,
            "step1_bound": bound, "t_star": t_star, "t_upper": t_upper, "nulls": nulls_out,
            "veto_material_errors": veto, "false_veto_probability": false_veto, "power": power, "limitations": [
                "Outcomes are resolved; reviewer error, unknown usage and infrastructure failures are not simulated.",
                "Power assumes latency=false and no audit detector.",
                "Nuisance parameters are assumptions until a pilot measures them.",
                "Size and power fractions are Monte Carlo estimates with the reported standard errors."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new calibration record")
    args = parser.parse_args(argv)
    try:
        output = args.output.absolute()
        if output.exists() or output.parent.resolve(strict=True) != output.parent:
            raise artifact_io.BenchmarkError("calibration_output", "output must be a new file in a canonical directory")
        result = calibrate(load_input(args.input))
        artifact_io.write_new(output, result)
        print(artifact_io.canonical({key: result[key] for key in ("t_star", "t_upper", "nulls",
                                                                  "veto_material_errors", "power")}).decode())
        return 0
    except (artifact_io.BenchmarkError, OSError, ValueError, TypeError, KeyError, ArithmeticError) as error:
        print(f"{getattr(error, 'code', 'calibration_error')}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
