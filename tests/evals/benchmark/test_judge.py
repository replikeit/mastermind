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
from evals.benchmark import corpus, judge, review
from evals.benchmark import trials as trial_runner
from tests.evals.support.corpus import CorpusFixture
from tests.evals.support.review import completed_assessment


STUB = """import hashlib, json, os, pathlib, sys
state = pathlib.Path(STATE)
if sys.argv[1:] == ['--version']:
    print('fake-v1 (Claude Code)')
    sys.exit(0)
call = len(list(state.glob('call-*.json'))) + 1
cwd = pathlib.Path.cwd()
(state / f'call-{call}.json').write_text(json.dumps({
    'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': str(cwd), 'home': os.environ['HOME'],
    'environment': sorted(os.environ), 'key': os.environ.get('ANTHROPIC_API_KEY'),
    'base_url': os.environ.get('ANTHROPIC_BASE_URL'),
    'disabled': [os.environ.get(name) for name in ('DISABLE_AUTOUPDATER', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')],
    'template': json.loads((cwd / 'assessment-template.json').read_text()),
    'files': {str(path.relative_to(cwd)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in cwd.rglob('*') if path.is_file()}}))
def load(name, default):
    path = state / f'{name}-{call}.json'
    return json.loads(path.read_text()) if path.exists() else default
mode = load('mode', '')
if mode == 'block':
    open(state / 'never', 'rb').read()
init = {'type': 'system', 'subtype': 'init', 'model': 'judge-model', 'claude_code_version': 'fake-v1',
        'cwd': str(cwd), 'permissionMode': 'dontAsk', 'tools': ['Read'], 'mcp_servers': [], 'plugins': []}
init.update(load('init', {}))
print(json.dumps(init))
if mode == 'flood':
    print('x' * 8192)
result = load('result', None)
if result is not None:
    print(json.dumps(result))
sys.exit(3 if mode == 'exit' else 0)
"""

CANARIES = {"CLAUDE_CODE_OAUTH_TOKEN": "canary", "ANTHROPIC_BASE_URL": "http://canary.invalid",
            "CLAUDE_CONFIG_DIR": "/canary-config"}


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "requires POSIX and Git")
class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.case = CorpusFixture()
        self.addCleanup(self.case.close)
        self.fixture = self.case.fixture
        self.root = self.fixture.root
        self.case.qualify()
        selected = corpus.select_case(self.case.path, self.case.task["id"], self.fixture.repo)
        self.export = self.make_export("review-export", selected["rubric"], selected["summary"])
        self.template = artifact_io.load_json(self.export / "reviewer/assessment-template.json")
        self.state = self.root / "judge-state"
        self.state.mkdir()
        os.mkfifo(self.state / "never")
        self.instruction = self.root / "judge.md"
        self.instruction.write_text("Assess the answers.\n")
        self.config = {"cli": self.fixture.executable("fake-claude", f"STATE = {str(self.state)!r}\n" + STUB),
                       "model": "judge-model", "instruction": str(self.instruction), "reviewer": "judge",
                       "attempts": 3, "timeout_seconds": 30}
        self.output = self.root / "judge-run"

    def make_export(self, name, rubric, corpus_case=None):
        batch = trial_runner.prepare_batch(task=self.case.task, rubric=rubric, config=self.fixture.config,
            source_repo=self.fixture.repo, tool_repo=self.fixture.repo, output=self.root / ("batches-" + name),
            repetitions=1, corpus_case=corpus_case)
        for item in artifact_io.load_json(batch / "batch.json")["trials"]:
            trial_runner.run_trial(batch / item["directory"])
        return review.export_review(batch, self.root / name)

    def respond(self, call, text, models=("judge-model",), is_error=False, subtype="success", init=None, mode=None):
        result = {"type": "result", "subtype": subtype, "is_error": is_error, "result": text,
                  "modelUsage": {model: {} for model in models}, "permission_denials": [],
                  "usage": {"input_tokens": 10, "output_tokens": 5}}
        for name, value in (("result", result), ("init", init), ("mode", mode)):
            if value is not None:
                (self.state / f"{name}-{call}.json").write_text(json.dumps(value))

    def review(self, position, **change):
        """A completed reply for the answer at this template position (1-based)."""
        row = completed_assessment(self.export, "judge")["reviews"][position - 1]
        row["claims"][0].update(change)
        return json.dumps({"reviews": [row]})

    def respond_valid(self, first_call, positions):
        for offset, position in enumerate(positions):
            self.respond(first_call + offset, self.review(position))

    def calls(self):
        paths = sorted(self.state.glob("call-*.json"), key=lambda path: int(path.stem.split("-")[1]))
        return [json.loads(path.read_text()) for path in paths]

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

    def test_an_answer_without_a_valid_review_stops_the_run_unresolved(self):
        self.respond(1, "I could not finish the review.")
        self.respond(2, json.dumps({"reviews": [json.loads(self.review(1))["reviews"][0]] * 2}))
        self.respond(3, self.review(2))
        code, out, err = self.main()
        self.assertEqual(code, 2, err)
        summary = json.loads(out)
        self.assertIsNone(summary["receipt"])
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
