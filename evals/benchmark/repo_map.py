"""Offline payload sweep and development schedules over retained repo-map inputs."""

from pathlib import Path
import argparse
import hashlib
import re
import tempfile

from . import artifacts, runtime, source
from evals.shared.process import run_bounded


BUDGETS = (512, 1600, 4096, 16384)
MODES = ("bundle", "map-only", "instructions-only")
ARMS = ("baseline", "map-only", "instructions-only", "bundle")


def require(condition, message):
    if not condition:
        raise artifacts.BenchmarkError("repo_map_input_mismatch", message)


def sha(path):
    return artifacts.hash_file(path, artifacts.BINARY_BYTE_LIMIT)["sha256"]


def factorial_schedule(cases):
    """Rotate each case's first order and reverse it for its second repetition."""
    require(bool(cases) and all(isinstance(case, str) and case for case in cases)
            and len(cases) == len(set(cases)), "case IDs must be nonempty and unique")
    rows = []
    for number, case in enumerate(cases):
        offset = number % len(ARMS)
        order = ARMS[offset:] + ARMS[:offset]
        for repetition in range(2):
            for position, arm in enumerate(order if repetition == 0 else order[::-1]):
                rows.append({"case": case, "arm": arm, "repetition": repetition, "position": position})
    return rows


def validate_payload(value, source_sha256, budget):
    require(type(value.get("schema_version")) is int and value["schema_version"] == 1
            and value.get("algorithm") == "focused_shortlist_v3"
            and value.get("source_sha256") == source_sha256 and value.get("budget_bytes") == budget,
            "native map has the wrong source, algorithm or budget binding")
    payload = value.get("payload")
    require(isinstance(payload, str) and type(value.get("payload_bytes")) is int
            and value["payload_bytes"] == len(payload.encode()) <= budget,
            "native payload byte accounting differs from its UTF-8 body")
    require(type(value.get("selected")) is int and 0 <= value["selected"] <= 9,
            "invalid selected definition count")
    return value


def equivalent_budgets(rows):
    groups = {}
    for budget in BUDGETS:
        signature = artifacts.digest({r["case"]: r["payload_sha256"] for r in rows
            if r["budget_bytes"] == budget and r["mode"] == "bundle"})
        groups.setdefault(signature, []).append(budget)
    return list(groups.values())


def retained_inputs(campaign, seal, env):
    require(seal.get("kind") == "mastermind-integrated-map-all-task-inputs"
            and seal.get("algorithm") == "focused_shortlist_v3", "unsupported retained campaign")
    pairs = {}
    for case, binding in seal["cases"].items():
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]*", case), "invalid case ID")
        jobs = sorted((j for j in seal["jobs"] if j["case"] == case), key=lambda j: j["position"])
        require(len(jobs) == 2 and {j["condition"] for j in jobs} == {"baseline", "map"}
                and all(j["repetition"] == 0 for j in jobs), "expected one retained pair per case")
        requests = {}
        for job in jobs:
            trial = campaign / job["trial"]
            require(trial.resolve().is_relative_to(campaign), "trial is outside the retained campaign")
            request = artifacts.load_json(trial / "request.json")
            require(sha(trial / "request.json") == job["request_file_sha256"]
                    and artifacts.digest(request) == job["request_sha256"]
                    and sha(trial / "adapter-runtime.json") == job["runtime_sha256"], "retained request/runtime changed")
            require(request["task"] == binding["task"] and request["source_files"] == binding["source_files"]
                    and request["source_root"] == binding["source_root"]
                    and request["projection_revision"] == binding["projection_revision"], "retained source binding differs")
            requests[job["condition"]] = request
        baseline, bundle = requests["baseline"], requests["map"]
        require({k: v for k, v in baseline.items() if k != "portable_instruction"}
                == {k: v for k, v in bundle.items() if k != "portable_instruction"}, "pair differs beyond intervention")
        mapping_path = campaign / "cases" / case / "map.json"
        mapping = artifacts.load_json(mapping_path)
        require(sha(mapping_path) == binding["map_sha256"]
                and bundle["portable_instruction"] == baseline["portable_instruction"] + "\n\n" + mapping["payload"],
                "retained map differs from its producer request")
        expected_source = artifacts.digest({"revision": binding["task"]["revision"], "files": binding["source_files"]})
        require(expected_source == binding["source_sha256"], "invalid source inventory digest")
        root = Path(binding["source_root"])
        source.verify_source(root, binding["source_files"])
        source.verify_projection(root, binding["source_files"], binding["projection_revision"], env)
        mmcg = baseline["mmcg"]
        require(source.validate_index(Path(mmcg["index"]), root, binding["source_files"],
                mmcg["index_contract"], mmcg["indexed_files"]) == binding["index_sha256"] == mmcg["index_sha256"],
                "retained index changed")
        require(mmcg["runtime"]["sha256"] == seal["native"]["sha256"]
                and mmcg["binary"] == seal["native"]["path"], "producer native binding changed")
        pairs[case] = {"jobs": jobs, "request": baseline, "mapping": mapping}
    require(len(seal["jobs"]) == 2 * len(pairs), "unexpected extra retained jobs")
    return pairs


