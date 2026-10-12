"""Seeded-defect calibration sets for the model judge.

A set reuses one sealed review export's task, key and sources. Its answers are
originals that a named reference reviewer judged satisfied (controls) and copies of
such originals that each carry one declared defect. The judge sees the usual packet
format and one answer per call; key.json, which maps answers to defects, stays
outside reviewer/. Scores measure agreement with seeded ground truth and the
reference's labels, not calibration against blind human review.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import os
import random
import re
import secrets
import sys
import uuid

from . import artifacts as artifact_io
from . import conditions as condition_contract
from . import corpus
from . import judge
from . import review
from . import review_contracts
from .assessment import check_assessment, read_assessments
from .qualify import clopper_pearson_lower
from .review_io import Root, encoded, sha


# Each defect breaks one key element; its target names that element.
DEFECTS = {"criterion_removed": "criterion_id", "fabricated_citation": "criterion_id",
           "listed_false_claim": "false_claim_index", "novel_false_claim": None,
           "overclaimed_unknown": "unknown_index"}

# These defects are proven against the source, so they carry anchors.
ANCHORED = {"listed_false_claim", "novel_false_claim", "fabricated_citation"}

BOOTSTRAP_DRAWS = 2000

# A percentile bootstrap over fewer clusters has too few distinct resamples to bound anything.
MINIMUM_BOOTSTRAP_CASES = 5

OUTCOMES = ("satisfied", "unsatisfied", "unknown")

ANSWER_LIMIT = 16 * 1024 * 1024

ANCHOR_LIMIT = 64


def check_item(row: dict, rubric: dict, answer: str, sources: dict) -> None:
    """Contract of one key item against the answer it labels; build also checks the original."""
    review_contracts.fields(row, ("source_review_id", "defect", "target", "passage", "anchors", "rationale",
                                  "expected_outcome"), ("review_id",))
    review_contracts.identifier(row["source_review_id"], "review-")
    defect = row["defect"]
    review_contracts.require(defect == "control" or defect in DEFECTS, "unknown seeded defect", "calibration_item")
    review_contracts.require(row["expected_outcome"] == ("satisfied" if defect == "control" else "unsatisfied"),
                             "expected outcome conflicts with the defect", "calibration_item")
    review_contracts.text(row["rationale"])
    # A citation defect may replace every citation of a long answer, so its proof is longer than a claim's.
    review_contracts.require(isinstance(row["anchors"], list) and len(row["anchors"]) <= ANCHOR_LIMIT
                             and len(set(row["anchors"])) == len(row["anchors"]), "invalid defect evidence", "calibration_item")
    for anchor in row["anchors"]:
        review_contracts.text(anchor, 1024)
    corpus.validate_anchors(row["anchors"], sources)
    if defect == "control":
        review_contracts.require(row["target"] == {} and row["passage"] is None and not row["anchors"],
                                 "a control declares no defect", "calibration_item")
        return
    field = DEFECTS[defect]
    target = row["target"]
    review_contracts.require(isinstance(target, dict) and set(target) == ({field} if field else set()),
                             "defect target names the wrong key element", "calibration_item")
    if field == "criterion_id":
        review_contracts.require(target[field] in {item["id"] for item in rubric["acceptance_criteria"]},
                                 "unknown acceptance criterion", "calibration_item")
    elif field:
        listed = rubric["materially_false_claims" if field == "false_claim_index" else "expected_unknowns"]
        review_contracts.require(type(target[field]) is int and 0 <= target[field] < len(listed),
                                 "defect target is outside the key", "calibration_item")
    review_contracts.require(bool(row["anchors"]) == (defect in ANCHORED),
                             "source-proven defects need anchors and others carry none", "calibration_item")
    passage = review_contracts.text(row["passage"])
    # A removal is evidenced by the text that is gone; every other defect by the text that carries it.
    review_contracts.require((passage in answer) != (defect == "criterion_removed"),
                             "defect passage does not match the answer", "calibration_item")


def load_mutations(path: Path) -> dict:
    value = artifact_io.load_json(path)
    review_contracts.fields(value, ("kind", "schema_version", "reference", "controls", "mutants"))
    review_contracts.require(value["kind"] == "mastermind-judge-calibration-mutations"
                             and type(value["schema_version"]) is int and value["schema_version"] == 1,
                             "unsupported mutations file", "calibration_mutations")
    review_contracts.require(isinstance(value["reference"], str)
                             and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value["reference"]),
                             "reference must be a reviewer label", "calibration_mutations")
    review_contracts.require(isinstance(value["controls"], list) and isinstance(value["mutants"], list),
                             "invalid controls or mutants", "calibration_mutations")
    for control in value["controls"]:
        review_contracts.identifier(control, "review-")
    review_contracts.require(len(set(value["controls"])) == len(value["controls"]), "duplicate control", "calibration_mutations")
    for mutant in value["mutants"]:
        review_contracts.fields(mutant, ("source_review_id", "defect", "target", "answer", "passage", "anchors", "rationale"))
        review_contracts.identifier(mutant["source_review_id"], "review-")
        review_contracts.require(mutant["defect"] in DEFECTS and isinstance(mutant["target"], dict)
                                 and all(isinstance(item, (str, int)) and type(item) is not bool for item in mutant["target"].values()),
                                 "unknown seeded defect or malformed target", "calibration_mutations")
        review_contracts.text(mutant["answer"], 4096)
    return value


def build(export: Path, mutations: Path, output: Path) -> Path:
    export = export.resolve(strict=True)
    mutations = mutations.resolve(strict=True)
    destination = output.parent.resolve(strict=True) / output.name
    review_contracts.require(not destination.is_relative_to(export), "calibration set must be outside the review export", "review_path")
    plan = load_mutations(mutations)
    with Root(export) as root, Root(mutations.parent) as plan_root:
        seal, packet, _, answers, sources = review.load_export(root)
        rubric = packet["rubric"]
        review_contracts.require("acceptance_criteria" in rubric,
                                 "seeded defects are scored against acceptance criteria", "judge_schema")
        reference = next((value for value in read_assessments(root, seal, packet, answers, sources)
                          if value["reviewer"] == plan["reference"]), None)
        review_contracts.require(reference is not None, "the reference reviewer has no receipt in the export", "calibration_reference")
        satisfied = {row["review_id"] for row in reference["reviews"] if row["outcome"]["status"] == "satisfied"}
        entries = []
        for source_id in plan["controls"]:
            review_contracts.require(source_id in satisfied, "a control is not reference-satisfied", "calibration_reference")
            entries.append((answers[source_id], {"source_review_id": source_id, "defect": "control", "target": {},
                            "passage": None, "anchors": [], "expected_outcome": "satisfied",
                            "rationale": f"Original answer judged satisfied by {plan['reference']}."}))
        for mutant in plan["mutants"]:
            original = answers.get(mutant["source_review_id"])
            review_contracts.require(mutant["source_review_id"] in satisfied and original is not None,
                                     "a mutant's original is not reference-satisfied", "calibration_reference")
            body = plan_root.read(mutant["answer"], ANSWER_LIMIT)
            review_contracts.require(body, "empty mutant answer", "calibration_item")
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise artifact_io.BenchmarkError("calibration_item", "mutant answer is not UTF-8") from error
            row = {key: mutant[key] for key in ("source_review_id", "defect", "target", "passage", "anchors", "rationale")}
            row["expected_outcome"] = "unsatisfied"
            check_item(row, rubric, text, sources)
            review_contracts.require((row["passage"] in original) == (row["defect"] == "criterion_removed"),
                                     "defect passage does not match the original", "calibration_item")
            entries.append((text, row))
        review_contracts.require(2 <= len(entries) <= condition_contract.TRIAL_LIMIT
                                 and len({text for text, _ in entries}) == len(entries),
                                 "a set needs 2..60 distinct answers", "calibration_item")
        secrets.SystemRandom().shuffle(entries)
        export_id = "export-" + uuid.uuid4().hex
        ids = ["review-" + uuid.uuid4().hex for _ in entries]
        items = [{"review_id": review_id, "answer": {"path": "answers/" + review_id + ".md",
                  "bytes": len(text.encode()), "sha256": sha(text.encode())}}
                 for review_id, (text, _) in zip(ids, entries)]
        calibration_packet = dict(packet, export_id=export_id, items=items)
        packet_body = encoded(calibration_packet)
        template_body = encoded(review.assessment_template(calibration_packet, sha(packet_body)))
        key_body = encoded({"kind": "mastermind-judge-calibration-key", "schema_version": 1, "export_id": export_id,
            "packet_sha256": sha(packet_body),
            "source": {"export_id": seal["export_id"], "packet_sha256": seal["packet_sha256"],
                       "coordinator_sha256": seal["coordinator_sha256"], "reference": plan["reference"],
                       "reference_assessment_sha256": artifact_io.digest(reference)},
            "items": [dict(row, review_id=review_id) for review_id, (_, row) in zip(ids, entries)],
            "semantics": "seeded_defects_not_trial_results", "comparison_accepted": False, "quality_uplift": None})
        try:
            destination.mkdir(mode=0o700)
        except FileExistsError as error:
            raise artifact_io.BenchmarkError("review_exists", "choose a new calibration set directory") from error
        with Root(destination) as target:
            target.write_new("reviewer/packet.json", packet_body)
            target.write_new("reviewer/assessment-template.json", template_body)
            for path, record in sources.items():
                body = root.read("reviewer/source/" + path, record["bytes"])
                review_contracts.require(sha(body) == record["sha256"], "review source changed", "review_source")
                target.write_new("reviewer/source/" + path, body)
            for review_id, (text, _) in zip(ids, entries):
                target.write_new("reviewer/answers/" + review_id + ".md", text.encode())
            target.write_new("key.json", key_body)
            root.recheck()
            target.write_new("seal.json", encoded({"kind": "mastermind-judge-calibration-seal", "schema_version": 1,
                "export_id": export_id, "packet_sha256": sha(packet_body), "template_sha256": sha(template_body),
                "key_sha256": sha(key_body)}))
            target.recheck()
    return destination


def load_set(root: Root) -> tuple[dict, dict, dict, dict, dict]:
    seal = root.json("seal.json")
    review_contracts.fields(seal, ("kind", "schema_version", "export_id", "packet_sha256", "template_sha256", "key_sha256"))
    review_contracts.require(seal["kind"] == "mastermind-judge-calibration-seal" and type(seal["schema_version"]) is int
                             and seal["schema_version"] == 1, "unsupported calibration set", "calibration_identity")
    review_contracts.identifier(seal["export_id"], "export-")
    key = root.json("key.json")
    review_contracts.require(root.records["key.json"]["sha256"] == seal["key_sha256"], "calibration key changed", "calibration_identity")
    packet, items, answers, sources = review.load_packet(root, seal)
    review_contracts.fields(key, ("kind", "schema_version", "export_id", "packet_sha256", "source", "items",
                                  "semantics", "comparison_accepted", "quality_uplift"))
    review_contracts.require(key["kind"] == "mastermind-judge-calibration-key" and type(key["schema_version"]) is int
                             and key["schema_version"] == 1
                             and key["export_id"] == seal["export_id"] and key["packet_sha256"] == seal["packet_sha256"]
                             and key["semantics"] == "seeded_defects_not_trial_results"
                             and key["comparison_accepted"] is False and key["quality_uplift"] is None,
                             "invalid calibration key", "calibration_identity")
    review_contracts.require("acceptance_criteria" in packet["rubric"], "seeded defects are scored against acceptance criteria", "judge_schema")
    review_contracts.require(isinstance(key["items"], list) and len(answers) == len(items)
                             and sorted(row.get("review_id") for row in key["items"] if isinstance(row, dict)) == sorted(answers),
                             "the key must label every answer once", "calibration_identity")
    for row in key["items"]:
        check_item(row, packet["rubric"], answers[row["review_id"]], sources)
    return seal, packet, key, answers, sources


def run(path: Path, config: dict, output: Path, key: str) -> dict:
    """Judge every answer of a set; unlike an export, one unresolved answer does not stop the others."""
    path = path.resolve(strict=True)
    output = output.parent.resolve(strict=True) / output.name
    review_contracts.require(not output.is_relative_to(path), "judge output must be outside the calibration set", "review_path")
    with Root(path) as root:
        seal, packet, seeded, answers, sources = load_set(root)
        review_contracts.require(config["reviewer"] != seeded["source"]["reference"],
                                 "the judge cannot be scored against its own reference labels", "calibration_reference")
        template = artifact_io.parse_json(root.read("reviewer/assessment-template.json"))
        judge.check_version(config, key)
        check = judge.checker(template, config, seal, packet, answers, sources)
        output.mkdir(mode=0o700)
        artifact_io.write_new(output / "judge.json", judge.config_record(seal, config))
        results, failure = [], None
        try:
            for position, item in enumerate(template["reviews"], start=1):
                result = {"review_id": item["review_id"], "attempts": [], "review": None}
                results.append(result)
                result["review"] = judge.assess(root, config, key, output, position, template, item, check, result["attempts"])
        except BaseException as error:
            failure = {"code": getattr(error, "code", "judge_error"), "message": str(error)}
            raise
        finally:
            summary = {"kind": "mastermind-judge-calibration-run", "schema_version": 1, "set": str(path),
                       "export_id": seal["export_id"], "key_sha256": seal["key_sha256"], "reviewer": config["reviewer"],
                       "answers": len(template["reviews"]),
                       "assessed_answers": sum(result["review"] is not None for result in results),
                       "items": results, "error": failure, "semantics": "model_declared_against_seeded_defects",
                       "comparison_accepted": False, "quality_uplift": None}
            artifact_io.write_new(output / "calibration-run.json", summary)
    return summary


def spans(text: str, needle: str) -> list[tuple[int, int]]:
    found, start = [], text.find(needle)
    while needle and start >= 0:
        found.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return found


def located(row: dict, verdict: dict, answer: str) -> bool:
    """Whether the judge flagged the element the defect broke, not merely some failure."""
    field = DEFECTS[row["defect"]]
    if field == "criterion_id":
        return any(item["criterion_id"] == row["target"][field] and item["status"] == "unmet" for item in verdict["acceptance"])
    if field == "unknown_index":
        return any(item["unknown_index"] == row["target"][field] and item["handling"] == "overclaimed" for item in verdict["unknowns"])
    passage = spans(answer, row["passage"])
    # A quote that also occurs outside the passage may have meant that other text.
    return any(claim["material_error"] and all(any(quote_start < passage_end and passage_start < quote_end
                                                   for passage_start, passage_end in passage)
                                               for quote_start, quote_end in spans(answer, claim["quote"]))
               for claim in verdict["claims"])


def proportion(successes: int, trials: int) -> dict:
    return {"successes": successes, "trials": trials, "rate": successes / trials if trials else None,
            "lower_95": clopper_pearson_lower(successes, trials) if trials else None}


def gwet_ac1(pairs: list[tuple[str, str]]) -> float | None:
    """Three-category AC1, so an unknown verdict agrees with neither ground truth."""
    if not pairs:
        return None
    agreement = sum(left == right for left, right in pairs) / len(pairs)
    shares = [sum((left == name) + (right == name) for left, right in pairs) / (2 * len(pairs)) for name in OUTCOMES]
    chance = sum(share * (1 - share) for share in shares) / (len(OUTCOMES) - 1)
    return (agreement - chance) / (1 - chance) if chance < 1 else None


def summarize(rows: list[dict]) -> dict:
    resolved = [row for row in rows if row["judged"] is not None]
    controls = [row for row in rows if row["defect"] == "control"]
    mutants = [row for row in rows if row["defect"] != "control"]

    def rates(group, correct):
        settled = [row for row in group if row["judged"] is not None]
        hits = sum(correct(row) for row in settled)
        return {"answers": len(group), "unresolved": len(group) - len(settled),
                "resolved": proportion(hits, len(settled)), "worst_case": proportion(hits, len(group))}

    accepted = lambda row: row["judged"] == "satisfied"
    caught = lambda row: row["judged"] == "unsatisfied"
    found = lambda row: bool(row["located"])
    by_defect = {}
    for defect in sorted({row["defect"] for row in mutants}):
        group = [row for row in mutants if row["defect"] == defect]
        by_defect[defect] = dict(rates(group, caught), located=rates(group, found))
    sensitivity, specificity = rates(controls, accepted), rates(mutants, caught)
    youden = {name: (sensitivity[name]["rate"] + specificity[name]["rate"] - 1
                     if sensitivity[name]["rate"] is not None and specificity[name]["rate"] is not None else None)
              for name in ("resolved", "worst_case")}
    pairs = [(row["judged"], row["expected"]) for row in resolved]
    cases = sorted({row["case"] for row in resolved})
    lower = None
    if len(cases) >= MINIMUM_BOOTSTRAP_CASES:
        rng = random.Random(0)
        draws = sorted(value for value in (
            gwet_ac1([(row["judged"], row["expected"]) for case in (rng.choice(cases) for _ in cases)
                      for row in resolved if row["case"] == case])
            for _ in range(BOOTSTRAP_DRAWS)) if value is not None)
        lower = draws[int(0.05 * len(draws))] if draws else None
    return {"sensitivity": sensitivity, "specificity": specificity, "located": rates(mutants, found),
            "youden_j": youden,
            "gwet_ac1": {"value": gwet_ac1(pairs), "case_bootstrap_lower_95": lower, "cases": len(cases),
                         "minimum_cases_for_bound": MINIMUM_BOOTSTRAP_CASES},
            "by_defect": by_defect}


def score(runs: list[Path], output: Path) -> dict:
    destination = output.parent.resolve(strict=True) / output.name
    rows, identities, seen, runs_seen = [], set(), set(), []
    for directory in runs:
        directory = directory.resolve(strict=True)
        summary = artifact_io.load_json(directory / "calibration-run.json")
        config = artifact_io.load_json(directory / "judge.json")
        review_contracts.require(summary.get("kind") == "mastermind-judge-calibration-run"
                                 and config.get("export_id") == summary.get("export_id")
                                 and config.get("reviewer") == summary.get("reviewer"),
                                 "not a calibration run", "calibration_identity")
        review_contracts.require(summary["error"] is None and len(summary["items"]) == summary["answers"],
                                 "an interrupted run is not scored; judge the set again", "calibration_run")
        identities.add(artifact_io.canonical({name: config[name] for name in (
            "version", "cli", "model", "base_url", "reviewer", "instruction_sha256", "prompt_sha256", "tools",
            "attempts_per_answer", "timeout_seconds")}))
        with Root(Path(summary["set"])) as root:
            seal, packet, key, answers, sources = load_set(root)
            review_contracts.require(seal["export_id"] == summary["export_id"] and seal["key_sha256"] == summary["key_sha256"]
                                     and len(answers) == summary["answers"], "run and set differ", "calibration_identity")
            review_contracts.require(summary["reviewer"] != key["source"]["reference"],
                                     "the judge cannot be scored against its own reference labels", "calibration_reference")
            # The same answer text judged under another set ID is a repeated trial, not a new one.
            digests = {sha(answer.encode()) for answer in answers.values()}
            review_contracts.require(seal["export_id"] not in seen and not digests & seen,
                                     "an answer is scored twice", "calibration_identity")
            seen.update(digests, {seal["export_id"]})
            template = artifact_io.parse_json(root.read("reviewer/assessment-template.json"))
            verdicts = {item["review_id"]: item["review"] for item in summary["items"]}
            review_contracts.require(set(verdicts) == set(answers) and len(verdicts) == len(summary["items"]),
                                     "run labels differ from the set's answers", "calibration_identity")
            runs_seen.append({"set": seal["export_id"], "case": packet["task"]["id"], "answers": len(answers),
                              "assessed_answers": sum(value is not None for value in verdicts.values()),
                              "error": summary["error"]})
            for row in key["items"]:
                verdict, answer = verdicts.get(row["review_id"]), answers[row["review_id"]]
                if verdict is not None:
                    check_assessment(dict(template, reviewer=summary["reviewer"], reviews=[verdict]), seal, packet,
                                     {row["review_id"]: answer}, sources)
                rows.append({"case": packet["task"]["id"], "set": seal["export_id"], "review_id": row["review_id"],
                             "source_review_id": row["source_review_id"], "defect": row["defect"], "target": row["target"],
                             "expected": row["expected_outcome"],
                             "judged": verdict["outcome"]["status"] if verdict else None,
                             "located": located(row, verdict, answer) if verdict and row["defect"] != "control" else None,
                             "material_error": any(claim["material_error"] for claim in verdict["claims"]) if verdict else None})
    review_contracts.require(len(identities) == 1, "runs must share one judge configuration", "calibration_identity")
    report = {"kind": "mastermind-judge-calibration-report", "schema_version": 1,
              "judge": artifact_io.parse_json(identities.pop()), "runs": runs_seen, **summarize(rows), "items": rows,
              "semantics": "agreement_with_seeded_defects_and_reference_labels_not_human_calibration",
              "comparison_accepted": False, "quality_uplift": None}
    artifact_io.write_new(destination, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build", help="build a calibration set from a sealed export")
    make.add_argument("export", type=Path)
    make.add_argument("--mutations", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True, help="new directory outside the export")
    judged = commands.add_parser("run", help="judge every answer of a calibration set")
    judged.add_argument("set", type=Path)
    judged.add_argument("--config", type=Path, required=True)
    judged.add_argument("--output", type=Path, required=True, help="new directory outside the set")
    scored = commands.add_parser("score", help="score calibration runs against their seeded keys")
    scored.add_argument("runs", type=Path, nargs="+")
    scored.add_argument("--output", type=Path, required=True, help="new report file")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(build(args.export, args.mutations, args.output))
            return 0
        if args.command == "score":
            report = score(args.runs, args.output)
            print(artifact_io.canonical({key: report[key] for key in ("sensitivity", "specificity", "youden_j", "gwet_ac1")}).decode())
            return 0
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise artifact_io.BenchmarkError("anthropic_api_key_missing", "bare Claude CLI requires ANTHROPIC_API_KEY")
        summary = run(args.set, judge.load_config(args.config), args.output, key)
        print(artifact_io.canonical({key: summary[key] for key in ("export_id", "answers", "assessed_answers", "error")}).decode())
        return 0 if summary["assessed_answers"] == summary["answers"] else 2
    except (artifact_io.BenchmarkError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"{getattr(error, 'code', 'judge_error')}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
