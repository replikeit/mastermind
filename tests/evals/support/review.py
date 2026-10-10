"""Complete assessments for disposable review exports."""

from evals.benchmark import artifacts as artifact_io


def completed_assessment(export, reviewer="alice"):
    value = artifact_io.load_json(export / "reviewer/assessment-template.json")
    value["reviewer"] = reviewer
    for item in value["reviews"]:
        item["outcome"] = {"status": "unsatisfied", "rationale": "The required value and uncertainty are omitted."}
        item["claims"] = [{"quote": "Observed src/service.py:2.", "support": "supported",
                           "anchors": ["src/service.py:2"], "material_error": False,
                           "rationale": "The cited function returns the fixed value."}]
        item["knowns"] = [{"known_index": 0, "coverage": "partial",
                           "answer_excerpt": "Observed src/service.py:2.",
                           "rationale": "It cites the source but does not state the value."}]
        item["unknowns"] = [{"unknown_index": 0, "handling": "omitted", "answer_excerpt": None,
                             "rationale": "Caller reliance is not discussed."}]
        if "acceptance" in item:
            item["acceptance"] = [{"criterion_id": row["criterion_id"], "status": "unmet", "answer_excerpt": None,
                                   "rationale": "The fixed return value is not stated."} for row in item["acceptance"]]
    return value
