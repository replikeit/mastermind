"""Sparse relevance measurements distinguish missing, unjudged and negative results."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals.benchmark import concept_relevance


class ConceptRelevanceTests(unittest.TestCase):
    def test_sparse_judgments_do_not_turn_unlabeled_rows_into_failures(self):
        case = {"id": "source", "split": "independent", "kind": "positive", "query": "source receipt",
                "top": 5, "relevant": [{"path": "src/source.rs", "symbol": "receipt"},
                                        {"path": "src/source.rs", "symbol": "verify"}],
                "distractors": [{"path": "src/other.rs", "symbol": "receipt"}]}
        response = {"candidates": [{"path": "src/unlabeled.rs", "name": "receipt"},
                                   {"path": "src/source.rs", "name": "receipt"},
                                   {"path": "src/other.rs", "name": "receipt"}]}
        scored = concept_relevance.score_case(case, response)
        self.assertEqual((scored["first_relevant_rank"], scored["anchor_recall"]), (2, .5))
        self.assertEqual((scored["judged_precision"], scored["unjudged_rows"]), (.5, 1))

    def test_sparse_fixture_can_omit_distractor_labels(self):
        case = {"id": "sparse", "split": "independent", "kind": "positive", "query": "read source",
                "top": 5, "relevant": [{"path": "source.py", "symbol": "read"}]}
        result = concept_relevance.score_case(case, {"candidates": [
            {"path": "source.py", "name": "read"}, {"path": "other.py", "name": "read"}]})
        self.assertEqual((result["anchors_found"], result["judged_rows"], result["unjudged_rows"]), (1, 1, 1))

    def test_empty_negative_and_failed_queries_preserve_their_distinct_denominators(self):
        positive = {"id": "hit", "split": "independent", "kind": "positive", "query": "receipt",
                    "top": 5, "relevant": [{"path": "src/receipt.rs", "symbol": "verify"}], "distractors": []}
        hit = concept_relevance.score_case(positive, {"candidates": [{"path": "src/receipt.rs", "name": "verify"}]})
        empty = concept_relevance.score_case({**positive, "id": "empty"}, {"candidates": []})
        negative = concept_relevance.score_case({**positive, "id": "negative", "kind": "negative", "relevant": []},
                                                {"candidates": [{"path": "src/receipt.rs", "name": "verify"}]})
        failed = {"id": "failed", "split": "independent", "kind": "positive", "status": "failed"}
        summary = concept_relevance.summarize([hit, empty, negative, failed])["independent"]
        self.assertEqual((summary["planned_cases"], summary["failed_cases"], summary["positive_queries"]), (4, 1, 3))
        self.assertIsNone(summary["hit_at_k"])
        self.assertEqual(summary["hit_at_k_bounds"], [1 / 3, 2 / 3])
        self.assertEqual((summary["negative_queries_with_candidates"], summary["negative_returned_rows"]), (1, 1))

    def test_conflicting_judgments_and_oversized_pages_fail_visibly(self):
        anchor = {"path": "src/source.rs", "symbol": "read"}
        case = {"id": "source", "split": "development", "kind": "positive", "query": "source", "top": 1,
                "relevant": [anchor], "distractors": [anchor]}
        with self.assertRaisesRegex(ValueError, "conflicting"):
            concept_relevance.score_case(case, {"candidates": []})
        with self.assertRaisesRegex(ValueError, "bounded"):
            concept_relevance.score_case({**case, "distractors": []}, {"candidates": [anchor, anchor]})

    def test_changed_fixture_or_wal_cannot_be_bound_to_an_earlier_query(self):
        for changed in ("suite", "wal"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                source.mkdir()
                (source / "service.py").write_text("def service(): pass\n")
                binary, index, suite = root / "mmcg", root / "index.db", root / "suite.json"
                binary.write_text("compiled binary placeholder")
                index.write_bytes(b"index fixture")
                suite.write_text(json.dumps({"schema_version": 1, "source_head": "fixture",
                    "source_files_sha256": {"service.py": hashlib.sha256((source / "service.py").read_bytes()).hexdigest()},
                    "cases": [{"id": "source", "split": "independent", "kind": "positive", "query": "ORIGINAL",
                               "top": 5, "relevant": [{"path": "service.py", "symbol": "service"}], "distractors": []}]}))

                def query(*args, **kwargs):
                    if changed == "suite":
                        suite.write_text(suite.read_text().replace("ORIGINAL", "CHANGED"))
                    else:
                        index.with_name(index.name + "-wal").write_bytes(b"committed change")
                    return SimpleNamespace(returncode=0, stdout='{"candidates": []}', stderr="")

                with patch.object(concept_relevance.subprocess, "run", side_effect=query):
                    with self.assertRaisesRegex(ValueError, "input changed"):
                        concept_relevance.evaluate(binary, index, source, suite)
