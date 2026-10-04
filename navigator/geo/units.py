"""Building unit counts: `units` column, else a range parsed from `use_description`.

Parsers live in config/unit_parsers.yaml (CONTRACT.md 7). They read the assessor data
sets' own coding of building size; they are not law and carry no thresholds. Anything a
parser does not clearly match gives no range (fail closed): the engine then evaluates a
unit predicate as UNKNOWN and names `units` as the missing fact.

Parser kinds:
- `range`: a regex; `min` / `max` name a capture group number (or a fixed int), with an
  optional `min_add` for strict "more than N" codes (">8-UNIT-APT" -> min 9).
- `none`: a regex for descriptions reviewed as carrying no unit count.
- `sum_tokens`: split on `split`, each segment must hold exactly one `token` match;
  the result is the sum (NJ MOD-IV "3B-7U/4B-24U-G" -> 31). A segment with no clear token
  or an `ambiguous` match gives no range for the whole description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from navigator import settings

CONFIG = settings.REPO_ROOT / "config" / "unit_parsers.yaml"


@dataclass(frozen=True)
class UnitRange:
    units_min: int | None
    units_max: int | None
    parser_id: str | None      # which parser decided (None: nothing matched)
    note: str                  # why, in plain words (logged, shown on review)

    @property
    def has_range(self) -> bool:
        return self.units_min is not None or self.units_max is not None


@dataclass(frozen=True)
class Parser:
    id: str
    kind: str
    pattern: re.Pattern[str]
    states: frozenset[str]
    spec: dict[str, Any]


@lru_cache(maxsize=4)
def load_parsers(path: Path = CONFIG) -> tuple[Parser, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    seen: set[str] = set()
    for p in data["parsers"]:
        if p["id"] in seen:
            raise ValueError(f"duplicate unit parser id {p['id']!r}")
        seen.add(p["id"])
        if p["kind"] not in ("range", "none", "sum_tokens"):
            raise ValueError(f"unit parser {p['id']}: unknown kind {p['kind']!r}")
        out.append(Parser(id=p["id"], kind=p["kind"], pattern=re.compile(p["pattern"]),
                          states=frozenset(p.get("states") or ()), spec=p))
    return tuple(out)


def _value(spec: Any, m: re.Match[str]) -> int | None:
    if spec is None:
        return None
    if isinstance(spec, dict):
        return int(m.group(spec["group"])) + int(spec.get("add", 0))
    return int(spec)


def _sum_tokens(p: Parser, desc: str) -> UnitRange:
    token = re.compile(p.spec["token"])
    ambiguous = re.compile(p.spec["ambiguous"]) if p.spec.get("ambiguous") else None
    if ambiguous and (hit := ambiguous.search(desc)):
        return UnitRange(None, None, p.id, f"ambiguous unit token {hit.group(0)!r}; no range")
    total = 0
    for seg in re.split(p.spec.get("split", "/"), desc):
        found = token.findall(seg)
        if len(found) != 1:
            return UnitRange(None, None, p.id,
                             f"segment {seg!r} has {len(found)} clear unit tokens; no range")
        total += int(found[0])
    return UnitRange(total, total, p.id, f"sum of unit tokens in {desc!r}")


def parse_use_description(desc: str | None, state: str | None = None) -> UnitRange:
    desc = (desc or "").strip()
    if not desc:
        return UnitRange(None, None, None, "no use_description")
    for p in load_parsers():
        if p.states and state not in p.states:
            continue
        m = p.pattern.search(desc)
        if not m:
            continue
        if p.kind == "none":
            return UnitRange(None, None, p.id, f"{desc!r} carries no unit count")
        if p.kind == "sum_tokens":
            return _sum_tokens(p, desc)
        lo, hi = _value(p.spec.get("min"), m), _value(p.spec.get("max"), m)
        if lo is not None and hi is not None and lo > hi:
            return UnitRange(None, None, p.id, f"inverted range in {desc!r}; no range")
        return UnitRange(lo, hi, p.id, f"range parsed from {desc!r}")
    return UnitRange(None, None, None, f"no parser matches {desc!r}; no range")


@dataclass(frozen=True)
class UnitFacts:
    units: int | None
    units_min: int | None
    units_max: int | None
    units_source: str | None   # "units" | "use_description" | None
    review_reasons: tuple[str, ...]
    note: str


def resolve_units(units_raw: str | None, use_description: str | None, state: str | None) -> UnitFacts:
    """`units` wins when present; the description range is only a cross-check then.

    If the two disagree, the range is widened to cover both values (fail closed: a unit
    predicate between them becomes UNKNOWN) and the row is flagged for review.
    """
    parsed = parse_use_description(use_description, state)
    raw = (units_raw or "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = None
        if n is None or n < 0:
            reasons = (f"units column value {raw!r} is not a whole number; ignored",)
            if parsed.has_range:
                return UnitFacts(None, parsed.units_min, parsed.units_max, "use_description",
                                 reasons, parsed.note)
            return UnitFacts(None, None, None, None, reasons, parsed.note)
        lo, hi = n, n
        reasons: tuple[str, ...] = ()
        outside = ((parsed.units_min is not None and n < parsed.units_min)
                   or (parsed.units_max is not None and n > parsed.units_max))
        if parsed.has_range and outside:
            # Hull of {n} and the parsed interval; a missing bound stays open (None).
            lo = min(n, parsed.units_min) if parsed.units_min is not None else None
            hi = max(n, parsed.units_max) if parsed.units_max is not None else None
            reasons = (f"units column ({n}) conflicts with use_description {use_description!r} "
                       f"({_fmt(parsed)}); range widened to "
                       f"{_fmt(UnitRange(lo, hi, None, ''))} so unit tests on it stay unknown",)
        return UnitFacts(n, lo, hi, "units", reasons, "units column")
    if parsed.has_range:
        return UnitFacts(None, parsed.units_min, parsed.units_max, "use_description", (), parsed.note)
    return UnitFacts(None, None, None, None, (), parsed.note)


def _fmt(r: UnitRange) -> str:
    if r.units_min is not None and r.units_max is not None:
        return f"{r.units_min}" if r.units_min == r.units_max else f"{r.units_min}-{r.units_max}"
    if r.units_min is not None:
        return f"{r.units_min} or more"
    if r.units_max is not None:
        return f"{r.units_max} or fewer"
    return "any number"
