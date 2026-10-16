"""Measure sparse concept anchors through a compiled mmcg CLI, without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from . import artifacts


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(root: Path) -> str:
    """Bind every file in the disposable source tree, excluding derived state."""
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".mastermind", "target", "__pycache__"} for part in relative.parts):
            continue
        if path.is_file():
            files[relative.as_posix()] = file_sha256(path)
    return artifacts.digest(files)


def load_suite(path: Path, source: Path) -> tuple[dict, str]:
    body = artifacts.read_file(path)
    suite = artifacts.parse_json(body)
    if suite.get("schema_version") != 1 or not suite.get("cases"):
        raise ValueError("expected a nonempty concept relevance suite v1")
    for relative, expected in suite["source_files_sha256"].items():
        selected = (source / relative).resolve()
        if not selected.is_relative_to(source.resolve()) or file_sha256(selected) != expected:
            raise ValueError(f"fixture source changed: {relative}")
    identifiers = set()
    for case in suite["cases"]:
        if case["id"] in identifiers:
            raise ValueError("duplicate relevance case id")
        identifiers.add(case["id"])
        if case["kind"] not in {"positive", "negative"}:
            raise ValueError("unknown relevance case kind")
        if (case["kind"] == "positive") != bool(case["relevant"]):
            raise ValueError("positive cases need source anchors; negative cases must have none")
    return suite, hashlib.sha256(body).hexdigest()


def index_digest(index: Path) -> dict:
    # A writer may commit into WAL without changing the main SQLite file.
    wal = index.with_name(index.name + "-wal")
    return {"database_sha256": file_sha256(index),
            "wal_sha256": file_sha256(wal) if wal.exists() else None}


def anchor_key(anchor: dict) -> tuple[str, str]:
    return anchor["path"], anchor["symbol"]


def score_case(case: dict, response: dict) -> dict:
    relevant = {anchor_key(anchor) for anchor in case["relevant"]}
    distractors = {anchor_key(anchor) for anchor in case.get("distractors", [])}
    if relevant & distractors:
        raise ValueError("conflicting relevance judgments")
    rows = response["candidates"]
    if not isinstance(rows, list) or len(rows) > case["top"]:
        raise ValueError("invalid bounded candidate page")
    hits, judgments, ranks = set(), [], []
    for rank, row in enumerate(rows, 1):
        key = row["path"], row["name"]
        judgment = "unjudged"
        if key in relevant:
            hits.add(key)
            ranks.append(rank)
            judgment = "relevant"
        elif key in distractors:
            judgment = "distractor"
        judgments.append({"rank": rank, "path": key[0], "symbol": key[1], "judgment": judgment})
    judged = [row for row in judgments if row["judgment"] != "unjudged"]
    return {
        "id": case["id"], "split": case["split"], "kind": case["kind"],
        "query": case["query"], "top": case["top"], "status": "completed",
        "anchor_count": len(relevant), "anchors_found": len(hits),
        "anchor_hit": bool(hits) if relevant else None,
        "anchor_recall": len(hits) / len(relevant) if relevant else None,
        "first_relevant_rank": min(ranks) if ranks else None,
        "returned_rows": len(rows), "judged_rows": len(judged),
        "relevant_rows": len(ranks), "unjudged_rows": len(rows) - len(judged),
        "judged_precision": len(ranks) / len(judged) if judged else None,
        "negative_returned_rows": len(rows) if case["kind"] == "negative" else None,
        "judgments": judgments, "response": response,
    }


def summarize(rows: list[dict]) -> dict:
    result = {}
    for split in sorted({row["split"] for row in rows}):
        selected = [row for row in rows if row["split"] == split]
        positives = [row for row in selected if row["kind"] == "positive"]
        completed = [row for row in selected if row["status"] == "completed"]
        known_positives = [row for row in completed if row["kind"] == "positive"]
        negatives = [row for row in completed if row["kind"] == "negative"]
        unknown = len(positives) - len(known_positives)
        hits = sum(row["anchor_hit"] for row in known_positives)
        judged = sum(row["judged_rows"] for row in completed)
        relevant = sum(row["relevant_rows"] for row in completed)
        anchors = sum(row["anchor_count"] for row in known_positives)
        result[split] = {
            "planned_cases": len(selected), "completed_cases": len(completed),
            "failed_cases": len(selected) - len(completed), "positive_queries": len(positives),
            "positive_queries_unknown": unknown, "positive_queries_with_anchor": hits,
            "hit_at_k": hits / len(positives) if positives and not unknown else None,
            "hit_at_k_bounds": [hits / len(positives), (hits + unknown) / len(positives)] if positives else None,
            "observed_anchor_recall": sum(row["anchors_found"] for row in known_positives) / anchors if anchors else None,
            "judged_rows": judged, "unjudged_rows": sum(row["unjudged_rows"] for row in completed),
            "judged_precision": relevant / judged if judged else None,
            "negative_queries": sum(row["kind"] == "negative" for row in selected),
            "negative_queries_completed": len(negatives),
            "negative_queries_with_candidates": sum(row["returned_rows"] > 0 for row in negatives),
            "negative_returned_rows": sum(row["returned_rows"] for row in negatives),
        }
    return result


def evaluate(binary: Path, index: Path, source: Path, suite_path: Path) -> dict:
    suite, suite_hash = load_suite(suite_path, source)
    binary_hash, before = file_sha256(binary), source_digest(source)
    index_before, runner_hash = index_digest(index), file_sha256(Path(__file__))
    rows = []
    for case in suite["cases"]:
        try:
            process = subprocess.run(
                [str(binary), "--index", str(index), "concept", case["query"],
                 "--top", str(case["top"]), "--format", "json"],
                cwd=source, capture_output=True, text=True, timeout=90, check=False,
            )
            if process.returncode:
                raise ValueError(f"exit {process.returncode}: {process.stderr[:4096]}")
            rows.append(score_case(case, json.loads(process.stdout)))
        except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired, OSError) as error:
            rows.append({"id": case["id"], "split": case["split"], "kind": case["kind"],
                         "query": case["query"], "status": "failed", "error": str(error)})
    if (source_digest(source) != before or file_sha256(binary) != binary_hash
            or file_sha256(suite_path) != suite_hash or index_digest(index) != index_before
            or file_sha256(Path(__file__)) != runner_hash):
        raise ValueError("evaluation input changed during relevance evaluation")
    return {
        "kind": "mastermind-concept-relevance", "schema_version": 1,
        "source_head": suite["source_head"], "source_tree_sha256": before,
        "suite_sha256": suite_hash, "binary_sha256": binary_hash,
        "index_sha256": index_before["database_sha256"], "index_wal_sha256": index_before["wal_sha256"],
        "runner_sha256": runner_hash,
        "summary": summarize(rows), "cases": rows,
        "limitations": [
            "Purposive single-repository queries; no population or model-quality inference",
            "Sparse anchors: unlabeled rows remain unjudged, not false positives",
            "Failed queries stay in planned denominators and make point hit@k unknown",
            "An unsupported-domain lexical candidate does not establish that capability",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path("evals/fixtures/concept-relevance.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.binary.resolve(), args.index.resolve(), args.source.resolve(), args.suite.resolve())
    artifacts.write_new(args.output, report)
    print(json.dumps(report["summary"], indent=2))
    if any(row["status"] == "failed" for row in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
