"""Producer audits use sealed answers and never rewrite reviewer receipts."""

import os
import shutil
import subprocess
import sys
import unittest

from evals.benchmark import artifacts, review, trials
from tests.evals.support.corpus import CorpusFixture
from tests.evals.support.review import completed_assessment


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class ProducerBindingReviewTests(unittest.TestCase):
    def test_cli_audits_sealed_answers_without_model_or_grade_changes(self):
        case = CorpusFixture()
        self.addCleanup(case.close)
        fixture = case.fixture
        answer = ("service.py:2\n  ```python\n      return 7\n  ```\n\n"
                  "Another citation: src/service.py:1\n```python\n    return 7\n```\n\n"
                  "Documentation: docs/guide.md:1.\n")
        fixture.adapter("init()\nfinal(" + repr(answer) + ")\n")
        batch = trials.prepare_batch(task=case.task, rubric=case.key,
            config=fixture.config, source_repo=fixture.repo, tool_repo=fixture.repo,
            output=fixture.root / "batches", repetitions=1)
        for item in artifacts.load_json(batch / "batch.json")["trials"]:
            trials.run_trial(batch / item["directory"])
        export = review.export_review(batch, fixture.root / "review-export")
        assessment = completed_assessment(export)
        for item in assessment["reviews"]:
            item["claims"][0]["quote"] = "service.py:2"
            item["knowns"][0]["answer_excerpt"] = "service.py:2"
        submitted = fixture.root / "assessment.json"
        submitted.write_bytes(artifacts.canonical(assessment))
        receipt = review.import_assessment(export, submitted)
        receipt_before = receipt.read_bytes()
        status_before = review.review_status(export)
        first, second = fixture.root / "producer-audit.json", fixture.root / "producer-audit-cli.json"
        self.assertEqual(review.audit_producer_bindings(export, first), first)
        report = artifacts.load_json(first)
        self.assertEqual(report["summary"], {"answers": 3, "answers_without_citations": 0,
                                           "citations": {"valid": 3, "invalid": 3, "unverifiable": 3}})
        self.assertFalse(report["comparison_accepted"])
        self.assertIsNone(report["quality_uplift"])
        command = [sys.executable, "-m", "evals.benchmark.review", "audit-producer-bindings",
                   str(export), "--output", str(second)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, PATH=""))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(artifacts.load_json(second), report)
        self.assertEqual(receipt.read_bytes(), receipt_before)
        self.assertEqual(review.review_status(export), status_before)
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, PATH=""))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(artifacts.load_json(second), report)
        with self.assertRaises(artifacts.BenchmarkError):
            review.audit_producer_bindings(export, export / "producer-audit.json")
        source = export / "reviewer/source/src/service.py"
        source.chmod(0o600)
        source.write_bytes(b"def value():\n    return 9\n")
        failed = fixture.root / "changed-source-audit.json"
        with self.assertRaises(artifacts.BenchmarkError) as raised:
            review.audit_producer_bindings(export, failed)
        self.assertEqual(raised.exception.code, "review_source")
        self.assertFalse(failed.exists())
        self.assertEqual(receipt.read_bytes(), receipt_before)


if __name__ == "__main__":
    unittest.main()
