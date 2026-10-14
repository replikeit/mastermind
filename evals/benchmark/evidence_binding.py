"""Literal source-quote binding, separate from reviewer semantic judgments."""

from __future__ import annotations

from . import artifacts, corpus, review_contracts
from .review_io import sha


STATUSES = ("valid", "invalid", "unverifiable")


def validate_source_quotes(claim):
    """Validate optional declarations without deciding whether they match source bytes."""
    quotes = claim.get("source_quotes", [])
    review_contracts.require(isinstance(quotes, list) and len(quotes) <= 16,
                             "invalid literal source quotes", "review_source_quote")
    seen = set()
    for row in quotes:
        review_contracts.fields(row, ("anchor", "source_sha256", "quote"))
        anchor = review_contracts.text(row["anchor"], 1024)
        review_contracts.require(anchor in claim["anchors"] and anchor not in seen,
                                 "source quote needs a distinct declared anchor", "review_source_quote")
        seen.add(anchor)
        review_contracts.hash_value(row["source_sha256"])
        review_contracts.text(row["quote"])


def _snapshot(body):
    # The corpus numbers lines by LF, not Unicode separators or standalone CR.
    parts = body.split(b"\n")
    lines = [part + b"\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return {"sha256": sha(body), "bytes": len(body), "lines": lines}


def _anchor_result(anchor, quote, sources, snapshots):
    result = {"anchor": anchor}
    if quote is not None:
        result["quote_sha256"] = sha(quote["quote"].encode("utf-8"))
    try:
        corpus.validate_anchors([anchor], sources)
    except artifacts.BenchmarkError as error:
        return dict(result, status="invalid", reason=error.code)
    path, _, span = anchor.rpartition(":")
    snapshot = snapshots.get(path)
    if snapshot is None:
        return dict(result, status="unverifiable", reason="source_unavailable")
    result["source_sha256"] = snapshot["sha256"]
    record = sources[path]
    if (snapshot["sha256"] != record["sha256"] or snapshot["bytes"] != record["bytes"]
            or len(snapshot["lines"]) != record["lines"]):
        return dict(result, status="invalid", reason="source_snapshot_mismatch")
    if quote is None:
        return dict(result, status="unverifiable", reason="source_quote_missing")
    if quote["source_sha256"] != snapshot["sha256"]:
        return dict(result, status="invalid", reason="source_digest_mismatch")
    bounds = [int(value) for value in span.split("-")]
    fragment = b"".join(snapshot["lines"][bounds[0] - 1:bounds[-1]])
    if quote["quote"].encode("utf-8") not in fragment:
        return dict(result, status="invalid", reason="source_quote_outside_span")
    return dict(result, status="valid", reason="quote_bound")


def audit(assessments, sources, source_bodies):
    """Audit validated assessments against a pinned snapshot; never change their grades."""
    snapshots = {path: _snapshot(body) for path, body in source_bodies.items() if path in sources}
    counts = {name: dict.fromkeys(STATUSES, 0) for name in ("claims", "anchors")}
    records = []
    for assessment in assessments:
        reviews = []
        for item in assessment["reviews"]:
            claims = []
            for index, claim in enumerate(item["claims"]):
                validate_source_quotes(claim)
                quotes = {row["anchor"]: row for row in claim.get("source_quotes", [])}
                anchors = [_anchor_result(anchor, quotes.get(anchor), sources, snapshots)
                           for anchor in claim["anchors"]]
                statuses = {row["status"] for row in anchors}
                status = ("invalid" if "invalid" in statuses else "valid" if statuses == {"valid"}
                          else "unverifiable")
                claims.append({"claim_index": index, "status": status, "anchors": anchors})
                counts["claims"][status] += 1
                for row in anchors:
                    counts["anchors"][row["status"]] += 1
            reviews.append({"review_id": item["review_id"], "answer_sha256": item["answer_sha256"],
                            "claims": claims})
        records.append({"reviewer": assessment["reviewer"],
                        "assessment_sha256": artifacts.digest(assessment), "reviews": reviews})
    return {"summary": {"assessments": len(records), **counts}, "assessments": records}
