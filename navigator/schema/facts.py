"""Facts a coverage predicate may reference (BACKEND_PLAN.md 2.6).

This is a vocabulary, not law: it names building facts, never thresholds or dates.
`AVAILABLE` facts come from sample_addresses.csv (or are derived from it);
`NOT_AVAILABLE` facts are legitimate coverage conditions the data cannot answer, so the
engine evaluates them as UNKNOWN and names the missing fact. A predicate that uses any
other fact name is dropped by verify and the rule is marked needs_review.
"""
from __future__ import annotations

from typing import Any

AVAILABLE: dict[str, str] = {
    "units": "number of residential units in the building (integer)",
    "year_built": "year the building was built (integer)",
    "certificate_of_occupancy_date": "date of the first certificate of occupancy (YYYY-MM-DD); "
                                     "only estimated from year_built",
    "use_description": "assessor land-use description text",
}

NOT_AVAILABLE: dict[str, str] = {
    "owner_type": "kind of owner, e.g. natural person, corporation, REIT, public agency",
    "owner_occupied": "owner lives in the building (boolean)",
    "owner_units_owned": "number of units the owner holds in total (integer)",
    "separately_alienable": "unit can be sold separately, e.g. single-family home or condo (boolean)",
    "government_owned_or_subsidized": "publicly owned or rent-restricted affordable housing (boolean)",
    "deed_restricted_affordable": "deed-restricted affordable housing (boolean)",
    "dormitory_or_institutional": "dormitory, hospital, care facility, hotel or similar (boolean)",
    "shared_living_with_owner": "tenant shares bathroom or kitchen with the owner (boolean)",
    "tenancy_months": "how long the current tenant has occupied the unit (number)",
    "rent_amount": "current monthly rent (number)",
    "tenant_income_source": "tenant's lawful source of income",
    "unit_is_furnished": "unit is rented furnished (boolean)",
}

ALLOWED = {**AVAILABLE, **NOT_AVAILABLE}
OPS = {"<", "<=", ">", ">=", "==", "!=", "in", "not_in"}


def predicate_errors(node: Any, path: str = "$") -> list[str]:
    """Structural check of a predicate tree; returns problems, empty if valid.

    Forms: {"fact", "op", "value"} | {"all": [...]} | {"any": [...]} | {"not": {...}}.
    """
    if not isinstance(node, dict):
        return [f"{path}: not an object"]
    keys = set(node)
    if keys in ({"all"}, {"any"}):
        (k,) = keys
        items = node[k]
        if not isinstance(items, list) or not items:
            return [f"{path}.{k}: must be a non-empty list"]
        return [e for i, item in enumerate(items) for e in predicate_errors(item, f"{path}.{k}[{i}]")]
    if keys == {"not"}:
        return predicate_errors(node["not"], f"{path}.not")
    if keys == {"fact", "op", "value"}:
        errs = []
        if node["fact"] not in ALLOWED:
            errs.append(f"{path}: unknown fact {node['fact']!r}")
        if node["op"] not in OPS:
            errs.append(f"{path}: unknown op {node['op']!r}")
        if node["op"] in ("in", "not_in") and not isinstance(node["value"], list):
            errs.append(f"{path}: op {node['op']} needs a list value")
        return errs
    return [f"{path}: unexpected keys {sorted(keys)}"]


def describe() -> str:
    """Fact list as it appears in the extraction prompt."""
    lines = ["Facts the data has:"]
    lines += [f"- `{k}`: {v}" for k, v in AVAILABLE.items()]
    lines.append("Facts the data does NOT have (still use them when the law depends on them; "
                 "the answer will be 'unknown'):")
    lines += [f"- `{k}`: {v}" for k, v in NOT_AVAILABLE.items()]
    return "\n".join(lines)
