"""Precedence between state and city rules, driven only by extracted text (BACKEND_PLAN.md 2.8).

The texts read are each rule's `interaction`, `provenance[*].interaction_text` and (for
the "local rent control" carve-out) `exemptions`. The patterns below are generic legal
phrasing ("the local ordinance shall apply", "not be subject to both", "municipality shall
be prohibited from enacting"); they hold no rule ids, citations, cities, dates or numbers.

Relation kinds (one per matching text):
- `yields_to_local`: a state rule's text says a covering local rule governs instead.
  At an address where a same-category city rule covers the unit, the state rule is
  `superseded`. If the text only defers to *stricter* local control ("... less than ..."),
  the comparison of the two limits is not checked and is listed as such.
- `conflict`: the text names a state/local interaction that cannot be resolved from the
  text alone (a conditional deferral, a preemption clause, a "state law preempts this
  policy" clause). Both rules are kept and the lookup rows get `conflict_flag` with a reason.

Targets are city rules in the same state and category (for a state rule), or state rules
of the city's state in the same category (for a city rule). When the text of a state
rule comes from a city's own document (manifest jurisdiction "City, ST"), its targets are
limited to that city.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from navigator.schema.models import RuleInternal

_F = re.I | re.S
_LOCAL = r"(?:local|city|town|county|municipal\w*)"
# one character inside a clause: anything but a sentence break ("12.5" stays one clause)
_CLAUSE = r"(?:[^.;]|\.(?=\d))"

# State text deferring to a local rule that covers the unit.
DEFERS_TO_LOCAL = [
    re.compile(rf"\blocal (?:ordinance|law|rule)s?\b{_CLAUSE}{{0,200}}?\bshall (?:apply|govern|control|prevail)\b", _F),
    re.compile(rf"\bnot be subject to both\b{_CLAUSE}{{0,80}}?\b{_LOCAL}\b", _F),
    re.compile(rf"\b(?:already )?subject to (?:the |a |an )?{_LOCAL}\W{{0,2}}s?\b{_CLAUSE}{{0,60}}?"
               rf"\b(?:ordinance|rent control|rent stabilization|(?-i:[A-Z]{{2,5}}))\b", _F),
    re.compile(rf"\b(?:subject to|under)\b{_CLAUSE}{{0,20}}?\b(?:{_LOCAL}\s+)?(?:rent|price) control\b", _F),
]
# Deference only to stricter local control: comparing the limits is not checked.
STRICTER_ONLY = re.compile(rf"\b(?:rent|price) control\b{_CLAUSE}{{0,300}}?\bless than\b", _F)
# Conditions that make a deferral unresolvable from text (dates of adoption, durations, ...).
CONDITIONAL = re.compile(
    r"\b(?:adopted|enacted|in effect)\s+(?:on or\s+)?(?:before|after|prior to|since)\b"
    r"|\bfor (?:a period of|less than|more than|at least)\b"
    r"|\bwhere\b[^.;]{0,120}\bconflicts?\b", re.I)

# State text overriding or barring local rules; local text yielding to state law.
STATE_OVER_LOCAL = [
    re.compile(rf"\bmunicipalit(?:y|ies)\b{_CLAUSE}{{0,60}}?\bprohibited from (?:enacting|adopting|enforcing)\b", _F),
    re.compile(rf"\bno (?:city|town|municipality|county)\b{_CLAUSE}{{0,40}}?\bmay (?:enact|adopt|maintain|enforce)\b", _F),
    re.compile(rf"\bexempt from (?:any |all )?{_LOCAL}\b", _F),
    re.compile(rf"\b(?:state|federal)(?: or (?:state|federal))? laws?\b{_CLAUSE}{{0,60}}?\bpreempts?\b", _F),
    re.compile(rf"\bpreempt\w*\b{_CLAUSE}{{0,60}}?\b(?:{_LOCAL}|ordinances?)\b", _F),
    re.compile(rf"\bgoverned by\b{_CLAUSE}{{0,160}}?\band not by\b{_CLAUSE}{{0,60}}?\b(?:ordinance|{_LOCAL}|chapter)\b", _F),
]


@dataclass(frozen=True)
class Relation:
    source: str              # team_rule_id whose text states the interaction
    kind: str                # "yields_to_local" | "conflict"
    targets: tuple[str, ...]
    text: str                # verbatim extracted sentence that triggered it
    stricter_only: bool = False


def _state_of(jurisdiction: str) -> str:
    return jurisdiction.rsplit(", ", 1)[-1]


def _texts(rule: RuleInternal) -> list[tuple[str, str | None]]:
    """(text, source_doc_id) pairs to read, deduplicated, in a stable order."""
    out: list[tuple[str, str | None]] = []
    if rule.interaction:
        out.append((rule.interaction, rule.source_doc_id))
    for p in rule.provenance:
        if p.get("interaction_text"):
            out.append((str(p["interaction_text"]), p.get("source_doc_id")))
    if rule.exemptions:
        out.append((rule.exemptions, rule.source_doc_id))
    seen, uniq = set(), []
    for t, d in out:
        key = " ".join(t.split())
        if key and key not in seen:
            seen.add(key)
            uniq.append((key, d))
    return uniq


def _doc_jurisdictions() -> dict[str, str]:
    try:
        from navigator import starter
        return {k: v.get("jurisdictions") or "" for k, v in starter.manifest().items()}
    except (OSError, KeyError):
        return {}


def relations(rules: list[RuleInternal], doc_jurisdictions: dict[str, str] | None = None) -> list[Relation]:
    """All text-driven interactions among `rules` (deterministic order)."""
    docs = _doc_jurisdictions() if doc_jurisdictions is None else doc_jurisdictions
    live = [r for r in rules if r.status != "failed"]
    out: list[Relation] = []
    for rule in sorted(live, key=lambda r: r.team_rule_id):
        state = _state_of(rule.jurisdiction)
        for text, doc_id in _texts(rule):
            is_exemption = text == " ".join((rule.exemptions or "").split())
            # Only a state rule can defer to local rules; a city text naming local rules
            # is about its own city.
            defers = rule.level == "state" and any(p.search(text) for p in DEFERS_TO_LOCAL)
            over = any(p.search(text) for p in STATE_OVER_LOCAL)
            if is_exemption:
                # Exemption lists are only read for deferral to local rent/price control.
                defers = defers and bool(STRICTER_ONLY.search(text))
                over = False
            if not (defers or over):
                continue
            if rule.level == "state":
                doc_jur = docs.get(doc_id or "", "")
                scope = doc_jur if ", " in doc_jur and _state_of(doc_jur) == state else None
                targets = tuple(sorted(
                    r.team_rule_id for r in live
                    if r.level == "city" and r.category == rule.category and _state_of(r.jurisdiction) == state
                    and (scope is None or r.jurisdiction == scope)))
            else:
                targets = tuple(sorted(
                    r.team_rule_id for r in live
                    if r.level == "state" and r.category == rule.category and r.jurisdiction == state))
            if not targets:
                continue
            resolvable = rule.level == "state" and defers and not over and not CONDITIONAL.search(text)
            kind = "yields_to_local" if resolvable else "conflict"
            out.append(Relation(rule.team_rule_id, kind, targets, text,
                                stricter_only=bool(resolvable and STRICTER_ONLY.search(text))))
    return out


def link(rules: list[RuleInternal], doc_jurisdictions: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """team_rule_id -> {"overrides": [...], "interaction": str | None} for rules.json.

    `overrides` lists the rules this one supersedes or yields to (CONTRACT.md 2), and
    `interaction` says the direction in words, quoting the source text. Every rule id is
    present; rules without an interaction get `{"overrides": [], "interaction": None}`.
    """
    out: dict[str, dict[str, Any]] = {r.team_rule_id: {"overrides": set(), "interaction": []} for r in rules}
    for rel in relations(rules, doc_jurisdictions):
        ids = ", ".join(rel.targets)
        quote = f'(source text: "{rel.text}")'
        src = out[rel.source]
        src["overrides"].update(rel.targets)
        if rel.kind == "yields_to_local":
            cond = " that is stricter" if rel.stricter_only else ""
            src["interaction"].append(f"Yields to {ids} where that local rule{cond} covers the unit {quote}.")
            for t in rel.targets:
                out[t]["overrides"].add(rel.source)
                out[t]["interaction"].append(f"Supersedes {rel.source} where this rule covers the unit.")
        else:
            src["interaction"].append(
                f"Possible conflict with {ids}; not resolved from the text, flagged for review {quote}.")
            for t in rel.targets:
                out[t]["overrides"].add(rel.source)
                out[t]["interaction"].append(
                    f"Possible conflict with {rel.source}; not resolved from the text, flagged for review.")
    return {
        rid: {"overrides": sorted(v["overrides"]),
              "interaction": " ".join(dict.fromkeys(v["interaction"])) or None}
        for rid, v in sorted(out.items())
    }
