"""Verify candidates into rules (BACKEND_PLAN.md 2.5). Deterministic, no LLM.

Rejecting gates (first failure rejects; logged to rejects.jsonl and audit.jsonl):
  schema/enums, jurisdiction known to the manifest, level matches jurisdiction form,
  quoted_span found in the source document.
Non-rejecting checks lower confidence and add review reasons. Then duplicates are merged,
dates resolved, status computed for the default as-of date, and conflicting dates for the
same law from different sources are flagged. Writes rules.json (schema fields only),
rules_internal.json and rejects.jsonl.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from navigator import audit, settings
from navigator.extract import dates
from navigator.extract.chunk import MAX_CHARS
from navigator.ingest.corpus import Doc, read_docs
from navigator.schema import facts
from navigator.schema.models import RuleInternal
from navigator.schema.writers import dump_json, write_rules
from navigator.verify.spans import find_span, numbers_supported

BASE_CONFIDENCE = 0.9
REVIEW_PENALTY = 0.05
MIN_CONFIDENCE = 0.3
DATE_WINDOW = 1000          # chars around the span where the date phrase should sit
NUMBER_WINDOW = 1500        # chars around the span where claimed numbers may come from
SOURCE_RANK = {"official": 0}  # anything else ranks after official text


def _state(jurisdiction: str) -> str:
    return jurisdiction.rsplit(", ", 1)[-1]


def known_jurisdictions(docs: list[Doc]) -> set[str]:
    out = set()
    for d in docs:
        out.add(d.jurisdiction)
        out.add(_state(d.jurisdiction))
    return out


# --------------------------------------------------------------- one candidate


def check_candidate(c: dict[str, Any], doc: Doc, valid_jur: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    """(verified fields, None) or (None, reject reason)."""
    jur = (c.get("jurisdiction") or "").strip()
    if jur not in valid_jur:
        return None, f"jurisdiction {jur!r} is not a manifest jurisdiction"
    expected_level = "city" if ", " in jur else "state"
    if c.get("level") != expected_level:
        return None, f"level {c.get('level')!r} does not match jurisdiction {jur!r}"
    for f in ("title", "requirement", "citation", "quoted_span"):
        if not (c.get(f) or "").strip():
            return None, f"missing {f}"
    assert doc.text is not None and doc.body_offset is not None
    found = find_span(doc.text, c["quoted_span"], doc.body_offset)
    if not found:
        return None, "quoted_span not found in source document"
    start, end, match = found

    reasons: list[str] = []          # set needs_review
    notes: list[str] = []            # informational only
    penalty = 0.0
    single_chunk = len(doc.text) - doc.body_offset <= MAX_CHARS
    if match == "tolerant":
        penalty += 0.05
    text = doc.text

    # date phrase near the span, anchor anywhere in the document
    phrase, anchor = c.get("effective_date_phrase"), c.get("effective_date_anchor")
    if phrase:
        p = find_span(text, phrase, doc.body_offset) if len(phrase.strip()) >= 20 else None
        near = p and (p[0] < end + DATE_WINDOW and p[1] > start - DATE_WINDOW)
        if p is None and phrase.strip() in text:
            q = text.find(phrase.strip(), doc.body_offset)
            near = q >= 0 and abs(q - start) < DATE_WINDOW + (end - start)
        if not near and phrase.strip() not in text and not p:
            reasons.append("effective-date phrase not found in source text")
        elif not near:
            # In a one-section page the operative clause often closes the section; in a long
            # multi-rule document a far-away date may belong to a different rule.
            (notes if single_chunk else reasons).append(
                f"effective-date phrase is more than {DATE_WINDOW} chars from the quote")
    if anchor and anchor.strip() not in text and not find_span(text, anchor, doc.body_offset):
        reasons.append("effective-date anchor not found in source text")

    # numbers must come from the source: the headline near the span, the rest from the
    # document (statutes put exemptions and penalties in other subdivisions)
    window = text[max(doc.body_offset, start - NUMBER_WINDOW):end + NUMBER_WINDOW]
    body = text[doc.body_offset:]
    for field, src, where in (("requirement", window, "near the quote"), ("key_value", window, "near the quote"),
                              ("coverage_text", body, "in the document"), ("exemptions", body, "in the document"),
                              ("penalty", body, "in the document")):
        bad = numbers_supported(c.get(field), src)
        if bad:
            reasons.append(f"{field} has numbers not found {where}: {', '.join(bad)}")

    # predicates
    predicates = None
    raw = c.get("predicates_json")
    if raw:
        try:
            predicates = json.loads(raw)
            errs = facts.predicate_errors(predicates)
        except json.JSONDecodeError as exc:
            errs = [f"invalid JSON ({exc.msg})"]
        if errs:
            predicates = None
            reasons.append("coverage predicates dropped: " + "; ".join(errs[:3]))

    if jur != doc.jurisdiction and jur != _state(doc.jurisdiction):
        reasons.append(f"rule jurisdiction {jur} differs from document jurisdiction {doc.jurisdiction}")
    elif jur != doc.jurisdiction:
        notes.append(f"state rule taken from a {doc.jurisdiction} source")

    return {"jur": jur, "start": start, "end": end, "match": match, "predicates": predicates,
            "reasons": reasons, "notes": notes, "penalty": penalty, "quote": text[start:end]}, None


# ---------------------------------------------------------------- merging


CITE_SECTION = re.compile(r"\d+[A-Za-z]?(?:[.:\-]\d+[A-Za-z]?)+")
CITE_BILL = re.compile(r"\b([A-Z]{1,3})\.?\s?(\d{2,5})\b")
# "Senate, No. 2983" / "House Bill No. 5222": chamber word -> its initial, as in "S.2983"
CITE_CHAMBER = re.compile(r"\b(Senate|House|Assembly)\b[\s,]*(?:Bill\s*)?No\.?\s*(\d{2,5})\b", re.I)


def citation_key(citation: str) -> str:
    """Core identifier of a citation, so differently written cites of one law match."""
    if m := CITE_SECTION.search(citation):
        return m.group(0).lower()
    if m := CITE_CHAMBER.search(citation):
        return (m.group(1)[0] + m.group(2)).lower()
    if m := CITE_BILL.search(citation):
        return (m.group(1) + m.group(2)).lower()
    return re.sub(r"[^a-z0-9]", "", citation.lower())


def _rank(item: dict[str, Any]) -> tuple:
    c, v = item["c"], item["v"]
    return (SOURCE_RANK.get(c["source_type"], 1), {"exact": 0, "normalized": 1, "tolerant": 2}[v["match"]],
            -len(v["quote"]), c["candidate_id"])


def merge(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group verified candidates that state the same rule.

    Same document: same (jurisdiction, category, citation key) and overlapping spans (chunk
    overlap repeats a rule). Across documents: same key and exactly one rule per document
    under that key, so a one-to-one match is unambiguous. Everything else stays separate.
    """
    # within a document
    groups: list[list[dict[str, Any]]] = []
    by_doc_key: dict[tuple, list[list[dict[str, Any]]]] = defaultdict(list)
    for it in sorted(items, key=lambda i: (i["c"]["source_doc_id"], i["v"]["start"])):
        c, v = it["c"], it["v"]
        k = (c["source_doc_id"], v["jur"], c["category"], citation_key(c["citation"]))
        for g in by_doc_key[k]:
            if any(o["v"]["start"] < v["end"] and v["start"] < o["v"]["end"] for o in g):
                g.append(it)
                break
        else:
            g = [it]
            by_doc_key[k].append(g)
            groups.append(g)
    # across documents
    by_key: dict[tuple, list[list[dict[str, Any]]]] = defaultdict(list)
    for g in groups:
        c = g[0]["c"]
        by_key[(g[0]["v"]["jur"], c["category"], citation_key(c["citation"]))].append(g)
    merged: list[list[dict[str, Any]]] = []
    for gs in by_key.values():
        docs = [g[0]["c"]["source_doc_id"] for g in gs]
        if len(gs) > 1 and len(set(docs)) == len(docs):
            merged.append([it for g in gs for it in g])
        else:
            merged.extend(gs)
    return merged


