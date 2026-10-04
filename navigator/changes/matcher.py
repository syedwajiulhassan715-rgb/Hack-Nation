"""Map the change tests' organizer rule ids to our team_rule_ids (CONTRACT.md 5). Deterministic.

An organizer id has the form <PLACE>-<KIND>-<NUM>:
    PLACE  a state code (CA, NJ, MA) or a city prefix (HOB, JC). City prefixes are resolved
           against the manifest's city jurisdictions: the prefix must equal the city name's
           initials or start its name (case-insensitive), and match exactly one city.
    KIND   ALG -> algorithmic_rent_setting, RENT -> rent_increase_limits (the id scheme
           named in CONTRACT.md 5; an unknown kind matches nothing).
    NUM    digits -> an enacted law (in_force or not_yet_effective);
           P<digits> -> a pending or failed measure.
Every rule with that jurisdiction, category and status class is a match. Several ids in one
test that share a key (MA-ALG-P1, MA-ALG-P2) match the same pool: the pairing of each id to
one rule is not decidable from the id, so the test is matched as a set.

The result is written to config/test_rule_map.yaml for one human review. If that file says
`reviewed: true`, its mapping is used as-is and any difference from the matcher is reported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from navigator import settings, starter
from navigator.engine.status import status_hint
from navigator.schema.models import RuleInternal

KIND_CATEGORY = {"ALG": "algorithmic_rent_setting", "RENT": "rent_increase_limits"}
ID_RX = re.compile(r"^(?P<place>[A-Z]+)-(?P<kind>[A-Z]+)-(?P<num>P?\d+)$")
MAP_FILE = "test_rule_map.yaml"


@dataclass
class IdMatch:
    org_id: str
    jurisdiction: str | None = None       # resolved place
    level: str | None = None
    category: str | None = None
    status_class: str | None = None       # enacted | pending_or_failed
    team_rule_ids: list[str] = field(default_factory=list)
    problem: str | None = None            # why nothing matched (None when matched)


def manifest_jurisdictions() -> list[str]:
    return sorted({row["jurisdictions"].strip() for row in starter.manifest().values()
                   if row.get("jurisdictions", "").strip()})


def _city_for_prefix(prefix: str, states: list[str] | None, jurs: list[str]) -> tuple[str | None, str | None]:
    cities = [j for j in jurs if ", " in j and (not states or j.rsplit(", ", 1)[1] in states)]
    hits = []
    for j in cities:
        name = j.rsplit(", ", 1)[0]
        initials = "".join(w[0] for w in re.split(r"[\s\-]+", name) if w).upper()
        squashed = re.sub(r"[^A-Za-z]", "", name).upper()
        if prefix == initials or (len(prefix) >= 3 and squashed.startswith(prefix)):
            hits.append(j)
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, f"prefix {prefix} names no corpus city"
    return None, f"prefix {prefix} is ambiguous: {', '.join(hits)}"


def _status_class(rule: RuleInternal) -> str:
    return "pending_or_failed" if status_hint(rule) in ("bill_or_proposal", "failed") else "enacted"


def match_id(org_id: str, rules: list[RuleInternal], states: list[str] | None,
             jurs: list[str] | None = None) -> IdMatch:
    jurs = jurs if jurs is not None else manifest_jurisdictions()
    m = IdMatch(org_id)
    g = ID_RX.match(org_id)
    if not g:
        m.problem = "id does not follow <PLACE>-<KIND>-<NUM>"
        return m
    place, kind, num = g["place"], g["kind"], g["num"]
    m.category = KIND_CATEGORY.get(kind)
    if m.category is None:
        m.problem = f"unknown kind {kind}"
        return m
    m.status_class = "pending_or_failed" if num.startswith("P") else "enacted"
    if place in jurs and ", " not in place:
        m.jurisdiction, m.level = place, "state"
    else:
        m.jurisdiction, m.problem = _city_for_prefix(place, states, jurs)
        if m.jurisdiction is None:
            return m
        m.level = "city"
    m.team_rule_ids = sorted(r.team_rule_id for r in rules
                             if r.jurisdiction == m.jurisdiction and r.level == m.level
                             and r.category == m.category and _status_class(r) == m.status_class)
    if not m.team_rule_ids:
        kinds = "pending or failed" if m.status_class == "pending_or_failed" else "enacted"
        m.problem = f"no {kinds} {m.category} rule for {m.jurisdiction} was extracted from the corpus"
    return m


def match_test(test: dict[str, Any], rules: list[RuleInternal]) -> dict[str, list[IdMatch]]:
    """{'rule_ids': [...], 'conflict_with': [...]} -> one IdMatch per organizer id."""
    jurs = manifest_jurisdictions()
    states = test.get("states")
    return {key: [match_id(i, rules, states, jurs) for i in test.get(key, [])]
            for key in ("rule_ids", "conflict_with")}


def build_map(rules: list[RuleInternal]) -> dict[str, Any]:
    tests: dict[str, Any] = {}
    for t in starter.change_tests():
        entry: dict[str, Any] = {}
        for key, ms in match_test(t, rules).items():
            for m in ms:
                entry.setdefault(key, {})[m.org_id] = {
                    "jurisdiction": m.jurisdiction, "level": m.level, "category": m.category,
                    "status_class": m.status_class, "team_rule_ids": m.team_rule_ids,
                    **({"problem": m.problem} if m.problem else {})}
        tests[t["test_id"]] = entry
    return {"reviewed": False,
            "note": "Generated by navigator.changes.matcher. Set reviewed: true after one human "
                    "check; the reviewed mapping is then used as-is.",
            "tests": tests}


def map_path() -> Path:
    return settings.SETTINGS_FILE.parent / MAP_FILE


def resolve(rules: list[RuleInternal], write: bool = True) -> tuple[dict[str, Any], list[str]]:
    """(mapping to use, warnings). Writes the generated map unless a reviewed one exists."""
    generated = build_map(rules)
    path = map_path()
    warnings: list[str] = []
    if path.is_file():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if existing.get("reviewed"):
            if existing.get("tests") != generated["tests"]:
                warnings.append(f"{path} is human-reviewed and differs from the matcher's output; "
                                "the reviewed mapping is used")
            return existing, warnings
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(generated, sort_keys=False, allow_unicode=True), encoding="utf-8", newline=chr(10))
    return generated, warnings
