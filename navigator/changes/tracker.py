"""Change tracking: dev/change_tests.json -> outputs/changes.json (BACKEND_PLAN.md 2.9).

Deterministic, no LLM. Every result comes from the coverage engine (engine.lookup) run on
the dates the test names, for the rules the matcher maps the test's ids to.

Per test type:
  as_of     affected = addresses where any mapped rule's result differs between
            as_of_before and as_of_after. Conflicts: addresses covered by a mapped rule on
            as_of_after that are also covered by a `conflict_with` rule. A conflict_with id
            whose rule has no source text in the corpus, but whose place resolves to a corpus
            city, still flags that city's addresses for human review (fail closed: the test
            names a possible conflict that we cannot rule out).
  boundary  affected = addresses where a mapped city rule is in the lookup on `as_of`. If
            the rule has no source text, the boundary alone is known: affected = addresses
            whose legal city is that city (the rule's own coverage could not be checked).
  pending   affected = addresses the mapped bills would cover if enacted (coverage not
            FALSE); lookups must still say `pending`.
  negative  affected = []; checks that no rent limit from the measure or from a city rule is
            reported, and records the measure as failed only if a rule for it exists.
  other     fail closed: empty lists and a note that the test type is not supported.

`expected_behavior` is checked by the explicit assertions below (written to
outputs/changes_internal.json and scores/changes_report.txt), never parsed from prose.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from navigator import audit, settings, starter
from navigator.changes import matcher
from navigator.engine import coverage, lookup
from navigator.engine.coverage import FALSE
from navigator.engine.facts import parcel_facts
from navigator.engine.status import status_on
from navigator.schema.models import ChangeResult, LookupRowInternal, RuleInternal
from navigator.schema.writers import dump_json, write_changes

COVERED = lookup.COVERED            # applies, unknown, superseded
IN_LOOKUP = COVERED + ("not_yet_effective", "pending")


@dataclass
class Check:
    name: str
    passed: bool | None             # None: could not be checked (named in detail)
    detail: str

    def line(self) -> str:
        mark = {True: "PASS", False: "FAIL", None: "N/A "}[self.passed]
        return f"[{mark}] {self.name} - {self.detail}"


@dataclass
class Outcome:
    affected: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)


class Context:
    """Rules, parcels and per-date engine results (each date evaluated once)."""

    def __init__(self, rules: list[RuleInternal], parcels: list[dict[str, Any]]):
        self.rules = rules
        self.by_id = {r.team_rule_id: r for r in rules}
        order = {aid: i for i, aid in enumerate(starter.address_ids())}
        self.parcels = sorted(parcels, key=lambda p: order[str(p["address_id"])])
        self._days: dict[str, dict[str, dict[str, LookupRowInternal]]] = {}

    def on(self, day: str) -> dict[str, dict[str, LookupRowInternal]]:
        """{address_id: {team_rule_id: row}} on `day`."""
        if day not in self._days:
            self._days[day] = {str(p["address_id"]): {r.team_rule_id: r for r in
                                                      lookup.evaluate_address(p, self.rules, day)}
                               for p in self.parcels}
        return self._days[day]

    def in_states(self, states: list[str] | None) -> list[dict[str, Any]]:
        return [p for p in self.parcels if not states or p["state"] in states]


# ------------------------------------------------------------------ helpers


def _ids(entry: dict[str, Any], key: str = "rule_ids") -> list[str]:
    return sorted({rid for m in entry.get(key, {}).values() for rid in m.get("team_rule_ids", [])})


def _describe(ctx: Context, rid: str) -> str:
    r = ctx.by_id[rid]
    eff = r.effective_date or "not stated"
    return f"{rid} ({r.citation}; {r.source_doc_id}; status {r.status} on the default date; effective {eff})"


def _match_notes(ctx: Context, entry: dict[str, Any], key: str = "rule_ids") -> list[str]:
    out = []
    for org, m in entry.get(key, {}).items():
        if m.get("team_rule_ids"):
            out.append(f"{org} -> " + "; ".join(_describe(ctx, rid) for rid in m["team_rule_ids"]))
        else:
            out.append(f"{org} -> no match ({m.get('problem', 'no rule')})")
    shared = [org for org, m in entry.get(key, {}).items() if m.get("team_rule_ids")]
    pools = Counter(tuple(entry[key][o]["team_rule_ids"]) for o in shared)
    if any(n > 1 for n in pools.values()):
        out.append("several organizer ids share one pool of our rules; matched as a set "
                   "(the one-to-one pairing is not decidable from the ids)")
    return out


def _review_notes(ctx: Context, rids: list[str]) -> list[str]:
    out = []
    for rid in rids:
        r = ctx.by_id[rid]
        if r.needs_review and r.review_reasons:
            out.append(f"{rid} needs review: " + "; ".join(r.review_reasons))
    return out


def _city_name(jur: str) -> str:
    return jur.rsplit(", ", 1)[0]


def _in_city(p: dict[str, Any], jur: str) -> bool:
    return p.get("city") == jur


def _maybe_in_city(p: dict[str, Any], jur: str) -> bool:
    """Legal city not resolved, but the postal city names `jur` (cannot be ruled out)."""
    return p.get("city") is None and p["state"] == jur.rsplit(", ", 1)[1] \
        and (p.get("postal_city") or "").strip().lower() == _city_name(jur).lower()


def _results(rows: dict[str, LookupRowInternal], rids: list[str]) -> dict[str, str]:
    return {rid: rows[rid].result for rid in rids if rid in rows}


def _count_line(label: str, aids: list[str], ctx: Context) -> str:
    by_city = Counter((p.get("city") or f"{p['state']} (legal city unresolved)")
                      for p in ctx.parcels if str(p["address_id"]) in set(aids))
    parts = ", ".join(f"{k} {v}" for k, v in sorted(by_city.items()))
    return f"{label}: {len(aids)}" + (f" ({parts})" if parts else "")


# ------------------------------------------------------------------ test types


def track_as_of(ctx: Context, test: dict[str, Any], entry: dict[str, Any]) -> Outcome:
    o = Outcome()
    before, after = test["as_of_before"], test["as_of_after"]
    states = test.get("states")
    rids = _ids(entry)
    scope = ctx.in_states(states)
    o.notes += _match_notes(ctx, entry)
    o.notes.append(f"as-of dates used: {before} -> {after}")
    if not rids:
        o.notes.append("no rule of ours matches; nothing computed (no source text, nothing invented)")
        o.checks.append(Check("mapped rules exist", None, "no matching rule; expected behavior not checkable"))
        return o
    b, a = ctx.on(before), ctx.on(after)
    for p in ctx.parcels:
        aid = str(p["address_id"])
        if _results(b[aid], rids) != _results(a[aid], rids):
            o.affected.append(aid)
    o.notes.append(_count_line("affected (result changes for a mapped rule)", o.affected, ctx))

    # expected behavior: not_yet_effective before, applies after, for every in-scope address
    nye = [str(p["address_id"]) for p in scope
           if (r := _results(b[str(p["address_id"])], rids)) and set(r.values()) == {"not_yet_effective"}]
    app = [str(p["address_id"]) for p in scope
           if (r := _results(a[str(p["address_id"])], rids)) and set(r.values()) == {"applies"}]
    where = "/".join(states) if states else "all"
    o.checks.append(Check(f"not_yet_effective on {before} for every {where} address",
                          len(nye) == len(scope), f"{len(nye)}/{len(scope)}"))
    o.checks.append(Check(f"applies on {after} for every {where} address",
                          len(app) == len(scope), f"{len(app)}/{len(scope)}"))
    for label, got, day in (("before", nye, before), ("after", app, after)):
        rows = ctx.on(day)
        other = Counter(tuple(sorted(_results(rows[str(p["address_id"])], rids).values())) or ("not in lookup",)
                        for p in scope if str(p["address_id"]) not in set(got))
        if other:
            o.notes.append(f"{label} ({day}), addresses not as expected: "
                           + ", ".join(f"{'/'.join(k)} {v}" for k, v in sorted(other.items())))
    for rid in rids:
        o.notes.append(f"{rid} status: {status_on(ctx.by_id[rid], before)} on {before}, "
                       f"{status_on(ctx.by_id[rid], after)} on {after}")

    # conflicts on the after date
    if entry.get("conflict_with"):
        o.notes += ["conflict_with " + n for n in _match_notes(ctx, entry, "conflict_with")]
        covered = {aid for aid in a if any(a[aid].get(rid) and a[aid][rid].result in COVERED for rid in rids)}
        flagged: set[str] = set()
        for org, m in entry["conflict_with"].items():
            cids = m.get("team_rule_ids") or []
            if cids:
                hit = {aid for aid in covered if any(a[aid].get(c) and a[aid][c].result in COVERED for c in cids)}
                o.notes.append(f"{org}: {len(hit)} addresses covered by both on {after}")
            elif m.get("jurisdiction") and m.get("level") != "state":
                jur = m["jurisdiction"]
                sure = {str(p["address_id"]) for p in ctx.parcels if _in_city(p, jur)} & covered
                maybe = {str(p["address_id"]) for p in ctx.parcels if _maybe_in_city(p, jur)} & covered
                hit = sure | maybe
                o.notes.append(
                    f"{org}: no source text in the corpus; the {len(sure)} addresses in {jur} covered "
                    f"by the mapped rule on {after} are flagged for human review because the test names "
                    "a possible conflict we cannot rule out"
                    + (f" (+{len(maybe)} with unresolved legal city whose postal city is {_city_name(jur)})"
                       if maybe else ""))
            else:
                hit = set()
                o.notes.append(f"{org}: not resolvable to a place; no conflict flag can be computed")
            flagged |= hit
        o.conflicts = sorted(flagged)
        engine_flags = {aid for aid in a for rid in rids if a[aid].get(rid) and a[aid][rid].conflict_flag}
        o.notes.append(f"engine conflict flags on mapped rules on {after}: {len(engine_flags)} addresses")
    o.notes += _review_notes(ctx, rids)
    return o


def track_boundary(ctx: Context, test: dict[str, Any], entry: dict[str, Any]) -> Outcome:
    o = Outcome()
    day = test.get("as_of") or settings.load()["default_as_of"]
    rows = ctx.on(day)
    o.notes += _match_notes(ctx, entry)
    o.notes.append(f"as-of date used: {day}")
    affected: set[str] = set()
    places: list[str] = []
    for org, m in entry.get("rule_ids", {}).items():
        jur, rids = m.get("jurisdiction"), m.get("team_rule_ids") or []
        if jur:
            places.append(jur)
        if rids:
            hit = {aid for aid, rs in rows.items() if any(rid in rs and rs[rid].result in IN_LOOKUP for rid in rids)}
            outside = sorted(aid for aid in hit if not any(_in_city(p, jur) for p in ctx.parcels
                                                           if str(p["address_id"]) == aid))
            o.checks.append(Check(f"{org} only for {jur} addresses", not outside,
                                  f"{len(hit)} addresses, {len(outside)} outside {jur}"))
        elif jur and m.get("level") == "city":
            hit = {str(p["address_id"]) for p in ctx.parcels if _in_city(p, jur)}
            o.notes.append(f"{org}: no source text in the corpus, so it is not in rules.json or lookups.json; "
                           f"affected lists the {len(hit)} addresses whose legal city is {jur} "
                           "(boundary only; the rule's own coverage could not be checked)")
            o.checks.append(Check(f"{org} only for {jur} addresses", None,
                                  f"no rule text; boundary gives {len(hit)} addresses"))
        else:
            hit = set()
            o.checks.append(Check(f"{org} resolved to a place", False, m.get("problem") or "unresolved"))
        affected |= hit
    o.affected = sorted(affected)
    o.notes.append(_count_line("affected", o.affected, ctx))
    stray = sorted(aid for aid in o.affected
                   if not any(_in_city(p, j) for p in ctx.parcels if str(p["address_id"]) == aid for j in places))
    o.checks.append(Check("no affected address outside the named cities", not stray, f"{len(stray)} outside"))

    # legal city vs postal city in the named cities' states (the point of a boundary test)
    st = {j.rsplit(", ", 1)[1] for j in places}
    differs = [p for p in ctx.parcels if p["state"] in st and p.get("city")
               and (p.get("postal_city") or "").strip().lower() != _city_name(p["city"]).lower()
               and (any(_in_city(p, j) for j in places)
                    or (p.get("postal_city") or "").strip().lower() in {_city_name(j).lower() for j in places})]
    if differs:
        o.notes.append("legal city differs from postal city: " + ", ".join(
            f"{p['address_id']} postal {p.get('postal_city')} -> legal {p['city']}" for p in differs[:12])
            + (f" (+{len(differs) - 12} more)" if len(differs) > 12 else ""))
    unresolved = [str(p["address_id"]) for p in ctx.parcels if p["state"] in st and p.get("city") is None]
    if unresolved:
        o.notes.append(f"legal city unresolved, not checked: {', '.join(unresolved)}")
    return o


def track_pending(ctx: Context, test: dict[str, Any], entry: dict[str, Any]) -> Outcome:
    o = Outcome()
    day = test.get("as_of") or settings.load()["default_as_of"]
    rids = _ids(entry)
    scope = ctx.in_states(test.get("states"))
    o.notes += _match_notes(ctx, entry)
    o.notes.append(f"as-of date used: {day}")
    if not rids:
        o.notes.append("no rule of ours matches; nothing computed")
        o.checks.append(Check("mapped rules exist", None, "no matching rule; expected behavior not checkable"))
        return o
    rows = ctx.on(day)
    in_force = [rid for rid in rids if status_on(ctx.by_id[rid], day) == "in_force"]
    o.checks.append(Check("mapped bills are not in force", not in_force,
                          f"in force: {', '.join(in_force) or 'none'}"))
    city_scope = [p for p in scope if p.get("city")]
    ok = [p for p in city_scope
          if (r := _results(rows[str(p["address_id"])], rids)) and set(r.values()) == {"pending"}
          and len(r) == len(rids)]
    o.checks.append(Check("reported as pending for every address in a corpus city",
                          len(ok) == len(city_scope), f"{len(ok)}/{len(city_scope)}"))
    for p in scope:
        f = parcel_facts(p)
        if any(coverage.evaluate(ctx.by_id[rid].predicates, f).value != FALSE for rid in rids):
            o.affected.append(str(p["address_id"]))
    o.notes.append(_count_line("affected if enacted (coverage not ruled out)", o.affected, ctx))
    o.checks.append(Check("affected if enacted = every in-scope address", len(o.affected) == len(scope),
                          f"{len(o.affected)}/{len(scope)}"))
    o.notes.append("lookups.json reports these bills as pending (not in force); affected is hypothetical")
    o.notes += _review_notes(ctx, rids)
    return o


def track_negative(ctx: Context, test: dict[str, Any], entry: dict[str, Any]) -> Outcome:
    o = Outcome()
    day = test.get("as_of") or settings.load()["default_as_of"]
    rows = ctx.on(day)
    scope = ctx.in_states(test.get("states"))
    o.notes += _match_notes(ctx, entry)
    o.notes.append(f"as-of date used: {day}")
    rids = _ids(entry)
    cats = sorted({m["category"] for m in entry.get("rule_ids", {}).values() if m.get("category")})

    failed = [rid for rid in rids if ctx.by_id[rid].status == "failed"]
    other = [rid for rid in rids if rid not in failed]
    if failed:
        o.notes.append("recorded as failed: " + ", ".join(failed))
    if other:
        o.notes.append("matched but not recorded as failed (review): "
                       + ", ".join(f"{rid} status {ctx.by_id[rid].status}" for rid in other))
    if not rids:
        o.notes.append("the measure has no text in the corpus, so it cannot be recorded as failed "
                       "(a failed record needs a citable span); it is absent from rules.json and lookups.json")
    o.checks.append(Check("measure recorded as failed", bool(failed) if rids else None,
                          ", ".join(failed) or "no citable text in the corpus"))

    in_lookup = sorted({rid for rs in rows.values() for rid in rs if rid in rids})
    o.checks.append(Check("measure never appears in lookups", not in_lookup, ", ".join(in_lookup) or "absent"))

    # no limit from a city rule or from a pending/failed measure for any in-scope city address
    reported: Counter[str] = Counter()
    bad: set[str] = set()
    for p in scope:
        for rid, row in rows[str(p["address_id"])].items():
            r = ctx.by_id[rid]
            if r.category in cats and row.result in COVERED:
                reported[rid] += 1
                if r.level == "city" or status_on(r, day) != "in_force":
                    bad.add(rid)
    if cats:
        o.checks.append(Check(f"no {'/'.join(cats)} rule from a city ordinance or an unenacted measure "
                              "reported as applying", not bad, ", ".join(sorted(bad)) or "none"))
    else:
        o.checks.append(Check("no rule from a city ordinance or an unenacted measure reported as applying",
                              None, "the test's rule ids name no category; not checkable"))
    for rid, n in sorted(reported.items()):
        if rid not in bad:
            r = ctx.by_id[rid]
            o.notes.append(f"state rule {rid} ({r.citation}) is in the lookups for {n} addresses; "
                           f"its requirement reads: \"{r.requirement[:160]}\" (review: not a cap from the measure)")
    o.notes.append("affected is empty: a measure that did not pass changes no result")
    return o


TRACKERS: dict[str, Callable[[Context, dict[str, Any], dict[str, Any]], Outcome]] = {
    "as_of": track_as_of, "boundary": track_boundary, "pending": track_pending, "negative": track_negative,
}


def track(ctx: Context, test: dict[str, Any], entry: dict[str, Any]) -> Outcome:
    fn = TRACKERS.get(test.get("type", ""))
    if fn is None:
        o = Outcome(notes=[f"test type {test.get('type')!r} is not supported; nothing computed"])
        o.checks.append(Check("test type supported", False, str(test.get("type"))))
        return o
    return fn(ctx, test, entry)


# ------------------------------------------------------------------ run


def compute(rules: list[RuleInternal], parcels: list[dict[str, Any]], mapping: dict[str, Any]
            ) -> dict[str, tuple[dict[str, Any], Outcome]]:
    ctx = Context(rules, parcels)
    return {t["test_id"]: (t, track(ctx, t, mapping["tests"].get(t["test_id"], {})))
            for t in starter.change_tests()}


def run(out_dir: Path | None = None) -> None:
    rules = lookup.load_rules()
    parcels = lookup.load_parcels()
    lookup._check_parcels(parcels)
    mapping, warnings = matcher.resolve(rules, write=out_dir is None)
    results = compute(rules, parcels, mapping)

    disclaimer = settings.load()["disclaimer"]
    changes = {tid: ChangeResult(affected_address_ids=o.affected, conflict_flag_address_ids=o.conflicts,
                                 notes=" | ".join(warnings + o.notes) + f" | {disclaimer}")
               for tid, (_, o) in results.items()}
    out = out_dir or settings.path("outputs")
    write_changes(changes, out_dir=out)
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dump_json({"generated_at": generated, "mapping_reviewed": bool(mapping.get("reviewed")),
               "tests": {tid: {"title": t.get("title"), "type": t.get("type"),
                               "expected_behavior": t.get("expected_behavior"),
                               "affected": len(o.affected), "conflicts": len(o.conflicts),
                               "checks": [c.__dict__ for c in o.checks], "notes": o.notes}
                         for tid, (t, o) in results.items()}},
              out / "changes_internal.json")

    lines = [f"Change tests T1-T5 (dev/change_tests.json). {disclaimer}", f"generated_at {generated}"]
    for tid, (t, o) in results.items():
        lines.append(f"\n{tid} {t.get('title')} [{t.get('type')}]: {len(o.affected)} affected, "
                     f"{len(o.conflicts)} conflict-flagged")
        lines.append(f"  expected: {t.get('expected_behavior')}")
        lines += ["  " + c.line() for c in o.checks]
    report = "\n".join(lines) + "\n"
    if out_dir is None:
        scores = settings.path("scores")
        scores.mkdir(parents=True, exist_ok=True)
        (scores / "changes_report.txt").write_text(report, encoding="utf-8")
    for tid, (_, o) in results.items():
        audit.log("changes", f"{tid}: {len(o.affected)} affected, {len(o.conflicts)} conflict-flagged",
                  checks={c.name: c.passed for c in o.checks})
    print(report, end="")
