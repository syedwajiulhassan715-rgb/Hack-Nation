"""Deterministic one- or two-sentence explanations for lookups.json (no LLM).

Each explanation names the rule's citation, says what decided the result and what could
not be checked. It quotes no building numbers: the only numbers allowed are those in the
rule's own quoted_span, key_value or citation, the citations of rules it names, and
team_rule_ids (golden rule 7). Wording describes coverage only, never how to avoid a rule
(golden rule 11).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from navigator.engine.boundary import join, label
from navigator.engine.coverage import Coverage, DERIVED_CO
from navigator.schema.models import RuleInternal

NUMBER = re.compile(r"\d+(?:[.,:/-]\d+)*")
RULE_ID = re.compile(r"\br-\d+\b")
EVASION = re.compile(r"\b(avoid|get around|loophole|evade|circumvent|qualify for)\b", re.I)


@dataclass
class Decision:
    """What the engine decided for one row, as input to the template."""
    result: str                       # applies | unknown | superseded | not_yet_effective | pending
    coverage: Coverage
    reason: str = "coverage"          # coverage | jurisdiction | may_be_superseded | superseded
    other: RuleInternal | None = None # governing / possibly governing rule
    conflicts: list[tuple[RuleInternal, str]] = field(default_factory=list)
    city_unconfirmed: bool = False
    outside_cities: bool = False
    stricter_only: bool = False


def _verb(items: list[str]) -> str:
    return "is" if len(items) == 1 else "are"


def _main(rule: RuleInternal, d: Decision) -> str:
    head = f"{rule.citation} ({rule.jurisdiction})"
    cov = d.coverage
    if d.result == "pending":
        s = f"{head} is a pending bill or proposal, not law in force on the query date"
        if cov.value == "unknown" and cov.missing:
            s += f"; whether it would cover this building depends on {join([label(m) for m in cov.missing])}"
        return s
    if d.result == "not_yet_effective":
        s = f"{head} is enacted but not yet in effect on the query date"
        if cov.value == "unknown" and cov.missing:
            s += f"; whether it will cover this building depends on {join([label(m) for m in cov.missing])}"
        return s
    if d.result == "superseded" and d.other is not None:
        stricter = " stricter" if d.stricter_only else ""
        return (f"{head} covers this building, but {d.other.team_rule_id} ({d.other.citation}) governs here "
                f"because the state text defers to a{stricter} local rule that covers the unit")
    if d.result == "unknown":
        if d.reason == "jurisdiction":
            return (f"{head} may apply, but the address's legal city is not confirmed "
                    f"(the postal city may differ), so city rules are not decided")
        if d.reason == "may_be_superseded" and d.other is not None:
            return (f"{head} covers this building but may be superseded by {d.other.team_rule_id} "
                    f"({d.other.citation}), whose coverage of this unit could not be confirmed")
        missing = [label(m) for m in cov.missing] or ["coverage facts"]
        return (f"{head} may apply, but coverage could not be decided because the "
                f"{join(missing)} {_verb(missing)} not known")
    # applies
    if not cov.has_predicates:
        return f"{head} applies: it covers rental housing in {rule.jurisdiction} and no building condition was extracted to test"
    used = [label(u) for u in cov.used]
    if DERIVED_CO in cov.derived:
        used = [u for u in used if u != label("year_built")] + ["year built (as an estimate of the certificate-of-occupancy date)"]
    if used:
        return f"{head} applies: the building's {join(used)} {'meets' if len(used) == 1 else 'meet'} its coverage conditions"
    return f"{head} applies: its coverage conditions are met"


def _second(rule: RuleInternal, d: Decision) -> str:
    parts: list[str] = []
    nc: list[str] = []
    if d.coverage.presumed:
        nc.append("exemptions based on " + join([label(p) for p in d.coverage.presumed]))
    if rule.exemptions and d.result in ("applies", "superseded", "unknown"):
        nc.append("the other listed exemptions" if nc else "the listed exemptions")
    if d.stricter_only and d.result == "superseded":
        nc.append("whether the local limit is in fact stricter")
    if d.city_unconfirmed and d.reason != "jurisdiction":
        nc.append("the legal city (not confirmed)")
    if d.outside_cities:
        nc.append("city rules (address is outside the cities with rules in the corpus)")
    if nc:
        parts.append("Not checked: " + join(nc))
    if d.conflicts:
        first = d.conflicts[0][0]
        names = f"{first.team_rule_id} ({first.citation})"
        if len(d.conflicts) > 1:
            names += " and other rules in the same category"   # no counts: golden rule 7
        why = d.conflicts[0][1]
        parts.append(("flagged" if parts else "Flagged") + f" for review: possible conflict with {names}, {why}")
    if rule.conflict_flag:
        parts.append(("flagged" if parts else "Flagged") + " for review: the sources disagree about this rule")
    return "; ".join(parts)


def allowed_numbers_text(rule: RuleInternal, d: Decision) -> str:
    others = [d.other] if d.other is not None else []
    others += [o for o, _ in d.conflicts]
    return " ".join([rule.quoted_span, rule.key_value or "", rule.citation] + [o.citation for o in others])


def numbers_ok(text: str, allowed: str) -> bool:
    allowed_norm = " ".join(allowed.split())
    return all(tok in allowed_norm for tok in NUMBER.findall(RULE_ID.sub("", text)))


def explain(rule: RuleInternal, d: Decision) -> str:
    main = _main(rule, d)
    second = _second(rule, d)
    text = main + "." + (f" {second[0].upper()}{second[1:]}." if second else "")
    if not numbers_ok(text, allowed_numbers_text(rule, d)) or EVASION.search(text):
        # Fall back to the bare result with the citation (its numbers are always allowed).
        text = f"{rule.citation} ({rule.jurisdiction}): {d.result.replace('_', ' ')}."
    return text
