"""Development order balance and native payload admission boundaries."""

from collections import Counter
import unittest

from evals.benchmark import artifacts, repo_map


class RepoMapTests(unittest.TestCase):
    def test_two_repetitions_balance_mean_order_without_claiming_uniform_per_case(self):
        cases = [f"case-{number}" for number in range(8)]
        rows = repo_map.factorial_schedule(cases)
        self.assertEqual(len(rows), 64)
        for case in cases:
            first = [row["arm"] for row in rows if row["case"] == case and row["repetition"] == 0]
            second = [row["arm"] for row in rows if row["case"] == case and row["repetition"] == 1]
            self.assertEqual(second, first[::-1])
            for arm in repo_map.ARMS:
                positions = [row["position"] for row in rows if row["case"] == case and row["arm"] == arm]
                self.assertEqual(sum(positions), 3)
                self.assertEqual(len(positions), 2)
        for arm in repo_map.ARMS:
            positions = Counter(row["position"] for row in rows if row["arm"] == arm)
            self.assertEqual(positions, {0: 4, 1: 4, 2: 4, 3: 4})

    def test_duplicate_or_empty_cases_cannot_add_pseudoreplicates(self):
        for cases in ([], ["same", "same"], [""], [None]):
            with self.subTest(cases=cases), self.assertRaises(artifacts.BenchmarkError):
                repo_map.factorial_schedule(cases)

    def test_budget_aliases_depend_on_all_case_payloads_not_metadata_or_row_counts(self):
        rows = [{"case": case, "budget_bytes": budget, "mode": "bundle", "selected": 3,
            "payload_sha256": artifacts.digest("smaller" if case == "second" and budget == 512 else "same")}
            for budget in repo_map.BUDGETS for case in ("first", "second")]
        self.assertEqual(repo_map.equivalent_budgets(rows), [[512], [1600, 4096, 16384]])

    def test_native_payload_requires_utf8_bytes_and_exact_source_budget_binding(self):
        source_sha = "a" * 64
        value = {"schema_version": 1, "algorithm": "focused_shortlist_v3",
            "source_sha256": source_sha, "budget_bytes": 512,
            "payload": "карта", "payload_bytes": len("карта".encode()), "selected": 1}
        self.assertEqual(repo_map.validate_payload(value, source_sha, 512), value)
        mutations = ({"schema_version": True}, {"source_sha256": "b" * 64}, {"budget_bytes": 1600},
            {"payload_bytes": len("карта")}, {"payload": "x" * 513, "payload_bytes": 513},
            {"selected": True}, {"selected": 10}, {"algorithm": "other"})
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(artifacts.BenchmarkError):
                repo_map.validate_payload(dict(value, **mutation), source_sha, 512)


if __name__ == "__main__":
    unittest.main()
