"""Literal source bindings without converting evidence integrity into acceptance."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

from evals.benchmark import artifacts as artifact_io
from evals.benchmark import evidence_binding
from evals.benchmark import review
from evals.benchmark import trials as trial_runner
from tests.evals.support.corpus import CorpusFixture
from tests.evals.support.review import completed_assessment


class EvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.path = "src/service.py"
        self.body = b"def value():\n    return 7\n"
        self.sources = {self.path: self.record(self.body)}
        self.bodies = {self.path: self.body}

    def record(self, body):
        return {"path": self.path, "git_mode": "100644", "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "lines": body.count(b"\n") + int(bool(body) and not body.endswith(b"\n"))}

    def claim(self, anchor="src/service.py:2", quote="    return 7\n"):
        return {"quote": "The function performs network I/O.", "support": "contradicted",
                "anchors": [anchor], "material_error": True,
                "rationale": "The reviewer declares a false conclusion.",
                "source_quotes": [{"anchor": anchor, "source_sha256": self.sources[self.path]["sha256"],
                                   "quote": quote}]}

    def audit(self, *claims):
        assessments = [{"reviewer": "fixture", "reviews": [
            {"review_id": "review-" + "1" * 32, "answer_sha256": "2" * 64,
             "claims": list(claims), "outcome": {"status": "unsatisfied"}}]}]
        report = evidence_binding.audit(assessments, self.sources, self.bodies)
        return report, report["assessments"][0]["reviews"][0]["claims"]

    def test_correct_binding_remains_valid_for_a_semantically_false_claim(self):
        claim = self.claim()
        original = copy.deepcopy(claim)
        report, claims = self.audit(claim)
        self.assertEqual(claims[0]["status"], "valid")
        anchor = claims[0]["anchors"][0]
        self.assertEqual(anchor["reason"], "quote_bound")
        self.assertEqual(anchor["source_sha256"], hashlib.sha256(self.body).hexdigest())
        self.assertEqual(anchor["quote_sha256"], hashlib.sha256(b"    return 7\n").hexdigest())
        self.assertEqual(report["summary"]["claims"], {"valid": 1, "invalid": 0, "unverifiable": 0})
        self.assertEqual(claim, original)
        self.assertEqual(claim["support"], "contradicted")
        self.assertTrue(claim["material_error"])

    def test_quote_at_shifted_line_is_invalid_even_when_it_exists_elsewhere(self):
        _, claims = self.audit(self.claim(anchor="src/service.py:1"))
        self.assertEqual(claims[0]["status"], "invalid")
        self.assertEqual(claims[0]["anchors"][0]["reason"], "source_quote_outside_span")

    def test_declared_digest_and_retained_snapshot_mismatches_are_distinct(self):
        stale = self.claim()
        stale["source_quotes"][0]["source_sha256"] = "0" * 64
        _, claims = self.audit(stale)
        self.assertEqual(claims[0]["anchors"][0]["reason"], "source_digest_mismatch")
        self.assertEqual(claims[0]["status"], "invalid")
        self.bodies[self.path] = self.body.replace(b"7", b"9")
        _, claims = self.audit(self.claim())
        self.assertEqual(claims[0]["anchors"][0]["reason"], "source_snapshot_mismatch")
        self.assertEqual(claims[0]["status"], "invalid")

    def test_legacy_missing_and_unavailable_evidence_remain_unverifiable(self):
        legacy = self.claim()
        del legacy["source_quotes"]
        no_anchor = copy.deepcopy(legacy)
        no_anchor["anchors"] = []
        report, claims = self.audit(legacy, no_anchor)
        self.assertEqual([claim["status"] for claim in claims], ["unverifiable"] * 2)
        self.assertEqual(claims[0]["anchors"][0]["reason"], "source_quote_missing")
        self.assertEqual(claims[1]["anchors"], [])
        self.assertEqual(report["summary"]["anchors"], {"valid": 0, "invalid": 0, "unverifiable": 1})
        self.bodies = {}
        _, claims = self.audit(self.claim())
        self.assertEqual(claims[0]["status"], "unverifiable")
        self.assertEqual(claims[0]["anchors"][0]["reason"], "source_unavailable")

    def test_line_spans_preserve_crlf_unicode_whitespace_and_unterminated_last_line(self):
        self.body = "header\r\n\tλ = 'é'  \r\nlast\u2028tail".encode()
        self.sources[self.path] = self.record(self.body)
        self.bodies[self.path] = self.body
        exact = self.claim(anchor="src/service.py:2-3", quote="\tλ = 'é'  \r\nlast\u2028tail")
        normalized = self.claim(anchor="src/service.py:2", quote="\tλ = 'é'  \n")
        altered = self.claim(anchor="src/service.py:2", quote=" λ = 'é'  \r\n")
        _, claims = self.audit(exact, normalized, altered)
        self.assertEqual([claim["status"] for claim in claims], ["valid", "invalid", "invalid"])
        self.assertEqual(claims[1]["anchors"][0]["reason"], "source_quote_outside_span")
        self.assertEqual(claims[2]["anchors"][0]["reason"], "source_quote_outside_span")

    def test_invalid_anchor_dominates_missing_quote_in_claim_status(self):
        claim = self.claim(anchor="src/service.py:1")
        claim["anchors"].append("src/service.py:2")
        report, claims = self.audit(claim)
        self.assertEqual(claims[0]["status"], "invalid")
        self.assertEqual([anchor["status"] for anchor in claims[0]["anchors"]],
                         ["invalid", "unverifiable"])
        self.assertEqual(report["summary"]["anchors"], {"valid": 0, "invalid": 1, "unverifiable": 1})

    def test_anchor_syntax_scope_and_range_fail_with_corpus_reason(self):
        for anchor, code in (("src/service.py:0", "corpus_anchor_invalid"),
                             ("private.py:1", "corpus_anchor_scope"),
                             ("src/service.py:3", "corpus_anchor_range")):
            with self.subTest(anchor=anchor):
                _, claims = self.audit(self.claim(anchor=anchor))
                self.assertEqual(claims[0]["status"], "invalid")
                self.assertEqual(claims[0]["anchors"][0]["reason"], code)

    def test_source_quote_schema_rejects_duplicate_foreign_unbounded_and_mistyped_entries(self):
        valid = self.claim()
        source_quote = valid["source_quotes"][0]
        cases = [
            ("duplicate", [source_quote, copy.deepcopy(source_quote)]),
            ("foreign", [dict(source_quote, anchor="src/service.py:1")]),
            ("blank", [dict(source_quote, quote=" " * 4)]),
            ("oversize", [dict(source_quote, quote="x" * (64 * 1024))]),
            ("digest", [dict(source_quote, source_sha256="invalid")]),
            ("quote_type", [dict(source_quote, quote=7)]),
            ("anchor_type", [dict(source_quote, anchor=2)]),
            ("unexpected_field", [dict(source_quote, extra=True)]),
            ("entry_type", [None]),
            ("list_type", "not-a-list"),
        ]
        for name, quotes in cases:
            with self.subTest(boundary=name):
                claim = copy.deepcopy(valid)
                claim["source_quotes"] = quotes
                with self.assertRaises(artifact_io.BenchmarkError):
                    evidence_binding.validate_source_quotes(claim)
        claim = copy.deepcopy(valid)
        claim["anchors"] = [f"src/service.py:{number}" for number in range(1, 18)]
        claim["source_quotes"] = [dict(source_quote, anchor=anchor) for anchor in claim["anchors"]]
        with self.assertRaises(artifact_io.BenchmarkError):
            evidence_binding.validate_source_quotes(claim)


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class EvidenceBindingIntegrationTests(unittest.TestCase):
    def test_real_import_and_cli_publish_bound_reports_without_rewriting_reviews(self):
        case = CorpusFixture()
        self.addCleanup(case.close)
        fixture = case.fixture
        batch = trial_runner.prepare_batch(task=case.task, rubric=case.key,
            config=fixture.config, source_repo=fixture.repo, tool_repo=fixture.repo,
            output=fixture.root / "batches", repetitions=1)
        for item in artifact_io.load_json(batch / "batch.json")["trials"]:
            trial_runner.run_trial(batch / item["directory"])
        export = review.export_review(batch, fixture.root / "review-export")
        pending_output = fixture.root / "pending-binding-report.json"
        review.audit_bindings(export, pending_output)
        pending = artifact_io.load_json(pending_output)
        self.assertEqual(pending["answers_without_assessment"], 3)
        self.assertEqual(pending["summary"]["claims"], dict.fromkeys(evidence_binding.STATUSES, 0))
        value = completed_assessment(export)
        packet = artifact_io.load_json(export / "reviewer/packet.json")
        source_digest = next(row["sha256"] for row in packet["source_files"]
                             if row["path"] == "src/service.py")
        for item in value["reviews"]:
            item["claims"][0]["source_quotes"] = [{"anchor": "src/service.py:2",
                "source_sha256": source_digest, "quote": "    return 7\n"}]
        value["reviews"][-1]["claims"][0]["source_quotes"][0]["quote"] = "    return 99\n"
        submission = fixture.root / "assessment.json"
        submission.write_bytes(artifact_io.canonical(value))
        review.import_assessment(export, submission)
        receipt = export / "reviews/alice.json"
        original_receipt = receipt.read_bytes()
        output = fixture.root / "binding-report.json"
        self.assertEqual(review.audit_bindings(export, output), output)
        report = artifact_io.load_json(output)
        self.assertEqual(report["summary"]["claims"], {"valid": 2, "invalid": 1, "unverifiable": 0})
        self.assertEqual(report["attempts"]["planned"], 3)
        self.assertEqual(report["answers_without_assessment"], 0)
        self.assertFalse(report["comparison_accepted"])
        self.assertIsNone(report["quality_uplift"])
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertEqual(json.loads(original_receipt)["assessment"], value)
        with self.assertRaises(artifact_io.BenchmarkError) as raised:
            review.audit_bindings(export, export / "binding-report.json")
        self.assertEqual(raised.exception.code, "review_path")
        self.assertFalse((export / "binding-report.json").exists())
        second = fixture.root / "cli-binding-report.json"
        command = [sys.executable, "-m", "evals.benchmark.review", "audit-bindings", str(export),
                   "--output", str(second)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, PATH=""))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(artifact_io.load_json(second), report)
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, PATH=""))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(artifact_io.load_json(second), report)
        source = export / "reviewer/source/src/service.py"
        source.chmod(0o600)
        source.write_bytes(b"def value():\n    return 9\n")
        failed_output = fixture.root / "mutated-binding-report.json"
        with self.assertRaises(artifact_io.BenchmarkError) as raised:
            review.audit_bindings(export, failed_output)
        self.assertEqual(raised.exception.code, "review_source")
        self.assertFalse(failed_output.exists())
        self.assertEqual(receipt.read_bytes(), original_receipt)


if __name__ == "__main__":
    unittest.main()