# ---------------------------------------------------------------- build rules


def build_rule(group: list[dict[str, Any]], as_of: str) -> RuleInternal:
    best = min(group, key=_rank)
    c, v = best["c"], best["v"]
    reasons = list(v["reasons"])
    penalty = v["penalty"]

    res = dates.resolve(c.get("effective_date_phrase"), c.get("effective_date_anchor"),
                        jurisdiction=v["jur"], level=c["level"], status_hint=c["status_hint"])
    reasons += res.review_reasons
    notes = list(v["notes"]) + res.notes
    penalty += res.confidence_penalty

    # same law, other sources: different status hints or dates are conflicts for review
    conflict_notes = []
    hints = {it["c"]["status_hint"] for it in group}
    if len(hints) > 1:
        reasons.append("sources disagree on whether this is enacted, pending or failed: "
                       + ", ".join(sorted(f"{it['c']['source_doc_id']}={it['c']['status_hint']}" for it in group)))
    other_dates = {}
    for it in group:
        if it is best:
            continue
        r2 = dates.resolve(it["c"].get("effective_date_phrase"), it["c"].get("effective_date_anchor"),
                           jurisdiction=it["v"]["jur"], level=it["c"]["level"],
                           status_hint=it["c"]["status_hint"])
        # A conflict needs two stated effective dates; a rate period's start is not one.
        periods = ("date_range_start",)
        if res.date and r2.date and r2.date != res.date \
                and res.method not in periods and r2.method not in periods:
            other_dates[it["c"]["source_doc_id"]] = r2.date
    if other_dates:
        conflict_notes.append(
            f"Sources give different effective dates: {res.date or 'not stated'} ({c['source_doc_id']}, used)"
            + "".join(f"; {d} ({doc})" for doc, d in sorted(other_dates.items())))

    status = dates.status_on(c["status_hint"], res.date, as_of)
    confidence = max(MIN_CONFIDENCE, round(BASE_CONFIDENCE - penalty - REVIEW_PENALTY * len(reasons), 2))
    if conflict_notes:
        confidence = min(confidence, 0.6)

    coverage: Any = c.get("coverage_text")
    if v["predicates"] is not None:
        coverage = {"text": c.get("coverage_text"), "predicates": v["predicates"]}

    return RuleInternal(
        team_rule_id="pending",
        jurisdiction=v["jur"],
        level=c["level"],
        category=c["category"],
        status=status,
        title=c["title"].strip(),
        requirement=c["requirement"].strip(),
        key_value=c.get("key_value"),
        coverage_conditions=coverage,
        exemptions=c.get("exemptions"),
        overrides=[],
        interaction=None,
        effective_date=res.date,
        citation=c["citation"].strip(),
        source_doc_id=c["source_doc_id"],
        source_url=c["source_url"],
        quoted_span=v["quote"],
        confidence=confidence,
        conflict_flag=bool(conflict_notes),
        conflict_note="; ".join(conflict_notes) or None,
        span_start=v["start"],
        span_end=v["end"],
        span_match=v["match"],
        retrieved_at=c["retrieved_at"],
        penalty=c.get("penalty"),
        effective_date_phrase=c.get("effective_date_phrase"),
        effective_date_anchor=c.get("effective_date_anchor"),
        effective_date_method=res.method,
        predicates=v["predicates"],
        needs_review=bool(reasons or conflict_notes),
        review_reasons=reasons,
        notes=notes,
        provenance=[{"candidate_id": it["c"]["candidate_id"], "source_doc_id": it["c"]["source_doc_id"],
                     "source_url": it["c"]["source_url"], "span_start": it["v"]["start"],
                     "span_end": it["v"]["end"], "status_hint": it["c"]["status_hint"],
                     "interaction_text": it["c"].get("interaction_text"),
                     "coverage_text": it["c"].get("coverage_text"),
                     **it["c"]["provenance"]} for it in sorted(group, key=_rank)],
    )


