"""Apply a pre-registered qualification rule to sealed campaign review sets.

The task is the sampling unit and its repository is the test unit. Unresolved
outcomes are evaluated at both bounds; a decision that changes between them is
inconclusive. Critical values come from the pre-registration because they are
calibrated by simulation outside this module.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import math
import statistics
import sys

from . import artifacts as artifact_io
from . import campaign


PREREG_FIELDS = {"kind", "schema_version", "claim", "baseline", "candidate", "reviewer", "repetitions",
                 "clusters", "margin", "t_star", "t_upper", "veto_material_errors", "max_unknown_usage",
                 "max_infrastructure_failures", "latency", "audit"}
AUDIT_FIELDS = {"reviewer", "false_accept_limit", "discordance_p"}
CLAIMS = {"R": {"step1_bound": None, "gmr_upper": 1.0}, "Q": {"step1_bound": 0.0, "gmr_upper": 1.10}}
SAVING = 0.90
# Stops and interruptions invalidate a stage; infrastructure failures are counted against a limit.
STAGE_STOPS = {"not_run", "unfinished", "missing_artifacts", "setup_error", "input_changed"}
INFRASTRUCTURE = {"invocation_error", "model_error"}


def inventory_error(message):
    return artifact_io.BenchmarkError("qualify_inventory", message)


def load_prereg(path: Path) -> tuple[dict, str]:
    body = artifact_io.read_file(path)
    value = artifact_io.parse_json(body)
    fail = lambda message: artifact_io.BenchmarkError("qualify_prereg", message)
    if not isinstance(value, dict) or set(value) != PREREG_FIELDS:
        raise fail("unexpected pre-registration fields")
    number = lambda item, low, high: type(item) in (int, float) and low < item <= high
    count = lambda item: type(item) is int and item >= 0
    if (value["kind"] != "mastermind-qualification-prereg" or value["schema_version"] != 1
            or value["claim"] not in CLAIMS
            or not all(isinstance(value[name], str) and value[name] for name in ("baseline", "candidate", "reviewer"))
            or value["baseline"] == value["candidate"]
            or type(value["repetitions"]) is not int or not 2 <= value["repetitions"] <= 20 or value["repetitions"] % 2
            or not number(value["margin"], 0, 1) or not number(value["t_star"], 0, 100)
            or not number(value["t_upper"], 0, 100)
            or not all(count(value[name]) for name in ("veto_material_errors", "max_unknown_usage",
                                                      "max_infrastructure_failures"))
            or type(value["latency"]) is not bool):
        raise fail("invalid pre-registration values")
    clusters = value["clusters"]
    if (not isinstance(clusters, dict) or not clusters
            or not all(isinstance(key, str) and isinstance(label, str) and label for key, label in clusters.items())
            or len(set(clusters.values())) < 2):
        raise fail("clusters map every case to a repository, with at least two repositories")
    audit = value["audit"]
    if audit is not None and (not isinstance(audit, dict) or set(audit) != AUDIT_FIELDS
            or not isinstance(audit["reviewer"], str) or not audit["reviewer"] or audit["reviewer"] == value["reviewer"]
            or not number(audit["false_accept_limit"], 0, 1) or not number(audit["discordance_p"], 0, 1)):
        raise fail("invalid audit detector")
    return value, hashlib.sha256(body).hexdigest()


def case_records(comparison: dict, prereg: dict) -> tuple[list[dict], dict]:
    records, states = [], {}
    for report in comparison["cases"]:
        labels = {row["reviewer"]: row for row in report["by_reviewer"]}
        judged = labels.get(prereg["reviewer"])
        source = judged or report["by_reviewer"][0]
        pairs = []
        for pair in source["pairs"]:
            row = {}
            for arm in ("baseline", "candidate"):
                slot = pair[arm]
                states[slot["run_status"]] = states.get(slot["run_status"], 0) + 1
                failed = slot["reason"].startswith("failed")
                success = slot["success"] if judged is not None or failed else {"lower": 0, "upper": 1}
                # A failed attempt without a reviewed answer cannot carry a material error.
                material = slot["material_error"] if judged is not None else None
                if failed and material is None:
                    material = False
                row[arm] = {"success": success, "material_error": material, "review_id": slot["review_id"]}
            pairs.append(row)
        resources = report["efficiency"][0]["by_condition"]
        records.append({"case": report["task_id"], "pairs": pairs, "labels": labels, "judged": judged is not None,
            "tool_revision": report["tool_revision"],
            "resources": {arm: {metric: resources[prereg[arm]]["resources"][metric]
                                for metric in ("total_tokens", "trial_total_seconds")}
                          for arm in ("baseline", "candidate")}})
    return records, states


def campaign_identity(path: Path) -> tuple[dict, str]:
    body = artifact_io.read_file(path / "review-set.json")
    plan = artifact_io.parse_json(body)["campaign"]
    return ({"config_sha256": plan["config_sha256"], "conditions": plan["conditions"],
             "repetitions": plan["repetitions"], "model": plan["model"]}, hashlib.sha256(body).hexdigest())


def load_cases(review_sets: list[Path], prereg: dict, *, interim: bool) -> tuple[list[dict], list[dict]]:
    cases, bindings, identities = [], [], []
    for path in review_sets:
        identity, digest = campaign_identity(path)
        if (sorted(identity["conditions"]) != sorted((prereg["baseline"], prereg["candidate"]))
                or identity["repetitions"] != prereg["repetitions"]):
            raise inventory_error("a qualification campaign runs exactly the registered two conditions and repetitions")
        comparison = campaign.compare(path, prereg["baseline"], prereg["candidate"])
        if comparison["scope"] != "sealed_current_source_qualification" or not comparison["balanced_positions"]:
            raise inventory_error("qualification needs balanced sealed qualification campaigns")
        records, states = case_records(comparison, prereg)
        if set(states) & STAGE_STOPS:
            raise artifact_io.BenchmarkError("qualify_stage_invalid", "a stopped or interrupted attempt invalidates the stage")
        failures = sum(states.get(state, 0) for state in INFRASTRUCTURE)
        if failures > prereg["max_infrastructure_failures"]:
            raise artifact_io.BenchmarkError("qualify_stage_invalid", "infrastructure failures exceed the registered limit")
        if not any(record["judged"] for record in records):
            raise inventory_error("the registered reviewer assessed no case in this review set")
        identities.append((identity["config_sha256"], identity["model"],
                           frozenset(record["tool_revision"] for record in records)))
        cases.extend(records)
        bindings.append({"review_set_sha256": digest, "corpus_sha256": comparison["corpus_sha256"],
                         "config_sha256": identity["config_sha256"], "cases": len(records),
                         "unreviewed_cases": sum(not record["judged"] for record in records),
                         "infrastructure_failures": failures})
    identifiers = [case["case"] for case in cases]
    expected = set(prereg["clusters"])
    if (len(set(identities)) != 1 or len(next(iter(identities))[2]) != 1
            or len(set(identifiers)) != len(identifiers)
            or not set(identifiers) <= expected or not interim and set(identifiers) != expected):
        raise inventory_error("review sets must cover the registered cases once with one configuration, model and tool")
    return cases, bindings


def mean(values):
    return sum(values) / len(values)


def cluster_estimate(values: dict, clusters: dict, critical: float) -> dict:
    """Mean over repositories of per-repository task means, with a t-scaled standard error."""
    groups = {}
    for case, value in values.items():
        groups.setdefault(clusters[case], []).append(value)
    means = [mean(group) for group in groups.values()]
    centre = mean(means)
    if len(means) < 2:
        return {"point": centre, "standard_error": None, "lower": None, "upper": None, "repositories": len(means)}
    error = statistics.stdev(means) / math.sqrt(len(means))
    return {"point": centre, "standard_error": error, "lower": centre - critical * error,
            "upper": centre + critical * error, "repositories": len(means)}


def resource_ratio(cases: list[dict], metric: str, prereg: dict, summary) -> dict:
    """Per-task log ratios; a non-positive or missing observation counts as unknown usage."""
    unknown = {"baseline": 0, "candidate": 0}
    ratios, complete = {}, True
    for case in cases:
        positive = {}
        for arm in unknown:
            measured = case["resources"][arm][metric]
            values = [value for value in measured["observed_values"] if value > 0]
            unknown[arm] += measured["unknown_attempts"] + len(measured["observed_values"]) - len(values)
            positive[arm] = values
        if all(positive.values()):
            ratios[case["case"]] = summary(positive["candidate"]) - summary(positive["baseline"])
        else:
            complete = False
    if not complete or max(unknown.values()) > prereg["max_unknown_usage"]:
        return {"status": "unknown", "unknown_attempts": unknown}
    estimate = cluster_estimate(ratios, prereg["clusters"], prereg["t_upper"])
    upper = None if estimate["upper"] is None else math.exp(estimate["upper"])
    return {"status": "measured", "unknown_attempts": unknown, "ratio": math.exp(estimate["point"]), "upper": upper}


def scenario(cases: list[dict], prereg: dict, bound: str, tokens: dict, seconds: dict | None) -> dict:
    """Acceptance and veto at one bound: worst favours the baseline, best the candidate."""
    pick = {"worst": {"baseline": "upper", "candidate": "lower"},
            "best": {"baseline": "lower", "candidate": "upper"}}[bound]
    deltas, rates, errors = {}, {"baseline": [], "candidate": []}, {"baseline": 0, "candidate": 0}
    for case in cases:
        means = {arm: mean([pair[arm]["success"][pick[arm]] for pair in case["pairs"]]) for arm in rates}
        for arm in rates:
            rates[arm].append(means[arm])
            for pair in case["pairs"]:
                flag = pair[arm]["material_error"]
                unfavourable = (arm == "candidate") == (bound == "worst")
                errors[arm] += flag is True or flag is None and unfavourable
        deltas[case["case"]] = means["candidate"] - means["baseline"]
    acceptance = cluster_estimate(deltas, prereg["clusters"], prereg["t_star"])
    vetoed = errors["candidate"] - errors["baseline"] > prereg["veto_material_errors"]
    rule = CLAIMS[prereg["claim"]]
    bound_value = -prereg["margin"] if rule["step1_bound"] is None else rule["step1_bound"]
    step1 = acceptance["lower"] is not None and acceptance["lower"] > bound_value and not vetoed
    rate = {arm: mean(rates[arm]) for arm in rates}
    step2 = None
    if tokens["status"] == "measured" and tokens["upper"] is not None:
        step2 = tokens["upper"] < rule["gmr_upper"]
        if prereg["claim"] == "R":
            per_accepted = tokens["ratio"] * rate["baseline"] / rate["candidate"] if rate["candidate"] > 0 else math.inf
            step2 = step2 and tokens["ratio"] <= SAVING and per_accepted <= SAVING
    step3 = None
    if seconds is not None and seconds["status"] == "measured" and seconds["upper"] is not None:
        step3 = seconds["upper"] < 1.0 and seconds["ratio"] <= SAVING
    # Steps apply in a fixed sequence: an unknown later step matters only after the earlier one holds.
    if not step1:
        decision = "reject"
    elif step2 is None or step2 and seconds is not None and step3 is None:
        decision = "inconclusive"
    else:
        decision = "promote" if step2 and step3 is not False else "experimental"
    return {"decision": decision, "acceptance": acceptance, "acceptance_rate": rate,
            "material_errors": errors, "vetoed": vetoed, "steps": [step1, step2, step3]}


def binomial_tail(successes: int, trials: int, rate: float) -> float:
    return sum(math.comb(trials, k) * rate ** k * (1 - rate) ** (trials - k) for k in range(successes, trials + 1))


def clopper_pearson_lower(successes: int, trials: int, alpha: float = 0.05) -> float:
    """One-sided exact lower bound: the smallest rate with P(X >= successes) >= alpha."""
    if successes == 0:
        return 0.0
    low, high = 0.0, 1.0
    for _ in range(80):
        middle = (low + high) / 2
        low, high = (low, middle) if binomial_tail(successes, trials, middle) >= alpha else (middle, high)
    return high


def fisher_exact(table: list[list[int]]) -> float:
    """Two-sided p-value: total probability of tables as or less likely than the observed one."""
    (a, b), (c, d) = table
    rows, column, total = (a + b, c + d), a + c, a + b + c + d
    probability = lambda x: math.comb(rows[0], x) * math.comb(rows[1], column - x) / math.comb(total, column)
    observed = probability(a)
    support = range(max(0, column - rows[1]), min(rows[0], column) + 1)
    return min(1.0, sum(p for p in map(probability, support) if p <= observed * (1 + 1e-9)))


def audit_detector(cases: list[dict], prereg: dict) -> dict | None:
    audit = prereg["audit"]
    if audit is None:
        return None
    unmet = false_accepts = audited = 0
    discord = {"baseline": [0, 0], "candidate": [0, 0]}
    for case in cases:
        judge, human = (case["labels"].get(name) for name in (prereg["reviewer"], audit["reviewer"]))
        if judge is None or human is None:
            continue
        audited += 1
        for judged, checked in zip(judge["pairs"], human["pairs"]):
            for arm in discord:
                left, right = judged[arm]["success"], checked[arm]["success"]
                if (left["lower"] != left["upper"] or right["lower"] != right["upper"]
                        or not checked[arm]["reason"].startswith("reviewer_declared")):
                    continue
                discord[arm][left["lower"] != right["lower"]] += 1
                if right["lower"] == 0:
                    unmet += 1
                    false_accepts += left["lower"] == 1
    lower = clopper_pearson_lower(false_accepts, unmet) if unmet else None
    table = [discord["baseline"], discord["candidate"]]
    p_value = fisher_exact(table) if all(sum(row) for row in table) else None
    # A registered audit that observed no human labels is missing evidence, not a pass.
    fired = (not audited or lower is not None and lower > audit["false_accept_limit"]
             or p_value is not None and p_value < audit["discordance_p"])
    return {"audited_cases": audited, "human_unmet": unmet, "judge_false_accepts": false_accepts,
            "false_accept_lower_bound": lower,
            "agreement_by_arm": {arm: {"agree": row[0], "disagree": row[1]} for arm, row in discord.items()},
            "discordance_p": p_value, "inconclusive": fired}


def log_mean(values):
    return mean([math.log(value) for value in values])


def log_median(values):
    return math.log(statistics.median(values))


def decide(cases: list[dict], prereg: dict, *, interim: bool = False) -> dict:
    tokens = resource_ratio(cases, "total_tokens", prereg, log_mean)
    seconds = resource_ratio(cases, "trial_total_seconds", prereg, log_median) if prereg["latency"] else None
    scenarios = {bound: scenario(cases, prereg, bound, tokens, seconds) for bound in ("worst", "best")}
    audit = audit_detector(cases, prereg)
    reasons = []
    if interim:
        # Non-binding futility uses the bound most favourable to the candidate.
        if scenarios["best"]["acceptance"]["point"] < -prereg["margin"]:
            decision, reasons = "reject", ["futility_acceptance"]
        elif prereg["claim"] == "R" and tokens["status"] == "measured" and tokens["ratio"] >= 1.0:
            decision, reasons = "experimental", ["futility_tokens"]
        else:
            decision = "continue"
    else:
        decisions = {row["decision"] for row in scenarios.values()}
        decision = next(iter(decisions)) if len(decisions) == 1 else "inconclusive"
        if len(decisions) > 1:
            reasons.append("unresolved_outcomes_change_decision")
        if "inconclusive" in decisions:
            reasons.append("unknown_resource_usage")
        if audit is not None and audit["inconclusive"]:
            decision = "inconclusive"
            reasons.append("audit_detector")
    return {"decision": decision, "reasons": reasons, "scenarios": scenarios, "tokens": tokens,
            "latency": seconds, "audit": audit, "tasks": len(cases),
            "repositories": len({prereg["clusters"][case["case"]] for case in cases})}


def case_summary(case: dict, prereg: dict) -> dict:
    return {"case": case["case"], "repository": prereg["clusters"][case["case"]], "reviewed": case["judged"],
            "acceptance": {arm: {bound: mean([pair[arm]["success"][bound] for pair in case["pairs"]])
                                 for bound in ("lower", "upper")} for arm in ("baseline", "candidate")}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--review-set", type=Path, action="append", required=True)
    parser.add_argument("--interim", action="store_true", help="apply only the non-binding futility rule")
    parser.add_argument("--report", type=Path, required=True, help="new private report with per-case records")
    parser.add_argument("--decision", type=Path, required=True, help="new decision record without per-case data")
    args = parser.parse_args(argv)
    try:
        report_path, decision_path = args.report.absolute(), args.decision.absolute()
        if report_path == decision_path or report_path.exists() or decision_path.exists():
            raise artifact_io.BenchmarkError("qualify_output", "report and decision must be two new files")
        prereg, digest = load_prereg(args.prereg)
        cases, bindings = load_cases([path.resolve() for path in args.review_set], prereg, interim=args.interim)
        result = decide(cases, prereg, interim=args.interim)
        identity = {"prereg_sha256": digest, "mode": "interim" if args.interim else "final", "claim": prereg["claim"],
                    "baseline": prereg["baseline"], "candidate": prereg["candidate"], "reviewer": prereg["reviewer"],
                    "review_sets": bindings, "semantics": "pre_registered_rule_on_reviewer_declared_outcomes"}
        report = {"kind": "mastermind-qualification-report", "schema_version": 1, **identity, **result,
                  "cases": [case_summary(case, prereg) for case in cases]}
        decision = {"kind": "mastermind-qualification-decision", "schema_version": 1, **identity,
                    "decision": result["decision"], "reasons": result["reasons"], "tasks": result["tasks"],
                    "repositories": result["repositories"],
                    "acceptance": {bound: {key: row["acceptance"][key] for key in ("point", "lower")}
                                   for bound, row in result["scenarios"].items()},
                    "tokens": result["tokens"], "latency": result["latency"],
                    "audit_inconclusive": None if result["audit"] is None else result["audit"]["inconclusive"]}
        artifact_io.write_new(report_path, report)
        try:
            artifact_io.write_new(decision_path, decision)
        except BaseException:
            report_path.unlink(missing_ok=True)
            raise
        print(artifact_io.canonical(decision).decode())
        return 0
    except (artifact_io.BenchmarkError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"{getattr(error, 'code', 'qualify_error')}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
