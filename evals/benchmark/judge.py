"""Assess a review export with a pinned Claude CLI and import its first valid assessment.

The judge reads a verified copy of reviewer/ in a fresh temporary directory, so
the coordinator mapping, raw trials and earlier attempts are not beside it. The
CLI's permission layer confines Read to that directory; it is not an OS sandbox.
Judge labels are model declarations until they are calibrated against blind
human review.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import re
import sys
import tempfile

from . import artifacts as artifact_io
from . import review
from . import review_contracts
from . import runtime as runtime_identity
from .assessment import check_assessment, receipt_names
from .review_io import Root, sha
from evals.shared.process import run_bounded


VERSION = "mastermind-judge-v1"

# An allow rule for Read would also lift the CLI's working-directory confinement,
# so permissions come only from dontAsk mode.
TOOLS = "Read"

PROMPT = (b"Assess every retained answer in the current directory. packet.json holds the original task "
          b"and its review key, answers/ holds the answers and source/ holds the cited source. Complete "
          b"assessment-template.json and reply with only a JSON object whose \"reviews\" field holds the "
          b"completed reviews.\n")

STDOUT_LIMIT = 64 * 1024 * 1024


def load_config(path: Path) -> dict:
    value = artifact_io.load_json(path)
    review_contracts.require(isinstance(value, dict) and set(value) == {
            "cli", "model", "instruction", "reviewer", "attempts", "timeout_seconds"}, "unexpected judge config fields", "judge_config")
    review_contracts.require(isinstance(value["model"], str) and value["model"].strip()
            and isinstance(value["reviewer"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value["reviewer"])
            and type(value["attempts"]) is int and 1 <= value["attempts"] <= 3
            and type(value["timeout_seconds"]) is int and 1 <= value["timeout_seconds"] <= 7200,
            "judge needs a model, a lowercase reviewer label, 1..3 attempts and 1..7200 seconds", "judge_config")
    instruction = Path(value["instruction"]).resolve(strict=True)
    body = artifact_io.read_file(instruction)
    return dict(value, cli=runtime_identity.runtime_pin(value["cli"], "claude"),
                instruction=str(instruction), instruction_text=body.decode("utf-8"),
                instruction_sha256=sha(body))


def command(config: dict) -> list[str]:
    return [config["cli"]["path"], "-p", "--bare", "--model", config["model"],
            "--system-prompt", config["instruction_text"], "--tools", TOOLS,
            "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-chrome",
            "--permission-mode", "dontAsk", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose"]


def check_version(config: dict, key: str) -> None:
    with tempfile.TemporaryDirectory(prefix="mastermind-judge-") as temporary:
        base = Path(temporary).resolve()
        result = run_bounded([config["cli"]["path"], "--version"], cwd=base,
                             env=runtime_identity.clean_environment(base, {"ANTHROPIC_API_KEY": key}),
                             timeout=10, stdout_limit=4096, stderr_limit=4096)
    if (result.stop_reason or result.returncode != 0
            or result.stdout.decode("utf-8", "replace").strip() != config["cli"]["version"] + " (Claude Code)"):
        raise artifact_io.BenchmarkError("claude_cli_version_mismatch", "CLI does not report the pinned version")


def write_workspace(root: Root, workspace: Path) -> None:
    for path, record in sorted(root.records.items()):
        if not path.startswith("reviewer/") or record["sha256"] is None:
            continue
        body = root.read(path, record["limit"])
        review_contracts.require(sha(body) == record["sha256"], "reviewer packet changed", "review_changed")
        target = workspace / path.removeprefix("reviewer/")
        target.parent.mkdir(parents=True, exist_ok=True)
        artifact_io.write_new_bytes(target, body)


def observe(stdout: bytes, record: dict) -> tuple[dict, dict]:
    rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    init = next((row for row in rows if isinstance(row, dict) and row.get("type") == "system"
                 and row.get("subtype") == "init"), None)
    result = next((row for row in reversed(rows) if isinstance(row, dict) and row.get("type") == "result"), None)
    review_contracts.require(isinstance(init, dict) and isinstance(result, dict),
                             "CLI stream lacks its init or result event", "judge_cli_error")
    record["observed"] = {name: init.get(name) for name in (
        "model", "claude_code_version", "cwd", "permissionMode", "tools", "mcp_servers", "plugins")}
    models = result.get("modelUsage")
    record["observed"]["models_used"] = sorted(models) if isinstance(models, dict) else None
    record["observed"]["permission_denials"] = result.get("permission_denials")
    record["usage"] = result.get("usage")
    return init, result


def check_runtime(init: dict, result: dict, config: dict, workspace: Path) -> None:
    review_contracts.require(init.get("tools") == [TOOLS] and init.get("mcp_servers") == []
            and init.get("cwd") == str(workspace) and init.get("permissionMode") == "dontAsk"
            and init.get("claude_code_version") == config["cli"]["version"],
            "CLI runtime differs from the judge contract", "judge_runtime_mismatch")
    review_contracts.require(result.get("is_error") is False and result.get("subtype") == "success"
            and isinstance(result.get("result"), str), "CLI did not return a successful result", "judge_cli_error")
    review_contracts.require(init.get("model") == config["model"] and isinstance(result.get("modelUsage"), dict)
            and set(result["modelUsage"]) == {config["model"]},
            "CLI reported a model other than the requested one", "judge_model_mismatch")


def reply_reviews(text: str) -> list:
    start, end = text.find("{"), text.rfind("}")
    review_contracts.require(0 <= start < end, "reply contains no JSON object", "judge_output_invalid")
    reply = artifact_io.parse_json(text[start:end + 1].encode())
    review_contracts.require(isinstance(reply, dict) and "reviews" in reply, "reply omits reviews", "judge_output_invalid")
    return reply["reviews"]


def attempt(root: Root, config: dict, key: str, output: Path, index: int, check) -> tuple[dict, dict | None]:
    with tempfile.TemporaryDirectory(prefix="mastermind-judge-") as temporary:
        base = Path(temporary).resolve()
        workspace = base / "workspace"
        write_workspace(root, workspace)
        env = runtime_identity.clean_environment(base, {"ANTHROPIC_API_KEY": key})
        env.update({"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"})
        result = run_bounded(command(config), cwd=workspace, env=env, stdin=PROMPT,
                             timeout=config["timeout_seconds"], stdout_limit=STDOUT_LIMIT, stderr_limit=256 * 1024)
    stdout = bytes(result.stdout)
    artifact_io.write_new_bytes(output / f"attempt-{index}.stdout", stdout)
    artifact_io.write_new_bytes(output / f"attempt-{index}.stderr", bytes(result.stderr))
    record = {"attempt": index, "stop_reason": result.stop_reason, "returncode": result.returncode,
              "stdout_sha256": sha(stdout), "observed": None, "usage": None, "status": "invalid", "error": None}
    assessment = None
    try:
        review_contracts.require(not result.stop_reason and result.returncode == 0,
                                 "CLI did not exit cleanly", "judge_cli_error")
        init, outcome = observe(stdout, record)
        check_runtime(init, outcome, config, workspace)
        assessment = check(reply_reviews(outcome["result"]))
        record["status"] = "valid"
    except artifact_io.BenchmarkError as error:
        record["error"] = {"code": error.code, "message": str(error)}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        record["error"] = {"code": "judge_output_invalid", "message": str(error)}
    artifact_io.write_new(output / f"attempt-{index}.json", record)
    return record, assessment if record["status"] == "valid" else None


def run(export: Path, config: dict, output: Path, key: str) -> dict:
    export = export.resolve(strict=True)
    output = output.parent.resolve(strict=True) / output.name
    review_contracts.require(not output.is_relative_to(export), "judge output must be outside the review export", "review_path")
    with Root(export) as root:
        seal, packet, _, answers, sources = review.load_export(root)
        template = artifact_io.parse_json(root.read("reviewer/assessment-template.json"))
        review_contracts.require("acceptance_criteria" in packet["rubric"],
                "the judge assesses original-request acceptance; this key has no acceptance criteria", "judge_schema")
        review_contracts.require(config["reviewer"] + ".json" not in receipt_names(root),
                "reviewer already submitted an assessment", "review_exists")
        check_version(config, key)

        def check(reviews):
            value = dict(template, reviewer=config["reviewer"], reviews=reviews)
            check_assessment(value, seal, packet, answers, sources)
            return value

        output.mkdir(mode=0o700)
        artifact_io.write_new(output / "judge.json", {"kind": "mastermind-judge-config", "schema_version": 1,
            "version": VERSION, "export_id": seal["export_id"], "packet_sha256": seal["packet_sha256"],
            "template_sha256": seal["template_sha256"], "cli": config["cli"], "model": config["model"],
            "reviewer": config["reviewer"], "instruction_sha256": config["instruction_sha256"],
            "prompt_sha256": sha(PROMPT), "tools": TOOLS, "attempts": config["attempts"],
            "timeout_seconds": config["timeout_seconds"]})
        attempts, receipt, failure = [], None, None
        try:
            for index in range(1, config["attempts"] + 1):
                record, assessment = attempt(root, config, key, output, index, check)
                attempts.append(record)
                if assessment is not None:
                    artifact_io.write_new(output / "assessment.json", assessment)
                    # The importer re-verifies the export and assessment under its own lock;
                    # another reviewer's receipt is not input drift for this judge.
                    receipt = str(review.import_assessment(export, output / "assessment.json"))
                    break
        except BaseException as error:
            failure = {"code": getattr(error, "code", "judge_error"), "message": str(error)}
            raise
        finally:
            summary = {"kind": "mastermind-judge-run", "schema_version": 1, "export_id": seal["export_id"],
                       "reviewer": config["reviewer"], "attempts": attempts, "receipt": receipt, "error": failure,
                       "semantics": "model_declared_not_human_calibrated", "comparison_accepted": False,
                       "quality_uplift": None}
            artifact_io.write_new(output / "judge-run.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory outside the export")
    args = parser.parse_args(argv)
    try:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise artifact_io.BenchmarkError("anthropic_api_key_missing", "bare Claude CLI requires ANTHROPIC_API_KEY")
        summary = run(args.export, load_config(args.config), args.output, key)
        print(artifact_io.canonical(summary).decode())
        return 0 if summary["receipt"] else 2
    except (artifact_io.BenchmarkError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"{getattr(error, 'code', 'judge_error')}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
