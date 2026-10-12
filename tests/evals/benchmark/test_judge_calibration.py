"""Seeded-defect sets hide their key from the judge and score each defect against its ground truth."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from evals.benchmark import artifacts as artifact_io
from evals.benchmark import judge, judge_calibration, review
from evals.benchmark.review_io import Root, encoded, sha
from tests.evals.support.judge import CANARIES, JudgeFixture


ANSWER = "Observed src/service.py:2: value() returns the fixed value 7. Whether callers rely on the value is unknown."
CLAIM = "Observed src/service.py:2: value() returns the fixed value 7."
UNKNOWN = "Whether callers rely on the value is unknown."

# text, target, passage, anchors
MUTANTS = {
    "criterion_removed": (UNKNOWN, {"criterion_id": "value"}, CLAIM, []),
    "listed_false_claim": (ANSWER.replace("returns the fixed value 7", "fetches 7 over the network"),
                           {"false_claim_index": 0}, "value() fetches 7 over the network.", ["src/service.py:1-2"]),
    "novel_false_claim": (ANSWER.replace("value 7", "value 8"), {}, "value() returns the fixed value 8.", ["src/service.py:2"]),
    "overclaimed_unknown": (ANSWER.replace(UNKNOWN, "Every caller relies on the value."), {"unknown_index": 0},
                            "Every caller relies on the value.", []),
    "fabricated_citation": (ANSWER.replace("service.py:2", "service.py:1"), {"criterion_id": "value"},
                            "Observed src/service.py:1:", ["src/service.py:2"]),
}

SECOND_SET = {
    "novel_false_claim": (ANSWER.replace("value 7", "value 9"), {}, "value() returns the fixed value 9.", ["src/service.py:2"]),
    "overclaimed_unknown": (ANSWER.replace(UNKNOWN, "No caller relies on the value."), {"unknown_index": 0},
                            "No caller relies on the value.", []),
}

MATERIAL = {"quote": "value() fetches 7 over the network.", "support": "contradicted",
            "anchors": ["src/service.py:1-2"], "material_error": True, "rationale": "It returns a literal."}


def verdict(item, answer, *, met=True, claim=None, unknown="appropriate"):
    """A schema-valid review of one answer; met=None marks the criterion unknown. The outcome follows the evidence."""
    first = answer[:answer.index(". ") + 1] if ". " in answer else answer
    claims = [claim or {"quote": first, "support": "supported", "anchors": ["src/service.py:2"],
                        "material_error": False, "rationale": "The cited line returns the value."}]
    excerpt = next((text for text in (UNKNOWN, "Every caller relies on the value.", "No caller relies on the value.")
                    if text in answer), None)
    unknowns = [{"unknown_index": 0, "handling": unknown if excerpt else "omitted",
                 "answer_excerpt": excerpt, "rationale": "Caller reliance."}]
    failed = met is False or any(row["material_error"] for row in claims) or unknowns[0]["handling"] == "overclaimed"
    status = "unsatisfied" if failed else "unknown" if met is None else "satisfied"
    return {"review_id": item["review_id"], "answer_sha256": item["answer_sha256"], "rubric_sha256": item["rubric_sha256"],
            "claims": claims, "outcome": {"status": status, "rationale": "Per the evidence."},
            "knowns": [{"known_index": 0, "coverage": "covered" if "value 7" in answer else "missing",
                        "answer_excerpt": first if "value 7" in answer else None, "rationale": "The fixed value."}],
            "unknowns": unknowns,
            "acceptance": [{"criterion_id": "value", "status": "met" if met else "unknown" if met is None else "unmet",
                            "answer_excerpt": first if met else None, "rationale": "The value and citation."}]}


def rows_for(cases, bad):
    """Four resolved answers per case; a bad case is judged wrong on every one of them."""
    rows = []
    for case in range(cases):
        for defect in ("control", "control", "listed_false_claim", "criterion_removed"):
            expected = "satisfied" if defect == "control" else "unsatisfied"
            wrong = "unsatisfied" if expected == "satisfied" else "satisfied"
            rows.append({"case": f"case-{case}", "defect": defect, "expected": expected,
                         "judged": wrong if case in bad else expected, "located": defect != "control" and case not in bad})
    return rows


def counts(table):
    return {name: (table[name]["successes"], table[name]["trials"]) for name in ("resolved", "worst_case")}


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class JudgeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.judge = JudgeFixture(ANSWER, attempts=2)
        self.addCleanup(self.judge.close)
        self.root, self.export, self.config = self.judge.root, self.judge.export, self.judge.config
        self.originals = [item["review_id"] for item in self.judge.template["reviews"]]
        self.label("reference", {self.originals[0]: True, self.originals[1]: True, self.originals[2]: False})
        self.mutations = self.root / "mutations"
        self.mutations.mkdir()
        self.call = 0

    def label(self, reviewer, satisfied):
        template = self.judge.template
        value = dict(template, reviewer=reviewer,
                     reviews=[verdict(item, ANSWER, met=satisfied[item["review_id"]]) for item in template["reviews"]])
        path = self.root / f"{reviewer}.json"
        path.write_bytes(artifact_io.canonical(value))
        review.import_assessment(self.export, path)

    def plan(self, defects=tuple(MUTANTS), controls=None, file="mutations.json", source=0, texts=MUTANTS, **change):
        mutants = []
        for defect in defects:
            text, target, passage, anchors = texts[defect]
            (self.mutations / f"{file}-{defect}.md").write_text(text)
            mutants.append({"source_review_id": self.originals[source], "defect": defect, "target": target,
                            "answer": f"{file}-{defect}.md", "passage": passage, "anchors": anchors, "rationale": "Seeded."})
        value = {"kind": "mastermind-judge-calibration-mutations", "schema_version": 1, "reference": "reference",
                 "controls": self.originals[:2] if controls is None else controls, "mutants": mutants}
        value.update(change)
        path = self.mutations / file
        path.write_bytes(artifact_io.canonical(value))
        return path

    def cli(self, *argv, key="fixture-key"):
        environment = dict(CANARIES, ANTHROPIC_API_KEY=key)
        with patch.dict(os.environ, environment, clear=True), redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = judge_calibration.main([str(value) for value in argv])
        return code, out.getvalue(), err.getvalue()

    def build(self, directory="set", **change):
        path = self.plan(**change)
        return self.cli("build", self.export, "--mutations", path, "--output", self.root / directory)

    def built(self, directory="set", **change):
        code, out, err = self.build(directory, **change)
        self.assertEqual(code, 0, err)
        calibration_set = Path(out.strip())
        key = artifact_io.load_json(calibration_set / "key.json")
        template = {item["review_id"]: item for item in
                    artifact_io.load_json(calibration_set / "reviewer/assessment-template.json")["reviews"]}
        rows = {}
        for row in key["items"]:
            name = row["defect"] if row["defect"] != "control" else "control-" + row["source_review_id"]
            rows[name] = dict(row, item=template[row["review_id"]],
                              answer=(calibration_set / "reviewer/answers" / (row["review_id"] + ".md")).read_text())
        return calibration_set, key, rows

    def reply(self, row, **options):
        return json.dumps({"reviews": [verdict(row["item"], row["answer"], **options)]})

    def run_judge(self, calibration_set, replies, output="run", config=None, **respond_options):
        """Queue replies by template position; a reply of None is an invalid attempt for both tries."""
        config = config or self.config
        for item in artifact_io.load_json(calibration_set / "reviewer/assessment-template.json")["reviews"]:
            reply = replies.get(item["review_id"])
            for text in ([reply] if reply is not None else ["I could not finish.", "Still unfinished."]):
                self.call += 1
                self.judge.respond(self.call, text, **respond_options)
        path = self.root / f"{output}-config.json"
        path.write_bytes(artifact_io.canonical(config))
        return self.cli("run", calibration_set, "--config", path, "--output", self.root / output)

    def test_judge_sees_one_answer_without_the_key_and_scores_follow_the_seeded_ground_truth(self):
        # Reversed plan order puts the unresolved answer first, so the others prove the run continues.
        with patch.object(judge_calibration.secrets.SystemRandom, "shuffle", lambda _, entries: entries.reverse()):
            calibration_set, key, rows = self.built()
        packet = artifact_io.load_json(calibration_set / "reviewer/packet.json")
        source = artifact_io.load_json(self.export / "reviewer/packet.json")
        source_seal = artifact_io.load_json(self.export / "seal.json")
        for field in ("task", "rubric", "rubric_sha256", "source_files"):
            self.assertEqual(packet[field], source[field])
        self.assertFalse({item["review_id"] for item in packet["items"]} & set(self.originals))
        self.assertEqual(set(rows), {"control-" + self.originals[0], "control-" + self.originals[1], *MUTANTS})
        reference = artifact_io.load_json(self.export / "reviews/reference.json")["assessment"]
        self.assertEqual(key["source"], {"export_id": source_seal["export_id"], "packet_sha256": source_seal["packet_sha256"],
                                         "coordinator_sha256": source_seal["coordinator_sha256"], "reference": "reference",
                                         "reference_assessment_sha256": artifact_io.digest(reference)})

        control, hedged = rows["control-" + self.originals[0]], rows["control-" + self.originals[1]]
        replies = {control["review_id"]: self.reply(control),
                   hedged["review_id"]: self.reply(hedged, met=None),
                   rows["criterion_removed"]["review_id"]: self.reply(rows["criterion_removed"], met=False),
                   rows["listed_false_claim"]["review_id"]: self.reply(rows["listed_false_claim"], claim=MATERIAL),
                   rows["novel_false_claim"]["review_id"]: self.reply(rows["novel_false_claim"], met=None),
                   # Caught through a material error on the true first sentence, not the overclaimed unknown.
                   rows["overclaimed_unknown"]["review_id"]: self.reply(rows["overclaimed_unknown"], claim=dict(
                       MATERIAL, quote=CLAIM, anchors=["src/service.py:2"])),
                   rows["fabricated_citation"]["review_id"]: None}
        code, out, err = self.run_judge(calibration_set, replies)
        self.assertEqual(code, 2, err)
        summary = artifact_io.load_json(self.root / "run/calibration-run.json")
        self.assertEqual((summary["answers"], summary["assessed_answers"], summary["error"]), (7, 6, None))
        self.assertIsNone(summary["items"][0]["review"])
        self.assertEqual(summary["items"][0]["review_id"], rows["fabricated_citation"]["review_id"])
        self.assertEqual(len(summary["items"][0]["attempts"]), 2)
        for call in self.judge.calls():
            files = set(call["files"])
            answer = next(name for name in files if name.startswith("answers/"))
            self.assertEqual(files - {answer}, {"packet.json", "assessment-template.json", "source/src/service.py",
                                                "source/docs/guide.md"})
            self.assertEqual(len(call["template"]["reviews"]), 1)

        code, out, err = self.cli("score", self.root / "run", "--output", self.root / "report.json")
        self.assertEqual(code, 0, err)
        report = artifact_io.load_json(self.root / "report.json")
        self.assertEqual(counts(report["sensitivity"]), {"resolved": (1, 2), "worst_case": (1, 2)})
        self.assertEqual(counts(report["specificity"]), {"resolved": (3, 4), "worst_case": (3, 5)})
        self.assertEqual(counts(report["located"]), {"resolved": (2, 4), "worst_case": (2, 5)})
        self.assertEqual(report["specificity"]["unresolved"], 1)
        self.assertAlmostEqual(report["youden_j"]["resolved"], 0.25)
        self.assertAlmostEqual(report["youden_j"]["worst_case"], 0.1)
        self.assertAlmostEqual(report["gwet_ac1"]["value"], 0.534, places=3)
        self.assertEqual((report["gwet_ac1"]["case_bootstrap_lower_95"], report["gwet_ac1"]["cases"]), (None, 1))
        by_defect = report["by_defect"]
        self.assertEqual(counts(by_defect["novel_false_claim"]), {"resolved": (0, 1), "worst_case": (0, 1)})
        self.assertEqual(counts(by_defect["overclaimed_unknown"]["located"]), {"resolved": (0, 1), "worst_case": (0, 1)})
        self.assertEqual(counts(by_defect["listed_false_claim"]["located"]), {"resolved": (1, 1), "worst_case": (1, 1)})
        self.assertEqual(by_defect["fabricated_citation"]["unresolved"], 1)
        self.assertEqual([run["assessed_answers"] for run in report["runs"]], [6])
        self.assertEqual(report["judge"]["attempts_per_answer"], 2)

        second, _, more = self.built("second", controls=[], defects=tuple(SECOND_SET), texts=SECOND_SET, file="second.json")
        replies = {row["review_id"]: self.reply(row) for row in more.values()}
        code, _, err = self.run_judge(second, replies, output="run-second")
        self.assertEqual(code, 0, err)
        code, _, err = self.cli("score", self.root / "run", self.root / "run-second", "--output", self.root / "both.json")
        self.assertEqual(code, 0, err)
        both = artifact_io.load_json(self.root / "both.json")
        self.assertEqual(counts(both["specificity"]), {"resolved": (3, 6), "worst_case": (3, 7)})
        self.assertEqual(len(both["runs"]), 2)

        other = dict(self.config, model="other-model")
        code, _, err = self.run_judge(second, replies, output="run-other", config=other,
                                      models=("other-model",), init={"model": "other-model"})
        self.assertEqual(code, 0, err)
        rebuilt, _, again = self.built("rebuilt", file="rebuilt.json")
        code, _, err = self.run_judge(rebuilt, {row["review_id"]: self.reply(row) for row in again.values()}, output="run-rebuilt")
        self.assertEqual(code, 0, err)
        tampered = self.root / "run-tampered"
        shutil.copytree(self.root / "run-second", tampered)
        (tampered / "calibration-run.json").chmod(0o600)
        altered = artifact_io.load_json(tampered / "calibration-run.json")
        altered["items"][0]["review"]["outcome"]["status"] = "unsatisfied"
        (tampered / "calibration-run.json").write_bytes(artifact_io.canonical(altered))
        for name, runs, error in (("same_run_twice", ("run", "run"), "calibration_identity"),
                                  ("other_judge_config", ("run", "run-other"), "calibration_identity"),
                                  ("same_answers_rebuilt", ("run", "run-rebuilt"), "calibration_identity"),
                                  ("altered_verdict", ("run-tampered",), "review_outcome")):
            with self.subTest(name):
                code, _, err = self.cli("score", *(self.root / run for run in runs), "--output", self.root / f"{name}.json")
                self.assertEqual((code, err.split(":")[0]), (2, error))
                self.assertFalse((self.root / f"{name}.json").exists())

    def test_an_interrupted_run_keeps_its_record_and_is_not_scored(self):
        calibration_set, _, rows = self.built()
        original = judge.assess

        def interrupt(root, config, key, output, position, *rest):
            if position == 3:
                raise KeyboardInterrupt
            return original(root, config, key, output, position, *rest)

        replies = {row["review_id"]: self.reply(row) for row in rows.values()}
        with patch.object(judge, "assess", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_judge(calibration_set, replies)
        summary = artifact_io.load_json(self.root / "run/calibration-run.json")
        self.assertEqual((summary["answers"], summary["assessed_answers"], len(summary["items"])), (7, 2, 3))
        self.assertEqual((summary["items"][2]["review"], summary["items"][2]["attempts"]), (None, []))
        self.assertEqual(summary["error"]["code"], "judge_error")
        code, _, err = self.cli("score", self.root / "run", "--output", self.root / "partial.json")
        self.assertEqual((code, err.split(":")[0]), (2, "calibration_run"))

    def test_the_judge_cannot_be_its_own_reference(self):
        calibration_set, _, _ = self.built()
        code, _, err = self.run_judge(calibration_set, {}, config=dict(self.config, reviewer="reference"))
        self.assertEqual((code, err.split(":")[0]), (2, "calibration_reference"))
        self.assertEqual(self.judge.calls(), [])

    def test_build_refuses_answers_that_do_not_carry_their_declared_defect(self):
        removed, listed = MUTANTS["criterion_removed"], MUTANTS["listed_false_claim"]
        cases = [
            ("passage_absent", {"listed_false_claim": (listed[0], listed[1], "value() calls a remote API.", listed[3])},
             "calibration_item"),
            ("passage_unchanged_from_original", {"listed_false_claim": (listed[0], listed[1], UNKNOWN, listed[3])},
             "calibration_item"),
            ("removed_passage_kept", {"criterion_removed": (ANSWER + " Nothing else.", *removed[1:])}, "calibration_item"),
            ("removed_passage_never_existed", {"criterion_removed": (removed[0], removed[1], "Nothing here.", [])},
             "calibration_item"),
            ("wrong_target_field", {"listed_false_claim": (listed[0], {"criterion_id": "value"}, *listed[2:])},
             "calibration_item"),
            ("unknown_criterion", {"criterion_removed": (removed[0], {"criterion_id": "nope"}, *removed[2:])},
             "calibration_item"),
            ("target_outside_key", {"listed_false_claim": (listed[0], {"false_claim_index": 3}, *listed[2:])},
             "calibration_item"),
            ("malformed_target", {"listed_false_claim": (listed[0], {"false_claim_index": [0]}, *listed[2:])},
             "calibration_mutations"),
            ("anchored_without_anchors", {"listed_false_claim": (*listed[:3], [])}, "calibration_item"),
            ("anchors_on_removal", {"criterion_removed": (*removed[:3], ["src/service.py:2"])}, "calibration_item"),
            ("anchor_outside_source", {"listed_false_claim": (*listed[:3], ["src/service.py:9"])}, "corpus_anchor_range"),
            ("empty_answer", {"listed_false_claim": ("", *listed[1:])}, "calibration_item"),
        ]
        for name, change, error in cases:
            with self.subTest(name), patch.dict(MUTANTS, change):
                defect = next(iter(change))
                code, _, err = self.build(name, defects=(defect,), file=f"{name}.json")
                self.assertEqual((code, err.split(":")[0]), (2, error))
                self.assertFalse((self.root / name).exists())
        for name, change, error in (
                ("control_not_satisfied", {"controls": [self.originals[2]]}, "calibration_reference"),
                ("mutant_of_unsatisfied", {"source": 2}, "calibration_reference"),
                ("missing_reference", {"reference": "nobody"}, "calibration_reference"),
                ("duplicate_control", {"controls": self.originals[:2] + self.originals[:1], "defects": ()},
                 "calibration_mutations"),
                ("single_answer", {"controls": [], "defects": ("criterion_removed",)}, "calibration_item")):
            with self.subTest(name):
                code, _, err = self.build(name, file=f"{name}.json", **change)
                self.assertEqual((code, err.split(":")[0]), (2, error))
        with self.subTest("identical_answers"):
            twin = (self.export / "reviewer/answers" / (self.originals[1] + ".md")).read_text()
            copied = {"novel_false_claim": (twin, {}, twin[twin.rindex(" Trial "):], ["src/service.py:2"])}
            code, _, err = self.build("identical_answers", file="identical.json", defects=("novel_false_claim",), texts=copied)
            self.assertEqual((code, err.split(":")[0]), (2, "calibration_item"))
        with self.subTest("malformed_control"):
            code, _, err = self.build("malformed_control", file="malformed_control.json", controls=["nope"])
            self.assertEqual(code, 2)
            self.assertNotIn("judge_error", err)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "m.md").write_text(MUTANTS["novel_false_claim"][0])
        (self.mutations / "link").symlink_to(outside)
        path = self.plan(defects=("novel_false_claim",), file="link.json")
        plan = artifact_io.load_json(path)
        plan["mutants"][0]["answer"] = "link/m.md"
        path.write_bytes(artifact_io.canonical(plan))
        code, _, err = self.cli("build", self.export, "--mutations", path, "--output", self.root / "linked")
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "linked").exists())
        code, _, err = self.cli("build", self.export, "--mutations", self.plan(), "--output", self.export / "inside")
        self.assertEqual((code, err.split(":")[0]), (2, "review_path"))

    def test_a_changed_key_or_answer_invalidates_the_set(self):
        calibration_set, key, _ = self.built()
        answer = next((calibration_set / "reviewer/answers").iterdir())

        def resealed(items):
            body = encoded(dict(key, items=items))
            seal = artifact_io.load_json(calibration_set / "seal.json")
            return {"key.json": body, "seal.json": encoded(dict(seal, key_sha256=sha(body)))}

        retargeted = [dict(row, target={"criterion_id": "nope"}) if row["defect"] == "criterion_removed" else row
                      for row in key["items"]]
        for name, changes, errors in (
                ("unresealed_key", {"key.json": (calibration_set / "key.json").read_bytes() + b" "}, {"calibration_identity"}),
                ("answer", {str(answer.relative_to(calibration_set)): answer.read_bytes() + b" "}, {"review_answer"}),
                ("resealed_missing_item", resealed(key["items"][1:]), {"calibration_identity"}),
                ("resealed_retarget", resealed(retargeted), {"calibration_item"})):
            with self.subTest(name):
                originals = {}
                for relative, body in changes.items():
                    path = calibration_set / relative
                    originals[path] = path.read_bytes()
                    path.chmod(0o600)
                    path.write_bytes(body)
                with self.assertRaises(artifact_io.BenchmarkError) as raised, Root(calibration_set) as root:
                    judge_calibration.load_set(root)
                self.assertIn(raised.exception.code, errors)
                for path, body in originals.items():
                    path.write_bytes(body)

    def test_case_bootstrap_bounds_only_enough_cases(self):
        report = judge_calibration.summarize(rows_for(6, bad={0}))
        bound, value = report["gwet_ac1"]["case_bootstrap_lower_95"], report["gwet_ac1"]["value"]
        self.assertEqual(report["gwet_ac1"]["cases"], 6)
        self.assertLess(bound, value)
        self.assertGreater(bound, judge_calibration.gwet_ac1([(row["judged"], row["expected"]) for row in rows_for(1, bad={0})]))
        few = judge_calibration.summarize(rows_for(4, bad={0}))["gwet_ac1"]
        self.assertEqual((few["case_bootstrap_lower_95"], few["cases"], few["minimum_cases_for_bound"]), (None, 4, 5))


if __name__ == "__main__":
    unittest.main()
