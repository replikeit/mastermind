"""The registered qualification rule decides from clustered task outcomes and keeps unknowns visible."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from evals.benchmark import artifacts, campaign, qualify, review
from tests.evals.support.corpus import CorpusFixture
from tests.evals.support.review import completed_assessment


def prereg(**change):
    value = {"kind": "mastermind-qualification-prereg", "schema_version": 1, "claim": "R",
             "baseline": "base", "candidate": "cand", "reviewer": "judge", "repetitions": 2,
             "clusters": {f"t{index}": f"r{index // 2}" for index in range(8)}, "margin": 0.10,
             "t_star": 2.353, "t_upper": 1.638, "veto_material_errors": 1, "max_unknown_usage": 2,
             "max_infrastructure_failures": 0, "latency": False, "audit": None}
    value.update(change)
    return value


def series(value, count):
    return list(value) if isinstance(value, (list, tuple)) else [value] * count


def case(name, baseline=(1, 1), candidate=(1, 1), tokens=(100, 80), unknown=(0, 0), seconds=(10, 10), errors=0):
    """Outcomes are 0, 1 or None for an unresolved review; errors flags candidate answers as material errors.

    Token and second entries are one value per arm or a list with one value per attempt."""
    pairs = []
    for index, (left, right) in enumerate(zip(baseline, candidate)):
        row = {}
        for arm, value in (("baseline", left), ("candidate", right)):
            success = {"lower": 0, "upper": 1} if value is None else {"lower": value, "upper": value}
            flag = None if value is None else arm == "candidate" and index < errors
            row[arm] = {"success": success, "material_error": flag, "review_id": f"{name}-{arm}-{index}"}
        pairs.append(row)
    resources = {arm: {"total_tokens": {"observed_values": series(tokens[position], len(pairs)),
                                        "unknown_attempts": unknown[position]},
                       "trial_total_seconds": {"observed_values": series(seconds[position], len(pairs)),
                                               "unknown_attempts": 0}}
                 for position, arm in enumerate(("baseline", "candidate"))}
    return {"case": name, "pairs": pairs, "labels": {}, "judged": True, "tool_revision": "rev",
            "resources": resources}


def corpus(ratios=(78, 80, 82, 79, 81, 80, 77, 83), **change):
    return [case(f"t{index}", tokens=(100, ratio), **change) for index, ratio in enumerate(ratios)]


def report(name, judged=True, statuses=("completed", "completed"), material=(False, False), tool="rev"):
    """A campaign.compare case report for arms base/cand with two repetitions."""
    pairs = []
    for index in range(2):
        row = {}
        for position, arm in enumerate(("baseline", "candidate")):
            status = statuses[position]
            failed = status != "completed"
            success = {"lower": 0, "upper": 0} if failed else {"lower": 1, "upper": 1} if judged else {"lower": 0, "upper": 1}
            reason = ("failed_attempt" if failed else "reviewer_declared_satisfied" if judged
                      else "unreviewed_or_unknown")
            row[arm] = {"review_id": f"{name}-{arm}-{index}", "run_status": status, "success": success,
                        "reason": reason, "material_error": material[position] if judged else None}
        pairs.append(row)
    resources = {"total_tokens": {"observed_values": [100, 100], "unknown_attempts": 0},
                 "trial_total_seconds": {"observed_values": [10, 10], "unknown_attempts": 0}}
    return {"task_id": name, "tool_revision": tool,
            "by_reviewer": [{"reviewer": "judge" if judged else None, "pairs": pairs}],
            "efficiency": [{"by_condition": {arm: {"resources": copy.deepcopy(resources)} for arm in ("base", "cand")}}]}


def comparison(reports, model="model", scope="sealed_current_source_qualification", balanced=True):
    return {"cases": reports, "model": model, "scope": scope, "balanced_positions": balanced, "corpus_sha256": "c" * 64}


class DecisionRuleTests(unittest.TestCase):
    def test_registered_steps_promote_keep_experimental_or_reject(self):
        self.assertEqual(qualify.decide(corpus(), prereg())["decision"], "promote")
        self.assertEqual(qualify.decide(corpus((94, 96, 95, 95, 96, 94, 95, 95)), prereg())["decision"], "experimental")
        losses = corpus()
        for item in losses[::2]:
            item.update(case(item["case"], candidate=(0, 0), tokens=(100, 80)))
        result = qualify.decide(losses, prereg())
        self.assertEqual(result["decision"], "reject")
        self.assertAlmostEqual(result["scenarios"]["worst"]["acceptance"]["point"], -0.5)

    def test_acceptance_bound_uses_repository_means_and_t_star(self):
        cases = []
        for index in range(8):
            baseline, candidate = (1, 1, 1, 1), (1, 1, 1, 1)
            if index == 0:
                candidate = (0, 1, 1, 1)
            if index == 2:
                baseline = (0, 1, 1, 1)
            cases.append(case(f"t{index}", baseline=baseline, candidate=candidate, tokens=(100, 80)))
        acceptance = qualify.decide(cases, prereg())["scenarios"]["worst"]["acceptance"]
        error = (2 * 0.125 ** 2 / 3) ** 0.5 / 2
        self.assertAlmostEqual(acceptance["standard_error"], error)
        self.assertAlmostEqual(acceptance["lower"], -2.353 * error)
        self.assertEqual(acceptance["repositories"], 4)
        self.assertEqual(qualify.decide(cases, prereg())["decision"], "reject")
        self.assertEqual(qualify.decide(cases, prereg(t_star=1.638))["decision"], "promote")

    def test_token_upper_bound_uses_t_upper(self):
        cases = [case(f"t{index}", tokens=(100, (70, 75, 95, 105)[index // 2])) for index in range(8)]
        result = qualify.decide(cases, prereg())
        self.assertLess(result["tokens"]["upper"], 1.0)
        self.assertEqual(result["decision"], "promote")
        self.assertEqual(qualify.decide(cases, prereg(t_upper=2.353))["decision"], "experimental")

    def test_unresolved_outcomes_that_change_the_decision_are_inconclusive(self):
        cases = corpus()
        cases[0] = case("t0", candidate=(None, None), tokens=(100, 78))
        result = qualify.decide(cases, prereg(veto_material_errors=10))
        self.assertLess(result["scenarios"]["worst"]["acceptance"]["lower"], -0.10)
        self.assertFalse(result["scenarios"]["worst"]["vetoed"])
        self.assertEqual({bound: row["decision"] for bound, row in result["scenarios"].items()},
                         {"worst": "reject", "best": "promote"})
        self.assertEqual((result["decision"], result["reasons"]), ("inconclusive", ["unresolved_outcomes_change_decision"]))
        self.assertEqual(result["scenarios"]["worst"]["material_errors"]["candidate"], 2)
        self.assertEqual(result["scenarios"]["best"]["material_errors"]["candidate"], 0)

    def test_material_error_veto_and_unknown_usage_boundaries(self):
        cases = corpus()
        cases[0] = case("t0", tokens=(100, 78), errors=2)
        result = qualify.decide(cases, prereg())
        self.assertEqual((result["decision"], result["scenarios"]["worst"]["vetoed"]), ("reject", True))
        self.assertEqual(result["scenarios"]["worst"]["material_errors"], {"baseline": 0, "candidate": 2})
        cases[0] = case("t0", tokens=(100, 78), errors=1)
        self.assertEqual(qualify.decide(cases, prereg())["decision"], "promote")
        cases[0] = case("t0", tokens=(100, 78), unknown=(0, 2))
        self.assertEqual(qualify.decide(cases, prereg())["tokens"]["status"], "measured")
        for change, unknown in (({"unknown": (0, 3)}, {"baseline": 0, "candidate": 3}),
                                ({"unknown": (3, 0)}, {"baseline": 3, "candidate": 0}),
                                ({"tokens": ([100, 0], [0, 0])}, {"baseline": 1, "candidate": 2}),
                                ({"tokens": ([100, 100], []), "unknown": (0, 2)}, {"baseline": 0, "candidate": 2})):
            with self.subTest(change=change):
                cases[0] = case("t0", **dict({"tokens": (100, 78)}, **change))
                limit = 0 if change.get("tokens", (0, [0]))[1] == [0, 0] else 2
                result = qualify.decide(cases, prereg(max_unknown_usage=limit))
                self.assertEqual((result["decision"], result["tokens"]["status"]), ("inconclusive", "unknown"))
                self.assertEqual(result["tokens"]["unknown_attempts"], unknown)
                self.assertEqual(result["reasons"], ["unknown_resource_usage"])

    def test_tokens_use_geometric_means_and_charge_accepted_answers(self):
        skewed = [case(f"t{index}", tokens=([100, 100, 100, 100], [50, 50, 50, 1600]),
                       baseline=(1,) * 4, candidate=(1,) * 4) for index in range(8)]
        result = qualify.decide(skewed, prereg())
        self.assertAlmostEqual(result["tokens"]["ratio"], (50 ** 3 * 1600) ** 0.25 / 100)
        self.assertEqual(result["decision"], "experimental")
        lower_yield = [case(f"t{index}", baseline=(1,) * 10 + (0,) * 10, candidate=(1,) * 9 + (0,) * 11,
                            tokens=(100, 85)) for index in range(8)]
        result = qualify.decide(lower_yield, prereg())
        self.assertAlmostEqual(result["scenarios"]["worst"]["acceptance"]["lower"], -0.05)
        self.assertEqual(result["decision"], "experimental")
        higher_yield = [case(f"t{index}", baseline=(0, 1), tokens=(100, 95)) for index in range(8)]
        self.assertEqual(qualify.decide(higher_yield, prereg())["decision"], "experimental")

    def test_quality_claim_needs_a_positive_bound_and_a_bounded_token_increase(self):
        self.assertEqual(qualify.decide(corpus((100,) * 8), prereg(claim="Q"))["decision"], "reject")
        better = [case(f"t{index}", baseline=(0, 1), tokens=(100, 101)) for index in range(8)]
        result = qualify.decide(better, prereg(claim="Q"))
        self.assertEqual(result["decision"], "promote")
        self.assertAlmostEqual(result["scenarios"]["worst"]["acceptance"]["point"], 0.5)
        costly = [case(f"t{index}", baseline=(0, 1), tokens=(100, 150 + index)) for index in range(8)]
        self.assertEqual(qualify.decide(costly, prereg(claim="Q"))["decision"], "experimental")
        self.assertEqual(qualify.decide(costly, prereg(claim="Q"), interim=True)["decision"], "continue")

    def test_claimed_latency_uses_medians_after_the_token_step(self):
        fast = [case(f"t{index}", tokens=(100, 78 + index % 3), seconds=([10, 10, 10], [5, 5, 40]),
                     baseline=(1, 1, 1), candidate=(1, 1, 1)) for index in range(8)]
        slow = [case(f"t{index}", tokens=(100, 78 + index % 3), seconds=(10, 9.7)) for index in range(8)]
        self.assertEqual(qualify.decide(fast, prereg(latency=True))["decision"], "promote")
        self.assertEqual(qualify.decide(slow, prereg(latency=True))["decision"], "experimental")
        for ratios, decision in (((78, 80, 82, 79, 81, 80, 77, 83), "inconclusive"),
                                 ((94, 96, 95, 95, 96, 94, 95, 95), "experimental")):
            with self.subTest(decision=decision):
                cases = corpus(ratios)
                cases[0]["resources"]["candidate"]["trial_total_seconds"]["unknown_attempts"] = 3
                result = qualify.decide(cases, prereg(latency=True))
                self.assertEqual((result["decision"], result["latency"]["status"]), (decision, "unknown"))

    def test_audit_detector_statistics_filters_and_missing_labels(self):
        self.assertAlmostEqual(qualify.clopper_pearson_lower(5, 5), 0.05 ** (1 / 5), places=6)
        self.assertEqual(qualify.clopper_pearson_lower(0, 4), 0.0)
        self.assertAlmostEqual(qualify.fisher_exact([[3, 1], [1, 3]]), 34 / 70, places=9)
        audit = {"reviewer": "maintainer", "false_accept_limit": 0.15, "discordance_p": 0.01}

        def labelled(judge_success, human_success, human_reason="reviewer_declared_unsatisfied", count=3):
            cases = corpus()
            for item in cases[:count]:
                judge, human = copy.deepcopy(item["pairs"]), copy.deepcopy(item["pairs"])
                for pair in judge:
                    for arm in pair:
                        pair[arm].update(success=dict(judge_success), reason="reviewer_declared_satisfied")
                for pair in human:
                    for arm in pair:
                        pair[arm].update(success=dict(human_success), reason=human_reason)
                item["labels"] = {"judge": {"pairs": judge}, "maintainer": {"pairs": human}}
            return cases

        agreeing = qualify.decide(labelled({"lower": 1, "upper": 1}, {"lower": 1, "upper": 1},
                                           "reviewer_declared_satisfied"), prereg(audit=audit))
        self.assertEqual((agreeing["decision"], agreeing["audit"]["inconclusive"]), ("promote", False))
        lenient = qualify.decide(labelled({"lower": 1, "upper": 1}, {"lower": 0, "upper": 0}), prereg(audit=audit))
        self.assertEqual((lenient["audit"]["human_unmet"], lenient["audit"]["judge_false_accepts"]), (12, 12))
        self.assertEqual((lenient["decision"], lenient["reasons"]), ("inconclusive", ["audit_detector"]))
        for judge_success, reason in (({"lower": 1, "upper": 1}, "failed_attempt"),
                                      ({"lower": 0, "upper": 1}, "reviewer_declared_unsatisfied")):
            with self.subTest(reason=reason, judge=judge_success):
                result = qualify.decide(labelled(judge_success, {"lower": 0, "upper": 0}, reason), prereg(audit=audit))
                self.assertEqual(result["audit"]["human_unmet"], 0)
                self.assertEqual(result["decision"], "promote")
        unaudited = qualify.decide(corpus(), prereg(audit=audit))
        self.assertEqual((unaudited["audit"]["audited_cases"], unaudited["decision"]), (0, "inconclusive"))
        discordant = labelled({"lower": 1, "upper": 1}, {"lower": 0, "upper": 0})
        for item in discordant[:3]:
            for pair in item["labels"]["maintainer"]["pairs"]:
                pair["baseline"].update(success={"lower": 1, "upper": 1}, reason="reviewer_declared_satisfied")
        result = qualify.decide(discordant, prereg(audit=dict(audit, false_accept_limit=0.99)))
        self.assertEqual(result["audit"]["agreement_by_arm"], {"baseline": {"agree": 6, "disagree": 0},
                                                               "candidate": {"agree": 0, "disagree": 6}})
        self.assertLess(result["audit"]["discordance_p"], 0.01)
        self.assertEqual(result["decision"], "inconclusive")

    def test_interim_futility_is_non_binding_and_serialisable_for_one_repository(self):
        losses = [case(f"t{index}", candidate=(0, 0)) for index in range(8)]
        self.assertEqual(qualify.decide(losses, prereg(), interim=True)["decision"], "reject")
        costly = corpus((100, 101, 102, 100, 103, 101, 100, 102))
        self.assertEqual(qualify.decide(costly, prereg(), interim=True)["decision"], "experimental")
        self.assertEqual(qualify.decide(corpus(), prereg(), interim=True)["decision"], "continue")
        unresolved = [case(f"t{index}", candidate=(None, None), tokens=(100, 80)) for index in range(8)]
        self.assertEqual(qualify.decide(unresolved, prereg(), interim=True)["decision"], "continue")
        one = qualify.decide(corpus()[:2], prereg(), interim=True)
        self.assertEqual((one["decision"], one["repositories"]), ("continue", 1))
        self.assertIsNone(one["scenarios"]["worst"]["acceptance"]["lower"])
        artifacts.canonical(one)

    def test_case_records_keep_judge_flags_and_unresolved_missing_reviews(self):
        records, states = qualify.case_records(comparison([
            report("t0", statuses=("completed", "budget_exceeded"), material=(False, True)),
            report("t1", judged=False, statuses=("completed", "timeout"))]), prereg())
        failed = records[0]["pairs"][0]["candidate"]
        self.assertEqual((failed["success"], failed["material_error"]), ({"lower": 0, "upper": 0}, True))
        self.assertEqual(records[0]["pairs"][0]["baseline"]["material_error"], False)
        unjudged = records[1]["pairs"][0]
        self.assertEqual(unjudged["baseline"]["success"], {"lower": 0, "upper": 1})
        self.assertEqual((unjudged["candidate"]["success"], unjudged["candidate"]["material_error"]),
                         ({"lower": 0, "upper": 0}, False))
        self.assertEqual(states, {"completed": 4, "budget_exceeded": 2, "timeout": 2})

    def test_load_cases_refuses_mixed_or_invalid_stages(self):
        identity = {"config_sha256": "a" * 64, "conditions": ["base", "cand"], "repetitions": 2, "model": "model"}
        value = prereg(clusters={"t0": "r0", "t1": "r1"})
        sets = [Path("/stage-1"), Path("/stage-2")]

        def run(reports_by_set, identities=None, code="qualify_inventory"):
            replies = iter([comparison(reports) for reports in reports_by_set])
            stamps = iter(identities or [identity] * len(reports_by_set))
            with patch.object(qualify.campaign, "compare", side_effect=lambda *args: next(replies)), \
                    patch.object(qualify, "campaign_identity", side_effect=lambda path: (next(stamps), "d" * 64)):
                with self.assertRaises(artifacts.BenchmarkError) as raised:
                    qualify.load_cases(sets[:len(reports_by_set)], value, interim=False)
            self.assertEqual(raised.exception.code, code)

        run([[report("t0")], [report("t1")]], [identity, dict(identity, config_sha256="b" * 64)])
        run([[report("t0")], [report("t1", tool="other")]])
        run([[report("t0"), report("t1")]], [dict(identity, conditions=["base", "cand", "third"])])
        run([[report("t0"), report("t1", judged=False)]], [dict(identity, repetitions=4)])
        run([[report("t0", judged=False), report("t1", judged=False)]])
        run([[report("t0"), report("t1", statuses=("not_run", "completed"))]], code="qualify_stage_invalid")
        run([[report("t0"), report("t1", statuses=("model_error", "completed"))]], code="qualify_stage_invalid")
        with patch.object(qualify.campaign, "compare", return_value=comparison([report("t0"), report("t1")], balanced=False)), \
                patch.object(qualify, "campaign_identity", return_value=(identity, "d" * 64)):
            with self.assertRaises(artifacts.BenchmarkError):
                qualify.load_cases(sets[:1], value, interim=False)
        with patch.object(qualify.campaign, "compare",
                          return_value=comparison([report("t0"), report("t1", statuses=("model_error", "completed"))])), \
                patch.object(qualify, "campaign_identity", return_value=(identity, "d" * 64)):
            cases, bindings = qualify.load_cases(sets[:1], dict(value, max_infrastructure_failures=2), interim=False)
        self.assertEqual((len(cases), bindings[0]["infrastructure_failures"]), (2, 2))

    def test_invalid_registrations_are_refused(self):
        for change in ({"claim": "X"}, {"baseline": "cand"}, {"repetitions": 3}, {"repetitions": 0}, {"margin": 0},
                       {"t_star": "2"}, {"t_upper": -1}, {"kind": "other"}, {"max_infrastructure_failures": -1},
                       {"clusters": {"t0": "r0"}}, {"latency": "yes"}, {"extra": 1},
                       {"audit": {"reviewer": "judge", "false_accept_limit": 0.15, "discordance_p": 0.01}},
                       {"audit": {"reviewer": "human", "false_accept_limit": "0.15", "discordance_p": 0.01}}):
            with self.subTest(change=change):
                directory = Path(tempfile.mkdtemp()).resolve()
                self.addCleanup(shutil.rmtree, directory)
                artifacts.write_new(directory / "prereg.json", prereg(**change))
                with self.assertRaises(artifacts.BenchmarkError) as raised:
                    qualify.load_prereg(directory / "prereg.json")
                self.assertEqual(raised.exception.code, "qualify_prereg")


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class SealedReviewSetTests(unittest.TestCase):
    def setUp(self):
        self.case = CorpusFixture()
        self.addCleanup(self.case.close)
        self.fixture = self.case.fixture
        second = copy.deepcopy(self.case.entry)
        second.update(id="service-02", task="tasks/service-02.json", rubric="rubrics/service-02.json")
        self.case.registry["cases"].append(second)
        self.case.save()
        artifacts.write_new(self.case.root / second["task"], dict(self.case.task, id="service-02"))
        artifacts.write_new(self.case.root / second["rubric"], dict(self.case.key, task_id="service-02"))
        self.case.qualify()
        self.fixture.config["conditions"] = [{"id": "base", "tools": "source", "instruction_paths": []},
                                             {"id": "cand", "tools": "mmcg", "instruction_paths": []}]
        self.campaign = self.fixture.root / "campaign"
        campaign.prepare(corpus_path=self.case.path, config=self.fixture.config, source_repo=self.fixture.repo,
                         tool_repo=self.fixture.repo, output=self.campaign, repetitions=2)
        campaign.run(self.campaign, progress=lambda *args, **kwargs: None)
        self.prereg = prereg(repetitions=2, clusters={"service-01": "r1", "service-02": "r2"},
                             t_star=6.314, t_upper=6.314, veto_material_errors=2)

    def review_set(self, name, reviewers=None, flagged=()):
        output = self.fixture.root / name
        campaign.export(self.campaign, output)
        for identifier, label in (reviewers or {"service-01": "judge", "service-02": "judge"}).items():
            value = completed_assessment(output / identifier, label)
            slots = artifacts.load_json(output / identifier / "coordinator.json")["slots"]
            candidates = {slot["review_id"] for slot in slots if slot["condition"] == "cand"}
            for item in value["reviews"]:
                if identifier in flagged and item["review_id"] in candidates:
                    item["claims"][0].update(support="unsupported", anchors=[], material_error=True)
            submission = self.fixture.root / f"{name}-{identifier}.json"
            artifacts.write_new(submission, value)
            review.import_assessment(output / identifier, submission)
        return output

    def run_cli(self, value, review_sets, name, report=None, decision=None):
        path = self.fixture.root / f"{name}-prereg.json"
        artifacts.write_new(path, value)
        report = report or self.fixture.root / f"{name}-report.json"
        decision = decision or self.fixture.root / f"{name}-decision.json"
        arguments = ["--prereg", str(path), "--report", str(report), "--decision", str(decision)]
        for review_set in review_sets:
            arguments.extend(("--review-set", str(review_set)))
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = qualify.main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_cli_decides_from_sealed_review_sets_and_shares_only_the_decision(self):
        complete = self.review_set("complete", flagged=("service-01",))
        code, out, err = self.run_cli(self.prereg, [complete], "complete")
        self.assertEqual(code, 0, err)
        decision = artifacts.load_json(self.fixture.root / "complete-decision.json")
        self.assertEqual(decision, json.loads(out))
        self.assertEqual(decision["decision"], "experimental")
        self.assertEqual(decision["prereg_sha256"],
                         hashlib.sha256((self.fixture.root / "complete-prereg.json").read_bytes()).hexdigest())
        self.assertEqual(set(decision), {"kind", "schema_version", "prereg_sha256", "mode", "claim", "baseline",
                                         "candidate", "reviewer", "review_sets", "semantics", "decision", "reasons",
                                         "tasks", "repositories", "acceptance", "tokens", "latency",
                                         "audit_inconclusive"})
        self.assertEqual(set(decision["acceptance"]["worst"]), {"point", "lower"})
        report = artifacts.load_json(self.fixture.root / "complete-report.json")
        self.assertEqual([row["case"] for row in report["cases"]], ["service-01", "service-02"])
        self.assertEqual(report["scenarios"]["worst"]["material_errors"], {"baseline": 0, "candidate": 2})
        partial = self.review_set("partial", reviewers={"service-01": "judge", "service-02": "maintainer"})
        code, out, err = self.run_cli(self.prereg, [partial], "partial")
        self.assertEqual(code, 0, err)
        scenarios = artifacts.load_json(self.fixture.root / "partial-report.json")["scenarios"]
        self.assertEqual({bound: row["acceptance"]["point"] for bound, row in scenarios.items()},
                         {"worst": -0.5, "best": 0.5})
        self.assertEqual(json.loads(out)["review_sets"][0]["unreviewed_cases"], 1)
        for name, value, review_sets, code in (
                ("missing_case", dict(self.prereg, clusters={"service-01": "r1", "other": "r2"}), [complete],
                 "qualify_inventory"),
                ("uncovered_case", dict(self.prereg, clusters={**self.prereg["clusters"], "service-03": "r3"}),
                 [complete], "qualify_inventory"),
                ("repetitions", dict(self.prereg, repetitions=4), [complete], "qualify_inventory"),
                ("duplicate_set", self.prereg, [complete, complete], "qualify_inventory")):
            with self.subTest(name=name):
                status, _, err = self.run_cli(value, review_sets, name)
                self.assertEqual(status, 2)
                self.assertTrue(err.startswith(code + ":"), err)
                self.assertFalse((self.fixture.root / f"{name}-decision.json").exists())
                self.assertFalse((self.fixture.root / f"{name}-report.json").exists())
        linked = self.fixture.root / "linked"
        linked.symlink_to(self.fixture.root, target_is_directory=True)
        status, _, err = self.run_cli(self.prereg, [complete], "linked", decision=linked / "linked-decision.json")
        self.assertEqual(status, 2)
        self.assertTrue(err.startswith("artifact_path:"), err)
        self.assertFalse((self.fixture.root / "linked-report.json").exists())
        taken = self.fixture.root / "taken-decision.json"
        taken.write_text("{}")
        for name, report, decision in (("taken", None, taken),
                                       ("same", self.fixture.root / "same.json", self.fixture.root / "same.json")):
            with self.subTest(name=name):
                status, _, err = self.run_cli(self.prereg, [complete], name, report=report, decision=decision)
                self.assertEqual(status, 2)
                self.assertTrue(err.startswith("qualify_output:"), err)
                self.assertFalse((self.fixture.root / f"{name}-report.json").exists())
                self.assertFalse((self.fixture.root / "same.json").exists())


if __name__ == "__main__":
    unittest.main()
