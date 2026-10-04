"""Reasoning boundary per lookup row: what was checked and what could not be (golden rule 15).

Labels are plain names for the fact vocabulary in navigator/schema/facts.py (not law).
`checked` / `not_checked` are internal (lookups_internal.json, API, UI); they may carry
building values. The submission explanation never quotes building numbers.
"""
from __future__ import annotations

from navigator.engine.coverage import Coverage
from navigator.engine.facts import Facts
from navigator.schema import facts as vocab

LABELS = {
    "units": "unit count",
    "year_built": "year built",
    "certificate_of_occupancy_date": "certificate-of-occupancy date",
    "use_description": "land-use description",
    "owner_type": "owner type",
    "owner_occupied": "owner occupancy",
    "owner_units_owned": "number of units the owner holds",
    "separately_alienable": "whether the unit can be sold separately",
    "government_owned_or_subsidized": "public ownership or subsidy",
    "deed_restricted_affordable": "deed-restricted affordable status",
    "dormitory_or_institutional": "dormitory or institutional use",
    "shared_living_with_owner": "shared kitchen or bath with the owner",
    "tenancy_months": "length of the tenancy",
    "rent_amount": "rent amount",
    "tenant_income_source": "tenant's source of income",
    "unit_is_furnished": "whether the unit is furnished",
}

EXEMPTIONS_TEXT = "the rule's listed exemptions (text only, not all checkable)"
NO_PREDICATES = "coverage conditions beyond the jurisdiction (none extracted as checkable facts)"


def label(fact: str) -> str:
    return LABELS.get(fact, fact.replace("_", " "))


def join(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _fact_value(fact: str, f: Facts) -> str | None:
    if fact == "units":
        if f.units_min is None and f.units_max is None:
            return None
        if f.units_exact is not None:
            rng = str(f.units_exact)
        else:
            rng = f"{f.units_min if f.units_min is not None else '?'}-{f.units_max if f.units_max is not None else '?'}"
        return f"units {rng} (from {f.units_source})"
    if fact == "year_built" and f.year_built is not None:
        return f"year built {f.year_built}"
    if fact == "use_description" and f.use_description:
        return f"land-use description '{f.use_description}'"
    return None


def checked(rule_jurisdiction: str, level: str, f: Facts, cov: Coverage | None, status: str,
            as_of: str) -> list[str]:
    out = [f"state {f.state} (address data)"]
    if level == "city":
        out.append(f"city {f.city} (jurisdiction confidence {f.jurisdiction_confidence}"
                   + (f", {f.jurisdiction_source}" if f.jurisdiction_source else "") + ")")
    out.append(f"rule jurisdiction {rule_jurisdiction}")
    out.append(f"rule status on {as_of}: {status}")
    if cov is not None:
        for fact in cov.used:
            v = _fact_value(fact, f)
            if v:
                out.append(v)
        if cov.derived:
            out.extend(cov.derived)
    return out


def not_checked(rule_exemptions: str | None, f: Facts, cov: Coverage | None, *,
                city_rules_skipped: bool, extra: list[str] | None = None) -> list[str]:
    out: list[str] = []
    if cov is not None:
        if not cov.has_predicates:
            out.append(NO_PREDICATES)
        for fact in cov.missing:
            reason = "not in the data" if fact in vocab.NOT_AVAILABLE else "missing for this address"
            out.append(f"{label(fact)} ({reason})")
        for fact in cov.presumed:
            out.append(f"{label(fact)} (not in the data; exemption that depends on it not checked)")
        if "certificate_of_occupancy_date" in cov.referenced and "certificate_of_occupancy_date" not in cov.missing:
            out.append("certificate-of-occupancy date itself (only year built is known)")
    if rule_exemptions:
        out.append(EXEMPTIONS_TEXT)
    if city_rules_skipped:
        out.append("city rules (legal city not resolved to a city with rules in the corpus)")
    out.extend(extra or [])
    return list(dict.fromkeys(out))
