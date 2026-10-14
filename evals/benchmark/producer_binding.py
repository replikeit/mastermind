"""Parse optional Markdown source snippets and audit their literal source bindings.

``audit_answer`` accepts answer text, a pinned inventory keyed by canonical
repository path (``lines``, ``bytes``, ``sha256``), and the corresponding source
bytes. ``source_prefix`` may identify a trusted source root already bound to the
request. No filesystem, model, semantic grading, or source-path guessing occurs.
"""

from __future__ import annotations

import re
import unicodedata

from . import artifacts, evidence_binding
from .review_io import sha


PARSER_VERSION = "mastermind-producer-binding-v4"
ANSWER_BYTE_LIMIT = 16 * 1024 * 1024
SNIPPET_BYTE_LIMIT = 16 * 1024
MAX_CITATIONS = 4096
MAX_FENCES = 4096

PARSER_CONTRACT = {
    "citations": "whitespace-free inventory path/basename or filelike path:line or path:first-last (ASCII hyphen or en dash); LF source line numbering",
    "fences": "backticks or tildes, zero to three leading spaces; closing marker has the same kind and at least the opening length",
    "adjacency": "citation-before-fence preferred within punctuation-adjacent runs; one citation and one fence per pair; reverse fallback never reuses a preceding fence",
    "framing": "check fixed raw and CommonMark-dedented body candidates after removing one final LF or CRLF; raw-only matches are unverifiable",
    "paths": "exact inventory path, trusted root prefix, or unique inventory basename",
    "unsafe_paths": "URLs, backslashes, traversal components, and network roots are never reinterpreted",
    "indented_code": "lines with four leading spaces or a leading tab are excluded; they prevent snippet association",
    "offsets": "half-open Unicode character spans in the original answer",
    "limits": {"answer_bytes": ANSWER_BYTE_LIMIT, "snippet_bytes": SNIPPET_BYTE_LIMIT,
               "citations": MAX_CITATIONS, "fences": MAX_FENCES},
    "semantics": "literal binding only; semantic acceptance is not recomputed",
}

_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
_OPEN = re.compile(r"(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>[^\n]*)\Z")
_CLOSE = re.compile(r" {0,3}(?P<marker>`{3,}|~{3,})[ \t]*\Z")
_TOKEN = re.compile(r"[^\s`\[\](){}*<>\"',;]+")
_SPAN = re.compile(r"[0-9]+(?:[-–][0-9]+)?\Z")
_BOUNDS = re.compile(r"[1-9][0-9]{0,9}(?:[-–][1-9][0-9]{0,9})?\Z")
_INDENTED = re.compile(r" {4}| {0,3}\t")


def _fences(answer):
    blocks, current = [], None
    for line in _LINE.finditer(answer):
        text = line.group()
        if text.endswith("\n"):
            text = text[:-1].removesuffix("\r")
        if current is not None:
            closing = _CLOSE.fullmatch(text)
            if (closing and closing["marker"][0] == current["marker"]
                    and len(closing["marker"]) >= current["marker_length"]):
                current.update(answer_span=[current["answer_span"][0], line.end()],
                               body_span=[current["body_span"][0], line.start()],
                               closing_marker_length=len(closing["marker"]), closed=True)
                blocks.append(current)
                if len(blocks) > MAX_FENCES:
                    raise artifacts.BenchmarkError("producer_fence_limit", "answer has too many fenced blocks")
                current = None
            continue
        opening = _OPEN.fullmatch(text)
        if opening and not (opening["marker"][0] == "`" and "`" in opening["info"]):
            current = {"answer_span": [line.start(), len(answer)],
                       "body_span": [line.end(), len(answer)],
                       "opening_indent": len(opening["indent"]),
                       "marker": opening["marker"][0], "marker_length": len(opening["marker"]),
                       "closing_marker_length": None, "closed": False}
    if current is not None:
        blocks.append(current)
        if len(blocks) > MAX_FENCES:
            raise artifacts.BenchmarkError("producer_fence_limit", "answer has too many fenced blocks")
    return blocks


def _source_reference(path, sources, basenames):
    basename = path.rsplit("/", 1)[-1]
    return (path in sources or path in basenames or "/" in path or "\\" in path
            or ("." in basename and not basename.endswith(".")))


def _outside_citations(answer, blocks, sources, basenames):
    rows, cursor = [], 0
    for block in [*blocks, None]:
        end = block["answer_span"][0] if block is not None else len(answer)
        for line in _LINE.finditer(answer, cursor, end):
            if _INDENTED.match(line.group()):
                continue
            for token in _TOKEN.finditer(answer, line.start(), line.end()):
                reference = token.group().rstrip(".!?:")
                path, separator, span = reference.rpartition(":")
                if path and separator and _SPAN.fullmatch(span) and _source_reference(path, sources, basenames):
                    rows.append({"original_citation": reference, "original_path": path,
                                 "answer_span": [token.start(), token.start() + len(reference)],
                                 "line_span": span})
                    if len(rows) > MAX_CITATIONS:
                        raise artifacts.BenchmarkError("producer_citation_limit", "answer has too many source citations")
        if block is not None:
            cursor = block["answer_span"][1]
    return rows


