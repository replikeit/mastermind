"""Repository documentation discovery, excluding generated local evidence."""

from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from scripts import validate


class DocumentationDiscoveryTests(unittest.TestCase):
    def test_local_state_is_excluded_without_hiding_source_under_an_ignored_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "target" / "checkout"
            private = root / ".mastermind" / "research" / "copy" / "README.md"
            private.parent.mkdir(parents=True)
            private.write_text("[private](missing.md)\n[[missing-private]]\n")
            source = root / "README.md"
            source.write_text("[source](missing.md)\n[[missing-source]]\n")
            nearby = root / "mastermind-notes" / "README.md"
            nearby.parent.mkdir()
            nearby.write_text("[source](../README.md)\n")
            with patch.object(validate, "REPO_ROOT", root):
                links = validate.collect_relative_links()
                self.assertEqual(set(links), {source, nearby})
                issues = validate.validate_relative_links(links)
                self.assertEqual([issue.path for issue in issues], [source])
                wiki = validate.collect_wikilinks()
                self.assertEqual(wiki, {source: {"missing-source"}})
                issues = validate.validate_wikilinks([], wiki)
                self.assertEqual([issue.path for issue in issues], [source])


class EvalFixtureClueTests(unittest.TestCase):
    def test_behavior_fixture_sources_are_scanned_but_readmes_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "evals/behavior/fixtures/sample"
            source = fixture / "changes/after/source.py"
            source.parent.mkdir(parents=True)
            source.write_text("# auditor must catch this\n")
            baseline = fixture / "baseline"
            baseline.mkdir()
            (baseline / "README.md").write_text("auditor must catch this\n")
            (fixture / "README.md").write_text("auditor must catch this\n")
            with patch.object(validate, "REPO_ROOT", root):
                issues = validate.validate_eval_fixture_clues()
            self.assertEqual([issue.path for issue in issues], [source])
            self.assertEqual(issues[0].level, "error")
            self.assertIn("banned clue", issues[0].msg)

    def test_missing_or_empty_fixture_inventory_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / "evals/behavior/fixtures"
            for state in ("missing", "empty", "empty-trees"):
                with self.subTest(state=state):
                    if state == "empty":
                        fixtures.mkdir(parents=True)
                    elif state == "empty-trees":
                        (fixtures / "sample/baseline").mkdir(parents=True)
                        (fixtures / "sample/changes").mkdir()
                    with patch.object(validate, "REPO_ROOT", root):
                        issues = validate.validate_eval_fixture_clues()
                    self.assertTrue(issues)
                    self.assertTrue(all(issue.level == "error" for issue in issues))
