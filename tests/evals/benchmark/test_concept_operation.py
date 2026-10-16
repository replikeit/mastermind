"""Phased source review keeps bindings, uncertainty and query denominators."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals.benchmark import concept_operation


class ConceptOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "service.py").write_text("def service():\n    return 7\n")
        self.binary = self.root / "mmcg"
        self.binary.write_text("retained binary fixture")
        self.index = self.root / "index.db"
        self.index.write_bytes(b"frozen index fixture")
        self.suite = self.root / "suite.json"
        cases = []
        for identifier, query, kind in [("hit", "read fixed value", "positive"),
                                        ("uncertain", "read unclear value", "positive"),
                                        ("negative", "send unrelated value", "negative")]:
            cases.append({"id": identifier, "query": query, "kind": kind, "split": "independent",
                          "top": 5, "relevant": [] if kind == "negative" else [
                              {"path": "service.py", "symbol": "service" if identifier == "hit"
                               else "HIDDEN_QREL_CANARY"}], "distractors": []})
        self.suite.write_text(json.dumps({"schema_version": 1, "source_head": "frozen-head",
            "source_files_sha256": {"service.py": hashlib.sha256((self.source / "service.py").read_bytes()).hexdigest()},
            "cases": cases}))
        self.output = self.root / "prepared"
        self.assessments = self.root / "assessments"
        self.assessments.mkdir()

    def native(self, arguments, **kwargs):
        self.assertEqual(arguments[1:4], ["--index", str(self.index), "concept-review"])
        if arguments[4] == "prepare":
            query = arguments[5]
            packet = {"schema_version": 1, "query": query, "top": 5,
                      "hints": [value.removeprefix("--hint=") for value in arguments[6:]
                                if value.startswith("--hint=")],
                      "packet_sha256": hashlib.sha256(query.encode()).hexdigest(),
                      "omissions": [{"path": "hidden.py", "reason": "source_limit"}] if "fixed" in query else [],
                      "retrieval_truncated": "fixed" in query,
                      "candidates": [{"id": "candidate-1", "path": "service.py", "name": "service",
                                      "line_start": 1, "line_end": 2,
                                      "snippets": [{"start_line": 1, "end_line": 2,
                                                    "text": "def service():\n    return 7"}]}]}
            return SimpleNamespace(returncode=0, stdout=json.dumps(packet).encode(), stderr=b"")
        self.assertEqual(arguments[4], "finish")
        packet = json.loads(Path(arguments[6]).read_text())
        unknown = "unclear" in packet["query"] or "unrelated" in packet["query"]
        coverage_complete = not packet["omissions"] and not packet["retrieval_truncated"]
        result = {"schema_version": 1, "packet_sha256": packet["packet_sha256"],
                  "review_status": "complete" if not unknown and coverage_complete else "incomplete",
                  "assessment_complete": not unknown, "coverage_complete": coverage_complete,
                  "omissions": packet["omissions"], "retrieval_truncated": packet["retrieval_truncated"],
                  "result_truncated": False,
                  "candidates": [] if unknown else packet["candidates"],
                  "unknown_candidates": packet["candidates"] if unknown else [], "rejected_count": 0}
        return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode(), stderr=b"")

    def role_native(self, arguments, *, contexts=(), ambiguities=(),
                    contract=concept_operation.ROLE_CONTRACT, **kwargs):
        result = self.native(arguments, **kwargs)
        value = json.loads(result.stdout)
        value["role_contract"] = contract
        if contract == concept_operation.ROLE_CONTRACT and arguments[4] == "prepare":
            value["request_contract"] = (
                json.loads(Path(arguments[arguments.index("--request-contract") + 1]).read_text())
                if "--request-contract" in arguments else
                {"operation": value["query"], "constraints": []})
        if arguments[4] == "finish":
            packet = json.loads(Path(arguments[6]).read_text())
            if contract == concept_operation.ROLE_CONTRACT:
                value["query"] = packet["query"]
                value["request_contract"] = packet["request_contract"]
            ambiguous = packet["query"] in ambiguities
            if ambiguous:
                value["candidates"] = packet["candidates"]
                value["unknown_candidates"] = []
                value["assessment_complete"] = True
            for candidate in value["candidates"]:
                candidate["role"] = ("supporting_context" if ambiguous or packet["query"] in contexts
                                     else "implementation")
                candidate["supporting_evidence"] = []
                if contract == concept_operation.ROLE_CONTRACT:
                    candidate["witness"] = {
                        "behavior": "Exposes the inspected fixed-value behavior.",
                        "relation": ("operation_navigation" if candidate["role"] == "supporting_context"
                                     else "performs_operation"),
                        "constraint_checks": [{"constraint_id": item["id"], "status": "matched",
                            "evidence": [{"path": "service.py", "source_sha256": hashlib.sha256(
                                (self.source / "service.py").read_bytes()).hexdigest(),
                                "start_line": 1, "end_line": 2}]}
                            for item in packet["request_contract"]["constraints"]]}
            for candidate in value["unknown_candidates"]:
                candidate["role"] = None
                candidate["supporting_evidence"] = []
            value["semantic_candidates"] = [row for row in value["candidates"]
                                             if row["role"] != "supporting_context"]
            value["supporting_context"] = [row for row in value["candidates"]
                                           if row["role"] == "supporting_context"]
            value["query_ambiguities"] = ["Unresolved requested behavior"] if ambiguous else []
            value["review_status"] = ("complete" if value["assessment_complete"]
                                      and value["coverage_complete"] and not ambiguous else "incomplete")
        result.stdout = json.dumps(value).encode()
        return result

    def prepare(self, native=None, hints_path=None, request_contracts_path=None):
        with patch.object(concept_operation.subprocess, "run", side_effect=native or self.native):
            return concept_operation.prepare(self.binary, self.index, self.source, self.suite, self.output,
                                             hints_path, request_contracts_path)

    def assess(self, prepared, omit=()):
        for row in prepared["cases"]:
            if row["status"] == "prepared" and row["id"] not in omit:
                (self.assessments / row["assessment_file"]).write_text(json.dumps({
                    "schema_version": 1, "packet_sha256": row["packet_sha256"],
                    "judgments": [{"candidate_id": "candidate-1", "verdict": "unknown",
                                   "reason": "Deterministic test input", "citations": []}]}))

    def finish(self, native=None):
        with patch.object(concept_operation.subprocess, "run", side_effect=native or self.native):
            return concept_operation.finish(self.output / "preparation.json", self.assessments)

    def test_packets_withhold_qrels_and_unknown_rows_do_not_become_known_empty_negatives(self):
        hints = self.root / "hints.json"
        values = {"hit": ["--literal", "fixed values"], "uncertain": [], "negative": []}
        hints.write_text(json.dumps(values))
        prepared = self.prepare(hints_path=hints)
        self.assertEqual(prepared["bindings"]["hints_sha256"], hashlib.sha256(hints.read_bytes()).hexdigest())
        for row in prepared["cases"]:
            path = self.output / row["packet_file"]
            self.assertNotIn(row["id"], path.name)
            self.assertNotIn("HIDDEN_QREL_CANARY", path.read_text())
            self.assertNotIn("relevant", json.loads(path.read_text()))
            self.assertEqual(json.loads(path.read_text())["hints"], values[row["id"]])
        self.assess(prepared)
        result = self.finish()
        summary = result["summary"]["independent"]
        self.assertEqual((summary["planned_cases"], summary["failed_cases"], summary["positive_queries"]), (3, 0, 2))
        self.assertEqual((summary["positive_queries_with_anchor"], summary["positive_queries_unknown"]), (1, 1))
        self.assertIsNone(summary["hit_at_k"])
        self.assertEqual(summary["hit_at_k_bounds"], [.5, 1.0])
        self.assertEqual((summary["unknown_candidates"], summary["negative_queries_known_empty"],
                          summary["negative_queries_review_incomplete"]), (2, 0, 1))
        self.assertEqual((summary["assessment_complete_cases"], summary["assessment_incomplete_cases"],
                          summary["coverage_complete_cases"], summary["coverage_incomplete_cases"]), (1, 2, 2, 1))
        self.assertEqual((summary["queries_with_source_omissions"], summary["source_omission_records"],
                          summary["retrieval_truncated_queries"]), (1, 1, 1))
        self.assertEqual((summary["raw_positive_queries_with_anchor"], summary["raw_anchor_observations"],
                          summary["raw_anchor_observations_in_incomplete_reviews"]), (1, 1, 1))
        hit = next(row for row in result["cases"] if row["id"] == "hit")
        self.assertEqual(hit["response"]["candidates"][0]["line"], 1)

    def test_prepare_failure_and_missing_assessment_remain_in_planned_denominators(self):
        def native(arguments, **kwargs):
            if arguments[4:6] == ["prepare", "read fixed value"]:
                return SimpleNamespace(returncode=7, stdout=b"", stderr=b"unavailable")
            return self.native(arguments, **kwargs)

        prepared = self.prepare(native)
        self.assertEqual(prepared["failed_cases"], 1)
        self.assess(prepared, omit=("uncertain",))
        result = self.finish()
        summary = result["summary"]["independent"]
        self.assertEqual((summary["planned_cases"], summary["completed_cases"], summary["failed_cases"]), (3, 1, 2))
        self.assertEqual((summary["positive_queries"], summary["positive_queries_unknown"]), (2, 2))
        self.assertEqual(summary["hit_at_k_bounds"], [0.0, 1.0])
        self.assertEqual(len(result["assessment_coverage"]["missing"]), 1)
        failed = {row["id"]: row for row in result["cases"] if row["status"] == "failed"}
        self.assertEqual(failed["hit"]["stage"], "prepare")
        self.assertIn("assessment is missing", failed["uncertain"]["error"])

    def test_binding_drift_between_phases_stops_before_native_finish(self):
        hints = self.root / "hints.json"
        hints.write_text(json.dumps({"hit": [], "uncertain": [], "negative": []}))
        prepared = self.prepare(hints_path=hints)
        self.assess(prepared)
        self.index.with_name(self.index.name + "-wal").write_bytes(b"new committed data")
        hints.write_text(json.dumps({"hit": ["changed recall"], "uncertain": [], "negative": []}))
        with patch.object(concept_operation.subprocess, "run") as native:
            with self.assertRaisesRegex(ValueError, "since prepare: hints_sha256, index_wal_sha256"):
                concept_operation.finish(self.output / "preparation.json", self.assessments)
        native.assert_not_called()

    def test_hints_require_exact_case_coverage_and_bounded_utf8_strings_before_native_calls(self):
        defaults = {"hit": [], "uncertain": [], "negative": []}
        invalid = [{"hit": []}, {**defaults, "extra": []}, {**defaults, "hit": "string"},
                   {**defaults, "hit": ["hint"] * 9}, {**defaults, "hit": ["я" * 33]}]
        hints = self.root / "hints.json"
        for values in invalid:
            with self.subTest(values=values):
                hints.write_text(json.dumps(values))
                with patch.object(concept_operation.subprocess, "run") as native:
                    with self.assertRaises(ValueError):
                        concept_operation.prepare(self.binary, self.index, self.source, self.suite,
                                                  self.output, hints)
                native.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_prepare_retains_drift_record_and_cannot_be_finished_or_overwritten(self):
        def mutate(arguments, **kwargs):
            result = self.native(arguments, **kwargs)
            self.binary.write_text("changed executable")
            return result

        prepared = self.prepare(mutate)
        self.assertEqual(prepared["status"], "input_changed")
        self.assertEqual(prepared["changed_inputs"], ["binary_sha256"])
        original = (self.output / "preparation.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "stable operation-search preparation"):
            self.finish()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual((self.output / "preparation.json").read_bytes(), original)

    def test_changed_packet_and_extra_assessment_cannot_enter_native_finish(self):
        prepared = self.prepare()
        self.assess(prepared)
        extra = self.assessments / "unplanned.json"
        extra.write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected assessment"):
            self.finish()
        extra.unlink()
        packet = self.output / prepared["cases"][0]["packet_file"]
        packet.write_text(packet.read_text().replace("return 7", "return 9"))
        with patch.object(concept_operation.subprocess, "run") as native:
            with self.assertRaisesRegex(ValueError, "prepared packet changed"):
                concept_operation.finish(self.output / "preparation.json", self.assessments)
        native.assert_not_called()

    def test_assessment_drift_during_finish_invalidates_the_whole_measurement(self):
        prepared = self.prepare()
        self.assess(prepared)
        assessment = self.assessments / prepared["cases"][0]["assessment_file"]

        def mutate(arguments, **kwargs):
            result = self.native(arguments, **kwargs)
            assessment.write_text(assessment.read_text() + "\n")
            return result

        with self.assertRaisesRegex(ValueError, "input changed during finish"):
            self.finish(mutate)

    def test_native_result_with_wrong_packet_binding_is_a_failed_query(self):
        prepared = self.prepare()
        self.assess(prepared)

        def wrong_packet(arguments, **kwargs):
            result = self.native(arguments, **kwargs)
            value = json.loads(result.stdout)
            value["packet_sha256"] = "wrong-packet"
            result.stdout = json.dumps(value).encode()
            return result

        result = self.finish(wrong_packet)
        self.assertEqual(result["summary"]["independent"]["failed_cases"], 3)
        self.assertTrue(all("does not match" in row["error"] for row in result["cases"]))

    def test_supporting_context_preserves_useful_page_without_counting_as_semantic_anchor(self):
        for contract in ("operation-roles-v1", "operation-roles-v2", "operation-roles-v3"):
            with self.subTest(contract=contract):
                self.output = self.root / f"prepared-{contract}"
                self.assessments = self.root / f"assessments-{contract}"
                self.assessments.mkdir()

                def native(arguments, **kwargs):
                    return self.role_native(arguments, contexts=("read fixed value",),
                                            contract=contract, **kwargs)

                prepared = self.prepare(native)
                self.assertEqual({row["status"] for row in prepared["cases"]}, {"prepared"},
                                 prepared["cases"])
                self.assertTrue(all(row["role_contract"] == contract for row in prepared["cases"]))
                self.assess(prepared)
                result = self.finish(native)
                hit = next(row for row in result["cases"] if row["id"] == "hit")
                self.assertFalse(hit["anchor_hit"])
                self.assertEqual((hit["returned_rows"], hit["judged_rows"], hit["useful_returned_rows"],
                                  hit["navigation_returned_rows"]), (0, 0, 1, 1))
                self.assertEqual(hit["response"]["candidates"][0]["name"], "service")
                self.assertEqual(hit["response"]["semantic_candidates"], [])
                self.assertEqual(hit["response"]["supporting_context"], hit["response"]["candidates"])
                summary = result["summary"]["independent"]
                self.assertEqual((summary["raw_anchor_observations"], summary["semantic_returned_rows"],
                                  summary["useful_returned_rows"], summary["navigation_returned_rows"]),
                                 (0, 0, 1, 1))
                self.assertEqual(summary["role_aware_cases"], 3)

    def test_query_ambiguity_keeps_assessment_complete_negative_out_of_known_empty_results(self):
        def native(arguments, **kwargs):
            return self.role_native(arguments, ambiguities=("send unrelated value",), **kwargs)

        prepared = self.prepare(native)
        self.assess(prepared)
        result = self.finish(native)
        negative = next(row for row in result["cases"] if row["id"] == "negative")
        self.assertEqual(negative["status"], "completed")
        self.assertTrue(negative["assessment_complete"])
        self.assertTrue(negative["coverage_complete"])
        self.assertEqual(negative["unknown_candidates_count"], 0)
        self.assertEqual((negative["review_status"], negative["returned_rows"],
                          negative["navigation_returned_rows"]), ("incomplete", 0, 1))
        summary = result["summary"]["independent"]
        self.assertEqual((summary["negative_queries_known_empty"], summary["queries_with_ambiguities"],
                          summary["query_ambiguity_records"], summary["negative_queries_with_navigation"]),
                         (0, 1, 1, 1))

    def test_new_role_contract_cannot_downgrade_or_accept_malformed_partitions(self):
        prepared = self.prepare(self.role_native)
        self.assess(prepared)

        def ambiguous_context(value, ambiguities):
            value["query_ambiguities"] = ambiguities
            for candidate in value["candidates"]:
                candidate["role"] = "supporting_context"
            value["semantic_candidates"] = []
            value["supporting_context"] = value["candidates"]
            value["review_status"] = "incomplete"

        corruptions = {
            "missing_contract": lambda value: value.pop("role_contract"),
            "unknown_contract": lambda value: value.update(role_contract="operation-roles-v0"),
            "mixed_supported_contracts": lambda value: value.update(
                role_contract=("operation-roles-v1" if concept_operation.ROLE_CONTRACT == "operation-roles-v2"
                               else "operation-roles-v2")),
            "missing_semantic_partition": lambda value: value.pop("semantic_candidates"),
            "overlapping_partitions": lambda value: value.update(supporting_context=value["candidates"]),
            "unknown_role": lambda value: value["candidates"][0].update(role="neighbor"),
            "role_on_unknown": lambda value: value.update(
                unknown_candidates=[{"role": "implementation"}], assessment_complete=False,
                review_status="incomplete"),
            "malformed_ambiguities": lambda value: ambiguous_context(value, "unclear"),
            "too_many_ambiguities": lambda value: ambiguous_context(value, ["unclear"] * 9),
            "oversized_ambiguity": lambda value: ambiguous_context(value, ["я" * 129]),
            "blank_ambiguity": lambda value: ambiguous_context(value, [" "]),
            "control_character_ambiguity": lambda value: ambiguous_context(value, ["unclear\u0085term"]),
            "ambiguous_semantic_positive": lambda value: value.update(query_ambiguities=["unclear"]),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(name=name):
                def native(arguments, **kwargs):
                    result = self.role_native(arguments, **kwargs)
                    packet = json.loads(Path(arguments[6]).read_text())
                    if packet["query"] == "read fixed value":
                        value = json.loads(result.stdout)
                        corrupt(value)
                        result.stdout = json.dumps(value).encode()
                    return result

                result = self.finish(native)
                summary = result["summary"]["independent"]
                self.assertEqual((summary["planned_cases"], summary["completed_cases"],
                                  summary["failed_cases"]), (3, 2, 1))
                hit = next(row for row in result["cases"] if row["id"] == "hit")
                self.assertEqual((hit["status"], hit["stage"]), ("failed", "finish"))

    def test_query_only_contract_is_bound_before_retrieval_and_drift_stops_finish(self):
        path = self.root / "contracts.json"
        cases = json.loads(self.suite.read_text())["cases"]
        contracts = {case["id"]: {"operation": case["query"], "constraints": [
            {"id": "object", "text": "value", "kind": "result"}]} for case in cases}
        path.write_text(json.dumps(contracts))
        prepared = self.prepare(self.role_native, request_contracts_path=path)
        self.assertEqual(prepared["failed_cases"], 0)
        for row in prepared["cases"]:
            packet = json.loads((self.output / row["packet_file"]).read_text())
            self.assertEqual(packet["request_contract"], contracts[row["id"]])
        self.assess(prepared)
        result = self.finish(self.role_native)
        self.assertEqual(result["summary"]["independent"]["failed_cases"], 0)
        contracts["hit"]["constraints"][0]["kind"] = "state"
        path.write_text(json.dumps(contracts))
        with patch.object(concept_operation.subprocess, "run") as native:
            with self.assertRaisesRegex(ValueError, "request_contracts_sha256"):
                self.finish()
        native.assert_not_called()

    def test_invalid_request_contracts_fail_before_any_native_call(self):
        path = self.root / "contracts.json"
        defaults = {case["id"]: {"operation": case["query"], "constraints": []}
                    for case in json.loads(self.suite.read_text())["cases"]}
        invalid = [{"hit": defaults["hit"]},
                   {**defaults, "hit": {"operation": "read fixed value", "constraints": [
                       {"id": "scope", "text": "a different request", "kind": "scope"}]}}]
        for contracts in invalid:
            with self.subTest(contracts=contracts):
                path.write_text(json.dumps(contracts))
                with patch.object(concept_operation.subprocess, "run") as native:
                    with self.assertRaises(ValueError):
                        concept_operation.prepare(self.binary, self.index, self.source, self.suite,
                                                  self.output, request_contracts_path=path)
                native.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_unproven_or_inconsistent_native_witness_is_failed_not_a_useful_hit(self):
        path = self.root / "contracts.json"
        path.write_text(json.dumps({case["id"]: {"operation": case["query"], "constraints": [
            {"id": "object", "text": "value", "kind": "result"}]}
            for case in json.loads(self.suite.read_text())["cases"]}))
        prepared = self.prepare(self.role_native, request_contracts_path=path)
        self.assess(prepared)
        corruptions = {
            "missing_witness": lambda candidate: candidate.pop("witness"),
            "missing_constraint": lambda candidate: candidate["witness"].update(constraint_checks=[]),
            "uninspected_constraint": lambda candidate: candidate["witness"]["constraint_checks"][0].update(
                status="uninspected"),
            "contradicted_constraint": lambda candidate: candidate["witness"]["constraint_checks"][0].update(
                status="contradicted"),
            "missing_evidence": lambda candidate: candidate["witness"]["constraint_checks"][0].update(
                evidence=[]),
            "prerequisite_claimed_as_implementation": lambda candidate: candidate["witness"].update(
                relation="generic_prerequisite"),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(name=name):
                def native(arguments, **kwargs):
                    result = self.role_native(arguments, **kwargs)
                    packet = json.loads(Path(arguments[6]).read_text())
                    if packet["query"] == "read fixed value":
                        value = json.loads(result.stdout)
                        corrupt(value["candidates"][0])
                        result.stdout = json.dumps(value).encode()
                    return result
                result = self.finish(native)
                summary = result["summary"]["independent"]
                self.assertEqual((summary["planned_cases"], summary["failed_cases"]), (3, 1))
                self.assertEqual(summary["raw_anchor_observations"], 0)


if __name__ == "__main__":
    unittest.main()