def _sort_key(r: RuleInternal) -> tuple:
    return (0 if r.level == "state" else 1, _state(r.jurisdiction), r.jurisdiction, r.category,
            r.source_doc_id or "", r.span_start or 0)


def run() -> None:
    as_of = settings.load()["default_as_of"]
    out = settings.path("outputs")
    docs = {d.doc_id: d for d in read_docs()}
    valid_jur = known_jurisdictions([d for d in docs.values() if d.jurisdiction])
    cand_path = out / "candidates.jsonl"
    candidates = [json.loads(line) for line in cand_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    verified, rejects = [], []
    for c in candidates:
        doc = docs.get(c["source_doc_id"])
        if doc is None or not doc.text_available:
            v, reason = None, "source document has no text"
        else:
            v, reason = check_candidate(c, doc, valid_jur)
        if v is None:
            rejects.append({"candidate_id": c["candidate_id"], "source_doc_id": c["source_doc_id"],
                            "reason": reason, "candidate": c})
            audit.log("verify", "reject", reason, candidate_id=c["candidate_id"], doc_id=c["source_doc_id"])
        else:
            verified.append({"c": c, "v": v})

    groups = merge(verified)
    rules = sorted((build_rule(g, as_of) for g in groups), key=_sort_key)
    for i, r in enumerate(rules, 1):
        r.team_rule_id = f"r-{i:04d}"
        audit.log("verify", "accept", "; ".join(r.review_reasons) or None, team_rule_id=r.team_rule_id,
                  candidates=[p["candidate_id"] for p in r.provenance], status=r.status,
                  effective_date=r.effective_date, date_method=r.effective_date_method,
                  span_match=r.span_match, conflict_flag=r.conflict_flag or None)

    write_rules(rules)
    dump_json({"as_of": as_of, "rules": [r.model_dump(mode="json") for r in rules]}, out / "rules_internal.json")
    with (out / "rejects.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for rj in rejects:
            fh.write(json.dumps(rj, ensure_ascii=False) + "\n")

    by_status = defaultdict(int)
    for r in rules:
        by_status[r.status] += 1
    review = sum(r.needs_review for r in rules)
    print(f"{len(candidates)} candidates -> {len(rules)} rules ({len(verified) - len(rules)} merged), "
          f"{len(rejects)} rejected; status {dict(sorted(by_status.items()))}; "
          f"{review} need review; {sum(r.conflict_flag for r in rules)} conflict-flagged")
