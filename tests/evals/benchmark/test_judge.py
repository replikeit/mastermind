"""The judge sees only a reviewer copy, retains every attempt and imports one valid assessment."""

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
    'disabled': [os.environ.get(name) for name in ('DISABLE_AUTOUPDATER', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')],
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

    def reviews(self, **change):
        rows = completed_assessment(self.export, "judge")["reviews"]
        for row in rows:
            row["claims"][0].update(change)
        return json.dumps({"reviews": rows})

    def calls(self):
        return [json.loads(path.read_text()) for path in sorted(self.state.glob("call-*.json"))]

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
            index = record["attempt"]
            self.assertEqual(artifact_io.load_json(output / f"attempt-{index}.json"), record)
            stdout = (output / f"attempt-{index}.stdout").read_bytes()
            self.assertEqual(hashlib.sha256(stdout).hexdigest(), record["stdout_sha256"])
            self.assertTrue((output / f"attempt-{index}.stderr").is_file())

    def test_retries_invalid_output_and_imports_first_valid_assessment(self):
        self.respond(1, self.reviews(quote="A sentence the answer never wrote."))
        self.respond(2, "```json\n" + self.reviews() + "\n```")
        code, out, err = self.main()
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual([row["status"] for row in summary["attempts"]], ["invalid", "valid"])
        self.assertEqual(summary["attempts"][0]["error"]["code"], "review_quote")
        self.assertIsNone(summary["error"])
        self.assert_retained(summary)
        self.assertEqual(review.review_status(self.export)["reviewers"], [{"reviewer": "judge", "reviewed": 3}])
        recorded = artifact_io.load_json(self.output / "judge.json")
        self.assertEqual(recorded["instruction_sha256"], hashlib.sha256(self.instruction.read_bytes()).hexdigest())
        self.assertEqual(recorded["prompt_sha256"], hashlib.sha256(judge.PROMPT).hexdigest())
        reviewer = self.export / "reviewer"
        expected = {str(path.relative_to(reviewer)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in reviewer.rglob("*") if path.is_file()}
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]["cwd"], calls[1]["cwd"])
        self.assertNotEqual(calls[0]["home"], calls[1]["home"])
        for call in calls:
            argv = call["argv"]
            self.assertEqual(call["stdin"], judge.PROMPT.decode())
            self.assertEqual(call["files"], expected)
            self.assertEqual(Path(call["home"]).parent, Path(call["cwd"]).parent)
            self.assertEqual(call["key"], "fixture-key")
            self.assertEqual(call["disabled"], ["1", "1"])
            self.assertFalse(set(CANARIES) & set(call["environment"]))
            self.assertIn("--bare", argv)
            self.assertIn("--strict-mcp-config", argv)
            self.assertNotIn("--allowedTools", argv)
            for option, value in (("--tools", "Read"), ("--permission-mode", "dontAsk"), ("--setting-sources", ""),
                                  ("--output-format", "stream-json"), ("--system-prompt", "Assess the answers.\n")):
                self.assertEqual(argv[argv.index(option) + 1], value)

    def test_keeps_every_rejected_attempt_and_leaves_the_review_unresolved(self):
        self.respond(1, "I could not finish the review.")
        self.respond(2, self.reviews(), models=("judge-model", "another-model"))
        self.respond(3, self.reviews(), init={"tools": ["Read", "Bash"]})
        code, out, err = self.main()
        self.assertEqual(code, 2, err)
        summary = json.loads(out)
        self.assertIsNone(summary["receipt"])
        self.assertEqual([row["error"]["code"] for row in summary["attempts"]],
                         ["judge_output_invalid", "judge_model_mismatch", "judge_runtime_mismatch"])
        self.assertEqual(summary["attempts"][1]["observed"]["models_used"], ["another-model", "judge-model"])
        self.assertEqual(summary["attempts"][2]["observed"]["tools"], ["Read", "Bash"])
        self.assert_retained(summary)
        self.assertFalse((self.output / "assessment.json").exists())
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_each_runtime_field_outside_the_contract_rejects_the_attempt(self):
        for call, (init, code) in enumerate((
                ({"cwd": "/elsewhere"}, "judge_runtime_mismatch"),
                ({"mcp_servers": [{"name": "extra", "status": "connected"}]}, "judge_runtime_mismatch"),
                ({"permissionMode": "default"}, "judge_runtime_mismatch"),
                ({"claude_code_version": "fake-v2"}, "judge_runtime_mismatch"),
                ({"model": "another-model"}, "judge_model_mismatch")), start=1):
            with self.subTest(init=init):
                self.respond(call, self.reviews(), init=init)
                status, out, err = self.main(dict(self.config, attempts=1), output=self.root / f"judge-run-{call}")
                self.assertEqual(status, 2, err)
                self.assertEqual(json.loads(out)["attempts"][0]["error"]["code"], code)
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_cli_failures_and_error_results_are_rejected_attempts(self):
        self.respond(1, self.reviews(), mode="block")
        self.respond(2, self.reviews(), mode="flood")
        self.respond(3, self.reviews(), mode="exit")
        with patch.object(judge, "STDOUT_LIMIT", 4096):
            code, out, err = self.main(dict(self.config, timeout_seconds=1))
        self.assertEqual(code, 2, err)
        attempts = json.loads(out)["attempts"]
        self.assertEqual([(row["stop_reason"], row["error"]["code"]) for row in attempts],
                         [("timeout", "judge_cli_error"), ("output_limit", "judge_cli_error"), (None, "judge_cli_error")])
        self.assertEqual(attempts[2]["returncode"], 3)
        for call, change in ((4, {"is_error": True}), (5, {"subtype": "error_max_turns"})):
            with self.subTest(change=change):
                self.respond(call, self.reviews(), **change)
                code, out, err = self.main(dict(self.config, attempts=1), output=self.root / f"judge-run-{call}")
                self.assertEqual(code, 2, err)
                self.assertEqual(json.loads(out)["attempts"][0]["error"]["code"], "judge_cli_error")
        self.assertEqual(review.review_status(self.export)["reviewers"], [])

    def test_another_reviewer_import_does_not_discard_a_valid_assessment(self):
        alice = self.root / "alice.json"
        alice.write_bytes(artifact_io.canonical(completed_assessment(self.export, "alice")))
        original = judge.run_bounded

        def run_with_concurrent_import(command, **options):
            if "--version" not in command:
                review.import_assessment(self.export, alice)
            return original(command, **options)

        self.respond(1, self.reviews())
        with patch.object(judge, "run_bounded", side_effect=run_with_concurrent_import):
            code, out, err = self.main()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(row["reviewer"] for row in review.review_status(self.export)["reviewers"]),
                         ["alice", "judge"])

    def test_failed_import_keeps_the_run_summary(self):
        self.respond(1, self.reviews())
        with patch.object(review, "import_assessment", side_effect=artifact_io.BenchmarkError("review_busy", "busy")):
            code, out, err = self.main()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("review_busy:"), err)
        summary = artifact_io.load_json(self.output / "judge-run.json")
        self.assertEqual(summary["error"]["code"], "review_busy")
        self.assertIsNone(summary["receipt"])
        self.assertEqual(summary["attempts"][0]["status"], "valid")
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
                             ("timeout_seconds", 7201), ("timeout_seconds", True), ("reviewer", "Judge"), ("model", "")):
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