def _adjacent(text):
    return (not any(_INDENTED.match(line.group()) and line.group().strip() for line in _LINE.finditer(text))
            and all(char.isspace() or char == "`" or unicodedata.category(char).startswith("P")
                    for char in text))


def _associate(answer, citations, blocks):
    events = sorted([(row["answer_span"], "citation", index) for index, row in enumerate(citations)]
                    + [(row["answer_span"], "fence", index) for index, row in enumerate(blocks)])
    groups, current = [], []
    for event in events:
        if current and not _adjacent(answer[current[-1][0][1]:event[0][0]]):
            groups.append(current)
            current = []
        current.append(event)
    if current:
        groups.append(current)
    paired, reasons = {}, {}
    for group in groups:
        runs = []
        for _, kind, index in group:
            if not runs or runs[-1][0] != kind:
                runs.append((kind, []))
            runs[-1][1].append(index)
        consumed = set()
        for position, (kind, references) in enumerate(runs):
            if kind != "citation":
                continue
            if position + 1 < len(runs):
                fences = runs[position + 1][1]
            elif position and not any(index in consumed for index in runs[position - 1][1]):
                fences = runs[position - 1][1]
            else:
                continue
            # Even an ambiguous preceding pair reserves its fence run.
            consumed.update(fences)
            if len(references) == len(fences) == 1:
                if blocks[fences[0]]["closed"]:
                    paired[references[0]] = fences[0]
                else:
                    reasons[references[0]] = "producer_quote_unclosed"
            else:
                reasons.update((index, "producer_quote_ambiguous") for index in references)
    return paired, reasons


def _resolve(path, sources, basenames, prefix):
    if (":" in path or "\\" in path or any(part in {".", ".."} for part in path.split("/"))
            or path.startswith("//")):
        return None, {"reason": "producer_source_unsafe"}, "invalid"
    if path in sources:
        return path, {"reason": "source_path_exact"}, None
    if prefix is not None and path.startswith(prefix):
        suffix = path[len(prefix):]
        if suffix in sources:
            return suffix, {"reason": "source_prefix_exact"}, None
        return None, {"reason": "producer_source_unknown"}, "invalid"
    if "/" not in path:
        candidates = basenames.get(path, [])
        if len(candidates) == 1:
            return candidates[0], {"reason": "source_basename_unique"}, None
        if candidates:
            return None, {"reason": "producer_source_ambiguous", "candidates": candidates}, "unverifiable"
    return None, {"reason": "producer_source_unknown"}, "invalid"


def _bounds_reason(span):
    if not _BOUNDS.fullmatch(span):
        return "corpus_anchor_invalid"
    bounds = [int(value) for value in span.replace("–", "-").split("-")]
    return "corpus_anchor_range" if bounds[0] > bounds[-1] else None


def _quote(answer, block):
    body = answer[slice(*block["body_span"])]
    raw_bytes = body.encode("utf-8")
    indent = block["opening_indent"]
    parts, removed, changed = [], 0, 0
    for line in _LINE.finditer(body):
        text = line.group()
        count = min(indent, len(text) - len(text.lstrip(" ")))
        parts.append(text[count:])
        removed += count
        changed += int(bool(count))
    quote = "".join(parts)
    framing = "\r\n" if body.endswith("\r\n") else "\n" if body.endswith("\n") else ""
    if framing:
        quote = quote[:-len(framing)]
        body = body[:-len(framing)]
    metadata = dict(block, removed_indentation_spaces=removed, indented_body_lines=changed,
                    removed_final_linebreak=framing, raw_body_bytes=len(raw_bytes),
                    raw_body_sha256=sha(raw_bytes))
    return quote, body, metadata


