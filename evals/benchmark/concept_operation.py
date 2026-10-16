"""Freeze native operation-search packets, then score separately reviewed results.

This module never invokes a model. Give reviewers only the packet files, without
the suite or preparation manifest, and place their assessments in a new directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata

from . import artifacts, concept_relevance


ROLE_CONTRACT = "operation-roles-v3"
SUPPORTED_ROLE_CONTRACTS = frozenset({"operation-roles-v1", "operation-roles-v2", ROLE_CONTRACT})
ROLES = frozenset({"implementation", "entrypoint", "contract", "essential_helper",
                   "supporting_context"})
WITNESS_ROLES = {"performs_operation": "implementation", "exposes_result": "entrypoint",
                 "operation_contract": "contract", "domain_contribution": "essential_helper",
                 "operation_navigation": "supporting_context",
                 "generic_prerequisite": "supporting_context"}


def _bounded_text(value: object, limit: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= limit
            and not any(unicodedata.category(character) == "Cc" for character in value))


def _request_contract(value: object, query: str) -> dict:
    if (not isinstance(value, dict) or set(value) != {"operation", "constraints"}
            or not _bounded_text(value["operation"], 256)
            or not isinstance(value["constraints"], list) or len(value["constraints"]) > 8):
        raise ValueError("invalid native request contract")
    constraints, texts = {}, set()
    for item in value["constraints"]:
        if (not isinstance(item, dict) or set(item) != {"id", "text", "kind"}
                or not _bounded_text(item["id"], 64) or item["id"] in constraints
                or not _bounded_text(item["text"], 256) or item["text"] not in query
                or item["text"] in texts
                or item["kind"] not in {"input", "state", "scope", "result"}):
            raise ValueError("invalid native query constraint")
        constraints[item["id"]] = item
        texts.add(item["text"])
    return constraints


def _v3_witness(candidate: dict, constraints: dict) -> None:
    value = candidate.get("witness")
    if (not isinstance(value, dict) or set(value) != {"behavior", "relation", "constraint_checks"}
            or not _bounded_text(value["behavior"], 2048)
            or not isinstance(value["relation"], str)
            or WITNESS_ROLES.get(value["relation"]) != candidate["role"]
            or not isinstance(value["constraint_checks"], list)):
        raise ValueError("invalid native operation witness or role relation")
    seen = set()
    for item in value["constraint_checks"]:
        if (not isinstance(item, dict) or set(item) != {"constraint_id", "status", "evidence"}
                or not isinstance(item["constraint_id"], str)
                or item["constraint_id"] not in constraints or item["constraint_id"] in seen
                or item["status"] != "matched" or not isinstance(item["evidence"], list)
                or not 1 <= len(item["evidence"]) <= 16):
            raise ValueError("native useful result has an unproven query constraint")
        seen.add(item["constraint_id"])
        for citation in item["evidence"]:
            if (not isinstance(citation, dict)
                    or set(citation) != {"path", "source_sha256", "start_line", "end_line"}
                    or not _bounded_text(citation["path"], 4096)
                    or not isinstance(citation["source_sha256"], str)
                    or len(citation["source_sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in citation["source_sha256"])
                    or type(citation["start_line"]) is not int
                    or type(citation["end_line"]) is not int
                    or not 1 <= citation["start_line"] <= citation["end_line"]):
                raise ValueError("invalid native constraint evidence")
    if seen != set(constraints):
        raise ValueError("native useful result omits a declared query constraint")


def _role_contract(value: dict) -> str | None:
    if "role_contract" not in value:
        return None
    if (not isinstance(value["role_contract"], str)
            or value["role_contract"] not in SUPPORTED_ROLE_CONTRACTS):
        raise ValueError("unsupported native operation role contract")
    return value["role_contract"]


def _role_page(response: dict, expected_contract: str | None, top: int) -> tuple[list, list, list]:
    if _role_contract(response) != expected_contract:
        raise ValueError("native result role contract does not match its packet")
    useful = response["candidates"]
    if expected_contract is None:
        return useful, [], []
    semantic = response.get("semantic_candidates")
    navigation = response.get("supporting_context")
    ambiguities = response.get("query_ambiguities")
    if (not isinstance(useful, list) or len(useful) > top or not isinstance(semantic, list)
            or not isinstance(navigation, list) or not isinstance(ambiguities, list)
            or len(ambiguities) > 8
            or any(not isinstance(value, str) or not value.strip()
                   or len(value.encode("utf-8")) > 256
                   or any(unicodedata.category(character) == "Cc" for character in value)
                   for value in ambiguities)):
        raise ValueError("invalid native role page or query ambiguities")
    identities = []
    for candidate in useful:
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str)
                or not candidate["id"] or candidate.get("role") not in ROLES):
            raise ValueError("invalid native candidate identity or operation role")
        identities.append(candidate["id"])
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate native useful candidate identity")
    expected_semantic = [row for row in useful if row["role"] != "supporting_context"]
    expected_navigation = [row for row in useful if row["role"] == "supporting_context"]
    if semantic != expected_semantic or navigation != expected_navigation:
        raise ValueError("native semantic and navigation partitions do not match the useful page")
    for candidate in response["unknown_candidates"]:
        if not isinstance(candidate, dict) or candidate.get("role") is not None:
            raise ValueError("invalid native unknown candidate operation role")
    if ambiguities and semantic:
        raise ValueError("ambiguous query cannot yield native semantic operation positives")
    if expected_contract == ROLE_CONTRACT:
        constraints = _request_contract(response.get("request_contract"), response.get("query", ""))
        for candidate in useful:
            _v3_witness(candidate, constraints)
    return semantic, navigation, ambiguities


def _bindings(binary: Path, index: Path, source: Path, suite: Path, hints: Path | None = None,
              request_contracts: Path | None = None) -> dict:
    index_hashes = concept_relevance.index_digest(index)
    return {
        "source_tree_sha256": concept_relevance.source_digest(source),
        "binary_sha256": concept_relevance.file_sha256(binary),
        "index_sha256": index_hashes["database_sha256"],
        "index_wal_sha256": index_hashes["wal_sha256"],
        "suite_sha256": concept_relevance.file_sha256(suite),
        "hints_sha256": concept_relevance.file_sha256(hints) if hints is not None else None,
        "request_contracts_sha256": (concept_relevance.file_sha256(request_contracts)
                                      if request_contracts is not None else None),
        "runner_sha256": concept_relevance.file_sha256(Path(__file__)),
        "sparse_runner_sha256": concept_relevance.file_sha256(Path(concept_relevance.__file__)),
        "artifacts_sha256": concept_relevance.file_sha256(Path(artifacts.__file__)),
    }


def _changed(before: dict, after: dict) -> list[str]:
    return sorted(key for key in before if before[key] != after.get(key))


def _native(binary: Path, index: Path, source: Path, arguments: list[str]) -> dict:
    process = subprocess.run(
        [str(binary), "--index", str(index), "concept-review", *arguments],
        cwd=source, capture_output=True, timeout=90, check=False,
    )
    if process.returncode:
        error = process.stderr
        if isinstance(error, bytes):
            error = error.decode("utf-8", errors="replace")
        raise ValueError(f"exit {process.returncode}: {error[:4096]}")
    body = process.stdout
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > artifacts.FILE_BYTE_LIMIT:
        raise ValueError("native response exceeded the packet byte limit")
    return artifacts.parse_json(body)


def _case(case: dict) -> dict:
    return {key: case[key] for key in ("id", "split", "kind", "query", "top")}


def prepare(binary: Path, index: Path, source: Path, suite_path: Path, output: Path,
            hints_path: Path | None = None, request_contracts_path: Path | None = None) -> dict:
    """Publish every packet and one preparation record, preserving failed cases."""
    binary, index, source, suite_path, output = (
        path.resolve() for path in (binary, index, source, suite_path, output))
    if output.is_relative_to(source):
        raise ValueError("packet output must be outside the frozen source tree")
    suite, suite_hash = concept_relevance.load_suite(suite_path, source)
    hints_hash = None
    hints = {case["id"]: [] for case in suite["cases"]}
    if hints_path is not None:
        hints_path = hints_path.resolve()
        body = artifacts.read_file(hints_path)
        hints = artifacts.parse_json(body)
        hints_hash = hashlib.sha256(body).hexdigest()
        if set(hints) != {case["id"] for case in suite["cases"]}:
            raise ValueError("hints must cover frozen case IDs exactly without missing or extra cases")
        for selected in hints.values():
            if (not isinstance(selected, list) or len(selected) > 8
                    or any(not isinstance(value, str) or len(value.encode("utf-8")) > 64
                           for value in selected)):
                raise ValueError("hints need at most eight strings of at most 64 UTF-8 bytes per case")
    request_contracts, request_contracts_hash = None, None
    if request_contracts_path is not None:
        request_contracts_path = request_contracts_path.resolve()
        body = artifacts.read_file(request_contracts_path)
        request_contracts = artifacts.parse_json(body)
        request_contracts_hash = hashlib.sha256(body).hexdigest()
        if (not isinstance(request_contracts, dict)
                or set(request_contracts) != {case["id"] for case in suite["cases"]}):
            raise ValueError("request contracts must cover frozen case IDs exactly")
        for case in suite["cases"]:
            _request_contract(request_contracts[case["id"]], case["query"])
    before = _bindings(binary, index, source, suite_path, hints_path, request_contracts_path)
    if before["suite_sha256"] != suite_hash:
        raise ValueError("suite input changed while loading")
    if before["hints_sha256"] != hints_hash:
        raise ValueError("hints input changed while loading")
    if before["request_contracts_sha256"] != request_contracts_hash:
        raise ValueError("request contracts changed while loading")
    output.mkdir()
    packets = output / "packets"
    packets.mkdir()
    if request_contracts is not None:
        (output / "request-contracts").mkdir()
    rows = []
    for position, case in enumerate(suite["cases"], 1):
        row = _case(case)
        opaque = hashlib.sha256(case["id"].encode()).hexdigest()[:16]
        filename = f"{position:04d}-{opaque}.json"
        try:
            arguments = ["prepare", case["query"], "--top", str(case["top"])]
            arguments.extend(f"--hint={value}" for value in hints[case["id"]])
            if request_contracts is not None:
                contract_path = output / "request-contracts" / filename
                artifacts.write_new(contract_path, request_contracts[case["id"]])
                arguments.extend(["--request-contract", str(contract_path)])
            packet = _native(binary, index, source, arguments)
            if (packet.get("schema_version") != 1 or packet.get("query") != case["query"]
                    or packet.get("top") != case["top"] or not isinstance(packet.get("candidates"), list)
                    or not isinstance(packet.get("packet_sha256"), str)
                    or packet.get("hints") != hints[case["id"]]):
                raise ValueError("native packet does not match the frozen case")
            role_contract = _role_contract(packet)
            if role_contract == ROLE_CONTRACT:
                _request_contract(packet.get("request_contract"), case["query"])
                if request_contracts is not None and packet["request_contract"] != request_contracts[case["id"]]:
                    raise ValueError("native request contract differs from the frozen query-only contract")
            target = packets / filename
            artifacts.write_new(target, packet)
            row.update(status="prepared", packet_file=f"packets/{filename}",
                       packet_file_sha256=concept_relevance.file_sha256(target),
                       packet_sha256=packet["packet_sha256"], assessment_file=filename,
                       prepared_candidates=len(packet["candidates"]),
                       source_omission_records=len(packet.get("omissions", [])),
                       retrieval_truncated=packet.get("retrieval_truncated"),
                       role_contract=role_contract)
        except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired,
                OSError, artifacts.BenchmarkError) as error:
            row.update(status="failed", stage="prepare", error=str(error))
        rows.append(row)
    after = _bindings(binary, index, source, suite_path, hints_path, request_contracts_path)
    drift = _changed(before, after)
    record = {
        "kind": "mastermind-concept-operation-preparation", "schema_version": 1,
        "status": "input_changed" if drift else "prepared",
        "paths": {"binary": str(binary), "index": str(index), "source": str(source),
                  "suite": str(suite_path), "hints": str(hints_path) if hints_path is not None else None,
                  "request_contracts": str(request_contracts_path) if request_contracts_path else None},
        "source_head": suite["source_head"], "bindings": before,
        "bindings_after": after, "changed_inputs": drift, "cases": rows,
        "reviewer_contract": "Review only packets/*.json. Withhold suite, anchors, case kinds and this manifest.",
        "planned_cases": len(rows), "failed_cases": sum(row["status"] == "failed" for row in rows),
    }
    artifacts.write_new(output / "preparation.json", record)
    return record


def _packet_path(prepared: Path, relative: str) -> Path:
    path = (prepared.parent / relative).resolve()
    if not path.is_relative_to((prepared.parent / "packets").resolve()):
        raise ValueError("prepared packet escaped its packet directory")
    return path


def _summarize(rows: list[dict]) -> dict:
    summaries = concept_relevance.summarize(rows)
    for split, summary in summaries.items():
        selected = [row for row in rows if row["split"] == split]
        completed = [row for row in selected if row["status"] == "completed"]
        incomplete = [row for row in completed if row["review_status"] == "incomplete"]
        uncertain_misses = [row for row in incomplete
                            if row["kind"] == "positive" and not row["anchor_hit"]]
        summary["positive_queries_unknown"] += len(uncertain_misses)
        positive = summary["positive_queries"]
        hits = summary["positive_queries_with_anchor"]
        unknown = summary["positive_queries_unknown"]
        summary["hit_at_k"] = hits / positive if positive and not unknown else None
        summary["hit_at_k_bounds"] = [hits / positive, (hits + unknown) / positive] if positive else None
        summary.update(
            review_complete_cases=len(completed) - len(incomplete),
            review_incomplete_cases=len(incomplete),
            assessment_complete_cases=sum(row["assessment_complete"] for row in completed),
            assessment_incomplete_cases=sum(not row["assessment_complete"] for row in completed),
            coverage_complete_cases=sum(row["coverage_complete"] for row in completed),
            coverage_incomplete_cases=sum(not row["coverage_complete"] for row in completed),
            queries_with_source_omissions=sum(bool(row["source_omission_records"]) for row in completed),
            source_omission_records=sum(row["source_omission_records"] for row in completed),
            retrieval_truncated_queries=sum(row["retrieval_truncated"] for row in completed),
            result_truncated_queries=sum(row["result_truncated"] for row in completed),
            raw_positive_queries_with_anchor=sum(bool(row["anchor_hit"]) for row in completed
                                                 if row["kind"] == "positive"),
            raw_anchor_observations=sum(row["anchors_found"] for row in completed
                                        if row["kind"] == "positive"),
            raw_anchor_observations_in_incomplete_reviews=sum(row["anchors_found"] for row in incomplete
                                                              if row["kind"] == "positive"),
            unknown_candidates=sum(row["unknown_candidates_count"] for row in completed),
            negative_queries_review_incomplete=sum(row["kind"] == "negative" for row in incomplete),
            negative_queries_known_empty=sum(row["kind"] == "negative" and not row["returned_rows"]
                                             and row["review_status"] == "complete" for row in completed),
            role_aware_cases=sum(row["role_contract"] in SUPPORTED_ROLE_CONTRACTS for row in completed),
            useful_returned_rows=sum(row["useful_returned_rows"] for row in completed),
            semantic_returned_rows=sum(row["returned_rows"] for row in completed),
            navigation_returned_rows=sum(row["navigation_returned_rows"] for row in completed),
            queries_with_navigation=sum(bool(row["navigation_returned_rows"]) for row in completed),
            queries_with_ambiguities=sum(bool(row["query_ambiguities"]) for row in completed),
            query_ambiguity_records=sum(len(row["query_ambiguities"]) for row in completed),
            positive_queries_with_useful_results=sum(row["kind"] == "positive"
                                                     and bool(row["useful_returned_rows"])
                                                     for row in completed),
            positive_queries_with_semantic_results=sum(row["kind"] == "positive"
                                                       and bool(row["returned_rows"])
                                                       for row in completed),
            negative_queries_with_navigation=sum(row["kind"] == "negative"
                                                 and bool(row["navigation_returned_rows"])
                                                 for row in completed),
        )
    return summaries


def finish(prepared_path: Path, assessments: Path) -> dict:
    """Finish stable packets with external assessments; missing assessments fail visibly."""
    prepared_path, assessments = prepared_path.resolve(), assessments.resolve()
    prepared_hash = concept_relevance.file_sha256(prepared_path)
    prepared = artifacts.load_json(prepared_path)
    if (prepared.get("kind") != "mastermind-concept-operation-preparation"
            or prepared.get("schema_version") != 1 or prepared.get("status") != "prepared"):
        raise ValueError("expected stable operation-search preparation")
    paths = {key: Path(value) if value is not None else None for key, value in prepared["paths"].items()}
    before = _bindings(paths["binary"], paths["index"], paths["source"], paths["suite"],
                       paths.get("hints"), paths.get("request_contracts"))
    drift = _changed(prepared["bindings"], before)
    if drift:
        raise ValueError(f"evaluation input changed since prepare: {', '.join(drift)}")
    suite, _ = concept_relevance.load_suite(paths["suite"], paths["source"])
    expected_cases = {case["id"]: case for case in suite["cases"]}
    prepared_cases = prepared["cases"]
    if (len(prepared_cases) != len(expected_cases)
            or {row["id"] for row in prepared_cases} != set(expected_cases)):
        raise ValueError("preparation does not cover the frozen suite exactly")
    for row in prepared_cases:
        if _case(row) != _case(expected_cases[row["id"]]):
            raise ValueError("prepared case changed relative to frozen suite")
    expected_assessments = {row["assessment_file"] for row in prepared_cases if row["status"] == "prepared"}
    observed_assessments = {path.name for path in assessments.iterdir()}
    extra = sorted(observed_assessments - expected_assessments)
    if extra:
        raise ValueError(f"unexpected assessment files: {', '.join(extra)}")
    packet_hashes, assessment_hashes = {}, {}
    for row in prepared_cases:
        if row["status"] != "prepared":
            continue
        packet_path = _packet_path(prepared_path, row["packet_file"])
        packet_hash = concept_relevance.file_sha256(packet_path)
        if packet_hash != row["packet_file_sha256"]:
            raise ValueError(f"prepared packet changed: {row['packet_file']}")
        packet_hashes[str(packet_path)] = packet_hash
        assessment = assessments / row["assessment_file"]
        if assessment.name in observed_assessments:
            assessment_hashes[str(assessment)] = hashlib.sha256(artifacts.read_file(assessment)).hexdigest()
    rows = []
    for row in prepared_cases:
        case = expected_cases[row["id"]]
        if row["status"] != "prepared":
            rows.append({**_case(case), "status": "failed", "stage": "prepare", "error": row["error"]})
            continue
        assessment = assessments / row["assessment_file"]
        try:
            if str(assessment) not in assessment_hashes:
                raise ValueError("assessment is missing")
            packet_path = _packet_path(prepared_path, row["packet_file"])
            packet = artifacts.load_json(packet_path)
            role_contract = _role_contract(packet)
            if role_contract != row.get("role_contract"):
                raise ValueError("prepared role contract does not match its packet")
            response = _native(paths["binary"], paths["index"], paths["source"],
                               ["finish", "--packet", str(packet_path), "--assessment", str(assessment)])
            unknown = response.get("unknown_candidates")
            review_status = response.get("review_status")
            assessment_complete = response.get("assessment_complete")
            coverage_complete = response.get("coverage_complete")
            omissions = response.get("omissions")
            retrieval_truncated = response.get("retrieval_truncated")
            result_truncated = response.get("result_truncated")
            semantic, navigation, ambiguities = _role_page(response, role_contract, case["top"])
            if role_contract == ROLE_CONTRACT and response.get("request_contract") != packet["request_contract"]:
                raise ValueError("native result changed the bound request contract")
            if (response.get("packet_sha256") != row["packet_sha256"]
                    or review_status not in {"complete", "incomplete"} or not isinstance(unknown, list)
                    or type(assessment_complete) is not bool or type(coverage_complete) is not bool
                    or type(retrieval_truncated) is not bool or type(result_truncated) is not bool
                    or not isinstance(omissions, list)
                    or assessment_complete != (not unknown)
                    or coverage_complete != (not omissions and not retrieval_truncated)
                    or (review_status == "complete") != (assessment_complete and coverage_complete
                                                         and not ambiguities)):
                raise ValueError("native review result does not match its packet or uncertainty contract")
            if role_contract is None:
                for candidate in response["candidates"]:
                    if "line" not in candidate and "line_start" in candidate:
                        candidate["line"] = candidate["line_start"]
            scored = concept_relevance.score_case(case, {**response, "candidates": semantic})
            scored["response"] = response
            scored.update(review_status=review_status, unknown_candidates_count=len(unknown),
                          assessment_complete=assessment_complete, coverage_complete=coverage_complete,
                          source_omission_records=len(omissions), retrieval_truncated=retrieval_truncated,
                          result_truncated=result_truncated,
                          role_contract=role_contract,
                          useful_returned_rows=len(response["candidates"]),
                          navigation_returned_rows=len(navigation), query_ambiguities=ambiguities,
                          packet_sha256=row["packet_sha256"],
                          assessment_sha256=assessment_hashes[str(assessment)])
            rows.append(scored)
        except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired,
                OSError, artifacts.BenchmarkError) as error:
            rows.append({**_case(case), "status": "failed", "stage": "finish", "error": str(error)})
    after = _bindings(paths["binary"], paths["index"], paths["source"], paths["suite"],
                      paths.get("hints"), paths.get("request_contracts"))
    drift = _changed(before, after)
    if concept_relevance.file_sha256(prepared_path) != prepared_hash:
        drift.append("preparation_sha256")
    for path, expected in {**packet_hashes, **assessment_hashes}.items():
        if concept_relevance.file_sha256(Path(path)) != expected:
            drift.append(path)
    if {path.name for path in assessments.iterdir()} != observed_assessments:
        drift.append("assessment_inventory")
    if drift:
        raise ValueError(f"evaluation input changed during finish: {', '.join(drift)}")
    return {
        "kind": "mastermind-concept-operation-relevance", "schema_version": 1,
        "source_head": prepared["source_head"], **before,
        "preparation_sha256": prepared_hash, "summary": _summarize(rows), "cases": rows,
        "packet_file_sha256": packet_hashes, "assessment_file_sha256": assessment_hashes,
        "assessment_coverage": {"expected": len(expected_assessments), "provided": len(observed_assessments),
                                "missing": sorted(expected_assessments - observed_assessments)},
        "limitations": [
            "External source review is separate from deterministic harness verification.",
            "Sparse frozen anchors do not label every emitted result.",
            "Unknown review candidates remain separate; incomplete empty negatives are not known-empty results.",
            "Role-aware hit and precision measurements exclude supporting context; raw responses retain the useful page.",
            "Legacy packets without a role contract retain their original unpartitioned measurement behavior.",
            "Failed and missing assessments remain in planned query denominators.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("prepare")
    for name in ("binary", "index", "source", "suite"):
        first.add_argument(f"--{name}", type=Path, required=True)
    first.add_argument("--output-dir", type=Path, required=True)
    first.add_argument("--hints", type=Path,
                       help="frozen JSON mapping every case ID to optional client recall hints")
    first.add_argument("--request-contracts", type=Path,
                       help="query-only JSON contracts fixed before candidate inspection, keyed by case ID")
    last = commands.add_parser("finish")
    last.add_argument("--prepared", type=Path, required=True)
    last.add_argument("--assessments", type=Path, required=True)
    last.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.binary, args.index, args.source, args.suite, args.output_dir,
                             args.hints, args.request_contracts)
            print(json.dumps({key: result[key] for key in ("status", "planned_cases", "failed_cases", "changed_inputs")}))
            return int(result["status"] != "prepared" or bool(result["failed_cases"]))
        result = finish(args.prepared, args.assessments)
        artifacts.write_new(args.output, result)
        print(json.dumps(result["summary"], indent=2))
        return int(any(row["status"] == "failed" for row in result["cases"]))
    except (ValueError, OSError, artifacts.BenchmarkError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
