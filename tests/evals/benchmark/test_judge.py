"""The judge sees one answer per call, retains every attempt and imports one complete assessment."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from evals.benchmark import artifacts as artifact_io
from evals.benchmark import judge, review
from tests.evals.support.judge import CANARIES, JudgeFixture
from tests.evals.support.review import completed_assessment


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.judge = JudgeFixture("Observed src/service.py:2. It\u2019s fixed. It\u2018s set.")
        self.addCleanup(self.judge.close)
        for name in ("case", "fixture", "root", "export", "template", "state", "instruction", "config"):
            setattr(self, name, getattr(self.judge, name))
        self.output = self.root / "judge-run"

    def make_export(self, name, rubric, corpus_case=None):
        return self.judge.export_batch(name, rubric, corpus_case)

    def respond(self, call, text, **options):
        self.judge.respond(call, text, **options)

    def review(self, position, **change):
        """A completed reply for the answer at this template position (1-based)."""
        row = completed_assessment(self.export, "judge")["reviews"][position - 1]
        row["claims"][0].update(change)
        return json.dumps({"reviews": [row]})

    def review_with_quote(self, position, quote):
        reply = json.loads(self.review(position))
        reply["reviews"][0]["claims"].append({"quote": quote, "support": "unknown", "anchors": [],
                                              "material_error": False, "rationale": "Not checkable from source."})
        reply["reviews"][0]["knowns"][0]["answer_excerpt"] = quote
        return json.dumps(reply)

    def respond_valid(self, first_call, positions):
        for offset, position in enumerate(positions):
            self.respond(first_call + offset, self.review(position))

    def calls(self):
        return self.judge.calls()

    def main(self, config=None, output=None, export=None, key="fixture-key"):
        path = self.root / "judge-config.json"
        path.write_bytes(artifact_io.canonical(self.config if config is None else config))
        environment = dict(CANARIES, ANTHROPIC_API_KEY=key) if key else dict(CANARIES)
        with patch.dict(os.environ, environment, clear=True), redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = judge.main([str(export or self.export), "--config", str(path),
                               "--output", str(output or self.output)])
        return code, out.getvalue(), err.getvalue()

    def assert_retained(self, summary, output=None):
        output = output or self.output
        self.assertEqual(artifact_io.load_json(output / "judge-run.json"), summary)
        audit = summary["binding_audit"]
        if audit is not None:
            self.assertEqual(Path(audit["path"]), output / "binding-audit.json")
            self.assertEqual(hashlib.sha256(Path(audit["path"]).read_bytes()).hexdigest(), audit["sha256"])
        for record in summary["attempts"]:
            self.assertEqual(artifact_io.load_json(output / f"{record['name']}.json"), record)
            stdout = (output / f"{record['name']}.stdout").read_bytes()
            self.assertEqual(hashlib.sha256(stdout).hexdigest(), record["stdout_sha256"])
            self.assertTrue((output / f"{record['name']}.stderr").is_file())

    def test_retries_one_answer_and_imports_the_complete_assessment(self):
        self.respond(1, self.review(1, quote="A sentence the answer never wrote."))
        self.respond(2, "```json\n" + self.review(1) + "\n```\nDone; the {reviews} field above holds one review.")
        self.respond_valid(3, (2, 3))
        code, out, err = self.main()
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        items = self.template["reviews"]
        self.assertEqual([(row["review_id"], row["status"]) for row in summary["attempts"]],
                         [(items[0]["review_id"], "invalid")] + [(item["review_id"], "valid") for item in items])
        self.assertEqual(summary["attempts"][0]["error"]["code"], "review_quote")
        self.assertEqual((summary["answers"], summary["assessed_answers"], summary["error"]), (3, 3, None))
        self.assert_retained(summary)
        audit = artifact_io.load_json(Path(summary["binding_audit"]["path"]))
        self.assertEqual(audit["summary"]["claims"], {"valid": 0, "invalid": 0, "unverifiable": 3})
        self.assertEqual(review.review_status(self.export)["reviewers"], [{"reviewer": "judge", "reviewed": 3}])
        recorded = artifact_io.load_json(self.output / "judge.json")
        self.assertEqual(recorded["instruction_sha256"], hashlib.sha256(self.instruction.read_bytes()).hexdigest())
        self.assertEqual(recorded["prompt_sha256"], hashlib.sha256(judge.PROMPT).hexdigest())
        reviewer = self.export / "reviewer"
        verified = {str(path.relative_to(reviewer)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in reviewer.rglob("*") if path.is_file() and path.parent.name != "answers"
                    and path.name != "assessment-template.json"}
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual(len({call["cwd"] for call in calls}), 4)
        self.assertEqual(len({call["home"] for call in calls}), 4)
        for call, item in zip(calls, [items[0], *items]):
            answer = f"answers/{item['review_id']}.md"
            files = dict(call["files"])
            self.assertEqual(files.pop(answer), hashlib.sha256((reviewer / answer).read_bytes()).hexdigest())
            files.pop("assessment-template.json")
            self.assertEqual(files, verified)
            self.assertEqual(call["template"], dict(self.template, reviews=[item]))
            argv = call["argv"]
            self.assertEqual(call["stdin"], judge.PROMPT.decode())
            self.assertEqual(Path(call["home"]).parent, Path(call["cwd"]).parent)
            self.assertEqual(call["key"], "fixture-key")
            self.assertIsNone(call["base_url"])
            self.assertEqual(call["disabled"], ["1", "1"])
            self.assertFalse(set(CANARIES) & set(call["environment"]))
            self.assertIn("--bare", argv)
            self.assertIn("--strict-mcp-config", argv)
            self.assertNotIn("--allowedTools", argv)
            for option, value in (("--tools", "Read"), ("--permission-mode", "dontAsk"), ("--setting-sources", ""),
                                  ("--output-format", "stream-json"), ("--system-prompt", "Assess the answers.\n")):
                self.assertEqual(argv[argv.index(option) + 1], value)

    def test_source_quotes_are_audited_without_repairing_declarations_or_changing_grades(self):
        packet = artifact_io.load_json(self.export / "reviewer/packet.json")
        source = next(row for row in packet["source_files"] if row["path"] == "src/service.py")
        declared = []
        for position, quote in ((1, "    return 7\n"), (2, "def value():\n"), (3, None)):
            options = {} if quote is None else {"source_quotes": [{"anchor": "src/service.py:2",
                "source_sha256": source["sha256"], "quote": quote}]}
            reply = self.review(position, **options)
            declared.append(json.loads(reply)["reviews"][0])
            self.respond(position, reply)
        code, out, err = self.main()
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assert_retained(summary)
        receipt = artifact_io.load_json(Path(summary["receipt"]))
        self.assertEqual(receipt["assessment"]["reviews"], declared)
        audit = artifact_io.load_json(Path(summary["binding_audit"]["path"]))
        self.assertEqual(audit["summary"]["claims"], {"valid": 1, "invalid": 1, "unverifiable": 1})
        self.assertEqual(audit["summary"]["anchors"], {"valid": 1, "invalid": 1, "unverifiable": 1})
        self.assertEqual(audit["assessments"][0]["assessment_sha256"], receipt["assessment_sha256"])
        claims = [row["claims"][0] for row in audit["assessments"][0]["reviews"]]
        self.assertEqual([(row["status"], row["anchors"][0]["reason"]) for row in claims],
                         [("valid", "quote_bound"), ("invalid", "source_quote_outside_span"),
                          ("unverifiable", "source_quote_missing")])
        self.assertFalse(audit["comparison_accepted"])
        self.assertIsNone(audit["quality_uplift"])

    def test_failed_post_import_audit_keeps_the_receipt_and_can_be_recovered_without_model_calls(self):
        self.respond_valid(1, (1, 2, 3))
        with patch.object(review, "audit_bindings",
                          side_effect=artifact_io.BenchmarkError("review_path", "audit publication failed")):
            code, _, err = self.main()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("review_path:"), err)
        summary_path = self.output / "judge-run.json"
        summary_body = summary_path.read_bytes()
        summary = artifact_io.load_json(summary_path)
        self.assertEqual(summary["error"]["code"], "review_path")
        self.assertIsNone(summary["binding_audit"])
        receipt = Path(summary["receipt"])
        receipt_body = receipt.read_bytes()
        self.assertEqual(review.review_status(self.export)["reviewers"], [{"reviewer": "judge", "reviewed": 3}])
        self.assertEqual(artifact_io.load_json(receipt)["assessment"],
                         artifact_io.load_json(self.output / "assessment.json"))
        recovered = review.audit_bindings(self.export, self.output / "binding-audit-recovery.json")
        self.assertEqual(artifact_io.load_json(recovered)["summary"]["claims"]["unverifiable"], 3)
        self.assertEqual(summary_path.read_bytes(), summary_body)
        self.assertEqual(receipt.read_bytes(), receipt_body)
        retry, _, err = self.main(output=self.root / "another-judge-run")
        self.assertEqual(retry, 2)
        self.assertTrue(err.startswith("review_exists:"), err)
        self.assertEqual(len(self.calls()), 3)

    def test_typographic_retyping_is_repaired_only_to_a_unique_exact_span(self):
        self.respond(1, self.review_with_quote(1, "It's "))
        self.respond(2, self.review_with_quote(1, "It's fixed."))
        self.respond_valid(3, (2, 3))
        code, out, err = self.main()
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual([(row["status"], row["quotes_repaired"]) for row in summary["attempts"][:2]],
                         [("invalid", 0), ("valid", 2)])
        self.assertEqual(summary["attempts"][0]["error"]["code"], "review_quote")
        stored = artifact_io.load_json(Path(summary["receipt"]))["assessment"]["reviews"][0]
        self.assertEqual(stored["claims"][-1]["quote"], "It\u2019s fixed.")
        self.assertEqual(stored["knowns"][0]["answer_excerpt"], "It\u2019s fixed.")

    def test_an_answer_without_a_valid_review_stops_the_run_unresolved(self):
        self.respond(1, "I could not finish the review.")
        self.respond(2, json.dumps({"reviews": [json.loads(self.review(1))["reviews"][0]] * 2}))
        self.respond(3, self.review(2))
        code, out, err = self.main()
        self.assertEqual(code, 2, err)
        summary = json.loads(out)
        self.assertIsNone(summary["receipt"])
        self.assertIsNone(summary["binding_audit"])
        self.assertEqual(summary["assessed_answers"], 0)
        self.assertEqual([row["error"]["code"] for row in summary["attempts"]],
                         ["judge_output_invalid", "judge_output_invalid", "review_inventory"])
        self.assertEqual(len(self.calls()), 3)
        self.assert_retained(summary)
        self.assertFalse((self.output / "assessment.json").exists())
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_each_runtime_field_outside_the_contract_rejects_the_attempt(self):
        for call, (change, code) in enumerate((
                ({"init": {"tools": ["Read", "Bash"]}}, "judge_runtime_mismatch"),
                ({"init": {"cwd": "/elsewhere"}}, "judge_runtime_mismatch"),
                ({"init": {"mcp_servers": [{"name": "extra", "status": "connected"}]}}, "judge_runtime_mismatch"),
                ({"init": {"permissionMode": "default"}}, "judge_runtime_mismatch"),
                ({"init": {"claude_code_version": "fake-v2"}}, "judge_runtime_mismatch"),
                ({"init": {"model": "another-model"}}, "judge_model_mismatch"),
                ({"models": ("judge-model", "another-model")}, "judge_model_mismatch")), start=1):
            with self.subTest(change=change):
                self.respond(call, self.review(1), **change)
                status, out, err = self.main(dict(self.config, attempts=1), output=self.root / f"judge-run-{call}")
                self.assertEqual(status, 2, err)
                record = json.loads(out)["attempts"][0]
                self.assertEqual(record["error"]["code"], code)
        self.assertEqual(record["observed"]["models_used"], ["another-model", "judge-model"])
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_cli_failures_and_error_results_are_rejected_attempts(self):
        self.respond(1, self.review(1), mode="block")
        self.respond(2, self.review(1), mode="flood")
        self.respond(3, self.review(1), mode="exit")
        with patch.object(judge, "STDOUT_LIMIT", 4096):
            code, out, err = self.main(dict(self.config, timeout_seconds=1))
        self.assertEqual(code, 2, err)
        attempts = json.loads(out)["attempts"]
        self.assertEqual([(row["stop_reason"], row["error"]["code"]) for row in attempts],
                         [("timeout", "judge_cli_error"), ("output_limit", "judge_cli_error"), (None, "judge_cli_error")])
        self.assertEqual(attempts[2]["returncode"], 3)
        for call, change in ((4, {"is_error": True}), (5, {"subtype": "error_max_turns"})):
            with self.subTest(change=change):
                self.respond(call, self.review(1), **change)
                code, out, err = self.main(dict(self.config, attempts=1), output=self.root / f"judge-run-{call}")
                self.assertEqual(code, 2, err)
                self.assertEqual(json.loads(out)["attempts"][0]["error"]["code"], "judge_cli_error")
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_configured_endpoint_reaches_the_cli_and_its_provenance(self):
        endpoint = "https://judge.example.invalid/api/anthropic"
        self.respond_valid(1, (1, 2, 3))
        code, _, err = self.main(dict(self.config, base_url=endpoint))
        self.assertEqual(code, 0, err)
        self.assertEqual({call["base_url"] for call in self.calls()}, {endpoint})
        self.assertEqual(artifact_io.load_json(self.output / "judge.json")["base_url"], endpoint)

    def test_another_reviewer_import_does_not_discard_a_valid_assessment(self):
        alice = self.root / "alice.json"
        alice.write_bytes(artifact_io.canonical(completed_assessment(self.export, "alice")))
        original = judge.run_bounded
        imported = []

        def run_with_concurrent_import(command, **options):
            if "--version" not in command and not imported:
                imported.append(review.import_assessment(self.export, alice))
            return original(command, **options)

        self.respond_valid(1, (1, 2, 3))
        with patch.object(judge, "run_bounded", side_effect=run_with_concurrent_import):
            code, out, err = self.main()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(row["reviewer"] for row in review.review_status(self.export)["reviewers"]),
                         ["alice", "judge"])

    def test_failed_import_keeps_the_run_summary(self):
        self.respond_valid(1, (1, 2, 3))
        with patch.object(review, "import_assessment", side_effect=artifact_io.BenchmarkError("review_busy", "busy")):
            code, out, err = self.main()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("review_busy:"), err)
        summary = artifact_io.load_json(self.output / "judge-run.json")
        self.assertEqual(summary["error"]["code"], "review_busy")
        self.assertIsNone(summary["receipt"])
        self.assertEqual(summary["assessed_answers"], 3)
        self.assertTrue((self.output / "assessment.json").is_file())

    def test_refuses_before_any_model_call(self):
        existing = self.root / "existing.json"
        existing.write_bytes(artifact_io.canonical(completed_assessment(self.export, "judge")))
        calibration = dict(self.case.key, status="calibration_key_source_reviewed")
        calibration.pop("acceptance_criteria")
        legacy = self.make_export("legacy-export", calibration)
        cases = [("missing_key", {"key": None}, "anthropic_api_key_missing"),
                 ("output_in_export", {"output": self.export / "judge-run"}, "review_path"),
                 ("no_acceptance_criteria", {"export": legacy}, "judge_schema"),
                 ("version_mismatch", {"config": dict(self.config, cli=dict(self.config["cli"], version="fake-v2"))},
                  "claude_cli_version_mismatch"),
                 ("extra_field", {"config": dict(self.config, effort="max")}, "judge_config")]
        for field, value in (("attempts", 4), ("attempts", 0), ("attempts", True), ("timeout_seconds", 0),
                             ("timeout_seconds", 7201), ("timeout_seconds", True), ("reviewer", "Judge"), ("model", ""),
                             ("base_url", "http://judge.invalid"), ("base_url", "https://judge invalid")):
            cases.append((f"{field}={value!r}", {"config": dict(self.config, **{field: value})}, "judge_config"))
        cases.append(("reviewer_exists", {}, "review_exists"))
        for name, change, code in cases:
            with self.subTest(name=name):
                if name == "reviewer_exists":
                    review.import_assessment(self.export, existing)
                status, _, err = self.main(**change)
                self.assertEqual(status, 2)
                self.assertTrue(err.startswith(code + ":"), err)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
