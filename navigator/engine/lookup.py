"""Coverage engine: rules x parcels -> lookups (BACKEND_PLAN.md 2.8). Deterministic, no LLM.

Public API (stable; the change tracker calls these):

    load_rules() -> list[RuleInternal]          # outputs/rules_internal.json
    load_parcels() -> list[dict]                # outputs/parcels.json (Phase 4)
    evaluate_address(parcel, rules, as_of) -> list[LookupRowInternal]

Per address, for each rule whose jurisdiction is the parcel's state or its legal city:
    status on as_of (dates.status_on): failed -> left out
    coverage (three-valued):           FALSE  -> left out (CONTRACT.md 3)
    pending -> pending;  not yet effective -> not_yet_effective
    in force: TRUE -> applies;  UNKNOWN -> unknown (missing fact named)
    city rule while the legal city is not confirmed -> unknown
    precedence (precedence.py, from extracted text only):
        state rule that defers to local rules + a same-category city rule whose coverage
        was decided from building facts -> superseded; if that city rule's coverage could
        not be confirmed -> unknown ("may be superseded by ...")
        unresolved interactions -> both rows conflict_flag with the reason
Rows are sorted by team_rule_id; addresses by the starter order. Two runs are byte-identical.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from navigator import settings, starter, stubs
from navigator.engine import boundary, confidence, coverage, precedence
from navigator.engine.coverage import FALSE, TRUE, Coverage
from navigator.engine.explain_lookup import Decision, explain
from navigator.engine.facts import Facts, parcel_facts
from navigator.engine.status import status_on
from navigator.schema.models import LookupRowInternal, RuleInternal
from navigator.schema.writers import dump_json, write_lookups

COVERED = ("applies", "unknown", "superseded")
CONFLICT_WHY = "whose interaction with this rule is stated in the source text but not resolved here"
RESULT_ORDER = ["applies", "superseded", "unknown", "not_yet_effective", "pending"]


class EngineInputError(SystemExit):
    """Stops `python -m navigator lookups` with a clear message; nothing is written."""


# ------------------------------------------------------------------ loading


def load_rules(path: Path | None = None) -> list[RuleInternal]:
    """Rules from outputs/rules_internal.json (the verify stage's output)."""
    path = path or settings.path("outputs") / "rules_internal.json"
    if not path.is_file():
        raise EngineInputError(f"lookups: {path} not found; run `python -m navigator verify` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [RuleInternal.model_validate(r) for r in data["rules"]]


def load_parcels(path: Path | None = None) -> list[dict[str, Any]]:
    """Parcels from outputs/parcels.json (the geocode stage's output)."""
    path = path or settings.path("outputs") / "parcels.json"
    if not path.is_file():
        raise EngineInputError(
            f"lookups: {path} not found; run `python -m navigator geocode` first. "
            "No lookups were written (an empty lookups.json would read as 'no rule applies').")
    data = json.loads(path.read_text(encoding="utf-8"))
    parcels = data["parcels"] if isinstance(data, dict) else data
    return list(parcels)


# ------------------------------------------------------------------ engine

_REL_CACHE: dict[tuple, tuple[list[RuleInternal], list[precedence.Relation]]] = {}


def _relations(rules: list[RuleInternal]) -> list[precedence.Relation]:
    # The entry keeps the rule objects alive, so their id()s cannot be reused by a new
    # list and return stale relations.
    key = tuple((r.team_rule_id, id(r)) for r in rules)
    hit = _REL_CACHE.get(key)
    if hit is None:
        _REL_CACHE.clear()
        _REL_CACHE[key] = hit = (list(rules), precedence.relations(rules))
    return hit[1]


class _Row:
    def __init__(self, rule: RuleInternal, status: str, cov: Coverage, result: str, reason: str):
        self.rule, self.status, self.cov = rule, status, cov
        self.result, self.reason = result, reason
        self.other: RuleInternal | None = None
        self.superseded_by: str | None = None
        self.stricter_only = False
        self.conflicts: dict[str, RuleInternal] = {}
        self.extra_not_checked: list[str] = []


def _base_row(rule: RuleInternal, f: Facts, as_of: str) -> _Row | None:
    st = status_on(rule, as_of)
    if st == "failed":
        return None
    cov = coverage.evaluate(rule.predicates, f, as_of)
    if cov.value == FALSE:
        return None
    if st == "pending":
        return _Row(rule, st, cov, "pending", "status")
    if st == "not_yet_effective":
        return _Row(rule, st, cov, "not_yet_effective", "status")
    if rule.level == "city" and not f.city_confirmed:
        return _Row(rule, st, cov, "unknown", "jurisdiction")
    return _Row(rule, st, cov, "applies" if cov.value == TRUE else "unknown", "coverage")


def _apply_precedence(rows: dict[str, _Row], rels: list[precedence.Relation]) -> None:
    yields: dict[str, dict[str, bool]] = {}         # state id -> {city id: stricter_only}
    for rel in rels:
        if rel.kind != "yields_to_local" or rel.source not in rows:
            continue
        for t in rel.targets:
            prev = yields.setdefault(rel.source, {}).get(t)
            yields[rel.source][t] = rel.stricter_only if prev is None else (prev and rel.stricter_only)
    for sid, targets in sorted(yields.items()):
        row = rows[sid]
        if row.status != "in_force" or row.result not in ("applies", "unknown"):
            continue
        live = [rows[t] for t in sorted(targets) if t in rows and rows[t].status == "in_force"]
        confirmed = [r for r in live if r.result == "applies" and r.cov.has_predicates]
        unconfirmed = [r for r in live if r.result in ("applies", "unknown") and r not in confirmed]
        if row.result == "applies" and confirmed:
            gov = confirmed[0]
            row.result, row.reason, row.other = "superseded", "superseded", gov.rule
            row.superseded_by = gov.rule.team_rule_id
            row.stricter_only = targets[gov.rule.team_rule_id]
        elif row.result == "applies" and unconfirmed:
            row.result, row.reason, row.other = "unknown", "may_be_superseded", unconfirmed[0].rule
        elif confirmed or unconfirmed:
            first = (confirmed or unconfirmed)[0].rule.team_rule_id
            row.extra_not_checked.append(f"whether {first} governs instead (state text defers to local rules)")


def _apply_conflicts(rows: dict[str, _Row], rels: list[precedence.Relation]) -> None:
    for rel in rels:
        if rel.kind != "conflict" or rel.source not in rows or rows[rel.source].result not in COVERED:
            continue
        src = rows[rel.source]
        for t in rel.targets:
            other = rows.get(t)
            if other is None or other.result not in COVERED:
                continue
            src.conflicts[t] = other.rule
            other.conflicts[rel.source] = src.rule


def _finish(row: _Row, f: Facts, as_of: str, outside_cities: bool) -> LookupRowInternal:
    rule = row.rule
    conflicts = [(row.conflicts[k], CONFLICT_WHY) for k in sorted(row.conflicts)]
    d = Decision(result=row.result, coverage=row.cov, reason=row.reason, other=row.other,
                 conflicts=conflicts, city_unconfirmed=not f.city_confirmed and f.city is not None,
                 outside_cities=outside_cities, stricter_only=row.stricter_only)
    conflict_flag = bool(conflicts) or rule.conflict_flag
    extra = list(row.extra_not_checked)
    if conflicts:
        extra.append("unresolved interaction with " + ", ".join(o.team_rule_id for o, _ in conflicts))
    if row.reason == "may_be_superseded" and row.other is not None:
        extra.append(f"whether {row.other.team_rule_id} covers this unit (its coverage could not be confirmed)")
    if row.stricter_only and row.result == "superseded":
        extra.append("whether the local limit is stricter than the state limit")
    conf, reasons = confidence.score(
        rule.confidence, f, row.cov, level=rule.level, has_exemptions=bool(rule.exemptions),
        stricter_not_compared=row.stricter_only and row.result == "superseded",
        superseder_unconfirmed=row.reason == "may_be_superseded", conflict=conflict_flag)
    return LookupRowInternal(
        team_rule_id=rule.team_rule_id,
        result=row.result,
        explanation=explain(rule, d),
        conflict_flag=conflict_flag,
        checked=boundary.checked(rule.jurisdiction, rule.level, f, row.cov, row.status, as_of),
        not_checked=boundary.not_checked(rule.exemptions, f, row.cov, city_rules_skipped=outside_cities,
                                         extra=extra),
        missing_facts=list(row.cov.missing),
        superseded_by=row.superseded_by,
        confidence=conf,
        confidence_reasons=reasons,
    )


def evaluate_address(parcel: dict, rules: list[RuleInternal], as_of: str) -> list[LookupRowInternal]:
    """Lookup rows (LookupRowInternal) for one parcels.json record on `as_of` (YYYY-MM-DD).

    Rules that do not apply (coverage FALSE) and failed rules are left out. Rows are
    sorted by team_rule_id. Pure: depends only on its arguments (and, for precedence
    scoping, the read-only corpus manifest).
    """
    f = parcel_facts(parcel)
    rows: dict[str, _Row] = {}
    for rule in sorted(rules, key=lambda r: r.team_rule_id):
        if rule.jurisdiction == f.state or (f.city is not None and rule.jurisdiction == f.city):
            row = _base_row(rule, f, as_of)
            if row is not None:
                rows[rule.team_rule_id] = row
    rels = _relations(rules)
    _apply_precedence(rows, rels)
    _apply_conflicts(rows, rels)
    outside = f.city is None
    return [_finish(rows[k], f, as_of, outside) for k in sorted(rows)]


# ------------------------------------------------------------------ timeline


def _first_in_force_day(rule: RuleInternal) -> str | None:
    """First date on which status_on() reports the rule in force (None if never)."""
    eff = rule.effective_date
    if not eff:
        return None
    parts = [int(p) for p in eff.split("-")]
    if len(parts) == 3:
        cand = dt.date(*parts)
    elif len(parts) == 2:
        y, m = parts
        cand = dt.date(y, m, calendar.monthrange(y, m)[1]) + dt.timedelta(days=1)
    else:
        cand = dt.date(parts[0] + 1, 1, 1)
    iso = cand.isoformat()
    return iso if status_on(rule, iso) == "in_force" else None


def key_dates(rules: list[RuleInternal], as_of: str) -> list[str]:
    days = {as_of}
    for r in rules:
        d = _first_in_force_day(r)
        if d:
            days.add(d)
    return sorted(days)


def _best(results: list[str]) -> str:
    return min(results, key=RESULT_ORDER.index)


def build_timeline(parcels: list[dict], rules: list[RuleInternal], dates_: list[str]):
    by_cat = {r.team_rule_id: r.category for r in rules}
    snapshots: dict[str, dict[str, Any]] = {}
    timeline: dict[str, list[dict[str, Any]]] = {}
    prev: dict[str, dict[str, str]] = {}
    for day in dates_:
        snap: dict[str, Any] = {}
        for p in parcels:
            aid = str(p["address_id"])
            rows = evaluate_address(p, rules, day)
            cats: dict[str, dict[str, Any]] = {}
            for r in rows:
                c = cats.setdefault(by_cat[r.team_rule_id], {"results": [], "conflict_flag": False})
                c["results"].append(r.result)
                c["conflict_flag"] = c["conflict_flag"] or r.conflict_flag
            snap[aid] = {cat: {"result": _best(v["results"]), "conflict_flag": v["conflict_flag"],
                               "rules": len(v["results"])} for cat, v in sorted(cats.items())}
            now = {r.team_rule_id: r.result for r in rows}
            if aid in prev:
                changes = [{"team_rule_id": k, "from": prev[aid].get(k), "to": now.get(k)}
                           for k in sorted(set(prev[aid]) | set(now)) if prev[aid].get(k) != now.get(k)]
                if changes:
                    timeline.setdefault(aid, []).append({"date": day, "changes": changes})
            prev[aid] = now
        snapshots[day] = snap
    return timeline, snapshots


# ------------------------------------------------------------------ run


def _check_parcels(parcels: list[dict]) -> None:
    ids = [str(p.get("address_id")) for p in parcels]
    expected = starter.address_ids()
    problems = []
    if dup := sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"duplicate address ids {dup[:5]}")
    if missing := [i for i in expected if i not in set(ids)]:
        problems.append(f"{len(missing)} address ids missing, e.g. {missing[:5]}")
    if extra := sorted(set(ids) - set(expected)):
        problems.append(f"{len(extra)} unknown address ids, e.g. {extra[:5]}")
    for p in parcels:
        if not p.get("state"):
            problems.append(f"{p.get('address_id')}: no state")
    if problems:
        raise EngineInputError("lookups: parcels.json is incomplete; nothing written:\n  " + "\n  ".join(problems[:20]))


def run(as_of: str | None = None, out_dir: Path | None = None, timeline: bool = True) -> None:
    as_of = as_of or settings.load()["default_as_of"]
    out = out_dir or settings.path("outputs")
    rules = load_rules()
    parcels = load_parcels()
    _check_parcels(parcels)
    order = {aid: i for i, aid in enumerate(starter.address_ids())}
    parcels = sorted(parcels, key=lambda p: order[str(p["address_id"])])

    lookups = {str(p["address_id"]): evaluate_address(p, rules, as_of) for p in parcels}
    write_lookups(as_of, lookups, rules, out_dir=out)
    dump_json({"as_of": as_of,
               "lookups": {aid: [r.model_dump(mode="json") for r in rows] for aid, rows in lookups.items()}},
              out / "lookups_internal.json")
    if timeline:
        days = key_dates(rules, as_of)
        tl, snaps = build_timeline(parcels, rules, days)
        dump_json({"dates": days, "timeline": tl}, out / "timeline.json")
        dump_json({"dates": days, "snapshots": snaps}, out / "snapshots.json")
    if out_dir is None:
        stubs.clear_marker()

    by_result = Counter(r.result for rows in lookups.values() for r in rows)
    empty = sum(1 for rows in lookups.values() if not rows)
    flagged = sum(1 for rows in lookups.values() for r in rows if r.conflict_flag)
    print(f"lookups as of {as_of}: {len(lookups)} addresses, {sum(by_result.values())} rows "
          f"{dict(sorted(by_result.items()))}; {empty} addresses with no rows; {flagged} conflict-flagged rows")
