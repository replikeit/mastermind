"""Producer citation parsing against a pinned inventory without changing acceptance."""

import copy
import hashlib
import unittest
from unittest import mock

from evals.benchmark import artifacts, producer_binding


def source_inventory(bodies):
    return {
        path: {
            "path": path,
            "git_mode": "100644",
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "lines": body.count(b"\n") + int(bool(body) and not body.endswith(b"\n")),
        }
        for path, body in bodies.items()
    }


def quoted_answer(reference, quote="    return 7"):
    return f"`{reference}`\n```python\n{quote}\n```\n"


class ProducerBindingTests(unittest.TestCase):
    def setUp(self):
        self.bodies = {"src/service.py": b"def value():\n    return 7\n"}
        self.sources = source_inventory(self.bodies)

    def audit(self, answer, **kwargs):
        return producer_binding.audit_answer(answer, self.sources, self.bodies, **kwargs)

    def binding(self, answer, **kwargs):
        report = self.audit(answer, **kwargs)
        self.assertEqual(report["summary"]["citation_count"], 1)
        return report["bindings"][0]

    def test_list_continuation_fence_removes_framing_but_preserves_code_indentation(self):
        answer = ("1. Source: `src/service.py:1-2`\n\n"
                  "   ```python\n"
                  "   def value():\n"
                  "       return 7\n"
                  "   ```\n")
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["quote"], "def value():\n    return 7")
        self.assertEqual(row["quote_sha256"], hashlib.sha256(row["quote"].encode()).hexdigest())
        self.assertEqual(row["anchor"], "src/service.py:1-2")

    def test_tilde_and_long_backtick_fences_preserve_shorter_marker_lines_as_source(self):
        self.bodies["src/service.py"] = b"value = 7\n```\n"
        self.sources = source_inventory(self.bodies)
        for opening, closing in (("~~~~python", "~~~~~"), ("````python", "`````")):
            with self.subTest(opening=opening):
                answer = f"[src/service.py:1-2]\n{opening}\nvalue = 7\n```\n{closing}\n"
                row = self.binding(answer)
                self.assertEqual(row["status"], "valid")
                self.assertEqual(row["quote"], "value = 7\n```")

    def test_crlf_and_unicode_in_snippets_are_preserved_without_text_normalization(self):
        self.bodies["src/service.py"] = "def résumé():\r\n    return 'é\u2028λ'\r\n".encode()
        self.sources = source_inventory(self.bodies)
        answer = ("`src/service.py:1-2`\r\n"
                  "  ```python\r\n"
                  "  def résumé():\r\n"
                  "      return 'é\u2028λ'\r\n"
                  "  ```\r\n")
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["quote"], "def résumé():\r\n    return 'é\u2028λ'")
        altered = answer.replace("é", "e\u0301")
        self.assertEqual(self.binding(altered)["status"], "invalid")

    def test_citation_looking_strings_inside_closed_and_unclosed_fences_are_not_references(self):
        for closing in ("```\n", ""):
            with self.subTest(closed=bool(closing)):
                answer = "Example:\n```text\nsrc/service.py:2\n" + closing
                report = self.audit(answer)
                self.assertEqual(report["bindings"], [])
                self.assertEqual(report["summary"]["citation_count"], 0)
                self.assertTrue(report["no_citations"])
                self.assertFalse(report["semantic_acceptance_recomputed"])
                self.assertEqual(report["summary"]["fences"]["unclosed"], int(not closing))

    def test_indented_code_citations_cannot_bind_a_following_fence(self):
        for indent in ("    ", "\t"):
            with self.subTest(indent=repr(indent)):
                answer = (f"{indent}```python\n"
                          f"{indent}src/service.py:2\n"
                          f"{indent}```\n"
                          "```python\n    return 7\n```\n")
                report = self.audit(answer)
                self.assertEqual(report["bindings"], [])
                self.assertEqual(report["summary"]["citation_count"], 0)
                self.assertTrue(report["no_citations"])

    def test_indented_code_is_a_barrier_between_an_outside_citation_and_fence(self):
        for indent in ("    ", "\t"):
            with self.subTest(indent=repr(indent)):
                answer = f"`src/service.py:2`\n{indent}```\n```python\n    return 7\n```\n"
                row = self.binding(answer)
                self.assertEqual(row["status"], "unverifiable")
                self.assertEqual(row["reason"], "source_quote_missing")
                self.assertIsNone(row["fence"])

    def test_only_adjacent_fences_supply_quotes_and_intervening_prose_breaks_association(self):
        direct = "`src/service.py:2`\n\n```python\n    return 7\n```\n"
        separated = "`src/service.py:2`\nA separate explanation.\n```python\n    return 7\n```\n"
        self.assertEqual(self.binding(direct)["status"], "valid")
        row = self.binding(separated)
        self.assertEqual(row["status"], "unverifiable")
        self.assertEqual(row["reason"], "source_quote_missing")
        self.assertIsNone(row["quote"])

    def test_unclosed_fence_does_not_verify_a_preceding_citation(self):
        answer = "`src/service.py:2`\n```python\n    return 7\nsrc/service.py:1\n"
        report = self.audit(answer)
        self.assertEqual(report["summary"]["citation_count"], 1)
        self.assertEqual(report["summary"]["fences"]["unclosed"], 1)
        row = report["bindings"][0]
        self.assertEqual(row["status"], "unverifiable")
        self.assertEqual(row["reason"], "producer_quote_unclosed")
        self.assertIsNone(row["quote"])

    def test_standalone_cr_at_eof_is_not_normalized_into_a_closing_fence(self):
        answer = "`src/service.py:2`\n```python\n    return 7\n```\r"
        row = self.binding(answer)
        self.assertEqual(row["status"], "unverifiable")
        self.assertEqual(row["reason"], "producer_quote_unclosed")

    def test_multiple_adjacent_citations_or_snippets_are_not_guessed(self):
        self.bodies["src/other.py"] = self.bodies["src/service.py"]
        self.sources = source_inventory(self.bodies)
        answers = (
            "`src/service.py:2` `src/other.py:2`\n```python\n    return 7\n```\n",
            "`src/service.py:2`\n```python\n    return 7\n```\n\n```python\n    return 7\n```\n",
            "```python\n    return 7\n```\n\n```python\n    return 7\n```\n`src/service.py:2`\n",
            "```python\n    return 7\n```\n`src/service.py:2` `src/other.py:2`\n",
        )
        for answer in answers:
            with self.subTest(answer=answer):
                report = self.audit(answer)
                self.assertGreater(report["summary"]["citation_count"], 0)
                self.assertTrue(all(row["status"] == "unverifiable" for row in report["bindings"]))
                self.assertTrue(all(row["reason"] == "producer_quote_ambiguous"
                                    for row in report["bindings"]))

    def test_alternating_citations_and_fences_bind_as_independent_pairs(self):
        self.bodies["src/other.py"] = b"def other():\n    return 9\n"
        self.sources = source_inventory(self.bodies)
        answer = quoted_answer("src/service.py:2") + "\n" + quoted_answer("src/other.py:2", "    return 9")
        report = self.audit(answer)
        self.assertEqual(report["summary"]["citations"], {"valid": 2, "invalid": 0, "unverifiable": 0})
        self.assertEqual([row["quote"] for row in report["bindings"]], ["    return 7", "    return 9"])

    def test_ambiguous_citation_run_does_not_block_a_later_independent_pair(self):
        self.bodies["src/other.py"] = self.bodies["src/service.py"]
        self.sources = source_inventory(self.bodies)
        answer = ("`src/service.py:2` `src/other.py:2`\n"
                  "```python\n    return 7\n```\n\n"
                  + quoted_answer("src/service.py:2"))
        report = self.audit(answer)
        self.assertEqual([row["status"] for row in report["bindings"]],
                         ["unverifiable", "unverifiable", "valid"])
        self.assertEqual([row["reason"] for row in report["bindings"][:2]],
                         ["producer_quote_ambiguous"] * 2)

    def test_reverse_association_does_not_steal_a_fence_from_an_earlier_citation(self):
        answer = quoted_answer("src/service.py:2") + "\n`src/service.py:2`\n"
        report = self.audit(answer)
        self.assertEqual([row["status"] for row in report["bindings"]], ["valid", "unverifiable"])
        self.assertEqual(report["bindings"][1]["reason"], "source_quote_missing")
        self.assertIsNone(report["bindings"][1]["fence"])

    def test_following_fence_has_priority_over_a_preceding_fence(self):
        answer = ("```python\n    return 9\n```\n"
                  + quoted_answer("src/service.py:2"))
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["quote"], "    return 7")

    def test_unused_preceding_fence_is_supported_when_there_is_no_following_fence(self):
        answer = "```python\n    return 7\n```\n`src/service.py:2`\n"
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["quote"], "    return 7")

    def test_canonical_and_unique_basename_references_resolve_from_inventory(self):
        for reference, resolution in (("src/service.py:2", "source_path_exact"),
                                      ("service.py:2", "source_basename_unique")):
            with self.subTest(reference=reference):
                row = self.binding(quoted_answer(reference))
                self.assertEqual(row["status"], "valid")
                self.assertEqual(row["resolved_path"], "src/service.py")
                self.assertEqual(row["anchor"], "src/service.py:2")
                self.assertEqual(row["resolution"]["reason"], resolution)
                self.assertEqual(row["original_path"], reference.rpartition(":")[0])

    def test_non_file_metadata_is_ignored_and_inventory_extensionless_filename_is_supported(self):
        self.bodies["Makefile"] = b"all:\n\ttrue\n"
        self.sources = source_inventory(self.bodies)
        answer = ("Fields: top:1 candidate_total:2 candidate_count:3.\n\n"
                  + quoted_answer("Makefile:2", "\ttrue"))
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["resolved_path"], "Makefile")
        self.assertEqual(row["anchor"], "Makefile:2")

    def test_duplicate_basenames_are_unverifiable_even_if_only_one_source_matches_quote(self):
        self.bodies["other/service.py"] = b"def value():\n    return 9\n"
        self.sources = source_inventory(self.bodies)
        row = self.binding(quoted_answer("service.py:2"))
        self.assertEqual(row["status"], "unverifiable")
        self.assertIsNone(row["resolved_path"])
        self.assertEqual(set(row["resolution"]["candidates"]),
                         {"src/service.py", "other/service.py"})

    def test_malformed_line_bounds_are_invalid_even_when_basename_is_ambiguous(self):
        self.bodies["other/service.py"] = self.bodies["src/service.py"]
        self.sources = source_inventory(self.bodies)
        for span, reason in (("0", "corpus_anchor_invalid"), ("2-1", "corpus_anchor_range")):
            with self.subTest(span=span):
                row = self.binding(quoted_answer("service.py:" + span))
                self.assertEqual(row["status"], "invalid")
                self.assertEqual(row["reason"], reason)
                self.assertIsNone(row["resolved_path"])

    def test_canonical_root_filename_takes_precedence_over_basename_fallback(self):
        self.bodies["service.py"] = self.bodies["src/service.py"]
        self.bodies["src/service.py"] = b"def value():\n    return 9\n"
        self.sources = source_inventory(self.bodies)
        row = self.binding(quoted_answer("service.py:2"))
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["resolved_path"], "service.py")
        self.assertEqual(row["resolution"]["reason"], "source_path_exact")

    def test_unknown_traversal_and_foreign_absolute_paths_are_not_suffix_matched(self):
        references = ("missing.py:2", "wrong/service.py:2", "../src/service.py:2",
                      "src/../src/service.py:2", "/elsewhere/src/service.py:2")
        for reference in references:
            with self.subTest(reference=reference):
                row = self.binding(quoted_answer(reference))
                self.assertEqual(row["status"], "invalid")
                self.assertIsNone(row["resolved_path"])
                self.assertIsNone(row["anchor"])

    def test_trusted_absolute_prefix_must_match_on_the_exact_directory_boundary(self):
        prefix = "/pinned/source"
        row = self.binding(quoted_answer(prefix + "/src/service.py:2"), source_prefix=prefix)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["resolution"]["reason"], "source_prefix_exact")
        for reference in (prefix + "-foreign/src/service.py:2",
                          prefix + "/../source/src/service.py:2",
                          prefix + "//src/service.py:2"):
            with self.subTest(reference=reference):
                row = self.binding(quoted_answer(reference), source_prefix=prefix)
                self.assertEqual(row["status"], "invalid")
                self.assertIsNone(row["resolved_path"])

    def test_anchor_range_and_literal_mismatch_have_distinct_failures(self):
        outside_range = self.binding(quoted_answer("src/service.py:3"))
        wrong_line = self.binding(quoted_answer("src/service.py:1"))
        self.assertEqual(outside_range["status"], "invalid")
        self.assertEqual(outside_range["reason"], "corpus_anchor_range")
        self.assertEqual(wrong_line["status"], "invalid")
        self.assertEqual(wrong_line["reason"], "source_quote_outside_span")

    def test_en_dash_range_preserves_the_reference_and_validates_the_exact_range(self):
        reference = "src/service.py:1–2"
        answer = quoted_answer(reference, "def value():\n    return 7")
        row = self.binding(answer)
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["original_citation"], reference)
        self.assertEqual(answer[slice(*row["answer_span"])], reference)
        self.assertEqual(row["line_span"], "1–2")
        self.assertEqual(row["anchor"], "src/service.py:1-2")
        self.assertEqual(row["quote"], "def value():\n    return 7")

        reversed_reference = "src/service.py:2–1"
        reversed_row = self.binding(quoted_answer(reversed_reference, "    return 7"))
        self.assertEqual(reversed_row["original_citation"], reversed_reference)
        self.assertEqual(reversed_row["line_span"], "2–1")
        self.assertEqual(reversed_row["status"], "invalid")
        self.assertEqual(reversed_row["reason"], "corpus_anchor_range")
        self.assertIsNone(reversed_row["anchor"])

        for unsupported in ("src/service.py:1—2", "src/service.py:1-2–3"):
            with self.subTest(unsupported=unsupported):
                report = self.audit(quoted_answer(unsupported, "def value():\n    return 7"))
                self.assertTrue(report["no_citations"])
                self.assertEqual(report["summary"]["citation_count"], 0)

    def test_missing_blank_and_oversize_snippets_remain_unverifiable(self):
        answers = (
            ("`src/service.py:2`\n", "source_quote_missing"),
            (quoted_answer("src/service.py:2", "   \t"), "producer_quote_blank"),
            (quoted_answer("src/service.py:2", "λ" * 8193), "producer_quote_limit"),
        )
        for answer, reason in answers:
            with self.subTest(reason=reason):
                row = self.binding(answer)
                self.assertEqual(row["status"], "unverifiable")
                self.assertEqual(row["reason"], reason)

    def test_no_citations_does_not_become_a_successful_verification(self):
        report = self.audit("This answer makes a claim without evidence.\n")
        self.assertTrue(report["no_citations"])
        self.assertEqual(report["summary"]["citations"], {"valid": 0, "invalid": 0, "unverifiable": 0})
        self.assertFalse(report["semantic_acceptance_recomputed"])

    def test_snapshot_failure_is_reported_without_mutating_input_inventory(self):
        original_sources = copy.deepcopy(self.sources)
        self.bodies["src/service.py"] = self.bodies["src/service.py"].replace(b"7", b"9")
        row = self.binding(quoted_answer("src/service.py:2", "    return 9"))
        self.assertEqual(row["status"], "invalid")
        self.assertEqual(row["reason"], "source_snapshot_mismatch")
        self.assertEqual(self.sources, original_sources)

    def test_citation_cap_rejects_overflow_without_truncating_the_answer(self):
        reference = "`src/service.py:2`\n"
        with mock.patch.object(producer_binding, "MAX_CITATIONS", 2):
            report = self.audit(reference * 2)
            self.assertEqual(report["summary"]["citation_count"], 2)
            with self.assertRaises(artifacts.BenchmarkError) as raised:
                self.audit(reference * 3)
        self.assertEqual(raised.exception.code, "producer_citation_limit")

    def test_fence_cap_counts_closed_and_unclosed_blocks_and_rejects_overflow(self):
        block = "```text\nbody\n```\n"
        with mock.patch.object(producer_binding, "MAX_FENCES", 2):
            report = self.audit(block * 2)
            self.assertEqual(report["summary"]["fences"]["observed"], 2)
            for third_block in (block, "```text\nbody\n"):
                with self.subTest(closed=third_block == block):
                    with self.assertRaises(artifacts.BenchmarkError) as raised:
                        self.audit(block * 2 + third_block)
                    self.assertEqual(raised.exception.code, "producer_fence_limit")


if __name__ == "__main__":
    unittest.main()
