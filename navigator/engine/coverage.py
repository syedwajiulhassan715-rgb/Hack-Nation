"""Three-valued coverage of a rule's predicates against building facts (BACKEND_PLAN.md 2.6).

Predicates use the vocabulary in navigator/schema/facts.py:
`{fact, op, value}` leaves combined with `all` / `any` / `not` (Kleene logic).

Leaves:
- `units`: interval logic on [units_min, units_max] (CONTRACT.md 7).
- `year_built`, `use_description`: plain comparison; missing -> UNKNOWN.
- `certificate_of_occupancy_date` op D: estimated from year built against D's year
  (built after -> FALSE, before -> TRUE "derived from year built", same year or missing ->
  UNKNOWN). D always comes from the rule's own predicate.
- facts the data does not have (owner type, owner occupancy, ...) -> UNKNOWN.
- a date fact compared with `{"years_before_query_date": N}` (rolling conditions such as
  "certificate of occupancy within the previous N years"): D = query date minus N years,
  then the same year-based logic as above. With no query date -> UNKNOWN.

Exemptions that only facts we never have could trigger: if the strict evaluation is
UNKNOWN, a second pass presumes that such special statuses are absent ("not owner
occupied", "not a dormitory", "not subsidized", "owner type is not the named type"). If
that makes coverage TRUE, coverage is TRUE with those exemptions listed as *not checked*
(lower confidence). A positive condition on such a fact (e.g. "owner is a natural person")
is never presumed: it stays UNKNOWN. Facts in `vocab.NOT_PRESUMED` (local rent-control
status) are common, not special, and are never presumed either way. The presumption can
only turn UNKNOWN into TRUE, never into FALSE, so it never drops a rule (fail closed,
CLAUDE.md golden rule 2).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from navigator.engine.facts import Facts
from navigator.schema import facts as vocab

TRUE, FALSE, UNKNOWN = "true", "false", "unknown"

# Policy switch (documented in NOTES): set False for strict mode, where any condition on a
# fact the data does not have leaves the rule UNKNOWN.
PRESUME_UNCHECKABLE_EXEMPTIONS_ABSENT = True

DERIVED_CO = "certificate-of-occupancy date estimated from year built"


@dataclass
class Coverage:
    value: str                                    # TRUE | FALSE | UNKNOWN
    has_predicates: bool
    missing: list[str] = field(default_factory=list)    # facts that left it UNKNOWN
    used: list[str] = field(default_factory=list)       # known facts that decided it
    derived: list[str] = field(default_factory=list)    # reasons like DERIVED_CO
    presumed: list[str] = field(default_factory=list)   # unavailable facts presumed absent
    referenced: list[str] = field(default_factory=list) # every fact the predicates name


@dataclass
class _R:
    value: str
    missing: set[str] = field(default_factory=set)
    used: set[str] = field(default_factory=set)
    derived: set[str] = field(default_factory=set)
    presumed: set[str] = field(default_factory=set)


def _neg(v: str) -> str:
    return {TRUE: FALSE, FALSE: TRUE}.get(v, UNKNOWN)


def _tri(b: bool) -> str:
    return TRUE if b else FALSE


def _merge(value: str, parts: list[_R]) -> _R:
    out = _R(value)
    for p in parts:
        out.missing |= p.missing
        out.used |= p.used
        out.derived |= p.derived
        out.presumed |= p.presumed
    return out


# ------------------------------------------------------------------ leaves


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _interval(op: str, value: Any, lo: int | None, hi: int | None) -> str:
    """Compare an integer known to lie in [lo, hi] (None = unbounded) with value."""
    if op in ("in", "not_in"):
        vals = [v for v in (_num(x) for x in (value if isinstance(value, list) else [value])) if v is not None]
        if lo is not None and lo == hi:
            r = _tri(float(lo) in vals)
        elif not any((lo is None or v >= lo) and (hi is None or v <= hi) for v in vals):
            r = FALSE
        else:
            r = UNKNOWN
        return r if op == "in" else _neg(r)
    v = _num(value)
    if v is None:
        return UNKNOWN
    if op in ("==", "!="):
        if lo is not None and lo == hi:
            r = _tri(lo == v)
        elif (lo is not None and v < lo) or (hi is not None and v > hi):
            r = FALSE
        else:
            r = UNKNOWN
        return r if op == "==" else _neg(r)
    # x < v, x <= v, x > v, x >= v over every x in [lo, hi]
    def holds(x: float) -> bool:
        return {"<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v}[op]
    if op in ("<", "<="):
        if hi is not None and holds(hi):
            return TRUE
        if lo is not None and not holds(lo):
            return FALSE
        return UNKNOWN
    if op in (">", ">="):
        if lo is not None and holds(lo):
            return TRUE
        if hi is not None and not holds(hi):
            return FALSE
        return UNKNOWN
    return UNKNOWN


def _year_of(value: Any) -> int | None:
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def years_before(as_of: str, n: int) -> str:
    """ISO date n years before as_of (29 February -> 28 February)."""
    d = dt.date.fromisoformat(as_of)
    try:
        return d.replace(year=d.year - n).isoformat()
    except ValueError:
        return d.replace(year=d.year - n, day=28).isoformat()


def rolling_note(as_of: str, n: int) -> str:
    return f"rolling cutoff {years_before(as_of, n)} (query date {as_of} minus {n} years)"


def _date_vs_year(op: str, cutoff: int, year: int) -> str:
    """A date known only by its year, compared with a cutoff date in year `cutoff`:
    same year -> UNKNOWN, else decided."""
    if year == cutoff:
        return UNKNOWN
    before = year < cutoff
    return _tri(before) if op in ("<", "<=") else _tri(not before)


def _co_leaf(op: str, value: Any, f: Facts, as_of: str | None) -> _R:
    """certificate_of_occupancy_date <op> D, estimated from year built (guide 4.1)."""
    derived = {DERIVED_CO}
    n = vocab.relative_years(value)
    if n is not None:
        if as_of is None:
            return _R(UNKNOWN, missing={"certificate_of_occupancy_date"})
        value = years_before(as_of, n)
        derived.add(rolling_note(as_of, n))
    cutoff = _year_of(value)
    if f.year_built is None:
        return _R(UNKNOWN, missing={"certificate_of_occupancy_date", "year_built"})
    if cutoff is None or op not in vocab.ORDER_OPS:
        return _R(UNKNOWN, missing={"certificate_of_occupancy_date"})
    v = _date_vs_year(op, cutoff, f.year_built)
    if v == UNKNOWN:
        return _R(UNKNOWN, missing={"certificate_of_occupancy_date"}, used={"year_built"})
    return _R(v, used={"year_built"}, derived=derived)


def _year_built_leaf(op: str, value: Any, f: Facts, as_of: str | None) -> _R:
    n = vocab.relative_years(value)
    if n is not None and as_of is None:
        return _R(UNKNOWN, missing={"year_built"})
    if f.year_built is None:
        return _R(UNKNOWN, missing={"year_built"})
    if n is not None:
        # "built within the previous n years": compare the build year with the cutoff date
        cutoff = years_before(as_of, n)
        v = _date_vs_year(op, int(cutoff[:4]), f.year_built) if op in vocab.ORDER_OPS else UNKNOWN
        if v == UNKNOWN:
            return _R(UNKNOWN, missing={"year_built"}, used={"year_built"})
        return _R(v, used={"year_built"}, derived={rolling_note(as_of, n)})
    return _R(_interval(op, value, f.year_built, f.year_built), used={"year_built"})


def _plain(op: str, actual: Any, value: Any) -> str:
    if op in ("in", "not_in"):
        vals = value if isinstance(value, list) else [value]
        hit = any(_eq(actual, v) for v in vals)
        return _tri(hit if op == "in" else not hit)
    if op in ("==", "!="):
        return _tri(_eq(actual, value) == (op == "=="))
    a, v = _num(actual), _num(value)
    if a is None or v is None:
        return UNKNOWN
    return _tri({"<": a < v, "<=": a <= v, ">": a > v, ">=": a >= v}.get(op, False))


def _eq(a: Any, b: Any) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a).strip().casefold() == str(b).strip().casefold()


def _negative_form(op: str, value: Any) -> bool:
    """Leaf asserts the absence of a special status ('!= x', 'not_in', '== false')."""
    return op in ("!=", "not_in") or (op == "==" and value is False)


def _leaf(node: dict[str, Any], f: Facts, presume: bool, as_of: str | None) -> _R:
    fact, op, value = node["fact"], node["op"], node["value"]
    if fact == "units":
        if f.units_min is None and f.units_max is None:
            return _R(UNKNOWN, missing={"units"})
        v = _interval(op, value, f.units_min, f.units_max)
        return _R(v, used={"units"}) if v != UNKNOWN else _R(v, missing={"units"}, used={"units"})
    if fact == "year_built":
        return _year_built_leaf(op, value, f, as_of)
    if fact == "certificate_of_occupancy_date":
        return _co_leaf(op, value, f, as_of)
    if fact == "use_description":
        if f.use_description is None:
            return _R(UNKNOWN, missing={"use_description"})
        return _R(_plain(op, f.use_description, value), used={"use_description"})
    # Facts the data does not have (or unknown names, which verify should have dropped).
    if presume and fact in vocab.NOT_AVAILABLE and fact not in vocab.NOT_PRESUMED:
        return _R(_tri(_negative_form(op, value)), presumed={fact})
    return _R(UNKNOWN, missing={fact})


def _eval(node: dict[str, Any], f: Facts, presume: bool, as_of: str | None) -> _R:
    if "all" in node or "any" in node:
        is_all = "all" in node
        kids = [_eval(k, f, presume, as_of) for k in node["all" if is_all else "any"]]
        decisive = FALSE if is_all else TRUE
        hits = [k for k in kids if k.value == decisive]
        if hits:
            return _merge(decisive, hits)
        unknown = [k for k in kids if k.value == UNKNOWN]
        if unknown:
            return _merge(UNKNOWN, unknown)
        return _merge(_neg(decisive), kids)
    if "not" in node:
        r = _eval(node["not"], f, presume, as_of)
        r.value = _neg(r.value)
        return r
    return _leaf(node, f, presume, as_of)


def _facts_named(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    if "fact" in node:
        return {node["fact"]}
    out: set[str] = set()
    for k in ("all", "any"):
        for item in node.get(k) or []:
            out |= _facts_named(item)
    if "not" in node:
        out |= _facts_named(node["not"])
    return out


def evaluate(predicates: dict[str, Any] | None, f: Facts, as_of: str | None = None) -> Coverage:
    """Coverage of one rule at one building on `as_of` (YYYY-MM-DD). No predicates -> TRUE
    (covers the jurisdiction). Without `as_of`, conditions relative to the query date are
    UNKNOWN."""
    if not predicates:
        return Coverage(TRUE, has_predicates=False)
    referenced = sorted(_facts_named(predicates))
    if vocab.predicate_errors(predicates):
        # Malformed predicates never decide anything (verify should have dropped them).
        return Coverage(UNKNOWN, True, missing=referenced, referenced=referenced)
    strict = _eval(predicates, f, False, as_of)
    if strict.value == UNKNOWN and PRESUME_UNCHECKABLE_EXEMPTIONS_ABSENT:
        lenient = _eval(predicates, f, True, as_of)
        if lenient.value == TRUE:
            return Coverage(TRUE, True, missing=[], used=sorted(lenient.used),
                            derived=sorted(lenient.derived), presumed=sorted(lenient.presumed),
                            referenced=referenced)
        # Still undecided: name only the facts that block it (a positive condition on a
        # fact we lack, or a missing building fact), not every exemption fact.
        blocking = lenient.missing | lenient.presumed
        if blocking:
            return Coverage(UNKNOWN, True, missing=sorted(blocking), used=sorted(strict.used),
                            derived=sorted(strict.derived), referenced=referenced)
    return Coverage(strict.value, True,
                    missing=sorted(strict.missing) if strict.value == UNKNOWN else [],
                    used=sorted(strict.used), derived=sorted(strict.derived), referenced=referenced)
