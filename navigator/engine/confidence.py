"""Deterministic 0-1 confidence for a lookup row, with named reasons (BACKEND_PLAN.md 2.8).

Starts from the rule's own confidence (span match, date method, review reasons, set by
verify) and subtracts fixed penalties for what the engine had to estimate or skip.
No model self-ratings.
"""
from __future__ import annotations

from navigator.engine.coverage import Coverage, DERIVED_CO
from navigator.engine.facts import Facts

DEFAULT_RULE_CONFIDENCE = 0.9
FLOOR = 0.1
CONFLICT_CAP = 0.6

P_DERIVED_CO = 0.1
P_PRESUMED = 0.05
P_NO_PRED_EXEMPTIONS = 0.1
P_PRED_EXEMPTIONS = 0.05
P_UNITS_FROM_DESCRIPTION = 0.05
P_JURISDICTION_LOW = 0.2
P_JURISDICTION_MEDIUM = 0.05
P_STRICTER_NOT_COMPARED = 0.05
P_UNKNOWN_SUPERSEDER = 0.05


def score(rule_confidence: float | None, f: Facts, cov: Coverage | None, *, level: str,
          has_exemptions: bool, stricter_not_compared: bool = False,
          superseder_unconfirmed: bool = False, conflict: bool = False) -> tuple[float, list[str]]:
    base = DEFAULT_RULE_CONFIDENCE if rule_confidence is None else rule_confidence
    reasons = [f"rule record confidence {base:.2f}"]
    total = 0.0

    def pen(amount: float, why: str) -> None:
        nonlocal total
        total += amount
        reasons.append(f"-{amount:.2f} {why}")

    if cov is not None:
        if DERIVED_CO in cov.derived:
            pen(P_DERIVED_CO, "derived from year built")
        if cov.presumed:
            pen(P_PRESUMED, "exemptions depending on facts not in the data were not checked")
        if "units" in cov.used and f.units_source == "use_description":
            pen(P_UNITS_FROM_DESCRIPTION, "unit count parsed from the land-use description")
        if has_exemptions:
            if cov.has_predicates:
                pen(P_PRED_EXEMPTIONS, "listed exemptions only partly expressed as checkable facts")
            else:
                pen(P_NO_PRED_EXEMPTIONS, "listed exemptions not checked (no checkable predicates)")
    if level == "city" and not f.city_confirmed:
        pen(P_JURISDICTION_LOW, "legal city not confirmed")
    elif level == "city" and f.jurisdiction_confidence == "medium":
        pen(P_JURISDICTION_MEDIUM, "legal city from a non-exact geocoder match")
    if stricter_not_compared:
        pen(P_STRICTER_NOT_COMPARED, "whether the local limit is stricter was not compared")
    if superseder_unconfirmed:
        pen(P_UNKNOWN_SUPERSEDER, "coverage of the possibly governing local rule not confirmed")
    value = max(FLOOR, round(base - total, 2))
    if conflict and value > CONFLICT_CAP:
        value = CONFLICT_CAP
        reasons.append(f"capped at {CONFLICT_CAP:.2f}: conflict flagged for review")
    return value, reasons