def audit_answer(answer: str, sources: dict, source_bodies: dict, *, source_prefix: str | None = None) -> dict:
    """Audit optional adjacent snippets against pinned bytes; return diagnostics, not grades."""
    try:
        body = answer.encode("utf-8") if isinstance(answer, str) else None
    except UnicodeError as error:
        raise artifacts.BenchmarkError("producer_answer_invalid", "answer must be UTF-8 text") from error
    if body is None:
        raise artifacts.BenchmarkError("producer_answer_invalid", "answer must be UTF-8 text")
    if len(body) > ANSWER_BYTE_LIMIT:
        raise artifacts.BenchmarkError("producer_answer_limit", "answer exceeds the citation audit byte cap")
    if source_prefix is not None and (not isinstance(source_prefix, str) or not source_prefix.startswith("/")):
        raise artifacts.BenchmarkError("producer_source_prefix", "trusted source prefix must be an absolute path")
    prefix = source_prefix.rstrip("/") + "/" if source_prefix is not None else None
    basenames = {}
    for path in sorted(sources):
        basenames.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    blocks = _fences(answer)
    references = _outside_citations(answer, blocks, sources, basenames)
    paired, pairing_reasons = _associate(answer, references, blocks)
    bindings, claims, claim_indices, quote_reasons = [], [], [], {}
    for index, reference in enumerate(references):
        row = dict(reference, resolved_path=None, anchor=None, quote=None, fence=None,
                   quote_match_mode=None)
        path, resolution, status = _resolve(reference["original_path"], sources, basenames, prefix)
        row.update(resolved_path=path, resolution=resolution)
        if path is not None:
            row["source_sha256"] = sources[path]["sha256"]
        quote, raw_quote = None, None
        if index in paired:
            quote, raw_quote, row["fence"] = _quote(answer, blocks[paired[index]])
            for mode, candidate in (("rendered", quote), ("raw", raw_quote)):
                quoted_bytes = candidate.encode("utf-8")
                field_prefix = "" if mode == "rendered" else "raw_"
                row.update({field_prefix + "quote_sha256": sha(quoted_bytes),
                            field_prefix + "quote_bytes": len(quoted_bytes)})
                if len(quoted_bytes) > SNIPPET_BYTE_LIMIT:
                    quote_reasons[index, mode] = "producer_quote_limit"
                elif not candidate.strip():
                    quote_reasons[index, mode] = "producer_quote_blank"
            if len(quote.encode("utf-8")) <= SNIPPET_BYTE_LIMIT:
                row["quote"] = quote
        if index in pairing_reasons:
            quote_reasons[index, "rendered"] = pairing_reasons[index]
        bounds_reason = _bounds_reason(reference["line_span"])
        if bounds_reason:
            row.update(status="invalid", reason=bounds_reason)
        elif status is not None:
            row.update(status=status, reason=resolution["reason"])
        else:
            anchor = path + ":" + reference["line_span"].replace("–", "-")
            row["anchor"] = anchor
            if len(anchor.encode("utf-8")) > 1024:
                row.update(status="invalid", reason="producer_source_path_limit")
            else:
                candidates = [("rendered", quote)]
                if raw_quote is not None:
                    candidates.append(("raw", raw_quote))
                for mode, candidate in candidates:
                    quotes = ([] if candidate is None or (index, mode) in quote_reasons else
                              [{"anchor": anchor, "source_sha256": sources[path]["sha256"],
                                "quote": candidate}])
                    claims.append({"anchors": [anchor], "source_quotes": quotes})
                    claim_indices.append((index, mode))
        bindings.append(row)
    diagnostic = {"reviewer": "producer-literal-diagnostic", "reviews": [
        {"review_id": "producer-answer", "answer_sha256": sha(body), "claims": claims}]}
    audit = evidence_binding.audit([diagnostic], sources, source_bodies)
    results = {}
    for (index, mode), claim in zip(claim_indices, audit["assessments"][0]["reviews"][0]["claims"]):
        result = claim["anchors"][0]
        row = bindings[index]
        status, reason = result["status"], result["reason"]
        if (index, mode) in quote_reasons and status != "invalid":
            status, reason = "unverifiable", quote_reasons[index, mode]
        results[index, mode] = status, reason
        if mode == "rendered" and "source_sha256" in result:
            row["observed_source_sha256"] = result["source_sha256"]
    for index, mode in claim_indices:
        if mode != "rendered":
            continue
        row = bindings[index]
        status, reason = results[index, "rendered"]
        raw = results.get((index, "raw"))
        if raw is not None:
            rendered_bound, raw_bound = status == "valid", raw[0] == "valid"
            rendered_absent = reason == "source_quote_outside_span"
            raw_absent = raw[1] == "source_quote_outside_span"
            row["quote_match_mode"] = ("both" if rendered_bound and raw_bound else
                                       "rendered_only" if rendered_bound and raw_absent else
                                       "raw_only" if raw_bound and rendered_absent else
                                       "neither" if rendered_absent and raw_absent else None)
            if rendered_absent and raw_bound:
                status, reason = "unverifiable", "producer_quote_raw_only"
            elif rendered_absent and raw[0] == "unverifiable":
                status, reason = raw
        row.update(status=status, reason=reason)
    counts = dict.fromkeys(evidence_binding.STATUSES, 0)
    for row in bindings:
        counts[row["status"]] += 1
    return {"kind": "mastermind-producer-literal-binding", "schema_version": 1,
            "parser_version": PARSER_VERSION, "parser_contract": dict(PARSER_CONTRACT),
            "answer_sha256": sha(body), "source_inventory_sha256": artifacts.digest(sources),
            "source_digest_origin": "pinned_inventory_not_producer_declaration",
            "summary": {"citation_count": len(bindings), "citations": counts,
                        "fences": {"observed": len(blocks), "associated": len(paired),
                                   "unclosed": sum(not block["closed"] for block in blocks)}},
            "no_citations": not bool(bindings), "semantic_acceptance_recomputed": False,
            "bindings": bindings}
