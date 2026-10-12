"""A sealed export with a stub Claude CLI that records every call and replays queued results."""

import json
import os

from evals.benchmark import artifacts as artifact_io
from evals.benchmark import corpus, review
from evals.benchmark import trials as trial_runner
from .corpus import CorpusFixture


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


def respond(state, call, text, models=("judge-model",), is_error=False, subtype="success", init=None, mode=None):
    result = {"type": "result", "subtype": subtype, "is_error": is_error, "result": text,
              "modelUsage": {model: {} for model in models}, "permission_denials": [],
              "usage": {"input_tokens": 10, "output_tokens": 5}}
    for name, value in (("result", result), ("init", init), ("mode", mode)):
        if value is not None:
            (state / f"{name}-{call}.json").write_text(json.dumps(value))


def calls(state):
    paths = sorted(state.glob("call-*.json"), key=lambda path: int(path.stem.split("-")[1]))
    return [json.loads(path.read_text()) for path in paths]


class JudgeFixture:
    """One qualification case run once per condition, exported for review, with a fake judge CLI."""

    def __init__(self, answer, attempts=3):
        self.case = CorpusFixture()
        self.fixture = self.case.fixture
        self.root = self.fixture.root
        self.case.qualify()
        # Each attempt's answer ends with its trial name, so answers of one export are distinct texts.
        self.fixture.adapter(f"init()\nfinal(answer={answer!r} + ' Trial ' + pathlib.Path(request['source_root']).parent.name + '.')\n")
        selected = corpus.select_case(self.case.path, self.case.task["id"], self.fixture.repo)
        self.export = self.export_batch("review-export", selected["rubric"], selected["summary"])
        self.template = artifact_io.load_json(self.export / "reviewer/assessment-template.json")
        self.state = self.root / "judge-state"
        self.state.mkdir()
        os.mkfifo(self.state / "never")
        self.instruction = self.root / "judge.md"
        self.instruction.write_text("Assess the answers.\n")
        self.config = {"cli": self.fixture.executable("fake-claude", f"STATE = {str(self.state)!r}\n" + STUB),
                       "model": "judge-model", "instruction": str(self.instruction), "reviewer": "judge",
                       "attempts": attempts, "timeout_seconds": 30}

    def export_batch(self, name, rubric, corpus_case=None):
        batch = trial_runner.prepare_batch(task=self.case.task, rubric=rubric, config=self.fixture.config,
            source_repo=self.fixture.repo, tool_repo=self.fixture.repo, output=self.root / ("batches-" + name),
            repetitions=1, corpus_case=corpus_case)
        for item in artifact_io.load_json(batch / "batch.json")["trials"]:
            trial_runner.run_trial(batch / item["directory"])
        return review.export_review(batch, self.root / name)

    def respond(self, call, text, **options):
        respond(self.state, call, text, **options)

    def calls(self):
        return calls(self.state)

    def close(self):
        self.case.close()