def sweep(campaign, native):
    campaign, native = campaign.resolve(strict=True), native.resolve(strict=True)
    input_sha, native_sha = sha(campaign / "input-seal.json"), sha(native)
    seal = artifacts.load_json(campaign / "input-seal.json")
    require(sha(Path(seal["native"]["path"])) == seal["native"]["sha256"], "retained producer native changed")
    rows, advice = [], None
    with tempfile.TemporaryDirectory(prefix="mm-map-sweep-") as temporary:
        work = Path(temporary).resolve()
        env = runtime.clean_environment(work)
        pairs = retained_inputs(campaign, seal, env)
        for case, pair in pairs.items():
            binding, request = seal["cases"][case], pair["request"]
            for budget in BUDGETS:
                variants = {}
                for mode in MODES:
                    command = [str(native), "--index", request["mmcg"]["index"], "repo-map",
                        request["task"]["question"], "--source-sha256", binding["source_sha256"],
                        "--budget-bytes", str(budget), "--payload", mode]
                    outputs = []
                    for _ in range(2):
                        process = run_bounded(command, cwd=work, env=env, stdout_limit=artifacts.CONTROL_BYTE_LIMIT)
                        require(not process.stop_reason and process.returncode == 0, "native map generation failed")
                        outputs.append(process.stdout)
                    require(outputs[0] == outputs[1], "native map generation is not deterministic")
                    value = validate_payload(artifacts.parse_json(outputs[0]), binding["source_sha256"], budget)
                    variants[mode] = value
                    text = value["payload"]
                    rows.append({"case": case, "budget_bytes": budget, "mode": mode,
                        "payload_bytes": value["payload_bytes"], "selected": value["selected"],
                        "payload_sha256": hashlib.sha256(text.encode()).hexdigest(), "payload": text,
                        "request_sha256": artifacts.digest(dict(request,
                            portable_instruction=request["portable_instruction"] + "\n\n" + text)), "command": command})
                bundle, mapping, instructions = (variants[m] for m in MODES)
                require(bundle["payload"].count(instructions["payload"]) == 1 and bool(instructions["payload"])
                        and mapping["payload"] == bundle["payload"].replace(instructions["payload"], "", 1)
                        and mapping["selected"] == bundle["selected"] and instructions["selected"] == 0,
                        "ablations changed the map factor or failed to isolate the advice")
                require(advice is None or advice == instructions["payload"], "instruction factor varies across cases/budgets")
                advice = instructions["payload"]
                if budget == 1600:
                    require(bundle == pair["mapping"], "default bundle no longer equals retained input")
        require(pairs == retained_inputs(campaign, seal, env), "retained inputs changed during sweep")
    require(sha(campaign / "input-seal.json") == input_sha and sha(native) == native_sha
            and sha(Path(seal["native"]["path"])) == seal["native"]["sha256"], "sweep inputs changed")
    groups = equivalent_budgets(rows)
    representatives = [values[0] for values in groups]
    aliases = {}
    for row in rows:
        key = (row["case"], row["request_sha256"])
        row["alias_of"] = aliases.get(key)
        aliases.setdefault(key, {"budget_bytes": row["budget_bytes"], "mode": row["mode"]})
    repeat = [{"case": case, "condition": j["condition"], "repetition": 1, "position": position,
        "retained_request_sha256": j["request_sha256"], "retained_trial": j["trial"]}
        for case, pair in pairs.items() for position, j in enumerate(reversed(pair["jobs"]))]
    return {"kind": "mastermind-repo-map-offline-sweep", "schema_version": 1,
        "scope": "development_only_not_qualification", "campaign": str(campaign), "input_sha256": input_sha,
        "native": {"path": str(native), "sha256": native_sha}, "budgets": list(BUDGETS),
        "distinct_curve_points": representatives, "budget_equivalence_groups": groups,
        "recommended_factorial_budget": next(values[0] for values in groups if BUDGETS[-1] in values),
        "map_factor": "same selected locations, source binding and shortlist disclaimer; bundle budget reservation",
        "instruction_factor": advice, "rows": rows, "reverse_pair_repeat": repeat,
        "factorial_schedule": factorial_schedule(list(pairs)), "model_calls_started": 0,
        "model_launch_gates": ["judge calibration bound to exact instruction/tools/model profile",
            "human reference remains separate from model proxy labels"],
        "qualification_gates": ["new preregistered held-out cases from at least two repositories",
            "design-specific t_star simulation; existing development cases remain development"],
        "limitations": ["bytes are not tokenizer measurements", "equal payloads are aliases, not independent budget evidence",
            "two factorial repetitions balance each arm's mean position per case; uniform positions require four repetitions",
            "reverse repeat and fresh factorial are separate plans, not automatically cumulative model runs"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = sweep(args.campaign, args.native)
    artifacts.write_new(args.output.resolve(), result)
    print(f"Swept {len(result['rows'])} payloads; distinct curve points: {result['distinct_curve_points']}; model calls: 0")


if __name__ == "__main__":
    main()
